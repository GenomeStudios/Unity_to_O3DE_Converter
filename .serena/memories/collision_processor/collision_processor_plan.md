---
name: collision-processor-plan
description: Plan + locked decisions for the Collisions tab (F-Collision) — defaults + per-collider-entity overrides for O3DE CollisionLayer/CollisionGroupId, plus the NEW base feature of a target O3DE project root on the converter project. Engine-source-verified serialization.
metadata:
  type: project
---

# Collisions Tab — Plan (F-Collision)

## Goal
Give converted colliders an authored collision **layer** ("from") and
**group** ("to"), via a new Collisions tab mirroring F-5 Mesh / F-6
Material (defaults + read-only multi-select inventory + per-object
override). Today colliders emit NO layer/group (the `physx_mesh_collider`
plan left engine defaults: layer `Default`, collides with `All`).

## Engine-verified serialization (o3de_sourcedev)
`Physics::ColliderConfiguration` (`Code/Framework/AzFramework/.../Physics/Shape.cpp`, Version 7):
- `"CollisionLayer"` → `AzPhysics::CollisionLayer` → `{ "Index": <u8 0..63> }`
  (UUID `{5AA459C8-2D92-46D2-9154-ED49EE4FE70E}`; member `m_index`, field `"Index"`).
- `"CollisionGroupId"` → `AzPhysics::CollisionGroups::Id` → `{ "GroupId": "<AZ::Uuid>" }`
  (UUID `{DFED4FE5-...}`; member `m_id`, field `"GroupId"`).

A collider stores "collides-with" ONLY as a GroupId UUID referencing a named
**preset** — there is no inline custom mask on the collider. The names behind
layers/groups live in the target project's
`physxsystemconfiguration.setreg`, settings-registry path
`/Amazon/Gems/{PhysX,PhysX5}/PhysXSystemConfiguration/CollisionConfig`:
- `Layers.LayerNames` = `array<string,64>` (array index = layer index).
- `Groups.GroupPresets[]` = `{Id:{GroupId:uuid}, Name, Group:{Mask:u64}, ReadOnly}`.
`CollisionConfiguration` UUID `{84059477-...}`, embedded in `SystemConfiguration`
field `"CollisionConfig"`. Nothing in a Unity asset provides these → must be read
from the target O3DE project.

## Resolved Decisions (Q&A 2026-06-01)
**Q1 — What is a selectable "collision object" (no GUID like meshes)?**
A: **Per collider-bearing entity**, keyed `"<prefab_guid>:<entity_file_id>"`.
Stage-1 records a collider inventory into `outputs.asset_processor`.

**Q2 — Where does the layer/group vocabulary come from; do we write the .setreg?**
A: **Read-only.** Converter only stamps `Index`/`GroupId`; NEVER writes the
`.setreg`. Vocabulary is READ from the target project's setreg to populate
name pickers.

**Q3 — How does the tab find the setreg? (refinement after Q2)**
A: **NEW base feature — target O3DE project root on the converter project**
(`.u2oproj.json`). Tab derives `<o3de_project_root>/Registry/physxsystemconfiguration.setreg`,
with an optional per-tab `setreg_override`. The project-root field is a general
base feature reusable beyond collisions.

**Q4 — Phase-1 scope?**
A: **Editor + collider stamping.** Tab + inventory + stamping ship now;
`.setreg` WRITING is out of scope (Phase 2, may never be needed).

## Schema (project_manager._default_stages, after material_processor)
```python
"collision_processor": {
    "defaults": {
        "collision_layer":    None,   # int 0..63 or None → don't emit (engine default)
        "collision_group_id": None,   # UUID str or None  → don't emit
    },
    "overrides": {},      # "<prefab_guid>:<file_id>": {"collision_layer":1,"collision_group_id":"<uuid>"}
    "layer_names": {},    # {"0":"Default",...}  display-only, cached from .setreg
    "group_names": {},    # {"<uuid>":"All",...} display-only, cached from .setreg
    "setreg_override": "" # blank → derive from project's target O3DE root
}
```
Effective-value chain per entity/field: `overrides[key][field]` → `defaults[field]`
→ `None`. `None` effective value = emit nothing (byte-compat with current output).
`collision_processor` is a sub-stage (NOT in `STAGE_KEYS`); picked up by `from_json`
per-stage deep-merge like mesh_processor/material_processor.

## Changes by file
- **0. project_manager.py — NEW base field `o3de_project_root`.** Top-level `Project`
  field (not platform-namespaced), mirroring `scope_root`: dataclass field (~526),
  to_json/from_json round-trip, `set_o3de_project_root()` + `_mark_dirty`, helper
  `physx_setreg_path() -> Optional[Path]` = `<root>/Registry/physxsystemconfiguration.setreg`.
  UI in project header form (main_app ~1144–1172): `_path_row` "Target O3DE project"
  + browse + editingFinished → set + `commit_metadata`, status label mirroring
  `_refresh_scope_root_status`.
- **1. project_manager.py — collision_processor schema** (above).
- **2. targets/o3de/collision_config.py — NEW** read-only parser
  `parse_physx_collision_config(setreg_path) -> ({index_str:name}, {uuid:name})`.
  Tolerant of PhysX/PhysX5 gem names + missing keys; skip empty/"Unnamed" layers.
- **3. integrated_asset_processor.py — collider inventory.** `self._collision_objects`
  in __init__; populate in `process_prefab` (prefab_guid resolved ~line 1287, colliders
  iterated ~1051) per collider-bearing GO; emit in `to_outputs()` (~1573) as
  `"collision_objects"`. Entry: `{prefab_guid, prefab_name, entity_file_id, entity_name,
  collider_types[], collider_summary}`.
- **4. Collider stamping** — mirror `collider_pxmesh_mapping` threading:
  - producer builds `collision_config_mapping={file_id:{"layer":int|None,"group":uuid|None}}`
    from defaults+overrides keyed `prefab_guid:file_id`, passes to `create_o3de_prefab`.
  - prefab_writer: `create_o3de_prefab(..., collision_config_mapping=None)` →
    `worker._collision_config_mapping`; ctx build (~701) adds `collision_config=getattr(...)`.
  - base.py ProcessingContext: new `collision_config: Dict[str,Dict]` field.
  - box_collider.py: shared `_apply_collision_config(collider_cfg, go, ctx)` (next to
    `_resolve_target`), called by all 4 writers (box/sphere/capsule/mesh) where
    `collider_cfg` is built. Adds `CollisionLayer={Index:layer}` / `CollisionGroupId={GroupId:group}`.
  - scene_converter.py: passes `collision_config_mapping={}` (scene per-object out of scope).
- **5. main_app.py — CollisionTab** (mirror MeshTab 4482–5132). Two editable-combo fields
  (layer "from" from layer_names + (engine default); group "to" from group_names). Multi-edit
  common/`…` semantics. Reload-physics-layers button → `parse_physx_collision_config(effective
  setreg)`; effective = setreg_override else `proj.physx_setreg_path()`. Inventory from
  `outputs.asset_processor.collision_objects` with ★ for overrides. Selection Overrides + Clear.
  Tab registered after Materials (insert index 5, shift Terrain→6/Config→7; grep hard-coded
  tab indices in Mission Command/Dashboard nav).

## Implementation Plan (paced, verify at each pivot)
- **I.0** Target O3DE project root base feature (§0). T-0. Pivot: user points at a real
  O3DE project; status confirms setreg found.
- **I.1** Collision schema + setreg parser (§1+§2). T-1, T-6. Pivot.
- **I.2** Stage-1 collider inventory (§3). T-7. Pivot (real-pack run).
- **I.3** Collider stamping (§4). T-2..T-5. Pivot (prefab JSON + back-compat).
- **I.4** CollisionTab UI (§5). T-8. Pivot (user drives tab).
- **I.5** In-engine verification (user). T-9.

## Testing matrix
| ID | Phase | Proof |
|----|-------|-------|
| T-0 | I.0 | `o3de_project_root` round-trips save→load; `physx_setreg_path()`=`<root>/Registry/physxsystemconfiguration.setreg`; blank→None |
| T-1 | I.1 | `collision_processor` stage present, defaults `{collision_layer:None,collision_group_id:None}` after open |
| T-6 | I.1 | parser returns correct `{index:name}`+`{uuid:name}` from sample setreg (PhysX + PhysX5 paths) |
| T-7 | I.2 | parsed prefab w/ colliders → `to_outputs()['collision_objects']` keyed prefab_guid:file_id w/ summary |
| T-2 | I.3 | default layer=1+group uuid → ColliderConfiguration has CollisionLayer={Index:1}+CollisionGroupId={GroupId:uuid} |
| T-3 | I.3 | nothing configured → NO CollisionLayer/CollisionGroupId (byte-compat) |
| T-4 | I.3 | per-entity override beats default for that entity only |
| T-5 | I.3 | partial override (layer only) → layer overridden, group inherits default |
| T-8 | I.4 | tab launches; inventory+★; multi-select edit applies to all; mixed `…`; Clear works; round-trips |
| T-9 | I.5 | converted collider shows chosen layer/group in O3DE Inspector + filtering correct (user) |
| reg | all | existing suite green (collider writers, assetinfo_writer, mesh state-index, patch worker) |

## Out of scope (Phase 2 / deferred)
- Writing/patching the `.setreg`.
- Auto-mapping Unity `m_Layer` (TagManager) → O3DE layer + Unity collision matrix → groups.
- Scene-entity per-object overrides (global defaults could still apply cheaply).
- Authoring custom group masks / creating presets.
- Per-collider (vs per-entity) overrides when one entity has multiple distinct colliders.

Plan file mirror: `C:\Users\gaian\.claude\plans\linear-percolating-cosmos.md`.
Related: `mem:physx_mesh_collider/physx_mesh_collider_plan`, `mem:mesh_preprocessing/mesh_preprocessing_plan`,
`mem:material_preprocessing/material_preprocessing_plan`.
