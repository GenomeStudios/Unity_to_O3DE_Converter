"""
=============================================================================
UNITY'S BUILT-IN MESHES  (platforms.unity.builtin_meshes)
=============================================================================

A cube made in the Unity editor (GameObject > 3D Object > Cube) shows a mesh
that is no file of the project: its reference names Unity's own resources
(``BUILTIN_MESH_GUID``) and a fixed id. There is nothing to copy, so the
converter writes the mesh itself, as a Wavefront OBJ the Asset Processor
turns into a model like any other scene file.

Only the cube is written so far. It is the same under every turn that maps
the axes onto each other, so it does not matter how the scene pipeline
orients an OBJ. The other built-in meshes (sphere, capsule, cylinder, plane,
quad) are not: they wait for that to be measured, and a renderer that shows
one is reported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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
    ``UnityBuiltin_<Name>.obj`` and return its path; None for a mesh this
    module does not write (see ``BUILTIN_MESH_NAMES`` for the names)."""
    if BUILTIN_MESH_NAMES.get(str(mesh_file_id)) != "Cube":
        return None
    path = Path(folder) / "UnityBuiltin_Cube.obj"
    path.write_text(_cube_obj(), encoding="ascii")
    return path


def _cube_obj() -> str:
    """Unity's cube: one metre on a side, centred on its origin, four
    vertices to a face so every face has its own normal and the whole of the
    texture. Faces wind counter-clockwise seen from outside."""
    lines = ["# Unity's built-in Cube, written by the Unity to O3DE converter.",
             "# One metre on a side, centred on the origin.",
             "o Cube"]
    faces = []
    # Each face: its normal n, and two edge directions u, v with u x v = n.
    for axis in range(3):
        for sign in (1.0, -1.0):
            normal = [0.0, 0.0, 0.0]
            normal[axis] = sign
            u, v = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
            u[(axis + 1) % 3] = sign
            v[(axis + 2) % 3] = 1.0
            corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
            faces.append((normal, [[0.5 * (normal[i] + a * u[i] + b * v[i]) for i in range(3)] for a, b in corners]))

    for _, corners in faces:
        lines += ["v %.6f %.6f %.6f" % tuple(corner) for corner in corners]
    lines += ["vt 0.000000 0.000000", "vt 1.000000 0.000000", "vt 1.000000 1.000000", "vt 0.000000 1.000000"]
    lines += ["vn %.6f %.6f %.6f" % tuple(normal) for normal, _ in faces]
    lines.append(f"usemtl {BUILTIN_MATERIAL_LABEL}")
    for index in range(len(faces)):
        first = 4 * index + 1
        lines.append("f " + " ".join(f"{first + corner}/{corner + 1}/{index + 1}" for corner in range(4)))
    return "\n".join(lines) + "\n"
