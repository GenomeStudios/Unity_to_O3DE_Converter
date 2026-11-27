"""Unit tests for a material read by its shader's own file (nature_pack I.4).

Of the NatureManufacture pack's 179 converted materials 142 use the
distributor's shaders. Read by the names Unity's own shaders use, ten of them
got no base colour, none its packed mask map, and no leaf was cut out. The
shader's file says what the material alone does not:

  - which of the material's stored properties the shader reads; the rest is
    left over from shaders the material had before;
  - how a packed texture is packed, in its label;
  - whether the surface is cut by alpha, at which property's threshold, and
    whether both its faces show.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor, PIL_AVAILABLE
from platforms.unity.asset_database import AssetDatabase, live_properties
from platforms.unity.shader_source import CULL_BACK, CULL_OFF, ShaderFacts, packed_channels

BASE, NORMAL, MASK, OLD, COVER = ("b" * 32, "c" * 32, "d" * 32, "e" * 32, "f" * 32)


# =============================================================================
# FIXTURES
# =============================================================================

def _facts(**changes) -> ShaderFacts:
    """A pack's layered rock shader: a base layer and a cover over it."""
    declared = {
        "_BaseColorMap": ("2D", "Base Map"), "_BaseColor": ("Color", "Base Color"),
        "_BaseTilingOffset": ("Vector", "Base Tiling and Offset"),
        "_BaseNormalMap": ("2D", "Base Normal Map"), "_BaseNormalScale": ("Range(0, 8)", "Base Normal Scale"),
        "_BaseMaskMap": ("2D", "Base Mask Map MT(R) AO(G) H(B) SM(A)"),
        "_BaseMetallic": ("Range(0, 1)", "Base Metallic"),
        "_BaseAORemapMin": ("Range(0, 1)", "Base AO Remap Min"),
        "_BaseSmoothnessRemapMin": ("Range(0, 1)", "Base Smoothness Remap Min"),
        "_BaseSmoothnessRemapMax": ("Range(0, 1)", "Base Smoothness Remap Max"),
        "_AlphaCutoff": ("Range(0, 1)", "Alpha Cutoff"),
        "_CoverMaskMap": ("2D", "Cover Mask Map MT(R) AO(G) H(B) SM(A)"),
    }
    facts = ShaderFacts(name="Pack/URP/Lit/Top Cover",
                        properties={name: kind for name, (kind, _) in declared.items()},
                        labels={name: label for name, (_, label) in declared.items()},
                        cull=CULL_BACK)
    for key, value in changes.items():
        setattr(facts, key, value)
    return facts


def _material_text(floats=None, keywords=(), tiling=(1, 1, 0, 0)) -> str:
    """A material of that shader which was a URP Lit material before: it
    still stores `_MainTex`, `_Cutoff` and `_AlphaClip` from then."""
    numbers = {"_BaseNormalScale": 1.5, "_BaseMetallic": 1, "_BaseAORemapMin": 0.2,
               "_BaseSmoothnessRemapMin": 0.1, "_BaseSmoothnessRemapMax": 0.7, "_AlphaCutoff": 0,
               "_AlphaClip": 1, "_Cutoff": 0.5, "_Smoothness": 0.5, "_Cull": 0}
    numbers.update(floats or {})
    lines = ["%YAML 1.1", "%TAG !u! tag:unity3d.com,2011:", "--- !u!21 &2100000", "Material:", "  m_Name: Rock",
             "  m_ValidKeywords:" + (" []" if not keywords else "")]
    lines += [f"  - {keyword}" for keyword in keywords]
    lines += ["  m_SavedProperties:", "    m_TexEnvs:"]
    for name, guid in (("_BaseColorMap", BASE), ("_BaseMaskMap", MASK), ("_BaseNormalMap", NORMAL),
                       ("_CoverMaskMap", COVER), ("_MainTex", OLD)):
        lines += [f"    - {name}:", f"        m_Texture: {{fileID: 2800000, guid: {guid}, type: 3}}",
                  "        m_Scale: {x: 1, y: 1}", "        m_Offset: {x: 0, y: 0}"]
    lines += ["    m_Floats:"] + [f"    - {name}: {value}" for name, value in numbers.items()]
    lines += ["    m_Colors:", "    - _BaseColor: {r: 0.5, g: 0.6, b: 0.7, a: 1}", "    - _Color: {r: 1, g: 0, b: 0, a: 1}",
              f"    - _BaseTilingOffset: {{r: {tiling[0]}, g: {tiling[1]}, b: {tiling[2]}, a: {tiling[3]}}}"]
    return "\n".join(lines) + "\n"


def _read(facts, **material) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Rock.mat"
        path.write_text(_material_text(**material), encoding="utf-8")
        return AssetDatabase(Path(folder)).parse_material(path, shader_facts=facts)


# =============================================================================
# WHAT THE SHADER DOES NOT DECLARE IS LEFT OVER
# =============================================================================

def test_only_declared_properties_are_kept_in_the_shaders_order():
    saved = {"m_TexEnvs": [{"_MainTex": 1}, {"_CoverMaskMap": 2}, {"_BaseMaskMap": 3}],
             "m_Floats": [{"_Cutoff": 0.5}, {"_AlphaCutoff": 0}], "m_Colors": [{"_Color": {}}], "m_Ints": []}
    live = live_properties(saved, _facts())
    assert live["m_TexEnvs"] == [{"_BaseMaskMap": 3}, {"_CoverMaskMap": 2}]
    assert live["m_Floats"] == [{"_AlphaCutoff": 0}] and live["m_Colors"] == [] and live["m_Ints"] == []


def test_a_texture_and_a_colour_of_an_earlier_shader_are_not_read():
    read = _read(_facts())
    assert read["textures"]["baseColor"] == BASE, "not the old `_MainTex`"
    assert read["properties"]["baseColor.color"] == [0.5, 0.6, 0.7, 1], "not the old `_Color`"
    assert read["properties"]["normal.factor"] == 1.5


def test_without_the_shaders_file_the_material_is_read_as_before():
    read = _read(None)
    assert read["textures"]["baseColor"] == BASE and "roughness" not in read["textures"]
    assert read["properties"]["opacity.mode"] == "Cutout", "Unity's own `_AlphaClip` and `_Cutoff` count"


# =============================================================================
# A PACKED TEXTURE, BY ITS LABEL
# =============================================================================

def test_a_label_spells_the_channels():
    assert packed_channels("_BaseMaskMap", "Base Mask Map MT(R) AO(G) H(B) SM(A)") == {
        "metallic": "R", "occlusion": "G", "height": "B", "smoothness": "A"}
    assert packed_channels("_AmbientOcclusionG", "AO (G) Sm (A)") == {"occlusion": "G", "smoothness": "A"}
    assert packed_channels("_MetalicRAOGSmothnessA", "Metalic (R) AO (G) Smothness (A)")["smoothness"] == "A"
    assert packed_channels("_MaskMap", "Mask Map") == {"metallic": "R", "occlusion": "G", "smoothness": "A"}
    assert packed_channels("_BaseColorMap", "Base Map") == {} and packed_channels("_CoverMaskA", "Cover Mask (A)") == {}


def test_the_first_layers_mask_map_feeds_three_slots_each_from_its_channel():
    read = _read(_facts())
    assert [read["textures"][slot] for slot in ("metallic", "occlusion.specular", "roughness")] == [MASK] * 3
    assert read["texture_channels"] == {"metallic": ("R", False), "occlusion.specular": ("G", False),
                                        "roughness": ("A", True)}
    assert COVER not in read["textures"].values(), "the cover is the second layer"


def test_smoothness_and_occlusion_remaps_become_bounds_and_a_strength():
    """Smoothness in [0.1, 0.7] is roughness in [0.3, 0.9]; occlusion in
    [0.2, 1] is a strength of 0.8."""
    properties = _read(_facts())["properties"]
    assert round(properties["roughness.lowerBound"], 6) == 0.3 and round(properties["roughness.upperBound"], 6) == 0.9
    assert properties["occlusion.specularFactor"] == 0.8
    assert "roughness.factor" not in properties, "the old `_Smoothness` is not read"


def test_a_metallic_scale_of_zero_means_no_metal_whatever_the_texture_holds():
    read = _read(_facts(), floats={"_BaseMetallic": 0})
    assert "metallic" not in read["textures"] and "metallic" not in read["texture_channels"]
    assert read["properties"]["metallic.factor"] == 0.0
    assert read["textures"]["roughness"] == MASK, "the other values of the map still count"


def test_tiling_kept_in_one_vector_becomes_the_materials():
    properties = _read(_facts(), tiling=(4, 2, 0.5, 0))["properties"]
    assert properties["uv.center"] == [0.0, 0.0]
    assert (properties["uv.tileU"], properties["uv.tileV"], properties["uv.offsetU"]) == (4.0, 2.0, 0.5)


# =============================================================================
# CUT BY ALPHA, AND BOTH FACES
# =============================================================================

def test_a_leftover_alpha_clip_does_not_cut_a_rock():
    """The shader cuts by its keyword, at `_AlphaCutoff`. The material stores
    `_AlphaClip: 1` and `_Cutoff: 0.5` from an earlier shader: not read."""
    assert "opacity.mode" not in _read(_facts())["properties"]
    assert "opacity.mode" not in _read(_facts(), keywords=("_ALPHATEST_ON",))["properties"], "a threshold of zero"


def test_the_keyword_cuts_at_the_shaders_own_threshold():
    properties = _read(_facts(), keywords=("_ALPHATEST_ON",), floats={"_AlphaCutoff": 0.25})["properties"]
    assert properties["opacity.mode"] == "Cutout" and properties["opacity.factor"] == 0.75


def test_a_shader_that_always_cuts_needs_no_keyword():
    properties = _read(_facts(always_clips=True), floats={"_AlphaCutoff": 0.126})["properties"]
    assert properties["opacity.mode"] == "Cutout" and round(properties["opacity.factor"], 3) == 0.874


def test_a_shader_that_cuts_at_a_threshold_it_does_not_declare_is_left_opaque():
    """The pack's bark: its threshold is a number inside the shader."""
    facts = _facts(always_clips=True)
    del facts.properties["_AlphaCutoff"]
    assert "opacity.mode" not in _read(facts)["properties"]


def test_both_faces_show_by_the_shaders_lit_pass_not_by_a_leftover_cull():
    assert "general.doubleSided" not in _read(_facts(cull=CULL_BACK))["properties"], "`_Cull: 0` is left over"
    assert _read(_facts(cull=CULL_OFF))["properties"]["general.doubleSided"] is True
    assert _read(None)["properties"]["general.doubleSided"] is True, "one of Unity's own shaders reads `_Cull`"


# =============================================================================
# THROUGH THE WORKER
# =============================================================================

SHADER = '''Shader "Pack/URP/Lit/Rock"
{
    Properties
    {
        [NoScaleOffset]_BaseColorMap("Base Map", 2D) = "white" {}
        [NoScaleOffset]_BaseMaskMap("Base Mask Map MT(R) AO(G) SM(A)", 2D) = "white" {}
        _BaseMetallic("Base Metallic", Range(0, 1)) = 1
        _BaseSmoothnessRemapMax("Base Smoothness Remap Max", Range(0, 1)) = 1
        _AlphaCutoff("Alpha Cutoff", Range(0, 1)) = 0.5
    }
    SubShader { Pass { Name "Universal Forward" Cull Back } }
}
'''


def test_the_worker_reads_the_shader_file_and_writes_each_value_from_its_channel():
    if not PIL_AVAILABLE:
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as folder:
        unity = Path(folder) / "unity"
        unity.mkdir()
        files = {"Rock.shader": ("a" * 32, SHADER), "Rock.mat": ("9" * 32, _material_text().replace(
            "Material:\n", "Material:\n  m_Shader: {fileID: 4800000, guid: " + "a" * 32 + ", type: 3}\n"))}
        for name, (guid, text) in files.items():
            (unity / name).write_text(text, encoding="utf-8")
            (unity / f"{name}.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")
        for name, guid, pixel in (("Base.png", BASE, (200, 100, 50, 255)), ("Mask.png", MASK, (255, 128, 0, 64))):
            Image.new("RGBA", (2, 2), pixel).save(unity / name)
            (unity / f"{name}.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")

        random.seed(7)
        worker = IntegratedAssetProcessor(unity, Path(folder) / "out", log_callback=lambda line: None,
                                          convert_smoothness_to_roughness=True)
        assert worker._process_material("9" * 32)
        assert worker._material_metadata["9" * 32]["shader_name"] == "Pack/URP/Lit/Rock"
        values = json.loads((Path(folder) / "out" / "Materials" / "Rock.material").read_text(encoding="utf-8"))["propertyValues"]
        assert values["baseColor.textureMap"] == "../Textures/Base.png"
        assert values["metallic.textureMap"] == "../Textures/Mask.png", "metallic is in red already"
        assert values["roughness.textureMap"] == "../Textures/Mask_Roughness.png"
        assert values["occlusion.specularTextureMap"] == "../Textures/Mask_Occlusion.png"
        textures = Path(folder) / "out" / "Textures"
        with Image.open(textures / "Mask_Roughness.png") as roughness, Image.open(textures / "Mask_Occlusion.png") as occlusion:
            assert roughness.mode == "L" and roughness.getpixel((0, 0)) == 191        # 255 - smoothness 64
            assert occlusion.mode == "L" and occlusion.getpixel((0, 0)) == 128        # the green channel


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
