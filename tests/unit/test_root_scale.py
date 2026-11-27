"""Unit tests for the scale of a prefab's root (nature_pack I.4).

Seventy-nine prefabs of the NatureManufacture pack are saved with a root
scale other than one (a rock at twice its model's size). The converter left
a root's whole transform out, since whoever places a prefab gives its
position and rotation. A placement stores a scale only when it changes it:

  - the root entity keeps the root's own scale, and leaves out its position
    and rotation;
  - a placement that sets no scale writes none: the prefab's own stands;
  - a placement that sets one replaces the root entity's scale, axis by
    axis, where an axis it does not name keeps the prefab's.
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
from targets.o3de.prefab_writer import instance_scale_patches, overridden_root_scale

ROCK_GUID = "aaaabbbbccccdddd0000111122223333"
ROOT_TRANSFORM = "400000"


# =============================================================================
# FIXTURES
# =============================================================================

def _prefab(scale, position=(0, 0, 0)) -> str:
    """A prefab of a root and one child, the root stored with this scale."""
    def one(game_object_id, transform_id, name, father, children, local_scale, local_position):
        child_lines = "".join(f"\n  - {{fileID: {child}}}" for child in children) or " []"
        return f"""--- !u!1 &{game_object_id}
GameObject:
  m_Component:
  - component: {{fileID: {transform_id}}}
  m_Name: {name}
--- !u!4 &{transform_id}
Transform:
  m_GameObject: {{fileID: {game_object_id}}}
  m_LocalRotation: {{x: 0, y: 0.7071068, z: 0, w: 0.7071068}}
  m_LocalPosition: {{x: {local_position[0]}, y: {local_position[1]}, z: {local_position[2]}}}
  m_LocalScale: {{x: {local_scale[0]}, y: {local_scale[1]}, z: {local_scale[2]}}}
  m_Children:{child_lines}
  m_Father: {{fileID: {father}}}
"""
    return ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
            + one(100000, ROOT_TRANSFORM, "Rock", 0, (400002,), scale, position)
            + one(100002, 400002, "Moss", ROOT_TRANSFORM, (), (1, 1, 1), (0, 1, 0)))


def _convert(tmp: Path, scale, position=(0, 0, 0)):
    """Convert the prefab; return its entities by name and its entity map."""
    unity = tmp / "unity"
    unity.mkdir(parents=True, exist_ok=True)
    (unity / "Rock.prefab").write_text(_prefab(scale, position), encoding="utf-8")
    (unity / "Rock.prefab.meta").write_text(f"fileFormatVersion: 2\nguid: {ROCK_GUID}\n", encoding="utf-8")
    random.seed(7)
    worker = IntegratedAssetProcessor(unity, tmp / "out", log_callback=lambda line: None)
    assert worker.process_prefab(unity / "Rock.prefab")
    written = json.loads((tmp / "out" / "Prefabs" / "Rock.prefab").read_text(encoding="utf-8"))
    return ({entity["Name"]: entity for entity in written["Entities"].values()},
            worker._project_prefab_records[ROCK_GUID])


def _placed(**scale_overrides) -> GameObject:
    """A placement of the rock that sets these axes of its root's scale,
    beside the position and rotation Unity always stores."""
    modifications = [{"target": {"fileID": ROOT_TRANSFORM}, "propertyPath": path, "value": 0}
                     for path in ([f"m_LocalPosition.{axis}" for axis in "xyz"]
                                  + [f"m_LocalRotation.{axis}" for axis in "xyzw"])]
    modifications += [{"target": {"fileID": ROOT_TRANSFORM}, "propertyPath": f"m_LocalScale.{axis}", "value": value}
                      for axis, value in scale_overrides.items()]
    # A scale set on an object inside the instance is not the instance's.
    modifications.append({"target": {"fileID": "400002"}, "propertyPath": "m_LocalScale.x", "value": 9})
    go = GameObject(file_id="7000", name="Rock (3)", transform=Transform(), is_prefab_instance=True)
    go.prefab_modifications = modifications
    return go


def _map(root_scale=(2.0, 2.0, 2.0), **more) -> dict:
    return {"root_entity": "Entity_[1000001]", "root_scale": list(root_scale),
            "entity_aliases": {"100000": "Entity_[1000001]"}, **more}


ROOT = "/Entities/Entity_[1000001]/Components"
UNIFORM = f"{ROOT}/TransformComponent/Transform Data/UniformScale"


# =============================================================================
# THE ROOT ENTITY
# =============================================================================

def test_the_root_entity_keeps_the_roots_scale_and_leaves_out_where_it_stands():
    with tempfile.TemporaryDirectory() as folder:
        entities, _ = _convert(Path(folder), scale=(2, 2, 2), position=(5, 0, 3))
        data = entities["Rock"]["Components"]["TransformComponent"]["Transform Data"]
        assert data == {"Translate": [0.0, 0.0, 0.0], "UniformScale": 2.0}
        # What hangs below keeps its own place and turn.
        moss = entities["Moss"]["Components"]["TransformComponent"]["Transform Data"]
        assert moss["Translate"] == [0.0, 0.0, 1.0] and "Rotate" in moss


def test_a_root_scaled_by_axis_carries_the_scale_component():
    with tempfile.TemporaryDirectory() as folder:
        entities, _ = _convert(Path(folder), scale=(1, 3, 2))
        components = entities["Rock"]["Components"]
        assert components["EditorNonUniformScaleComponent"]["NonUniformScale"] == [1.0, 2.0, 3.0]
        assert "UniformScale" not in components["TransformComponent"]["Transform Data"]


def test_the_entity_map_keeps_the_roots_scale_as_unity_stores_it():
    with tempfile.TemporaryDirectory() as folder:
        _, record = _convert(Path(folder), scale=(1, 3, 2))
        assert record["root_scale"] == [1.0, 3.0, 2.0]


# =============================================================================
# A PLACEMENT'S SCALE
# =============================================================================

def test_only_a_scale_set_on_the_instances_own_root_counts():
    assert overridden_root_scale(_placed().prefab_modifications) == {}
    assert overridden_root_scale(_placed(y=3).prefab_modifications) == {"y": 3.0}


def test_a_placement_that_sets_no_scale_writes_none():
    """The prefab's own scale stands: the rock is twice its model's size
    wherever it is placed."""
    assert instance_scale_patches(_placed(), _map(), 5, lambda line: None) == []


def test_a_scale_the_same_on_all_axes_replaces_the_root_entitys():
    patches = instance_scale_patches(_placed(x=3, y=3, z=3), _map(), 5, lambda line: None)
    assert patches == [{"op": "add", "path": UNIFORM, "value": 3.0}]


def test_an_axis_the_placement_does_not_name_keeps_the_prefabs():
    """Root (2, 2, 2), placement sets y to 3: Unity shows (2, 3, 2), which in
    O3DE's axes is (2, 2, 3) - by axis now, so the uniform scale is one."""
    patches = instance_scale_patches(_placed(y=3), _map(), 5, lambda line: None)
    assert patches[0] == {"op": "add", "path": UNIFORM, "value": 1.0}
    assert patches[1]["path"] == f"{ROOT}/EditorNonUniformScaleComponent"
    assert patches[1]["value"]["NonUniformScale"] == [2.0, 2.0, 3.0]


def test_a_placement_that_evens_out_a_root_scaled_by_axis_takes_its_component_back():
    patches = instance_scale_patches(_placed(x=2, y=2, z=2), _map(root_scale=(1.0, 3.0, 2.0)), 5, lambda line: None)
    assert patches == [{"op": "add", "path": UNIFORM, "value": 2.0},
                       {"op": "add", "path": f"{ROOT}/EditorNonUniformScaleComponent/NonUniformScale",
                        "value": [1.0, 1.0, 1.0]}]


def test_a_roots_mesh_stretch_stays_in_whatever_scale_it_is_handed():
    patches = instance_scale_patches(_placed(x=3, y=3, z=3), _map(root_mesh_stretch=[1.0, 1.0, 2.0]), 5,
                                     lambda line: None)
    assert patches[0] == {"op": "add", "path": UNIFORM, "value": 1.0}
    assert patches[1]["value"]["NonUniformScale"] == [3.0, 3.0, 6.0]


def test_without_the_prefabs_entity_map_only_the_container_can_be_scaled():
    patches = instance_scale_patches(_placed(x=3, y=3, z=3), None, 5, lambda line: None)
    assert patches == [{"op": "replace", "value": 3.0,
                        "path": "/ContainerEntity/Components/TransformComponent/Transform Data/UniformScale"}]
    warnings = []
    assert instance_scale_patches(_placed(y=3), None, 5, warnings.append) == []
    assert len(warnings) == 1


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
