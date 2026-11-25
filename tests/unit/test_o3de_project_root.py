"""Unit tests for the target O3DE project root base field (I.0).

Covers:
  - `o3de_project_root` round-trips through `to_json` → `from_json`.
  - `physx_setreg_path()` resolves to
    `<root>/Registry/physxsystemconfiguration.setreg`, and is None when the
    root is unset.
  - `new_project(...)` and `set_o3de_project_root(...)` populate the field.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import Project, SourceEngine


def test_roundtrip_preserves_o3de_project_root():
    """A project with a target O3DE root survives to_json → from_json."""
    proj = Project.from_json({
        "name": "RootRoundtrip",
        "source_engine": "unity",
        "o3de_project_root": "D:/Games/MyO3DEProject",
        "stages": {},
        "pipeline_status": {},
    }, None)
    assert proj.o3de_project_root == Path("D:/Games/MyO3DEProject")

    body = proj.to_json()
    # to_json stores the OS-native string form (Path normalizes separators).
    assert body["o3de_project_root"] == str(Path("D:/Games/MyO3DEProject"))

    reopened = Project.from_json(body, None)
    assert reopened.o3de_project_root == Path("D:/Games/MyO3DEProject")


def test_blank_root_is_none_and_serializes_empty():
    """Missing / blank root → None field, empty string on disk."""
    proj = Project.from_json({"name": "NoRoot", "stages": {}, "pipeline_status": {}}, None)
    assert proj.o3de_project_root is None
    assert proj.to_json()["o3de_project_root"] == ""
    assert proj.physx_setreg_path() is None


def test_physx_setreg_path_resolution():
    """`physx_setreg_path()` points at the project's Registry setreg."""
    proj = Project.from_json({
        "name": "SetregPath",
        "o3de_project_root": "C:/o3de/Proj",
        "stages": {},
        "pipeline_status": {},
    }, None)
    setreg = proj.physx_setreg_path()
    assert setreg == Path("C:/o3de/Proj") / "Registry" / "physxsystemconfiguration.setreg"


def test_setter_marks_dirty_and_clears():
    proj = Project.from_json({"name": "Setter", "stages": {}, "pipeline_status": {}}, None)
    proj._mark_clean()
    proj.set_o3de_project_root(Path("E:/SomeProj"))
    assert proj.o3de_project_root == Path("E:/SomeProj")
    assert proj.is_dirty()
    # Clearing back to None.
    proj.set_o3de_project_root(None)
    assert proj.o3de_project_root is None


def test_onboarding_fields_populate_project():
    """The onboarding dialog's collected values (type + source + destination)
    land on the project, keyed by the same names new_project() forwards."""
    proj = Project.from_json({
        "name": "Onboarded",
        "source_engine": "unity",
        "scope_root": "U:/UnityAssets",
        "o3de_project_root": "O:/O3DEProj",
        "stages": {},
        "pipeline_status": {},
    }, None)
    assert proj.source_engine == SourceEngine.UNITY
    assert proj.scope_root == Path("U:/UnityAssets")
    assert proj.o3de_project_root == Path("O:/O3DEProj")


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
