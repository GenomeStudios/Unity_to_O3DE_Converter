"""Unit tests for a placement saved against an earlier form of its prefab
(nature_pack I.6, found on the Alchemist House pack).

A drawer there is placed in a scene with a position that names, as the
placement's root, a transform the drawer's prefab no longer has: the prefab
was rebuilt after the scene was saved. Unity drops an override that names
nothing, and shows the drawer where the prefab's own root stands. The
converter applied the position, and put the drawer two and a half metres
away.
"""

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.prefab import lost_root
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter

GUID = "92caae8afe1371b45b3e7fa9442a75aa"
MODEL_GUID = "09315e77fd19efb4b922c358a7cee4fa"

# The prefab as it is now: its root is transform 400.
SIDECAR = {"root_entity": "Entity_[1]", "entity_aliases": {"100": "Entity_[1]"},
           "transform_owners": {"400": "100"}, "root_position": [1.0, 2.0, 3.0],
           "root_rotation": [0.0, 0.0, 0.0, 1.0]}

ROOT_VALUES = {"m_LocalPosition.x": 5, "m_LocalPosition.y": 6, "m_LocalPosition.z": 7,
               "m_LocalRotation.x": 0, "m_LocalRotation.y": 0, "m_LocalRotation.z": 0, "m_LocalRotation.w": 1}


def _overrides(target: str, guid: str = GUID):
    return [{"target": {"fileID": int(target), "guid": guid}, "propertyPath": path, "value": value}
            for path, value in ROOT_VALUES.items()]


# =============================================================================
# THE RULE
# =============================================================================

def test_a_root_the_prefab_has_is_not_lost():
    assert lost_root(_overrides("400"), SIDECAR, GUID) is False


def test_a_root_the_prefab_no_longer_has_is_lost():
    assert lost_root(_overrides("4003366411676352"), SIDECAR, GUID) is True


def test_a_root_taken_from_another_file_is_not_this_prefabs_to_judge():
    """A prefab whose root is a placed model: the placement names the
    model's transform, by the model's guid."""
    assert lost_root(_overrides("-8679921383154817045", MODEL_GUID), SIDECAR, GUID) is False


def test_without_the_prefabs_record_nothing_is_judged():
    assert lost_root(_overrides("4003366411676352"), None, GUID) is False
    assert lost_root(_overrides("4003366411676352"), {"root_entity": "Entity_[1]"}, GUID) is False
    assert lost_root([], SIDECAR, GUID) is False


# =============================================================================
# THE LEVEL
# =============================================================================

def _level(target: str):
    lines = "".join(f"""    - target: {{fileID: {target}, guid: {GUID}, type: 2}}
      propertyPath: {path}
      value: {value}
      objectReference: {{fileID: 0}}
""" for path, value in ROOT_VALUES.items())
    scene_text = f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &7000
Prefab:
  m_Modification:
    m_TransformParent: {{fileID: 0}}
    m_Modifications:
{lines}    m_RemovedComponents: []
  m_ParentPrefab: {{fileID: 100100000, guid: {GUID}, type: 2}}
  m_IsPrefabParent: 0
"""
    converter = UnitySceneConverter(PrefabDatabase(), log_callback=lambda *_: None)
    with tempfile.TemporaryDirectory() as folder:
        scene = Path(folder) / "Props.unity"
        scene.write_text(scene_text, encoding="utf-8")
        converter.parse_unity_scene(str(scene))
        for go in converter.game_objects.values():
            if go.is_prefab_instance:
                converter.prefab_references[go.file_id] = Path(folder) / "Drawer02.prefab"
        converter._entity_maps_by_stem["Drawer02"] = SIDECAR
        level = Path(folder) / "Level.prefab"
        converter.create_o3de_level(str(level), Path(folder))
        patches = next(iter(json.loads(level.read_text(encoding="utf-8"))["Instances"].values()))["Patches"]
    translate = [patch["value"] for patch in patches if "/Translate/" in patch["path"]]
    return translate, converter.coverage.warnings


def test_a_placement_stands_where_its_overrides_say():
    translate, warnings = _level("400")
    assert translate == [5.0, 7.0, 6.0] and not warnings                 # Unity (x, y, z) -> O3DE (x, z, y)


def test_a_placement_with_a_lost_root_stands_where_the_prefabs_root_stands():
    translate, warnings = _level("4003366411676352")
    assert translate == [1.0, 3.0, 2.0]
    assert any("earlier form of its prefab" in line for line in warnings)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
