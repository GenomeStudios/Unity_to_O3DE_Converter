# Unity-to-O3DE Converter — Working Status (as of 2026-03-14)

## Project Overview
Two-stage automated converter: Unity graphical assets/prefabs → O3DE prefabs, then Unity scenes → O3DE levels.

**Active scripts** (ignore `legacy_unity_prefab_to_o3de.py` and `bake_fbx_transforms.py`):
- `integrated_asset_processor.py` — Stage 1: asset + prefab importer
- `unity_scene_converter_gui.py` — Stage 2: scene → level converter
- `main_app.py` — Unified PySide6 GUI entry point (two-tab: Prefab Processor + Scene Converter)
- `converter_settings.json` — shared settings file persisting GUI paths between sessions

---

## Stage 1: Asset Processor (`integrated_asset_processor.py`)

### Working ✓
- **Prefab discovery**: scrubs source folder, finds `.prefab` files as dependency anchors
- **YAML parsing**: parses Unity prefab multi-doc YAML (anchors pattern), extracts GameObject, Transform, MeshFilter, MeshRenderer, Rigidbody, BoxCollider, SphereCollider, CapsuleCollider, MeshCollider, PrefabInstance
- **Hierarchy building**: resolves transform→GameObject IDs, builds bidirectional parent/child tree
- **Component processor system**: auto-discovered, WEIGHT-ordered plugin modules in `components/` directory
  - `mesh.py` (25), `material.py` (50), `rigidbody.py` (75), `box_collider.py` (100), `sphere_collider.py` (125), `capsule_collider.py` (150), `mesh_collider.py` (175)
- **Texture scraping**: copies textures to `Textures/` output dir, tracks by GUID
- **Mesh scraping**: copies FBX/mesh files to `Meshes/` output dir
- **Material pipeline**:
  - Texture map: `_MainTex/_BaseMap` → `baseColor`, `_BumpMap/_NormalMap` → `normal`, `_MetallicGlossMap` → `metallic` + `roughness`, `_OcclusionMap` → `occlusion`, `_EmissionMap` → `emissive`, `_HeightMap` → `height`
  - Scalar: `_Metallic`, `_Smoothness`/`_Glossiness` (inverted to roughness), `_BumpScale`, color `_Color/_BaseColor`
  - Transparency: Unity `_Surface=1` or `_Mode>=2` → `opacity.mode = "Blended"`; alpha clip via `_AlphaClip` or `_Mode==1`
  - Writes `.material` files using `StandardPBR.materialtype`
  - Material file names **preserve case** from Unity source (e.g. `Door_MetalDark.azmaterial`)
- **Multi-material slots**: `EditorMaterialComponent` emits `{}` (default slot) + `{0}`, `{1}`, ... indexed slots matching Unity MeshRenderer material list order ✓
- **O3DE prefab generation**: `_create_o3de_prefab` builds valid `.prefab` JSON with container entity + child entities
- **Nested prefab instances**: `_parse_prefab_instance_in_prefab` and `_create_nested_prefab_instance` handle prefabs-within-prefabs
- **Settings persistence**: GUI saves/loads source/output/blender paths to `converter_settings.json`
- **FBX .assetinfo generation**:
  - Per-entity named MeshGroups: one group per mesh entity, `{FBX_stem}-{entity_name}` format → predictable assetHint
  - `build_fbx_node_paths`: maps entity file_ids to `RootNode.ModelName.ChildName` FBX paths
  - `write_fbx_assetinfo`: writes Y-up CoordinateSystemRule, selectedNodes always starts with `"RootNode"`
  - `read_fbx_hierarchy` (binary FBX parser): extracts Model/Geometry/Material/LayerElement sub-objects (UV channels, vertex color layers) for full selectedNodes lists
  - Sub-object path detection wired; full integration of hierarchy sub-paths still in progress

### Coordinate Conversion (CORRECTED as of 2026-03-14)
Unity → O3DE axis swap:
- Position: `(x, z, y)` — Y↔Z swap only, **no X negation**
- Rotation quaternion: `(qx, qz, qy, qw)` — **no X negation**
- Scale: `(sx, sz, sy)`
- Shape collider centers: `(cx, cz, cy)` — **no X negation**

Previous versions negated X; this was incorrect and has been removed from:
- `unity_scene_converter_gui.py` (`convert_to_o3de_coordinates`)
- `components/box_collider.py`, `sphere_collider.py`, `capsule_collider.py`

### Physics — Code Present, Needs Verification ⚠
- **`_parse_collider_data`**: parses center, size (Box), radius (Sphere/Capsule), height+direction (Capsule), mesh GUID + convex flag (MeshCollider), is_trigger flag
- **`_create_physx_components`**: Box/Sphere/Capsule/MeshCollider all emitting correct shape + ShapeCollider components
- Rigidbody → `EditorRigidBodyComponent` with mass, drag, angular drag, gravity, kinematic, constraint bitmask axis-swapped
- No Rigidbody + has colliders → `EditorStaticRigidBodyComponent`
- Multi-collider: extras become child entities `{Name}_Collider_{N}`
- **User reports**: collision/rigidbody may have bugs in component linkage; shape offsets need field verification

### Known Issues ✗
- **Mesh coordinate / pivot**: Unity internally rebakes mesh coordinates. Coordinate conversion handles Y-up→Z-up swap correctly now (no X negation), but Unity's internal mesh pivot bake vs raw FBX coordinates can still cause offsets on some assets.
- **Non-uniform scale**: `EditorNonUniformScaleComponent` is written when scale is non-uniform. Uniform scale path writes `scale[0]` as scalar. End-to-end verification not complete.
- **Material pipeline**: Specular workflow, detail maps, some edge-case shader properties not yet mapped.
- **assetinfo sub-object paths**: `read_fbx_hierarchy` implemented but full wiring of sub-paths (UVChannel, material nodes) into `selectedNodes` in `write_fbx_assetinfo` still in progress.

---

## Stage 2: Scene Converter (`unity_scene_converter_gui.py`)

### Working ✓
- **Unity scene parsing**: same YAML multi-doc approach, extracts GameObjects + PrefabInstances from `.unity` scene files
- **Prefab matching**: `PrefabDatabase` finds O3DE prefabs by GUID (from `.meta` files) or by name fallback; tracks missing prefabs
- **Level generation**: `create_o3de_level` builds O3DE `.prefab`-format level JSON, placing matched prefabs as instances with transforms
- **Coordinate conversion**: same formula as Stage 1 (`x, z, y` / `qx, qz, qy, qw`)
- **Settings persistence**: saves scene path, output path, prefab directory list

### Known Issues ✗
- **~Matches "nearly all"** prefabs — some prefabs go unmatched (tracked in `missing_prefabs` set)
- Coordinate issue from Stage 1 propagates here

---

## Data Model
```
Transform: position(x,y,z), rotation(qx,qy,qz,qw), scale(x,y,z), is_uniform_scale()
GameObject: file_id, name, transform, components, parent_id, children_ids,
            mesh_guid, material_guids[], has_rigidbody, rigidbody_data,
            colliders[], is_prefab_instance, prefab_source_guid, component_data{}
```

## Output Structure
```
<output_root>/
  Prefabs/    ← .prefab files
  Materials/  ← .material files (StandardPBR)
  Textures/   ← copied texture files
  Meshes/     ← copied FBX/mesh files + .assetinfo sidecars
```

## Next Priority Areas
1. Complete sub-object path integration in `write_fbx_assetinfo` (UV channels, material nodes in selectedNodes)
2. Debug/verify collider shape offset pipeline end-to-end
3. Finalize material pipeline (specular workflow, detail maps)
4. Non-uniform scale end-to-end verification
