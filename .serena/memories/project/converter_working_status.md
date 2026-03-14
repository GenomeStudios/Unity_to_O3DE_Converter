# Unity-to-O3DE Converter — Working Status (as of 2026-03-13)

## Project Overview
Two-stage automated converter: Unity graphical assets/prefabs → O3DE prefabs, then Unity scenes → O3DE levels.

**Active scripts** (ignore `legacy_unity_prefab_to_o3de.py` and `bake_fbx_transforms.py`):
- `integrated_asset_processor.py` — Stage 1: asset + prefab importer (GUI: `IntegratedProcessorGUI`)
- `unity_scene_converter_gui.py` — Stage 2: scene → level converter (GUI: `SceneConverterGUI`)
- `converter_settings.json` — shared settings file persisting GUI paths between sessions

---

## Stage 1: Asset Processor (`integrated_asset_processor.py`)

### Working ✓
- **Prefab discovery**: scrubs source folder, finds `.prefab` files as dependency anchors
- **YAML parsing**: parses Unity prefab multi-doc YAML (anchors pattern), extracts GameObject, Transform, MeshFilter, MeshRenderer, Rigidbody, BoxCollider, SphereCollider, CapsuleCollider, MeshCollider, PrefabInstance
- **Hierarchy building**: resolves transform→GameObject IDs, builds bidirectional parent/child tree
- **Texture scraping**: copies textures to `Textures/` output dir, tracks by GUID
- **Mesh scraping**: copies FBX/mesh files to `Meshes/` output dir
- **Material pipeline (partial)**:
  - Texture map: `_MainTex/_BaseMap` → `baseColor`, `_BumpMap/_NormalMap` → `normal`, `_MetallicGlossMap` → `metallic` + `roughness` (same texture), `_OcclusionMap` → `occlusion.specularTextureMap`, `_EmissionMap` → `emissive`, `_HeightMap/_ParallaxMap` → `height`
  - Scalar map: `_Metallic`, `_Smoothness`/`_Glossiness` (inverted to roughness), `_BumpScale`, color `_Color/_BaseColor`, emission color
  - Transparency detection: Unity `_Surface=1` or `_Mode>=2` → `opacity.mode = "Blended"`; alpha clip via `_AlphaClip` or `_Mode==1`
  - Writes `.material` files using `StandardPBR.materialtype`
  - Uses relative paths (`../Textures/filename`) from `Materials/` folder
  - **Needs more work**: full material pipeline not finalized (e.g. specular workflow, detail maps)
- **Multi-material slots**: `EditorMaterialComponent` uses indexed slots `{0}`, `{1}`, etc. matching Unity's MeshRenderer material list order ✓
- **O3DE prefab generation**: `_create_o3de_prefab` builds valid `.prefab` JSON with container entity + child entities
- **Nested prefab instances**: `_parse_prefab_instance_in_prefab` and `_create_nested_prefab_instance` handle prefabs-within-prefabs
- **Settings persistence**: GUI saves/loads source path, output path, blender path to `converter_settings.json` under key `"asset_processor"`
- **Blender integration**: `bake_fbx_with_blender` exists and is wired in, but Blender bake pass is **completely ineffectual** for fixing coordinate issues (see known issue below)

### Physics — Code Present, Needs Verification ⚠
- **`_parse_collider_data`**: parses center, size (Box), radius (Sphere/Capsule), height+direction (Capsule), mesh GUID + convex flag (MeshCollider), is_trigger flag
- **`_create_physx_components`**: 
  - Box → `EditorBoxShapeComponent` + `EditorShapeColliderComponent`
  - Sphere → `EditorSphereShapeComponent` + `EditorShapeColliderComponent`
  - Capsule → `EditorCapsuleShapeComponent` + `EditorShapeColliderComponent`
  - MeshCollider → `EditorMeshColliderComponent`
  - Rigidbody → `EditorRigidBodyComponent` with mass, drag, angular drag, gravity, kinematic, constraint bitmask axis-swapped (Unity Y↔Z)
  - No Rigidbody + has colliders → `EditorStaticRigidBodyComponent`
  - Multi-collider: extras become child entities `{Name}_Collider_{N}`
- **User reports**: "collision and rigidbody detection not yet working" — code structure is in place as of last commit; may have bugs in component linkage or detection

### Known Issues ✗
- **Coordinate system / mesh rebaking**: Major issue. Unity rebakes mesh coordinates internally (not native to raw FBX). Coordinate conversion formula is: position `(-x, z, y)`, quaternion `(-qx, qz, qy, qw)`, scale `(sx, sz, sy)`. This handles the Y-up→Z-up swap, but Unity's mesh-baked transforms are not properly accounted for. Blender bake pass attempted and abandoned.
- **Non-uniform scale**: `EditorNonUniformScaleComponent` is written when scale is non-uniform (axes differ > 0.0001). However uniform scale path only writes `scale[0]` as scalar. Non-uniform scale component writing is implemented but the underlying mesh coordinate issue may make results wrong.

---

## Stage 2: Scene Converter (`unity_scene_converter_gui.py`)

### Working ✓
- **Unity scene parsing**: same YAML multi-doc approach, extracts GameObjects + PrefabInstances from `.unity` scene files
- **Prefab matching**: `PrefabDatabase` finds O3DE prefabs by GUID (from `.meta` files) or by name fallback; tracks missing prefabs
- **Level generation**: `create_o3de_level` builds O3DE `.prefab`-format level JSON, placing matched prefabs as instances with transforms
- **Coordinate conversion**: identical formula to Stage 1 (`-x, z, y` / `-qx, qz, qy, qw`)
- **Settings persistence**: saves scene path, output path, prefab directory list

### Known Issues ✗
- **~Matches "nearly all"** prefabs — some prefabs go unmatched (tracked in `missing_prefabs` set)
- Same coordinate issue as Stage 1 propagates here

---

## Data Model
```
Transform: position(x,y,z), rotation(qx,qy,qz,qw), scale(x,y,z), is_uniform_scale()
GameObject: file_id, name, transform, components, parent_id, children_ids,
            mesh_guid, material_guids[], has_rigidbody, rigidbody_data,
            colliders[], is_prefab_instance, prefab_source_guid
```

## Output Structure
```
<output_root>/
  Prefabs/    ← .prefab files
  Materials/  ← .material files (StandardPBR)
  Textures/   ← copied texture files
  Meshes/     ← copied FBX/mesh files
```

## Next Priority Areas
1. Debug/verify collider+rigidbody detection pipeline (may be a component→GO linkage bug)
2. Resolve mesh coordinate system issue (Unity internal bake vs raw FBX coordinates)
3. Finalize material pipeline (specular workflow, detail maps, etc.)
4. Non-uniform scale end-to-end verification
