---
name: prefab-marking-plan
description: Design + locked decisions for F-4 — scrubbed prefab checklist for Stage 1, plus cross-stage Mesh / Material stubs that feed off Stage 1 outputs.
metadata:
  type: project
---

# F-4 Prefab Marking — Plan

## Goal

Replace Stage 1's "process every `.prefab` under source" model with a
**scrubbed checklist**, so the user picks exactly which prefabs to
convert. Add cross-stage display so:

- Scene Converter knows how many prefabs are available from the project
  for reference resolution (and stops needing the `prefab_dirs` UI).
- Mesh / Material tabs stub in with read-only inventories sourced from
  the prefab-processor outputs.
- Per-level post-run breakdowns surface on the Scene tab (and per-
  prefab on the Prefab tab) so the user can audit what got produced.

## Resolved Decisions (Q&A)

**Q1 — How are prefabs scrubbed?**
A: `scrub_scope_for(effective_source, "*.prefab")` — mirrors F-3's
scene scrubbing. Relative paths under the project's effective source.

**Q2 — Default selection state?**
A: None checked. Explicit user consent, same as F-3 scenes.

**Q3 — Persistence shape?**
A: `stages.asset_processor.selected_prefabs: list[str]` (sorted
relative paths). Old projects without the key get the F-4 default via
a per-stage deep-merge in `Project.from_json` — schema migration
without a version bump.

**Q4 — Does Stage 2 still use `prefab_dirs`?**
A: **No, drop the UI.** Stage 2's prefab database is now built from
`<project.stages.asset_processor.output_path>/Prefabs/` plus any
legacy `prefab_dirs` still in the JSON for backwards compat. The user
no longer manages this list manually. If the project has no Prefab
Processor output yet, Stage 2 warns the user before letting them run.

**Q5 — Cross-stage display on Prefab tab?**
A: One info line above the output section: "X prefab(s) selected ·
Last run produced N meshes, M materials". Materials and mesh counts
pull from `project.outputs.asset_processor.{meshes, materials}`.

**Q6 — Cross-stage display on Scene tab?**
A: A new section "Project Prefab Inventory" above the log: shows the
count of prefabs available to resolve references against. Different
messages for the three states (no project / selections-but-no-run /
run-completed).

**Q7 — Per-level post-run breakdown on Scene tab?**
A: A "Last Run Details" section at the bottom (hidden until the run
populates `project.outputs.scene_converter.scenes`). Two rows per
level: header with name → output_path + timestamp, detail line with
"X entities · Y prefab refs · Z blanks · W missing".

**Q8 — Per-prefab breakdown on Prefab tab?**
A: Same "Last Run Details" pattern. One line per converted prefab:
"  • Prefabs/Foo.prefab  ·  N entities, M material slot(s)". Capped
at 20 entries with a "… and N more" footer.

**Q9 — Mesh and Material tabs?**
A: **Stubs.** Both share an `_InventoryStubTab` base that renders:
- Intro paragraph explaining the dependency on the prefab run.
- Inventory list pulled from `project.outputs.asset_processor.<key>`.
- Last-run details capped at 20 entries.
- Disabled "Process (F-5)" / "Process (F-6)" action button with a
  tooltip explaining the future feature.

The actual mesh-override and shader-mapping pipelines are F-5 / F-6
respectively. These tabs surface the data Stage 1 already produces so
the cross-stage usage is visible immediately.

**Q10 — Tab order with Mesh + Material added?**
A: Dashboard → Scene → Prefab → **Mesh → Material** → Terrain →
Config(hidden). 5 visible converter tabs.

**Q11 — Test-close prompt suppression?**
A: `MainWindow.SUPPRESS_CLOSE_PROMPT: bool = False` class attribute.
Verification scripts set `main_app.MainWindow.SUPPRESS_CLOSE_PROMPT =
True` before constructing the window; `closeEvent` checks the flag
and accepts immediately, bypassing the unsaved-project prompt.
Environment variable `U2O_SKIP_CLOSE_PROMPT` works as an alternative.

## Design

### Schema additions

```json
"stages": {
  "asset_processor": {
    "source_path":      "",
    "selected_prefabs": [],   // F-4 — relative paths under effective_source
    "output_path":      ""
  }
}
```

`Project.from_json` does a **per-stage deep merge** so newer schema
fields stay populated when an older project file is loaded. The
shallow `dict.update()` we had before would clobber `selected_prefabs`
if the saved JSON didn't include it.

### Input hash for asset_processor

```
{ scope_root, effective_source, output_path,
  selected_prefabs: [...sorted...],
  files: { rel_path: mtime, ... }   # only the selected ones }
```

Changing the selection changes the hash, which flips the dashboard
card from `synchronized` → `unsynchronized`. Same mechanism F-3
already uses for scenes.

### Readiness chain

For `asset_processor`:
1. No source → `unset` / "No source set"
2. Source has no .prefab files → `partial` / "Source has no .prefab files"
3. No prefabs selected → `partial` / "No prefabs selected"
4. No output → `partial` / "No destination set"
5. Ready (all met, never run) → `ready` / "Ready"
6. Last run → `ok` / `warn` with the post-run summary

### Worker filter

`_start_processing` resolves the selected relative paths to absolute
files, prompts on missing ones, and passes only the resolved subset
into `_do_processing` (which itself no longer rglobs the source).

### Cross-stage display widgets

| Tab | Widget | Source |
|---|---|---|
| Prefab | `_usage_label` | `selected_prefabs` count + `outputs.asset_processor.{meshes, materials}` counts |
| Prefab | `_last_run_box` | `outputs.asset_processor.{prefabs, last_run}` |
| Scene | `_project_prefabs_label` | `outputs.asset_processor.prefabs` count |
| Scene | `_last_run_box` | `outputs.scene_converter.{scenes, last_run}` |
| Mesh | `_inv_list` + `_inv_summary` | `outputs.asset_processor.meshes` |
| Mesh | `_last_run_box` | `outputs.asset_processor.{meshes, last_run}` |
| Material | `_inv_list` + `_inv_summary` | `outputs.asset_processor.materials` |
| Material | `_last_run_box` | `outputs.asset_processor.{materials, last_run}` |

All cross-stage widgets refresh on:
- `project_changed` (covers project open/close/switch)
- `status_changed` (covers per-stage updates from worker finalize)

### `_InventoryStubTab`

Shared base for Mesh + Material:

```python
class _InventoryStubTab(QWidget):
    STAGE_KEY:   str    # informational only (no schema yet)
    OUTPUTS_KEY: str    # 'meshes' or 'materials'
    TITLE:       str
    EMPTY_MSG:   str
    FUTURE_F:    str    # 'F-5' or 'F-6'
```

`MeshTab` and `MaterialTab` subclass this and set the four constants.

### Test-close suppression

```python
class MainWindow(QMainWindow):
    SUPPRESS_CLOSE_PROMPT = False

    def closeEvent(self, event):
        if self.SUPPRESS_CLOSE_PROMPT or os.environ.get("U2O_SKIP_CLOSE_PROMPT"):
            event.accept()
            return
        # ... existing prompt logic ...
```

Tests set the class attribute once before constructing MainWindow.

## Implementation Plan

### I.1 — Test-close suppression
**Done when:** `SUPPRESS_CLOSE_PROMPT` flag in closeEvent. Verification
scripts use it; no more dialog leaks.

### I.2 — Schema + deep-merge `from_json`
**Done when:** `selected_prefabs` added to `_default_stages`. Existing
testbed projects (which don't carry the key) load with the F-4
default via per-stage deep merge.

### I.3 — Input hash + readiness updates
**Done when:** `input_hash_for("asset_processor", project)` includes
`selected_prefabs`. `compute_stage_readiness` adds the
prefab-selection rung before the destination rung.

### I.4 — PrefabProcessorTab UI rebuild
**Done when:**
- Scrubbed `*.prefab` checklist mirroring F-3 scene checklist.
- Refresh / Select All / Clear Selection / Clear Missing buttons.
- Missing-but-selected entries render with ⚠ + tooltip.
- `_usage_label` above output section.
- `_last_run_box` below the log.

### I.5 — Worker filter
**Done when:** `_start_processing` resolves the selected relative
paths and passes them into `_do_processing`. Worker no longer
rglobs the source.

### I.6 — Scene Converter cross-stage display
**Done when:**
- `prefab_dirs` UI section removed (schema field preserved).
- New "Project Prefab Inventory" section above the log.
- `_collect_prefab_db_paths` derives the PrefabDatabase search dirs
  from `project.stages.asset_processor.output_path / "Prefabs"` plus
  any legacy `prefab_dirs`.
- Worker uses `_collect_prefab_db_paths()` instead of `self._prefab_dirs`.

### I.7 — Scene Converter per-level breakdown
**Done when:** `_last_run_box` shows two lines per converted scene
(header + counts) sourced from `outputs.scene_converter.scenes`.

### I.8 — Mesh + Material stub tabs
**Done when:**
- `_InventoryStubTab` base class exists.
- `MeshTab` + `MaterialTab` subclass it with their constants set.
- Inventory list, summary, last-run details render correctly.
- Process button is disabled with explanatory tooltip.

### I.9 — Tab reorder
**Done when:**
- `MainWindow.__init__` adds Mesh + Material between Prefab and
  Terrain.
- `_STAGE_TAB_INDEX` extends to include `mesh_processor` and
  `material_processor`.
- CLI `--tab=mesh|material` accepted.

### I.10 — Verification

| ID | Proof |
|---|---|
| T-1 | Existing testbed loads with `selected_prefabs` populated as `[]` (deep merge) |
| T-2 | Input hash changes when selection changes |
| T-3 | Readiness chain reports "No prefabs selected" when source set + selection empty |
| T-4 | Tab list is Dashboard / Scene / Prefab / Mesh / Material / Terrain / Config |
| T-5 | Pre-run: cross-stage labels say "no prefabs" / "no meshes" / "no materials" |
| T-6 | Simulated prefab run populates: prefab usage label, scene project-prefab label, mesh inventory, material inventory, all three last-run boxes |
| T-7 | Simulated scene run populates Scene tab's last-run with per-level rows ("X entities · Y prefab refs · Z blanks · W missing") |
| T-8 | `mw.close()` with SUPPRESS_CLOSE_PROMPT=True doesn't fire the unsaved-project dialog |

## Out of scope (deliberately)

- **Auto-check by scene reference.** F-3's smart-default scene-by-prefab
  affordance still pending. With F-4 in place, F-3 could now compute
  which prefabs each scene references and auto-check them; deferred
  to a follow-up polish.
- **Mesh override / material remapping.** Full F-5 / F-6 work. The
  stub tabs only display inventory; actual processing lands in those
  features.
- **Per-prefab metadata in `selected_prefabs`.** Just a list of paths.
  Override metadata (which F-5 / F-6 may want) goes in their own
  stage settings.
- **Multi-output prefab destinations.** Stage 1 still emits to a
  single `output_path`.
