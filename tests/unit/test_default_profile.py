"""Unit tests for the F-9 default shader profile.

Verifies that ``project_manager.DEFAULT_SHADER_PROFILE`` captures the
legacy hard-coded Unity TEXTURE_MAP / PROPERTY_MAP / IGNORE_UNMAPPED
behaviour byte-for-byte. F-9.I.1b verification."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import (
    DEFAULT_PROFILE_NAME,
    DEFAULT_SHADER_PROFILE,
    _default_stages,
)


def test_default_profile_has_required_fields():
    p = DEFAULT_SHADER_PROFILE
    for key in ("description", "target_materialtype",
                "texture_map", "property_map",
                "ignore_unmapped", "special_rules"):
        assert key in p, f"DEFAULT_SHADER_PROFILE missing '{key}'"


def test_texture_map_baseColor_routes():
    """Standard / URP / HDRP / aliases all map to baseColor slot."""
    tm = DEFAULT_SHADER_PROFILE["texture_map"]
    for name in ("_MainTex", "_BaseMap", "_BaseColorMap", "_Albedo",
                 "_AlbedoMap", "_Diffuse", "_DiffuseMap"):
        assert tm[name]["slot"] == "baseColor", \
            f"{name!r} should map to baseColor, got {tm[name]}"


def test_texture_map_normal_routes():
    tm = DEFAULT_SHADER_PROFILE["texture_map"]
    for name in ("_BumpMap", "_NormalMap", "_NormalTex"):
        assert tm[name]["slot"] == "normal"


def test_texture_map_metallic_routes():
    tm = DEFAULT_SHADER_PROFILE["texture_map"]
    for name in ("_MetallicGlossMap", "_MetallicMap", "_MetallicTex"):
        assert tm[name]["slot"] == "metallic"


def test_texture_map_occlusion_routes():
    tm = DEFAULT_SHADER_PROFILE["texture_map"]
    for name in ("_OcclusionMap", "_AOMap", "_AmbientOcclusion",
                 "_AmbientOcclusionMap", "_AO"):
        assert tm[name]["slot"] == "occlusion.specular"


def test_texture_map_mk4_pack_recognised():
    """MK4 / Alien Fantasy Forest property names that the user's
    testbed depends on."""
    tm = DEFAULT_SHADER_PROFILE["texture_map"]
    assert tm["_RockAlbedo"]["slot"]   == "baseColor"
    assert tm["_RockNormal"]["slot"]   == "normal"
    assert tm["_RockSpecular"]["slot"] == "specular"


def test_property_map_canonical_entries():
    pm = DEFAULT_SHADER_PROFILE["property_map"]
    assert pm["_Color"]["target"]             == "baseColor.color"
    assert pm["_BaseColor"]["target"]         == "baseColor.color"
    assert pm["_BumpScale"]["target"]         == "normal.factor"
    assert pm["_OcclusionStrength"]["target"] == "occlusion.specularFactor"
    assert pm["_EmissionColor"]["target"]     == "emissive.color"


def test_ignore_unmapped_carries_mk4_layers():
    ig = set(DEFAULT_SHADER_PROFILE["ignore_unmapped"])
    for name in ("_Detail", "_AODetail",
                 "_CoverAlbedo", "_CoverNormal", "_CoverSpecular"):
        assert name in ig, f"{name!r} should be in ignore_unmapped"


def test_smoothness_to_roughness_default_on():
    sr = DEFAULT_SHADER_PROFILE["special_rules"]
    assert sr["metallic_gloss_smoothness_to_roughness"] is True


def test_default_stages_carries_default_profile():
    """The default profile must be seeded into every new project's
    material_processor stage so brand-new projects render correctly."""
    mp = _default_stages()["material_processor"]
    assert DEFAULT_PROFILE_NAME in mp["shader_profiles"]
    assert mp["defaults"]["profile"] == DEFAULT_PROFILE_NAME
    # Mappings pre-seed with profile name (not legacy materialtype path).
    for shader, value in mp["shader_mappings"].items():
        assert value == DEFAULT_PROFILE_NAME, \
            f"shader_mappings[{shader!r}] = {value!r}; expected profile name"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
