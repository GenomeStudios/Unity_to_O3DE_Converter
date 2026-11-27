"""
=============================================================================
UNITY'S BUILT-IN MESHES  (platforms.unity.builtin_meshes)
=============================================================================

A cube, a quad or a plane made in the Unity editor (GameObject > 3D Object)
shows a mesh that is no file of the project: its reference names Unity's own
resources (``BUILTIN_MESH_GUID``) and a fixed id. There is nothing to copy,
so the converter makes the mesh itself and writes it as a Wavefront OBJ,
which the Asset Processor turns into a model like any other scene file.

Every mesh is made in Unity's own space (``mesh_asset.UnityMesh``) and
written by ``mesh_asset.write_obj``, which turns it into the engine's.

How close each one is to Unity's:

  - Quad, Plane, Cube, Cylinder: Unity's own vertices, normals and texture
    coordinates, made by rule (checked against the meshes Unity 2021.3
    hands out). The cylinder's side shows its texture twice around, as
    Unity's does.
  - Sphere, Capsule: the same size and the same lay of the texture, on the
    converter's own grid of vertices. Unity's two are smoothed cubes whose
    vertices follow no rule, so they are not reproduced point for point.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional, Tuple

from platforms.unity.mesh_asset import UnityMesh, write_obj

# The guid of Unity's default resources, which hold the built-in meshes.
BUILTIN_MESH_GUID = "0000000000000000e000000000000000"

# Unity's fixed file ids of its built-in meshes.
BUILTIN_MESH_NAMES = {
    "10202": "Cube",
    "10206": "Cylinder",
    "10207": "Sphere",
    "10208": "Capsule",
    "10209": "Plane",
    "10210": "Quad",
}

# The one material slot a built-in mesh has, as the model will name it.
BUILTIN_MATERIAL_LABEL = "UnityBuiltin"

# The built-in meshes without thickness. A collision mesh made of one cannot
# be a convex hull (a hull needs a volume): it is always a triangle mesh.
FLAT_MESHES = ("Plane", "Quad")

# The converter's own grid for the two meshes it does not copy from Unity.
ROUND_SEGMENTS = 24          # around the axis
ROUND_RINGS = 8              # from a pole to the equator


# =============================================================================
# WRITING
# =============================================================================

def builtin_mesh_node_path(mesh_file: Path) -> str:
    """The path of the mesh in the scene graph O3DE makes of a file
    ``write_builtin_mesh`` wrote, for the node selection of its mesh group.

    The top node of an OBJ is not ``RootNode`` as in an FBX: the importer
    names it after the file and SceneAPI makes that a valid name by turning
    the dot into an underscore (read off the Asset Processor's job log). The
    mesh below it carries the name of the file's ``o`` line."""
    mesh_file = Path(mesh_file)
    return f"{mesh_file.name.replace('.', '_')}.{mesh_file.stem.split('_', 1)[-1]}"


def write_builtin_mesh(mesh_file_id: str, folder: Path) -> Optional[Path]:
    """Write the built-in mesh with this Unity file id into ``folder`` as
    ``UnityBuiltin_<Name>.obj`` and return its path; None for an id that
    names no built-in mesh (see ``BUILTIN_MESH_NAMES``)."""
    mesh = builtin_mesh(mesh_file_id)
    if mesh is None:
        return None
    return write_obj(mesh, Path(folder) / f"UnityBuiltin_{mesh.name}.obj",
                     object_name=mesh.name, labels=[BUILTIN_MATERIAL_LABEL])


def builtin_mesh(mesh_file_id: str) -> Optional[UnityMesh]:
    """The built-in mesh with this Unity file id, in Unity's space; None for
    an id that names none."""
    make = _MAKERS.get(BUILTIN_MESH_NAMES.get(str(mesh_file_id), ""))
    return make() if make else None


# =============================================================================
# THE FLAT ONES
# =============================================================================

def _quad() -> UnityMesh:
    """One metre square in the XY plane, facing -Z, the texture upright."""
    mesh = _empty("Quad")
    _add_flat_sheet(mesh, origin=(-0.5, -0.5, 0.0), along_u=(1.0, 0.0, 0.0), along_v=(0.0, 1.0, 0.0), cells=1)
    return mesh


def _plane() -> UnityMesh:
    """Ten metres square in the XZ plane, facing up, ten cells a side. The
    texture starts at the +X +Z corner and runs towards -X and -Z."""
    mesh = _empty("Plane")
    _add_flat_sheet(mesh, origin=(5.0, 0.0, 5.0), along_u=(-10.0, 0.0, 0.0), along_v=(0.0, 0.0, -10.0), cells=10)
    return mesh


# The cube's faces: where the texture's U and V run on each. The face looks
# along ``along_v x along_u``.
_CUBE_FACES = (
    ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),        # +Z
    ((-1.0, 0.0, 0.0), (0.0, 0.0, -1.0)),       # +Y
    ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),       # -Z
    ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),        # -Y
    ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),        # -X
    ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),         # +X
)


def _cube() -> UnityMesh:
    """One metre on a side, centred on its origin, four vertices to a face
    so every face has its own normal and the whole of the texture."""
    mesh = _empty("Cube")
    for along_u, along_v in _CUBE_FACES:
        normal = _cross(along_v, along_u)
        origin = tuple(0.5 * (n - u - v) for n, u, v in zip(normal, along_u, along_v))
        _add_flat_sheet(mesh, origin, along_u, along_v, cells=1)
    return mesh


# =============================================================================
# THE ROUND ONES
# =============================================================================

def _cylinder() -> UnityMesh:
    """Half a metre in radius, two metres tall along Y, twenty sides. Unity
    wraps the texture around each half of the side, so it shows twice; the
    caps show a disc cut from the middle of it."""
    mesh = _empty("Cylinder")
    radius, sides = 0.5, 20

    def rim(angle: float, height: float) -> Tuple[float, float, float]:
        return (0.0 - radius * math.cos(angle), height, 0.0 - radius * math.sin(angle))

    for half in (0.0, 1.0):                     # from -X by -Z to +X, then on by +Z to -X
        def side(u: float, v: float, half=half):
            angle = (half + u) * math.pi
            return rim(angle, 2.0 * v - 1.0), (0.0 - math.cos(angle), 0.0, 0.0 - math.sin(angle)), (u, v)
        _add_sheet(mesh, columns=sides // 2, rows=1, point=side)

    def top(u: float, v: float):
        x, y, z = rim(0.0 - u * 2.0 * math.pi, 1.0) if v else (0.0, 1.0, 0.0)
        return (x, y, z), (0.0, 1.0, 0.0), (0.5 - x, 0.5 - z)

    def bottom(u: float, v: float):
        x, y, z = rim(u * 2.0 * math.pi, -1.0) if v else (0.0, -1.0, 0.0)
        return (x, y, z), (0.0, -1.0, 0.0), (0.5 + x, 0.5 - z)

    _add_sheet(mesh, columns=sides, rows=1, point=top)
    _add_sheet(mesh, columns=sides, rows=1, point=bottom)
    return mesh


def _sphere() -> UnityMesh:
    """Half a metre in radius. The texture wraps once around Y, starting at
    -X and running by -Z, and from the bottom pole to the top."""
    mesh = _empty("Sphere")
    radius = 0.5

    def point(u: float, v: float):
        around, up = 2.0 * math.pi * u, math.pi * (v - 0.5)
        normal = (0.0 - math.cos(up) * math.cos(around), math.sin(up), 0.0 - math.cos(up) * math.sin(around))
        return tuple(radius * value for value in normal), normal, (u, v)

    _add_sheet(mesh, columns=ROUND_SEGMENTS, rows=2 * ROUND_RINGS, point=point)
    return mesh


def _capsule() -> UnityMesh:
    """Half a metre in radius, two metres tall along Y: two half spheres a
    metre apart. The texture wraps once around Y, starting at +X and running
    by +Z, and runs evenly with the height."""
    mesh = _empty("Capsule")
    radius, half_height = 0.5, 0.5
    rows = 2 * ROUND_RINGS + 1                  # the rings of both halves, and the straight band between

    def point(u: float, v: float):
        row = round(v * rows)
        if row <= ROUND_RINGS:                  # the lower half sphere, from its pole up to its rim
            up, centre = (row / ROUND_RINGS - 1.0) * math.pi / 2.0, 0.0 - half_height
        else:                                   # the upper one, from its rim up to its pole
            up, centre = (row - ROUND_RINGS - 1) / ROUND_RINGS * math.pi / 2.0, half_height
        around = 2.0 * math.pi * u
        normal = (math.cos(up) * math.cos(around), math.sin(up), math.cos(up) * math.sin(around))
        x, y, z = radius * normal[0], radius * normal[1] + centre, radius * normal[2]
        return (x, y, z), normal, (u, (y + 1.0) / 2.0)

    _add_sheet(mesh, columns=ROUND_SEGMENTS, rows=rows, point=point)
    return mesh


_MAKERS = {"Cube": _cube, "Cylinder": _cylinder, "Sphere": _sphere, "Capsule": _capsule,
           "Plane": _plane, "Quad": _quad}


# =============================================================================
# SHEETS
# Every surface here is a sheet of cells laid over it: a flat one for a face,
# a rolled one for a side, one drawn together at an edge for a cap or a pole.
# =============================================================================

def _empty(name: str) -> UnityMesh:
    return UnityMesh(name=name, positions=[], normals=[], uvs=[], sub_meshes=[[]])


def _add_sheet(mesh: UnityMesh, columns: int, rows: int, point: Callable) -> None:
    """Add a sheet of ``columns`` by ``rows`` cells to ``mesh``.

    ``point(u, v)`` gives the position, the normal and the texture
    coordinate at ``u``, ``v`` (each from 0 to 1). Seen from its front, the
    sheet has U running to the right and V up, as a texture has; that makes
    Unity's clockwise triangles. A cell whose corners fall together (the
    middle of a cap, a pole) gives one triangle instead of two."""
    first = len(mesh.positions)
    for row in range(rows + 1):
        for column in range(columns + 1):
            position, normal, uv = point(column / columns, row / rows)
            mesh.positions.append(_tidy(position))      # tidied, so corners that meet are the same point
            mesh.normals.append(_tidy(normal))
            mesh.uvs.append(_tidy(uv))

    for row in range(rows):
        for column in range(columns):
            low_left = first + row * (columns + 1) + column
            low_right, up_left, up_right = low_left + 1, low_left + columns + 1, low_left + columns + 2
            for triangle in ((low_left, up_left, up_right), (low_left, up_right, low_right)):
                if len({mesh.positions[corner] for corner in triangle}) == 3:
                    mesh.sub_meshes[0].extend(triangle)


def _add_flat_sheet(mesh: UnityMesh, origin, along_u, along_v, cells: int) -> None:
    """Add a flat sheet of ``cells`` by ``cells`` cells: its texture starts
    at ``origin`` and runs the whole of ``along_u`` and ``along_v``. It
    faces along ``along_v x along_u``."""
    facing = _cross(along_v, along_u)
    length = math.sqrt(sum(value * value for value in facing))
    normal = tuple(value / length for value in facing)

    def point(u: float, v: float):
        return tuple(o + u * a + v * b for o, a, b in zip(origin, along_u, along_v)), normal, (u, v)

    _add_sheet(mesh, cells, cells, point)


def _tidy(values) -> tuple:
    """Numbers without the noise of the sines and cosines they came from,
    and without a minus sign on a zero."""
    return tuple(round(value, 7) + 0.0 for value in values)


def _cross(a, b) -> Tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
