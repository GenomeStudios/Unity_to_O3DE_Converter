"""Unit tests for what a scene adds below an object of a placed prefab
(nature_pack I.6, found on the Alien Fantasy Forest and Alchemist House
packs).

A rock dropped under a placed rock is the scene's own object, parented to an
object inside the placement. Unity names that parent by a *stripped*
transform: a line saying which transform of which placement it is. The scene
converter knew no object for such a parent, so the rock was neither a root
nor anyone's child, and was never written.

Now it is the level's own entity, and names its parent inside the placement
by path: ``Instance_[n]/Entity_[m]``.
"""

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter, stripped_transforms

GUID = "b8b9543d5a3438845ae145555ee5afef"

# The source prefab: a root (object 100, transform 400) with one object
# below it (object 101, transform 401), as its entity map records them.
SIDECAR = {"root_entity": "Entity_[1]", "entity_aliases": {"100": "Entity_[1]", "101": "Entity_[2]"},
           "transform_owners": {"400": "100", "401": "101"}}

PLACEMENT = """--- !u!1001 &7000
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 0}
    m_Modifications:
    - target: {fileID: 400, guid: __GUID__, type: 3}
      propertyPath: m_LocalPosition.x
      value: 5
      objectReference: {fileID: 0}
    - target: {fileID: 100, guid: __GUID__, type: 3}
      propertyPath: m_Name
      value: Rock
      objectReference: {fileID: 0}
  m_SourcePrefab: {fileID: 100100000, guid: __GUID__, type: 3}
"""

STRIPPED = """--- !u!4 &7400 stripped
Transform:
  m_CorrespondingSourceObject: {fileID: __SOURCE__, guid: __GUID__, type: 3}
  m_PrefabInstance: {fileID: 7000}
  m_PrefabAsset: {fileID: 0}
"""

PEBBLE = """--- !u!1 &8000
GameObject:
  m_Component:
  - component: {fileID: 8400}
  m_Name: Pebble
--- !u!4 &8400
Transform:
  m_GameObject: {fileID: 8000}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 1, y: 2, z: 3}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children: []
  m_Father: {fileID: 7400}
"""

# A second placement, hung below the same object of the first.
SECOND_PLACEMENT = """--- !u!1001 &9000
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 7400}
    m_Modifications:
    - target: {fileID: 100, guid: __GUID__, type: 3}
      propertyPath: m_Name
      value: Moss
      objectReference: {fileID: 0}
  m_SourcePrefab: {fileID: 100100000, guid: __GUID__, type: 3}
"""

HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"


def _scene(*parts, source="401") -> str:
    return (HEADER + "".join(parts)).replace("__GUID__", GUID).replace("__SOURCE__", source)


def _parse(text: str) -> UnitySceneConverter:
    converter = UnitySceneConverter(PrefabDatabase(), log_callback=lambda *_: None)
    with tempfile.TemporaryDirectory() as folder:
        scene = Path(folder) / "Scene.unity"
        scene.write_text(text, encoding="utf-8")
        converter.parse_unity_scene(str(scene))
    return converter


def _level(converter: UnitySceneConverter) -> dict:
    """The level written for a parsed scene, every placement taken as a
    converted prefab with ``SIDECAR`` as its entity map."""
    with tempfile.TemporaryDirectory() as folder:
        prefab = Path(folder) / "Rock.prefab"
        for go in converter.game_objects.values():
            if go.is_prefab_instance:
                converter.prefab_references[go.file_id] = prefab
        converter._entity_maps_by_stem["Rock"] = SIDECAR
        level = Path(folder) / "Level.prefab"
        converter.create_o3de_level(str(level), Path(folder))
        return json.loads(level.read_text(encoding="utf-8"))


def _named(level: dict, name: str) -> dict:
    return next(entity for entity in level["Entities"].values() if entity["Name"] == name)


# =============================================================================
# THE STRIPPED TRANSFORM
# =============================================================================

def test_a_stripped_transform_names_its_placement_and_its_source():
    assert stripped_transforms(_scene(PLACEMENT, STRIPPED, PEBBLE)) == {"7400": ("7000", "401")}


def test_a_scene_from_before_unity_2018_3_spells_it_differently():
    """Alien Fantasy Forest's demo: ``m_PrefabParentObject`` and
    ``m_PrefabInternal``, the reference wrapped over two lines."""
    old = ("--- !u!4 &2060932985 stripped\nTransform:\n"
           "  m_PrefabParentObject: {fileID: 4462193800706686, guid: b8b9543d5a3438845ae145555ee5afef,\n"
           "    type: 2}\n  m_PrefabInternal: {fileID: 1580143146}\n")
    assert stripped_transforms(old) == {"2060932985": ("1580143146", "4462193800706686")}


def test_a_transform_that_is_not_stripped_is_none_of_them():
    assert stripped_transforms(_scene(PLACEMENT, PEBBLE)) == {}


# =============================================================================
# THE PARENT
# =============================================================================

def test_an_object_added_below_a_placement_becomes_its_child():
    converter = _parse(_scene(PLACEMENT, STRIPPED, PEBBLE))
    placement = next(go for go in converter.game_objects.values() if go.is_prefab_instance)
    pebble = next(go for go in converter.game_objects.values() if go.name == "Pebble")
    assert pebble.parent_id == placement.file_id and pebble.file_id in placement.children_ids
    assert pebble.component_data["parent_in_placement"] == "401"
    assert [go.name for go in converter.game_objects.values() if go.parent_id is None] == ["Rock"]


def test_an_object_below_a_placement_the_scene_does_not_hold_goes_to_the_top():
    converter = _parse(_scene(STRIPPED, PEBBLE))
    pebble = next(go for go in converter.game_objects.values() if go.name == "Pebble")
    assert pebble.parent_id is None
    assert any("does not hold" in line for line in converter.coverage.warnings)


# =============================================================================
# THE LEVEL
# =============================================================================

def test_the_object_is_written_under_the_entity_inside_the_placement():
    level = _level(_parse(_scene(PLACEMENT, STRIPPED, PEBBLE)))
    instance = next(iter(level["Instances"]))
    transform = _named(level, "Pebble")["Components"]["TransformComponent"]
    assert transform["Parent Entity"] == f"{instance}/Entity_[2]"
    assert transform["Transform Data"]["Translate"] == [1.0, 3.0, 2.0]        # Unity (x, y, z) -> O3DE (x, z, y)


def test_an_object_under_the_placements_root_names_the_root_entity():
    level = _level(_parse(_scene(PLACEMENT, STRIPPED, PEBBLE, source="400")))
    instance = next(iter(level["Instances"]))
    assert _named(level, "Pebble")["Components"]["TransformComponent"]["Parent Entity"] == f"{instance}/Entity_[1]"


def test_a_parent_without_an_entity_of_its_own_gives_the_root_and_a_warning():
    converter = _parse(_scene(PLACEMENT, STRIPPED, PEBBLE, source="499"))
    level = _level(converter)
    instance = next(iter(level["Instances"]))
    assert _named(level, "Pebble")["Components"]["TransformComponent"]["Parent Entity"] == f"{instance}/Entity_[1]"
    assert any("no entity of its own" in line for line in converter.coverage.warnings)


def test_a_placement_below_an_object_of_another_placement_names_it_by_path():
    level = _level(_parse(_scene(PLACEMENT, STRIPPED, SECOND_PLACEMENT)))
    assert len(level["Instances"]) == 2
    parents = {patch["value"] for instance in level["Instances"].values() for patch in instance["Patches"]
               if patch["path"].endswith("/Parent Entity")}
    first = next(alias for alias, instance in level["Instances"].items()
                 if any(patch["value"] == "../Entity_[1000000]" for patch in instance["Patches"]))
    assert parents == {"../Entity_[1000000]", f"../{first}/Entity_[2]"}


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
