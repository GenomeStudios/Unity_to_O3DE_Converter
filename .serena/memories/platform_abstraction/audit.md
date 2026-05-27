---
name: platform-abstraction-audit
description: System-wide audit of platform-agnostic core vs Unity-coupled code paths. The line third-party developers cross to plug in non-Unity source engines.
metadata:
  type: project
---

# Platform Abstraction — System-Wide Audit

This memo is the cartography of the converter as of 2026-05-27 (post-F-9 / post-F-8). It separates the codebase into two domains:

1. **PAC** — Platform-Agnostic Core. The structure / systems / workflows that survive any source engine. Preserved as-is.
2. **UNS** — Unity-Specific Surface. Code that reads Unity files, knows Unity property names, or assumes Unity conventions. Scoped behind the platform plugin contract.

The audit also defines the **Platform Plugin Contract** — the interface a non-Unity developer would implement to slot in Unreal / Godot / Blender support without touching the core.

Linked features: [[output-propagation-plan]] (F-9 — already established the
output-side abstraction with shader profiles), [[orchestration-plan]] (F-8),
[[material-component-label-resolution-plan]] (component-processor plugin
system — the prototype this audit generalises).

---

## Part 1 — Platform-Agnostic Core (PAC)

These files / classes / signals are **engine-neutral**. They orchestrate the
workflow but never speak Unity directly. Third-party platform plugins
read and write to these surfaces but don't replace them.

### 1.1 Project system

`project_manager.py`:
- `Project` dataclass: `name`, `notes`, `created`, `modified`, `stages`,
  `pipeline_status`, `outputs`, `scope_root`, `preflight_acks`.
- `SourceEngine` enum: `UNITY / UNREAL / GODOT / BLENDER`. **Already
  positioned as the platform selector.**
- `ProjectManager(QObject)` singleton: new/open/save/save_as, recent
  list, current-project broker.
- `PROJECT_FILE_EXT = ".u2oproj.json"` — the on-disk record.
- `_default_stages()`, `_default_outputs()`, `_default_status()`,
  `_deep_merge()` — schema scaffolding.

**Stays PAC.** The Project carries platform-specific data inside
`stages` / `outputs` opaquely; the project file itself stays
engine-neutral.

### 1.2 State index + patching

`integrated_asset_processor.py` (parts):
- `_canonical_hash(payload)` — sha256-over-canonical-JSON. Engine-neutral.
- State index buckets (`materials/meshes/textures/prefabs`) — engine-neutral
  shape. Per-entry `input_hash` is computed from data the platform plugin
  produces (source mtime + profile + override), so the bucket structure
  doesn't care what platform fed it.
- `IntegratedAssetProcessor.patch()` — generic dirty-detect / re-emit
  loop. Calls `_process_material(guid)`, which the platform plugin
  re-implements; the orchestration is neutral.

**Stays PAC** with one rename — `IntegratedAssetProcessor` is presently
named for the role it plays (asset_processor stage worker) but lives in
a file whose name suggests it's the union of all responsibilities. Splits
out cleanly: the patch loop / state recording is core; the prefab parse /
material extract / O3DE-prefab emit are Unity-Specific.

### 1.3 Materialtype resolver

`project_manager.py::resolve_materialtype_path(value)`:
- Knows O3DE's `@gemroot:Atom_Feature_Common@/...` syntax.
- Knows the StandardPBR / BasePBR / EnhancedPBR builtins.

This is **O3DE-specific, not Unity-specific**. Stays in core because every
platform plugin targets the same O3DE output surface. If we later add
non-O3DE output targets, this becomes target-platform-specific too — but
that's not in scope.

### 1.4 Externally-modified detection

`project_manager.py::detect_externally_modified(state_index)`:
- mtime vs last_emitted, 1s tolerance.
- Buckets keyed materials/meshes/textures/prefabs.

**Stays PAC.** Reads only the state_index which is engine-neutral.

### 1.5 Shader profile data model

`project_manager.py`:
- `DEFAULT_SHADER_PROFILE` dict shape:
  ```
  description, target_materialtype, texture_map, property_map,
  ignore_unmapped, special_rules
  ```
- `DEFAULT_PROFILE_NAME = "Default — Anything to PBR"`.

The profile **schema** is PAC. The default profile's *contents*
(`_MainTex → baseColor`, `_BumpMap → normal`, `_MetallicGlossMap →
metallic`, etc.) are UNS — they assume Unity property names.

### 1.6 Preflight system

`preflight.py`:
- `PreflightItem`, `PreflightReport`, `_snapshot_hash`.
- `CHECK_REGISTRY` list + `run_preflight(project, deps_present)`.
- Check functions: most are PAC (they read `selected_prefabs`,
  `selected_scenes`, etc. — opaque string lists). The
  `check_material_processor` body is currently UNS-tinted because it
  expects Unity-shaped `material_metadata` (shader_name string), but
  the shape itself can be carried by any platform.

**Mostly PAC.** Each check is composable; non-Unity platforms add their
own check functions to `CHECK_REGISTRY` (or extend the existing ones
via the platform plugin).

### 1.7 Orchestration

`main_app.py`:
- `PipelineOrchestrator(QObject)` — drives stages in dependency order
  via `processing_changed` listeners.
- `_compute_queue` — reads `selected_prefabs / selected_scenes /
  selected_materials` from stages.

**Stays PAC.** Stage queue is selection-driven; selection lists are
opaque strings the orchestrator never inspects.

### 1.8 UI shell

`main_app.py`:
- `MainWindow` — title bar, dep banner, tab dispatch.
- `DashboardTab` — Pipeline Status cards + Preflight panel +
  activity log.
- `ProjectHeaderBanner` — name + engine + scope root + notes.
- `_PreflightPanel` — severity rendering + Acknowledge.
- `CustomTitleBar`, `DismissibleBanner`, `StageStatusCard`,
  `_PathField`, `_FloatField`, `_NotesEdit`, `_InventoryStubTab` —
  generic widgets.
- `THEME_QSS` — Catppuccin Mocha global stylesheet.

**Stays PAC.** None of these widgets parse Unity content. Per-stage
tabs (PrefabProcessorTab, SceneConverterTab, MeshTab, MaterialTab,
TerrainTab) **read** engine-neutral state from the Project but their
worker code is UNS — see Part 2.

### 1.9 Worker thread abstraction

`main_app.py::WorkerThread(QThread)`:
- Generic fn-runner with log emitter + finished signal.

**Stays PAC.** Workers run any callable.

### 1.10 O3DE output writing primitives

These are O3DE-specific but **target**-platform-specific, not
*source*-platform-specific:
- `_make_bare_entity`, `_create_container_entity`,
  `_create_nested_prefab_instance` — write O3DE prefab JSON.
- `write_fbx_assetinfo` — write O3DE `.assetinfo` sidecar.
- Coordinate-system rule + Y-up correction.

Currently embedded in `integrated_asset_processor.py`. Splits into a
`targets/o3de/` module in the refactor — see Part 4.

---

## Part 2 — Unity-Specific Surface (UNS)

### 2.1 File extensions

- `.prefab` (Unity prefab YAML)
- `.unity` (Unity scene YAML)
- `.mat` (Unity material YAML)
- `.fbx` / `.obj` / `.dae` / `.blend` / `.3ds` / `.max` / `.ma` / `.mb`
  (mesh formats — third-party, but the scrubber uses these)
- `.shader` (Unity ShaderLab — used to resolve shader names)
- `.meta` (Unity GUID sidecar)
- `.terrain` (Unity terrain asset)
- `.controller` (Unity animator)
- `.png/.jpg/.jpeg/.tga/.tif/.tiff/.bmp/.psd/.exr/.hdr` (textures —
  source-neutral but discovered via Unity .meta sidecars)

### 2.2 Unity parsers

`integrated_asset_processor.py`:
- `AssetDatabase`:
  - `_build_guid_index` — walks `.meta` files. **UNS** (Unity GUID
    scheme).
  - `resolve_guid(guid) → Path` — Unity GUID → file path.
  - `path_to_guid(path) → guid` — reverse lookup.
  - `parse_material(path, profile)` — parses Unity .mat YAML.
  - `_extract_material_data` — Unity `m_TexEnvs / m_Floats / m_Colors`
    extraction.
- Per-prefab parsing:
  - `_parse_unity_prefab(path)` — Unity prefab YAML doc walker.
  - `_parse_transform`, `_parse_game_object`,
    `_parse_prefab_instance_in_prefab`.
  - `_build_hierarchy` — Unity Transform parent-child resolution.
- Per-material:
  - `_process_material(guid)` — Unity-keyed; reads m_Shader ref,
    resolves shader name via .shader file.
  - `_resolve_shader_name(shader_guid, shader_fileid)` — opens .shader
    file, regex-extracts the `Shader "Name"` declaration. Has built-in
    fallback table for Unity Standard / Standard (Specular setup).
  - `_UNITY_BUILTIN_SHADERS = {4: "Standard", 46: "Standard (Specular setup)"}`.
- Per-texture:
  - `_process_texture(guid)`, `_process_metallic_gloss_as_roughness`.
- Per-mesh:
  - `_process_mesh(guid)` — copies FBX through.
- `_quaternion_to_euler` — Unity quat order (xyzw, Y-up).
- `_convert_to_o3de_coordinates` — Unity-space → O3DE-space swap.

`unity_scene_converter_gui.py`:
- `Transform`, `GameObject`, `PrefabDatabase`, `UnitySceneConverter`.
  Parses Unity .unity scene files. Same YAML pattern as prefab
  processor.

`terrain_material_processor.py`:
- Reads Unity .mat files, copies textures, writes O3DE .material.
  Pure Unity-source, O3DE-target.

`bake_fbx_transforms.py`:
- FBX binary manipulation; format-specific but engine-neutral
  enough to live in a `format/fbx/` module.

`legacy_unity_prefab_to_o3de.py`:
- Old single-pass converter. Either deprecated or migrate to plugin.

### 2.3 Unity component types

`components/`:
- `base.py::ComponentProcessor`:
  - Docstring + `HANDLES` list explicitly references **Unity** component
    type names.
  - `parse(comp_type, comp_data, go, log)` — Unity component dict.
- `mesh.py`, `material.py`, `light.py`, `box_collider.py`,
  `capsule_collider.py`, `sphere_collider.py`, `mesh_collider.py`,
  `rigidbody.py` — each consumes Unity component data and emits
  O3DE component JSON.

### 2.4 Unity material property names

Both in `project_manager.py::DEFAULT_SHADER_PROFILE` and
`integrated_asset_processor.py::_extract_material_data` legacy fallback:
- `_MainTex, _BaseMap, _BaseColorMap, _Albedo, _AlbedoMap, _AlbedoTex,
  _Diffuse, _DiffuseMap, _DiffuseTex, _ColorMap`
- `_BumpMap, _NormalMap, _NormalTex`
- `_MetallicGlossMap, _MetallicMap, _MetallicTex, _Metallic_Map`
- `_SpecGlossMap, _SpecularMap`
- `_OcclusionMap, _AOMap, _AmbientOcclusion, _AmbientOcclusionMap, _AO`
- `_RockAlbedo, _RockNormal, _RockSpecular` (MK4 pack)
- `_EmissionMap, _EmissionTex, _EmissiveMap, _Emissive`
- `_HeightMap, _ParallaxMap, _DisplacementMap`
- Properties: `_Color, _BaseColor, _BumpScale, _OcclusionStrength,
  _EmissionColor`
- Special-rule flags: `_Metallic, _Smoothness, _Glossiness,
  _GlossMapScale`
- Ignore list: `_DetailAlbedoMap, _DetailMask, _DetailNormalMap,
  _LightTextureB0, _VectorNoise, _texcoord, _Composite, _CompositeMap,
  _MOHS, _MaskMap, _Detail, _AODetail, _CoverAlbedo, _CoverNormal,
  _CoverSpecular`.

These property names are the substance of the `DEFAULT_SHADER_PROFILE`.
**The shape is PAC; the contents are UNS.** Other platforms ship their
own profiles with Unreal / Godot / Blender property names.

### 2.5 Unity convention constants

- `Y_UP_ROTATION` — Unity Y-up to O3DE Z-up correction quaternion.
- `read_fbx_up_axis` — FBX up-axis detection (format-specific, but
  used to drive Unity-style correction).
- Coordinate swizzle `(x, z, y)` — Unity → O3DE.

### 2.6 Scope-root semantics

`project.scope_root` is documented as "the project's source-engine
asset root". The implementation assumes Unity's `<ProjectRoot>` containing
`Assets/` — see `check_environment`. Other platforms would assume
different roots (Unreal's `Content/`, Godot's `res://`).

### 2.7 Unity-keyed pre-flight checks

`preflight.py::check_material_processor` consumes
`outputs.asset_processor.material_metadata` whose entries carry
`shader_name`, `shader_guid` — Unity-shaped. The CHECK is engine-neutral
in spirit (does every detected source-shader have a profile mapping?),
but the source shape requires the platform plugin to populate the
metadata in a compatible format.

---

## Part 3 — Platform Plugin Contract

The interface a third-party developer implements to add a source engine.
**Lives in `platforms/<engine>/` once split out**, registered with the
central `PlatformRegistry`.

### 3.1 Required surfaces (all platforms must provide)

```python
class SourcePlatform(Protocol):
    # ---- IDENTITY -------------------------------------------------------
    NAME:        str       # matches a `SourceEngine` enum value ("unity", "unreal", ...)
    DISPLAY:     str       # "Unity", "Unreal Engine 5", ...
    DESCRIPTION: str       # short tagline for the UI
    FILE_EXTENSIONS: dict  # {"scene": "*.unity", "prefab": "*.prefab",
                           #  "material": "*.mat", "shader": "*.shader",
                           #  "mesh": ["*.fbx", "*.obj"], ...}

    # ---- DISCOVERY ------------------------------------------------------
    def scope_root_label(self) -> str:
        """User-facing label for the scope-root field
        ('Unity project root', 'Unreal Content directory', ...)."""

    def validate_scope_root(self, path: Path) -> List[PreflightItem]:
        """Per-platform sanity. Unity: contains Assets/. Unreal:
        contains Content/. Returned items are appended to the
        Environment check during preflight."""

    def build_asset_index(self, scope_root: Path) -> "AssetIndex":
        """Walk the scope root and build the asset-id ↔ path index
        the worker will consult."""

    def scrub_prefabs(self, scope_root: Path) -> List[str]:
        """Return relative paths of prefab/scene-equivalent assets."""

    def scrub_scenes(self, scope_root: Path) -> List[str]:
        """Return relative paths of scene/level-equivalent assets."""

    def scrub_terrain(self, scope_root: Path) -> List[str]:
        """Return relative paths of terrain-equivalent assets."""

    # ---- EXTRACTION ----------------------------------------------------
    def parse_material(self, path: Path) -> "PlatformMaterial":
        """Read a source material file into the neutral
        PlatformMaterial shape. Used by the profile extractor."""

    def parse_prefab(self, path: Path) -> "PlatformPrefab":
        """Read a source prefab/scene-graph file into the neutral
        PlatformPrefab shape (entities + transform + component refs)."""

    def parse_scene(self, path: Path) -> "PlatformScene": ...

    def resolve_shader_name(self, material: "PlatformMaterial") -> str:
        """Friendly shader name used to look up shader_mappings."""

    # ---- PROFILE LIBRARY -----------------------------------------------
    def default_profiles(self) -> Dict[str, dict]:
        """Pre-seeded profile library. Unity ships
        'Default — Anything to PBR'; Unreal would ship 'Default —
        Unreal Material to PBR'; etc. Returned dict matches
        DEFAULT_SHADER_PROFILE shape."""

    def default_shader_mappings(self) -> Dict[str, str]:
        """Pre-seeded shader → profile_name mappings for built-in
        shaders the platform recognises out of the box."""

    # ---- COMPONENT PROCESSORS ------------------------------------------
    def component_processors(self) -> List["ComponentProcessor"]:
        """The plugin's component-type → O3DE-component-JSON
        translators. Loaded by build_dispatch_table()."""

    # ---- COORDINATE SYSTEM ---------------------------------------------
    def to_o3de_coordinates(self, t: Transform) -> Tuple[Transform, bool]:
        """Convert source transform → O3DE-space (Z-up, RH).
        Returns (converted, scale_was_non_uniform_flag)."""

    UP_AXIS:        str    # 'Y' or 'Z' (mesh-source convention)
    HANDEDNESS:     str    # 'RH' or 'LH'

    # ---- PREFLIGHT EXTENSIONS ------------------------------------------
    def preflight_checks(self) -> List[Callable]:
        """Platform-specific check functions appended to CHECK_REGISTRY."""
```

### 3.2 Neutral data shapes

The plugin produces and consumes these PAC dataclasses:

```python
@dataclass
class AssetIndex:
    by_id:      Dict[str, Path]    # platform's asset-id (Unity GUID, Unreal soft path, etc.) → file
    by_path:    Dict[Path, str]
    extensions: Dict[str, str]     # "material" → ".mat", etc.

@dataclass
class PlatformMaterial:
    name:         str
    shader_guid:  str            # platform's shader-id; opaque to PAC
    shader_id:    int            # secondary id (Unity fileID, Unreal class id, ...)
    raw_textures: Dict[str, str] # source property name → texture asset id
    raw_floats:   Dict[str, float]
    raw_colors:   Dict[str, List[float]]  # 4-component RGBA

@dataclass
class PlatformEntity:
    name:           str
    transform:      Transform
    mesh_id:        Optional[str]
    material_ids:   List[str]
    raw_components: List[dict]   # passed to ComponentProcessors

@dataclass
class PlatformPrefab:
    root:     PlatformEntity
    entities: Dict[str, PlatformEntity]
    parent_map: Dict[str, Optional[str]]   # child_id → parent_id

# Transform already exists in integrated_asset_processor; promote to PAC.
```

### 3.3 ComponentProcessor evolution

The existing `ComponentProcessor` ABC is a useful prototype but its
`HANDLES = ["MeshRenderer", "MeshFilter", ...]` strings are Unity-typed.
Two small adjustments:

1. `parse(comp_type, comp_data, go, log)` — `comp_type` is the platform's
   own type string. Plugins ship their own component processor set.
2. The MaterialComponentProcessor's emit phase is **engine-neutral** —
   it consumes `go.material_guids` (already abstracted as just "asset
   ids") and emits O3DE JSON. Stays as-is; just lives in a shared
   `o3de_emitters/` module reachable by all platforms.

### 3.4 Registration

```python
# platforms/__init__.py
PLATFORM_REGISTRY: Dict[str, SourcePlatform] = {}

def register(platform: SourcePlatform) -> None:
    PLATFORM_REGISTRY[platform.NAME] = platform

# At module import time:
from platforms.unity import UnityPlatform
register(UnityPlatform())
```

Plugins live in standalone modules; adding a new one is a single
`register(...)` call. The user-facing `SourceEngine` enum is already
positioned for this — adding `MAYA` or `CRYENGINE` is a single enum row
+ a new module.

---

## Part 4 — Non-Destructive Platform Switching

Locked decisions for what happens when a user flips the project's
`source_engine` (today purely cosmetic; F-platform-switch makes it
functional).

### 4.1 Off-platform data preservation

A project that started as Unity and switches to Unreal MUST preserve:
- Unity-specific selections (`selected_prefabs` list, even though Unreal
  wouldn't load them).
- Unity-specific profile library (`shader_profiles` containing
  `_MainTex` mappings).
- Unity-specific overrides keyed by Unity GUIDs.
- The state index entries that emitted under Unity (the user might
  flip back).

**Schema shift:** `Project.stages` becomes namespaced by platform:

```json
"stages_by_platform": {
  "unity": {
    "asset_processor":    { ... },
    "scene_converter":    { ... },
    "material_processor": { ... },
    ...
  },
  "unreal": {
    "asset_processor":    { ... },
    ...
  }
},
"active_platform": "unity"
```

Same for `outputs_by_platform` (state index, material_metadata, etc.).

`Project.stage_settings(key)` reads from
`stages_by_platform[active_platform][key]`. The lookup layer is the
seam — no caller other than ProjectManager touches the per-platform
namespace directly.

### 4.2 Cross-platform state

A few fields stay project-global, not per-platform:
- `name`, `notes`, `created`, `modified`, `scope_root`,
  `preflight_acks`.
- The current-platform pointer (`active_platform`).

### 4.3 Switching UX

UI lets the user pick a platform from the existing engine dropdown.
On switch:
1. Save current state into `stages_by_platform[old]`.
2. Read or initialise `stages_by_platform[new]` (default_stages for
   that platform).
3. Emit `project_changed` so every tab re-reads.
4. Show a transient toast "Switched to <Platform>. Previous platform's
   data preserved."

### 4.4 Migration of existing projects

Legacy projects have flat `stages` / `outputs`. On load:
- Assume Unity (existing projects are Unity-source).
- Move the flat dicts into `stages_by_platform["unity"]` /
  `outputs_by_platform["unity"]`.
- Set `active_platform = "unity"`.

One-shot in `Project.from_json`, same pattern as the earlier
`target_materialtype → profile` migration.

---

## Part 5 — Refactor Plan (sequenced)

The audit gives us the destination. The refactor lands in five
phases; each phase is independently shippable and the build stays green
across the seam.

### Phase 5.1 — Move + rename (mechanical, low-risk)

- Create `platforms/__init__.py` with `PLATFORM_REGISTRY` and
  `register()`.
- Create `platforms/unity/` module:
  - `platforms/unity/__init__.py` exports `UnityPlatform`.
  - `platforms/unity/asset_database.py` — moved from
    `integrated_asset_processor.py::AssetDatabase`.
  - `platforms/unity/material.py` — moved
    `_extract_material_data` + DEFAULT_SHADER_PROFILE.
  - `platforms/unity/prefab.py` — moved `_parse_unity_prefab` family.
  - `platforms/unity/shader.py` — `_resolve_shader_name`,
    `_UNITY_BUILTIN_SHADERS`, `_SHADER_NAME_RE`.
  - `platforms/unity/coordinates.py` — `Y_UP_ROTATION`,
    `_convert_to_o3de_coordinates`, FBX up-axis reader.
- Create `targets/o3de/` module:
  - `targets/o3de/prefab_writer.py` — `_make_bare_entity`,
    `_create_container_entity`, `_create_nested_prefab_instance`,
    `_create_entity_recursive`.
  - `targets/o3de/assetinfo_writer.py` — `write_fbx_assetinfo`,
    coordinate composition, quaternion helpers.
  - `targets/o3de/material_writer.py` — the JSON-emit half of
    `_process_material`.

Nothing changes behaviorally; imports update. No new tests required —
existing F-9 verification matrix re-runs.

### Phase 5.2 — Define the contract

- `platforms/base.py::SourcePlatform` Protocol.
- `platforms/types.py::PlatformMaterial`, `PlatformEntity`,
  `PlatformPrefab`, `AssetIndex`.
- `UnityPlatform` class assembles the moved modules into a single
  conformant object.
- Verification: import `platforms.unity.UnityPlatform`, assert
  conformance via `isinstance` against the Protocol.

### Phase 5.3 — Wire the registry into the worker

- `IntegratedAssetProcessor.__init__` accepts `platform:
  SourcePlatform` (defaults to looking up the current project's
  `active_platform` from PLATFORM_REGISTRY).
- Every `_parse_*` / `_resolve_shader_name` / `_extract_material_data`
  call site routes through `self.platform`.
- Component processor dispatch consults
  `self.platform.component_processors()` instead of the global
  `load_component_processors()`.

### Phase 5.4 — Project schema migration

- Add `Project.stages_by_platform: Dict[str, dict]` and
  `Project.outputs_by_platform: Dict[str, dict]`.
- Add `Project.active_platform: str`.
- Migrate `from_json` one-shot.
- Wrap `stage_settings(key)` / `update_stage(key, settings)` /
  `update_outputs(key, ...)` to route through the active platform.

### Phase 5.5 — Switch UX

- Engine dropdown calls `pm.set_active_platform(engine.value)`.
- Tabs re-apply on `project_changed`.
- Toast banner: "Switched to <X>. Previous platform's data preserved."

Each phase is its own plan / working-doc pair under
`.serena/memories/platform_abstraction/`.

---

## Part 6 — Third-party Developer Contract

What documentation a non-Unity dev needs to ship a plugin:

1. **The `SourcePlatform` Protocol** — Part 3.1 above. Living doc in
   `platforms/base.py`.
2. **The neutral data shapes** — Part 3.2 above. Living doc in
   `platforms/types.py`.
3. **A reference implementation** — `platforms/unity/` itself is the
   reference. ~1500 lines after the move, broken into named modules.
4. **The component-processor recipe** — `components/base.py` already
   documents `ComponentProcessor`. After Phase 5.3, the recipe extends
   to "drop a new class into `platforms/<your_engine>/components/`".
5. **The profile schema** — already documented at
   `project_manager.py::DEFAULT_SHADER_PROFILE`. Plugin ships its own
   default profile + its own default `shader_mappings`.
6. **The preflight extension recipe** — register additional check
   functions via `SourcePlatform.preflight_checks()`.
7. **The on-disk format** — `.u2oproj.json` schema, locked via
   `SCHEMA_VERSION` and the deep-merge load path.

After the refactor, a new platform is **one new directory + four
registry calls + N component processors**.

---

## Part 7 — What is explicitly NOT in scope

- Replacing O3DE as the output target. The refactor preserves
  O3DE-target assumptions; multi-output is a separate audit.
- Reworking the UI to be platform-aware beyond the dropdown switch.
  Per-tab UIs stay Unity-themed copy until a non-Unity plugin ships
  (which can override copy via the platform contract if needed).
- Networking / cloud / multi-user. Project file stays local-disk.
- Live engine bridges (e.g. talking to a running Unity / Unreal
  process). Plugins read static asset files.
