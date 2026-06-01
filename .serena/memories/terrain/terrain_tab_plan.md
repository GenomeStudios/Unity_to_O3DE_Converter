---
name: terrain-tab-plan
description: Design + locked decisions for the Terrain importer. v2 reorients conversion around the binary TerrainData .asset (auto-detected) and emits per-layer detail materials, heightmap, splatmaps, and a full terrain entity. Supersedes the v1 .mat-list design.
metadata:
  type: project
---

# Terrain Tab — Plan (v2: TerrainData-driven)

> **v1 superseded (2026-05-28).** The original design picked Unity `.mat` files and copied them into
> TerrainBaseMaterial envelopes. That is wrong for real terrains: `Terrain.mat` uses Unity's built-in
> `Nature/Terrain/Standard` shader (`m_Shader fileID 10623`) and **all texture slots are `fileID: 0`** —
> splat textures live in the binary `TerrainData` `.asset`, not the material. v1 against a real terrain
> emits an empty material. v2 below makes the `TerrainData` `.asset` the source of truth.

## Goal
Auto-detect the binary `TerrainData` `.asset` under the Unity Assets root and convert it into, à la carte:
1. **Per-splat-layer O3DE detail materials** (`TerrainBaseMaterial.materialtype`) with unique albedo+normal
   textures, tiling, metallic/roughness — pulled from `SplatDatabase.m_Splats`.
2. **Heightmap image** (16-bit PNG + world-size/range sidecar) from `Heightmap.m_Heights`/`m_Scale`.
3. **Splatmap weight masks** from the embedded `m_AlphaTextures` Texture2D objects.
4. **Full O3DE terrain entity** prefab wiring the above (layer spawner + surface materials list + height
   gradient + macro material).

## Resolved Decisions (Q&A history)

**v1 Q1–Q6** — see git history of this memory; superseded.

**v2 Q1 — Extract scope?** A: **All four** outputs (materials / heightmap / splatmaps / full entity).

**v2 Q2 — Binary TerrainData parser?** A: **Add UnityPy** (reads the embedded type tree of the
2017.4-era binary SerializedFile). No `requirements.txt` existed → create one. Pillow already present (11.3).

**v2 Q3 — Detection / UX?** A: **Auto-scan** the Unity Assets root for `TerrainData` `.asset` files and let
the user pick which to convert. `.mat`-picking is obsolete for terrains.

**v2 Q4 — Output independence?** A: The four outputs are **fully à la carte / independent**. Materials-only
("just gather the materials, don't restore the terrain object") is a first-class case — ticking Detail
Materials alone produces `Materials/` + `Textures/` and nothing else; the worker only does work for ticked
outputs (materials-only never decodes the heightmap or alphamaps). The `entity` output emits its
dependencies on the fly when needed, but selecting materials/heightmap/splatmaps does NOT require `entity`.

## Design

### Source-side parse — `platforms/unity/terrain_data.py` (UnityPy, pure parser, no O3DE knowledge)
- `is_terrain_data(path) -> bool` — sniff a SerializedFile for a TerrainData object (class id 156).
- `scan_for_terrains(assets_root) -> list[Path]` — walk `*.asset`, keep those that sniff.
- `parse_terrain_data(path) -> TerrainData`:
  - `layers: list[SplatLayer]` `{albedo_guid, normal_guid, tile_size, tile_offset, metallic, smoothness, normal_scale}`.
    Texture **GUIDs** recovered from the SerializedFile externals table via each PPtr's `file_id`
    (loose project assets store the GUID in `m_Externals`, not inline). GUIDs feed the existing
    `AssetDatabase.resolve_guid` to find the on-disk PNG — reuse, don't reinvent.
  - `heightmap: HeightmapInfo` `{width, height, heights(0..1 grid), scale(x,y,z)}`.
  - `alphamaps: list[AlphamapImage]` — embedded Texture2D objects (why the `.asset` is 15 MB); decoded to
    RGBA; each channel = one layer's weight in `m_Splats` order.

### Target-side emit — `targets/o3de/terrain_writer.py` (keeps the platforms/unity ↔ targets/o3de boundary)
- `write_detail_material` — one `.material` per layer; `TERRAIN_MATERIALTYPE` constant moves here.
  smoothness→roughness via the `1 − smoothness` convention from `AssetDatabase._extract_material_data`.
- `write_heightmap_image` — 16-bit PNG (PIL `I;16`) + `.json` sidecar (world size scale.x/z, height range scale.y).
- `write_splatmap_images` — one grayscale PNG per layer (split RGBA channels).
- `write_terrain_prefab` — full entity reusing `prefab_writer` helpers (`create_container_entity`,
  `make_bare_entity`, `generate_entity_id`, `generate_component_id`, `create_o3de_prefab`). Components:
  TerrainLayerSpawner, TerrainSurfaceMaterialsList, TerrainHeightGradientList + ImageGradient, TerrainMacroMaterial.
  **O3DE component type names + field schemas UNVERIFIED in this repo (no O3DE source tree)** — emitted from
  terrain-gem knowledge, proven by loading in O3DE (T-7); divergences fixed + logged in working doc.

### Output layout (extends existing `Terrain/` root)
```
<output>/Terrain/
  Materials/   <TerrainName>_Layer<N>_<albedoStem>.material
  Textures/    copied albedo + normal PNGs (deduped by GUID)
  Heightmaps/  <name>_height.png + <name>_height.json
  Splatmaps/   <name>_Layer<N>.png
  Prefabs/     <name>.prefab
```

### Worker — `platforms/unity/terrain.py`
`TerrainMaterialProcessor` → `TerrainProcessor` (thin alias kept). `process_terrain(asset, outputs: set[str])`,
`outputs ⊆ {materials, heightmap, splatmaps, entity}`. Always parses (cheap); runs only ticked outputs.
Retains/reuses `_copy_texture` + `_processed_textures` dedupe.

### UI — `main_app.py::TerrainTab`
Replace .mat add/remove/clear with a "Scan for Terrains" button → checkable list of detected `.asset`.
Add output-toggle checkboxes (Detail Materials / Heightmap / Splatmaps / Full Terrain Entity, default all on).
Settings under `terrain_processor`: `selected_materials` → `selected_terrains` + `outputs`; one-time migration
drops the old key. Worker calls `TerrainProcessor.process_terrain` per selected terrain.

### Orchestration / project outputs
Keep `terrain_processor` stage key (preflight + Mission Command touchpoints at main_app ~557, 625, 1853,
2058, 2268, 2712, 6870, 6964). `update_outputs` record becomes terrain-keyed. Preflight readiness:
"≥1 material selected" → "≥1 terrain selected".

### Dependencies
New `requirements.txt`: `UnityPy>=1.10`, `Pillow`.

## Implementation Plan (P / I / T)
- **I.1** `terrain_data.py` + UnityPy + `tests/test_terrain_data.py` (T-1,2,3). Pivot.
- **I.2** `terrain_writer.write_detail_material` + worker `materials` (T-4,5). Pivot.
- **I.3** `write_heightmap_image` + worker `heightmap` (T-6).
- **I.4** `write_splatmap_images` + worker `splatmaps` (T-6).
- **I.5** `write_terrain_prefab` + worker `entity` (T-7).
- **I.6** TerrainTab UI rework + orchestration/output wiring (T-8,9).

## Testing matrix
| ID | Proof | Phase |
|----|-------|-------|
| T-1 | UnityPy installs; `New Terrain2.asset` sniffs as TerrainData; scan finds it | I.1 |
| T-2 | Layer count as expected; each layer albedo/normal GUID resolves via AssetDatabase to a `Ground_Fantasy_*` PNG | I.1 |
| T-3 | Heightmap width/height>0; alphamap count ≥1 (unit test) | I.1 |
| T-4 | One `.material`/layer; JSON parses; references TerrainBaseMaterial.materialtype; `../Textures/...` paths | I.2 |
| T-5 | Detail `.material` loads in O3DE without missing-texture errors (user) | I.2 |
| T-6 | 16-bit heightmap PNG at grid res + sidecar correct; one splatmap PNG/layer (user visual) | I.3+I.4 |
| T-7 | `<name>.prefab` instantiates an O3DE terrain w/ height shape + blended layers (user; schema fixed if names diverge) | I.5 |
| T-8 | App launches; scan/list/toggles work; **materials-only → only Materials/+Textures/**; settings round-trip | I.6 |
| T-9 | Mission Command/preflight ready when ≥1 terrain selected; update_outputs records run | I.6 |

## Out of scope
Detail/macro mesh export; tree (`m_TreeInstances`) / grass (`m_DetailPrototypes`) instancing; multi-terrain
blend into one world; terrain patch-worker state-index; non-UnityPy fallback parser.

Sample test asset: `D:\OffLocalDev\Contracting\artificer\Assets\Alien Fantasy Forest\Terrain\New Terrain2.asset`
(+ `Ground_Fantasy_forest*` PNGs, `Terrain.mat`/`Test ground.mat`).
