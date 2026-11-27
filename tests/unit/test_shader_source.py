"""Unit tests for what a Unity shader file says about its materials
(nature_pack I.4).

A material keeps the properties of every shader it ever had. The shader's
own file says which of them it reads, which faces it draws and whether it
cuts by alpha. The NatureManufacture pack ships 55 such files.
"""

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.shader_source import (
    CULL_BACK, CULL_OFF, ShaderFacts, alpha_threshold_property, draws_both_faces, read_shader_facts,
)


# =============================================================================
# FIXTURES
# =============================================================================

def _shader(properties: str, forward_pass: str, editor_pass: str = "Cull Off", bom: bool = True) -> str:
    """A compiled Shader Graph as a pack ships it: a lit pass, then a pass
    for the editor that draws both faces whatever the surface does."""
    return ("﻿" if bom else "") + f'''Shader "Pack/URP/Foliage/Leaves"
{{
    Properties
    {{
{properties}
        [HideInInspector][NoScaleOffset]unity_Lightmaps("unity_Lightmaps", 2DArray) = "" {{}}
    }}
    SubShader
    {{
        Tags {{ "RenderType"="Opaque" "Queue"="AlphaTest" }}
        Pass
        {{
            Name "Universal Forward"
            {forward_pass}
            ZWrite On
        }}
        Pass
        {{
            Name "SceneSelectionPass"
            {editor_pass}
        }}
    }}
}}
'''


FOLIAGE = '''        _AlphaCutoff("Alpha Cutoff", Float) = 0.5
        [NoScaleOffset]_BaseColorMap("Base Map", 2D) = "white" {}
        _HealthyColor("Healthy Color", Color) = (1, 1, 1, 0)
        [Normal][NoScaleOffset]_NormalMap("Normal Map", 2D) = "bump" {}
        _NormalScale("Normal Scale", Range(0, 8)) = 1
        [NoScaleOffset]_MaskMap("Mask Map", 2D) = "white" {}'''


def _facts(text: str, name: str = "Leaves.shader"):
    with tempfile.TemporaryDirectory() as folder:
        file = Path(folder) / name
        file.write_text(text, encoding="utf-8")
        return read_shader_facts(file)


# =============================================================================
# READING
# =============================================================================

def test_the_name_is_read_past_a_byte_order_mark():
    """The pack's files start with one; the name was not found behind it,
    and 142 materials went unnamed."""
    assert _facts(_shader(FOLIAGE, "Cull Off")).name == "Pack/URP/Foliage/Leaves"
    assert _facts(_shader(FOLIAGE, "Cull Off", bom=False)).name == "Pack/URP/Foliage/Leaves"


def test_the_declared_properties_keep_their_order_and_kind():
    facts = _facts(_shader(FOLIAGE, "Cull Off"))
    assert list(facts.properties)[:6] == ["_AlphaCutoff", "_BaseColorMap", "_HealthyColor", "_NormalMap",
                                          "_NormalScale", "_MaskMap"]
    assert facts.properties["_NormalScale"] == "Range(0, 8)" and facts.properties["_HealthyColor"] == "Color"
    assert facts.textures() == ["_BaseColorMap", "_NormalMap", "_MaskMap", "unity_Lightmaps"]
    assert facts.declares("_MaskMap") and not facts.declares("_MainTex")


def test_culling_is_the_lit_passes_not_the_editor_passes():
    assert _facts(_shader(FOLIAGE, "Cull Off")).cull == CULL_OFF
    bark = _facts(_shader(FOLIAGE, "Cull Back"))
    assert bark.cull == CULL_BACK and bark.cull_property == ""
    rock = _facts(_shader(FOLIAGE, "Cull [_Cull]"))
    assert rock.cull == "" and rock.cull_property == "_Cull"


def test_a_shader_that_always_cuts_says_so_in_either_of_two_ways():
    assert _facts(_shader(FOLIAGE, "Cull Off\n            #define _ALPHATEST_ON 1")).always_clips
    assert _facts(_shader(FOLIAGE, "Cull Off\n            clip( tex2DNode3.a - _Cutoff );")).always_clips
    keyword = "Cull [_Cull]\n            #pragma shader_feature_local_fragment _ _ALPHATEST_ON"
    assert not _facts(_shader(FOLIAGE, keyword)).always_clips


def test_what_is_no_shader_file_gives_no_facts():
    assert _facts('{"m_SGVersion": 3}', name="Leaves.shadergraph") is None
    assert _facts("// nothing declared here\n") is None
    assert _facts('Shader "Pack/Bare"\n{\n}\n') is None, "no property declared: nothing said about a material"
    assert read_shader_facts(Path("missing/Leaves.shader")) is None


# =============================================================================
# WHAT FOLLOWS FOR A MATERIAL
# =============================================================================

def test_both_faces_show_when_the_pass_culls_nothing_or_the_material_sets_its_property_off():
    assert draws_both_faces(ShaderFacts(cull=CULL_OFF), {})
    assert not draws_both_faces(ShaderFacts(cull=CULL_BACK), {"_Cull": 0}), "a leftover _Cull is not read"
    assert draws_both_faces(ShaderFacts(cull_property="_Cull"), {"_Cull": 0})
    assert not draws_both_faces(ShaderFacts(cull_property="_Cull"), {"_Cull": 2})
    assert not draws_both_faces(ShaderFacts(cull_property="_Cull"), {})


def test_without_facts_unitys_own_property_is_taken():
    assert draws_both_faces(None, {"_Cull": 0}) and not draws_both_faces(None, {"_Cull": 2})
    assert not draws_both_faces(None, {})
    assert alpha_threshold_property(None) == "_Cutoff"


def test_the_threshold_is_read_from_the_property_the_shader_declares():
    assert alpha_threshold_property(_facts(_shader(FOLIAGE, "Cull Off"))) == "_AlphaCutoff"
    no_threshold = '        [NoScaleOffset]_TrunkBaseColorMap("Trunk Base Map", 2D) = "white" {}'
    assert alpha_threshold_property(_facts(_shader(no_threshold, "Cull Back"))) == ""


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
