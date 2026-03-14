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
Takes a Unity `.unity` scene file and cross-references it against the library of converted O3DE prefabs. It populates an O3DE level with matching prefab instances, preserving placement transforms and hierarchy structure.

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
| Multi-material slots | EditorMaterialComponent `{0}`, `{1}`... | Working |
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
| Mesh pivot / coordinate rebake | — | Known issue (see below) |

---

## Known Issues

**Mesh coordinate system**
Unity internally rebakes mesh coordinates in a way that does not match the raw FBX on disk. The converter applies the standard Unity → O3DE axis swap (`-x, z, y` for position; `-qx, qz, qy, qw` for rotation) but cannot correct for Unity's internal mesh rebake. A Blender transform-bake pass was attempted and abandoned as ineffectual. This remains the primary visual accuracy issue.

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
    mesh_collider.py    weight=175 MeshCollider

  legacy_unity_prefab_to_o3de.py   Legacy — pending removal
  bake_fbx_transforms.py           Legacy — pending removal
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
