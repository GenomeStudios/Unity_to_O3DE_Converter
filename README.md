> System built with Claude LLM generation. Public Domain.
>
> Guide video (project goals and usage walkthrough):
> https://youtu.be/peQf-9lWNYA

---

# Unity → O3DE Converter

An automated two-stage pipeline for bringing Unity graphical assets and prefabs into O3DE.

---

## Overview

The converter operates in two stages, each accessible from a tab in the unified GUI.

**Stage 1 — Prefab Processor**
Scrubs a Unity Assets folder for `.prefab` files. Each prefab serves as the dependency anchor for discovering every mesh, texture, and material it references. Those assets are converted into O3DE-ready equivalents and written to a clean output folder structure. The resulting `.prefab` files are pre-configured with correct material, mesh, and physics component references.

**Stage 2 — Scene Converter**
Takes a Unity `.unity` scene file and cross-references it against the library of converted O3DE prefabs. It populates an O3DE level with matching prefab instances, preserving placement transforms and hierarchy structure. GameObjects that do not resolve to a known prefab ("unowned" entities) are written as plain O3DE entities and run through the same component processor pipeline as Stage 1 — physics colliders, rigidbodies, and directional lights are emitted directly onto those entities.

---

## Requirements

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/) — `pip install PySide6`
- [PyYAML](https://pypi.org/project/PyYAML/) — `pip install pyyaml`
- Blender (optional, for FBX transform baking) — [blender.org](https://www.blender.org/download/)

---

## Running the Converter

**Unified launcher (recommended):**
```
python main_app.py
```

**Legacy launchers** (open directly to a specific tab):
```
UnityConverter.bat          # unified GUI
UnityPrefabConverter.bat    # opens on Prefab Processor tab
UnitySceneImporter.bat      # opens on Scene Converter tab
```

Last-used paths are automatically saved and restored between sessions via `converter_settings.json`.

---

## Output Structure

```
<output_root>/
  Prefabs/       O3DE .prefab files, one per Unity prefab
  Materials/     O3DE .material files (StandardPBR)
  Textures/      Consolidated texture files
  Meshes/        FBX / mesh files (optionally baked via Blender)
```

---

## What Converts

| Unity | O3DE | Status |
|---|---|---|
| Prefab hierarchy | Entity hierarchy in `.prefab` | Working |
| Uniform transform | TransformComponent | Working |
| Non-uniform scale | EditorNonUniformScaleComponent | Working |
| MeshFilter + MeshRenderer | EditorMeshComponent | Working |
| Multi-material slots | EditorMaterialComponent `{}` default + `{0}`, `{1}`... | Working |
| FBX .assetinfo per-entity MeshGroups | Named, predictable `.azmodel` asset hints | Working |
| Texture maps (albedo, normal, metallic, roughness, occlusion, emissive) | StandardPBR properties | Working |
| Transparency / alpha clip | `opacity.mode = Blended` | Working |
| BoxCollider | EditorBoxShapeComponent + EditorShapeColliderComponent | Working |
| SphereCollider | EditorSphereShapeComponent + EditorShapeColliderComponent | Working |
| CapsuleCollider | EditorCapsuleShapeComponent + EditorShapeColliderComponent | Working |
| MeshCollider | EditorMeshColliderComponent | Working |
| Rigidbody (dynamic) | EditorRigidBodyComponent | Working |
| No Rigidbody + collider | EditorStaticRigidBodyComponent | Working |
| Multiple colliders on one GO | Overflow → child entities `{Name}_Collider_N` | Working |
| Nested prefab instances | Nested instance references | Working |
| Scene placement + rotation | Prefab instance transforms in level | Working |
| Unowned scene entities — physics | BoxCollider / Rigidbody / StaticRigidBody emitted directly | Working |
| Unowned scene entities — directional light | EditorDirectionalLightComponent emitted directly | Working |
| Directional light (type=1) | EditorDirectionalLightComponent (intensity, shadows) + 180° pitch correction | Working |
| Mesh pivot / coordinate rebake | — | Known issue (see below) |

---

## Known Issues

**Mesh coordinate system**
Unity internally rebakes mesh coordinates in a way that does not match the raw FBX on disk. The converter applies the Unity → O3DE axis swap — position `(x, z, y)`, rotation `(qx, qz, qy, qw)`, scale `(sx, sz, sy)` — but cannot correct for Unity's internal mesh pivot bake. A Blender transform-bake pass was attempted and abandoned as ineffectual. This remains the primary visual accuracy issue on some assets.

**Material pipeline**
Texture, normal, metallic, roughness, and opacity conversions are functional. Specular workflow, detail maps, and some edge-case shader properties are not yet mapped.

---

## File Structure

```
unity_to_o3de_converter/
  main_app.py                      Unified PySide6 GUI (entry point)
  integrated_asset_processor.py    Stage 1 core — prefab + asset processing
  unity_scene_converter_gui.py     Stage 2 core — scene to level conversion
  converter_settings.json          Persisted GUI paths

  components/                      Pluggable component processor modules
    __init__.py                    Auto-discovery and dispatch table
    base.py                        ComponentProcessor ABC + ProcessingContext
    mesh.py          weight=25     MeshFilter / MeshRenderer
    material.py      weight=50     Material slot mapping
    rigidbody.py     weight=75     Rigidbody (dynamic + static)
    box_collider.py  weight=100    BoxCollider
    sphere_collider.py  weight=125 SphereCollider
    capsule_collider.py weight=150 CapsuleCollider
    mesh_collider.py       weight=175 MeshCollider
    light.py               weight=510 All Unity Light types (Directional / Point / Spot / Area)

  legacy_unity_prefab_to_o3de.py   Legacy — ignore
  bake_fbx_transforms.py           Legacy — ignore
```

---

## Authoring a New Component Processor

The `components/` directory is a self-contained plugin system. Drop a new `.py` file in and it is automatically discovered, instantiated, and wired into the pipeline on the next run. No changes to the core processor are needed.

### Step 1 — Create the module file

Name the file descriptively. The name has no effect on execution order.

```
components/my_component.py
```

### Step 2 — Subclass ComponentProcessor

```python
from typing import Callable, Dict, List
from .base import ComponentProcessor, ProcessingContext


class MyComponentProcessor(ComponentProcessor):

    # -------------------------------------------------------------------------
    # WEIGHT controls execution order — lower runs first.
    # Built-in processors use multiples of 25 (25, 50, 75, 100 ... 175).
    # Pick a value that fits where you need this processor to run.
    # Equal weights are resolved by file discovery order (first-come, first-served).
    # -------------------------------------------------------------------------
    WEIGHT  = 200

    # -------------------------------------------------------------------------
    # HANDLES lists the Unity component type names (as they appear in the
    # prefab YAML) that trigger this processor's parse() method.
    # Use an empty list for emit-only processors.
    # -------------------------------------------------------------------------
    HANDLES = ['MyUnityComponent']

    # -------------------------------------------------------------------------
    # EMITS is informational only — lists the O3DE component types written.
    # -------------------------------------------------------------------------
    EMITS   = ['MyO3DEComponent']
```

### Step 3 — Implement `parse()`

Called once per Unity component document during the prefab parse phase.
Populate fields on the `go` (GameObject) object.

```python
    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        """
        comp_type  — the Unity component type string (e.g. 'MyUnityComponent')
        comp_data  — the raw YAML dict for this component block
        go         — the GameObject this component belongs to;
                     populate go.mesh_guid, go.material_guids, go.colliders,
                     go.has_rigidbody, go.rigidbody_data, or go.component_data
                     for custom state
        log        — call log("message") for verbose output
        """
        value = comp_data.get('m_SomeField', 0)
        go.component_data['my_value'] = value
        log(f"    [MyComp] Parsed value={value}")
```

`go.component_data` is a plain `dict` keyed by anything you choose — use it
for any data that does not fit the standard `GameObject` fields.

### Step 4 — Implement `emit()`

Called once per entity during the O3DE prefab generation phase, after the
TransformComponent has been added. Mutate `entity['Components']` to write
your O3DE JSON.

```python
    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        """
        go     — the GameObject (read the data you stored in parse())
        entity — the O3DE entity dict being built; mutate entity['Components']
        ctx    — ProcessingContext with helpers and shared mappings (see below)

        Return a list of child entity IDs you created, or an empty list.
        """
        value = go.component_data.get('my_value')
        if value is None:
            return []

        entity['Components']['MyO3DEComponent'] = {
            '$type': 'MyO3DEComponent',
            'Id':    ctx.generate_component_id(),
            'Value': value,
        }
        ctx.log(f"  [MyComp] ✓ MyO3DEComponent — value={value}")
        return []
```

### ProcessingContext reference

| Field / method | Type | Purpose |
|---|---|---|
| `ctx.material_mapping` | `dict[guid, asset_hint]` | Resolved Unity material GUIDs → O3DE asset paths |
| `ctx.mesh_mapping` | `dict[guid, asset_hint]` | Resolved Unity mesh GUIDs → O3DE asset paths |
| `ctx.entities_dict` | `dict[id, entity]` | All entities being built (mutate to add child entities) |
| `ctx.entity_id_map` | `dict[file_id, entity_id]` | Maps GO file IDs to O3DE entity IDs |
| `ctx.generate_component_id()` | `-> str` | Generate a unique component ID string |
| `ctx.generate_entity_id()` | `-> str` | Generate a unique entity ID string |
| `ctx.make_bare_entity(id, name, parent_id)` | `-> dict` | Create a minimal child entity with standard boilerplate components |
| `ctx.log(msg)` | `-> None` | Emit a log message to the GUI console |

### Creating child entities

If your component needs to spawn a child entity (e.g. for overflow colliders
or LOD children), use `ctx.make_bare_entity` and register it:

```python
child_id = ctx.generate_entity_id()
child    = ctx.make_bare_entity(child_id, f"{go.name}_Child", entity['Id'])
child['Components']['SomeComponent'] = { ... }
ctx.entities_dict[child_id] = child
return [child_id]
```

### Logging conventions

Use these prefixes so log output is easy to scan:

| Prefix | When to use |
|---|---|
| `[MyComp]` | All messages from your processor (use your component name) |
| `✓` | Successful emit |
| `⚠` | Warning — partial result, missing data, fallback used |
| `✗` | Error — component skipped entirely |

```python
ctx.log(f"  [MyComp] ✓ Component emitted")
ctx.log(f"  [MyComp] ⚠ No data found — skipping")
ctx.log(f"  [MyComp] ✗ Failed: {reason}")
```

### Complete minimal example

```python
from typing import Callable, Dict, List
from .base import ComponentProcessor, ProcessingContext


class LightComponentProcessor(ComponentProcessor):
    """
    Converts Unity Light components to O3DE EditorLightComponent.
    Handles: Light
    """

    WEIGHT  = 200
    HANDLES = ['Light']
    EMITS   = ['EditorLightComponent']

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        go.component_data['light'] = {
            'type':      comp_data.get('m_Type', 1),        # 0=Spot 1=Dir 2=Point 3=Area
            'intensity': float(comp_data.get('m_Intensity', 1.0)),
            'color': (
                comp_data.get('m_Color', {}).get('r', 1.0),
                comp_data.get('m_Color', {}).get('g', 1.0),
                comp_data.get('m_Color', {}).get('b', 1.0),
            ),
        }
        log(f"    [Light] type={go.component_data['light']['type']}, "
            f"intensity={go.component_data['light']['intensity']}")

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        light = go.component_data.get('light')
        if not light:
            return []

        entity['Components']['EditorLightComponent'] = {
            '$type': 'EditorLightComponent',
            'Id':    ctx.generate_component_id(),
            'Controller': {
                'Configuration': {
                    'Intensity': light['intensity'],
                    'Color':     list(light['color']) + [1.0],
                }
            }
        }
        ctx.log(f"  [Light] ✓ EditorLightComponent — intensity={light['intensity']}")
        return []
```

Save this as `components/light.py` with `WEIGHT = 200` and it will be live on the next run.

---

## Change Log

**2026-05-25 (latest)**
- **Prefab override propagation**: nested-prefab instances now translate Unity `m_Modifications` into O3DE JSON-patch entries. Tier 1 (translate / rotate / scale) is always emitted; Tier 2 (`m_IsActive`) is logged to coverage; Tier 3 (`m_Materials.Array.data[N]` slot overrides) is resolved via per-prefab sidecars and emitted as `assetHint` patches. Anything else is recorded as an unhandled override path. Mirrored across both Stage 1 (`_create_nested_prefab_instance`) and Stage 2 (`UnitySceneConverter._create_prefab_instance`).
- **Entity-map sidecars**: each converted prefab now writes a `<stem>.entitymap.json` next to its `.prefab` recording the Unity-fileID → O3DE-entity-alias map, the root entity, and per-entity material slot GUID lists. Required for cross-prefab override resolution.
- **Asset index**: each run writes `<output_root>/asset_index.json` listing every processed material/mesh/prefab GUID and its O3DE asset hint. Loaded by Stage 2 (and override emission) to resolve GUIDs without re-walking the project.
- **Coverage report**: each run writes `coverage.json` next to its primary output. Lists every Unity component type seen (handled or not), every prefab override propertyPath (with handled/unhandled counts and example values), every missing GUID, and converter warnings. Both Stage 1 and Stage 2 emit one.
- **Material metallic / roughness reconciliation** (texture-aware): `_extract_material_data` now collects `_Metallic`, `_Smoothness`, `_Glossiness`, `_GlossMapScale` separately and routes them based on whether a metallic/roughness texture is bound. With a texture: no `metallic.factor` (O3DE ignores it), `roughness.lowerBound = 1 − multiplier` + `roughness.upperBound = 1.0`. Without: `metallic.factor` / `roughness.factor` scalars only.
- **Opacity `alphaSource = "Packed"`**: Cutout and Blended materials now write `opacity.alphaSource` so O3DE StandardPBR actually reads the alpha channel from the baseColor texture. Previously omitted; materials rendered fully opaque despite `opacity.mode` being set.

**2026-03-14**
- **Scene converter — component processing for unowned entities**: GameObjects in a Unity scene that are not resolved as prefab instances now run the full component processor pipeline. Physics (colliders, rigidbodies) and directional lights are emitted onto those entities. `GameObject` dataclass extended with processor fields; `_dispatch_component_processors()` and `_make_bare_entity()` added to `UnitySceneConverter`
- **Scene converter — component processing for unowned entities**: GameObjects in a Unity scene that are not resolved as prefab instances now run the full component processor pipeline. Physics (colliders, rigidbodies) and directional lights are emitted onto those entities. `GameObject` dataclass extended with processor fields; `_dispatch_component_processors()` and `_make_bare_entity()` added to `UnitySceneConverter`
- **Unified light processor** (`components/light.py`, weight=510): handles all Unity `Light` types in one place. Directional (m_Type=1) emits `EditorDirectionalLightComponent` with a 180° pitch flip on the entity transform to correct the Unity↔O3DE forward-axis mismatch. Point (m_Type=2) emits `EditorAreaLightComponent` (LightType=Sphere) plus an `EditorSphereShapeComponent`. Spot (m_Type=0) emits `EditorAreaLightComponent` (LightType=SimpleSpot) with shutter half-angles. Area (m_Type=3) emits `EditorAreaLightComponent` (LightType=SimplePoint) as a runtime approximation (Unity area lights are baked-only). `_to_int()` helper handles `m_Shadows`/`m_Type` being serialized as nested dicts in scene files vs plain ints in prefab files. Supersedes the earlier `directional_light.py` (removed)
- Shape components now emit with `DisplayFilled: false` / `IsFilled: false`; shape colliders emit with `DebugDrawSettings: {LocallyEnabled: false}`
- Removed X-axis inversion from coordinate conversion — position is now `(x, z, y)`, rotation `(qx, qz, qy, qw)`; same fix applied to all shape collider center offsets
- FBX `.assetinfo` generation: per-entity named MeshGroups, `selectedNodes` always begins with `"RootNode"`, binary FBX parser (`read_fbx_hierarchy`) extracts sub-objects (UV channels, vertex color layers, material nodes)
- Multi-material slot format confirmed: `EditorMaterialComponent` emits `{}` default slot followed by indexed `{0}`, `{1}`, ... slots preserving Unity MeshRenderer order
- Material `assetHint` paths now preserve source file case (e.g. `Door_MetalDark.azmaterial`)

**2026-03-13**
- Unified PySide6 GUI with Catppuccin dark theme, replacing separate tkinter windows
- Component processing refactored into auto-discovered weighted plugin modules (`components/`)
- Physics pipeline fully implemented: Box, Sphere, Capsule, MeshCollider + Rigidbody / StaticRigidBody
- Multi-collider overflow → child entity generation
- Rigidbody constraint bitmask → O3DE axis-swapped lock flags
- Verbose structured logging with `[Tag]` prefixes throughout all processors
- Settings (paths) persisted per-tab in `converter_settings.json`

**2026-02-06**
- Multi-material component import functional
- Transparency / opacity conversion functional
- Collider and Rigidbody detection added (translation not yet working at this date)
- Mesh / model offsets identified as ongoing issue
