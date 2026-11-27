"""Unit tests for the Unity TerrainData parser (platforms.unity.terrain_data).

Proves T-1/T-2/T-3 of the terrain expansion plan against the real sample
terrain (``New Terrain2.asset`` from the Alien Fantasy Forest pack):

  T-1  the asset sniffs as TerrainData and the folder scan finds it
  T-2  layers parse with albedo/normal GUIDs that resolve via AssetDatabase
       to the real Ground_Fantasy_* PNGs
  T-3  the heightmap grid and embedded splatmaps decode

The sample has since been opened by Unity 6, which upgraded it: its layers
are TerrainLayer assets of their own now, in ``Assets/_TerrainAutoUpgrade``
(nature_pack I.7). The same proofs hold for that form; the layer file itself
is read in ``test_a_terrain_layer_file_gives_its_textures_and_tiling``.

The sample lives outside the repo. Set ``U2O_TERRAIN_SAMPLE`` to override the
path. If UnityPy or the sample is unavailable, the tests print SKIP and pass so
the suite stays green on machines without the testbed."""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity import terrain_data as td
from platforms.unity.asset_database import AssetDatabase


# ── Test fixture location ────────────────────────────────────────────────────
_DEFAULT_SAMPLE = Path(
    r"D:\OffLocalDev\Contracting\artificer\Assets\Alien Fantasy Forest"
    r"\Terrain\New Terrain2.asset"
)
SAMPLE = Path(os.environ.get("U2O_TERRAIN_SAMPLE", str(_DEFAULT_SAMPLE)))
ASSETS_ROOT = Path(
    os.environ.get("U2O_ASSETS_ROOT",
                   r"D:\OffLocalDev\Contracting\artificer\Assets")
)


def _skip(reason: str) -> bool:
    """Return True (and print) when prerequisites are missing."""
    print(f"    SKIP — {reason}")
    return True


def _prereqs_ok() -> bool:
    if not td.unitypy_available():
        return not _skip("UnityPy not installed")
    if not SAMPLE.exists():
        return not _skip(f"sample terrain not found at {SAMPLE}")
    return True


# ── T-1: detection ───────────────────────────────────────────────────────────

def test_sniff_identifies_terrain_data():
    if not _prereqs_ok():
        return
    assert td.is_terrain_data(SAMPLE), "sample .asset not recognised as TerrainData"


def test_scan_finds_sample_terrain():
    if not _prereqs_ok():
        return
    if not ASSETS_ROOT.is_dir():
        _skip(f"assets root not found at {ASSETS_ROOT}")
        return
    found = td.scan_for_terrains(SAMPLE.parent)  # scan just the Terrain folder
    assert SAMPLE.resolve() in found, f"scan did not find {SAMPLE.name}: {found}"


# ── T-2: layers + GUID resolution ────────────────────────────────────────────

def test_layers_parse_with_resolvable_textures():
    if not _prereqs_ok():
        return
    terrain = td.parse_terrain_data(SAMPLE, want_heightmap=False,
                                    want_alphamaps=False)
    assert len(terrain.layers) == 6, \
        f"expected 6 splat layers, got {len(terrain.layers)}"

    if not ASSETS_ROOT.is_dir():
        _skip(f"assets root not found at {ASSETS_ROOT}; GUID resolution unchecked")
        return
    db = AssetDatabase(ASSETS_ROOT)
    for layer in terrain.layers:
        albedo = db.resolve_guid(layer.albedo_guid) if layer.albedo_guid else None
        normal = db.resolve_guid(layer.normal_guid) if layer.normal_guid else None
        assert albedo is not None, f"layer {layer.index} albedo GUID unresolved"
        assert normal is not None, f"layer {layer.index} normal GUID unresolved"
        assert albedo.suffix.lower() in db.texture_extensions
        assert normal.suffix.lower() in db.texture_extensions


def test_layer_tiling_populated():
    if not _prereqs_ok():
        return
    terrain = td.parse_terrain_data(SAMPLE, want_heightmap=False,
                                    want_alphamaps=False)
    # Every layer in the sample has a positive tile size (5..9).
    for layer in terrain.layers:
        assert layer.tile_size_x > 0 and layer.tile_size_y > 0, \
            f"layer {layer.index} has non-positive tiling"


def test_a_terrain_layer_file_gives_its_textures_and_tiling():
    """A ``.terrainlayer`` file as Unity writes it (text form)."""
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        layer_file = Path(folder) / "Moss.terrainlayer"
        layer_file.write_text(
            "%YAML 1.1\n--- !u!1953259897 &8574412962073106934\nTerrainLayer:\n"
            "  m_DiffuseTexture: {fileID: 2800000, guid: 3a5e0e19344fad04394c7143d31abca0, type: 3}\n"
            "  m_NormalMapTexture: {fileID: 2800000, guid: 0a6dd76ba7641f646b51f77e3e78f040, type: 3}\n"
            "  m_MaskMapTexture: {fileID: 0}\n  m_TileSize: {x: 7, y: 5}\n  m_TileOffset: {x: 0.5, y: 0}\n"
            "  m_Metallic: 0.25\n  m_Smoothness: 0.5\n", encoding="utf-8")
        layer = td.read_terrain_layer(3, layer_file)
    assert (layer.index, layer.albedo_guid, layer.normal_guid) == (
        3, "3a5e0e19344fad04394c7143d31abca0", "0a6dd76ba7641f646b51f77e3e78f040")
    assert (layer.tile_size_x, layer.tile_size_y, layer.tile_offset_x, layer.tile_offset_y) == (7.0, 5.0, 0.5, 0.0)
    assert (layer.metallic, layer.smoothness) == (0.25, 0.5)


def test_a_missing_terrain_layer_file_gives_a_layer_without_textures():
    layer = td.read_terrain_layer(0, None)
    assert layer.albedo_guid is None and layer.normal_guid is None and layer.tile_size_x == 1.0


# ── T-3: heightmap + alphamaps ───────────────────────────────────────────────

def test_heightmap_decodes():
    if not _prereqs_ok():
        return
    terrain = td.parse_terrain_data(SAMPLE, want_heightmap=True,
                                    want_alphamaps=False)
    hm = terrain.heightmap
    assert hm is not None, "heightmap not parsed"
    assert hm.width > 0 and hm.height > 0, "heightmap has zero dimension"
    assert len(hm.heights) == hm.width * hm.height, \
        f"heights len {len(hm.heights)} != {hm.width}x{hm.height}"
    assert hm.scale_y > 0, "heightmap world height (scale_y) not positive"


def test_alphamaps_decode():
    if not _prereqs_ok():
        return
    terrain = td.parse_terrain_data(SAMPLE, want_heightmap=False,
                                    want_alphamaps=True)
    assert len(terrain.alphamaps) >= 1, "no splatmaps decoded"
    first = terrain.alphamaps[0].image
    assert first is not None and first.mode == "RGBA", \
        f"splatmap should be RGBA PIL image, got {first}"
    # 6 layers need ceil(6/4)=2 RGBA splatmaps; layer 5 maps to tex 1 chan 1.
    amap, channel = terrain.alphamap_for_layer(5)
    assert amap is not None and channel == 1, \
        f"layer 5 should map to splatmap[1] channel 1, got {amap}, {channel}"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
