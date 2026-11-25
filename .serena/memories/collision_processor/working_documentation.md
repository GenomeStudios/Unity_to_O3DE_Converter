---
name: collision-processor-working-doc
description: Living status for the Collisions tab feature (F-Collision). See `mem:collision_processor/collision_processor_plan` for design, locked decisions, engine-verified serialization, and the testing matrix.
metadata:
  type: project
---

# Collisions Tab — Working Documentation

Newest entries at top.

## 2026-06-01 — I.0–I.4 SHIPPED + green. Only I.5 (in-engine) remains.

Built in one push (user said "move ahead, I'll verify in parallel"). Full suite
green except the pre-existing, unrelated `test_terrain_data.py` (UnityPy sample-asset
parse; no collision/terrain code touched).

### I.0 — target O3DE project root + New-project onboarding
- `Project.o3de_project_root` (top-level, to_json/from_json, `set_o3de_project_root`,
  `physx_setreg_path()` = `<root>/Registry/physxsystemconfiguration.setreg`).
- Project header row "Target O3DE Project" + status (`_refresh_o3de_root_status`).
- `NewProjectDialog` (Name/Type/Source/Target O3DE); `_on_new` forwards to extended
  `new_project(name, source_engine, scope_root, o3de_project_root)`.
- Tests: `tests/unit/test_o3de_project_root.py` 5/5.
- GOTCHA: main_app has no `typing`/future-annotations import → evaluated return
  annotations must be quoted strings (`-> "Optional[Path]"`).

### I.1 — schema + read-only setreg parser
- `collision_processor` stage in `_default_stages()`: `defaults{collision_layer,
  collision_group_id}` + `overrides` + `layer_names`/`group_names` caches +
  `setreg_override`.
- `targets/o3de/collision_config.py::parse_physx_collision_config(path) ->
  ({index:name},{uuid:name})`. Handles PhysX5/PhysX gem nodes, empty `{}` layer slots
  (array index = layer index), Id-less preset → null UUID. Verified against
  `AutomatedTesting/Registry/physxsystemconfiguration.setreg`.
- Tests: `tests/unit/test_collision_config.py` 5/5 (T-1, T-6).

### I.2 — Stage-1 collider inventory
- `IntegratedAssetProcessor._collision_objects`, populated in `process_prefab`
  (`_record_collision_objects`, keyed `"<prefab_guid>:<file_id>"`), emitted in
  `to_outputs()['collision_objects']`. Entry: prefab_guid/name, entity_file_id/name,
  collider_types[], collider_summary (e.g. "Mesh (convex), Box (trigger)", "Box ×2").
- Tests: `tests/unit/test_collision_inventory.py` 3/3 (T-7).

### I.3 — collider stamping
- `ProcessingContext.collision_config` (defaulted dict field; `field` imported in
  base.py). prefab_writer `create_o3de_prefab(..., collision_config_mapping=)` →
  `worker._collision_config_mapping`; ctx build reads it.
- `IntegratedAssetProcessor`: `collision_settings` ctor kwarg → `self._collision_settings`;
  `_build_collision_config_mapping(prefab_guid, gos)` resolves effective per-entity
  {layer,group} (override→default→None; both-None entities omitted = engine default).
  Threaded through `_create_o3de_prefab`. prefab_guid now resolved BEFORE the prefab
  write (shared with the record calls).
- Shared `box_collider._apply_collision_config(collider_cfg, go, ctx)` stamps
  `CollisionLayer={Index:int}` (layer 0 IS stamped) / `CollisionGroupId={GroupId:uuid}`;
  called by all 4 writers (box/sphere/capsule/mesh — go threaded into the 3 shape writers).
- main_app prefab worker threads `collision_settings` (snapshot → WorkerThread args →
  `_do_processing` → ctor). Patch worker untouched (no collider re-emit → no stamping,
  correct). scene_converter passes nothing (ctx default {}).
- Tests: `tests/unit/test_collision_stamping.py` 8/8 (T-2..T-5 + layer-0 + empty-group).
- Regression: assetinfo_writer 20/20, collision_resolver 8/8, prefab_wrapper 3/3,
  mesh_state_index 2/2, mesh_patch_worker 4/4 — all green.

### I.4 — CollisionTab UI
- `main_app._CollisionChoiceField(QComboBox)` (editable; engine-default + named items;
  raw int/uuid fallback; `…` for mixed) + `CollisionTab` (mirrors MeshTab: defaults +
  inventory + multi-select override + clear + last-run; "Reload physics layers" reads
  effective setreg = `setreg_override` else `proj.physx_setreg_path()`).
- Registered after Materials (index 5; Terrain→6/Config→7). Added "collisions" to
  `SUPPORTED_TABS` default (platforms/base.py), `_PLATFORM_TAB_KEYS`, `_STAGE_TAB_INDEX`.
  Updated `test_platform_contract.py` expected set + verified `test_tab_gating.py` 3/3.
- Tests: `tests/ui/test_collision_tab.py` 7/7 (T-8).

### Pending — I.5 in-engine verification (user pivot, T-9)
Open a converted project in O3DE; confirm a stamped collider shows the chosen layer/
group in the Inspector and that collision filtering behaves. Watch: a stamped GroupId
UUID must exist in the project's setreg or O3DE falls back to default (read-only design
— we don't write the setreg).

### Decisions in flight
- "destination" in the New dialog was mapped to the **target O3DE project root** (not a
  separate output folder). User to confirm; trivial to add a separate output field if
  they meant the raw output dir.

### Out of scope (unchanged) — see plan.
