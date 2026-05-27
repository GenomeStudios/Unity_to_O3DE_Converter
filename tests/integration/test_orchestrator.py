"""Integration test for the F-8 pipeline orchestrator —
queue advancement, stage skipping, and cancel."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()


def _seed_two_stage_project():
    """Set scope + asset_processor + scene_converter selections so the
    orchestrator queue is non-empty."""
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("OrchTest")
    td = tempfile.mkdtemp(prefix="u2o_orch_")
    scope = Path(td) / "scope"; scope.mkdir()
    proj.set_scope_root(scope)
    ap = dict(proj.stage_settings("asset_processor"))
    ap["output_path"] = str(Path(td) / "out")
    ap["selected_prefabs"] = ["Foo.prefab"]
    proj.update_stage("asset_processor", ap)
    sc = dict(proj.stage_settings("scene_converter"))
    sc["selected_scenes"] = ["Foo.unity"]
    sc["output_path"]     = str(Path(td) / "scene_out")
    proj.update_stage("scene_converter", sc)
    return proj, pm, td


def _cleanup(td):
    import shutil
    shutil.rmtree(td, ignore_errors=True)


def test_orchestrator_walks_dependency_order():
    """Queue is asset_processor → scene_converter when both have
    selections. Terrain is omitted because it has no selection
    (implicit Skip)."""
    from main_app import PipelineOrchestrator
    proj, pm, td = _seed_two_stage_project()
    try:
        orch = PipelineOrchestrator()
        dispatched = []
        finished   = []

        def stub_dispatch(stage_key):
            dispatched.append(stage_key)
            pm.processing_changed.emit(stage_key, True)
            pm.processing_changed.emit(stage_key, False)

        orch.stage_finished.connect(lambda s: finished.append(s))
        run_ok = []
        orch.run_finished.connect(lambda ok, _s: run_ok.append(ok))
        orch.run_all(proj, stub_dispatch)
        _app.processEvents()

        assert dispatched == ["asset_processor", "scene_converter"]
        assert finished   == ["asset_processor", "scene_converter"]
        assert run_ok     == [True]
        # Terrain omitted because no terrain materials selected.
        assert "terrain_processor" not in dispatched
    finally:
        _cleanup(td)


def test_orchestrator_cancel_drops_queued_stages():
    """cancel() called mid-run drops everything still in the queue;
    current stage finishes."""
    from main_app import PipelineOrchestrator
    proj, pm, td = _seed_two_stage_project()
    try:
        # Add terrain so the queue has 3 stages.
        tp = dict(proj.stage_settings("terrain_processor"))
        tp["selected_materials"] = ["/abs/foo.mat"]
        tp["output_path"] = str(Path(td) / "terrain_out")
        proj.update_stage("terrain_processor", tp)

        orch = PipelineOrchestrator()
        dispatched = []

        def stub_then_cancel(stage_key):
            dispatched.append(stage_key)
            if stage_key == "asset_processor":
                orch.cancel()
            pm.processing_changed.emit(stage_key, True)
            pm.processing_changed.emit(stage_key, False)

        run_ok = []
        orch.run_finished.connect(lambda ok, _s: run_ok.append(ok))
        orch.run_all(proj, stub_then_cancel)
        _app.processEvents()

        assert dispatched == ["asset_processor"], \
            f"cancel should have dropped scene/terrain: {dispatched}"
        assert not orch.is_running()
    finally:
        _cleanup(td)


def test_orchestrator_refuses_duplicate_run_all():
    """A second run_all while one is in flight is a no-op."""
    from main_app import PipelineOrchestrator
    proj, pm, td = _seed_two_stage_project()
    try:
        orch = PipelineOrchestrator()
        dispatched = []
        # Don't fire processing_changed — leaves the run perpetually
        # "in flight" until the test ends.
        orch.run_all(proj, lambda s: dispatched.append(s))
        dispatched_count_after_first = len(dispatched)

        # Second run_all should be ignored.
        orch.run_all(proj, lambda s: dispatched.append(s))
        _app.processEvents()
        assert len(dispatched) == dispatched_count_after_first, \
            "second run_all should not dispatch"
    finally:
        _cleanup(td)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
