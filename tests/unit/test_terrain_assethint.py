"""Regression test for ``_terrain_assetHint``.

Guards the 2026-05-31 fix: terrain entity prefab assetHints (material
/ heightmap / splatmap) were emitted without a project-relative root,
so they resolved to ``<project>/Materials/X`` instead of
``<project>/Assets/Art/.../Terrain/Materials/X.azmaterial`` and the
terrain rendered with no surfaces in O3DE.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests

from targets.o3de.terrain_writer import _terrain_assetHint


HINT_ROOT = "assets/art/alien fantasy forest"


def test_material_extension_swap_and_lowercasing():
    """``.material`` source extension flips to ``.azmaterial`` product
    extension. Whole hint is lowercased to match the O3DE cache key."""
    result = _terrain_assetHint(HINT_ROOT, "Materials/Showcase_Layer0_Albedo.material")
    assert result == "assets/art/alien fantasy forest/terrain/materials/showcase_layer0_albedo.azmaterial"


def test_png_gets_streamingimage_product_extension():
    """PNG sources produce ``<name>.png.streamingimage`` products
    (source extension preserved + product extension appended, mirroring
    the ``.fbx.azmodel`` convention)."""
    result = _terrain_assetHint(HINT_ROOT, "Heightmaps/Showcase_height.png")
    assert result == "assets/art/alien fantasy forest/terrain/heightmaps/showcase_height.png.streamingimage"


def test_splatmap_uses_same_png_rule():
    result = _terrain_assetHint(HINT_ROOT, "Splatmaps/Showcase_Layer1.png")
    assert result == "assets/art/alien fantasy forest/terrain/splatmaps/showcase_layer1.png.streamingimage"


def test_empty_input_passes_through_empty():
    assert _terrain_assetHint(HINT_ROOT, "") == ""
    assert _terrain_assetHint(HINT_ROOT, None) == ""


def test_unknown_extension_keeps_source():
    """An unknown extension falls through unchanged so the user gets a
    clean "asset not found" with the actual hint (rather than a hint
    silently misbound to a wrong product family)."""
    result = _terrain_assetHint(HINT_ROOT, "Materials/foo.weird")
    assert result == "assets/art/alien fantasy forest/terrain/materials/foo.weird"


def test_backslashes_normalised_to_forward():
    result = _terrain_assetHint(HINT_ROOT, "Materials\\foo.material")
    assert result == "assets/art/alien fantasy forest/terrain/materials/foo.azmaterial"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
