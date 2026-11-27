"""Unit tests for colliders on mirrored and on stretched objects
(nature_pack I.4, found on the bridges of the NatureManufacture pack).

  - PhysX takes no box with a negative side, so a box on a mirrored object
    (a scale of -1 along an axis) left its entity without a collider. Such a
    box gets an entity of its own, without the mirror; its centre goes to
    the other side instead.
  - The engine passes an entity's scale by axis to nothing below it. A
    second collider of an object sits on an entity of its own below the
    object's: it carries the object's scale by axis itself.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.components.box_collider import own_entity_placement


# =============================================================================
# A ROUND COLLIDER ON A MIRRORED OBJECT
# =============================================================================

def test_a_mirrored_objects_collider_lies_on_the_other_side():
    sphere = {"type": "SphereCollider", "center": (1.0, 0.5, 0.25), "radius": 0.5, "global_index": 0}
    transform, placed = own_entity_placement(sphere, (-2.0, 2.0, 2.0), True)
    assert transform == {"Translate": [-2.0, 0.5, 1.0]}                # Unity (x, y, z) -> O3DE (x, z, y)
    assert placed["radius"] == 1.0, "a size has no sign"


# =============================================================================
# IN A CONVERTED PREFAB
# =============================================================================

def _prefab(scale, boxes) -> str:
    """A 'Stand' with one child 'Board' of the given scale, carrying the
    given box colliders as (centre, size) pairs."""
    components = "".join(f"\n  - component: {{fileID: {6500 + index}}}" for index in range(len(boxes)))
    colliders = "".join(f"""--- !u!65 &{6500 + index}
BoxCollider:
  m_GameObject: {{fileID: 101}}
  m_IsTrigger: 0
  m_Size: {{x: {size[0]}, y: {size[1]}, z: {size[2]}}}
  m_Center: {{x: {centre[0]}, y: {centre[1]}, z: {centre[2]}}}
""" for index, (centre, size) in enumerate(boxes))
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  m_Name: Stand
--- !u!4 &400
Transform:
  m_GameObject: {{fileID: 100}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children:
  - {{fileID: 401}}
  m_Father: {{fileID: 0}}
--- !u!1 &101
GameObject:
  m_Component:
  - component: {{fileID: 401}}{components}
  m_Name: Board
--- !u!4 &401
Transform:
  m_GameObject: {{fileID: 101}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: {scale[0]}, y: {scale[1]}, z: {scale[2]}}}
  m_Children: []
  m_Father: {{fileID: 400}}
{colliders}"""


def _convert(tmp: Path, scale, boxes) -> dict:
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Stand.prefab"
    prefab.write_text(_prefab(scale, boxes), encoding="utf-8")
    (unity_root / "Stand.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122227777\n",
                                                  encoding="utf-8")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None)
    assert processor.process_prefab(prefab)
    emitted = json.loads((tmp / "out" / "Prefabs" / "Stand.prefab").read_text(encoding="utf-8"))
    return {entity["Name"]: entity["Components"] for entity in emitted["Entities"].values()}


def _box(components: dict) -> dict:
    return components["EditorBoxShapeComponent"]["BoxShape"]["Configuration"]


def test_a_box_on_an_unmirrored_object_stays_on_it():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (2, 1, 1), [((0.5, 0, 0), (1, 2, 3))])
        assert _box(entities["Board"])["Dimensions"] == [1.0, 3.0, 2.0]
        assert not any(name.startswith("Board_Collider") for name in entities)


def test_a_box_on_a_mirrored_object_gets_an_entity_of_its_own_without_the_mirror():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (-1, 1, 1), [((0.5, 0, 0), (1, 2, 3))])
        board, collider = entities["Board"], entities["Board_Collider_0"]
        assert board["EditorNonUniformScaleComponent"]["NonUniformScale"] == [-1.0, 1.0, 1.0]
        assert "EditorBoxShapeComponent" not in board and "EditorShapeColliderComponent" not in board
        assert "EditorNonUniformScaleComponent" not in collider, "nothing but the mirror to carry"
        assert _box(collider)["Dimensions"] == [1.0, 3.0, 2.0]
        assert _box(collider)["TranslationOffset"] == [-0.5, 0.0, 0.0], "the centre lies on the other side"
        assert collider["EditorShapeColliderComponent"]["ColliderConfiguration"]["Position"] == [-0.5, 0.0, 0.0]


def test_a_mirrored_and_stretched_objects_box_carries_the_stretch():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (-2, 1, 3), [((0.5, 0, 0), (1, 2, 3))])
        collider = entities["Board_Collider_0"]
        # Unity's (x, y, z) is O3DE's (x, z, y); the sizes, not the signs.
        assert collider["EditorNonUniformScaleComponent"]["NonUniformScale"] == [2.0, 3.0, 1.0]
        assert _box(collider)["TranslationOffset"] == [-0.5, 0.0, 0.0]


def test_a_second_box_of_a_stretched_object_carries_the_objects_scale():
    """Three boards of Prefab_Bridge_3 carry two boxes each. The second one
    stood half a metre out: its entity had nothing of the board's scale."""
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (0.75, 1, 0.5), [((0, 0, 0), (4, 1, 1)), ((0, 0, 0), (4, 1, 1))])
        board, second = entities["Board"], entities["Board_Collider_1"]
        assert "EditorBoxShapeComponent" in board
        assert second["EditorNonUniformScaleComponent"]["NonUniformScale"] == \
            board["EditorNonUniformScaleComponent"]["NonUniformScale"] == [0.75, 0.5, 1.0]
        assert _box(second)["Dimensions"] == [4.0, 1.0, 1.0]


def test_a_second_box_of_an_unstretched_object_carries_no_scale():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (1, 1, 1), [((0, 0, 0), (4, 1, 1)), ((0, 1, 0), (1, 1, 1))])
        assert "EditorNonUniformScaleComponent" not in entities["Board_Collider_1"]
        assert _box(entities["Board_Collider_1"])["TranslationOffset"] == [0.0, 0.0, 1.0]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
