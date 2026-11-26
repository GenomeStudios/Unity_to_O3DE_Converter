"""Unit tests for the parity harness's test beds (second_pack I.1, proof T.1).

Several beds can share one O3DE project - one asset pack each. Each keeps
its runs (truth dump, trace, report) in a folder of its own, or two beds
would write over each other.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "parity"))

from tests.harness import run_module_tests

# parity/parity.py is a script beside the package folder of the same name:
# load it by its path.
_spec = importlib.util.spec_from_file_location("parity_cli", REPO / "parity" / "parity.py")
parity_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity_cli)


# =============================================================================
# FIXTURE: a config and its conversion project, on a made-up O3DE project
# =============================================================================

def _bed(root: Path, name: str, work: str = ""):
    o3de_project = root / "o3de"
    o3de_project.mkdir(exist_ok=True)
    (root / f"{name}.u2oproj.json").write_text(json.dumps({
        "schema_version": 2, "name": name, "source_engine": "unity", "active_platform": "unity",
        "scope_root": str(root), "o3de_project_root": str(o3de_project),
        "stages_by_platform": {"unity": {"asset_processor": {
            "selected_prefabs": [], "output_path": str(o3de_project / "Assets" / name)}}},
    }), encoding="utf-8")
    config = {"name": name, "project": f"{name}.u2oproj.json", "level": f"Bench_Parity_{name}", "seed": 1,
              "tolerance": {"position_mm": 1.0, "rotation_deg": 0.1, "geometry_mm": 1.0}}
    if work:
        config["work"] = work
    config_file = root / f"{name}.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return parity_cli.Bed(config_file), o3de_project


# =============================================================================
# TESTS
# =============================================================================

def test_a_bed_that_names_no_run_folder_uses_the_first_beds():
    with tempfile.TemporaryDirectory() as folder:
        bed, o3de_project = _bed(Path(folder), "office")
        assert bed.work == o3de_project / "user" / "Parity"
        assert bed.report_dir == o3de_project / "user" / "Parity" / "report"


def test_two_beds_on_one_project_keep_their_runs_apart():
    with tempfile.TemporaryDirectory() as folder:
        office, o3de_project = _bed(Path(folder), "office")
        second, _ = _bed(Path(folder), "tirgames", work="Parity_Tirgames")
        assert second.work == o3de_project / "user" / "Parity_Tirgames"
        for folder_of in ("truth_base", "convert_dir", "cook_dir", "probe_dir", "report_dir"):
            assert getattr(office, folder_of) != getattr(second, folder_of), folder_of
        assert office.output != second.output and office.level != second.level


def test_the_shipped_beds_do_not_share_a_run_folder_or_an_output():
    configs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((REPO / "parity" / "configs").glob("*.json"))
               if not path.name.endswith(".u2oproj.json")]
    assert len(configs) >= 2
    works = [config.get("work", "Parity") for config in configs]
    levels = [config["level"] for config in configs]
    assert len(set(works)) == len(works), works
    assert len(set(levels)) == len(levels), levels


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
