"""Unit tests for a scale by axis carried down (nature_pack I.4).

The bridges of the NatureManufacture pack hang their boards under objects
stretched along one axis. Unity scales everything below such an object with
it; O3DE keeps a scale by axis on the one entity. The converter carries it
down before anything is written:

  - what hangs below gets its place scaled and its own scale multiplied;
  - an object turned by quarter turns takes the scale with its axes swapped,
    exactly; one turned otherwise would be skewed, and is reported;
  - a mirror skews nothing: the object below is turned over and mirrored
    along the same axes of its own, however it is turned;
  - one scale for all axes is left to the engine, which passes it down;
  - a placed prefab below gets its place scaled and is told what it
    inherits, for the writer of its scale.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matrix3
from tests.harness import run_module_tests
from platforms.unity.scale_carry import (
    carried_transform, carry_scales_down, handed_down, mirrored_rotation, scale_in_own_axes,
)
from platforms.unity.types import GameObject, Transform
from targets.o3de.prefab_writer import instance_scale_patches

HALF = 0.5 ** 0.5
QUARTER_ABOUT_Y = (0.0, HALF, 0.0, HALF)            # the object's X lies along the parent's -Z
EIGHTH_ABOUT_Y = (0.0, 0.3826834, 0.0, 0.9238795)   # turned 45 degrees: no axis lines up


def _close(a, b, tolerance=1e-6):
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


# =============================================================================
# ONE OBJECT
# =============================================================================

def test_an_objects_place_is_scaled_and_its_scale_multiplied():
    carried, skewed = carried_transform(Transform((1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 2.0)), (2.0, 1.0, 0.5))
    assert carried.position == (2.0, 2.0, 1.5) and carried.scale == (2.0, 1.0, 1.0) and not skewed


def test_an_object_turned_a_quarter_takes_the_scale_with_its_axes_swapped():
    """Its own X lies along the parent's Z: the parent's Z scale stretches
    it along X."""
    along, skewed = scale_in_own_axes(QUARTER_ABOUT_Y, (2.0, 1.0, 3.0))
    assert _close(along, (3.0, 1.0, 2.0)) and not skewed


def test_an_object_turned_otherwise_is_skewed_and_keeps_its_size_along_its_own_axes():
    along, skewed = scale_in_own_axes(EIGHTH_ABOUT_Y, (2.0, 1.0, 1.0))
    assert skewed
    assert _close(along, ((2.5) ** 0.5, 1.0, (2.5) ** 0.5), 1e-5)      # sqrt(2^2 / 2 + 1 / 2) on both
    assert scale_in_own_axes(EIGHTH_ABOUT_Y, (2.0, 2.0, 2.0)) == ((2.0, 2.0, 2.0), False) or \
        _close(scale_in_own_axes(EIGHTH_ABOUT_Y, (2.0, 2.0, 2.0))[0], (2.0, 2.0, 2.0)), "one scale for all axes never skews"


def test_a_mirror_is_carried_with_its_sign():
    along, skewed = scale_in_own_axes((0.0, 0.0, 0.0, 1.0), (-1.0, 1.0, 1.0))
    assert along == (-1.0, 1.0, 1.0) and not skewed


# =============================================================================
# A MIRROR
# =============================================================================

def _matrix(rotation, scale):
    """Rotation times scale, as a matrix."""
    diagonal = [[scale[0], 0.0, 0.0], [0.0, scale[1], 0.0], [0.0, 0.0, scale[2]]]
    return matrix3.mat_mul(matrix3.quat_to_matrix(rotation), diagonal)


def _same_matrix(a, b):
    return all(abs(a[row][column] - b[row][column]) < 1e-6 for row in range(3) for column in range(3))


def test_an_object_below_a_mirror_is_turned_over_and_mirrored_itself():
    """Mirror times rotation is the turned-over rotation times the mirror:
    the object's shape in its parent comes out the same."""
    own_scale = (1.0, 2.0, 3.0)
    for mirror in ((-1.0, 1.0, 1.0), (1.0, -1.0, 1.0), (-1.0, -1.0, 1.0), (-1.0, -1.0, -1.0)):
        for rotation in (EIGHTH_ABOUT_Y, QUARTER_ABOUT_Y, (0.1825742, 0.3651484, 0.5477226, 0.7302967)):
            turned, factors, skewed = handed_down(rotation, mirror)
            assert _close(factors, mirror) and not skewed, "a mirror skews nothing"
            in_unity = matrix3.mat_mul([[mirror[0], 0.0, 0.0], [0.0, mirror[1], 0.0], [0.0, 0.0, mirror[2]]],
                                       _matrix(rotation, own_scale))
            carried = _matrix(turned, tuple(own * factor for own, factor in zip(own_scale, factors)))
            assert _same_matrix(in_unity, carried), (mirror, rotation)


def test_a_mirror_along_x_turns_a_rotation_about_y_the_other_way():
    assert _close(mirrored_rotation(EIGHTH_ABOUT_Y, (-1.0, 1.0, 1.0)), (0.0, -0.3826834, 0.0, 0.9238795))
    assert _close(mirrored_rotation(EIGHTH_ABOUT_Y, (1.0, 1.0, 1.0)), EIGHTH_ABOUT_Y)


def test_a_mirrored_stretch_is_carried_as_a_mirror_and_a_stretch():
    carried, skewed = carried_transform(Transform((1.0, 2.0, 3.0), QUARTER_ABOUT_Y, (1.0, 1.0, 1.0)), (-2.0, 1.0, 1.0))
    assert carried.position == (-2.0, 2.0, 3.0) and not skewed
    # Turned a quarter the other way now, its own Z lies along the parent's X: mirrored along X, stretched along Z.
    assert _close(carried.rotation, (0.0, -HALF, 0.0, HALF)) and _close(carried.scale, (-1.0, 1.0, 2.0))


# =============================================================================
# THE PASS OVER A HIERARCHY
# =============================================================================

def _tree(**scales):
    """Bridge > Frame > Board > Nail, and Bridge > Lamp."""
    def make(file_id, name, parent, children, rotation=(0.0, 0.0, 0.0, 1.0)):
        return GameObject(file_id=file_id, name=name, parent_id=parent, children_ids=list(children),
                          transform=Transform((1.0, 1.0, 1.0), rotation, scales.get(name, (1.0, 1.0, 1.0))))
    objects = [make("1", "Bridge", None, ("2", "5")), make("2", "Frame", "1", ("3",)),
               make("3", "Board", "2", ("4",), QUARTER_ABOUT_Y), make("4", "Nail", "3", ()), make("5", "Lamp", "1", ())]
    return {go.file_id: go for go in objects}


def _by_name(objects):
    return {go.name: go.transform for go in objects.values()}


def test_a_scale_by_axis_reaches_everything_below_it():
    objects = _tree(Frame=(2.0, 1.0, 1.0))
    assert carry_scales_down(objects) == 2
    now = _by_name(objects)
    assert now["Frame"].position == (1.0, 1.0, 1.0) and now["Frame"].scale == (2.0, 1.0, 1.0), "the frame itself is as it was"
    assert now["Board"].position == (2.0, 1.0, 1.0)
    assert _close(now["Board"].scale, (1.0, 1.0, 2.0)), "turned a quarter: stretched along its own Z"
    # The board is by axis now, so it hands its scale on in turn.
    assert _close(now["Nail"].position, (1.0, 1.0, 2.0)) and _close(now["Nail"].scale, (1.0, 1.0, 2.0))
    assert now["Lamp"].scale == (1.0, 1.0, 1.0), "beside the frame, not below it"


def test_one_scale_for_all_axes_is_left_to_the_engine():
    objects = _tree(Frame=(2.0, 2.0, 2.0))
    assert carry_scales_down(objects) == 0
    assert _by_name(objects)["Board"].position == (1.0, 1.0, 1.0)


def test_a_skew_is_reported_once_per_object():
    objects = _tree(Frame=(2.0, 1.0, 1.0))
    objects["3"].transform = Transform((1.0, 1.0, 1.0), EIGHTH_ABOUT_Y, (1.0, 1.0, 1.0))
    warnings = []
    carry_scales_down(objects, warnings.append)
    assert len(warnings) == 1 and "'Board'" in warnings[0] and "skews" in warnings[0]


def test_a_placed_prefab_below_gets_its_place_scaled_and_is_told_what_it_inherits():
    objects = _tree(Frame=(2.0, 1.0, 1.0))
    objects["3"].is_prefab_instance = True
    carry_scales_down(objects)
    board = objects["3"]
    assert board.transform.position == (2.0, 1.0, 1.0)
    assert board.transform.scale == (1.0, 1.0, 1.0), "its own scale is written from its overrides"
    assert _close(board.component_data["inherited_scale"], (1.0, 1.0, 2.0))
    assert _by_name(objects)["Nail"].scale == (1.0, 1.0, 1.0), "what is inside the placed prefab is the prefab's"


def test_the_placed_prefabs_root_takes_what_it_inherits():
    """Root (1, 1, 1), nothing overridden, a frame above scaled by axis:
    the root entity gets the inherited scale, in O3DE's axes."""
    go = GameObject(file_id="7000", name="Board", transform=Transform(), is_prefab_instance=True)
    go.component_data["inherited_scale"] = (1.0, 1.0, 2.0)
    sidecar = {"root_entity": "Entity_[9]", "root_scale": [1.0, 1.0, 1.0], "entity_aliases": {"1": "Entity_[9]"}}
    patches = instance_scale_patches(go, sidecar, 5, lambda line: None)
    assert patches[0]["value"] == 1.0 and patches[0]["path"].endswith("/Transform Data/UniformScale")
    assert patches[1]["value"]["NonUniformScale"] == [1.0, 2.0, 1.0]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
