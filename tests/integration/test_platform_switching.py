"""Integration test for Phase D — non-destructive per-platform
namespaced project state. Switching engines preserves prior
platform's data; switching back restores it intact."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()


def test_new_project_namespaces_under_unity():
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("PhaseDInit")
    assert proj.active_platform == "unity"
    assert "unity" in proj.stages_by_platform
    assert proj.stages is proj.stages_by_platform["unity"]
    assert proj.outputs is proj.outputs_by_platform["unity"]


def test_switch_and_back_preserves_unity_data():
    from project_manager import project_manager, DEFAULT_PROFILE_NAME
    pm = project_manager()
    proj = pm.new_project("SwitchBackTest")
    # Mutate Unity slot with distinctive data.
    proj.update_stage("asset_processor", {
        "source_path": "/unity/src",
        "selected_prefabs": ["U.prefab"],
        "output_path": "/unity/out",
    })
    mp = dict(proj.stage_settings("material_processor"))
    mp["shader_mappings"] = dict(mp.get("shader_mappings", {}))
    mp["shader_mappings"]["CustomPack/UnityOnly"] = DEFAULT_PROFILE_NAME
    proj.update_stage("material_processor", mp)

    # Switch to Unreal — fresh defaults.
    proj.set_active_platform("unreal")
    unreal_ap = proj.stage_settings("asset_processor")
    assert unreal_ap.get("selected_prefabs") == [], \
        f"Unreal slot polluted with Unity data: {unreal_ap}"

    # Switch back to Unity → original data intact.
    proj.set_active_platform("unity")
    unity_ap = proj.stage_settings("asset_processor")
    assert unity_ap["selected_prefabs"] == ["U.prefab"]
    assert unity_ap["output_path"]      == "/unity/out"
    unity_mp = proj.stage_settings("material_processor")
    assert "CustomPack/UnityOnly" in unity_mp["shader_mappings"]


def test_set_source_engine_drives_switch():
    from project_manager import project_manager, SourceEngine
    pm = project_manager()
    proj = pm.new_project("EngineDriver")
    proj.set_source_engine(SourceEngine.GODOT)
    assert proj.active_platform == "godot"
    assert "godot" in proj.stages_by_platform
    proj.set_source_engine(SourceEngine.UNITY)
    assert proj.active_platform == "unity"


def test_multi_platform_save_load_roundtrip():
    """A project with selections in two platforms round-trips through
    disk save/load with both slots intact."""
    from project_manager import ProjectManager, SourceEngine
    td = Path(tempfile.mkdtemp(prefix="u2o_phaseD_rt_"))
    try:
        pm = ProjectManager(settings_path=td / "settings.json")
        proj = pm.new_project("RoundTripTwoSlots", SourceEngine.UNITY)
        proj.update_stage("asset_processor", {
            "source_path": "/unity/src", "selected_prefabs": ["U.prefab"],
            "output_path": "/unity/out",
        })
        proj.set_active_platform("unreal")
        proj.update_stage("asset_processor", {
            "source_path": "/unreal/src", "selected_prefabs": ["UE.uasset"],
            "output_path": "/unreal/out",
        })

        path = td / "RoundTripTwoSlots.u2oproj.json"
        pm.save_as(path)

        pm2 = ProjectManager(settings_path=td / "settings2.json")
        opened = pm2.open(path)
        assert opened.active_platform == "unreal"
        assert opened.stages_by_platform["unity"]["asset_processor"]["selected_prefabs"] == \
            ["U.prefab"]
        assert opened.stages_by_platform["unreal"]["asset_processor"]["selected_prefabs"] == \
            ["UE.uasset"]

        opened.set_active_platform("unity")
        assert opened.stage_settings("asset_processor")["selected_prefabs"] == \
            ["U.prefab"]
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
