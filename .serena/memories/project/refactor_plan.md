# Refactor Plan: Unified PySide6 GUI + Modular Component Processors
# STATUS: IN PROGRESS — delete after user verifies completion
# Created: 2026-03-13

---

## Goal Summary
1. Replace both tkinter GUIs with a single PySide6 app (`main_app.py`) with two tabs
2. Break component processing into auto-discovered, ordered plugin modules in `components/`
3. Add verbose structured logging throughout
4. Keep all existing core converter logic intact

---

## Final File Structure

```
unity_to_o3de_converter/
  main_app.py                      ← NEW: PySide6 unified GUI entry point
  integrated_asset_processor.py    ← REFACTORED: remove tkinter GUI class, wire component registry
  unity_scene_converter_gui.py     ← REFACTORED: remove tkinter GUI class, keep core converter
  converter_settings.json          ← unchanged
  UnityConverter.bat               ← NEW: single launcher (python main_app.py)
  UnityPrefabConverter.bat         ← keep for legacy, or update to call main_app.py
  UnitySceneImporter.bat           ← keep for legacy, or update to call main_app.py

  components/
    __init__.py                    ← auto-discovery: load_component_processors() -> List[ComponentProcessor]
    base.py                        ← ComponentProcessor ABC + ProcessingContext dataclass
    mesh.py                        ← WEIGHT=25:  MeshFilter + MeshRenderer (parse + emit EditorMeshComponent)
    material.py                    ← WEIGHT=50:  Material (parse material_guids, emit EditorMaterialComponent)
    rigidbody.py                   ← WEIGHT=75:  Rigidbody (parse + emit EditorRigidBodyComponent)
    box_collider.py                ← WEIGHT=100: BoxCollider (parse + emit Box shape + ShapeCollider)
    sphere_collider.py             ← WEIGHT=125: SphereCollider (parse + emit Sphere shape + ShapeCollider)
    capsule_collider.py            ← WEIGHT=150: CapsuleCollider (parse + emit Capsule shape + ShapeCollider)
    mesh_collider.py               ← WEIGHT=175: MeshCollider (parse + emit EditorMeshColliderComponent)
```

---

## Step 1: Create `components/base.py`

Define the ABC and context dataclass. Every processor inherits from `ComponentProcessor`.

```python
# ============================================================
# COMPONENT PROCESSOR BASE
# ============================================================

@dataclass
class ProcessingContext:
    """Passed to all component processors during emit phase."""
    material_mapping: Dict[str, str]    # unity guid -> o3de asset hint
    mesh_mapping: Dict[str, str]        # unity guid -> o3de asset hint
    entities_dict: Dict                 # entity_id -> entity dict (mutated in place)
    entity_id_map: Dict[str, str]       # go.file_id -> entity_id
    generate_component_id: Callable[[], str]
    generate_entity_id: Callable[[], str]
    make_bare_entity: Callable[[str, str, str], Dict]
    log: Callable[[str], None]

class ComponentProcessor(ABC):
    WEIGHT: int = 100         # lower runs first; ties broken by file discovery order (stable sort)
    HANDLES: List[str] = []   # Unity component type names handled in parse phase
    EMITS: List[str] = []     # (optional doc) what O3DE components are emitted

    def parse(self, comp_type: str, comp_data: Dict, go: 'GameObject', log: Callable) -> None:
        """
        Parse phase: called during _build_hierarchy for each Unity component doc.
        Populate go fields (go.mesh_guid, go.material_guids, go.colliders, etc.)
        or go.component_data[key] for processor-specific data.
        """

    def emit(self, go: 'GameObject', entity: Dict, ctx: ProcessingContext) -> List[str]:
        """
        Emit phase: called during _create_entity_recursive after transform is set.
        Mutate entity['Components'] dict.
        Return list of child entity_ids created (for multi-collider child entities).
        """
        return []
```

---

## Step 2: Create `components/__init__.py` — Auto-Discovery

```python
# ============================================================
# AUTO-DISCOVERY: load all ComponentProcessor subclasses
# from files in this directory, ordered by WEIGHT
# Ties are broken by file discovery order (Python sort is stable)
# ============================================================

import importlib, pkgutil, inspect
from pathlib import Path
from .base import ComponentProcessor

def load_component_processors(log=None) -> List[ComponentProcessor]:
    """
    Scan components/ directory for modules, import each, collect all
    ComponentProcessor subclasses (excluding the base ABC itself),
    sort by WEIGHT (stable — discovery order wins on ties),
    return instantiated list.
    """
    processors = []
    pkg_dir = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        if module_name in ('base',):
            continue
        module = importlib.import_module(f'.{module_name}', package=__package__)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ComponentProcessor) and obj is not ComponentProcessor:
                instance = obj()
                processors.append(instance)
                if log:
                    log(f"  [Registry] Loaded: {name} "
                        f"(weight={instance.WEIGHT}, handles={instance.HANDLES})")

    processors.sort(key=lambda p: p.WEIGHT)   # stable sort: equal weights keep discovery order
    return processors

def build_dispatch_table(processors: List[ComponentProcessor]) -> Dict[str, ComponentProcessor]:
    """Build {unity_type: processor} lookup from loaded processors."""
    table = {}
    for proc in processors:
        for unity_type in proc.HANDLES:
            table[unity_type] = proc
    return table
```

---

## Step 3: Refactor `integrated_asset_processor.py`

### Changes to `IntegratedAssetProcessor.__init__`
Add component registry initialization:
```python
from components import load_component_processors, build_dispatch_table

# In __init__:
self.component_processors = load_component_processors(log_callback)
self.component_dispatch = build_dispatch_table(self.component_processors)
self.log(f"  Registered {len(self.component_processors)} component processors")
```

### Changes to `_parse_unity_prefab`
Replace the `elif 'BoxCollider' in doc` chain with dispatcher:
```python
# Current code detects: MeshFilter, MeshRenderer, Rigidbody,
# BoxCollider, SphereCollider, CapsuleCollider, MeshCollider
# Replace with:
for known_type in self.component_dispatch.keys():
    if known_type in doc:
        components_data[anchor] = {'type': known_type, 'data': doc[known_type]}
        break
```

### Changes to `_build_hierarchy` (parse phase dispatch)
Replace the `if comp_type == 'MeshRenderer': ... elif ...` block with:
```python
if comp_type in self.component_dispatch:
    processor = self.component_dispatch[comp_type]
    self.log(f"    [Parse] {comp_type} -> {processor.__class__.__name__}")
    processor.parse(comp_type, comp_data, go, self.log)
else:
    self.log(f"    [Parse] ⚠ No processor for component type: {comp_type}")
```

### Changes to `_create_entity_recursive` (emit phase dispatch)
After TransformComponent is set, replace the MeshComponent/MaterialComponent/_create_physx_components block with:
```python
ctx = ProcessingContext(
    material_mapping=material_mapping,
    mesh_mapping=mesh_mapping,
    entities_dict=entities_dict,
    entity_id_map=entity_id_map,
    generate_component_id=self._generate_component_id,
    generate_entity_id=self._generate_entity_id,
    make_bare_entity=self._make_bare_entity,
    log=self.log,
)
collider_child_ids = []
for processor in self.component_processors:
    child_ids = processor.emit(go, entity, ctx)
    collider_child_ids.extend(child_ids)
```

### Remove from `integrated_asset_processor.py`
- `IntegratedProcessorGUI` class (entire class, ~300 lines)  
- `_process_material`, `_process_texture`, `_process_mesh` stay in `IntegratedAssetProcessor`
- `_create_physx_components`, `_add_mesh_collider`, `_add_shape_collider` move INTO their respective component modules
- `main()` function at bottom replaced by a simple shim: `from main_app import main; main()`

---

## Step 4: Individual Component Modules

### `components/mesh.py`
- WEIGHT = 25
- HANDLES = ['MeshFilter', 'MeshRenderer']
- parse: MeshFilter → go.mesh_guid; MeshRenderer → go.material_guids
- emit: if go.mesh_guid → add EditorMeshComponent with mesh assetHint
- Log: "  [Mesh] Assigned mesh: {mesh_path}" or "  [Mesh] ⚠ Mesh GUID not in mapping: {guid}"

### `components/material.py`
- WEIGHT = 50
- HANDLES = [] (no parse phase — material_guids populated by mesh processor)
- emit: if go.material_guids → add EditorMaterialComponent with indexed slots {0}, {1}...
- Log: "  [Material] {N} material slots assigned" / "  [Material] ⚠ Slot {i} GUID not in mapping"

### `components/rigidbody.py`
- WEIGHT = 75
- HANDLES = ['Rigidbody']
- parse: → go.has_rigidbody = True, go.rigidbody_data = {mass, drag, angular_drag, use_gravity, is_kinematic, constraints}
- emit: → EditorRigidBodyComponent with config; if no rigidbody but go.colliders → EditorStaticRigidBodyComponent
- Log: "  [Rigidbody] mass={mass}, kinematic={kin}, gravity={grav}, constraints={con}"

### `components/box_collider.py`
- WEIGHT = 100, HANDLES = ['BoxCollider']
- parse: → appends to go.colliders: {type, center, size, is_trigger}
- emit: → EditorBoxShapeComponent + EditorShapeColliderComponent (on main or child entity)

### `components/sphere_collider.py`
- WEIGHT = 125, HANDLES = ['SphereCollider']
- parse: → go.colliders: {type, center, radius, is_trigger}
- emit: → EditorSphereShapeComponent + EditorShapeColliderComponent

### `components/capsule_collider.py`
- WEIGHT = 150, HANDLES = ['CapsuleCollider']
- parse: → go.colliders: {type, center, radius, height, direction, is_trigger}
- emit: → EditorCapsuleShapeComponent + EditorShapeColliderComponent

### `components/mesh_collider.py`
- WEIGHT = 175, HANDLES = ['MeshCollider']
- parse: → go.colliders: {type, mesh_guid, convex, is_trigger}
- emit: → EditorMeshColliderComponent with mesh asset ref

### Multi-collider logic (shared, lives in base.py or collider utils)
When idx > 0 (more than one collider on a GO), create child entity via ctx.make_bare_entity,
add StaticRigidBody to child, return child_id. This logic currently in _create_physx_components
should move to a shared helper imported by all collider emit methods.

---

## Step 5: Create `main_app.py` — PySide6 Unified GUI

### Structure
```
main_app.py
  ├── THEME QSS string (dark theme constants)
  ├── LogSignal(QObject)            # thread-safe log signal
  ├── WorkerThread(QThread)         # generic worker for processing/conversion
  ├── PrefabProcessorTab(QWidget)   # replaces IntegratedProcessorGUI
  ├── SceneConverterTab(QWidget)    # replaces SceneConverterGUI
  ├── MainWindow(QMainWindow)       # QTabWidget container
  └── main()
```

### PySide6 Widgets Mapping (from tkinter)
| tkinter | PySide6 |
|---|---|
| ttk.Frame | QFrame / QWidget |
| ttk.Label | QLabel |
| ttk.Entry + StringVar | QLineEdit |
| ttk.Button | QPushButton |
| ScrolledText | QTextEdit (ReadOnly) |
| tk.Listbox | QListWidget |
| ttk.LabelFrame | QGroupBox |
| filedialog.askdirectory | QFileDialog.getExistingDirectory |
| filedialog.askopenfilename | QFileDialog.getOpenFileName |
| root.after(0, fn) | QTimer.singleShot(0, fn) |
| threading.Thread | QThread subclass |
| messagebox.showinfo | QMessageBox.information |
| messagebox.showerror | QMessageBox.critical |

### PrefabProcessorTab fields (same as IntegratedProcessorGUI)
- source_path: QLineEdit + Browse button
- output_path: QLineEdit + Browse button
- blender_path: QLineEdit + Browse + Auto-detect buttons
- blender_status: QLabel
- log_output: QTextEdit (ReadOnly, monospace font)
- process_btn: QPushButton ("Process Assets")
- Settings key: "asset_processor" in converter_settings.json

### SceneConverterTab fields (same as SceneConverterGUI)
- scene_path: QLineEdit + Browse button
- output_path: QLineEdit + Browse button
- prefab_dirs: QListWidget + Add/Remove/Clear buttons
- log_output: QTextEdit (ReadOnly, monospace font)
- convert_btn: QPushButton ("Convert Scene")
- Settings key: "scene_converter" in converter_settings.json

### Dark Theme QSS (approximate)
```css
QMainWindow, QWidget { background: #1e1e2e; color: #cdd6f4; }
QTabWidget::pane { border: 1px solid #45475a; }
QTabBar::tab { background: #313244; color: #cdd6f4; padding: 8px 16px; }
QTabBar::tab:selected { background: #89b4fa; color: #1e1e2e; }
QLineEdit { background: #313244; border: 1px solid #45475a; color: #cdd6f4; padding: 4px; border-radius: 4px; }
QPushButton { background: #45475a; color: #cdd6f4; border: none; padding: 6px 14px; border-radius: 4px; }
QPushButton:hover { background: #89b4fa; color: #1e1e2e; }
QPushButton#primary { background: #89b4fa; color: #1e1e2e; font-weight: bold; }
QTextEdit { background: #181825; color: #a6e3a1; font-family: Consolas, monospace; font-size: 9pt; border: 1px solid #45475a; }
QListWidget { background: #313244; border: 1px solid #45475a; color: #cdd6f4; }
QGroupBox { border: 1px solid #45475a; border-radius: 4px; margin-top: 8px; color: #89b4fa; }
QLabel#status_ok { color: #a6e3a1; }
QLabel#status_warn { color: #f9e2af; }
```

### Thread-safe logging
```python
class LogSignal(QObject):
    message = Signal(str)

class WorkerThread(QThread):
    log_signal = LogSignal()
    finished = Signal(bool, str)   # success, summary_message
    
    def __init__(self, fn, *args):
        self._fn = fn
        self._args = args
    
    def run(self):
        self._fn(*self._args, log=lambda msg: self.log_signal.message.emit(msg))
```
Tab connects `worker.log_signal.message` to `self._append_log(msg)` which calls `log_output.append(msg)`.

---

## Step 6: Verbose Logging Standards

All log messages should follow these prefixes for easy filtering:

| Prefix | Meaning |
|---|---|
| `[Registry]` | Component processor discovery at startup |
| `[Parse]` | YAML parsing events |
| `[Hierarchy]` | Parent/child resolution |
| `[Mesh]` | Mesh asset processing |
| `[Material]` | Material/texture processing |
| `[Physics]` | Collider/rigidbody events |
| `[Prefab]` | Prefab output generation |
| `[Scene]` | Scene conversion events |
| `✓` | Success |
| `⚠` | Warning / partial |
| `✗` | Error / failure |

---

## Step 7: Update `.bat` Files

`UnityConverter.bat`:
```bat
python main_app.py
```

Keep existing `.bat` files working by having them call main_app.py with a `--tab prefab` or `--tab scene` argument (optional).

---

## Step 8: `GameObject` Dataclass Extension

Add to `GameObject` in `integrated_asset_processor.py`:
```python
component_data: Dict[str, Any] = field(default_factory=dict)
```
This allows future processors to store arbitrary parsed data without modifying the dataclass.

---

## Execution Order

1. Create `components/base.py` (ProcessingContext + ComponentProcessor ABC)
2. Create `components/__init__.py` (auto-discovery)
3. Create each component module `mesh.py` through `mesh_collider.py`
   - Move logic FROM `_build_hierarchy` and `_create_entity_recursive` / `_create_physx_components` INTO respective modules
4. Refactor `IntegratedAssetProcessor`:
   - Add component_dispatch to __init__
   - Replace parse dispatch in `_parse_unity_prefab` and `_build_hierarchy`
   - Replace emit block in `_create_entity_recursive`
   - Remove `_create_physx_components`, `_add_mesh_collider`, `_add_shape_collider` (moved to modules)
   - Remove `IntegratedProcessorGUI` class
5. Refactor `unity_scene_converter_gui.py`:
   - Remove `SceneConverterGUI` class
   - Keep `UnitySceneConverter`, `PrefabDatabase`, `Transform`, `GameObject`
6. Create `main_app.py` with PySide6 unified GUI
7. Update `.bat` files

---

## Notes / Watch-outs
- `unity_scene_converter_gui.py` has its OWN `Transform` and `GameObject` classes (duplicated from integrated_asset_processor.py). These should remain as-is for now to avoid breaking scene converter; consider unifying into a shared `models.py` in a future pass.
- The scene converter (`UnitySceneConverter`) does NOT use the component processor system — it only places prefab instances in a level. No need to wire component modules into it.
- Settings file key for prefab tab is `"asset_processor"`, for scene tab is `"scene_converter"` — match these exactly.
- Blender integration (bake_fbx_with_blender) stays in integrated_asset_processor.py — it's called from the asset processor's mesh processing, not a component module.
- PySide6 must be installed: `pip install PySide6`
