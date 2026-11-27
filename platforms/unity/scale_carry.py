"""
=============================================================================
A SCALE BY AXIS, CARRIED DOWN  (platforms.unity.scale_carry)
=============================================================================

Unity scales everything below an object with the object, whatever the scale.
O3DE passes a uniform scale down; a scale that differs by axis lives in a
component on the one entity (``EditorNonUniformScaleComponent``) and reaches
nothing below it. A bridge whose boards hang under a stretched object keeps
its boards at their own size and at their unscaled places.

So the converter carries such a scale down itself, before anything is
written: every object below gets its place scaled, and its own scale
multiplied by what it inherits. The pass rewrites the parsed objects'
transforms; the writers then treat each object as they always did.

A scale by axis is two things, and they are carried apart:

  - a mirror (the signs). An object below a mirror is the mirror image of
    itself: its rotation turns over, and it is mirrored along the same axes
    of its own. That is exact however the object is turned.
  - a stretch (the magnitudes). Along each of the object's own axes it
    stretches by the length that axis has once scaled. For an object turned
    by quarter turns that is the stretch with its axes swapped, and exact.
    For one turned otherwise the stretch makes a skew, which no entity's
    position, rotation and scale can hold: the object gets the right place
    and the right size along each of its own axes, without the skew, and is
    reported.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Optional, Tuple

import matrix3
from platforms.unity.types import Transform

# Scales within this of each other count as one.
SAME = 1e-4

ONE = (1.0, 1.0, 1.0)


# =============================================================================
# THE PASS
# =============================================================================

def carry_scales_down(game_objects: Dict, warn: Optional[Callable[[str], None]] = None) -> int:
    """Carry every scale that differs by axis down to the objects below it,
    rewriting their transforms in place. ``game_objects`` is ``{file id:
    GameObject}`` with parents and children resolved. Returns the number of
    objects whose transform changed.

    A placed prefab below such an object gets its place scaled; what it
    inherits is noted on it as ``component_data["inherited_scale"]``, for
    the writer of its scale (``prefab_writer.instance_scale_patches``)."""
    changed = 0
    roots = [go for go in game_objects.values() if not go.parent_id or go.parent_id not in game_objects]
    pending = [(go, ONE) for go in roots]
    visited = set()
    while pending:
        go, inherited = pending.pop()
        if go.file_id in visited:                       # a hierarchy that loops is not followed
            continue
        visited.add(go.file_id)

        if not _is_one(inherited):
            rotation, factors, skewed = handed_down(go.transform.rotation, inherited)
            position = tuple(value * factor for value, factor in zip(go.transform.position, inherited))
            if go.is_prefab_instance:
                # A placed prefab's scale is written from its overrides and
                # its prefab's own scale; what it inherits goes with it.
                go.component_data["inherited_scale"] = factors
                scale = go.transform.scale
            else:
                scale = tuple(own * factor for own, factor in zip(go.transform.scale, factors))
            if skewed and warn:
                warn(f"'{go.name}' is turned inside a frame scaled {_text(inherited)}: that skews it, "
                     f"which O3DE cannot hold. It keeps its place and its size along its own axes.")
            go.transform = Transform(position, rotation, scale)
            changed += 1

        # What this object hands on: its whole scale when that differs by
        # axis (the engine passes none of it down), nothing when it is one
        # scale for all axes (the engine passes that down itself).
        own = go.transform.scale if not go.is_prefab_instance else ONE
        hands_on = ONE if _is_uniform(own) else tuple(own)
        for child_id in go.children_ids:
            if child_id in game_objects:
                pending.append((game_objects[child_id], hands_on))
    return changed


# =============================================================================
# ONE OBJECT
# =============================================================================

def carried_transform(transform: Transform, inherited: Tuple[float, float, float]) -> Tuple[Transform, bool]:
    """An object's transform with the scale ``inherited`` from above worked
    in (given along the axes of the object's parent), and whether that left
    a skew out."""
    rotation, factors, skewed = handed_down(transform.rotation, inherited)
    position = tuple(value * factor for value, factor in zip(transform.position, inherited))
    scale = tuple(own * factor for own, factor in zip(transform.scale, factors))
    return Transform(position, rotation, scale), skewed


def handed_down(rotation, inherited) -> Tuple[tuple, Tuple[float, float, float], bool]:
    """What a scale ``inherited`` along its parent's axes does to an object
    turned by ``rotation`` (a quaternion): the object's rotation afterwards,
    the factor on each axis of its own scale, and whether a skew was left
    out. The mirror goes first, then the stretch (see the module's notes)."""
    mirror = tuple(-1.0 if value < 0.0 else 1.0 for value in inherited)
    turned = mirrored_rotation(rotation, mirror)
    stretch, skewed = scale_in_own_axes(turned, tuple(abs(value) for value in inherited))
    return turned, tuple(sign * factor for sign, factor in zip(mirror, stretch)), skewed


def mirrored_rotation(rotation, mirror) -> tuple:
    """A rotation seen in a mirror. ``mirror`` holds -1 for every mirrored
    axis of the frame the rotation is given in, 1 for the others.

    With M the mirror and R the rotation, ``M R = (M R M) M``: the object
    turned by R and then mirrored is the object mirrored along the same
    axes of its own and then turned by ``M R M``. That rotation turns about
    the mirrored axis; through one mirror, the other way round."""
    x, y, z, w = rotation
    turns_over = mirror[0] * mirror[1] * mirror[2]      # -1 for one or three mirrored axes
    return (turns_over * mirror[0] * x, turns_over * mirror[1] * y, turns_over * mirror[2] * z, w)


def scale_in_own_axes(rotation, inherited) -> Tuple[Tuple[float, float, float], bool]:
    """A scale given along a parent's axes, as the stretch along each axis
    of an object turned by ``rotation`` (a quaternion), and whether the
    object is turned in a way that makes it a skew."""
    turn = matrix3.quat_to_matrix(rotation)
    along = []
    aligned = True
    for axis in range(3):
        column = [turn[row][axis] for row in range(3)]
        row_of_axis = max(range(3), key=lambda row: abs(column[row]))
        if abs(column[row_of_axis]) > 1.0 - 1e-6:
            # The axis lies along one of the parent's: that one's scale, sign and all.
            along.append(inherited[row_of_axis])
        else:
            along.append(math.sqrt(sum((inherited[row] * column[row]) ** 2 for row in range(3))))
            aligned = False
    return tuple(along), not aligned and not _is_uniform(inherited)


# =============================================================================
# HELPERS
# =============================================================================

def _is_uniform(scale) -> bool:
    return max(scale) - min(scale) < SAME


def _is_one(scale) -> bool:
    return all(abs(value - 1.0) < SAME for value in scale)


def _text(scale) -> str:
    return "(" + ", ".join(f"{value:.3g}" for value in scale) + ")"
