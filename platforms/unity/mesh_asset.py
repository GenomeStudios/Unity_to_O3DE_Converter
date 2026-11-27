"""
=============================================================================
UNITY MESH ASSETS  (platforms.unity.mesh_asset)
=============================================================================

A mesh does not have to come from a model file. Unity can store one on its
own, as an ``.asset`` file that holds a single ``Mesh`` object: a tree whose
best level of detail was baked in the editor, a mesh a tool generated. A
renderer names it like any other mesh, by the file's guid.

O3DE has no importer for that file. The converter reads it and writes the
mesh out as a Wavefront OBJ, which the Asset Processor turns into a model
like any other scene file.

What is read: the text form of the asset (``%YAML``), with its vertex data
uncompressed and in one stream - what Unity writes for a readable mesh when
the project serialises assets as text. Positions, normals, the first UV set
and the triangles of every sub-mesh are taken; tangents, vertex colours and
further UV sets are not (an OBJ has no place for them). A binary asset, a
compressed mesh or a sub-mesh that is not made of triangles is refused, and
the caller reports it.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


# =============================================================================
# THE MESH
# =============================================================================

@dataclass
class UnityMesh:
    """One Unity mesh, in Unity's own space: metres, Y up, left-handed,
    triangles wound clockwise seen from the front."""
    name:      str
    positions: List[Tuple[float, float, float]]
    normals:   List[Tuple[float, float, float]] = field(default_factory=list)   # empty or one per vertex
    uvs:       List[Tuple[float, float]] = field(default_factory=list)          # empty or one per vertex
    # One list of vertex indices per sub-mesh, three to a triangle. A
    # renderer's materials pair with the sub-meshes in order.
    sub_meshes: List[List[int]] = field(default_factory=list)


# The label the model gives the material slot of sub-mesh ``index``.
def material_label(index: int) -> str:
    return f"SubMesh{index}"


# =============================================================================
# READING
# =============================================================================

# Unity's vertex attribute formats that hold a real number, with their
# ``struct`` code and size in bytes: 32-bit and 16-bit floats.
_FLOAT_FORMATS = {0: ("f", 4), 1: ("e", 2)}

# Where the first UV set sits among a mesh's channels. Unity 2018.2 and later
# write fourteen channels (position, normal, tangent, colour, UV 0..7, ...),
# earlier versions eight (position, normal, colour, UV 0..3, tangent).
_UV_CHANNEL = {14: 4, 8: 3}

_TRIANGLES = 0          # a sub-mesh's ``topology``


def read_mesh_asset(asset_file: Path) -> Optional[UnityMesh]:
    """The mesh a Unity ``.asset`` file holds, or None when the file is not
    a mesh this module reads (see the module's notes)."""
    try:
        text = Path(asset_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None                                     # binary, or not there
    if not text.startswith("%YAML") or "\nMesh:\n" not in text:
        return None
    if _number(text, "m_MeshCompression") != 0:
        return None

    # ----- Vertices --------------------------------------------------------
    vertex_count = _number(text, "m_VertexCount")
    data = _hex(text, "_typelessdata")
    channels = [tuple(int(value) for value in match) for match in re.findall(
        r"- stream: (\d+)\s+offset: (\d+)\s+format: (\d+)\s+dimension: (\d+)", text)]
    if not vertex_count or not data or len(data) % vertex_count or len(channels) not in _UV_CHANNEL:
        return None
    if any(stream != 0 for stream, _, _, dimension in channels if dimension & 0xF):
        return None                                     # more than one stream
    stride = len(data) // vertex_count

    def channel(index: int, size: int) -> list:
        """The values of one channel, ``size`` numbers per vertex; empty
        when the mesh has no such channel or keeps it in another form."""
        _, offset, number_format, dimension = channels[index]
        if (dimension & 0xF) < size or number_format not in _FLOAT_FORMATS:
            return []
        code, width = _FLOAT_FORMATS[number_format]
        reader = struct.Struct("<" + code * size)
        if offset + width * size > stride:
            return []
        return [reader.unpack_from(data, vertex * stride + offset) for vertex in range(vertex_count)]

    positions = channel(0, 3)
    if not positions:
        return None

    # ----- Triangles ---------------------------------------------------------
    index_bytes = _hex(text, "m_IndexBuffer")
    index_code, index_width = ("<I", 4) if _number(text, "m_IndexFormat") == 1 else ("<H", 2)
    sub_meshes = []
    for block in re.findall(r"- serializedVersion: \d+\s+firstByte: (\d+)\s+indexCount: (\d+)\s+topology: (\d+)"
                            r"(?:\s+baseVertex: (\d+))?", text):
        first_byte, index_count, topology, base_vertex = (int(value or 0) for value in block)
        if topology != _TRIANGLES or first_byte + index_count * index_width > len(index_bytes):
            return None
        indices = [struct.unpack_from(index_code, index_bytes, first_byte + position * index_width)[0] + base_vertex
                   for position in range(index_count)]
        if any(index >= vertex_count for index in indices):
            return None
        sub_meshes.append(indices)
    if not sub_meshes:
        return None

    name = re.search(r"^  m_Name: (.*)$", text, re.M)
    return UnityMesh(
        name=(name.group(1).strip() if name else "") or Path(asset_file).stem,
        positions=positions,
        normals=channel(1, 3),
        uvs=channel(_UV_CHANNEL[len(channels)], 2),
        sub_meshes=sub_meshes,
    )


def _number(text: str, key: str) -> int:
    """The first whole number stored under ``key``; 0 when there is none."""
    match = re.search(rf"^\s*{key}: (-?\d+)\s*$", text, re.M)
    return int(match.group(1)) if match else 0


def _hex(text: str, key: str) -> bytes:
    """The bytes stored as hexadecimal text under ``key``."""
    match = re.search(rf"^\s*{key}: ([0-9a-fA-F]*)\s*$", text, re.M)
    try:
        return bytes.fromhex(match.group(1)) if match else b""
    except ValueError:
        return b""


# =============================================================================
# WRITING
# =============================================================================

def obj_node_path(obj_file: Path) -> str:
    """The path of the mesh in the scene graph O3DE makes of a file
    ``write_obj`` wrote, for the node selection of its mesh group: the top
    node is named after the file with its dot turned into an underscore, the
    mesh below it after the file's ``o`` line."""
    obj_file = Path(obj_file)
    return f"{obj_file.name.replace('.', '_')}.{obj_file.stem}"


def write_obj(mesh: UnityMesh, obj_file: Path, object_name: Optional[str] = None,
              labels: Optional[List[str]] = None) -> Path:
    """Write ``mesh`` as a Wavefront OBJ and return the file.

    The engine reads an OBJ as Y up and right-handed and turns it into its
    own space: a file point ``(x, y, z)`` becomes the engine's
    ``(-x, z, y)``. (Measured on the NatureManufacture bed: written in the
    engine's own axes, every such model came out turned half round about
    the diagonal of Y and Z.) The converter maps a Unity point ``(x, y, z)``
    to the engine's ``(x, z, y)``, so the file holds ``(-x, y, z)``: Unity's
    own coordinates with X mirrored, which is how a left-handed Y-up mesh is
    written into a right-handed Y-up file. A mirror turns a triangle's
    winding around, so the corners of each triangle are written in reverse.

    Every sub-mesh is one material group, labelled ``material_label(n)``,
    or by ``labels`` when given. The object is named after the file, so
    ``obj_node_path`` finds it, or ``object_name`` when given."""
    has_normals = len(mesh.normals) == len(mesh.positions)
    has_uvs = len(mesh.uvs) == len(mesh.positions)

    lines = [f"# {mesh.name}: a Unity mesh, written by the Unity to O3DE converter.",
             f"o {object_name or Path(obj_file).stem}"]
    lines += ["v %.6f %.6f %.6f" % (0.0 - x, y, z) for x, y, z in mesh.positions]
    if has_uvs:
        lines += ["vt %.6f %.6f" % (u, v) for u, v in mesh.uvs]
    if has_normals:
        lines += ["vn %.6f %.6f %.6f" % (0.0 - x, y, z) for x, y, z in mesh.normals]

    def corner(index: int) -> str:
        number = index + 1                              # OBJ counts from one
        if has_uvs and has_normals:
            return f"{number}/{number}/{number}"
        if has_uvs:
            return f"{number}/{number}"
        return f"{number}//{number}" if has_normals else str(number)

    for sub_mesh, indices in enumerate(mesh.sub_meshes):
        lines.append(f"usemtl {labels[sub_mesh] if labels else material_label(sub_mesh)}")
        for first in range(0, len(indices) - 2, 3):
            a, b, c = indices[first:first + 3]
            lines.append(f"f {corner(a)} {corner(c)} {corner(b)}")

    obj_file = Path(obj_file)
    obj_file.write_text("\n".join(lines) + "\n", encoding="ascii")
    return obj_file
