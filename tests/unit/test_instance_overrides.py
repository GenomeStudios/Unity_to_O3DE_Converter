"""Unit tests for the overrides of a nested prefab instance (parity_fixes
I.4, proof T.7) and for the sides of a box collider (I.6, proof T.9).

An instance's overrides name the object they change by its id in the source
prefab. Those on the instance's root place the instance; those on an object
inside it (the cell door of the Office pack, nudged in its frame) belong to
that object. Taken together they put the whole instance where the door was.
"""

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.components.box_collider import MIN_BOX_SIDE, box_dimensions
from platforms.unity.prefab import (
    UnityParseContext, nested_prefabs_first, parse_unity_prefab, root_override_target, targets_root,
)
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter
from targets.o3de.prefab_writer import child_transform_patches

ROOT = "2140103544440162284"       # the door prefab's root transform
MESH = "6791355114786859484"       # the transform of the door's mesh, inside it


# =============================================================================
# FIXTURE: the overrides the cell carries for its door
# =============================================================================

def _mod(target, path, value):
    return {"target": {"fileID": int(target), "guid": "ede9743b5aa5bff488ac363f58c4afb2", "type": 3},
            "propertyPath": path, "value": value, "objectReference": {"fileID": 0}}


def _door_overrides():
    root = {"m_RootOrder": 0, "m_LocalPosition.x": -0.605, "m_LocalPosition.y": 0, "m_LocalPosition.z": 1.5,
            "m_LocalRotation.w": 0, "m_LocalRotation.x": 0, "m_LocalRotation.y": 1, "m_LocalRotation.z": 0,
            "m_LocalEulerAnglesHint.y": 180}
    inside = {"m_LocalPosition.x": -0.004, "m_LocalPosition.z": -0.053}
    return ([_mod(ROOT, path, value) for path, value in root.items()]
            + [_mod("4237051237172027966", "m_Name", "Door_Cell")]
            + [_mod(MESH, path, value) for path, value in inside.items()])


def _yaml(modifications) -> str:
    lines = []
    for mod in modifications:
        lines += [f"    - target: {{fileID: {mod['target']['fileID']}, guid: {mod['target']['guid']}, type: 3}}",
                  f"      propertyPath: {mod['propertyPath']}",
                  f"      value: {mod['value']}",
                  "      objectReference: {fileID: 0}"]
    return "\n".join(lines)


CELL_PREFAB = """%%YAML 1.1
%%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 480938}
  m_Name: Cell
--- !u!4 &480938
Transform:
  m_GameObject: {fileID: 100}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children: []
  m_Father: {fileID: 0}
--- !u!1001 &7178775434919810505
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 480938}
    m_Modifications:
%s
    m_RemovedComponents: []
  m_SourcePrefab: {fileID: 100100000, guid: ede9743b5aa5bff488ac363f58c4afb2, type: 3}
""" % _yaml(_door_overrides())


class _Coverage:
    def record_component(self, *_):
        pass


# =============================================================================
# WHICH OVERRIDE IS THE INSTANCE'S OWN
# =============================================================================

def test_the_root_is_the_target_that_carries_position_and_rotation_whole():
    assert root_override_target(_door_overrides()) == ROOT


def test_with_two_whole_targets_the_one_with_a_root_order_is_the_root():
    whole = [f"m_LocalPosition.{a}" for a in "xyz"] + [f"m_LocalRotation.{a}" for a in "xyzw"]
    modifications = [_mod("11", path, 0) for path in whole] + \
                    [_mod("22", path, 0) for path in whole] + [_mod("22", "m_RootOrder", 3)]
    assert root_override_target(modifications) == "22"
    assert root_override_target(modifications[:-1]) == "11"       # no root order: the first listed


def test_without_a_whole_target_no_root_is_named_and_every_override_counts():
    modifications = [_mod("11", "m_LocalPosition.x", 1.0)]
    assert root_override_target(modifications) is None
    assert targets_root(modifications[0], None) is True
    assert targets_root(modifications[0], "22") is False


def test_the_prefab_parser_places_the_instance_by_its_roots_overrides_only():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Cell.prefab"
        path.write_text(CELL_PREFAB, encoding="utf-8")
        context = UnityParseContext(log=lambda line: None, coverage=_Coverage(), component_dispatch={})
        game_objects, _ = parse_unity_prefab(context, path)
    door = game_objects["7178775434919810505"]
    assert door.transform.position == (-0.605, 0.0, 1.5), door.transform.position
    assert door.transform.rotation == (0.0, 1.0, 0.0, 0.0)
    assert len(door.prefab_modifications) == len(_door_overrides())     # all kept for the emitter


def test_the_scene_parser_places_the_instance_by_its_roots_overrides_only():
    converter = UnitySceneConverter(PrefabDatabase(), log_callback=lambda line: None)
    converter._parse_prefab_instance({
        "m_SourcePrefab": {"guid": "ede9743b5aa5bff488ac363f58c4afb2"},
        "m_Modification": {"m_TransformParent": {"fileID": 0}, "m_Modifications": _door_overrides()},
    }, "77")
    assert converter.prefab_instances[0]["position"] == (-0.605, 0.0, 1.5)


# =============================================================================
# OVERRIDES ON AN OBJECT INSIDE THE INSTANCE
# =============================================================================

SIDECAR = {"entity_aliases": {"6791355114786436604": "Entity_[1000042]"},
           "transform_owners": {MESH: "6791355114786436604"}}


def test_a_position_override_inside_becomes_a_patch_per_axis_with_y_and_z_swapped():
    warnings = []
    patches = child_transform_patches(_door_overrides(), SIDECAR, "Door_Cell", warnings.append)
    base = "/Entities/Entity_[1000042]/Components/TransformComponent/Transform Data"
    assert patches == [
        {"op": "replace", "path": base + "/Translate/0", "value": -0.004},      # Unity x
        {"op": "replace", "path": base + "/Translate/1", "value": -0.053},      # Unity z
    ], patches
    assert warnings == []


def test_a_whole_rotation_inside_is_set_and_a_partial_one_is_reported():
    whole = _door_overrides() + [_mod(MESH, f"m_LocalRotation.{axis}", value)
                                 for axis, value in zip("xyzw", (0.0, 0.7071068, 0.0, 0.7071068))]
    warnings = []
    patches = child_transform_patches(whole, SIDECAR, "Door_Cell", warnings.append)
    rotate = next(p for p in patches if p["path"].endswith("/Rotate"))
    assert rotate["op"] == "add" and len(rotate["value"]) == 3
    assert abs(abs(rotate["value"][2]) - 90.0) < 1e-3 and warnings == []      # a yaw in Unity turns about O3DE's Z

    partial = _door_overrides() + [_mod(MESH, "m_LocalRotation.y", 0.5)]
    child_transform_patches(partial, SIDECAR, "Door_Cell", warnings.append)
    assert any("only part of the rotation" in line for line in warnings)


def test_a_uniform_scale_inside_is_set_under_the_engines_field_name():
    """The engine reads an entity's one scale from `UniformScale`. `Scale`
    is its legacy three-axis field, and a number written there is lost."""
    scaled = _door_overrides() + [_mod(MESH, f"m_LocalScale.{axis}", 0.796) for axis in "xyz"]
    patches = child_transform_patches(scaled, SIDECAR, "Door_Cell", lambda line: None)
    scale = next(p for p in patches if "Scale" in p["path"])
    assert scale["path"].endswith("/Transform Data/UniformScale") and scale["value"] == 0.796


def test_an_object_the_entity_map_does_not_hold_is_reported_not_patched():
    warnings = []
    assert child_transform_patches(_door_overrides(), {}, "Door_Cell", warnings.append) == []
    assert any(MESH in line for line in warnings), warnings


def test_overrides_that_cannot_be_told_apart_make_no_patches():
    assert child_transform_patches([_mod(MESH, "m_LocalPosition.x", 1.0)], SIDECAR, "Door", lambda line: None) == []


# =============================================================================
# THE ORDER PREFABS ARE CONVERTED IN
# =============================================================================

def test_a_prefab_comes_after_the_ones_it_nests_and_the_rest_keep_their_order():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        guids = {}

        def prefab(name, guid, nests=()):
            path = root / f"{name}.prefab"
            path.write_text("".join(f"  m_SourcePrefab: {{fileID: 100100000, guid: {g}, type: 3}}\n" for g in nests),
                            encoding="utf-8")
            guids[path] = guid
            return path

        cell = prefab("Cell", "aa", nests=("bb",))
        chair = prefab("Chair", "cc")
        door = prefab("Door_Cell", "bb", nests=("ff",))          # ff: a model, not one of the files
        loop_a = prefab("Loop_A", "dd", nests=("ee",))
        loop_b = prefab("Loop_B", "ee", nests=("dd",))

        ordered = nested_prefabs_first([cell, chair, door, loop_a, loop_b], guids.get)
        assert ordered == [door, cell, chair, loop_b, loop_a], [p.stem for p in ordered]


# =============================================================================
# THE SIDES OF A BOX COLLIDER
# =============================================================================

def test_a_negative_side_is_its_magnitude():
    """The standing whiteboard's legs: m_Size (0.03, 1.39, -0.02)."""
    assert box_dimensions((0.03, -0.02, 1.39)) == [0.03, 0.02, 1.39]


def test_a_side_of_zero_becomes_the_thinnest_box():
    """A sheet of paper: m_Size (0.21, 0, 0.297)."""
    assert box_dimensions((0.21, 0.297, 0.0)) == [0.21, 0.297, MIN_BOX_SIDE]
    assert all(side > 0.0 for side in box_dimensions((0, 0, 0)))


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
