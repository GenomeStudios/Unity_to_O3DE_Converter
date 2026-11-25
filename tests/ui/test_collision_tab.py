"""UI test for I.4 — CollisionTab (T-8).

Covers:
  - inventory renders from `outputs.asset_processor.collision_objects` with
    a ★ marker on overridden objects;
  - editing an override applies to the selection and prunes when it matches
    the default;
  - _CollisionChoiceField resolves selection / typed text to None|int|str;
  - "Reload physics layers" reads a real .setreg via the project's target
    O3DE root and populates the layer/group choices.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

import main_app
from project_manager import project_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _project_with_objects(overrides=None, defaults=None):
    pm = project_manager()
    proj = pm.new_project("CollisionTabTest")
    proj.outputs["asset_processor"] = {
        "last_run": "2026-06-01T00:00:00Z",
        "collision_objects": {
            "GUID:111": {"prefab_guid": "GUID", "prefab_name": "Crate",
                         "entity_file_id": "111", "entity_name": "Crate",
                         "collider_types": ["BoxCollider"], "collider_summary": "Box"},
            "GUID:222": {"prefab_guid": "GUID", "prefab_name": "Rock",
                         "entity_file_id": "222", "entity_name": "Rock",
                         "collider_types": ["MeshCollider"], "collider_summary": "Mesh (convex)"},
        },
    }
    proj.update_stage("collision_processor", {
        "defaults":  defaults or {"collision_layer": None, "collision_group_id": None},
        "overrides": overrides or {},
        "layer_names": {}, "group_names": {}, "setreg_override": "",
    })
    return proj, pm


# ---------------------------------------------------------------------------
# Inventory + markers
# ---------------------------------------------------------------------------

def test_inventory_renders_with_override_marker():
    proj, pm = _project_with_objects(
        overrides={"GUID:222": {"collision_layer": 3}})
    tab = main_app.CollisionTab()
    tab.apply_project(proj)
    assert tab._inv_list.count() == 2
    marked = {tab._inv_list.item(i).data(main_app.Qt.UserRole):
              tab._inv_list.item(i).text().startswith("★")
              for i in range(tab._inv_list.count())}
    assert marked["GUID:222"] is True       # has override
    assert marked["GUID:111"] is False      # no override


# ---------------------------------------------------------------------------
# Override apply + prune
# ---------------------------------------------------------------------------

def test_override_applies_to_selection():
    proj, pm = _project_with_objects(defaults={"collision_layer": 0,
                                               "collision_group_id": None})
    tab = main_app.CollisionTab()
    tab.apply_project(proj)
    tab._selected_keys = lambda: ["GUID:111"]
    tab._on_field_changed("override", "collision_layer", 5)
    overrides = pm.current().stage_settings("collision_processor")["overrides"]
    assert overrides["GUID:111"]["collision_layer"] == 5


def test_override_equal_to_default_is_pruned():
    proj, pm = _project_with_objects(
        defaults={"collision_layer": 2, "collision_group_id": None},
        overrides={"GUID:111": {"collision_layer": 9}})
    tab = main_app.CollisionTab()
    tab.apply_project(proj)
    tab._selected_keys = lambda: ["GUID:111"]
    # Edit the override back to the default value → entry becomes redundant.
    tab._on_field_changed("override", "collision_layer", 2)
    overrides = pm.current().stage_settings("collision_processor")["overrides"]
    assert "GUID:111" not in overrides


def test_clear_override_for_selection():
    proj, pm = _project_with_objects(
        overrides={"GUID:111": {"collision_layer": 7}})
    tab = main_app.CollisionTab()
    tab.apply_project(proj)
    tab._selected_keys = lambda: ["GUID:111"]
    tab._clear_override_for_selection()
    assert pm.current().stage_settings("collision_processor")["overrides"] == {}


# ---------------------------------------------------------------------------
# _CollisionChoiceField value resolution
# ---------------------------------------------------------------------------

def test_choice_field_layer_resolution():
    f = main_app._CollisionChoiceField("layer")
    f.set_choices([(0, "0 — Default"), (63, "63 — TouchBend")])
    f.set_common(63)
    assert f.current_value() == 63
    f.set_common(None)
    assert f.current_value() is None


def test_choice_field_group_resolution():
    g = main_app._CollisionChoiceField("group")
    g.set_choices([("{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}", "None")])
    g.set_common("{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}")
    assert g.current_value() == "{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}"
    g.set_common(None)
    assert g.current_value() is None


# ---------------------------------------------------------------------------
# Reload physics layers from the target O3DE project
# ---------------------------------------------------------------------------

def test_reload_physics_layers_populates_choices():
    with tempfile.TemporaryDirectory() as td:
        registry = Path(td) / "Registry"
        registry.mkdir()
        setreg = registry / "physxsystemconfiguration.setreg"
        layer_names = ["Default"] + [{} for _ in range(62)] + ["TouchBend"]
        setreg.write_text(json.dumps({
            "Amazon": {"Gems": {"PhysX5": {"PhysXSystemConfiguration": {
                "CollisionConfig": {
                    "Layers": {"LayerNames": layer_names},
                    "Groups": {"GroupPresets": [{"Name": "All", "ReadOnly": True}]},
                }}}}}
        }), encoding="utf-8")

        proj, pm = _project_with_objects()
        proj.set_o3de_project_root(Path(td))
        tab = main_app.CollisionTab()
        tab.apply_project(proj)
        tab._reload_physics_layers()

        cfg = pm.current().stage_settings("collision_processor")
        assert cfg["layer_names"] == {"0": "Default", "63": "TouchBend"}
        assert "All" in cfg["group_names"].values()
        # The default-layer combo now offers the named layers (engine default + 2).
        assert tab._default_fields["collision_layer"].count() == 3


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
