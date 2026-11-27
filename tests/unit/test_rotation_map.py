"""Unit tests for the Unity to O3DE rotation map (parity_fixes I.1, proof T.1).

Two things have to hold together for a converted rotation to be right:

  - the quaternion map: a Unity rotation in O3DE axes is ``A R A``, with
    ``A`` the swap of Y and Z. As a quaternion that is ``(-x, -z, -y, w)``;
  - the Euler angles written to the prefab: O3DE turns them back into a
    rotation as ``rotx * roty * rotz``, and must land on the same one.

The tests rebuild O3DE's side of that from its formula
(``AZ::Quaternion::SetFromEulerRadians``) and compare matrices.
"""

import math
import random
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.types import Transform
from targets.o3de.prefab_writer import convert_to_o3de_coordinates, quaternion_to_euler


# =============================================================================
# REFERENCE MATH
# =============================================================================

def _matrix(q):
    """The rotation matrix of a quaternion (x, y, z, w)."""
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
            [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)]]


def _swap(matrix):
    """``A M A``: the same linear map with Y and Z exchanged."""
    order = (0, 2, 1)
    return [[matrix[order[row]][order[column]] for column in range(3)] for row in range(3)]


def _o3de_quaternion_from_euler(degrees):
    """O3DE's ``SetFromEulerRadians``: rot = rotx * roty * rotz."""
    sx, sy, sz = (math.sin(math.radians(angle) / 2) for angle in degrees)
    cx, cy, cz = (math.cos(math.radians(angle) / 2) for angle in degrees)
    return (cx * sy * sz + sx * cy * cz,
            cx * sy * cz - sx * cy * sz,
            cx * cy * sz + sx * sy * cz,
            cx * cy * cz - sx * sy * sz)


def _largest_difference(a, b):
    return max(abs(a[row][column] - b[row][column]) for row in range(3) for column in range(3))


def _random_quaternion(generator):
    q = [generator.uniform(-1, 1) for _ in range(4)]
    length = math.sqrt(sum(value * value for value in q))
    return tuple(value / length for value in q)


def _axis_angle(axis, degrees):
    half = math.radians(degrees) / 2
    return (axis[0] * math.sin(half), axis[1] * math.sin(half), axis[2] * math.sin(half), math.cos(half))


def _convert(q):
    converted, _ = convert_to_o3de_coordinates(Transform((0.0, 0.0, 0.0), q, (1.0, 1.0, 1.0)))
    return converted.rotation


# =============================================================================
# THE QUATERNION MAP
# =============================================================================

def test_converted_rotation_is_the_unity_rotation_in_o3de_axes():
    generator = random.Random(11)
    for _ in range(500):
        q = _random_quaternion(generator)
        assert _largest_difference(_matrix(_convert(q)), _swap(_matrix(q))) < 1e-12


def test_unity_yaw_of_90_faces_plus_x():
    """Unity: turned +90 about Y, forward (+Z) points along +X. In O3DE the
    forward axis is +Y and must point along +X as well."""
    matrix = _matrix(_convert(_axis_angle((0, 1, 0), 90.0)))
    forward = [matrix[row][1] for row in range(3)]
    assert max(abs(forward[0] - 1.0), abs(forward[1]), abs(forward[2])) < 1e-12, forward


def test_unity_pitch_down_stays_down():
    """Unity: turned +50 about X, forward tips below the horizon. The same
    must hold for O3DE's forward axis, with no patch on top."""
    matrix = _matrix(_convert(_axis_angle((1, 0, 0), 50.0)))
    forward = [matrix[row][1] for row in range(3)]
    assert forward[2] < -0.7, forward          # O3DE Z is up
    assert forward[1] > 0.6, forward


def test_no_turn_and_half_turn_are_unchanged_in_effect():
    for q in ((0.0, 0.0, 0.0, 1.0), _axis_angle((0, 1, 0), 180.0)):
        assert _largest_difference(_matrix(_convert(q)), _swap(_matrix(q))) < 1e-12


# =============================================================================
# THE EULER ANGLES O3DE READS BACK
# =============================================================================

def test_euler_angles_give_the_same_rotation_back_in_o3de():
    generator = random.Random(5)
    for _ in range(500):
        q = _random_quaternion(generator)
        back = _o3de_quaternion_from_euler(quaternion_to_euler(q))
        assert _largest_difference(_matrix(back), _matrix(q)) < 1e-9, (q, back)


def test_single_axis_turns_keep_their_angle():
    for index, axis in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
        angles = quaternion_to_euler(_axis_angle(axis, 35.0))
        expected = [35.0 if position == index else 0.0 for position in range(3)]
        assert max(abs(a - e) for a, e in zip(angles, expected)) < 1e-9, angles


def test_looking_straight_along_x_is_still_the_same_rotation():
    """At 90 degrees about Y the X and Z angles are not separate; whatever
    split is written, O3DE must read the same rotation back."""
    for degrees in (90.0, -90.0):
        q = _matrix_product_quaternion(_axis_angle((1, 0, 0), 25.0), _axis_angle((0, 1, 0), degrees))
        back = _o3de_quaternion_from_euler(quaternion_to_euler(q))
        assert _largest_difference(_matrix(back), _matrix(q)) < 1e-6, (degrees, quaternion_to_euler(q))


def _matrix_product_quaternion(a, b):
    """The quaternion of rotation ``a`` after rotation ``b`` (a * b)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


# =============================================================================
# THE WHOLE WAY: UNITY ROTATION -> PREFAB ANGLES -> O3DE ROTATION
# =============================================================================

def test_a_compound_unity_rotation_arrives_whole():
    """The Showcase scene's light: turned about more than one axis."""
    unity = (0.7936, -0.1476, 0.2126, 0.5507)
    length = math.sqrt(sum(value * value for value in unity))
    unity = tuple(value / length for value in unity)
    in_o3de = _o3de_quaternion_from_euler(quaternion_to_euler(_convert(unity)))
    assert _largest_difference(_matrix(in_o3de), _swap(_matrix(unity))) < 1e-9


# =============================================================================
# THE DIRECTIONAL LIGHT ADDS NOTHING TO ITS TRANSFORM
# =============================================================================

def test_directional_light_leaves_the_transform_alone():
    from platforms.unity.components.light import LightComponentProcessor
    rotate = [12.0, -34.0, 56.0]
    entity = {"Id": "Entity_[1]",
              "Components": {"TransformComponent": {"Transform Data": {"Rotate": list(rotate)}}}}
    context = SimpleNamespace(generate_component_id=lambda: 1, log=lambda line: None, stats={})
    sun = SimpleNamespace(component_data={})
    LightComponentProcessor()._emit_directional({"intensity": 1.0, "shadows": True}, entity, sun, context)
    assert entity["Components"]["TransformComponent"]["Transform Data"]["Rotate"] == rotate
    assert "AZ::Render::EditorDirectionalLightComponent" in entity["Components"]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
