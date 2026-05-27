# Source-Platform Plugin Guide

This directory holds **source-engine plugins**. Each plugin teaches the
converter how to read assets from one engine (Unity, Unreal, Godot,
Blender, …) and feed them into the platform-agnostic core, which then
emits O3DE-target output.

The converter ships with [`unity/`](unity/) as the reference plugin.
Adding a new platform is a self-contained directory drop — no core
code changes required.

---

## Big picture

```
your source engine  →  YourPlatform plugin  →  PAC core  →  O3DE output
                         (this directory)        (the worker)     (targets/o3de/)
```

The PAC core (`integrated_asset_processor.py` + `project_manager.py` +
`preflight.py` + `main_app.py`) owns:

- The Conversion Project file (`.u2oproj.json`).
- Per-asset state index + dirty-detection + the patch worker.
- Mission Command preflight + Run All orchestration.
- The shader-profile data model and the materialtype resolver.
- Mission Command UI shell (tabs, dashboard, banner).

Your plugin owns:

- Asset discovery (scrubbing the scope root for prefabs / scenes /
  terrain candidates).
- Parsing (reading source files into neutral data shapes).
- Shader-name resolution for the F-9 profile chain.
- Default shader-profile library.
- Per-source-component-type processors.
- Coordinate-system correction.

Plugins are read-only. They never write to the source engine, make
network calls, or talk to a running engine process — they parse static
asset files on disk.

---

## What's in the box

```
platforms/
    __init__.py             # PLATFORM_REGISTRY + register()
    base.py                 # SourcePlatform ABC — the contract
    types.py                # Neutral data shapes
    README.md               # this file
    unity/                  # reference implementation
        __init__.py
        unity_platform.py   # SourcePlatform subclass
        asset_database.py
        shader.py
        prefab.py
        coordinates.py
        types.py            # Unity-specific dataclasses
        components/         # per-Unity-component-type processors
        README.md
```

A new plugin lives in `platforms/<engine_name>/` alongside Unity.
Estimated total size: **1500–2000 lines** across 5–8 modules.

---

## The contract

Every plugin implements [`SourcePlatform`](base.py) (ABC). The
interface splits into seven sections:

### 1. Identity (class-level constants)

```python
NAME            = "your_engine"        # lower-case enum-style id
DISPLAY         = "Your Engine"        # GUI dropdown label
DESCRIPTION     = "Short tagline."
FILE_EXTENSIONS = {                    # kinds the scrubbers understand
    "prefab":   "*.your_prefab",
    "scene":    "*.your_scene",
    "material": "*.your_mat",
    "shader":   "*.your_shader",
    "mesh":     ["*.fbx", "*.obj"],
    "texture":  ["*.png", "*.tga"],
    "terrain":  "*.your_terrain",
}
UP_AXIS         = "Y"                  # "Y" or "Z"
HANDEDNESS      = "LH"                 # "LH" or "RH"
SUPPORTED_TABS  = ["dashboard", "scenes", "prefabs",
                   "meshes", "materials", "terrain", "config"]
```

`SUPPORTED_TABS` narrows which tabs the GUI shows when this plugin is
active. Omit any tab whose stage your engine has no equivalent for.

### 2. Discovery

```python
def scope_root_label(self) -> str:
    """The text label shown next to the Source Root field on the Dashboard.
    Example: 'Unreal Content directory'."""

def validate_scope_root(self, path: Path) -> List[PreflightItem]:
    """Per-platform sanity check appended to the Environment preflight.
    Return a red item when the path doesn't look like your engine's
    project root; yellow + ack_key for soft warnings."""

def build_asset_index(self, scope_root: Path) -> AssetIndex:
    """Walk the scope and return the plugin's asset-id index. The id
    form is yours to choose (Unity GUID, Unreal soft path, Godot
    res:// path, Blender lib+name pair, ...)."""

def scrub_prefabs(self, scope_root: Path)  -> List[str]: ...
def scrub_scenes(self, scope_root: Path)   -> List[str]: ...
def scrub_terrain(self, scope_root: Path)  -> List[str]: ...
```

Scrubbers return paths **relative to** `scope_root`. The Mission
Command marking tabs surface them as checklists.

### 3. Extraction

```python
def parse_material(self, path: Path) -> PlatformMaterial:
    """Read a source material into the neutral PlatformMaterial shape.
    Populate raw_textures, raw_floats, raw_colors keyed by your
    engine's native property names. The F-9 profile chain translates
    them to O3DE slots."""

def parse_prefab(self, path: Path) -> PlatformPrefab:
    """Read a source prefab into a PlatformPrefab (root + entities +
    parent_map). Each entity carries a PlatformTransform, mesh/material
    asset ids, and raw_components dicts the component processors will
    translate."""

def parse_scene(self, path: Path) -> PlatformScene:
    """Same shape as parse_prefab for scene/level files. If the formats
    are identical (Unity's case), delegate to parse_prefab."""

def resolve_shader_name(self, material: PlatformMaterial) -> str:
    """Friendly shader name used as the key in shader_mappings. Read
    from material.shader_id (the platform-opaque shader identifier)."""
```

### 4. Profile library

```python
def default_profiles(self) -> Dict[str, dict]:
    """Pre-seeded shader-profile library. Ship at least one catch-all
    profile that maps your engine's standard PBR shader to O3DE
    StandardPBR. See platforms/unity/unity_platform.py for the
    reference Default — Anything to PBR profile."""

def default_shader_mappings(self) -> Dict[str, str]:
    """{shader_name: profile_name} dict the project carries on first
    open. Pre-seed common engine shaders (Unity Standard, URP/Lit,
    HDRP/Lit, etc.) so users don't face an empty mappings table."""
```

### 5. Component processors

```python
def component_processors(self) -> List[ComponentProcessor]:
    """Per-component-type processors that translate parsed components
    into O3DE component JSON. See platforms/unity/components/ for the
    reference set. Auto-discovery from a `components/` subdirectory is
    the typical pattern."""
```

Each `ComponentProcessor` subclass declares:
- `HANDLES = ["YourEngineComponentType", ...]` — types it parses.
- `WEIGHT` — execution order (lower runs earlier; Unity uses
  multiples of 25 between 25–510).
- `parse()` — called during parse phase to populate the entity.
- `emit()` — called during O3DE emission to add component JSON.

See [`components/base.py`](unity/components/base.py) for the ABC.

### 6. Coordinate system

```python
def to_o3de_coordinates(self, transform: PlatformTransform
                         ) -> Tuple[PlatformTransform, bool]:
    """Convert a source-space transform to O3DE space (Z-up, RH).
    Returns (converted, scale_was_non_uniform)."""

@property
def correction_quat(self) -> list:
    """Source-axis correction quaternion the O3DE assetinfo writer
    composes onto every CoordinateSystemRule. Unity ships a Y-up→Z-up
    quat; your engine ships whatever's appropriate."""
```

### 7. Preflight extensions

```python
def preflight_checks(self) -> List[Callable]:
    """Optional — additional check functions appended to the
    Mission Command preflight panel. Each callable receives a project
    and returns List[PreflightItem]."""
```

The base class's `validate_scope_root` already plugs into the
Environment category; extra checks are only needed for engine-specific
sanity (e.g. checking that a required dependency is installed).

---

## Neutral data shapes

The shapes your `parse_*` methods produce, defined in
[`types.py`](types.py):

| Type | Purpose |
|---|---|
| `AssetIndex` | id ↔ path mapping. The plugin chooses the id form. |
| `PlatformMaterial` | `name / shader_id / raw_textures / raw_floats / raw_colors / extra`. The PAC core runs the F-9 profile chain over these raw values. |
| `PlatformEntity` | One node in a source scene graph. Carries `entity_id`, `name`, `transform`, `mesh_id`, `material_ids`, `raw_components`. |
| `PlatformPrefab` | `root` + `entities: Dict[id, PlatformEntity]` + `parent_map`. Used for both prefabs and scenes (`PlatformScene` aliases this). |
| `PlatformTransform` | Position + quaternion rotation + scale. Stored as lists; `to_o3de_coordinates` is what swizzles. |

Plugin authors should NOT add fields to these dataclasses. Use the
`PlatformMaterial.extra: Dict[str, Any]` slot for platform-specific
spillover state if you need round-trip data.

---

## Step-by-step: building a new plugin

### Step 1: Scaffold the directory

```bash
mkdir platforms/<engine>
touch platforms/<engine>/__init__.py
touch platforms/<engine>/<engine>_platform.py
touch platforms/<engine>/README.md
```

### Step 2: Write the platform class

```python
# platforms/<engine>/<engine>_platform.py
from platforms.base import SourcePlatform
from platforms.types import (
    AssetIndex, PlatformMaterial, PlatformPrefab, PlatformScene,
    PlatformTransform,
)

class YourEnginePlatform(SourcePlatform):
    NAME    = "your_engine"
    DISPLAY = "Your Engine"
    # ... fill in identity constants ...

    def scope_root_label(self) -> str:
        return "Your engine's project root"

    def validate_scope_root(self, path):
        # red on missing, yellow with ack_key for soft warnings
        ...

    def build_asset_index(self, scope_root):
        ...

    def parse_material(self, path):
        ...

    def parse_prefab(self, path):
        ...

    def parse_scene(self, path):
        return self.parse_prefab(path)   # if your formats are identical

    def resolve_shader_name(self, material):
        ...

    def default_profiles(self):
        from project_manager import DEFAULT_SHADER_PROFILE
        return {"Default — Anything to PBR (Your Engine)": ...}

    def default_shader_mappings(self):
        return {...}

    def component_processors(self):
        from platforms.your_engine.components import load_component_processors
        return load_component_processors(log=None)

    def to_o3de_coordinates(self, transform):
        ...

    @property
    def correction_quat(self):
        return [...]    # source-axis correction quaternion
```

### Step 3: Add component processors

Mirror the layout under
[`platforms/unity/components/`](unity/components/):

```
platforms/<engine>/components/
    __init__.py            # copy from platforms/unity/components/__init__.py
    base.py                # copy or re-export from platforms.unity.components.base
    mesh.py                # one file per component type
    material.py
    light.py
    ...
```

Each `*.py` file declares one or more `ComponentProcessor` subclasses
that get auto-discovered.

### Step 4: Register the plugin

Edit [`platforms/__init__.py`](__init__.py) and add your import to
`_bootstrap_builtin_plugins`:

```python
def _bootstrap_builtin_plugins() -> None:
    from platforms.unity.unity_platform import UnityPlatform
    register(UnityPlatform())
    from platforms.your_engine.your_engine_platform import YourEnginePlatform
    register(YourEnginePlatform())
```

Registration is explicit (no auto-discovery). A broken plugin should
fail loudly at startup rather than silently from a missed scan.

### Step 5: Add the engine to the `SourceEngine` enum

Edit [`project_manager.py`](../project_manager.py):

```python
class SourceEngine(str, Enum):
    UNITY      = "unity"
    UNREAL     = "unreal"
    GODOT      = "godot"
    BLENDER    = "blender"
    YOUR_ENGINE = "your_engine"      # ← add here

    def display_name(self) -> str:
        return {
            SourceEngine.YOUR_ENGINE: "Your Engine",
            ...
        }[self]
```

The engine dropdown picks it up automatically.

### Step 6: Mirror the test coverage

The converter's test suite (`tests/`) is plain Python — no pytest.
Add tests for your plugin under the existing layout:

```
tests/
    fixtures/
        <engine>_project.py     # synthetic source asset tree builder
    unit/
        test_<engine>_platform_contract.py
        test_<engine>_default_profile.py
    integration/
        test_<engine>_material_emission.py
```

See [`tests/README.md`](../tests/README.md) for the test-writing
recipe. The shared harness picks up new files automatically.

---

## Reference: how Unity does it

The Unity plugin is the canonical example. See
[`unity/README.md`](unity/README.md) for a module-by-module
walkthrough.

Quick map:

| Concern | Unity module |
|---|---|
| Asset id index (.meta files → GUIDs) | [`unity/asset_database.py`](unity/asset_database.py) |
| YAML scene-graph parsing | [`unity/prefab.py`](unity/prefab.py) |
| `.shader` → friendly name resolution | [`unity/shader.py`](unity/shader.py) |
| Y-up → Z-up correction quaternion | [`unity/coordinates.py`](unity/coordinates.py) |
| Source-data dataclasses | [`unity/types.py`](unity/types.py) |
| `SourcePlatform` subclass | [`unity/unity_platform.py`](unity/unity_platform.py) |
| Per-component processors | [`unity/components/`](unity/components/) |

---

## Conventions

- **Plugin code is `Optional[T]`-tolerant.** Source files are often
  malformed (missing fields, empty arrays, type mismatches). Use
  `data.get(key, default)` chains and return reasonable defaults
  rather than raising.
- **Plugin code is dependency-light.** PyYAML is fair game. PySide6,
  Pillow, etc. should only appear in optional code paths gated on
  imports.
- **The platform-agnostic core is read-only from plugins' POV.** Don't
  reach into `IntegratedAssetProcessor`, `ProjectManager`, or
  `main_app` from plugin code. The contract is the only allowed
  interface.
- **Logging.** When the plugin runs inside the worker, the worker's
  log callback is reachable via the context dataclasses passed into
  your parsers. Standalone plugin operations (e.g. test scripts) get
  a no-op log.

---

## Further reading

- [`base.py`](base.py) — the `SourcePlatform` ABC with full method
  docstrings.
- [`types.py`](types.py) — neutral data shapes.
- [`unity/README.md`](unity/README.md) — Unity reference case study.
- [`../tests/README.md`](../tests/README.md) — how to write tests.
- [`../AGENTICS_GUIDELINES.md`](../AGENTICS_GUIDELINES.md) — if you're
  an LLM co-developing this codebase with a human, read this first.
- `.serena/memories/platform_abstraction/` — the audit memo + the
  refactor plan that shaped this layout.
