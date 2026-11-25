# LOD Handling — Working Documentation

Living status for the LOD strip toggle + (future) LodRule bake. Newest entries on top.
Paired with `mem:lod_handling/lod_handling_plan`.

---

## 2026-06-01 (b) — Toggle MOVED to Prefab Processor tab (user request)

User: "make this strip LODs a toggle on the prefab page." Relocated the setting from
`mesh_processor` (MeshTab) to **`asset_processor` (Prefab Processor tab)** — the
semantically correct home, since LOD stripping is a prefab-import transformation, not a
per-mesh concern. Worker now takes a first-class `strip_lods` constructor param instead
of reading it out of `mesh_settings`.

### Changes
- **`project_manager.py`**: removed `strip_lods` from `mesh_processor`; added
  `"strip_lods": True` to `asset_processor` defaults (~line 355).
- **`integrated_asset_processor.py`**: `__init__` gained `strip_lods: bool = True`
  kwarg → `self._strip_lods` (~887); `_parser_context()` now passes
  `strip_lods=self._strip_lods` (was `self._mesh_settings.get("strip_lods")`).
- **`main_app.py`**:
  - Reverted MeshTab checkbox/load/handler.
  - `PrefabProcessorTab`: new "Conversion Options" groupbox with `_strip_lods_cb`
    ("Strip LODs — keep LOD0 only", ~3013); load in `apply_project` under
    `_suppress_prefab_signals` (~3063); persisted via `_collect_stage_settings`
    (`"strip_lods"` key, ~3092) + `_on_strip_lods_changed` → `_save_settings` (~3102).
    NB: `update_stage` REPLACES the stage dict, so the key MUST live in
    `_collect_stage_settings` or field edits would wipe it.
  - Run path: snapshot `asset_processor.strip_lods` (~3377) → `WorkerThread(...,
    strip_lods)` → `_do_processing(..., strip_lods, log)` → worker ctor (~3407).
    `WorkerThread.run` passes `log=` as keyword, so adding `strip_lods` positionally
    before `log` is safe.
- **Patch worker** (`_run_full_patch`): unchanged — patch doesn't re-parse prefabs, so
  the ctor default (True) is correct.
- **Tests**: `test_lod_strip.py` docstring updated; added
  `test_worker_threads_strip_flag_into_context` (constructs the worker with
  strip_lods True/False, asserts `_parser_context().strip_lods`). **10/10 pass.**
- Full suite green except pre-existing unrelated `test_terrain_data.py`.

---

## 2026-06-01 (a) — I.1–I.3 SHIPPED (strip toggle, default-on)

Strip-to-LOD0 toggle landed end-to-end. (Settings home was `mesh_processor`/MeshTab in
this first pass — superseded by the move above.)

### Parser core — `platforms/unity/prefab.py` (unchanged by the move)
- `UnityParseContext` gained `strip_lods: bool = True`, `lod_keep_level: int = 0`
  (defaulted so existing constructors — `unity_platform.py`, tests — keep working).
- `parse_unity_prefab` else-branch captures `component_owner[comp_fileID] → GO fileID`
  for every component doc, and `lod_groups[lodgroup_fileID] → [[renderer_fileID,...]
  per level]` via `_extract_lod_renderer_levels`.
- After `build_hierarchy`, runs `strip_lod_groups(...)` when `ctx.strip_lods` and any
  LODGroups were seen. Helpers: `strip_lod_groups`, `_remove_go_subtree` (recursive,
  with a `keep`-set guard so a kept GO nested under a dropped one survives),
  `_extract_lod_renderer_levels`. Keep wins on a shared renderer.

### Tests — `tests/unit/test_lod_strip.py` (10)
extract-levels ordering/empty/null-ref; strip keeps LOD0 / drops lower + subtrees;
shared-renderer keep-wins; nested-keep guard; subtree count; full `parse_unity_prefab`
on a 2-level LODGroup fixture strip on/off; worker ctor → context wiring.

### Verification status
- ✅ Unit + behavioral parse + worker-wiring proofs pass.
- ⏳ **Not yet field-verified in Editor** on a real LOD-heavy pack (the user's actual
  perf-regression repro). Next: run a Stage-1 conversion on a pack with LODGroups,
  confirm in O3DE Editor that only LOD0 entities appear and perf recovers.
- ⏳ Manual GUI round-trip of the checkbox not yet user-confirmed.

### Pending / follow-ups
- I.3b — Stage-2 scene raw (non-prefab) LODGroups in `scene_converter.py`'s own parse
  loop. Scene-placed prefab *instances* already inherit stripped Stage-1 prefabs.
- I.4+ — LodRule bake (native O3DE LOD): combine LODn FBX nodes into one model +
  `LodRule` in `.assetinfo`, one MeshComponent. Stub in the plan; needs an
  `asset_processor.lod_mode` (strip | bake) setting + per-level FBX node selection.

### Root cause (recorded at open)
`LODGroup` (`!u!205`) is NOT in the component dispatch, so `parse_unity_prefab` stashed
no LODGroup data and every LOD child survived emission. LODGroup
`m_LODs[].renderers[].renderer.fileID` = MeshRenderer **component** fileIDs.
