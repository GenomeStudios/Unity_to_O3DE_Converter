"""Unit tests for material opacity-mode detection — cutout-vs-blended
precedence. Regression for the Office MetalShelf case where a material
sets BOTH _AlphaClip=1/_Mode=1 (cutout) AND _Surface=1 (transparent),
and reading _Surface first made it Blended → fully invisible in O3DE.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.asset_database import AssetDatabase


def _opacity(floats: dict):
    db = AssetDatabase(Path(tempfile.gettempdir()))
    material_data = {"m_SavedProperties": {
        "m_Floats": [{k: v} for k, v in floats.items()],
        "m_Colors": [],
        "m_TexEnvs": [],
    }}
    props = db._extract_material_data(material_data).get("properties", {})
    return props.get("opacity.mode")


def test_metalshelf_alphaclip_and_surface_resolves_cutout():
    """The real bug: _Surface=1 (transparent) + _AlphaClip=1 + _Mode=1
    (cutout) + _Cutoff must resolve to Cutout, not Blended."""
    assert _opacity({"_Surface": 1, "_AlphaClip": 1, "_Mode": 1, "_Cutoff": 0.5}) \
        == "Cutout"


def test_true_glass_resolves_blended():
    """Genuine transparent (no alpha clip) stays Blended."""
    assert _opacity({"_Surface": 1, "_AlphaClip": 0, "_Mode": 3}) == "Blended"


def test_standard_cutout_mode_resolves_cutout():
    assert _opacity({"_Mode": 1, "_Cutoff": 0.5}) == "Cutout"


def test_standard_fade_resolves_blended():
    assert _opacity({"_Mode": 2}) == "Blended"


def test_opaque_has_no_opacity_mode():
    assert _opacity({"_Surface": 0, "_AlphaClip": 0, "_Mode": 0}) is None


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
