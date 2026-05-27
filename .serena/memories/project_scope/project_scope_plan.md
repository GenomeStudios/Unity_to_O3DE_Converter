---
name: project-scope-plan
description: Design + locked decisions for F-2 — every project carries a single Unity scope_root (assets walking root). Per-stage source_path fields fall back to scope_root when blank.
metadata:
  type: project
---

# F-2 Project Scope Path — Plan

## Goal

Each Conversion Project has a single **`scope_root`** field — an
absolute path to the Unity assets walking root. All per-stage source
walking falls back to this when the stage's own `source_path` is
blank. Per-stage `source_path` becomes an **optional override**, not
a requirement.

Practical effect: a new project is configured by picking scope_root
once; all converters automatically scope to it. The stage source
fields are reserved for the case where you want a narrower walk
(e.g. only the `Materials/` subfolder for a terrain-only pass).

The testbed is [TestObjects/TestProject.u2oproj.json](TestObjects/TestProject.u2oproj.json)
pointing at scope_root = [TestObjects/TestOffice/](TestObjects/TestOffice/).

## Resolved Decisions (Q&A history)

**Q1 — Should scope_root be a Unity project root (with an Assets/
subfolder) or the assets root directly?**
A: **Assets root directly (walking root).** No magic `<scope_root>/Assets`
resolution. The testbed `TestObjects/TestOffice/` already contains
`Materials/Meshes/Prefabs/Textures` at top level; the converter walks
scope_root with rglob exactly as it walks the legacy `asset_processor.
source_path` today. If a user has a full Unity project root, they pick
`<root>/Assets` explicitly.

**Q2 — Single or multiple scope roots per project?**
A: **Single.** Multi-root deferred to v2 — keeps file scrubbing
tractable and matches typical conversion projects (one Unity asset
set per output).

**Q3 — How does per-stage `source_path` interact with `scope_root`?**
A: **Optional override.** Blank source_path → use scope_root. Non-blank
→ use the override. Stages stay independently configurable for the
"convert only this subfolder" case.

**Q4 — Project file missing the scope_root key (existing projects)?**
A: **Defaults to None (empty string in JSON).** No migration step
needed. Existing projects keep their per-stage source_paths as before;
when the user opens the project and sets scope_root, future blank
overrides start using it.

**Q5 — Where does the scope_root field live in the UI?**
A: **In the Project header on the Mission Command tab**, between
Scope and Created/Modified. Each converter tab gets a small **info
label** under its source_path field showing the effective path when
the override is blank: `→ using scope root: <path>`.

**Q6 — Should output_path also get a project-level fallback?**
A: **No, deferred.** Outputs are more often stage-specific (levels go
to one folder, prefab .prefab files go to another). Revisit if user
feedback says otherwise.

**Q7 — Should setting scope_root reset `pipeline_status`?**
A: **No.** `last_run` is historical; resetting it would lose
information. If the new scope_root genuinely invalidates an earlier
run, F-9 (output-state patching) is the right place to handle it.

**Q8 — Should setting scope_root auto-fill any per-stage source_path?**
A: **No.** The whole point of fallback semantics is that blank stages
*automatically* use scope_root without copying values around. If we
auto-fill, the user can't tell from the UI which fields are real
overrides vs. inherited values.

## Design

### Project file shape (`schema_version` stays at 1)

```json
{
  "schema_version": 1,
  "name": "TestProject",
  "scope": "asset_set",
  "scope_root": "D:/OffLocalDev/Unity_to_O3DE_Converter/TestObjects/TestOffice",
  "notes": "",
  ...
}
```

`scope_root` is a top-level optional string. Empty string == None
(no scope set). `Project.from_json` handles both missing key and
empty-string forms.

### `Project` dataclass changes

```python
@dataclass
class Project:
    ...existing fields...
    scope_root: Optional[Path] = None
    ...

    def set_scope_root(self, path: Optional[Path]) -> None: ...

    def effective_source(self, stage_key: str) -> str:
        """Resolve the walking root for a given stage:
          - stage's override source_path if non-empty,
          - else scope_root if set,
          - else "" (caller is responsible for the empty case)."""
        stage = self.stage_settings(stage_key)
        override = (stage.get("source_path") or "").strip()
        if override:
            return override
        return str(self.scope_root) if self.scope_root else ""
```

`to_json` writes `scope_root` as a string (or empty string if None).
`from_json` parses it: empty/missing → None, non-empty → Path(...).

### Mission Command header — new row

Between "Scope:" and "Created:" rows:

```
Scope:       [Asset Set ▾]
Source Root: [<line edit>                              ] [Browse…]
Created:     2026-05-26T...
```

- QLineEdit + Browse button row. Browse opens
  `QFileDialog.getExistingDirectory` starting at the current value.
- editingFinished + browse-pick both call `_on_scope_root_changed`,
  which writes via `Project.set_scope_root` + `pm.commit_metadata()`.
- An info label below the row shows the effective path resolution
  status: "(unset — stage source paths will be required)" when blank,
  otherwise just the path itself.

### Per-stage tab — effective-source info label

Each converter tab (Prefab / Scene / Terrain) gets a small label
underneath its source-path field:

```
Unity Assets Folder
[                                          ] [Browse…]
→ using scope root: D:/.../TestOffice
```

The label text comes from `project.effective_source(STAGE_KEY)` AND
the override state:

- Override blank + scope_root set → `→ using scope root: <path>`
  (cyan-ish color)
- Override blank + scope_root unset → `(no source set — fill this
  field or set a project scope root)` (warning yellow)
- Override non-blank → label hidden (the field itself is the source)

The label refreshes on `apply_project(project)` and on the override
field's `editingFinished`.

### Worker call-site change

Today's `_start_processing` reads `self._source_edit.text().strip()`
and passes it to `_do_processing`. New flow: read
`project.effective_source(STAGE_KEY)`. If empty, the existing
"please select both source and output folders" error still fires.

This means workers now route the *effective* path even if the UI
field is blank — the central behaviour switch.

### `SceneConverterTab` — special case

Scene converter's "source" today is a `scene_path` (a single .unity
file), not a directory. F-3 will replace that with a multi-scene
checklist scrubbed from scope_root. For F-2: leave the scene_path
field alone, no info label, no effective-source change. The fallback
contract only applies to the `source_path` / `source_dir` style
fields (asset_processor + terrain_processor for now).

## Implementation Plan

### I.1 — `Project.scope_root` field + `effective_source` accessor
**Done when:**
- `Project` dataclass has `scope_root: Optional[Path] = None`.
- `from_json` reads it (missing/empty → None, string → Path).
- `to_json` writes it as a string ("" when None).
- `Project.set_scope_root(path)` mutator marks dirty.
- `Project.effective_source(stage_key)` returns override-or-scope-or-empty.
- Project manager smoke test grows assertions for scope_root
  round-trip and effective_source resolution; still passes.

### I.2 — Mission Command "Source Root" row
**Done when:**
- ProjectTab header form has the new row between Scope and Created.
- Browse button works, picker pre-fills with current value.
- Editing or browsing fires `_on_scope_root_changed`, calls
  `project.set_scope_root` + `pm.commit_metadata()`.
- Apply_project sets the field text from `project.scope_root`.
- Empty state info label visible when blank.

### I.3 — Per-stage tab effective-source info labels + worker effective_source read
**Done when:**
- `PrefabProcessorTab` shows the info label, refreshes on
  apply_project + source override editingFinished.
- `TerrainTab` same.
- `SceneConverterTab` left as-is (Q5 design note).
- Both prefab + terrain `_start_*` methods read
  `project.effective_source(STAGE_KEY)` instead of UI field directly.
- The empty-source error still fires if both override AND scope_root
  are blank.

### I.4 — Verification with TestProject.u2oproj.json

Manual proofs:

| ID | Proof |
|---|---|
| T-1 | Open TestProject in app → Source Root field empty + info label "(unset…)". Browse to TestObjects/TestOffice → field populates, info label clears. Close + reopen app → field still populated from JSON. |
| T-2 | Leave prefab tab source field blank → info label reads "→ using scope root: …/TestOffice". Click Process → worker runs against TestOffice. |
| T-3 | Override prefab tab source field to TestObjects/TestOffice/Prefabs → info label hides, worker walks only that subfolder. |
| T-4 | Clear scope_root + leave override blank → click Process → original "please select both source and output folders" error fires. |
| T-5 | Open Legacy project (no scope_root key in its JSON) → Source Root field empty, tabs work as before with their existing per-stage source_paths. |

## Out of scope (deliberately, deferred to later F's)

- **Scope walking / file inventory.** Building a ScopeIndex that
  walks scope_root and caches scene/prefab/material file lists is
  F-3 + F-4 work. F-2 only delivers the field + the fallback.
- **Per-stage output_path fallback.** Outputs stay stage-specific
  (Q6).
- **Auto-fill from scope_root into stage source fields.** Q8 — would
  hide the override-vs-fallback distinction.
- **Multi-scope projects.** Q2 — one root per project for v1.
- **SceneConverterTab integration.** Scene picker shifts to a
  scrubbed checklist in F-3, so F-2 leaves it alone.
