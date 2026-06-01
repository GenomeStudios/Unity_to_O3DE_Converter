---
name: physx-mesh-collider-working-doc
description: Living status for the PhysX mesh collider .pxmesh feature. See `mem:physx_mesh_collider/physx_mesh_collider_plan` for design + engine-verified facts and `mem:asset_packs/import_catalogue` for the T1–T4 topologies.
metadata:
  type: project
---

# PhysX Mesh Collider — Working Documentation

## 2026-05-28 — Per-sub-mesh model SHIPPED (R.1–R.6 + tests). In-engine cook pending.

The per-entity / stem-named-whole-FBX approaches were both superseded
(see plan REVISION). The shipped model: **a collider's geometry is the
sub-mesh `m_Mesh = {guid, fileID}` → one FBX node → one PhysX group →
one `.pxmesh`**, with multiple groups allowed per assetinfo. Two axes:
ArtFBX↔ColliderFBX (which assetinfo) × Mesh→SubMesh (how many groups).

**What shipped**
- `mesh.py` / `mesh_collider.py` parse — capture `m_Mesh.fileID`
  (render `go.mesh_file_id`; collider `collider['mesh_file_id']`). [R.1]
- `integrated_asset_processor.resolve_collision_node(file_id,
  fbx_node_names, render_node)` — resolves a collision sub-mesh to its
  FBX node. Priority (hardened 2026-05-28): **real correlated node →
  single-mesh node[0] → linear decode `(fileID-4300000)//2` → fallback.**
  Correlation is trusted ONLY when its leaf is an actual FBX node
  (build_fbx_node_paths can fall back to the GO name, which may not exist
  — NatureManufacture GO `…_LOD2` vs FBX node `…_LOD02`). Linear decode is
  the authority for the common positive-fileID case. [R.2]
- `physx_group_name(stem, node, names)` — `{stem}` for single-mesh,
  `{stem}-{node_leaf}` for multi-mesh → distinct pxmesh products.
- `process_prefab` — collects collider refs, **scrapes** collision FBXs
  not already copied (Axis A), iterates render∪collision guids, builds
  one PhysX spec per distinct collision sub-mesh (Axis B), builds
  `collider_pxmesh_mapping {(guid,fileID): hint}`. [R.3/R.4 producer]
- `assetinfo_writer.write_fbx_assetinfo` — param is now `physx_specs`
  (list of `{name, node_paths, convex}`); emits one group per spec into
  the same `values[]` (TriMesh default / `export method:1` convex /
  identity-omits-rules). Works with or without visual groups. [R.4]
- `mesh_collider._write_mesh_collider` — hint from
  `ctx.collider_pxmesh_mapping[(guid, fileID)]` (guid falls back to the
  GO's render mesh). `ProcessingContext.collider_pxmesh_mapping` added;
  stashed on `worker._collider_pxmesh_mapping` by `create_o3de_prefab`
  (avoids threading through every recursive signature). scene_converter
  passes `{}`. [R.5]
- State index entry: `collider_entity_node_map` REPLACED by
  `physx_specs`. `_record_mesh_state` + patch worker re-emit updated; the
  "needs reparse" gate now keeps a collision-only FBX (empty
  entity_node_map but non-empty physx_specs) replayable. [R.6]

**Verification — end-to-end on REAL packs (material processing bypassed
in this PySide6-less env; the mesh/collider path is exercised fully):**
- T2 Alien Forest `Dead _trunk_01`: collider on parent → hint
  `…/Dead _trunk_01_L3.fbx.pxmesh`; L3 assetinfo gains a triangle PhysX
  group selecting `RootNode.Old_trunk_01_TRunk_L3_Bark_MatSG`. ✓
- T3 NatureManufacture `prefab_SM_road_border_01`: collider fileID
  4300000 → `SM_road_border_01-SM_road_border_01_LOD02.fbx.pxmesh` (linear
  decode; correlation correctly rejected the LOD2/LOD02 name mismatch). ✓
- T4 Office `StairsMod_Ground`: `_COL` FBX scraped though never rendered;
  3 distinct PhysX groups + 3 colliders resolve to their own sub-mesh
  pxmesh via linear decode. ✓
- Unit/integration: test_collision_resolver 8/8, test_assetinfo_writer
  16/16, test_mesh_state_index_shape 2/2, test_mesh_patch_worker 4/4.
- Full-suite remainder (16 modules) fails only on `ModuleNotFoundError:
  PySide6` (env), pre-existing, unrelated.

**Pending — in-engine cook (user pivot):** open the converted projects
in O3DE, confirm the `.pxmesh` products cook (Asset Processor) and the
colliders line up with the right sub-mesh in-world. Watch: (a) cook
without an `ImportGroup` (`{41DCBEAB…}`) — exporter doesn't require it,
add only if needed; (b) negative-hash fileID on a MULTI-mesh FBX has no
clean decode and relies on correlation — none seen in these packs, but
flag if one appears (would land on the fallback node).
