"""Unit tests for ``Project.from_json`` legacy migrations.

Covers:
  - Pre-F-9 schema (``defaults.target_materialtype`` + path-valued
    ``shader_mappings``) → F-9 (``defaults.profile`` + profile-name
    mappings).
  - Pre-Phase-D flat ``stages``/``outputs`` → namespaced
    ``stages_by_platform`` / ``outputs_by_platform``.
  - Legacy ``scope`` field (ProjectScope enum) → ``source_engine``
    (SourceEngine enum)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import Project, SourceEngine, DEFAULT_PROFILE_NAME


def test_f9_material_processor_migration():
    """`defaults.target_materialtype` drops; path-valued mappings
    coerce to the default profile name."""
    legacy = {
        "name": "F9-Legacy",
        "stages": {
            "material_processor": {
                "defaults": {"target_materialtype": "StandardPBR.materialtype"},
                "shader_mappings": {
                    "Standard": "StandardPBR.materialtype",
                    "Universal Render Pipeline/Lit": "StandardPBR.materialtype",
                    "CustomPack/Foo": "SomeRandom.materialtype",
                },
                "overrides": {"guid-x": {"materialtype": "/abs/Override.materialtype"}},
            },
        },
    }
    proj = Project.from_json(legacy, None)
    mp = proj.stages["material_processor"]
    assert "target_materialtype" not in mp["defaults"]
    assert mp["defaults"]["profile"] == DEFAULT_PROFILE_NAME
    for k, v in mp["shader_mappings"].items():
        assert v == DEFAULT_PROFILE_NAME, \
            f"shader_mappings[{k!r}] not coerced: {v!r}"
    # Per-material `materialtype` escape hatch preserved verbatim.
    assert mp["overrides"]["guid-x"]["materialtype"] == "/abs/Override.materialtype"


def test_phase_d_flat_to_namespaced_migration():
    """Pre-Phase-D files have flat `stages` + `outputs`. After
    `from_json`, both are lifted into the active platform's slot."""
    legacy = {
        "schema_version": 2,
        "name":  "Phase-D-Legacy",
        "source_engine": "unity",
        "stages": {
            "asset_processor": {"source_path": "/legacy/path",
                                  "selected_prefabs": ["A.prefab"],
                                  "output_path": "/legacy/out"},
        },
        "outputs": {
            "asset_processor": {"prefabs": {"guid-A": {"source_path": "/a"}}},
        },
        "pipeline_status": {},
    }
    proj = Project.from_json(legacy, None)
    assert proj.active_platform == "unity"
    assert "unity" in proj.stages_by_platform
    ap = proj.stage_settings("asset_processor")
    assert ap["source_path"] == "/legacy/path"
    assert ap["selected_prefabs"] == ["A.prefab"]
    assert proj.outputs["asset_processor"]["prefabs"]["guid-A"]["source_path"] == "/a"


def test_legacy_scope_enum_migrates_to_unity():
    """Pre-F-9 files carried `scope: whole_game` etc. (ProjectScope).
    Those values all map to SourceEngine.UNITY (since the user's
    projects were all Unity-sourced)."""
    legacy = {
        "name":  "EnumLegacy",
        "scope": "asset_set",
        "stages": {},
        "pipeline_status": {},
    }
    proj = Project.from_json(legacy, None)
    assert proj.source_engine == SourceEngine.UNITY
    # to_json writes the new key.
    body = proj.to_json()
    assert body["source_engine"] == "unity"


def test_namespaced_file_roundtrips_intact():
    """A file written by post-Phase-D `to_json` round-trips through
    `from_json` with both platform slots preserved."""
    namespaced = {
        "name": "Roundtrip",
        "source_engine": "unreal",
        "active_platform": "unreal",
        "stages_by_platform": {
            "unity":  {"asset_processor": {"selected_prefabs": ["U.prefab"]}},
            "unreal": {"asset_processor": {"selected_prefabs": ["UE.uasset"]}},
        },
        "outputs_by_platform": {
            "unity":  {"asset_processor": {}},
            "unreal": {"asset_processor": {}},
        },
        "pipeline_status": {},
    }
    proj = Project.from_json(namespaced, None)
    assert proj.active_platform == "unreal"
    assert proj.stages_by_platform["unity"]["asset_processor"]["selected_prefabs"] == ["U.prefab"]
    assert proj.stages_by_platform["unreal"]["asset_processor"]["selected_prefabs"] == ["UE.uasset"]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
