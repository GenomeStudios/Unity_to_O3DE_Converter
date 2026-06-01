---
name: physx-mesh-collider-plan
description: Plan + locked decisions for making MeshCollider entities cook a real .pxmesh via the FBX .assetinfo, matching O3DE's own PhysX MeshGroup serialization. Engine-source-verified.
metadata:
  type: project
---

# PhysX Mesh Collider — Plan

## Goal

When a Unity entity has a `MeshCollider`, the converted FBX `.assetinfo`
must contain a PhysX MeshGroup (`{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45B}`)
that cooks a `.pxmesh` product, and the entity's
`EditorMeshColliderComponent` must reference that product by `assetHint`.

Ground-truth references the user supplied:
- `ProjectSwitch/Assets/Art/Alien Fantasy Forest/Meshes/Mushroom_Big1.fbx.assetinfo`
  — a known-good PhysX MeshGroup (triangle mesh).
- `ProjectSwitch/Levels/HomeWorld/HomeWorld.prefab` — a known-good
  `EditorMeshColliderComponent` with `assetHint`
  `.../meshes/mushroom_big1.fbx.pxmesh`.

## Engine-verified facts (o3de_sourcedev — D:/OffLocalDev/o3de_sourcedev)

1. **Product name = `<groupName>.<sourceExt>.<productExt>`.**
   `MeshExporter.cpp:561` → `assetName = meshGroup.GetName()`;
   `FileUtilities::CreateOutputFileName` (FileUtilities.cpp:20) does
   `dir / groupName`, `ReplaceExtension(sourceExt)`, then `+ ".pxmesh"`.
   So group `Mushroom_Big1` + source `.fbx` → `mushroom_big1.fbx.pxmesh`.
   The converter's per-entity group name `{stem}-{entity}` therefore
   yields `{stem}-{entity}.fbx.pxmesh`, which is exactly what the
   existing component-hint derivation (`.azmodel`→`.pxmesh` on the
   visual hint) already produces. **Hint naming was never broken.**

2. **`export method` enum** (`MeshGroup.h:36`): `0=TriMesh, 1=Convex,
   2=Primitive`. Field `m_exportMethod{}` value-inits to 0. Omitting the
   field ⇒ TriMesh. The current writer hardcodes `"export method": 1`
   ⇒ everything cooked convex. **This is the actual bug.**

3. **Triangle default serializes bare.** `TriangleMeshAssetParams()`
   ctor sets the PhysX-derived defaults (e.g. `m_mergeMeshes=true`), so a
   default triangle group omits `TriangleMeshAssetParams` entirely. The
   reference group is exactly this: `name` + `NodeSelectionList` +
   `PhysicsMaterialSlots`, nothing else.

4. **Convex default also serializes bare params.** `ConvexAssetParams()`
   defaults come from `PxConvexMeshDesc` (flags=0) ⇒ `Use16bitIndices`
   and `CheckZeroAreaTriangles` default **false**. The old writer forced
   them `true` (non-default). A default convex group needs only
   `"export method": 1`; `ConvexAssetParams` can be omitted.

5. **Selection is literal, non-hierarchical.**
   `SceneNodeSelectionList::EnumerateSelectedNodes` iterates only the
   explicit `m_selectedNodes` set (SceneNodeSelectionList.cpp:66). The
   PhysX `MeshExporter` callback (MeshExporter.cpp:865) casts each
   selected node to `IMeshData` and skips non-mesh nodes. So selected
   nodes must include the actual mesh-data node. The converter's
   `node_path` (from `build_fbx_node_paths`) is the node the visual
   group already cooks successfully ⇒ reuse it. `selectedNodes` and
   `unselectedNodes` are `unordered_set<string>` ⇒ order irrelevant; the
   `{}` entry in the reference's `unselectedNodes` is a harmless editor
   serialization artifact and is NOT replicated.

## Resolved Decisions (Q&A — 2026-05-28)

**Q1 — pxmesh naming / grouping?**
A: **Per-entity, stem-suffixed.** One PhysX MeshGroup per collider
entity, named `{stem}-{entity}`; component hint
`{root}/meshes/{stem}-{entity}.fbx.pxmesh`. Validated by fact (1):
product name follows the group name, so per-entity groups produce
distinct per-entity products and the existing hint already matches.

**Q2 — Convex vs triangle?**
A: **Respect Unity `m_Convex`.** `m_Convex=0` ⇒ bare TriMesh group
(matches reference); `m_Convex=1` ⇒ `"export method": 1`. Params omitted
(engine defaults) in both cases.

**Q3 — `ShapeConfiguration…PhysicsAsset.Scale`?**
A: **Omit (default [1,1,1]).** The entity TransformComponent scale
already scales the collider; the reference's `[2,2,2]` was that entity's
own scale. Baking it would double-scale.

**Q4 — `CollisionLayer` / `CollisionGroupId`?**
A: **Leave engine defaults.** Don't emit; Unity has no equivalent. The
reference's `Index:2` was authored in-engine post-import.

## Design

### Collider map shape (carries convex flag)

`collider_entity_node_map` value evolves from a bare node-path string to
`{"node": <path>, "convex": <bool>}`. The writer accepts **either**
shape (legacy string ⇒ triangle) so cached pre-change state-index
entries and old tests keep working. Persisted as-is in the state index
so the mesh Patch worker replays convexness without re-parsing prefabs.

### PhysX MeshGroup emission (assetinfo_writer.write_fbx_assetinfo)

For each collider entity:
```
{
  "$type": "{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45B} MeshGroup",
  "id": "{<uuid>}",
  "name": "{stem}-{entity}",
  "NodeSelectionList": {
    "selectedNodes":   [node_path],
    "unselectedNodes": [<other entity node paths> , "RootNode"]
  },
  "PhysicsMaterialSlots": { "Slots": [ { "Name": <mesh node leaf name> } ] }
  // if convex:        "export method": 1
  // if coord rule has rotation/translation: "rules": { "rules": [coord_rule] }
}
```
Triangle (default) omits `export method`. Coordinate rule attached only
when it carries a non-identity rotation/translation (so the collision
mesh gets the same orientation correction the visual mesh got);
otherwise omitted to match the reference's minimal form.

### Component (mesh_collider._write_mesh_collider)

No change to hint derivation (already correct per fact 1). Per Q3/Q4: no
`Scale`, no `CollisionLayer`/`CollisionGroupId`. `MaterialSlots` stays as
the existing minimal default — the pxmesh defines the real slots; the
component slot is only per-slot material assignment and is not required
for collision. (Possible future polish: align the slot Name to the FBX
node leaf name to mirror the reference.)

## Implementation Plan

### I.1 — Writer: triangle/convex branch + correct selection
**Done when:** `write_fbx_assetinfo` PhysX block emits TriMesh by
default, `export method:1` for convex, selects the mesh node (unselects
others + RootNode), attaches the coordinate rule only when non-identity,
and accepts both dict and legacy-string collider-map values.

### I.2 — Producer threads convex flag
**Done when:** `integrated_asset_processor.process_prefab` builds
`collider_entity_node_map` with `{"node", "convex"}` values from
`go.colliders`. State-index round-trips the dict.

### I.3 — Tests
| ID | Proof |
|---|---|
| T-1 | Default (non-convex) collider ⇒ PhysX group has NO `export method`, NO `ConvexAssetParams` |
| T-2 | Convex collider ⇒ PhysX group has `export method: 1` |
| T-3 | `selectedNodes == [node_path]`; `RootNode` in `unselectedNodes`; other entity nodes unselected |
| T-4 | Identity mesh settings ⇒ PhysX group has NO `rules`; non-identity ⇒ coord rule present (existing test) |
| T-5 | Legacy string-valued collider map still emits a (triangle) group — back-compat |
| T-6 | Existing suite stays green (state-index shape, integration patch worker) |

### I.4 — In-engine verification (user pivot)
Run the converter on the Alien Forest project, drop a MeshCollider
entity into a level, and confirm in O3DE: the `.pxmesh` cooks (Asset
Processor), the collider references it, and collision is present. This
is the behavioral proof the unit tests can't give.

## 2026-05-28 REVISION — per-sub-mesh model (SUPERSEDES Q1/Q2 naming)

Cross-referencing three real packs (`mem:asset_packs/import_catalogue`)
disproved the "stem-named, one pxmesh per FBX, whole-FBX geometry"
decision. Evidence:
- **Office StairsMod**: dedicated `Colliders/StairsMod_Ground_COL.FBX`
  with 3 collision sub-meshes; 3 colliders each pick a distinct fileID.
- **NatureManufacture road border**: one FBX holds LOD0/1/2; the
  collider picks the LOD0 sub-mesh while sitting on the LOD2 GO.

So one FBX must yield **multiple** pxmesh products. Corrected model:

**Collision asset = `m_Mesh = {guid, fileID}` → exactly one FBX mesh
node → one pxmesh.** Pipeline must:
1. Capture BOTH `guid` and `fileID` on each MeshCollider (parse
   currently drops fileID — `mesh_collider.py::parse` must keep it).
2. Resolve `(guid, fileID)` → FBX node:
   - **Render-correlation first**: if a render entity uses the same
     `(guid, fileID)`, reuse the node `build_fbx_node_paths` already
     computed for it (handles T1/T2/T3).
   - **Else fileID→node decode** in the (possibly un-rendered) FBX:
     linear scheme `index = (fileID - 4300000)//2` against file-order
     `read_fbx_mesh_node_names`; single-mesh FBX ⇒ node[0]; negative
     hash fileIDs ⇒ whole-FBX fallback (OK only for single-mesh).
     (handles T4 dedicated `_COL` FBX.)
3. **Scrape** collision FBXs with no render consumer (T4) into `Meshes/`
   and emit an assetinfo carrying just the PhysX group(s).
4. Emit one PhysX group **per selected node**, named per-sub-mesh so
   products stay distinct: `{stem}-{node_leaf}` (or `{stem}` when the
   FBX is single-mesh). Product = `{name}.fbx.pxmesh`.
5. Component hint = the resolved per-sub-mesh pxmesh, threaded via a new
   `ctx.collider_pxmesh_mapping` keyed by `(guid, fileID)`.

The I.1 writer work (TriMesh-vs-Convex branch, literal node selection,
identity-omits-rules, back-compat values) stays valid groundwork — only
the *grouping/naming* and the *resolution* change. The per-entity
`collider_entity_node_map` shape and the producer's stem assumptions are
to be reworked to the `(guid, fileID)`-keyed model above.

### Two orthogonal axes (user framing, 2026-05-28)

The problem decomposes into two independent axes. O3DE allows MANY PhysX
MeshGroups in one assetinfo (same as the visual groups), so this is just
"append N groups to a `values[]` array":

- **Axis A — ArtFBX ↔ ColliderFBX** → *which assetinfo file*:
  - same-FBX collision ⇒ append PhysX group(s) to the art FBX's existing
    assetinfo (already holds the `{07B356B7}` visual groups). T1/T2/T3.
  - dedicated `_COL` FBX ⇒ scrape-copy it to `Meshes/` and write an
    assetinfo containing only PhysX group(s). T4.
- **Axis B — Mesh → SubMesh, SubMesh₂, …** → *how many groups*:
  - one PhysX group per distinct sub-mesh node referenced by any
    collider in scope; each → its own pxmesh. Naming `{stem}-{node_leaf}`
    (single-mesh FBX collapses to `{stem}`).

A given FBX is the intersection of the two axes: it may be an art FBX OR
a collider FBX (Axis A), and it may need 1..N PhysX groups (Axis B).

### Implementation breakdown (per-sub-mesh, replaces earlier I.1/I.2)

- **R.1 — Capture fileID.** `mesh_collider.py::parse` keeps
  `m_Mesh.fileID` alongside `guid`. (Render `MeshFilter` parse should
  also retain its mesh fileID for correlation.)
- **R.2 — Resolver.** A worker helper maps `(guid, fileID)` → FBX node:
  render-correlation first (reuse `build_fbx_node_paths` result for a
  render entity with the same guid+fileID), else linear
  `(fileID-4300000)//2` against file-order `read_fbx_mesh_node_names`;
  single-mesh ⇒ node[0]; negative-hash ⇒ whole-FBX fallback.
- **R.3 — Collision FBX scrape (Axis A).** Gather collider mesh guids;
  `_process_mesh` any not already copied as a render FBX.
- **R.4 — Writer (Axis B).** Replace the per-entity
  `collider_entity_node_map` param with a list of physx specs
  `[{name, node_paths, convex}]`; emit one group per spec into the
  assetinfo (TriMesh default / convex per flag; identity-omits-rules
  logic from I.1 retained). Works whether the assetinfo also has visual
  groups (art FBX) or not (dedicated COL FBX).
- **R.5 — Component hint.** `ctx.collider_pxmesh_mapping` keyed by
  `(guid, fileID)` → per-sub-mesh pxmesh hint; `_write_mesh_collider`
  resolves through it. Drop the file_id-keyed `.azmodel→.pxmesh` path.
- **R.6 — State index / patch worker.** Store the physx spec list per
  FBX (keyed by output FBX) so the mesh Patch worker re-emits without
  re-parsing prefabs.

### Testing matrix (T1–T4 from `mem:asset_packs/import_catalogue`)
| ID | Pack | Proof |
|---|---|---|
| T1 | Mushroom | collider on mesh GO, same single-mesh FBX ⇒ `{stem}.fbx.pxmesh`, hint resolves |
| T2 | Alien Forest Dead_trunk | collider on parent ⇒ pxmesh from the separate L3 FBX; root entity hint resolves |
| T3 | NatureManufacture road border | collider picks LOD0 sub-mesh of a multi-LOD FBX ⇒ pxmesh for that node only, not whole FBX |
| T4 | Office StairsMod | dedicated `_COL` FBX scraped; 3 sub-meshes ⇒ 3 distinct pxmesh products; 3 colliders resolve to the right one each |
| T5 | unit | TriMesh default / convex flag / identity-omits-rules (carried from I.1) |

**Status (2026-05-28):** R.1–R.6 SHIPPED with the `{stem}-{node_leaf}`
naming. T2/T3/T4 proven end-to-end on the real packs; resolver +
writer + state-index unit/integration tests green. One correctness
hardening landed during T3: `resolve_collision_node` trusts a correlated
render node only when its leaf is a real FBX node, else linear decode
wins (NatureManufacture LOD2/LOD02 GO-vs-FBX name mismatch). Remaining:
in-engine cook verification. See
`mem:physx_mesh_collider/working_documentation`.

## Out of scope
- ImportGroup (`{41DCBEAB…}`) emission — the reference has one but the
  exporter does not require it; revisit only if cook fails without it.
- Aligning component `MaterialSlots` Name to FBX node name.
- Convex decomposition (`DecomposeMeshes`) and primitive fitting.
- Multiple distinct collider meshes per entity (one MeshCollider/entity
  assumed).
