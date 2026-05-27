"""Unit tests for ``preflight.py`` — per-stage check functions, the
PreflightReport gate (red/yellow/Acknowledge), and ack-snapshot
drift. F-8 verification."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

# Qt app is needed because project_manager is a QObject.
_app = get_qt_app()


def test_empty_project_blocks_run_all():
    from preflight import run_preflight
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("EmptyPreflight")
    report = run_preflight(proj)
    assert report.has_red, "empty project should have at least one red"
    assert not report.can_run, "can_run should be False with reds"


def test_environment_red_drops_after_scope_root_set():
    from preflight import run_preflight
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("EnvFix")
    with tempfile.TemporaryDirectory() as td:
        proj.set_scope_root(Path(td))
        ap = dict(proj.stage_settings("asset_processor"))
        ap["output_path"] = str(Path(td) / "out")
        ap["selected_prefabs"] = ["Foo.prefab"]
        proj.update_stage("asset_processor", ap)
        report = run_preflight(proj)
        assert not report.has_red, \
            f"unexpected reds: {[it.title for it in report.reds]}"


def test_unmapped_shader_yellow_blocks_run_all():
    from preflight import run_preflight
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("UnmappedYellow")
    # Seed material metadata so the material check has detected shaders.
    proj.outputs["asset_processor"] = {
        "material_metadata": {
            "guid-a": {"shader_name": "CustomPack/Novel",
                        "asset_hint": "a", "source_stem": "A"},
        },
    }
    report = run_preflight(proj)
    yellow = [it for it in report.by_category("material_processor")
              if "without explicit mapping" in it.title]
    assert yellow, "expected an unmapped-shader yellow"
    item = yellow[0]
    assert item.ack_key == "material.unmapped"
    assert item.ack_snapshot, "yellow without snapshot can't be acknowledged"
    assert not report.can_run, "unacked yellow with ack_key should block"


def test_acknowledge_unlocks_can_run():
    from preflight import run_preflight
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("AckFlow")
    # Same setup as above + scope/output so only the material yellow blocks.
    with tempfile.TemporaryDirectory() as td:
        proj.set_scope_root(Path(td))
        ap = dict(proj.stage_settings("asset_processor"))
        ap["output_path"] = str(Path(td) / "out")
        ap["selected_prefabs"] = ["Foo.prefab"]
        proj.update_stage("asset_processor", ap)
        proj.outputs["asset_processor"] = {
            "material_metadata": {
                "guid-a": {"shader_name": "CustomPack/Novel",
                            "asset_hint": "a", "source_stem": "A"},
            },
        }
        report = run_preflight(proj)
        item = next(it for it in report.by_category("material_processor")
                    if it.ack_key == "material.unmapped")
        proj.set_preflight_ack(item.ack_key, item.ack_snapshot)
        report2 = run_preflight(proj)
        assert report2.can_run, \
            f"after Acknowledge, can_run should be True; "
        f"needs_ack: {[it.title for it in report2.needs_ack]}"


def test_snapshot_drift_rearms_ack():
    """Adding a new unmapped shader changes the snapshot hash so the
    prior Acknowledge no longer satisfies the gate."""
    from preflight import run_preflight
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("DriftRearm")
    proj.outputs["asset_processor"] = {
        "material_metadata": {
            "guid-a": {"shader_name": "CustomPack/A", "asset_hint": "a", "source_stem": "A"},
        },
    }
    r1 = run_preflight(proj)
    it1 = next(i for i in r1.by_category("material_processor")
               if i.ack_key == "material.unmapped")
    proj.set_preflight_ack(it1.ack_key, it1.ack_snapshot)

    # Add another unmapped shader → snapshot drifts.
    proj.outputs["asset_processor"]["material_metadata"]["guid-b"] = {
        "shader_name": "CustomPack/B", "asset_hint": "b", "source_stem": "B",
    }
    r2 = run_preflight(proj)
    it2 = next(i for i in r2.by_category("material_processor")
               if i.ack_key == "material.unmapped")
    assert it2.ack_snapshot != it1.ack_snapshot, \
        "snapshot hash should change when the unmapped set changes"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
