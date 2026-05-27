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
  - `mesh.py` (25), `material.py` (50), `rigidbody.py` (75), `box_collider.py` (100), `sphere_collider.py` (125), `capsule_collider.py` (150), `mesh_collider.py` (175), `light.py` (510)
- **Texture scraping**: copies textures to `Textures/` output dir, tracks by GUID
- **Mesh scraping**: copies FBX/mesh files to `Meshes/` output dir
- **Material pipeline**:
  - Texture map: `_MainTex/_BaseMap` → `baseColor`, `_BumpMap/_NormalMap` → `normal`, `_MetallicGlossMap` → `metallic` + `roughness`, `_OcclusionMap` → `occlusion`, `_EmissionMap` → `emissive`, `_HeightMap` → `height`
  - Scalar: `_BumpScale`, color `_Color/_BaseColor`. Metallic/roughness are reconciled in a dedicated post-pass — see below.
  - **Metallic/roughness reconciliation** (added 2026-05-25): O3DE StandardPBR has texture-aware property semantics. The post-pass in `_extract_material_data` collects raw Unity scalars (`_Metallic`, `_Smoothness`, `_Glossiness`, `_GlossMapScale`) and routes them based on whether a texture is bound:
    - Metallic — texture bound → no factor written (O3DE ignores it). No texture → `metallic.factor = _Metallic`.
    - Roughness — texture bound → `roughness.lowerBound = 1 − multiplier`, `roughness.upperBound = 1.0`. Multiplier is `_GlossMapScale` (Standard shader) if present, else `_Smoothness`/`_Glossiness` (URP collapses both roles into `_Smoothness`). No texture → `roughness.factor = 1 − smoothness`.
    - Caveat: Unity's `_MetallicGlossMap` stores smoothness in the alpha channel. O3DE samples the bound texture directly as roughness, so the alpha would have to be pre-inverted at copy time for the *texture content* to look correct. Currently NOT done — the bound texture's alpha is read as-is, which inverts shiny/dull on materials that use the metallic-gloss map. Bounds remap is still correct mathematically.
  - Transparency: Unity `_Surface=1` or `_Mode>=2` → `opacity.mode = "Blended"`; alpha clip via `_AlphaClip` or `_Mode==1`
  - **`opacity.alphaSource = "Packed"`** is emitted for both Cutout and Blended (fixed 2026-05-25). Without it, O3DE StandardPBR ignores the alpha channel of the baseColor texture and renders fully opaque regardless of opacity.mode. `opacity.factor` carries `_Cutoff` for Cutout.
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
- **Shape component defaults**: `EditorBoxShapeComponent` emits `DisplayFilled: false` + `IsFilled: false`; all shape colliders emit `DebugDrawSettings: {LocallyEnabled: false}`

### Unified Light (`light.py`, weight=510)
Single processor handles all Unity `Light` types via `m_Type` dispatch. Supersedes the
earlier `directional_light.py` (removed 2026-05-25).
- **Directional (m_Type=1)** → `AZ::Render::EditorDirectionalLightComponent`.
  Applies a 180° pitch flip to the TransformComponent on emit to correct the
  Unity↔O3DE forward-axis mismatch (without this, light shines from below).
- **Point (m_Type=2)** → `AZ::Render::EditorAreaLightComponent` with `LightType=1`
  (Sphere), plus an `EditorSphereShapeComponent` (radius `DEFAULT_SPHERE_RADIUS=0.05`)
  giving the emitter a physical size. IntensityMode=Lumen.
- **Spot (m_Type=0)** → `AZ::Render::EditorAreaLightComponent` with `LightType=7`
  (SimpleSpot). Unity stores `m_SpotAngle`/`m_InnerSpotAngle` as full cone angles;
  the processor halves them to feed O3DE's `Outer/InnerShutterAngleDegrees`.
  IntensityMode=Candela. EnableShutters=True.
- **Area (m_Type=3)** → `AZ::Render::EditorAreaLightComponent` with `LightType=6`
  (SimplePoint) as a runtime approximation; Unity area lights are baked-only and
  have no direct real-time equivalent. IntensityMode=Lumen, GI enabled.
- **Scene-safe parsing**: `m_Shadows` and `m_Type` may be plain ints (prefab files)
  or nested dicts (scene files); `_to_int()` helper handles both formats.
- **Dispatch precedence note**: `build_dispatch_table` is last-write-wins by WEIGHT
  ascending order. `light.py` (weight 510) registers last for the `Light` type, so
  it is the active parser. All processors' `emit()` methods always run; light.py's
  emit short-circuits when `go.component_data['unity_light']` is unset.

### Coordinate Conversion (CORRECTED as of 2026-03-14)
Unity → O3DE axis swap:
- Position: `(x, z, y)` — Y↔Z swap only, **no X negation**
- Rotation quaternion: `(qx, qz, qy, qw)` — **no X negation**
- Scale: `(sx, sz, sy)`
- Shape collider centers: `(cx, cz, cy)` — **no X negation**

Previous versions negated X; this was incorrect and has been removed from:
- `unity_scene_converter_gui.py` (`convert_to_o3de_coordinates`)
- `components/box_collider.py`, `sphere_collider.py`, `capsule_collider.py`

### Prefab Root Transform — Discarded on Inner Root (added 2026-05-26)
Unity prefabs are always rooted at a single GameObject whose stored transform is dead data: Unity records every PrefabInstance modification as the FINAL `m_LocalPosition` / `m_LocalRotation` / `m_LocalScale`, not a delta on top of the prefab root. Preserving the root GO's stored transform on the converted prefab's inner root entity caused a double-offset (consumer's ContainerEntity patch positioned the world placement, then the inner root entity added the Unity-stored bake on top — observed as 800-unit offsets in the field).

Fix in `_create_entity_recursive`: when `parent_entity_id == "ContainerEntity"` (i.e. this is the prefab's root entity), force identity transform and clear `needs_nonuniform` before the Transform Data block is emitted. The ContainerEntity itself is already identity (no Transform Data block in `_create_container_entity`); world placement is supplied entirely by the consumer's patches on the ContainerEntity. Discarded values are logged for visibility.

Caveat: if a Unity prefab root has an intentionally non-identity scale (rare for asset-pack content but possible for hand-authored prefabs), it's discarded too. The warning log surfaces this so the user can spot intentional bakes that need to be applied to children manually.

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
- **Component processor pipeline on unowned entities**: scene entities that are NOT resolved as prefab instances now run the full component processor pipeline (same as Stage 1):
  - During parse: component blocks (BoxCollider, Rigidbody, Light, etc.) collected and dispatched to `processor.parse()`
  - During emit: `processor.emit()` called on every non-prefab entity; physics, directional light, and any other registered processor components are written
  - `GameObject` dataclass extended with `has_rigidbody`, `colliders`, `mesh_guid`, `material_guids`, `component_data` fields
  - Mesh and material emit silently skipped (no AssetDatabase in scene converter); physics and light fully functional
  - `_make_bare_entity()` added to support overflow collider child entity creation
  - Log callback wired through from GUI to convertor and into ProcessingContext
- **Scene-file robustness**: `_to_int()` in `light.py` handles Unity scene files serializing `m_Shadows` / `m_Type` as nested dicts instead of plain ints

### Known Issues ✗
- **~Matches "nearly all"** prefabs — some prefabs go unmatched (tracked in `missing_prefabs` set)
- Coordinate issue from Stage 1 propagates here
- Mesh/material components not emitted for unowned entities (no asset DB; requires future integration)

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

---

## Prefab Override Propagation + Coverage Reporting (added 2026-05-25)

### Sidecars and indexes
All converter bookkeeping lives in **`<output_root>/.ImporterData/`** —
intentionally a dotfile-prefixed directory so the O3DE Asset Processor
ignores it. Created by `IntegratedAssetProcessor.__init__` and mirrored on
the Stage 2 side by `UnitySceneConverter.finalize`. Contents:

- **`<stem>.entitymap.json`** — one per converted prefab.
  Records `{source_guid, source_path, root_entity, container_alias,
  entity_aliases: {unity_file_id: o3de_entity_alias}, material_slots:
  {unity_file_id: [mat_guid_0, mat_guid_1, ...]}, go_names}`.
  Consumed by nested-instance override emission to translate Unity fileIDs
  inside `m_Modifications.target` into the right O3DE entity alias.
- **`asset_index.json`** — one per run. Records
  `{materials: {guid: assetHint}, meshes: {guid: stem}, prefabs: {guid: source_path}}`.
  Consumed by Stage 2 (and any cross-prefab override resolution) to translate
  Unity GUIDs to O3DE asset hints without re-walking the project.
- **`coverage.json`** — one per run. The end-of-run punch list of unhandled
  component types, unhandled override paths, missing assets, warnings.

These files are NOT O3DE artifacts. O3DE has no `.entitymap.json` type and
does not consume any file in `.ImporterData/`. Located here purely to keep
the Asset Processor from scanning them.

The Stage 1 entrypoint requires `processor.finalize()` to be called after the
last `process_prefab()` to write these artifacts. main_app.py is updated;
external callers must do the same.

### Override emission tiers (Stage 1 + Stage 2 nested/scene instances)
- **Tier 1 — Transform**: `m_LocalPosition.{x,y,z}`, `m_LocalRotation.{x,y,z,w}`,
  `m_LocalScale.{x,y,z}` emit `/ContainerEntity/.../Translate/{N}`,
  `Rotate/{N}`, and (uniform) `Scale` JSON patches.
- **Tier 2 — m_IsActive**: parsed and logged to coverage; not yet emitted as
  a patch because the O3DE disabled-entity field is not yet confirmed.
- **Tier 3 — `m_Materials.Array.data[N]`**: resolved via sidecar
  (`target.fileID` → `entity_alias`) and asset_index (`new_mat_guid` →
  `assetHint`); emits `/Entities/<alias>/Components/EditorMaterialComponent/
  Controller/Configuration/materials/{N}/MaterialAsset/assetHint`.
- **Everything else** (light intensity, rigidbody mass, collider size, etc.)
  is recorded as unhandled in `coverage.json` so the user gets an explicit
  punch list rather than silent data loss.

Sibling-field accounting (`m_AddedComponents`, `m_RemovedComponents`,
`m_AddedGameObjects`) is counted into coverage and warned about, but the
emission paths require larger surgery and are not implemented.

### Coverage report (CoverageTracker class in integrated_asset_processor.py)
- Tracks every Unity component type seen during parse, with handler resolution.
- Tracks every prefab override propertyPath (with `[N]` collapsed to `[*]`),
  with handled/unhandled counts and up to 3 example values per path.
- Tracks missing texture/mesh/material/prefab GUIDs.
- Tracks Unity light m_Type counts (Spot/Directional/Point/Area).
- Stores free-form warnings the converter wanted to surface.
- Stage 1 writes `<output_root>/coverage.json` from `finalize()`.
- Stage 2 writes `<scene_output_dir>/coverage.json` from `converter.finalize(output_dir)`.

### Known limitations
- Material-slot overrides are keyed by `target.fileID`, which is the
  MeshRenderer's fileID inside the source prefab. The current sidecar's
  `entity_aliases` map is keyed by GameObject fileID; renderer-component IDs
  are not recorded yet. Material override emission only works when the
  override happens to target a fileID that matches a GO alias. Improvement
  here is the next iteration of override propagation.
- m_IsActive emits no patch (logged to coverage only).
- Non-uniform scale overrides log a warning instead of emitting an
  EditorNonUniformScaleComponent patch.
- Added/removed components and added GameObjects are counted but not emitted.

---

## Next Priority Areas
1. Record renderer-component fileIDs in the entity-map sidecar so material
   slot overrides resolve reliably regardless of where the user authored them.
2. Confirm O3DE disabled-entity schema and emit m_IsActive patches.
3. Complete sub-object path integration in `write_fbx_assetinfo` (UV channels, material nodes in selectedNodes)
4. Debug/verify collider shape offset pipeline end-to-end
5. Finalize material pipeline (specular workflow, detail maps)
6. Non-uniform scale end-to-end verification
7. Add AssetDatabase support to scene converter for mesh/material emit on unowned entities
