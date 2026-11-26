"""Unit tests for Unity's built-in meshes (parity_fixes I.4, proof T.7): a
cube made in the Unity editor has no file to copy, so the converter writes
the mesh itself.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.builtin_meshes import (
    BUILTIN_MATERIAL_LABEL, BUILTIN_MESH_GUID, write_builtin_mesh,
)


# =============================================================================
# THE CUBE
# =============================================================================

def _read_obj(path: Path):
    vertices, faces = [], []
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if parts[:1] == ["v"]:
            vertices.append([float(value) for value in parts[1:]])
        elif parts[:1] == ["f"]:
            faces.append([int(corner.split("/")[0]) - 1 for corner in parts[1:]])
    return vertices, faces


def test_the_cube_is_one_metre_on_a_side_and_centred():
    with tempfile.TemporaryDirectory() as folder:
        path = write_builtin_mesh("10202", Path(folder))
        assert path.name == "UnityBuiltin_Cube.obj"
        vertices, faces = _read_obj(path)
        assert len(vertices) == 24 and len(faces) == 6
        assert {tuple(vertex) for vertex in vertices} == {(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5)
                                                          for z in (-0.5, 0.5)}
        assert f"usemtl {BUILTIN_MATERIAL_LABEL}" in path.read_text(encoding="ascii")


def test_every_face_winds_counter_clockwise_seen_from_outside():
    with tempfile.TemporaryDirectory() as folder:
        vertices, faces = _read_obj(write_builtin_mesh("10202", Path(folder)))
        for face in faces:
            a, b, c = (vertices[index] for index in face[:3])
            ab, ac = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            normal = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]
            centre = [sum(vertices[index][i] for index in face) / 4.0 for i in range(3)]
            assert sum(normal[i] * centre[i] for i in range(3)) > 0.0, face


def test_a_built_in_mesh_the_converter_does_not_write_gives_no_file():
    with tempfile.TemporaryDirectory() as folder:
        assert write_builtin_mesh("10207", Path(folder)) is None       # the sphere
        assert write_builtin_mesh("999", Path(folder)) is None


# =============================================================================
# IN A PREFAB
# =============================================================================

def _prefab(mesh_file_id: str) -> str:
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  - component: {{fileID: 3300}}
  - component: {{fileID: 2300}}
  m_Name: Ramp
--- !u!4 &400
Transform:
  m_GameObject: {{fileID: 100}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children: []
  m_Father: {{fileID: 0}}
--- !u!33 &3300
MeshFilter:
  m_GameObject: {{fileID: 100}}
  m_Mesh: {{fileID: {mesh_file_id}, guid: {BUILTIN_MESH_GUID}, type: 0}}
--- !u!23 &2300
MeshRenderer:
  m_GameObject: {{fileID: 100}}
  m_Materials:
  - {{fileID: 2100000, guid: 9e14b91c124f40844babf8171a66d570, type: 2}}
"""


def _convert(tmp: Path, mesh_file_id: str):
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Ramp.prefab"
    prefab.write_text(_prefab(mesh_file_id), encoding="utf-8")
    (unity_root / "Ramp.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122225555\n",
                                                 encoding="utf-8")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None)
    assert processor.process_prefab(prefab)
    emitted = json.loads((tmp / "out" / "Prefabs" / "Ramp.prefab").read_text(encoding="utf-8"))
    ramp = next(entity for entity in emitted["Entities"].values() if entity["Name"] == "Ramp")
    return processor, ramp, tmp / "out" / "Meshes"


def test_a_renderer_of_the_built_in_cube_gets_the_written_model():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, meshes = _convert(Path(tmp), "10202")
        hint = ramp["Components"]["AZ::Render::EditorMeshComponent"]["Controller"]["Configuration"]["ModelAsset"]["assetHint"]
        assert hint.endswith("/meshes/UnityBuiltin_Cube-Cube.obj.azmodel"), hint
        assert (meshes / "UnityBuiltin_Cube.obj").is_file()

        group = json.loads((meshes / "UnityBuiltin_Cube.obj.assetinfo").read_text(encoding="utf-8"))["values"][0]
        assert group["name"] == "UnityBuiltin_Cube-Cube"
        # An OBJ's top node is named after the file, not "RootNode".
        assert group["nodeSelectionList"]["selectedNodes"] == ["UnityBuiltin_Cube_obj", "UnityBuiltin_Cube_obj.Cube"]
        assert group["nodeSelectionList"]["unselectedNodes"] == []
        assert BUILTIN_MESH_GUID not in processor.coverage.missing_meshes


def test_a_renderer_of_another_built_in_mesh_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, _ = _convert(Path(tmp), "10207")
        assert "AZ::Render::EditorMeshComponent" not in ramp["Components"]
        assert any("built-in Sphere" in line for line in processor.coverage.warnings), processor.coverage.warnings


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
