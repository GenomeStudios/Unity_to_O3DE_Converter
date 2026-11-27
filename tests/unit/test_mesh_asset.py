"""Unit tests for Unity mesh assets (nature_pack I.4).

Nineteen trees of the NatureManufacture pack take their best level of detail
from a mesh stored on its own in an ``.asset`` file, not from a model file.
The converter reads the mesh and writes it as an OBJ:

  - positions, normals, the first UV set and each sub-mesh's triangles are
    read from the asset's text form, for both channel layouts Unity has used;
  - the OBJ holds Unity's coordinates with X mirrored, the corners of each
    triangle turned around, and one material group per sub-mesh;
  - a file that is no such mesh is refused, not guessed at.
"""

import struct
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.mesh_asset import material_label, obj_node_path, read_mesh_asset, write_obj


# =============================================================================
# FIXTURES
# A square in Unity's XY plane, facing -Z, in two sub-meshes of one triangle.
# =============================================================================

POSITIONS = [(0.0, 0.0, 0.5), (0.0, 2.0, 0.5), (1.0, 2.0, 0.5), (1.0, 0.0, 0.5)]
NORMAL = (0.0, 0.0, -1.0)
UVS = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
TRIANGLES = [[0, 1, 2], [0, 2, 3]]              # clockwise seen from -Z, Unity's front


def _asset_text(layout: int = 14, compression: int = 0, topology: int = 0, wide_indices: bool = False) -> str:
    """The text of a mesh asset holding the square. ``layout`` is the number
    of channels: 14 as Unity 2018.2 and later write them (position, normal,
    tangent, colour, UV 0, ...), 8 as earlier versions did (position,
    normal, colour, UV 0, ...)."""
    # Per vertex: position (12 bytes), normal (12), colour (4), UV (8).
    vertices = b"".join(struct.pack("<3f3f4B2f", *position, *NORMAL, 255, 255, 255, 255, *uv)
                        for position, uv in zip(POSITIONS, UVS))
    used = {0: (0, 0, 3), 1: (12, 0, 3), (3 if layout == 14 else 2): (24, 2, 4), (4 if layout == 14 else 3): (28, 0, 2)}
    channels = ""
    for index in range(layout):
        offset, number_format, dimension = used.get(index, (0, 0, 0))
        channels += f"    - stream: 0\n      offset: {offset}\n      format: {number_format}\n      dimension: {dimension}\n"
    code, width = ("<I", 4) if wide_indices else ("<H", 2)
    indices = b"".join(struct.pack(code, index) for triangle in TRIANGLES for index in triangle)
    sub_meshes = "".join(
        f"  - serializedVersion: 2\n    firstByte: {3 * width * number}\n    indexCount: 3\n    topology: {topology}\n"
        f"    baseVertex: 0\n    firstVertex: 0\n    vertexCount: 4\n" for number in range(len(TRIANGLES)))
    return ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n--- !u!43 &4300000\nMesh:\n  m_Name: Square\n"
            "  serializedVersion: 10\n  m_SubMeshes:\n" + sub_meshes +
            f"  m_MeshCompression: {compression}\n  m_IndexFormat: {1 if wide_indices else 0}\n"
            f"  m_IndexBuffer: {indices.hex()}\n  m_VertexData:\n    serializedVersion: 3\n    m_VertexCount: 4\n"
            "    m_Channels:\n" + channels + f"    m_DataSize: {len(vertices)}\n    _typelessdata: {vertices.hex()}\n")


def _read(text: str):
    with tempfile.TemporaryDirectory() as folder:
        asset = Path(folder) / "Square.asset"
        asset.write_text(text, encoding="utf-8")
        return read_mesh_asset(asset)


# =============================================================================
# READING
# =============================================================================

def test_the_mesh_is_read_as_unity_holds_it():
    mesh = _read(_asset_text())
    assert mesh.name == "Square"
    assert mesh.positions == POSITIONS and mesh.uvs == UVS
    assert mesh.normals == [NORMAL] * 4
    assert mesh.sub_meshes == TRIANGLES


def test_the_older_channel_layout_keeps_its_uvs_one_place_earlier():
    mesh = _read(_asset_text(layout=8))
    assert mesh.positions == POSITIONS and mesh.uvs == UVS


def test_wide_indices_are_read():
    assert _read(_asset_text(wide_indices=True)).sub_meshes == TRIANGLES


def test_what_is_no_readable_mesh_is_refused():
    assert _read(_asset_text(compression=1)) is None, "a compressed mesh keeps its vertices packed elsewhere"
    assert _read(_asset_text(topology=3)) is None, "lines are no triangles"
    assert _read("%YAML 1.1\n--- !u!114 &11400000\nMonoBehaviour:\n  m_Name: Settings\n") is None
    with tempfile.TemporaryDirectory() as folder:
        binary = Path(folder) / "Binary.asset"
        binary.write_bytes(b"\x00\x01\xff\xfe binary serialised asset")
        assert read_mesh_asset(binary) is None
        assert read_mesh_asset(Path(folder) / "Missing.asset") is None


# =============================================================================
# WRITING
# =============================================================================

def _written(mesh) -> list:
    with tempfile.TemporaryDirectory() as folder:
        return write_obj(mesh, Path(folder) / "Square.obj").read_text(encoding="ascii").splitlines()


def test_the_obj_holds_unitys_coordinates_with_x_mirrored_and_each_triangle_turned_around():
    """The engine reads an OBJ as Y up and right-handed: its (x, y, z) ends
    up at (-x, z, y), which is where the converter puts Unity's (x, y, z)
    when the file holds (-x, y, z)."""
    lines = _written(_read(_asset_text()))
    assert [line for line in lines if line.startswith("v ")] == [
        "v 0.000000 0.000000 0.500000", "v 0.000000 2.000000 0.500000",
        "v -1.000000 2.000000 0.500000", "v -1.000000 0.000000 0.500000"]
    assert [line for line in lines if line.startswith("vn ")] == ["vn 0.000000 0.000000 -1.000000"] * 4
    assert [line for line in lines if line.startswith("vt ")][1] == "vt 0.000000 1.000000"
    assert [line for line in lines if line.startswith("f ")] == ["f 1/1/1 3/3/3 2/2/2", "f 1/1/1 4/4/4 3/3/3"]


def test_every_sub_mesh_is_a_material_group_and_the_object_is_named_after_the_file():
    lines = _written(_read(_asset_text()))
    assert "o Square" in lines
    assert [line for line in lines if line.startswith("usemtl ")] == [
        f"usemtl {material_label(0)}", f"usemtl {material_label(1)}"] == ["usemtl SubMesh0", "usemtl SubMesh1"]
    assert obj_node_path(Path("out/Square.obj")) == "Square_obj.Square"


def test_a_mesh_without_normals_or_uvs_is_written_with_what_it_has():
    mesh = _read(_asset_text())
    mesh.normals, mesh.uvs = [], []
    lines = _written(mesh)
    assert not any(line.startswith(("vn ", "vt ")) for line in lines)
    assert [line for line in lines if line.startswith("f ")][0] == "f 1 3 2"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
