# Unity Source-Platform Plugin

The reference implementation of [`SourcePlatform`](../base.py). The
Unity plugin parses Unity Editor projects (`.prefab`, `.unity`,
`.mat`, `.shader`, `.meta` assets discovered under `Assets/`) and
feeds the platform-agnostic core, which then emits O3DE-target
output.

If you're authoring a non-Unity plugin, read this in tandem with
[`platforms/README.md`](../README.md) — this directory is the
copy-paste-and-adapt baseline.

---

## Module map

```
platforms/unity/
    __init__.py             Namespace docstring.
    unity_platform.py       UnityPlatform class — the SourcePlatform impl.
    asset_database.py       GUID index + `.mat` parser (AssetDatabase).
    prefab.py               Multi-doc YAML walker for prefabs + scenes.
    shader.py               `.shader` file → friendly name resolver.
    coordinates.py          UNITY_Y_UP_TO_O3DE_Z_UP_QUAT correction quat.
    types.py                Transform / UnityComponent / GameObject.
    components/             Per-component-type processors (auto-discovered).
        __init__.py
        base.py             ComponentProcessor ABC.
        mesh.py             MeshFilter / MeshRenderer.
        material.py         EditorMaterialComponent emit.
        light.py            All Unity light types.
        box_collider.py
        sphere_collider.py
        capsule_collider.py
        mesh_collider.py
        rigidbody.py
```

Total: ~1450 lines across 7 root modules + 9 component processors.

---

## How Unity asset identity works

Unity's asset system uses **GUIDs** stored in companion `.meta`
files. For every asset `Foo.prefab`, there's a `Foo.prefab.meta` file
alongside it containing:

```yaml
fileFormatVersion: 2
guid: deadbeefcafebabe000000000000eeee
PrefabImporter:
  externalObjects: {}
```

Materials reference shaders by GUID, prefabs reference materials by
GUID, etc. The plugin's [`asset_database.py`](asset_database.py)
walks the scope for every `*.meta` and builds the
`guid → file_path` index that the rest of the plugin consults.

The id form in `PlatformMaterial.shader_id` / `PlatformEntity.mesh_id`
is **the raw 32-char hex GUID string**. Other plugins are free to
choose their own id form (Unreal: soft-object path string, Godot:
`res://` path, Blender: lib+name pair).

---

## How Unity prefab parsing works

Unity stores prefabs as **multi-document YAML files** with a custom
`!u!N &anchor` tag preamble per document:

```yaml
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
    - component: {fileID: 4100}
  m_Name: Cube_001
--- !u!4 &4100
Transform:
  m_GameObject: {fileID: 100}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Father: {fileID: 0}
--- !u!23 &2300
MeshRenderer:
  m_GameObject: {fileID: 100}
  ...
```

The plugin's [`prefab.py`](prefab.py) walks every doc, dispatches on
top-level key (`GameObject` / `Transform` / `PrefabInstance` / known
component type), and assembles a flat `{file_id: GameObject}` dict +
a `{transform_id: gameobject_id}` resolution map.

### Two-pass design

1. **Pass 1**: every doc populates its GameObject placeholder.
   GameObject docs carry the name and the component-id list; Transform
   docs carry the position/rotation/scale and parent-id; component
   docs (MeshRenderer, Light, etc.) get stashed for later dispatch.
2. **Pass 2** (`build_hierarchy`): parent-child relationships are
   resolved (transform IDs → GameObject IDs), the bidirectional
   children list is built, and each parsed component is dispatched to
   its registered `ComponentProcessor.parse` method.

### The PrefabInstance case

Nested prefabs aren't expanded inline — they appear as
`PrefabInstance` docs with `m_SourcePrefab.guid` pointing at another
`.prefab` file plus an `m_Modification.m_Modifications` array of
property overrides (transform tweaks, material slot swaps,
m_IsActive changes, etc.).

`parse_prefab_instance_in_prefab` captures the full overrides array
verbatim onto a placeholder `GameObject` (with
`is_prefab_instance=True`), and the O3DE prefab writer translates them
to JSON patches at emit time.

---

## How Unity material parsing works

Unity `.mat` files are also multi-document YAML, but the relevant
document is the single `Material:` block:

```yaml
Material:
  m_Name: Cube_Material
  m_Shader: {fileID: 4800000, guid: deadbeefcafebabe000000000000aaaa, type: 3}
  m_SavedProperties:
    m_TexEnvs:
    - _MainTex:
        m_Texture: {fileID: 2800000, guid: ...000bbbb, type: 3}
    m_Floats:
    - _BumpScale: 1.5
    m_Colors:
    - _Color: {r: 0.5, g: 0.6, b: 0.7, a: 1.0}
```

`AssetDatabase.parse_material()` reads this and produces a dict the
F-9 profile chain consumes. The shader is stored as a `{fileID, guid,
type}` REFERENCE — NOT a name. The plugin's
[`shader.py`](shader.py)::`resolve_shader_name(asset_db, guid,
fileid)` reads the `Shader "Name"` declaration from the `.shader`
file the GUID points at, or falls back to a small built-in fileID
table for Unity engine shaders (`Standard`, `Standard (Specular
setup)`).

### The shader profile chain

Once the friendly shader name is known, the F-9 profile chain runs:

```
overrides[material_guid].profile        # per-material profile override
  → shader_mappings[shader_name]        # shader → profile lookup
  → defaults.profile                    # project default profile
```

The selected profile carries:

- `target_materialtype` — the O3DE `.materialtype` to emit.
- `texture_map: {unity_prop: {slot, transform}}` — e.g. `_MainTex →
  baseColor`.
- `property_map: {unity_prop: {target, transform}}` — e.g. `_Color →
  baseColor.color`.
- `ignore_unmapped` — names silenced from the unmapped-property
  warning.
- `special_rules` — flags like
  `metallic_gloss_smoothness_to_roughness` that change extraction
  behaviour.

The reference catch-all profile,
`Default — Anything to PBR`, captures Unity's Standard / URP / HDRP
property names — see `unity_platform.py::UnityPlatform.default_profiles`
and `project_manager.DEFAULT_SHADER_PROFILE`.

---

## How Unity coordinate-system correction works

Unity is **Y-up, left-handed**. O3DE is **Z-up, right-handed**. The
plugin handles this in two places:

### 1. Per-transform swizzle

`UnityPlatform.to_o3de_coordinates(transform)` (and the legacy
worker-side `_convert_to_o3de_coordinates`) swap Y/Z components:

```python
o3de_position = (unity_position[0], unity_position[2], unity_position[1])
o3de_rotation = (qx, qz, qy, qw)
o3de_scale    = (sx, sz, sy)
```

This produces a final transform whose Z is "up" relative to O3DE.

### 2. Per-mesh CoordinateSystemRule

FBX files have their own up-axis preference recorded in the binary
header (`up_axis == 1` for Y-up Maya-style files,
`up_axis == 2` for Z-up Blender-style). When the FBX is Y-up, the
plugin's `correction_quat` property
([`coordinates.py`](coordinates.py)::`UNITY_Y_UP_TO_O3DE_Z_UP_QUAT`)
gets composed into the assetinfo's `CoordinateSystemRule.rotation`
field so the imported mesh sits upright.

This quaternion is a **+90° rotation around X** — the standard
Y-up → Z-up correction.

User-supplied per-mesh rotations (from the F-5 Mesh tab) compose ON
TOP of the correction quaternion via the Hamilton product
`q_user ⊗ q_correction`, so the user's authored transform applies in
the corrected coordinate space.

---

## How Unity component processors work

The [`components/`](components/) directory is a plugin system inside
the plugin. Each `*.py` file declares one or more
`ComponentProcessor` subclasses:

```python
class MyComponentProcessor(ComponentProcessor):
    WEIGHT  = 200                       # lower runs earlier
    HANDLES = ["YourUnityComponentType"]
    EMITS   = ["YourO3DEComponentType"]

    def parse(self, comp_type, comp_data, go, log):
        # Populate go.component_data with parse-phase state.
        ...

    def emit(self, go, entity, ctx):
        # Add O3DE component JSON to entity["Components"].
        # Return a list of child entity IDs you created (e.g. overflow
        # collider entities).
        ...
        return []
```

Auto-discovery: `platforms/unity/components/__init__.py` walks its
own directory, finds every subclass, and sorts them by `WEIGHT`.
Adding a new processor is a drop-in `*.py` file with no other
changes.

Built-in processors:

| Module | Weight | Handles | Emits |
|---|---|---|---|
| `mesh.py` | 25 | MeshFilter / MeshRenderer | EditorMeshComponent |
| `material.py` | 50 | (emit-only) | EditorMaterialComponent |
| `rigidbody.py` | 75 | Rigidbody | EditorRigidBodyComponent / EditorStaticRigidBodyComponent |
| `box_collider.py` | 100 | BoxCollider | EditorBoxShapeComponent + EditorShapeColliderComponent |
| `sphere_collider.py` | 125 | SphereCollider | EditorSphereShapeComponent + EditorShapeColliderComponent |
| `capsule_collider.py` | 150 | CapsuleCollider | EditorCapsuleShapeComponent + EditorShapeColliderComponent |
| `mesh_collider.py` | 175 | MeshCollider | EditorMeshColliderComponent |
| `light.py` | 510 | Light | EditorDirectionalLightComponent / EditorAreaLightComponent |

Material runs after Mesh because `go.material_guids` is populated by
the MeshRenderer pass. Lights run last because their entity sort
order matters less than physics geometry.

---

## How worker / plugin dependency injection works

When `IntegratedAssetProcessor` (the worker) constructs an
`AssetDatabase`, it calls
`self.platform.bind_asset_db(self.asset_db)`. Subsequent
`UnityPlatform.parse_material` / `resolve_shader_name` calls consult
that bound DB instead of building a fresh one. The plugin's
`_asset_db` attribute is None until the bind happens; standalone
callers (tests, plugin-validation scripts) skip the bind and a
heuristic fallback builds a temporary DB scoped to the material's
grandparent directory.

This is the **dependency-injection seam** between plugin and worker.
Other plugins that hold engine-specific runtime state (e.g. an
Unreal plugin's UAsset cache) should mirror the same pattern.

---

## Worker-side method delegation

The Phase A/B/C platform-abstraction refactor moved every
Unity-specific parser and O3DE-target writer **out** of
`IntegratedAssetProcessor` and into this directory + `targets/o3de/`.
The worker retains thin wrapper methods that build a context object
and delegate:

```python
# In IntegratedAssetProcessor:
def _parse_unity_prefab(self, prefab_path):
    from platforms.unity.prefab import parse_unity_prefab
    return parse_unity_prefab(self._parser_context(), prefab_path)
```

This means:

- The worker is now an orchestration shell — it doesn't know about
  Unity-specific YAML formats, GUIDs, or component types.
- Switching the active platform swaps which plugin's parsers and
  component processors are wired into the worker on construction.
- Tests can exercise the parsers in isolation by constructing a
  `UnityParseContext` directly.

See `_parser_context` and `_writer_*` wrappers in
[`integrated_asset_processor.py`](../../integrated_asset_processor.py).

---

## Notable design decisions

These are the design choices captured in
`.serena/memories/platform_abstraction/` that informed the Unity
plugin's shape:

1. **Plugin code is read-only.** No reaching back into worker state
   for mutation. Worker passes context objects down; the plugin
   produces neutral data shapes; the worker consumes them.

2. **Asset id form is opaque to the PAC core.** Unity uses 32-char
   hex GUIDs; the core never inspects them. Other plugins can use
   any string-shaped id (paths, names, hashes).

3. **The legacy hard-coded TEXTURE_MAP lives in the default profile,
   not in code.** Pre-F-9, `_extract_material_data` had a hard-coded
   dict mapping `_MainTex → baseColor` etc. Post-F-9, that same data
   is the `texture_map` field of the `Default — Anything to PBR`
   profile — making it editable, project-overridable, and
   replaceable by other plugins shipping their own catch-all
   profiles for their engine's standard PBR shaders.

4. **Y-up correction is platform-supplied.** The assetinfo writer
   doesn't know about Y-up vs Z-up — it accepts a `correction_quat`
   parameter the worker pulls from `self.platform.correction_quat`.
   An Unreal plugin (Z-up natively) supplies the identity
   quaternion; a Maya plugin would supply something different.

5. **Multi-doc YAML walker is generic.** `parse_unity_prefab` and
   `parse_unity_scene` use the same code path — scenes and prefabs
   are structurally identical in Unity (both are multi-doc YAML with
   GameObject/Transform/component blocks). A plugin for an engine
   that splits scenes and prefabs differently (Unreal's
   `.umap` vs `.uasset`) would have two distinct parse paths.

---

## Open follow-ups (Unity-specific, not blocking)

These are deferred items called out in
`.serena/memories/platform_abstraction/working_documentation.md`:

- **FBX binary readers** (`read_fbx_mesh_node_names`,
  `read_fbx_material_names`, `read_fbx_up_axis`,
  `build_fbx_node_paths`) currently live on
  `integrated_asset_processor.py`. They're format-specific, not
  platform-specific — a future `format/fbx/` module would house them
  + any other FBX tooling.
- **`_process_metallic_gloss_as_roughness`** (Pillow-backed alpha
  inverter) is part of the worker pipeline; it could move to
  `platforms/unity/textures.py` if a non-Unity plugin needs a similar
  channel-flip helper.

Neither is blocking. The plugin is feature-complete.

---

## Further reading

- [`../README.md`](../README.md) — general plugin guide + contract
  reference.
- [`../base.py`](../base.py) — `SourcePlatform` ABC with docstrings.
- `.serena/memories/platform_abstraction/audit.md` — PAC vs UNS map.
- `.serena/memories/material_preprocessing/` — F-6 shader profile
  design history.
- `.serena/memories/output_propagation/` — F-9 emission contract +
  state index design.
