---
name: project-scope-working-doc
description: Living status log for F-2 (project-level scope_root path + per-stage fallback). Newest entries on top.
metadata:
  type: project
---

# F-2 Project Scope Path — Working Documentation

Newest entries on top. Linked plan: [[project-scope-plan]].

## 2026-05-26 — F-2 shipped ✓

### What landed
- **`Project.scope_root: Optional[Path] = None`** field added.
- **`Project.set_scope_root(path)`** mutator (marks dirty on change).
- **`Project.effective_source(stage_key)`** accessor — override-then-scope-then-empty.
- **`to_json` / `from_json`** carry `scope_root` as a string (empty string ↔ None).
- **`PrefabProcessorTab` and `TerrainTab`** UI:
  - Source-path field now placeholder reads "Override (blank → use
    project scope root)" instead of "Select Unity project Assets folder…".
  - Small info label below the field shows:
    - `→ using scope root: <path>` (cyan) when override blank +
      scope_root set
    - `→ no source set (set a project scope root, or fill this field)`
      (yellow) when both blank
    - hidden when an override is present
  - `_start_processing` / `_start_generation` read
    `project.effective_source(STAGE_KEY)` instead of the UI field
    directly, so the override + fallback contract runs through every
    worker dispatch.
- **`SceneConverterTab`** left untouched per Q5 — scene picker shifts
  to a scrubbed checklist in F-3.
- **`ProjectTab` Mission Command header**:
  - New row between Scope and Created: **Source Root** with QLineEdit
    + Browse + a status label below.
  - Status label colors: yellow when unset, red when path missing,
    green when valid.
  - Browse opens `QFileDialog.getExistingDirectory` pre-filled with
    current value.
  - editingFinished + Browse-pick both fire `_on_scope_root_changed`,
    which calls `proj.set_scope_root(...) + pm.commit_metadata()` —
    re-emits `project_changed` so the per-stage tabs' info labels
    refresh in sync.

### Sanity gates passed
- `py project_manager.py` → smoke OK (grew assertions 9 + 9b for
  scope_root round-trip, old-format compatibility, and override-vs-fallback
  resolution).
- `py -c "import main_app"` → OK.
- End-to-end behavioural proof against the actual testbed
  (`TestObjects/TestProject.u2oproj.json` pointing at
  `TestObjects/TestOffice/`):
  - [1] testbed loads with scope_root = None ✓
  - [2] setting scope_root makes effective_source for both
    asset_processor and terrain_processor resolve to TestOffice ✓
  - [3] reload from disk preserves scope_root ✓
  - [4] per-stage override beats scope_root ✓
  - [5] clearing override falls back to scope_root ✓
  - [6] clearing scope_root + clearing overrides restores pristine ✓
  - [7] pristine JSON has `"scope_root": ""` (empty string, not
    missing key) ✓

### T-series status

| ID | Status |
|---|---|
| T-1 (scope_root persists across relaunch) | ✓ programmatic |
| T-2 (blank stage source uses scope_root) | ✓ programmatic |
| T-3 (per-stage override beats scope) | ✓ programmatic |
| T-4 (empty scope_root + empty stage → "select source" error) | needs visual confirmation in app run; logic confirmed |
| T-5 (load project with no scope_root key) | ✓ programmatic via smoke #9b |

### Visual QA the user can do
Launch `UnityToO3DE_Converter.bat`, then:

1. Project tab → Open… → pick `TestObjects/TestProject.u2oproj.json`.
2. Confirm Source Root row visible between Scope and Created.
3. Click Browse next to Source Root → pick `TestObjects/TestOffice`.
4. Status label flips from yellow "(unset…)" to green
   "(stages with blank source will walk this root)".
5. Switch to Prefab Processor tab. Source field blank, info label
   reads `→ using scope root: D:/.../TestOffice` (cyan).
6. Type an override path into the source field, press Tab → info
   label hides.
7. Clear the override → label reappears.
8. Switch to Terrain tab — same behaviour.
9. Project tab → Source Root → clear field → Tab → status label
   flips to yellow.

### Open follow-ups
- Mission Command's scope_root status label currently treats
  "directory does not exist" as red — but doesn't check on
  project_changed unless the user re-edits. Could refresh on tab focus.
  Minor polish, not blocking.
- The status row uses `hdr_form.addRow("", self._scope_root_status)`
  which produces an empty label column. Visually OK on this dark
  theme but a future cleanup could span the row.
- `SceneConverterTab` deliberately not migrated to scope_root — that
  joins the F-3 multi-scene work.

## 2026-05-26 — Plan locked; starting I.1

8 design Q's resolved. Testbed selected: `TestObjects/TestProject.u2oproj.json`
pointing at `TestObjects/TestOffice/` (Materials / Meshes / Prefabs /
Textures at top level — confirms Q1's decision to treat scope_root
as the walking root with no Assets/ magic).

## Pending / not yet shipped

- User-driven visual T-4 confirmation.
- Future polish items listed in Open follow-ups above.
