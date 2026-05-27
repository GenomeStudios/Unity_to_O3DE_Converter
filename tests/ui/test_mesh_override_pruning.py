"""UI test for MeshTab's override normalisation.

Both convergence paths drop a redundant override entry and clear its
★ marker:
  - override edited back to default value
  - default edited to match a pre-existing override
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

import main_app  # noqa: F401  (loads stylesheet + main_app side-effects)


# ---------------------------------------------------------------------------
# Pure-helper coverage — _values_equal + _prune_redundant_overrides
# ---------------------------------------------------------------------------

def test_values_equal_scalars_and_vec3():
    eq = main_app.MeshTab._values_equal
    assert eq(True, True)
    assert not eq(True, False)
    assert eq(0.1 + 0.2, 0.3)
    assert eq([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert not eq([1.0, 2.0, 3.0], [1.0, 2.0, 3.001])
    assert not eq(None, 0.0)
    assert not eq([1.0], [1.0, 1.0])   # length mismatch


def test_prune_drops_entry_equal_to_defaults():
    defaults = {
        "zero_position":    True,
        "default_position": [0.0, 0.0, 0.0],
        "default_rotation": [0.0, 0.0, 0.0],
    }
    overrides = {
        "guid-redundant": {
            "zero_position":    True,
            "default_rotation": [0.0, 0.0, 0.0],
        },
        "guid-real": {
            "default_rotation": [90.0, 0.0, 0.0],
        },
    }
    pruned = main_app.MeshTab._prune_redundant_overrides(overrides, defaults)
    assert "guid-redundant" not in pruned
    assert "guid-real" in pruned


def test_prune_keeps_partial_override_with_real_difference():
    defaults  = {"zero_position": True, "default_rotation": [0.0, 0.0, 0.0]}
    overrides = {"g": {"zero_position": False}}   # only one field, differs
    pruned = main_app.MeshTab._prune_redundant_overrides(overrides, defaults)
    assert pruned == overrides


def test_prune_drops_empty_dict_entries():
    pruned = main_app.MeshTab._prune_redundant_overrides({"g": {}}, {})
    assert pruned == {}


# ---------------------------------------------------------------------------
# Integration — _on_field_changed prunes after each edit
# ---------------------------------------------------------------------------

def _build_meshtab_with_one_mesh(default_rotation, mesh_override):
    """Project with one mesh and a starting mesh_processor stage.
    Returns (tab, project_manager singleton, guid)."""
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("OverridePruneTest")
    guid = "guid-mesh-A"
    proj.outputs["asset_processor"] = {
        "meshes": {guid: {"asset_hint": "MeshA",
                          "source_stem": "MeshA",
                          "fbx_dest_path": "Meshes/MeshA.fbx"}},
    }
    proj.update_stage("mesh_processor", {
        "defaults":  {"zero_position": True,
                      "default_position": [0.0, 0.0, 0.0],
                      "default_rotation": list(default_rotation)},
        "overrides": ({guid: mesh_override} if mesh_override else {}),
    })
    tab = main_app.MeshTab()
    tab.apply_project(proj)
    return tab, pm, guid


def test_override_edited_back_to_default_drops_entry():
    tab, pm, guid = _build_meshtab_with_one_mesh(
        default_rotation=[0.0, 0.0, 0.0],
        mesh_override={"default_rotation": [90.0, 0.0, 0.0]},
    )
    proj = pm.current()
    assert guid in (proj.stage_settings("mesh_processor").get("overrides") or {})

    # Simulate the user selecting that mesh and editing its rotation X
    # back to 0 — _on_field_changed iterates self._selected_mesh_guids,
    # so we patch the selection helper.
    tab._selected_mesh_guids = lambda: [guid]
    tab._on_field_changed("override", ("default_rotation", "x"), 0.0)

    proj = pm.current()
    overrides = proj.stage_settings("mesh_processor").get("overrides") or {}
    assert guid not in overrides, \
        "Override edited back to default should have been pruned"


def test_default_edited_to_match_override_drops_entry():
    tab, pm, guid = _build_meshtab_with_one_mesh(
        default_rotation=[0.0, 0.0, 0.0],
        mesh_override={"default_rotation": [90.0, 0.0, 0.0]},
    )
    proj = pm.current()
    assert guid in (proj.stage_settings("mesh_processor").get("overrides") or {})

    # User edits the default rotation X to 90 — now both default and
    # override read [90, 0, 0]; override becomes redundant.
    tab._on_field_changed("defaults", ("default_rotation", "x"), 90.0)

    proj = pm.current()
    overrides = proj.stage_settings("mesh_processor").get("overrides") or {}
    assert guid not in overrides, \
        "Default changed to match override should have pruned the override"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
