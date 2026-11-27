"""Unit tests for objects Unity has switched off (second_pack I.6).

An inactive object does not show in Unity, and neither does anything below
it. The club level of the Tirgames pack switches 140 objects off by
instance override; converted without this they all stand in the level.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.types import GameObject, Transform
from targets.o3de.prefab_writer import active_state_patches, inactive_objects, mark_inactive


# =============================================================================
# WHICH OBJECTS DO NOT SHOW
# =============================================================================

def _objects():
    """Lamp > (Shade [off] > Bulb), Base."""
    lamp = GameObject(file_id="1", name="Lamp", transform=Transform(), children_ids=["2", "4"])
    shade = GameObject(file_id="2", name="Shade", transform=Transform(), parent_id="1", children_ids=["3"],
                       is_active=False)
    bulb = GameObject(file_id="3", name="Bulb", transform=Transform(), parent_id="2")
    base = GameObject(file_id="4", name="Base", transform=Transform(), parent_id="1")
    return {go.file_id: go for go in (lamp, shade, bulb, base)}


def test_an_object_below_a_switched_off_one_does_not_show_either():
    assert inactive_objects(_objects()) == {"2", "3"}


def test_marking_an_entity_makes_it_start_inactive_and_hidden():
    entity = {"Id": "Entity_[1]", "Components": {"EditorVisibilityComponent": {"$type": "EditorVisibilityComponent", "Id": 5}}}
    mark_inactive(entity)
    assert entity["IsRuntimeActive"] is False
    assert entity["Components"]["EditorVisibilityComponent"] == {
        "$type": "EditorVisibilityComponent", "Id": 5, "VisibilityFlag": False}


# =============================================================================
# IN A CONVERTED PREFAB
# =============================================================================

def _object_yaml(game_object_id, transform_id, name, father, children=(), active=1):
    child_lines = "".join(f"\n  - {{fileID: {child}}}" for child in children) or " []"
    return f"""--- !u!1 &{game_object_id}
GameObject:
  m_Component:
  - component: {{fileID: {transform_id}}}
  m_Name: {name}
  m_IsActive: {active}
--- !u!4 &{transform_id}
Transform:
  m_GameObject: {{fileID: {game_object_id}}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children:{child_lines}
  m_Father: {{fileID: {father}}}
"""


def _convert(tmp: Path):
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Lamp.prefab"
    prefab.write_text("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
                      + _object_yaml(1, 401, "Lamp", 0, children=(402, 404))
                      + _object_yaml(2, 402, "Shade", 401, children=(403,), active=0)
                      + _object_yaml(3, 403, "Bulb", 402)
                      + _object_yaml(4, 404, "Base", 401), encoding="utf-8")
    (unity_root / "Lamp.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122227777\n",
                                                 encoding="utf-8")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None)
    assert processor.process_prefab(prefab)
    emitted = json.loads((tmp / "out" / "Prefabs" / "Lamp.prefab").read_text(encoding="utf-8"))
    record = processor._project_prefab_records["aaaabbbbccccdddd0000111122227777"]
    return {entity["Name"]: entity for entity in emitted["Entities"].values()}, record


def test_a_switched_off_object_and_what_is_below_it_are_written_inactive():
    with tempfile.TemporaryDirectory() as tmp:
        entities, _ = _convert(Path(tmp))
        for name in ("Shade", "Bulb"):
            assert entities[name]["IsRuntimeActive"] is False, name
            assert entities[name]["Components"]["EditorVisibilityComponent"]["VisibilityFlag"] is False
        for name in ("Lamp", "Base"):
            assert "IsRuntimeActive" not in entities[name], name


def test_the_entity_map_says_who_is_below_whom_and_who_is_switched_off():
    with tempfile.TemporaryDirectory() as tmp:
        _, record = _convert(Path(tmp))
        assert record["inactive"] == ["2"]
        assert record["parents"] == {"2": "1", "3": "2", "4": "1"}


# =============================================================================
# SWITCHED OFF OR ON BY AN INSTANCE'S OVERRIDE
# =============================================================================

SIDECAR = {
    "root_entity":    "Entity_[1]",
    "entity_aliases": {"1": "Entity_[1]", "2": "Entity_[2]", "3": "Entity_[3]", "4": "Entity_[4]"},
    "parents":        {"2": "1", "3": "2", "4": "1"},
    "inactive":       ["2"],
    "extra_entities": {"4": ["Entity_[9]"]},
}


def _states(patches) -> dict:
    return {patch["path"].split("/IsRuntimeActive")[0]: patch["value"]
            for patch in patches if patch["path"].endswith("/IsRuntimeActive")}


def test_switching_the_root_off_switches_the_whole_instance_off():
    patches = active_state_patches("1", False, SIDECAR)
    assert _states(patches) == {
        "/ContainerEntity": False, "/Entities/Entity_[1]": False, "/Entities/Entity_[2]": False,
        "/Entities/Entity_[3]": False, "/Entities/Entity_[4]": False, "/Entities/Entity_[9]": False}
    # Each entity is hidden in the Editor as well.
    hidden = [patch for patch in patches if patch["path"].endswith("/EditorVisibilityComponent/VisibilityFlag")]
    assert len(hidden) == 6 and all(patch["value"] is False for patch in hidden)


def test_switching_one_object_off_takes_what_is_below_it_and_nothing_else():
    assert _states(active_state_patches("4", False, SIDECAR)) == {
        "/Entities/Entity_[4]": False, "/Entities/Entity_[9]": False}


def test_switching_an_object_on_brings_what_is_below_it():
    """The shade is off in the prefab; an instance switches it on."""
    assert _states(active_state_patches("2", True, SIDECAR)) == {
        "/Entities/Entity_[2]": True, "/Entities/Entity_[3]": True}


def test_switching_the_instance_on_leaves_off_what_the_prefab_has_off():
    states = _states(active_state_patches("", True, SIDECAR))
    assert states["/ContainerEntity"] is True and states["/Entities/Entity_[4]"] is True
    assert states["/Entities/Entity_[2]"] is False and states["/Entities/Entity_[3]"] is False


def test_an_object_the_entity_map_does_not_hold_gets_no_patch():
    assert active_state_patches("77", False, SIDECAR) == []


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
