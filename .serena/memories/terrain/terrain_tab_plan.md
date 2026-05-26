---
name: terrain-tab-plan
description: Design + locked decisions for the Terrain importer tab — converts user-picked Unity .mat files into O3DE TerrainBaseMaterial .material files plus textures.
metadata:
  type: project
---

# Terrain Tab — Plan

## Goal
A new GUI tab ("Terrain") in `main_app.py`, ordered between `Scene Converter` and `Config`, that lets the user pick specific Unity `.mat` files and convert each into an O3DE terrain detail material (referencing `@gemroot:Terrain@/Assets/Materials/Types/TerrainBaseMaterial.materialtype`) along with its textures.

## Resolved Decisions (Q&A history)

**Q1 — Output target?**
A: Single terrain detail material per selected Unity material, with its textures copied. No macro materials, no surface-tag/SurfaceMaterialsListComponent in this scope.

**Q2 — How are candidate materials discovered?**
A: User picks `.mat` files directly via file dialog. No prefab scanning. The original phrase "prefabs as source of truth" was overridden by this answer — `Terrain` tab does not parse prefabs at all in this iteration.

**Q3 — Per-material role / tag?**
A: Flat checked list, no per-material metadata. Each selected `.mat` produces one output `.material` named after the source stem.

**Q4 — Source folder?**
A: Separate from Prefab Processor. Terrain tab owns its own Unity Assets root field. The Assets root is required because the AssetDatabase indexes `.meta` files there to resolve texture GUIDs referenced by the selected `.mat`.

**Q5 — Which O3DE materialtype?**
A: `@gemroot:Terrain@/Assets/Materials/Types/TerrainBaseMaterial.materialtype`.

**Q6 — Staging?**
A: One stage — full tab + emission in one go. (User-elected.)

## Design

### UI layout (TerrainTab)
- Section "Unity Assets Folder" — `_path_row("Select Unity project Assets folder…")`
- Section "Output Folder" — `_path_row("Select O3DE output destination folder…")`
- Section "Selected Unity Materials" — `QListWidget` (multi-select) + button row:
  - **Add Materials…** — `QFileDialog.getOpenFileNames` filtered to `*.mat`
  - **Remove Selected**
  - **Clear All**
- Section "Output Structure" info box (read-only): describes `Terrain/Materials/` and `Terrain/Textures/`.
- Section "Processing Log" — same `_log_widget()`
- Button row: **Save Log…** / **Generate Terrain Materials** (primary).

### Output layout
- `<output>/Terrain/Materials/<MaterialName>.material`
- `<output>/Terrain/Textures/<copied texture files>`

### Settings persistence
Key `terrain_processor` in `converter_settings.json`:
```
{
  "terrain_processor": {
    "source_path":        "<unity assets root>",
    "output_path":        "<o3de output root>",
    "selected_materials": ["<abs path>", ...]
  }
}
```

### Implementation module
New file `terrain_material_processor.py` exposes `TerrainMaterialProcessor`:

```python
class TerrainMaterialProcessor:
    def __init__(self, unity_assets_root: Path, output_root: Path, log_callback=None): ...
    def process_materials(self, material_paths: list[Path]) -> dict: ...
```

Reuses `AssetDatabase` from `integrated_asset_processor` for GUID indexing and `parse_material`. Reimplements (minimal) the material-extraction + texture-copy + .material-write steps with `TerrainBaseMaterial` as the materialtype string.

**Assumption (testable on first run):** TerrainBaseMaterial accepts the same StandardPBR property paths (`baseColor.textureMap`, `normal.textureMap`, `roughness.factor`, etc.). If property names diverge, capture mismatches in working doc and iterate.

### Wiring change in `main_app.py`
```python
tabs.addTab(PrefabProcessorTab(), "Prefab Processor")
tabs.addTab(SceneConverterTab(),  "Scene Converter")
tabs.addTab(TerrainTab(),         "Terrain")      # ← new
tabs.addTab(ConfigTab(),          "Config")
```

The `--tab=` argument parser stays as-is (it only switches between `prefab` and `scene`). No new CLI arg needed.

## Implementation Plan

### I.1 — Plan + working doc memories
Done when: this file plus `working_documentation.md` exist under `.serena/memories/terrain/`.

### I.2 — `terrain_material_processor.py`
Done when:
- Module exists, defines `TerrainMaterialProcessor`.
- `process_materials([Path,...])` writes one `.material` per input under `<output>/Terrain/Materials/` and copies referenced textures to `<output>/Terrain/Textures/`.
- Returns a dict `{ "materials_written": int, "textures_written": int, "errors": [str] }`.

### I.3 — `TerrainTab` + tab wiring in `main_app.py`
Done when:
- `TerrainTab(QWidget)` class added between `SceneConverterTab` and `ConfigTab` definitions.
- Tab registered in `MainWindow.__init__` in the order above.
- Settings load/save round-trip under `terrain_processor`.
- Worker thread runs `TerrainMaterialProcessor.process_materials` off the GUI thread.
- App launches, tab appears in the correct position, fields persist.

### I.4 — Smoke test
Done when: `python main_app.py` launches without exception and the Terrain tab is interactive (browse, add/remove materials, persistence verified across restart).

## Testing matrix

| ID | Proof | Phase |
|----|-------|-------|
| T-1 | App launches, all four tabs present in order Prefab Processor / Scene Converter / Terrain / Config | I.3 |
| T-2 | Terrain tab settings round-trip (set source + output + add 2 .mat files, restart app, verify list restored) | I.3 |
| T-3 | Generate against 1 known .mat (with baseColor + normal textures) → `<output>/Terrain/Materials/<name>.material` exists, references `TerrainBaseMaterial.materialtype`, textures copied to `Terrain/Textures/` with correct `../Textures/...` relative paths | I.2 + I.3 |
| T-4 | `.material` JSON is parseable and contains expected property keys (`baseColor.textureMap`, `normal.textureMap`, factors as applicable) | I.2 |

T-3 and T-4 require the user to verify by running the app once the code lands. They are behavioural proofs, not unit tests.

## Out of scope (deliberately)
- Prefab scanning / discovery (Q2 decision).
- Per-material surface tags / SurfaceMaterialsListComponent (Q1 decision).
- TerrainMacroMaterialComponent emission.
- Heightmap / Image Gradient / PhysX heightfield generation.
- TerrainSpawner / TerrainWorld component emission.
- Per-material role assignment (Q3 decision).
- Smoothness→Roughness re-bake (terrain tab will plain-copy textures regardless of the Config flag in this iteration).
