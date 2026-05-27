---
name: prefab-marking-working-doc
description: Living status log for F-4 (scrubbed prefab checklist + cross-stage display + Mesh/Material stub tabs). Newest entries on top.
metadata:
  type: project
---

# F-4 Prefab Marking — Working Documentation

Newest entries on top. Linked plan: [[prefab-marking-plan]].

## 2026-05-27 — F-4 shipped ✓

### What landed

**Test-close suppression (I.1)**
- `MainWindow.SUPPRESS_CLOSE_PROMPT: bool = False` class attribute.
- `closeEvent` checks the class flag and the env var
  `U2O_SKIP_CLOSE_PROMPT` and accepts immediately if either is set.
  Stops verification scripts from popping the unsaved-project dialog
  and leaving zombie windows.

**Schema + deep-merge (I.2)**
- `_default_stages()` adds `selected_prefabs: []` to `asset_processor`.
- `Project.from_json` switched to a per-stage deep merge so older
  project files load cleanly with the new field defaulting to empty.
  Caught a regression where the shallow `dict.update()` was clobbering
  any new schema fields.

**Input hash + readiness (I.3)**
- `input_hash_for("asset_processor", ...)` now incorporates
  `selected_prefabs` (sorted) + per-file mtime fingerprints of the
  selected files.
- `compute_stage_readiness` for `asset_processor` adds the prefab
  selection step between "source set" and "destination set":
  - "Source has no .prefab files" — partial
  - "No prefabs selected" — partial
  - "{N} of {scrubbed_count} prefabs selected" — met

**PrefabProcessorTab UI (I.4)**
- Scrubbed checklist matching the F-3 scene checklist:
  Refresh from Scope / Select All / Clear Selection / Clear Missing.
- Missing-but-selected entries render with ⚠ + tooltip.
- New `_usage_label` above output: shows selection count + mesh /
  material output counts when present.
- New `_last_run_box` section: per-prefab breakdown after a run
  (output_path · entities · material slot count). Capped at 20.

**Worker filter (I.5)**
- `_start_processing` validates selection and resolves to absolute
  paths before kicking the worker. Missing-on-disk prompts before
  continuing with the resolved subset.
- `_do_processing` signature now takes `prefab_files: list` (was
  `rglob`-derived); no functional regression since the processor
  still calls `process_prefab(prefab_file)` per item.

**Scene Converter cross-stage (I.6)**
- Removed the `Prefab Search Directories` UI section entirely
  (schema `prefab_dirs` field kept for backwards compat).
- New `Project Prefab Inventory` section explains how many
  converted prefabs are available, with three states (no
  project / selections-but-no-run / run-complete).
- `_collect_prefab_db_paths()` derives the PrefabDatabase search
  dirs from `project.stages.asset_processor.output_path / "Prefabs"`
  plus any legacy `prefab_dirs`. Worker uses this instead of the
  old `self._prefab_dirs`.
- Pre-run warning prompt if the project has no prefab outputs yet.

**Scene Converter per-level breakdown (I.7)**
- `_last_run_box` at the bottom of the tab; hidden until
  `outputs.scene_converter.scenes` has entries.
- Two lines per scene: `  • <stem> → <output_path>  ·  <timestamp>`
  and `        N entities · M prefab refs · X blanks · Y missing`.
- Missing-prefab rows render in orange to draw the eye.

**Mesh + Material stub tabs (I.8)**
- `_InventoryStubTab` shared base.
- `MeshTab` (TITLE "Mesh Inventory", OUTPUTS_KEY "meshes", FUTURE_F
  "F-5"), `MaterialTab` (TITLE "Material Inventory", OUTPUTS_KEY
  "materials", FUTURE_F "F-6").
- Each tab: intro paragraph → inventory list (bounded scrollable) →
  summary line → last-run details → disabled Process button with
  tooltip pointing at the future feature.

**Tab reorder (I.9)**
- New order: Dashboard / Scene Converter / Prefab Processor /
  **Mesh / Material** / Terrain / Config(hidden corner).
- `_STAGE_TAB_INDEX` extended to include `mesh_processor` and
  `material_processor` (so dashboard cards can route to them if they
  ever appear there).
- CLI `--tab=` accepts `mesh|material` in addition to existing
  values.

### Sanity gates passed

- `py project_manager.py` → smoke OK (11 invariants).
- `py -c "import main_app"` → OK.
- E2E verification against the testbed:
  - F-4 schema present after open ✓
  - Input hash differs by selection (`16fef093f54dc967` vs
    `224dc67031bbc3f2`) ✓
  - Readiness reports "No prefabs selected" when source set,
    selection empty ✓
  - Tab order: Dashboard / Scene / Prefab / Mesh / Material /
    Terrain / Config ✓
  - Pre-run labels: prefab usage = "0 selected", scene prefabs =
    "No prefabs available", mesh / material inventories empty ✓
  - Simulated prefab run populates: prefab usage label, scene
    project-prefab label, mesh inventory (2 entries), material
    inventory (2 entries), all three last-run boxes visible ✓
  - Simulated scene run populates Scene tab's last-run with two
    levels: Demo1 (42 entities · 8 refs · 3 blanks · 0 missing) and
    Demo2 (17 · 4 · 1 · 2 missing) ✓
  - `mw.close()` with SUPPRESS_CLOSE_PROMPT=True returns cleanly,
    no dialog ✓

### Notes for future F's

- **F-3 smart-default scene checkbox.** Now that we have a prefab
  inventory, F-3 can compute which prefabs each scene references and
  auto-check them. Outside the scope of F-4 but cheap to add later.
- **F-5 (mesh preprocessing).** MeshTab already shows the per-mesh
  inventory; F-5 adds override storage + the actual preprocessing
  worker. The tab layout is the right shape to receive overrides.
- **F-6 (material library).** Same — MaterialTab shows the per-
  material inventory; F-6 adds shader-mapping rules + the worker.
- **Stage 2 prefab DB completeness.** Currently builds from
  `<asset_processor.output_path>/Prefabs/` via filesystem scan. A
  future iteration could read directly from
  `outputs.asset_processor.prefabs` keyed by GUID — skipping the
  disk scan entirely. Out of scope; would unlock pre-run resolution
  ("which prefabs ARE my scenes about to need?").

### Known follow-ups

- Mesh / Material tabs don't currently appear as Dashboard status
  cards. Once F-5 / F-6 give them their own stages with readiness
  semantics, the dashboard should grow new cards.
- The legacy `prefab_dirs` field is kept in the schema but dead. A
  later schema cleanup could prune it; not worth doing alone.

## Pending / not yet shipped

- Real Mesh preprocessing (F-5).
- Real Material shader-mapping library (F-6).
- Cross-stage: per-mesh / per-material "used by N prefabs" reverse
  lookup. Useful once F-5 / F-6 land.
