"""
=============================================================================
PARITY COMPARE - THE MATH
=============================================================================

Pure functions on numpy arrays. No files, no engine: everything here is unit
tested with made-up geometry (tests/unit/test_parity_compare.py).

Frames
------
The canonical frame is O3DE's: metres, Z up, right-handed. A Unity point
``(x, y, z)`` is the O3DE point ``(x, z, y)``; a Unity transform ``X`` is
the O3DE transform ``A X A``, with ``A`` the matrix of that swap. This file
is the only place that mapping is applied.

Distances
---------
Two pieces of geometry are compared as point sets: for each point of one,
the distance to the nearest point of the other, both ways. The largest of
those is zero only when the two coincide in place, so one number catches an
offset, a rotation, a mirror and a scale.

Placement fit
-------------
Truth vertices are not always exact: Unity's mesh compression moves each
vertex by up to a few millimetres. ``fit_placement`` therefore measures where
a whole mesh sits: it pairs each vertex with its nearest partner and solves
for the rigid motion between the two sets. Vertex noise averages out; a real
offset or turn of the mesh does not. Tolerances apply to that fit.

Residual
--------
For geometry that does not coincide, ``find_residual`` looks for the
correction that would make it: one of the 48 signed axis permutations (the
24 axis-aligned rotations and their mirrors), a uniform scale and a shift.
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

import numpy as np


# =============================================================================
# FRAMES
# =============================================================================

AXIS_SWAP = np.array([[1.0, 0.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0],
                      [0.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 0.0, 1.0]])


def unity_points_to_o3de(points: np.ndarray) -> np.ndarray:
    """Unity (x, y, z) to O3DE (x, z, y)."""
    return np.asarray(points, dtype=np.float64)[:, [0, 2, 1]]


def unity_matrix_to_o3de(matrix: np.ndarray) -> np.ndarray:
    """The O3DE transform that does to O3DE points what ``matrix`` does to
    the same points in Unity axes."""
    return AXIS_SWAP @ matrix @ AXIS_SWAP


def prefab_frame(root_matrix: np.ndarray) -> np.ndarray:
    """The frame a prefab's content is measured in: the root's position and
    rotation taken out, its scale kept (plan D.9). Returns the matrix that
    brings a root-inclusive matrix into that frame."""
    _, rotation, _, _ = decompose(root_matrix)
    placement = np.identity(4)
    placement[:3, :3] = rotation
    placement[:3, 3] = root_matrix[:3, 3]
    return np.linalg.inv(placement)


# =============================================================================
# TRANSFORMS
# =============================================================================

def decompose(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """Split a 4x4 into ``(translation, rotation, scale, mirrored)``.

    ``scale`` is the length of each column and always positive. ``rotation``
    is the columns without their length; when the matrix mirrors (negative
    determinant) the X column is negated so that ``rotation`` is a proper
    rotation, and ``mirrored`` is True."""
    linear = matrix[:3, :3]
    scale = np.linalg.norm(linear, axis=0)
    safe = np.where(scale > 1e-12, scale, 1.0)
    rotation = linear / safe
    mirrored = bool(np.linalg.det(rotation) < 0.0)
    if mirrored:
        rotation = rotation.copy()
        rotation[:, 0] = -rotation[:, 0]
    return matrix[:3, 3].copy(), rotation, scale, mirrored


def rotation_angle_deg(rotation_a: np.ndarray, rotation_b: np.ndarray) -> float:
    """The angle of the rotation that turns one orientation into the other."""
    cosine = (np.trace(rotation_a.T @ rotation_b) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def transform_delta(expected: np.ndarray, actual: np.ndarray) -> dict:
    """How far ``actual`` is from ``expected``: position in millimetres,
    rotation in degrees, the largest scale ratio error, and whether one
    mirrors and the other does not. ``rotation_class`` names what kind of
    rotation error it is (see ``classify_rotation``)."""
    t_e, r_e, s_e, m_e = decompose(expected)
    t_a, r_a, s_a, m_a = decompose(actual)
    return {
        "position_mm":     float(np.linalg.norm(t_e - t_a) * 1000.0),
        "position_delta":  [float(v) for v in (t_a - t_e)],
        "rotation_deg":    rotation_angle_deg(r_e, r_a),
        "rotation_class":  classify_rotation(r_e, r_a),
        "scale_error":     float(np.max(np.abs(s_a / np.where(s_e > 1e-12, s_e, 1.0) - 1.0))),
        "expected_scale":  [float(v) for v in s_e],
        "actual_scale":    [float(v) for v in s_a],
        "mirror_mismatch": m_e != m_a,
    }


def classify_rotation(expected: np.ndarray, actual: np.ndarray, tolerance_deg: float = 0.5) -> str:
    """Name a rotation error:

    ``none``       the two agree;
    ``inverted``   ``actual`` is the inverse of ``expected`` (the rotation was
                   applied the wrong way round);
    ``<name>``     they differ by an axis-aligned rotation, e.g. ``rot Z 180``;
    ``other``      anything else."""
    if rotation_angle_deg(expected, actual) <= tolerance_deg:
        return "none"
    if rotation_angle_deg(expected.T, actual) <= tolerance_deg:
        return "inverted"
    difference = actual @ expected.T
    for candidate, name in SIGNED_PERMUTATIONS:
        if np.linalg.det(candidate) > 0 and rotation_angle_deg(candidate, difference) <= tolerance_deg:
            return name
    return "other"


# =============================================================================
# THE 48 SIGNED AXIS PERMUTATIONS
# =============================================================================

def _describe(matrix: np.ndarray) -> str:
    """A readable name for a signed axis permutation."""
    if np.linalg.det(matrix) < 0:
        # A mirror is "mirror X" followed by a rotation.
        rest = matrix @ np.diag([-1.0, 1.0, 1.0])
        rotation = _describe(rest)
        return "mirror X" if rotation == "identity" else f"mirror X then {rotation}"

    angle = np.degrees(np.arccos(np.clip((np.trace(matrix) - 1.0) / 2.0, -1.0, 1.0)))
    if angle < 1e-6:
        return "identity"
    if abs(angle - 180.0) < 1e-6:
        # The axis is the eigenvector of eigenvalue 1.
        values, vectors = np.linalg.eig(matrix)
        axis = np.real(vectors[:, np.argmin(np.abs(values - 1.0))])
    else:
        axis = np.array([matrix[2, 1] - matrix[1, 2], matrix[0, 2] - matrix[2, 0], matrix[1, 0] - matrix[0, 1]])
    axis = axis / np.max(np.abs(axis))
    axis = np.round(axis).astype(int)
    if abs(angle - 180.0) < 1e-6 and (axis < 0).any() and not (axis > 0).any():
        axis = -axis

    names = "XYZ"
    if np.count_nonzero(axis) == 1:
        index = int(np.flatnonzero(axis)[0])
        sign = "" if abs(angle - 180.0) < 1e-6 else ("+" if axis[index] > 0 else "-")
        return f"rot {names[index]} {sign}{angle:.0f}"
    return f"rot ({','.join(str(v) for v in axis)}) {angle:.0f}"


def _signed_permutations() -> List[Tuple[np.ndarray, str]]:
    found = []
    for order in itertools.permutations(range(3)):
        for signs in itertools.product((1.0, -1.0), repeat=3):
            matrix = np.zeros((3, 3))
            for row, (column, sign) in enumerate(zip(order, signs)):
                matrix[row, column] = sign
            found.append((matrix, _describe(matrix)))
    # Identity first, then rotations, then mirrors: the simplest fit wins a tie.
    found.sort(key=lambda item: (item[1] != "identity", np.linalg.det(item[0]) < 0, item[1]))
    return found


SIGNED_PERMUTATIONS = _signed_permutations()


# =============================================================================
# POINT SETS
# =============================================================================

def subsample(points: np.ndarray, limit: int, seed: int = 0) -> np.ndarray:
    """At most ``limit`` points, always the same ones for the same input."""
    if len(points) <= limit:
        return points
    picks = np.random.default_rng(seed).choice(len(points), size=limit, replace=False)
    return points[np.sort(picks)]


def nearest_distances(source: np.ndarray, target: np.ndarray, chunk: int = 256) -> np.ndarray:
    """For every point of ``source``, the distance to the nearest point of
    ``target``. Empty ``target`` gives infinity."""
    if len(source) == 0:
        return np.zeros(0)
    if len(target) == 0:
        return np.full(len(source), np.inf)
    nearest = np.empty(len(source))
    target_squared = np.einsum("ij,ij->i", target, target)
    for start in range(0, len(source), chunk):
        block = source[start:start + chunk]
        squared = (np.einsum("ij,ij->i", block, block)[:, None]
                   - 2.0 * block @ target.T + target_squared[None, :])
        nearest[start:start + chunk] = np.sqrt(np.maximum(squared.min(axis=1), 0.0))
    return nearest


def two_way_distance(points_a: np.ndarray, points_b: np.ndarray, limit: int = 4000) -> dict:
    """Largest and typical nearest distance between two point sets, both
    ways, in millimetres, and the share of points further than 1 mm.

    Above ``limit`` points the asking side is sampled; the side that answers
    is always whole, so sampling never makes two equal sets look apart."""
    if len(points_a) == 0 or len(points_b) == 0:
        return {"max_mm": float("inf"), "p95_mm": float("inf"), "mean_mm": float("inf"), "beyond_1mm": 1.0}
    both = np.concatenate([nearest_distances(subsample(points_a, limit), points_b),
                           nearest_distances(subsample(points_b, limit), points_a)])
    return {
        "max_mm":     float(both.max() * 1000.0),
        "p95_mm":     float(np.percentile(both, 95) * 1000.0),
        "mean_mm":    float(both.mean() * 1000.0),
        "beyond_1mm": float((both > 0.001).mean()),
    }


def nearest_neighbours(source: np.ndarray, target: np.ndarray, chunk: int = 256):
    """For every point of ``source``: the index of the nearest point of
    ``target`` and the distance to it."""
    indices = np.empty(len(source), dtype=np.int64)
    distances = np.empty(len(source))
    target_squared = np.einsum("ij,ij->i", target, target)
    for start in range(0, len(source), chunk):
        block = source[start:start + chunk]
        squared = (np.einsum("ij,ij->i", block, block)[:, None]
                   - 2.0 * block @ target.T + target_squared[None, :])
        indices[start:start + chunk] = squared.argmin(axis=1)
        distances[start:start + chunk] = np.sqrt(np.maximum(squared.min(axis=1), 0.0))
    return indices, distances


def noise_gate(expected: np.ndarray, tolerance_m: float) -> float:
    """How far a vertex may be from its partner and still be the same
    vertex: the tolerance, plus what mesh compression can move a vertex of a
    mesh this size (a few thousandths of its diagonal)."""
    diagonal = float(np.linalg.norm(box_size(expected))) if len(expected) else 0.0
    return tolerance_m + max(0.002, 0.004 * diagonal)


def fit_placement(actual: np.ndarray, expected: np.ndarray, gate_m: float, limit: int = 3000) -> dict:
    """Where ``actual`` sits relative to ``expected``, as a rigid motion
    fitted over all vertex pairs closer than ``gate_m``.

    ``offset_mm``     how far the fit moves the centre of ``actual``;
    ``rotation_deg``  how far it turns it;
    ``scale``         size of ``expected`` over size of ``actual``;
    ``matched``       share of vertices, of either set, with a partner inside
                      the gate (the smaller of the two directions);
    ``noise_mm``      what is left per vertex once the fit is taken out."""
    empty = {"offset_mm": float("inf"), "rotation_deg": float("inf"), "scale": 1.0,
             "matched": 0.0, "noise_mm": float("inf")}
    if len(actual) < 3 or len(expected) < 3:
        return empty

    sample = subsample(actual, limit)
    indices, distances = nearest_neighbours(sample, expected)
    inside = distances <= gate_m
    back = nearest_distances(subsample(expected, limit), actual) <= gate_m
    matched = float(min(inside.mean(), back.mean()))
    if inside.sum() < 3:
        return {**empty, "matched": matched}

    source, target = sample[inside], expected[indices[inside]]
    centre_s, centre_t = source.mean(axis=0), target.mean(axis=0)
    spread_s, spread_t = source - centre_s, target - centre_t

    # Kabsch: the rotation that best turns the source pairs onto the target pairs.
    u, _, vt = np.linalg.svd(spread_s.T @ spread_t)
    handed = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
    rotation = vt.T @ np.diag([1.0, 1.0, handed]) @ u.T
    shift = centre_t - rotation @ centre_s

    centre = actual.mean(axis=0)
    fitted = source @ rotation.T + shift
    size_s = float(np.sqrt((spread_s ** 2).sum()))
    return {
        "offset_mm":    float(np.linalg.norm(rotation @ centre + shift - centre) * 1000.0),
        "offset":       [float(v) for v in (rotation @ centre + shift - centre)],
        "rotation_deg": rotation_angle_deg(np.identity(3), rotation),
        "scale":        float(np.sqrt((spread_t ** 2).sum()) / size_s) if size_s > 1e-12 else 1.0,
        "matched":      matched,
        "noise_mm":     float(np.sqrt(((fitted - target) ** 2).sum(axis=1).mean()) * 1000.0),
    }


def box_center(points: np.ndarray) -> np.ndarray:
    return (points.min(axis=0) + points.max(axis=0)) / 2.0


def box_size(points: np.ndarray) -> np.ndarray:
    return points.max(axis=0) - points.min(axis=0)


# =============================================================================
# RESIDUAL
# =============================================================================

def find_residual(actual: np.ndarray, expected: np.ndarray, tolerance_m: float,
                  coarse: int = 300, fine: int = 1500) -> dict:
    """The correction that would bring ``actual`` onto ``expected``:
    ``corrected = scale * (Q @ point) + shift``.

    Tries each signed axis permutation ``Q``. The scale is the ratio of the
    two boxes' diagonals when they differ by more than two per cent, else 1.
    The shift lines the two boxes' centres up. The 48 candidates are ranked
    on a small sample, and the best few are then measured both ways against
    the whole sets.

    Returns ``{"found", "name", "scale", "shift", "left_mm", "left_p95_mm",
    "rotation"}``. ``found`` says the best candidate brings 95 per cent of
    the points within the tolerance; ``left_mm`` is the largest distance it
    still leaves (a few stray vertices keep that high without spoiling the
    fit)."""
    if len(actual) == 0 or len(expected) == 0:
        return {"found": False, "name": "no geometry", "scale": 1.0, "shift": [0.0, 0.0, 0.0],
                "left_mm": float("inf"), "left_p95_mm": float("inf"), "rotation": np.identity(3).tolist()}

    diagonal_a = float(np.linalg.norm(box_size(actual)))
    diagonal_e = float(np.linalg.norm(box_size(expected)))
    ratio = diagonal_e / diagonal_a if diagonal_a > 1e-9 else 1.0
    scale = ratio if abs(ratio - 1.0) > 0.02 else 1.0
    center_a, center_e = box_center(actual), box_center(expected)

    def corrected(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        return scale * (points @ matrix.T) + (center_e - scale * (matrix @ center_a))

    # ----- Rank all 48 on a small sample -------------------------------------
    sample_a, target_e = subsample(actual, coarse), subsample(expected, 3000, seed=1)
    ranked = sorted(range(len(SIGNED_PERMUTATIONS)),
                    key=lambda index: nearest_distances(corrected(sample_a, SIGNED_PERMUTATIONS[index][0]),
                                                        target_e).max())

    # ----- Measure the best few both ways ------------------------------------
    best = None
    for index in ranked[:4]:
        matrix, name = SIGNED_PERMUTATIONS[index]
        moved = corrected(actual, matrix)
        both = np.concatenate([nearest_distances(subsample(moved, fine), expected),
                               nearest_distances(subsample(expected, fine), moved)])
        candidate = {"p95": float(np.percentile(both, 95)), "left": float(both.max()),
                     "name": name, "matrix": matrix}
        if best is None or candidate["p95"] < best["p95"] - 1e-9:
            best = candidate

    # The boxes' centres carry the vertex noise of both sets. With the turn
    # known, the mean gap over the matched pairs gives the shift to the
    # precision the tolerance asks for.
    shift = center_e - scale * (best["matrix"] @ center_a)
    moved = scale * (subsample(actual, fine) @ best["matrix"].T) + shift
    indices, distances = nearest_neighbours(moved, expected)
    inside = distances <= tolerance_m
    if best["p95"] <= tolerance_m and inside.sum() >= 3:
        shift = shift + (expected[indices[inside]] - moved[inside]).mean(axis=0)

    return {
        "found":       bool(best["p95"] <= tolerance_m),
        "name":        best["name"],
        "scale":       float(scale),
        "shift":       [float(v) for v in shift],
        "left_mm":     best["left"] * 1000.0,
        "left_p95_mm": best["p95"] * 1000.0,
        "rotation":    best["matrix"].tolist(),
    }


def describe_residual(residual: dict, tolerance_m: float) -> str:
    """One readable line for a residual, e.g. ``rot Z 180 + shift (0.602,
    0, -0.448) m``. ``none`` when nothing needs correcting."""
    if not residual["found"]:
        return f"no axis-aligned correction fits (best leaves {residual['left_mm']:.1f} mm)"
    parts = []
    if residual["name"] != "identity":
        parts.append(residual["name"])
    if abs(residual["scale"] - 1.0) > 1e-6:
        parts.append(f"scale x{residual['scale']:.4g}")
    if np.linalg.norm(residual["shift"]) > tolerance_m:
        parts.append("shift (" + ", ".join(f"{v:.3f}" for v in residual["shift"]) + ") m")
    return " + ".join(parts) if parts else "none"


def residual_class(residual: dict, tolerance_m: float) -> str:
    """A residual without its numbers, for grouping: which kinds of
    correction it holds."""
    if not residual["found"]:
        return "unexplained"
    kinds = []
    if residual["name"] != "identity":
        kinds.append(residual["name"])
    if abs(residual["scale"] - 1.0) > 1e-6:
        kinds.append("scale")
    if np.linalg.norm(residual["shift"]) > tolerance_m:
        kinds.append("shift")
    return " + ".join(kinds) if kinds else "none"


# =============================================================================
# ANALYTIC COLLIDER SHAPES
# How far points are from the surface of a sphere or a capsule.
# =============================================================================

def sphere_surface_distances(points: np.ndarray, center, radius: float) -> np.ndarray:
    return np.abs(np.linalg.norm(points - np.asarray(center), axis=1) - radius)


def capsule_surface_distances(points: np.ndarray, end_a, end_b, radius: float) -> np.ndarray:
    """``end_a`` and ``end_b`` are the centres of the capsule's two caps."""
    end_a, end_b = np.asarray(end_a, dtype=np.float64), np.asarray(end_b, dtype=np.float64)
    axis = end_b - end_a
    length_squared = float(axis @ axis)
    if length_squared < 1e-18:
        return sphere_surface_distances(points, end_a, radius)
    along = np.clip((points - end_a) @ axis / length_squared, 0.0, 1.0)
    nearest_on_axis = end_a + along[:, None] * axis
    return np.abs(np.linalg.norm(points - nearest_on_axis, axis=1) - radius)
