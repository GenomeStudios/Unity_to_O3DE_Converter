#!/usr/bin/env python3
"""
=============================================================================
UNITY TERRAIN MATERIAL PROCESSOR  (platforms.unity.terrain)
=============================================================================

Stage-3 worker: converts a user-picked set of Unity ``.mat`` files into
O3DE terrain detail materials referencing the TerrainBaseMaterial
materialtype. Copies all textures referenced by those materials into a
sibling ``Textures/`` folder.

Imported by ``main_app.py``'s TerrainTab. Pure worker — no UI.

Output layout (under ``<output_root>``)::

    Terrain/
        Materials/   <name>.material
        Textures/    <copied texture files>

Uses ``platforms.unity.asset_database.AssetDatabase`` for GUID indexing and
Unity ``.mat`` parsing. ``AssetDatabase.parse_material`` already runs
property reconciliation (metallic/roughness factor vs bounds, opacity
mode, smoothness handling), so this worker consumes its output and
routes it into a TerrainBaseMaterial JSON envelope.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Callable

from platforms.unity.asset_database import AssetDatabase


# =============================================================================
# CONSTANTS
# =============================================================================

TERRAIN_MATERIALTYPE = (
    "@gemroot:Terrain@/Assets/Materials/Types/TerrainBaseMaterial.materialtype"
)


# =============================================================================
# TERRAIN MATERIAL PROCESSOR
# =============================================================================

class TerrainMaterialProcessor:
    """
    Slim sibling of IntegratedAssetProcessor focused exclusively on terrain
    detail material emission from a user-provided list of .mat files.
    """

    # -------------------------------------------------------------------------
    # CONSTRUCTION
    # -------------------------------------------------------------------------

    def __init__(self, unity_assets_root: Path, output_root: Path,
                 log_callback: Optional[Callable[[str], None]] = None):
        self.unity_assets_root = unity_assets_root
        self.output_root       = output_root
        self.log               = log_callback or print

        self.asset_db = AssetDatabase(unity_assets_root)

        # Output layout
        self.terrain_root      = output_root / "Terrain"
        self.materials_dir     = self.terrain_root / "Materials"
        self.textures_dir      = self.terrain_root / "Textures"
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.textures_dir.mkdir(parents=True, exist_ok=True)

        # Track processed assets so a texture referenced by N materials is
        # copied exactly once per run.
        self._processed_textures: Dict[str, str] = {}   # guid -> relative_path

    # -------------------------------------------------------------------------
    # PUBLIC ENTRY
    # -------------------------------------------------------------------------

    def process_materials(self, material_paths: List[Path]) -> Dict:
        """
        Convert each .mat in `material_paths` into an O3DE terrain detail
        material. Returns a summary dict suitable for displaying in the GUI.
        """
        materials_written = 0
        errors:   List[str] = []

        for mat_path in material_paths:
            try:
                if self._process_one(mat_path):
                    materials_written += 1
                else:
                    errors.append(f"Skipped (parse failure): {mat_path.name}")
            except Exception as exc:
                errors.append(f"{mat_path.name}: {exc}")
                self.log(f"  ✗ {mat_path.name}: {exc}")

        return {
            "materials_written": materials_written,
            "textures_written":  len(self._processed_textures),
            "errors":            errors,
        }

    # -------------------------------------------------------------------------
    # PER-MATERIAL EMISSION
    # -------------------------------------------------------------------------

    def _process_one(self, mat_path: Path) -> bool:
        """Convert a single .mat file. Returns True on success."""
        self.log(f"\nProcessing: {mat_path.name}")

        if not mat_path.exists():
            self.log(f"  ⚠ File not found")
            return False
        if mat_path.suffix.lower() != ".mat":
            self.log(f"  ⚠ Not a .mat file")
            return False

        material_data = self.asset_db.parse_material(mat_path)
        if not material_data:
            self.log(f"  ⚠ Failed to parse Unity material YAML")
            return False

        # Copy referenced textures
        texture_paths: Dict[str, str] = {}
        for o3de_prop, texture_guid in material_data.get("textures", {}).items():
            rel = self._copy_texture(texture_guid)
            if rel:
                texture_paths[o3de_prop] = rel

        # Build .material body
        o3de_material = {
            "materialType":        TERRAIN_MATERIALTYPE,
            "materialTypeVersion": 5,
            "propertyValues":      {},
        }

        # Texture properties: paths relative to the Materials/ folder use
        # `../Textures/<file>` because of the Materials/Textures sibling layout.
        for o3de_prop, rel in texture_paths.items():
            if rel.startswith("Textures/"):
                relative_texture_path = f"../{rel}"
            else:
                relative_texture_path = rel

            # The occlusion property uses a non-conforming key per StandardPBR;
            # mirror that here in case TerrainBaseMaterial follows the same
            # convention. If it does not, the override is harmless and surfaces
            # in the asset processor log so we can fix it.
            if o3de_prop == "occlusion.specular":
                property_name = "occlusion.specularTextureMap"
            else:
                property_name = f"{o3de_prop}.textureMap"

            o3de_material["propertyValues"][property_name] = relative_texture_path

        # Scalar / color / enum properties — pass through what _extract_material_data
        # already reconciled (metallic/roughness factor vs bounds, opacity mode).
        for o3de_prop, value in material_data.get("properties", {}).items():
            if isinstance(value, list):
                color = value[:3] if len(value) >= 3 else [1.0, 1.0, 1.0]
                alpha = value[3]  if len(value) >= 4 else 1.0
                o3de_material["propertyValues"][o3de_prop] = [
                    float(color[0]), float(color[1]), float(color[2]), float(alpha),
                ]
            elif isinstance(value, str):
                o3de_material["propertyValues"][o3de_prop] = value
            else:
                o3de_material["propertyValues"][o3de_prop] = float(value)

        out_path = self.materials_dir / f"{mat_path.stem}.material"
        with open(out_path, "w") as f:
            json.dump(o3de_material, f, indent=4)

        self.log(
            f"  ✓ Wrote {out_path.relative_to(self.output_root)} "
            f"({len(texture_paths)} texture(s))"
        )
        return True

    # -------------------------------------------------------------------------
    # TEXTURE COPY
    # -------------------------------------------------------------------------

    def _copy_texture(self, texture_guid: str) -> Optional[str]:
        """
        Copy the texture identified by `texture_guid` into Terrain/Textures/.
        Returns the path relative to the Terrain root (e.g. "Textures/foo.png"),
        or None if the texture cannot be resolved or copied.
        """
        if texture_guid in self._processed_textures:
            return self._processed_textures[texture_guid]

        src = self.asset_db.resolve_guid(texture_guid)
        if not src or src.suffix.lower() not in self.asset_db.texture_extensions:
            self.log(f"    ⚠ Texture GUID not resolved: {texture_guid[:8]}…")
            return None

        dst = self.textures_dir / src.name
        try:
            if not dst.exists():
                shutil.copy2(src, dst)
            relative = f"Textures/{dst.name}"
            self._processed_textures[texture_guid] = relative
            return relative
        except Exception as exc:
            self.log(f"    ⚠ Failed to copy texture {src.name}: {exc}")
            return None
