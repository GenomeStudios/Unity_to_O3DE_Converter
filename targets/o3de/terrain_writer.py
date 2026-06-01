#!/usr/bin/env python3
"""
=============================================================================
O3DE TERRAIN EMITTER  (targets.o3de.terrain_writer)
=============================================================================

Target-side writer: turns parsed Unity terrain data (from
``platforms.unity.terrain_data``) into O3DE artifacts. Knows nothing about
Unity binary formats — it consumes the plain dataclasses and emits files.

Outputs (all optional / à la carte):
  - write_detail_material  -> one TerrainBaseMaterial .material per splat layer
  - write_heightmap_image  -> 16-bit heightmap PNG + world-size sidecar  (I.3)
  - write_splatmap_images  -> per-layer grayscale weight PNG             (I.4)
  - write_terrain_prefab   -> full terrain entity .prefab                (I.5)

NOTE: O3DE TerrainBaseMaterial property names and the terrain component
schemas are NOT verified against an O3DE source tree in this repo. The
conservative PBR-shared property set below is the most likely to load against
TerrainBaseMaterial; any divergence surfaces when the .material is opened in
O3DE and is reconciled there (plan T-5). Tiling is intentionally NOT written
into the detail material (unknown keys can break material load) — it travels
with the layer into the terrain-entity stage where O3DE applies it.
"""

import json
import random
from array import array
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

TERRAIN_MATERIALTYPE = (
    "@gemroot:Terrain@/Assets/Materials/Types/TerrainBaseMaterial.materialtype"
)
# Matches the StandardPBR envelope version the rest of the converter emits.
# Unverified against TerrainBaseMaterial specifically — see module note.
MATERIAL_TYPE_VERSION = 5


# =============================================================================
# DETAIL MATERIAL (one per splat layer)
# =============================================================================

def detail_material_filename(terrain_name: str, layer, albedo_stem: str) -> str:
    """Stable, unique name for a layer's detail material."""
    stem = albedo_stem or f"layer{layer.index}"
    return f"{_safe(terrain_name)}_Layer{layer.index}_{_safe(stem)}.material"


def write_detail_material(layer, albedo_rel: str, normal_rel: str,
                          out_path: Path) -> None:
    """
    Write one O3DE terrain detail material for ``layer``.

    ``albedo_rel`` / ``normal_rel`` are texture paths relative to the
    .material's own folder (e.g. ``../Textures/foo.png``) or None/"".
    Smoothness is converted to roughness with the same ``1 - smoothness``
    convention the StandardPBR path uses.
    """
    props: Dict[str, object] = {}

    if albedo_rel:
        props["baseColor.textureMap"] = albedo_rel
    if normal_rel:
        props["normal.textureMap"] = normal_rel
        props["normal.factor"] = 1.0

    # No metallic/roughness textures on terrain splats -> factors are valid.
    props["metallic.factor"] = _clamp01(layer.metallic)
    props["roughness.factor"] = _clamp01(1.0 - layer.smoothness)

    material = {
        "materialType":        TERRAIN_MATERIALTYPE,
        "materialTypeVersion": MATERIAL_TYPE_VERSION,
        "propertyValues":      props,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(material, f, indent=4)


# =============================================================================
# HEIGHTMAP IMAGE  (I.3)
# =============================================================================

def write_heightmap_image(heightmap, out_png: Path) -> dict:
    """
    Write a 16-bit grayscale heightmap PNG plus a world-size sidecar JSON
    (``<stem>.json`` beside the PNG). Returns the sidecar dict.

    Unity stores heights as int16 in [0, HEIGHT_DIVISOR]; we rescale to the
    full 16-bit range so O3DE's Image Gradient uses the entire precision band.
    The image is flipped vertically so its top row is +Z (Unity samples run
    from the terrain's near/-Z edge) — orientation is a visual verify point.
    """
    from PIL import Image  # lazy: Pillow only needed on this path

    w, h = heightmap.width, heightmap.height
    if w <= 0 or h <= 0 or len(heightmap.heights) != w * h:
        raise ValueError(
            f"heightmap dimensions invalid: {w}x{h}, {len(heightmap.heights)} samples")

    divisor = float(heightmap.HEIGHT_DIVISOR) or 1.0
    scale = 65535.0 / divisor
    samples = array("H", (min(65535, max(0, int(v * scale)))
                          for v in heightmap.heights))

    img = Image.frombytes("I;16", (w, h), samples.tobytes())
    img = img.transpose(Image.FLIP_TOP_BOTTOM)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)

    raw_min = min(heightmap.heights) if heightmap.heights else 0
    raw_max = max(heightmap.heights) if heightmap.heights else 0
    sidecar = {
        "resolution":    [w, h],
        "world_size_x":  heightmap.world_size_x,
        "world_size_z":  heightmap.world_size_z,
        "height_range":  heightmap.scale_y,                       # world units at normalized 1.0
        "height_min":    (raw_min / divisor) * heightmap.scale_y,
        "height_max":    (raw_max / divisor) * heightmap.scale_y,
        "bit_depth":     16,
    }
    out_json = out_png.with_suffix(".json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=4)
    return sidecar


# =============================================================================
# SPLATMAPS  (I.4)
# =============================================================================

def write_splatmap_images(terrain, out_dir: Path) -> Dict[int, str]:
    """
    Split the embedded RGBA splatmaps into one grayscale weight PNG per layer.
    Unity packs four layers per RGBA splatmap in m_Splats order, so layer N's
    weight is channel ``N % 4`` of splatmap ``N // 4``. Returns
    {layer_index: filename}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[int, str] = {}

    for layer in terrain.layers:
        amap, channel = terrain.alphamap_for_layer(layer.index)
        if amap is None or amap.image is None:
            continue
        bands = amap.image.split()           # R, G, B, A
        if channel >= len(bands):
            continue
        weight = bands[channel]              # single-channel grayscale weight
        fname = f"{_safe(terrain.name)}_Layer{layer.index}.png"
        weight.save(out_dir / fname)
        written[layer.index] = fname

    return written


# =============================================================================
# FULL TERRAIN ENTITY  (I.5)
# =============================================================================
#
# O3DE terrain is assembled from several components spread over a small entity
# tree. The component $type names below follow the O3DE Terrain gem's editor
# component names; their internal UUIDs and field schemas are NOT verified
# against an O3DE source tree here, so the emitted prefab is BEST-EFFORT and is
# proven (and reconciled) by loading it in O3DE (plan T-7). To guarantee the
# conversion is never lossy regardless, ``write_terrain_prefab`` also writes a
# ``<name>.terrain.json`` manifest capturing the full structured intent
# (world size, height range, per-layer material + splatmap + tiling) and the
# manual O3DE setup steps.

# Standard O3DE terrain entity tree:
#   <Terrain root>      LayerSpawner + AxisAlignedBox + HeightGradientList
#                       + SurfaceMaterialsList + MacroMaterial
#     <Height Gradient> ImageGradient(heightmap) + GradientTransform + Box

def write_terrain_prefab(terrain, material_rels: Dict[int, str],
                         heightmap_rel: Optional[str],
                         splatmap_rels: Dict[int, str],
                         out_prefab: Path,
                         asset_hint_root: str = "") -> dict:
    """
    Emit a best-effort O3DE terrain ``.prefab`` plus a ``<name>.terrain.json``
    manifest. ``*_rel`` paths are relative to the Terrain output root.
    ``asset_hint_root`` is the project-relative lowercased prefix every
    emitted assetHint must carry (e.g. ``assets/art/alien fantasy forest``).
    Empty string keeps the legacy behaviour, which emits cache-key-naive
    hints that only resolve when the output happens to sit directly under
    the project root.
    Returns the manifest dict.
    """
    name = terrain.name
    ids = _IdGen()

    world = terrain.heightmap
    box_x = world.world_size_x if world else 0.0
    box_z = world.world_size_z if world else 0.0
    box_y = world.scale_y if world else 0.0

    height_entity_id = ids.entity()
    root_entity_id   = ids.entity()

    # ── Height gradient entity (ImageGradient over the heightmap) ────────────
    height_entity = _bare_entity(ids, height_entity_id, "Height Gradient", root_entity_id)
    if heightmap_rel:
        height_entity["Components"]["EditorImageGradientComponent"] = {
            "$type": "EditorImageGradientComponent",
            "Id": ids.component(),
            "Configuration": {"ImageAsset": {"assetHint": _terrain_assetHint(asset_hint_root, heightmap_rel)}},
        }
        height_entity["Components"]["EditorGradientTransformComponent"] = {
            "$type": "EditorGradientTransformComponent",
            "Id": ids.component(),
        }
        height_entity["Components"]["EditorAxisAlignedBoxShapeComponent"] = \
            _aabb_component(ids, box_x, box_y, box_z)

    # ── Terrain root entity ──────────────────────────────────────────────────
    root_entity = _bare_entity(ids, root_entity_id, name, "ContainerEntity")
    root_entity["Components"]["EditorTerrainLayerSpawnerComponent"] = {
        "$type": "EditorTerrainLayerSpawnerComponent",
        "Id": ids.component(),
    }
    root_entity["Components"]["EditorAxisAlignedBoxShapeComponent"] = \
        _aabb_component(ids, box_x, box_y, box_z)
    root_entity["Components"]["EditorTerrainHeightGradientListComponent"] = {
        "$type": "EditorTerrainHeightGradientListComponent",
        "Id": ids.component(),
        "Configuration": {"GradientEntities": [height_entity_id]},
    }
    root_entity["Components"]["EditorTerrainSurfaceMaterialsListComponent"] = {
        "$type": "EditorTerrainSurfaceMaterialsListComponent",
        "Id": ids.component(),
        "Configuration": {
            "Mappings": [
                {
                    "Surface": f"terrain_layer_{layer.index}",
                    "MaterialAsset": {"assetHint": _terrain_assetHint(asset_hint_root, material_rels[layer.index])},
                }
                for layer in terrain.layers if layer.index in material_rels
            ],
            # Default material = layer 0 if present.
            "DefaultMaterial": (
                {"assetHint": _terrain_assetHint(asset_hint_root, material_rels[0])}
                if 0 in material_rels else {}
            ),
        },
    }
    root_entity["Components"]["EditorTerrainMacroMaterialComponent"] = {
        "$type": "EditorTerrainMacroMaterialComponent",
        "Id": ids.component(),
    }

    container = _container_entity(ids, name, [root_entity_id])

    prefab = {
        "ContainerEntity": container,
        "Entities": {
            root_entity_id:   root_entity,
            height_entity_id: height_entity,
        },
        "Instances": {},
    }

    out_prefab.parent.mkdir(parents=True, exist_ok=True)
    with open(out_prefab, "w", encoding="utf-8") as f:
        json.dump(prefab, f, indent=4)

    # ── Lossless manifest (always correct, even if the prefab needs fixup) ───
    manifest = _terrain_manifest(terrain, material_rels, heightmap_rel,
                                 splatmap_rels, box_x, box_y, box_z)
    with open(out_prefab.with_suffix(".terrain.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)
    return manifest


# ── Prefab building blocks (self-contained; no IntegratedAssetProcessor) ─────

class _IdGen:
    """Local id generator mirroring prefab_writer's scheme without the worker."""
    def __init__(self):
        self._n = 0

    def entity(self) -> str:
        self._n += 1
        return f"Entity_[{self._n}]"

    def component(self) -> int:
        return random.randint(1000000000000000, 9999999999999999)


def _editor_housekeeping(ids: "_IdGen") -> Dict:
    """The editor-only components every O3DE entity carries."""
    return {
        n: {"$type": n, "Id": ids.component()} for n in (
            "EditorDisabledCompositionComponent",
            "EditorEntityIconComponent",
            "EditorInspectorComponent",
            "EditorLockComponent",
            "EditorOnlyEntityComponent",
            "EditorPendingCompositionComponent",
            "EditorVisibilityComponent",
        )
    }


def _bare_entity(ids: "_IdGen", entity_id: str, name: str, parent_id: str) -> Dict:
    comps = {
        "TransformComponent": {
            "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
            "Id": ids.component(),
            "Parent Entity": parent_id,
        },
    }
    comps.update(_editor_housekeeping(ids))
    return {"Id": entity_id, "Name": name, "Components": comps}


def _container_entity(ids: "_IdGen", name: str, child_order: List[str]) -> Dict:
    comps = {
        "EditorEntitySortComponent": {
            "$type": "EditorEntitySortComponent",
            "Id": ids.component(),
            "Child Entity Order": child_order,
        },
        "EditorPrefabComponent": {
            "$type": "EditorPrefabComponent",
            "Id": ids.component(),
        },
        "TransformComponent": {
            "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
            "Id": ids.component(),
            "Parent Entity": "",
        },
    }
    comps.update(_editor_housekeeping(ids))
    return {"Id": "ContainerEntity", "Name": name, "Components": comps}


def _aabb_component(ids: "_IdGen", x: float, y: float, z: float) -> Dict:
    return {
        "$type": "EditorAxisAlignedBoxShapeComponent",
        "Id": ids.component(),
        "Configuration": {"Dimensions": [x, z, y]},   # O3DE Z-up: (X, Y, Z=height)
    }


def _terrain_manifest(terrain, material_rels, heightmap_rel, splatmap_rels,
                      box_x, box_y, box_z) -> dict:
    return {
        "name": terrain.name,
        "world_size": {"x": box_x, "y": box_z, "height": box_y},
        "heightmap": heightmap_rel,
        "layers": [
            {
                "index":    layer.index,
                "material": material_rels.get(layer.index),
                "splatmap": splatmap_rels.get(layer.index),
                "surface":  f"terrain_layer_{layer.index}",
                "tile_size": [layer.tile_size_x, layer.tile_size_y],
                "tile_offset": [layer.tile_offset_x, layer.tile_offset_y],
                "metallic":   layer.metallic,
                "smoothness": layer.smoothness,
            }
            for layer in terrain.layers
        ],
        "_note": (
            "Best-effort O3DE terrain prefab. Verify component schemas in the "
            "editor: TerrainLayerSpawner + AxisAlignedBox define the region; "
            "the Height Gradient child drives elevation from the heightmap "
            "image; SurfaceMaterialsList maps each layer's surface tag to its "
            "detail material; per-layer blend weighting uses the splatmaps via "
            "surface-mask gradients (set up manually). Tiling values above feed "
            "each detail material's UV scale in O3DE."
        ),
    }


# =============================================================================
# SHARED HELPERS
# =============================================================================

def _product(terrain_rel: Optional[str]) -> str:
    """Legacy as-is passthrough. Retained for the manifest writer (which
    keeps source-relative paths intact). The prefab writer now uses
    `_terrain_assetHint` so its emitted hints carry the project-relative
    root + the right product extension."""
    return terrain_rel or ""


def _terrain_assetHint(asset_hint_root: str, terrain_rel: Optional[str]) -> str:
    """Build an O3DE assetHint string from a Terrain-output-root-relative
    path (``Materials/foo.material`` / ``Heightmaps/foo.png`` / …).

    Two transforms apply:
      1. Prefix with ``<asset_hint_root>/terrain/`` lowercased so the
         result matches the product's cache-relative path. The lowercasing
         + project-root prefix is the same rule the Stage-1 worker uses
         for mesh / material hints.
      2. Map the source extension onto the product extension O3DE actually
         emits into the cache:
           ``.material`` → ``.azmaterial``
           ``.png``      → ``.png.streamingimage``
         Other extensions pass through; if a future product family lands
         here without an explicit mapping the resulting hint is a clean
         "not found" rather than a silent misbinding.
    """
    if not terrain_rel:
        return ""
    rel = terrain_rel.lower().replace("\\", "/")
    if rel.endswith(".material"):
        rel = rel[: -len(".material")] + ".azmaterial"
    elif rel.endswith(".png"):
        rel = rel + ".streamingimage"
    return f"{asset_hint_root}/terrain/{rel}"


def _safe(name: str) -> str:
    """Filesystem-safe token preserving case (matches converter convention)."""
    keep = "-_."
    return "".join(c if (c.isalnum() or c in keep) else "_" for c in str(name)).strip("_")


def _clamp01(v: float) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
