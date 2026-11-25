"""Unit tests for converter_cli.py and stage_runner.py (parity_harness I.2).

Covers:
  - ``--set``: value parsing, deep keys, refusals, and that neither
    ``describe`` nor ``run`` writes to the project file (proof T.7);
  - which prefabs a run takes: the marks, every prefab when nothing is
    marked, and the ``--only`` wildcard;
  - ``run`` end to end on a synthetic prefab: output, trace, the copy of the
    project with the run's bookkeeping, exit codes;
  - ``store_run``: a run's state index is merged onto the existing one.
"""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
import converter_cli as cli
from stage_runner import StageRun, store_run
from tests.unit.test_conversion_trace import _PREFAB_YAML, PREFAB_GUID


# =============================================================================
# FIXTURES
# =============================================================================

def _make_project(tmp: Path, marks=None) -> Path:
    """A Unity folder with two prefabs and a project file pointing at it."""
    unity = tmp / "unity"
    (unity / "Props").mkdir(parents=True)
    for name, guid in (("Crate", PREFAB_GUID), ("Props/Barrel", "ffff0000ffff0000ffff0000ffff0000")):
        (unity / f"{name}.prefab").write_text(
            _PREFAB_YAML.replace("m_Name: Crate", f"m_Name: {Path(name).name}"), encoding="utf-8")
        (unity / f"{name}.prefab.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")

    project_file = tmp / "test.u2oproj.json"
    project_file.write_text(json.dumps({
        "name": "CliTest", "source_engine": "unity", "scope_root": str(unity),
        "stages_by_platform": {"unity": {
            "asset_processor": {"selected_prefabs": marks or [], "output_path": str(tmp / "out")},
        }},
    }, indent=2), encoding="utf-8")
    return project_file


def _run_cli(*argv) -> tuple:
    """Run the CLI in-process; returns ``(exit code, printed text)``."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        code = cli.main(list(argv))
    return code, printed.getvalue()


# =============================================================================
# --set
# =============================================================================

def test_set_parses_json_values_and_text():
    with tempfile.TemporaryDirectory() as tmp:
        project = cli.load_project(_make_project(Path(tmp)))
        cli.apply_overrides(project, [
            "mesh_processor.defaults.auto_center=false",
            "mesh_processor.defaults.default_rotation=[90, 0, 0]",
            "asset_processor.output_path=D:/somewhere",
        ])
        defaults = project.stage_settings("mesh_processor")["defaults"]
        assert defaults["auto_center"] is False
        assert defaults["default_rotation"] == [90, 0, 0]
        assert project.stage_settings("asset_processor")["output_path"] == "D:/somewhere"


def test_set_makes_missing_deeper_keys():
    with tempfile.TemporaryDirectory() as tmp:
        project = cli.load_project(_make_project(Path(tmp)))
        cli.apply_overrides(project, ["mesh_processor.overrides.abc123.zero_position=false"])
        assert project.stage_settings("mesh_processor")["overrides"]["abc123"] == {"zero_position": False}


def test_set_refuses_an_unknown_stage_and_a_malformed_assignment():
    with tempfile.TemporaryDirectory() as tmp:
        project_file = _make_project(Path(tmp))
        for assignment in ("no_such_stage.key=1", "mesh_processor=1", "mesh_processor.defaults.auto_center"):
            code, printed = _run_cli("describe", str(project_file), "--set", assignment)
            assert code == cli.EXIT_REFUSED, (assignment, printed)
            assert "refused" in printed


def test_set_never_writes_to_the_project_file():
    with tempfile.TemporaryDirectory() as tmp:
        project_file = _make_project(Path(tmp))
        before = project_file.read_bytes()

        code, printed = _run_cli("describe", str(project_file),
                                 "--set", "mesh_processor.defaults.auto_center=false")
        assert code == cli.EXIT_OK
        assert '"auto_center": false' in printed, "describe must show the changed value"

        code, _ = _run_cli("run", str(project_file), "--stage", "asset_processor", "--quiet",
                           "--set", "mesh_processor.defaults.auto_center=false")
        assert code == cli.EXIT_OK
        assert project_file.read_bytes() == before


# =============================================================================
# WHICH PREFABS A RUN TAKES
# =============================================================================

def test_no_marks_means_every_prefab():
    with tempfile.TemporaryDirectory() as tmp:
        project = cli.load_project(_make_project(Path(tmp)))
        assert [path.name for path in cli.marked_prefabs(project)] == ["Crate.prefab", "Barrel.prefab"]


def test_marks_and_only_narrow_the_list():
    with tempfile.TemporaryDirectory() as tmp:
        project = cli.load_project(_make_project(Path(tmp), marks=["Props/Barrel.prefab", "Gone.prefab"]))
        assert [path.name for path in cli.marked_prefabs(project)] == ["Barrel.prefab"]

        everything = cli.load_project(_make_project(Path(tmp) / "second"))
        assert [path.name for path in cli.marked_prefabs(everything, only="cra*")] == ["Crate.prefab"]
        assert cli.marked_prefabs(everything, only="nothing*") == []


# =============================================================================
# run
# =============================================================================

def test_run_writes_output_trace_and_project_copy():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        project_file = _make_project(tmp)
        code, printed = _run_cli("run", str(project_file), "--stage", "asset_processor", "--quiet",
                                 "--seed", "3", "--trace", str(tmp / "trace"),
                                 "--project-out", str(tmp / "run" / "project.u2oproj.json"),
                                 "--log", str(tmp / "run" / "run.log"))
        assert code == cli.EXIT_OK, printed
        assert "Prefabs: 2/2" in printed
        assert "0 emitted value(s) not covered" in printed

        assert (tmp / "out" / "Prefabs" / "Crate.prefab").is_file()
        assert (tmp / "out" / "Prefabs" / "Barrel.prefab").is_file()
        assert (tmp / "run" / "run.log").stat().st_size > 0

        catalog = json.loads((tmp / "trace" / "trace.json").read_text(encoding="utf-8"))
        assert len(catalog["prefabs"]) == 2

        stored = cli.load_project(tmp / "run" / "project.u2oproj.json")
        assert stored.pipeline_status["asset_processor"]["prefabs_processed"] == 2
        assert stored.outputs["asset_processor"]["last_status"] == "ok"
        assert stored.outputs["asset_processor"]["last_input_hash"]


def test_same_seed_gives_the_same_prefab():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        project_file = _make_project(tmp)
        _run_cli("run", str(project_file), "--stage", "asset_processor", "--quiet", "--seed", "3")
        first = (tmp / "out" / "Prefabs" / "Crate.prefab").read_text(encoding="utf-8")
        _run_cli("run", str(project_file), "--stage", "asset_processor", "--quiet", "--seed", "3")
        assert (tmp / "out" / "Prefabs" / "Crate.prefab").read_text(encoding="utf-8") == first


def test_run_refuses_when_nothing_matches():
    with tempfile.TemporaryDirectory() as tmp:
        project_file = _make_project(Path(tmp))
        code, printed = _run_cli("run", str(project_file), "--stage", "asset_processor",
                                 "--quiet", "--only", "nothing*")
        assert code == cli.EXIT_REFUSED and "no prefab to process" in printed

        code, printed = _run_cli("run", str(project_file), "--stage", "scene_converter", "--quiet")
        assert code == cli.EXIT_REFUSED and "scene_converter" in printed


# =============================================================================
# store_run
# =============================================================================

def test_store_run_merges_the_state_index():
    with tempfile.TemporaryDirectory() as tmp:
        project = cli.load_project(_make_project(Path(tmp)))
        project.update_outputs("state_index", {"materials": {"old": {"input_hash": "1"}}, "meshes": {}})

        run = StageRun(
            stage_key="asset_processor", summary="s", errors=0,
            outputs={"last_run": "now", "last_status": "ok"},
            status={"prefabs_processed": 1},
            state_index={"materials": {"new": {"input_hash": "2"}}},
        )
        store_run(project, project, run, "hash123")

        assert project.outputs["state_index"]["materials"] == {
            "old": {"input_hash": "1"}, "new": {"input_hash": "2"}}
        assert project.outputs["asset_processor"]["last_input_hash"] == "hash123"
        assert project.pipeline_status["asset_processor"]["prefabs_processed"] == 1


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
