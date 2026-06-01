---
name: terrain-working-doc
description: Living status log for the Terrain importer. Newest entries on top. Tracks shipped pieces, regressions, decisions in flight, and pending items.
metadata:
  type: project
---

# Terrain Tab — Working Documentation

Newest entries on top. Links back to `mem:terrain/terrain_tab_plan`.

## 2026-05-28 — v2 SHIPPED (I.1–I.6 complete, code-side)
All implementation phases landed and verified programmatically against the sample terrain
(`New Terrain2.asset`, Alien Fantasy Forest). Full test suite green (22/22 modules) on Python 3.13.

### Files
- **NEW `platforms/unity/terrain_data.py`** — UnityPy-backed binary TerrainData reader. Lazy import
  (`unitypy_available()` / `_require_unitypy()`). `is_terrain_data`, `scan_for_terrains`,
  `parse_terrain_data(path, want_heightmap, want_alphamaps)`. Dataclasses SplatLayer / HeightmapData /
  AlphamapData / TerrainData. `guid_bytes_to_hex` (nibble-swap) converts UnityPy externals → .meta GUID hex.
- **NEW `targets/o3de/terrain_writer.py`** — all O3DE emission. `TERRAIN_MATERIALTYPE`, `write_detail_material`,
  `write_heightmap_image`, `write_splatmap_images`, `write_terrain_prefab` (+ self-contained `_IdGen`/entity
  builders mirroring prefab_writer's JSON shape, since prefab_writer is worker-coupled).
- **REWORK `platforms/unity/terrain.py`** — `TerrainMaterialProcessor` → `TerrainProcessor` (alias kept).
  `process_terrain(asset, outputs: set)` à la carte; reuses `_copy_texture` dedupe via AssetDatabase.
- **REWORK `main_app.py` TerrainTab** — "Scan for Terrains" + checkable terrain list + Outputs checkbox
  group (materials/heightmap/splatmaps/entity). Settings: `selected_materials` → `selected_terrains` +
  `outputs` (apply_project drops legacy key). Orchestration touchpoints updated (queue, preflight readiness,
  input hash, status/outputs records).
- **NEW `requirements.txt`** — PySide6, UnityPy>=1.10, Pillow.
- **project_manager.py** default terrain_processor stage → selected_terrains + outputs.

### Verified facts from the real asset (decoded, not assumed)
- PPtr → GUID: `externals[m_FileID - 1]`; FileID 0 = local/embedded. Nibble-swap hex matches .meta exactly.
- 6 splat layers; field is `specularMetallic` (Vector4, metallic = .x) + `smoothness` float; tile 5–9.
- Alphamaps: 2 embedded RGBA Texture2D "SplatAlpha 0/1" (1024²); layer N → tex N//4, channel N%4.
- Heightmap: 1025×1025 int16 (0..32767); m_Scale {x,z=0.1953, y=300} → world 200×200, height 300.
  16-bit PNG written normalized (raw/32767*65535), FLIP_TOP_BOTTOM applied (orientation = visual verify item).
- GUIDs resolve through existing `AssetDatabase.resolve_guid` to the real `Ground_Fantasy_forest*` PNGs.

### UnityPy = optional, Unity-platform-only dependency (per user request)
- `DEPENDENCIES` in main_app.py gained a 5th `platform_gate` field; UnityPy gated to `"unity"`.
  `check_dependencies()` skips platform-gated deps when `_active_platform()` != the gate, so UnityPy is only
  flagged missing for Unity sources. ConfigTab hides unreported dep labels. Converter runs without UnityPy;
  the terrain scan/generate paths show a clear "install requirements" message if it's absent.

### Environment gotcha (resolved)
The GUI launcher (`To_O3DE_Project_Converter.bat`) picks **Python 3.13** via `py -3`; Python 3.9 is also
installed but lacks PySide6. UnityPy + Pillow were installed into **both**, but 3.13 is the one that matters.

### OPEN — user O3DE verification (behavioural proofs, not yet done)
- **T-5**: load a detail `.material` in O3DE Material Editor (no missing-texture errors). TerrainBaseMaterial
  property names (`baseColor.textureMap`, `normal.textureMap`, `normal.factor`, `metallic.factor`,
  `roughness.factor`) + `materialTypeVersion: 5` are UNVERIFIED — reconcile against the real materialtype.
- **T-7**: instantiate `<name>.prefab` in O3DE. Terrain component `$type` names + field schemas
  (EditorTerrainLayerSpawnerComponent, EditorAxisAlignedBoxShapeComponent[Dimensions], 
  EditorTerrainHeightGradientListComponent[GradientEntities], EditorTerrainSurfaceMaterialsListComponent
  [Mappings/Surface/MaterialAsset.assetHint], EditorTerrainMacroMaterialComponent, EditorImageGradientComponent
  [Configuration.ImageAsset.assetHint], EditorGradientTransformComponent) are BEST-EFFORT — fix names/fields
  against the live Terrain gem and log here. The `<name>.terrain.json` manifest is the lossless fallback
  record regardless. Per-layer splatmap → surface-mask weighting is documented in the manifest, not yet
  auto-wired into the prefab.

## Heads-up (not terrain work)
At time of writing the tree also carries concurrent/uncommitted work for a **physx mesh collider** feature
(`assetinfo_writer.py`, `integrated_asset_processor.py`, `test_assetinfo_writer.py`, new
`.serena/memories/physx_mesh_collider/`) plus a full-file CRLF flip on `integrated_asset_processor.py`.
None of that is part of the terrain expansion and was left untouched.

## v1 history (superseded 2026-05-28)
The original `.mat`-list tab shipped (TerrainTab + `TerrainMaterialProcessor`) as a generic
StandardPBR→TerrainBaseMaterial copier; it could not handle real Unity terrains (empty Terrain.mat).
Texture copy/dedupe logic carried forward into `TerrainProcessor`.
