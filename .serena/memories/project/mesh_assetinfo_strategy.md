# Mesh Processing Strategy: Per-Entity Named MeshGroups via .assetinfo

## Core Approach
For every FBX used in a prefab, generate a `.assetinfo` sidecar that defines
one custom `MeshGroup` per mesh entity. Each group selects exactly one FBX node
and gets a clean, predictable name. The prefab's `assetHint`s target these by name.

## Why
- Auto-generated proc group names (`default_Closet_A_3E2AC070_...`) are UUID-based
  and cannot be predicted or targeted from the converter
- A custom MeshGroup named "Closet_A-Glass_L" produces `closet_a-glass_l.fbx.azmodel`
  which IS predictable and can be set as an assetHint
- Confirmed via manual test: `Closet_A-SampleGlassSelect` → targetable asset in O3DE

## FBX Node Path Convention
Unity entity hierarchy directly maps to FBX node paths:
- FBX stem: `Closet_A` (from `Closet_A.FBX`)
- Root entity "Closet_A" → `RootNode.Closet_A`
- Child "Closet_door_L" → `RootNode.Closet_A.Closet_door_L`
- Grandchild "Glass_L" → `RootNode.Closet_A.Closet_door_L.Glass_L`

## MeshGroup Name Format
`{FBX_stem}-{entity_name}` e.g. "Closet_A-Glass_L"
O3DE lowercases output: `closet_a-glass_l.fbx.azmodel`
AssetHint: `{project}/meshes/closet_a-glass_l.fbx.azmodel`

## MeshGroup Schema (confirmed from EvaluationAssets/Manual_O3DE_Closet_A.FBX.assetinfo)
```json
{
    "$type": "{07B356B7-3635-40B5-878A-FAC4EFD5AD86} MeshGroup",
    "name": "Closet_A-Glass_L",
    "nodeSelectionList": {
        "selectedNodes": ["RootNode.Closet_A.Closet_door_L.Glass_L"],
        "unselectedNodes": ["RootNode.Closet_A", "RootNode.Closet_A.Closet_door_L", ...]
    },
    "rules": {
        "rules": [
            {"$type": "CoordinateSystemRule", "useAdvancedData": true}
        ]
    },
    "id": "{GENERATED-UUID}"
}
```

## Data Flow Change
- `_process_mesh(guid)` now returns `Path` (not an assetHint string)
- `mesh_mapping` changes from `{mesh_guid: hint}` to `{entity_file_id: hint}`
- `MeshComponentProcessor.emit` looks up `ctx.mesh_mapping.get(go.file_id)` not `go.mesh_guid`
- After FBX copying, new step in `process_prefab` groups entities by mesh_guid,
  calls `build_fbx_node_paths` + `write_fbx_assetinfo`, builds per-entity hints

## Key Functions (in integrated_asset_processor.py)
- `build_fbx_node_paths(mesh_entities, all_game_objects, fbx_stem)` → `{file_id: node_path}`
- `write_fbx_assetinfo(fbx_dest_path, fbx_stem, entity_node_map, log)` → writes .assetinfo
- `read_fbx_up_axis(fbx_path)` → kept for potential future use (Y-up detection)

## Open: Y-up Axis Correction
`useAdvancedData: true` with no rotation = O3DE default handling.
If meshes appear 90° rotated (Y-up FBX from Maya), may need to add
`"rotation": [0.7071, 0, 0, 0.7071]` to each group's CoordinateSystemRule.
Test in O3DE after implementation to confirm.
