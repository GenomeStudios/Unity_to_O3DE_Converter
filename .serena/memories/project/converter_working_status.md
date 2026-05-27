# Unity-to-O3DE Converter — Working Status (last touched 2026-05-27)

Note: this memory is a long-form snapshot of converter behaviour. Most sections describe the Unity → O3DE pipeline at a level of detail that survives refactors. File paths reflect post-Pass-2 reality: the Stage-2 scene converter and the Stage-3 terrain processor now live under `platforms/unity/`. See `mem:pass2_consolidation/working_documentation` for the migration log.

## Project Overview
Two-stage automated converter: Unity graphical assets/prefabs → O3DE prefabs, then Unity scenes → O3DE levels. The platform-abstraction refactor moved Unity-specific parsers into `platforms/unity/` and standardised on a `SourcePlatform` plugin contract; Pass-2 (2026-05-27) finished the migration by moving the Stage-2 scene converter and Stage-3 terrain processor into the same package and dropping the `components/` re-export shim.

**Active scripts:**
- `integrated_asset_processor.py` — Stage 1: asset + prefab importer (thin worker; parsing delegates to `platforms.unity.prefab`, asset DB delegates to `platforms.unity.asset_database`, O3DE emission delegates to `targets.o3de.{prefab_writer,assetinfo_writer}`)
- `platforms/unity/scene_converter.py` — Stage 2: scene → level converter (was root-level `unity_scene_converter_gui.py` pre-Pass-2). Pure worker; no UI.
- `platforms/unity/terrain.py` — Stage 3: terrain detail material emitter (was root-level `terrain_material_processor.py` pre-Pass-2).
- `main_app.py` — Unified PySide6 GUI entry point.
- `project_manager.py` — Project schema (`.u2oproj.json`), `SourceEngine` enum, `Project` dataclass, materialtype resolver, externally-modified detection.
- `preflight.py` — F-8 preflight + Mission Command checks.
- `converter_settings.json` — recent-projects + global config (gitignored).
- `tools/bake_fbx_transforms.py` — standalone Blender headless tool (out-of-process).

Component processors live in `platforms/unity/components/`; auto-discovery is rooted there. The root-level `components/` shim package was deleted in Pass-2 I.3.

---

## Stage 1: Asset Processor (`integrated_asset_processor.py`)

### Working ✓
- **Prefab discovery**: scrubs source folder, finds `.prefab` files as dependency anchors
- **YAML parsing**: parses Unity prefab multi-doc YAML (anchors pattern), extracts GameObject, Transform, MeshFilter, MeshRenderer, Rigidbody, BoxCollider, SphereCollider, CapsuleCollider, MeshCollider, PrefabInstance
- **Hierarchy building**: resolves transform→GameObject IDs, builds bidirectional parent/child tree
- **Component processor system**: auto-discovered, WEIGHT-ordered plugin modules in `platforms/unity/components/`
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
  - F-9 shader profiles can override texture_map / property_map per Unity shader; the legacy hard-coded map lives in `DEFAULT_SHADER_PROFILE` and is used as the fallback chain root.
  - Writes `.material` files using `StandardPBR.materialtype`
  - Material file names **preserve case** from Unity source (e.g. `Door_MetalDark.azmaterial`)
- **Multi-material slots**: `EditorMaterialComponent` emits `{}` (default slot) + `{0}`, `{1}`, ... indexed slots matching Unity MeshRenderer material list order ✓
- **O3DE prefab generation**: `targets.o3de.prefab_writer.create_o3de_prefab` builds valid `.prefab` JSON with container entity + child entities
- **Nested prefab instances**: `parse_prefab_instance_in_prefab` and `create_nested_prefab_instance` handle prefabs-within-prefabs
- **State index + Patch worker** (F-9): per-asset sha256 input fingerprints under `outputs.state_index`; Patch worker re-emits only dirty assets
- **In-engine modification detection** (F-9.I.6b): mtime vs `last_emitted` (with 1s tolerance) flags assets edited in-engine since last patch
- **FBX .assetinfo generation**:
  - Per-entity named MeshGroups: one group per mesh entity, `{FBX_stem}-{entity_name}` format → predictable assetHint
  - `build_fbx_node_paths`: maps entity file_ids to `RootNode.ModelName.ChildName` FBX paths
  - `write_fbx_assetinfo`: writes Y-up CoordinateSystemRule (per-mesh, complementing the per-Transform swizzle); takes `correction_quat` from the platform plugin
  - `read_fbx_hierarchy` (binary FBX parser): extracts Model/Geometry/Material/LayerElement sub-objects (UV channels, vertex color layers) for full selectedNodes lists
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

Canonical implementation lives in `targets.o3de.prefab_writer.convert_to_o3de_coordinates`. Stage 2's `UnitySceneConverter.convert_to_o3de_coordinates` delegates to it post-Pass-2-I.4 (the local duplicate was deleted). The `platforms/unity/coordinates.py` constant `UNITY_Y_UP_TO_O3DE_Z_UP_QUAT` carries the per-mesh CoordinateSystemRule quaternion.

### Prefab Root Transform — Discarded on Inner Root (added 2026-05-26)
Unity prefabs are always rooted at a single GameObject whose stored transform is dead data: Unity records every PrefabInstance modification as the FINAL `m_LocalPosition` / `m_LocalRotation` / `m_LocalScale`, not a delta on top of the prefab root. Preserving the root GO's stored transform on the converted prefab's inner root entity caused a double-offset (consumer's ContainerEntity patch positioned the world placement, then the inner root entity added the Unity-stored bake on top — observed as 800-unit offsets in the field).

Fix in `create_entity_recursive`: when `parent_entity_id == "ContainerEntity"` (i.e. this is the prefab's root entity), force identity transform and clear `needs_nonuniform` before the Transform Data block is emitted. The ContainerEntity itself is already identity (no Transform Data block in `create_container_entity`); world placement is supplied entirely by the consumer's patches on the ContainerEntity. Discarded values are logged for visibility.

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
- **Material pipeline**: Specular workflow, detail maps, some edge-case shader properties not yet mapped — F-9 profile editor (F-10) is the planned authoring tool for filling these gaps.
- **assetinfo sub-object paths**: `read_fbx_hierarchy` implemented but full wiring of sub-paths (UVChannel, material nodes) into `selectedNodes` in `write_fbx_assetinfo` still in progress.

---

## Stage 2: Scene Converter (`platforms/unity/scene_converter.py`)

### Working ✓
- **Unity scene parsing**: same YAML multi-doc approach, extracts GameObjects + PrefabInstances from `.unity` scene files. Scene-level `PrefabInstance` blocks intentionally use a different parse path from prefab-nested ones — see Pass-2 I.4 note in `mem:pass2_consolidation/working_documentation`.
- **Prefab matching**: `PrefabDatabase` finds O3DE prefabs by GUID (from `.meta` files) or by name fallback; tracks missing prefabs
- **Level generation**: `create_o3de_level` builds O3DE `.prefab`-format level JSON, placing matched prefabs as instances with transforms
- **Coordinate conversion**: same formula as Stage 1 (`x, z, y` / `qx, qz, qy, qw`); delegates to `targets.o3de.prefab_writer.convert_to_o3de_coordinates`
- **Component processor pipeline on unowned entities**: scene entities that are NOT resolved as prefab instances now run the full component processor pipeline (same as Stage 1):
  - During parse: component blocks (BoxCollider, Rigidbody, Light, etc.) collected and dispatched to `processor.parse()`
  - During emit: `processor.emit()` called on every non-prefab entity; physics, directional light, and any other registered processor components are written
  - Mesh and material emit silently skipped (no AssetDatabase in scene converter); physics and light fully functional
  - `_make_bare_entity()` supports overflow collider child entity creation
  - Log callback wired through from GUI to convertor and into ProcessingContext
- **Scene-file robustness**: `_to_int()` in `light.py` handles Unity scene files serialising `m_Shadows` / `m_Type` as nested dicts instead of plain ints
- **Project-driven sidecars**: `UnitySceneConverter.__init__` takes optional `entity_maps_by_stem` and `asset_index` from the project file's `outputs.asset_processor` section, replacing the old `<output>/.ImporterData/*.entitymap.json` and `asset_index.json` reads.

### Known Issues ✗
- **~Matches "nearly all"** prefabs — some prefabs go unmatched (tracked in `missing_prefabs` set)
- Coordinate issue from Stage 1 propagates here
- Mesh/material components not emitted for unowned entities (no asset DB; requires future integration)

---

## Stage 3: Terrain Material Processor (`platforms/unity/terrain.py`)

Slim sibling of IntegratedAssetProcessor focused exclusively on terrain detail material emission from a user-provided list of `.mat` files. Output layout under `<output_root>/Terrain/{Materials,Textures}`. References `TerrainBaseMaterial.materialtype` from the O3DE Terrain gem.

---

## Data Model
```
Transform: position(x,y,z), rotation(qx,qy,qz,qw), scale(x,y,z), is_uniform_scale()
GameObject: file_id, name, transform, components, parent_id, children_ids,
            mesh_guid, material_guids[], has_rigidbody, rigidbody_data,
            colliders[], is_prefab_instance, prefab_source_guid, prefab_name,
            component_data{}, prefab_modifications[],
            prefab_added_components[], prefab_removed_components[],
            prefab_added_gameobjects[]
```
Canonical home: `platforms/unity/types.py`. Both Stage-1 worker and Stage-2 scene converter import from there post-Pass-2.

## Output Structure
```
<output_root>/
  Prefabs/    ← .prefab files
  Materials/  ← .material files (StandardPBR)
  Textures/   ← copied texture files
  Meshes/     ← copied FBX/mesh files + .assetinfo sidecars
  Terrain/    ← terrain detail materials + textures (when Stage-3 ran)
```
The project file `.u2oproj.json` carries `outputs.{asset_processor,scene_converter,terrain}.state_index` and per-stage `entity_maps`, `asset_index`, `coverage`. Converter bookkeeping no longer lands as sidecars on disk.

---

## Override emission tiers (Stage 1 + Stage 2 nested/scene instances)
- **Tier 1 — Transform**: `m_LocalPosition.{x,y,z}`, `m_LocalRotation.{x,y,z,w}`,
  `m_LocalScale.{x,y,z}` emit `/ContainerEntity/.../Translate/{N}`,
  `Rotate/{N}`, and (uniform) `Scale` JSON patches.
- **Tier 2 — m_IsActive**: parsed and logged to coverage; not yet emitted as
  a patch because the O3DE disabled-entity field is not yet confirmed.
- **Tier 3 — `m_Materials.Array.data[N]`**: resolved via entity-map (target.fileID → entity_alias) and asset_index (new_mat_guid → assetHint); emits `/Entities/<alias>/Components/EditorMaterialComponent/Controller/Configuration/materials/{N}/MaterialAsset/assetHint`.
- **Everything else** (light intensity, rigidbody mass, collider size, etc.) is recorded as unhandled in `coverage` so the user gets an explicit punch list rather than silent data loss.

Sibling-field accounting (`m_AddedComponents`, `m_RemovedComponents`, `m_AddedGameObjects`) is counted into coverage and warned about, but the emission paths require larger surgery and are not implemented.

### Coverage report (CoverageTracker class in integrated_asset_processor.py)
- Tracks every Unity component type seen during parse, with handler resolution.
- Tracks every prefab override propertyPath (with `[N]` collapsed to `[*]`), with handled/unhandled counts and up to 3 example values per path.
- Tracks missing texture/mesh/material/prefab GUIDs.
- Tracks Unity light m_Type counts (Spot/Directional/Point/Area).
- Stores free-form warnings the converter wanted to surface.
- Stage 1 stashes coverage into `Project.outputs_by_platform[active].asset_processor.coverage` at finalize.
- Stage 2 stashes coverage into `Project.outputs_by_platform[active].scene_converter.coverage` at finalize.

### Known limitations
- Material-slot overrides are keyed by `target.fileID`, which is the MeshRenderer's fileID inside the source prefab. The current entity-map's `entity_aliases` map is keyed by GameObject fileID; renderer-component IDs are not recorded yet. Material override emission only works when the override happens to target a fileID that matches a GO alias. Improvement here is the next iteration of override propagation.
- m_IsActive emits no patch (logged to coverage only).
- Non-uniform scale overrides log a warning instead of emitting an EditorNonUniformScaleComponent patch.
- Added/removed components and added GameObjects are counted but not emitted.

---

## Next Priority Areas
1. AssetDatabase wiring in Stage 2 so mesh/material emit on unowned entities works.
2. Record renderer-component fileIDs in the entity-map so material slot overrides resolve reliably regardless of where the user authored them.
3. Confirm O3DE disabled-entity schema and emit m_IsActive patches.
4. Complete sub-object path integration in `write_fbx_assetinfo` (UV channels, material nodes in selectedNodes).
5. Debug/verify collider shape offset pipeline end-to-end.
6. F-7 terrain heightmap extraction.
7. F-10 profile editor UI for filling out the shader-profile library.
8. Full Unity-parser unification (see Pass-2 I.4 deferred note) — needs a flag on the canonical parser to support both scene-placement and nested-reference PrefabInstance semantics.
9. Non-uniform scale end-to-end verification.
