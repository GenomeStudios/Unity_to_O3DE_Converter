---
name: asset-packs-import-catalogue
description: Reference catalogue of the 3 target Unity asset packs (Alien Fantasy Forest, Office & Police Station, NatureManufacture) — structure, collision conventions, FBX/fileID schemes, LOD/material/prefab traits, and per-feature import implications. Compare new feature work against this.
metadata:
  type: reference
---

# Target Asset Packs — Import Catalogue

Three Unity packs the user wants to import into O3DE "with as much
success as possible." Use this as the compatibility yardstick for any
converter feature (mesh, collider, material, LOD, prefab).

## Locations
- **Alien Fantasy Forest** — source `D:\OffLocalDev\Contracting\artificer\Assets\Alien Fantasy Forest`;
  active O3DE output project `D:\OffLocalDev\ProjectSwitch` (Assets/Art/Alien Fantasy Forest).
  Converter project: `D:\OffLocalDev\Unity to Converter Projects\Alient Forest - SwitchProject.u2oproj.json`.
- **Office & Police Station** — `D:\OffLocalDev\dellagolayover\Assets\OfficeAndPoliceStation`.
- **NatureManufacture Assets** — `C:\LocalDev\AGURP2024\Assets\NatureManufacture Assets`.

## At-a-glance metrics (2026-05-28)

| Metric | Alien Forest | Office/Police | NatureManufacture |
|---|---|---|---|
| Prefabs | 85 | 222 | 1056 |
| MeshCollider (non-convex) | 60 | 21 | 607 |
| MeshCollider (convex) | 0 | 0 | 4 |
| BoxCollider | 0 | 402 | 196 |
| LODGroup prefabs | 84 | 0 | 853 |
| Collision granularity | per-FBX (single-mesh LOD) | per-submesh of dedicated _COL FBX | per-submesh (LOD) of render FBX |

Across all three, MeshColliders are **overwhelmingly non-convex
(triangle)** — convex is a rounding error (4 total). BoxCollider is the
dominant collider in Office; absent in Alien Forest.

## Collision topology — the four patterns observed

The unifying truth: **a MeshCollider's collision geometry is one
specific Unity mesh sub-asset, identified by `m_Mesh = {guid, fileID}`**
— NOT "the FBX" and NOT "the collider GameObject's render mesh." The
collider GameObject and the geometry source are frequently decoupled.

- **T1 — collider on mesh GO, same single-mesh FBX** (Mushroom_Big1,
  the original reference). `m_Mesh` = the GO's own render FBX, one mesh.
  pxmesh == whole FBX.
- **T2 — collider on PARENT GO, separate single-mesh LOD FBX**
  (Alien Forest `Dead _trunk_01`). Collider sits on the root GO (no mesh
  of its own); `m_Mesh` → a separate per-LOD FBX (`*_L3.fbx`, the cheap
  LOD) that is ALSO rendered by a child entity. Single mesh per FBX.
- **T3 — collider on a LOD GO, specific sub-mesh of the SAME render FBX**
  (NatureManufacture `prefab_SM_road_border_01`). LODGroup with
  LOD0/1/2 all in one FBX (fileIDs 4300000/4300002/4300004). Collider
  is placed on the LOD2 GO but `m_Mesh` → fileID 4300000 = the **LOD0**
  sub-mesh. So: same FBX as render, but a *different* sub-mesh than the
  collider GO renders, and that sub-mesh IS rendered by another GO.
- **T4 — dedicated multi-submesh `_COL` FBX, never rendered**
  (Office `StairsMod_Ground`). Render FBX
  `Meshes/Building/StairsMod_Ground.FBX` (guid 7146a5ba); collision FBX
  `Colliders/StairsMod_Ground_COL.FBX` (guid 938990c8) is a SEPARATE
  file with 3 collision sub-meshes (`*_Collision`). Three GOs each have
  a MeshCollider → a distinct fileID (4300000/4300002/4300004) of the
  COL FBX. The COL FBX has no render consumer at all.

T3 and T4 break any "one pxmesh per FBX (stem-named)" model: a single
FBX must yield **multiple** pxmesh products, one per selected sub-mesh.

## Unity m_Mesh fileID → FBX node mapping (verified)

`read_fbx_mesh_node_names` (binary FBX reader in
`integrated_asset_processor`) returns mesh nodes in **file order**.

- **Legacy linear scheme** (positive fileIDs ≥ 4300000):
  `mesh_index = (fileID - 4300000) // 2`. Verified on StairsMod_COL:
  fileIDs 4300000/4300002/4300004 → nodes[0/1/2] =
  `StairsMod_Ground_Collision`, `StairsMod_RailingInside_Loop_Collision`,
  `StairsMod_RailingOutside_Collision`, and the GO names line up. Same
  scheme in NatureManufacture (4300000=LOD0) and Alien Forest.
- **Single-mesh FBX**: always node[0] regardless of fileID
  (Desk_metal_COL, Cell_COL each have exactly 1 mesh).
- **Hash scheme** (negative fileIDs, e.g. Desk_metal `m_Mesh.fileID =
  -7011492303168654833`, Unity 2018+ recursive-name hash): NOT decoded.
  Falls back to whole-FBX, which is correct only when the FBX is
  single-mesh (true for Desk/Cell). A multi-mesh FBX with hash fileIDs
  would need the recursive-name-hash reverse map — not yet implemented;
  none observed in these packs.

All three packs' COL/render FBXs are **binary** FBX (StairsMod v7200,
Dead_trunk_L3 v7300). The reader handles both. NOTE: passing an
MSYS-style `/d/...` path to the reader silently returns `[]` (caught
exception) — use Windows `D:/...` paths when testing.

## Path / naming conventions per pack
- **Alien Forest**: render + collision LODs together under `…/Models/`
  as `Name.fbx`, `Name_L1.fbx`, `Name_L2.fbx`, `Name_L3.fbx`. Collider
  uses the `_L3` (lowest) LOD as collision. Material names mixed-case;
  see `mem:project/converter_working_status` for the live material map.
- **Office/Police**: clean split — render in `Meshes/<category>/`,
  collision in a dedicated `Colliders/*_COL.FBX` (13 files). Convention:
  `<RenderStem>_COL.FBX`. Box-collider heavy (402); 21 mesh colliders.
- **NatureManufacture**: no `_COL` convention — collision is a sub-mesh
  (usually LOD0) of the render FBX. LODGroup-dominant (853/1056). Rocks,
  road borders, foliage — organic, high mesh-collider count (607).
  Sub-packs: Advanced Rock Pack, Forest/Meadow Environment Dynamic
  Nature, River Auto Material, Spline System, etc. Custom NM shaders
  (Object/Foliage/Particle Shaders) → material-profile work will need
  attention here.

## Feature implications (compare against these when designing)
- **PhysX mesh collider** (`mem:physx_mesh_collider/physx_mesh_collider_plan`):
  must resolve `(guid, fileID)` → one FBX node and cook a per-sub-mesh
  pxmesh. Whole-FBX/stem-only naming is INSUFFICIENT (T3, T4). Must
  scrape dedicated `_COL` FBXs that have no render consumer (T4). Must
  handle collider-on-parent / collider-on-different-LOD decoupling
  (T2, T3) — cannot assume the collider GO renders its collision mesh.
- **LOD**: Alien Forest + NatureManufacture are LODGroup-heavy; an
  O3DE LOD story (LodRule / multiple azmodels) matters for those two.
  Office has none.
- **Box colliders**: Office leans on BoxCollider (already handled by
  `box_collider.py`); validate offsets there specifically.
- **Convex**: respecting `m_Convex` matters almost nowhere (4 cases);
  triangle mesh is the default path to get right first.
