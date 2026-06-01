#!/usr/bin/env python3
"""
=============================================================================
UNITY TERRAIN PROCESSOR  (platforms.unity.terrain)
=============================================================================

Stage-3 worker: converts a Unity binary ``TerrainData`` ``.asset`` into O3DE
terrain artifacts. Orchestration only — parsing lives in
``platforms.unity.terrain_data`` and emission in ``targets.o3de.terrain_writer``.

Outputs are à la carte (any non-empty subset of ``materials``, ``heightmap``,
``splatmaps``, ``entity``); the worker only does the work for requested
outputs, so a materials-only run never decodes the heightmap or splatmaps.

Output layout (under ``<output_root>/Terrain/``)::

    Materials/   <TerrainName>_Layer<N>_<albedoStem>.material
    Textures/    copied albedo + normal PNGs (deduped by GUID)
    Heightmaps/  <TerrainName>_height.png + <TerrainName>_height.json
    Splatmaps/   <TerrainName>_Layer<N>.png
    Prefabs/     <TerrainName>.prefab
"""

import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from platforms.unity.asset_database import AssetDatabase
from platforms.unity import terrain_data as td
from targets.o3de import terrain_writer


# All recognised output kinds.
ALL_OUTPUTS = {"materials", "heightmap", "splatmaps", "entity"}


# =============================================================================
# TERRAIN PROCESSOR
# =============================================================================

class TerrainProcessor:
    """Converts a Unity TerrainData .asset into O3DE terrain artifacts."""

    # -------------------------------------------------------------------------
    # CONSTRUCTION
    # -------------------------------------------------------------------------

    def __init__(self, unity_assets_root: Path, output_root: Path,
                 log_callback: Optional[Callable[[str], None]] = None):
        from integrated_asset_processor import _derive_asset_hint_root
        self.unity_assets_root = Path(unity_assets_root)
        self.output_root       = Path(output_root)
        self.log               = log_callback or print

        self.asset_db = AssetDatabase(self.unity_assets_root)

        # Project-relative lowercased prefix every emitted assetHint must
        # carry. Same derivation as the Stage-1 worker — walks up from
        # ``output_root`` to ``project.json`` and returns the relative
        # path lowercased. Without this prefix the terrain entity prefab's
        # MaterialAsset / ImageAsset assetHints would resolve to
        # ``<project>/materials/X`` etc. — never the real
        # ``<project>/Assets/.../Terrain/Materials/X`` location.
        self.asset_hint_root = _derive_asset_hint_root(self.output_root)

        # Output layout
        self.terrain_root  = self.output_root / "Terrain"
        self.materials_dir = self.terrain_root / "Materials"
        self.textures_dir  = self.terrain_root / "Textures"
        self.heightmaps_dir = self.terrain_root / "Heightmaps"
        self.splatmaps_dir  = self.terrain_root / "Splatmaps"
        self.prefabs_dir    = self.terrain_root / "Prefabs"

        # Track processed assets so a texture referenced by N layers is copied
        # exactly once per run.
        self._processed_textures: Dict[str, str] = {}   # guid -> relative path

    # -------------------------------------------------------------------------
    # PUBLIC ENTRY
    # -------------------------------------------------------------------------

    def process_terrain(self, terrain_asset: Path,
                        outputs: Optional[Set[str]] = None) -> Dict:
        """
        Convert one TerrainData ``.asset``. ``outputs`` is any non-empty subset
        of ALL_OUTPUTS; defaults to all. Returns a summary dict.
        """
        outputs = set(outputs) if outputs else set(ALL_OUTPUTS)
        unknown = outputs - ALL_OUTPUTS
        if unknown:
            self.log(f"  ⚠ Ignoring unknown outputs: {sorted(unknown)}")
            outputs &= ALL_OUTPUTS

        result = {
            "terrain":            str(terrain_asset),
            "layers":             0,
            "materials_written":  0,
            "textures_written":   0,
            "heightmaps_written": 0,
            "splatmaps_written":  0,
            "prefab_written":     False,
            "errors":             [],
        }

        terrain_asset = Path(terrain_asset)
        self.log(f"\nProcessing terrain: {terrain_asset.name}")

        # The entity output needs materials + heightmap + splatmaps to wire its
        # components, so decode whatever any requested output requires.
        want_heightmap = "heightmap" in outputs or "entity" in outputs
        want_alphamaps = "splatmaps" in outputs or "entity" in outputs

        try:
            terrain = td.parse_terrain_data(
                terrain_asset,
                want_heightmap=want_heightmap,
                want_alphamaps=want_alphamaps,
            )
        except Exception as exc:
            msg = f"{terrain_asset.name}: parse failed: {exc}"
            self.log(f"  ✗ {msg}")
            result["errors"].append(msg)
            return result

        result["layers"] = len(terrain.layers)
        self.log(f"  Layers: {len(terrain.layers)}")

        # Layer→texture-relative-path map is needed by materials AND the entity.
        layer_textures = {}
        if outputs & {"materials", "entity"}:
            layer_textures = self._copy_layer_textures(terrain, result)

        # ── Detail materials ────────────────────────────────────────────────
        material_rels: Dict[int, str] = {}
        if "materials" in outputs or "entity" in outputs:
            material_rels = self._emit_detail_materials(
                terrain, layer_textures, result,
                count_in_result=("materials" in outputs),
            )

        # ── Heightmap ─────────────────────────────────────────────────────────
        heightmap_rel = None
        if "heightmap" in outputs or "entity" in outputs:
            heightmap_rel = self._emit_heightmap(
                terrain, result, count_in_result=("heightmap" in outputs))

        # ── Splatmaps ────────────────────────────────────────────────────────
        splatmap_rels: Dict[int, str] = {}
        if "splatmaps" in outputs or "entity" in outputs:
            splatmap_rels = self._emit_splatmaps(
                terrain, result, count_in_result=("splatmaps" in outputs))

        # ── Full terrain entity ───────────────────────────────────────────────
        if "entity" in outputs:
            self._emit_terrain_entity(
                terrain, material_rels, heightmap_rel, splatmap_rels, result)

        result["textures_written"] = len(self._processed_textures)
        return result

    # -------------------------------------------------------------------------
    # TEXTURE COPY
    # -------------------------------------------------------------------------

    def _copy_layer_textures(self, terrain, result) -> Dict[int, Dict[str, str]]:
        """Copy each layer's albedo + normal into Terrain/Textures/ (deduped).
        Returns {layer_index: {"albedo": rel, "normal": rel}} where rel is
        relative to the Terrain root (e.g. ``Textures/foo.png``)."""
        out: Dict[int, Dict[str, str]] = {}
        for layer in terrain.layers:
            entry = {}
            albedo = self._copy_texture(layer.albedo_guid)
            normal = self._copy_texture(layer.normal_guid)
            if albedo:
                entry["albedo"] = albedo
            if normal:
                entry["normal"] = normal
            out[layer.index] = entry
        return out

    def _copy_texture(self, guid: Optional[str]) -> Optional[str]:
        """Copy a texture by GUID into Terrain/Textures/. Returns the path
        relative to the Terrain root, or None."""
        if not guid:
            return None
        if guid in self._processed_textures:
            return self._processed_textures[guid]

        src = self.asset_db.resolve_guid(guid)
        if not src or src.suffix.lower() not in self.asset_db.texture_extensions:
            self.log(f"    ⚠ Texture GUID not resolved: {guid[:8]}…")
            return None

        self.textures_dir.mkdir(parents=True, exist_ok=True)
        dst = self.textures_dir / src.name
        try:
            if not dst.exists():
                shutil.copy2(src, dst)
            rel = f"Textures/{dst.name}"
            self._processed_textures[guid] = rel
            return rel
        except Exception as exc:
            self.log(f"    ⚠ Failed to copy texture {src.name}: {exc}")
            return None

    # -------------------------------------------------------------------------
    # DETAIL MATERIALS
    # -------------------------------------------------------------------------

    def _emit_detail_materials(self, terrain, layer_textures, result,
                              count_in_result: bool) -> Dict[int, str]:
        """Write one detail material per layer. Returns {layer_index: rel}
        where rel is the .material path relative to the Terrain root."""
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        material_rels: Dict[int, str] = {}

        for layer in terrain.layers:
            tex = layer_textures.get(layer.index, {})
            albedo_rel = _texture_ref_for_materials(tex.get("albedo"))
            normal_rel = _texture_ref_for_materials(tex.get("normal"))
            albedo_stem = Path(tex.get("albedo", "")).stem

            fname = terrain_writer.detail_material_filename(
                terrain.name, layer, albedo_stem)
            out_path = self.materials_dir / fname
            try:
                terrain_writer.write_detail_material(
                    layer, albedo_rel, normal_rel, out_path)
                material_rels[layer.index] = f"Materials/{fname}"
                if count_in_result:
                    result["materials_written"] += 1
                self.log(f"  ✓ Material: {fname}")
            except Exception as exc:
                msg = f"layer {layer.index} material: {exc}"
                self.log(f"    ⚠ {msg}")
                result["errors"].append(msg)

        return material_rels

    # -------------------------------------------------------------------------
    # HEIGHTMAP
    # -------------------------------------------------------------------------

    def _emit_heightmap(self, terrain, result, count_in_result: bool):
        """Write a 16-bit heightmap PNG + sidecar. Returns the PNG path
        relative to the Terrain root, or None."""
        hm = terrain.heightmap
        if hm is None or hm.width <= 0 or hm.height <= 0:
            self.log("    ⚠ No heightmap data to export")
            return None

        fname = f"{terrain_writer._safe(terrain.name)}_height.png"
        out_png = self.heightmaps_dir / fname
        try:
            sidecar = terrain_writer.write_heightmap_image(hm, out_png)
            if count_in_result:
                result["heightmaps_written"] += 1
            self.log(
                f"  ✓ Heightmap: {fname} ({hm.width}×{hm.height}, "
                f"world {sidecar['world_size_x']:.1f}×{sidecar['world_size_z']:.1f}, "
                f"height {sidecar['height_range']:.1f})"
            )
            return f"Heightmaps/{fname}"
        except Exception as exc:
            msg = f"heightmap: {exc}"
            self.log(f"    ⚠ {msg}")
            result["errors"].append(msg)
            return None

    # -------------------------------------------------------------------------
    # SPLATMAPS
    # -------------------------------------------------------------------------

    def _emit_splatmaps(self, terrain, result, count_in_result: bool) -> Dict[int, str]:
        """Write one grayscale weight PNG per layer. Returns {layer_index: rel}
        relative to the Terrain root."""
        if not terrain.alphamaps:
            self.log("    ⚠ No splatmaps to export")
            return {}
        try:
            written = terrain_writer.write_splatmap_images(terrain, self.splatmaps_dir)
        except Exception as exc:
            msg = f"splatmaps: {exc}"
            self.log(f"    ⚠ {msg}")
            result["errors"].append(msg)
            return {}

        rels: Dict[int, str] = {}
        for layer_index, fname in written.items():
            rels[layer_index] = f"Splatmaps/{fname}"
            self.log(f"  ✓ Splatmap: {fname}")
        if count_in_result:
            result["splatmaps_written"] += len(written)
        return rels

    # -------------------------------------------------------------------------
    # TERRAIN ENTITY
    # -------------------------------------------------------------------------

    def _emit_terrain_entity(self, terrain, material_rels, heightmap_rel,
                            splatmap_rels, result):
        """Write a best-effort terrain .prefab + a lossless .terrain.json
        manifest under Terrain/Prefabs/."""
        fname = f"{terrain_writer._safe(terrain.name)}.prefab"
        out_prefab = self.prefabs_dir / fname
        try:
            terrain_writer.write_terrain_prefab(
                terrain, material_rels, heightmap_rel, splatmap_rels, out_prefab,
                asset_hint_root=self.asset_hint_root)
            result["prefab_written"] = True
            self.log(f"  ✓ Terrain entity: {fname} (+ manifest)")
            self.log("    ⓘ Prefab component schemas are best-effort — verify "
                     "in O3DE; the .terrain.json manifest is the lossless record.")
        except Exception as exc:
            msg = f"terrain entity: {exc}"
            self.log(f"    ⚠ {msg}")
            result["errors"].append(msg)


# =============================================================================
# MODULE HELPERS
# =============================================================================

def _texture_ref_for_materials(terrain_rel: Optional[str]) -> Optional[str]:
    """Convert a Terrain-root-relative texture path (``Textures/foo.png``) into
    a path relative to the Materials/ folder (``../Textures/foo.png``)."""
    if not terrain_rel:
        return None
    if terrain_rel.startswith("Textures/"):
        return f"../{terrain_rel}"
    return terrain_rel


# =============================================================================
# BACK-COMPAT ALIAS
# =============================================================================

# The tab previously called TerrainMaterialProcessor.process_materials([...]).
# Keep a thin alias so any lingering import resolves; the new flow uses
# TerrainProcessor.process_terrain(asset, outputs).
TerrainMaterialProcessor = TerrainProcessor
