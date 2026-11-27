"""Unit tests for the order of an object's components (nature_pack I.6,
found on the Alchemist House pack).

A stove there carries five box colliders on one object. Its file stores
them in one order, the object's ``m_Component`` list names them in another,
and Unity goes by the list. The converter went by the file: the collider it
put on the object's own entity was not Unity's first, and every one of the
five was compared against the wrong box.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.prefab import component_ranks, in_unity_order


# =============================================================================
# THE LIST
# =============================================================================

def test_a_components_rank_is_its_place_in_the_objects_list():
    go = {"m_Component": [{"component": {"fileID": 400}}, {"component": {"fileID": 6502}},
                          {"component": {"fileID": 6501}}]}
    assert component_ranks(go) == {"400": 0, "6502": 1, "6501": 2}


def test_the_list_of_an_old_file_names_class_ids():
    """Before Unity 5.5 an entry was ``<class id>: {fileID}``."""
    assert component_ranks({"m_Component": [{4: {"fileID": 400}}, {65: {"fileID": 6501}}]}) == {"400": 0, "6501": 1}
    assert component_ranks({}) == {} and component_ranks({"m_Component": None}) == {}


def test_components_are_taken_in_the_lists_order_not_the_files():
    in_file = {"6501": {"type": "BoxCollider"}, "6502": {"type": "BoxCollider"}, "9000": {"type": "Light"}}
    ordered = in_unity_order(in_file, {"400": 0, "6502": 1, "6501": 2})
    assert list(ordered) == ["6502", "6501", "9000"], "listed ones by their place, an unlisted one after them"
    assert list(in_unity_order(in_file, {})) == ["6501", "6502", "9000"], "no list: the file's order"


# =============================================================================
# IN A CONVERTED PREFAB
# =============================================================================

# Two boxes on one object. The file stores the low one first; the object's
# list names the high one first.
PREFAB = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 400}
  - component: {fileID: 6502}
  - component: {fileID: 6501}
  m_Name: Stove
--- !u!4 &400
Transform:
  m_GameObject: {fileID: 100}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children: []
  m_Father: {fileID: 0}
--- !u!65 &6501
BoxCollider:
  m_GameObject: {fileID: 100}
  m_IsTrigger: 0
  m_Size: {x: 1, y: 1, z: 1}
  m_Center: {x: 0, y: 1, z: 0}
--- !u!65 &6502
BoxCollider:
  m_GameObject: {fileID: 100}
  m_IsTrigger: 0
  m_Size: {x: 2, y: 2, z: 2}
  m_Center: {x: 0, y: 5, z: 0}
"""


def test_the_objects_own_entity_gets_the_collider_unity_lists_first():
    with tempfile.TemporaryDirectory() as tmp:
        unity_root = Path(tmp) / "unity"
        unity_root.mkdir()
        prefab = unity_root / "Stove.prefab"
        prefab.write_text(PREFAB, encoding="utf-8")
        (unity_root / "Stove.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122228888\n",
                                                      encoding="utf-8")
        random.seed(7)
        processor = IntegratedAssetProcessor(unity_root, Path(tmp) / "out", log_callback=lambda line: None)
        assert processor.process_prefab(prefab)
        emitted = json.loads((Path(tmp) / "out" / "Prefabs" / "Stove.prefab").read_text(encoding="utf-8"))
        boxes = {entity["Name"]: entity["Components"]["EditorBoxShapeComponent"]["BoxShape"]["Configuration"]
                 for entity in emitted["Entities"].values() if "EditorBoxShapeComponent" in entity["Components"]}
        assert boxes["Stove"]["Dimensions"] == [2.0, 2.0, 2.0] and boxes["Stove"]["TranslationOffset"] == [0.0, 0.0, 5.0]
        assert boxes["Stove_Collider_1"]["Dimensions"] == [1.0, 1.0, 1.0]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
