"""
=============================================================================
UNITY → O3DE COORDINATE CORRECTION  (platforms.unity.coordinates)
=============================================================================

The quaternion needed to correct a Y-up Unity-style FBX import into
O3DE's Z-up render space. Promoted from the O3DE assetinfo writer
so the constant lives with its source-platform owner (Unity is the
one that produces Y-up content; O3DE is the one that consumes Z-up
content).

The assetinfo writer (``targets.o3de.assetinfo_writer.write_fbx_assetinfo``)
now accepts a ``correction_quat`` parameter. ``UnityPlatform`` passes
``UNITY_Y_UP_TO_O3DE_Z_UP_QUAT`` from this module; other plugins
(Unreal, Godot, …) supply their own correction quaternion if their
source axes differ from O3DE's.

Numeric details
---------------
The quaternion represents a +90° rotation around the X axis, which
maps Unity's left-handed Y-up basis to O3DE's right-handed Z-up
basis when combined with the converter's per-axis swizzle. The
floating-point components are pinned to match the values the legacy
hard-coded constant has carried since the converter's bootstrap.

Backwards compatibility
-----------------------
``targets.o3de.assetinfo_writer.Y_UP_ROTATION`` continues to alias
``UNITY_Y_UP_TO_O3DE_Z_UP_QUAT`` so any tooling that imported the
old name keeps working. The writer's ``correction_quat`` defaults
to the same value when no platform-supplied quaternion is passed.
"""

from typing import List


# 90° rotation around X — Unity Y-up → O3DE Z-up.
# Component order is [x, y, z, w] (matches the O3DE
# CoordinateSystemRule's rotation field convention).
UNITY_Y_UP_TO_O3DE_Z_UP_QUAT: List[float] = [
    0.7071067690849304,
    0.0,
    0.0,
    0.7071067094802856,
]


# Convenience alias for code that wants to read the source-side axis
# convention as a string. Mirrors `UnityPlatform.UP_AXIS`.
SOURCE_UP_AXIS    = "Y"
SOURCE_HANDEDNESS = "LH"
