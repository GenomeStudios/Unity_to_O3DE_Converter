"""
=============================================================================
MATRIX3
=============================================================================

The small 3x3 rotation arithmetic the converter needs, on nested lists. The
converter itself has no numpy, and these few functions do not earn one.

A rotation is ``[[m00, m01, m02], [m10, m11, m12], [m20, m21, m22]]`` acting
on column vectors; a quaternion is ``[x, y, z, w]``.
"""

from __future__ import annotations

import math

IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


# =============================================================================
# PRODUCTS
# =============================================================================

def mat_mul(a, b) -> list:
    return [[sum(a[row][k] * b[k][column] for k in range(3)) for column in range(3)] for row in range(3)]


def mat_vec(matrix, vector) -> list:
    return [sum(matrix[row][k] * vector[k] for k in range(3)) for row in range(3)]


def transpose(matrix) -> list:
    """The transpose, which for a rotation is its inverse."""
    return [[matrix[column][row] for column in range(3)] for row in range(3)]


def is_identity(matrix) -> bool:
    return all(abs(matrix[row][column] - IDENTITY[row][column]) < 1e-9 for row in range(3) for column in range(3))


# =============================================================================
# EULER ANGLES AND QUATERNIONS
# =============================================================================

def euler_xyz_matrix(degrees) -> list:
    """The matrix of an FBX Euler rotation in its default order XYZ: a turn
    about X, then Y, then Z (``Rz * Ry * Rx``)."""
    x, y, z = (math.radians(float(value or 0.0)) for value in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [[cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy,     sx * cy,                cx * cy]]


def quat_to_matrix(quaternion) -> list:
    x, y, z, w = quaternion
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
            [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)]]


def matrix_to_quat(m) -> list:
    """Quaternion [x, y, z, w] of a rotation matrix, stable for half turns."""
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        quaternion = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        quaternion = [0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s]
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        quaternion = [(m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s]
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        quaternion = [(m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s]
    # One sign for one rotation, so two runs write the same numbers.
    if quaternion[3] < 0.0 or (quaternion[3] == 0.0 and next((v for v in quaternion if v), 0.0) < 0.0):
        quaternion = [-value for value in quaternion]
    return [0.0 if abs(value) < 1e-12 else value for value in quaternion]
