"""Unit tests for Unity's built-in meshes (parity_fixes I.4, nature_pack I.6):
a cube, a quad or a plane made in the Unity editor has no file to copy, so
the converter makes the mesh itself.

The six meshes are checked here by what Unity's own are known to be: their
size, the way each face looks, and where the texture's corners lie. A
collider on one of them collides with the same written mesh.
"""

import json
import math
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.builtin_meshes import (
    BUILTIN_MATERIAL_LABEL, BUILTIN_MESH_GUID, BUILTIN_MESH_NAMES, builtin_mesh, write_builtin_mesh,
)

CUBE, CYLINDER, SPHERE, CAPSULE, PLANE, QUAD = "10202", "10206", "10207", "10208", "10209", "10210"


def _extent(mesh):
    return [(min(p[axis] for p in mesh.positions), max(p[axis] for p in mesh.positions)) for axis in range(3)]


def _corner(mesh, position):
    """The texture coordinates of the vertices at ``position``."""
    return {mesh.uvs[index] for index, found in enumerate(mesh.positions) if found == position}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


# =============================================================================
# EVERY MESH
# =============================================================================

def test_every_built_in_mesh_is_made():
    for file_id, name in BUILTIN_MESH_NAMES.items():
        mesh = builtin_mesh(file_id)
        assert mesh is not None and mesh.name == name
        assert len(mesh.positions) == len(mesh.normals) == len(mesh.uvs) > 0
        assert len(mesh.sub_meshes) == 1 and len(mesh.sub_meshes[0]) % 3 == 0
    assert builtin_mesh("999") is None


def test_every_triangle_shows_the_side_its_normals_point_to():
    """Unity winds a triangle clockwise seen from its front; with its
    left-handed axes that makes (b - a) x (c - a) the way the face looks."""
    for file_id, name in BUILTIN_MESH_NAMES.items():
        mesh = builtin_mesh(file_id)
        triangles = mesh.sub_meshes[0]
        for first in range(0, len(triangles), 3):
            a, b, c = (mesh.positions[index] for index in triangles[first:first + 3])
            facing = _cross([q - p for p, q in zip(a, b)], [q - p for p, q in zip(a, c)])
            assert any(abs(value) > 1e-9 for value in facing), f"{name}: a triangle without area"
            normal = [sum(mesh.normals[index][axis] for index in triangles[first:first + 3]) for axis in range(3)]
            assert sum(f * n for f, n in zip(facing, normal)) > 0.0, f"{name}: triangle {first // 3} looks inwards"


# =============================================================================
# THE FLAT ONES
# =============================================================================

def test_the_quad_is_a_metre_square_facing_minus_z_with_the_texture_upright():
    quad = builtin_mesh(QUAD)
    assert _extent(quad) == [(-0.5, 0.5), (-0.5, 0.5), (0.0, 0.0)]
    assert set(quad.normals) == {(0.0, 0.0, -1.0)}
    assert _corner(quad, (-0.5, -0.5, 0.0)) == {(0.0, 0.0)} and _corner(quad, (0.5, 0.5, 0.0)) == {(1.0, 1.0)}
    assert len(quad.positions) == 4 and len(quad.sub_meshes[0]) == 6


def test_the_plane_is_ten_metres_square_facing_up_with_the_texture_from_its_plus_corner():
    plane = builtin_mesh(PLANE)
    assert _extent(plane) == [(-5.0, 5.0), (0.0, 0.0), (-5.0, 5.0)]
    assert set(plane.normals) == {(0.0, 1.0, 0.0)}
    assert len(plane.positions) == 121 and len(plane.sub_meshes[0]) == 600
    assert _corner(plane, (5.0, 0.0, 5.0)) == {(0.0, 0.0)}
    assert _corner(plane, (-5.0, 0.0, 5.0)) == {(1.0, 0.0)} and _corner(plane, (5.0, 0.0, -5.0)) == {(0.0, 1.0)}


def test_the_cube_is_one_metre_on_a_side_with_a_whole_texture_on_every_face():
    cube = builtin_mesh(CUBE)
    assert _extent(cube) == [(-0.5, 0.5)] * 3
    assert len(cube.positions) == 24 and len(cube.sub_meshes[0]) == 36
    assert set(cube.normals) == {(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
                                 (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)}
    # Unity's cube: the texture's lower left corner on the front (-Z), top and right faces.
    def uv_at(position, normal):
        return next(cube.uvs[i] for i in range(24) if cube.positions[i] == position and cube.normals[i] == normal)
    assert uv_at((0.5, 0.5, -0.5), (0.0, 0.0, -1.0)) == (0.0, 0.0)
    assert uv_at((0.5, 0.5, 0.5), (0.0, 1.0, 0.0)) == (0.0, 0.0)
    assert uv_at((0.5, -0.5, -0.5), (1.0, 0.0, 0.0)) == (0.0, 0.0)
    assert uv_at((0.5, 0.5, 0.5), (1.0, 0.0, 0.0)) == (1.0, 1.0)


# =============================================================================
# THE ROUND ONES
# =============================================================================

def test_the_cylinder_has_unitys_twenty_sides_and_its_texture_twice_around():
    cylinder = builtin_mesh(CYLINDER)
    assert _extent(cylinder) == [(-0.5, 0.5), (-1.0, 1.0), (-0.5, 0.5)]
    assert len(cylinder.sub_meshes[0]) == 3 * 80
    rim = {position for position in cylinder.positions if position[1] == 1.0 and position != (0.0, 1.0, 0.0)}
    assert len(rim) == 20 and all(abs(math.hypot(x, z) - 0.5) < 1e-6 for x, _, z in rim)
    # On the side, U runs from 0 at -X to 1 at +X, and from 0 again back to -X.
    side = [(cylinder.positions[i], cylinder.uvs[i]) for i in range(len(cylinder.positions))
            if cylinder.normals[i][1] == 0.0]
    assert {uv[0] for position, uv in side if position == (0.5, -1.0, 0.0)} == {0.0, 1.0}
    assert {uv[0] for position, uv in side if position == (0.0, -1.0, -0.5)} == {0.5}
    assert {uv[0] for position, uv in side if position == (0.0, -1.0, 0.5)} == {0.5}


def test_the_sphere_is_half_a_metre_in_radius_with_the_texture_once_around():
    sphere = builtin_mesh(SPHERE)
    assert all(abs(math.sqrt(sum(value * value for value in position)) - 0.5) < 1e-6 for position in sphere.positions)
    assert _extent(sphere) == [(-0.5, 0.5)] * 3
    # U starts at -X and runs by -Z; V runs from the bottom pole to the top.
    assert (0.0, 0.5) in _corner(sphere, (-0.5, 0.0, 0.0)) and _corner(sphere, (0.0, 0.0, -0.5)) == {(0.25, 0.5)}
    assert _corner(sphere, (0.5, 0.0, 0.0)) == {(0.5, 0.5)}
    assert {uv[1] for uv in _corner(sphere, (0.0, -0.5, 0.0))} == {0.0}


def test_the_capsule_is_two_metres_tall_and_half_a_metre_in_radius():
    capsule = builtin_mesh(CAPSULE)
    assert _extent(capsule) == [(-0.5, 0.5), (-1.0, 1.0), (-0.5, 0.5)]
    # Every vertex lies on one of the two half spheres, a metre apart.
    for x, y, z in capsule.positions:
        centre = 0.5 if y > 0.0 else -0.5
        assert abs(math.sqrt(x * x + (y - centre) ** 2 + z * z) - 0.5) < 1e-6
    # U starts at +X; V runs evenly with the height.
    assert (0.0, 0.75) in _corner(capsule, (0.5, 0.5, 0.0)) and _corner(capsule, (0.0, -0.5, 0.5)) == {(0.25, 0.25)}


# =============================================================================
# THE FILE
# =============================================================================

def _read_obj(path: Path):
    vertices, faces, labels = [], [], []
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if parts[:1] == ["v"]:
            vertices.append(tuple(float(value) for value in parts[1:]))
        elif parts[:1] == ["f"]:
            faces.append([int(corner.split("/")[0]) - 1 for corner in parts[1:]])
        elif parts[:1] in (["o"], ["usemtl"]):
            labels.append(line)
    return vertices, faces, labels


def test_a_built_in_mesh_is_written_as_an_obj_named_after_it():
    with tempfile.TemporaryDirectory() as folder:
        path = write_builtin_mesh(QUAD, Path(folder))
        assert path.name == "UnityBuiltin_Quad.obj"
        vertices, faces, labels = _read_obj(path)
        assert labels == ["o Quad", f"usemtl {BUILTIN_MATERIAL_LABEL}"]
        assert len(vertices) == 4 and len(faces) == 2
        assert write_builtin_mesh("999", Path(folder)) is None


def test_the_file_holds_the_mesh_mirrored_in_x_with_its_triangles_turned():
    """The engine reads an OBJ as right-handed (``mesh_asset.write_obj``):
    the plane's +X +Z corner is the file's -X +Z, and its triangles wind
    counter-clockwise seen from above."""
    with tempfile.TemporaryDirectory() as folder:
        vertices, faces, _ = _read_obj(write_builtin_mesh(PLANE, Path(folder)))
        assert vertices[0] == (-5.0, 0.0, 5.0)
        a, b, c = (vertices[index] for index in faces[0])
        facing = _cross([q - p for p, q in zip(a, b)], [q - p for p, q in zip(a, c)])
        assert facing[1] > 0.0 and facing[0] == facing[2] == 0.0


# =============================================================================
# IN A PREFAB
# =============================================================================

def _prefab(mesh_file_id: str, collider: str = "") -> str:
    collider_line = "\n  - component: {fileID: 6400}" if collider else ""
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  - component: {{fileID: 3300}}
  - component: {{fileID: 2300}}{collider_line}
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
{collider}"""


def _mesh_collider(mesh_file_id: str, convex: int) -> str:
    return f"""--- !u!64 &6400
MeshCollider:
  m_GameObject: {{fileID: 100}}
  m_IsTrigger: 0
  m_Enabled: 1
  m_Convex: {convex}
  m_Mesh: {{fileID: {mesh_file_id}, guid: {BUILTIN_MESH_GUID}, type: 0}}
"""


def _convert(tmp: Path, mesh_file_id: str, collider: str = ""):
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Ramp.prefab"
    prefab.write_text(_prefab(mesh_file_id, collider), encoding="utf-8")
    (unity_root / "Ramp.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122225555\n",
                                                 encoding="utf-8")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None)
    assert processor.process_prefab(prefab)
    emitted = json.loads((tmp / "out" / "Prefabs" / "Ramp.prefab").read_text(encoding="utf-8"))
    ramp = next(entity for entity in emitted["Entities"].values() if entity["Name"] == "Ramp")
    return processor, ramp, tmp / "out" / "Meshes"


def _component(entity: dict, type_name: str) -> dict:
    return next((component for component in entity["Components"].values()
                 if component.get("$type", "").endswith(type_name)), None)


def test_a_renderer_of_the_built_in_cube_gets_the_written_model():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, meshes = _convert(Path(tmp), CUBE)
        hint = ramp["Components"]["AZ::Render::EditorMeshComponent"]["Controller"]["Configuration"]["ModelAsset"]["assetHint"]
        assert hint.endswith("/meshes/UnityBuiltin_Cube-Cube.obj.azmodel"), hint
        assert (meshes / "UnityBuiltin_Cube.obj").is_file()

        groups = json.loads((meshes / "UnityBuiltin_Cube.obj.assetinfo").read_text(encoding="utf-8"))["values"]
        assert len(groups) == 1 and groups[0]["name"] == "UnityBuiltin_Cube-Cube"
        # An OBJ's top node is named after the file, not "RootNode".
        assert groups[0]["nodeSelectionList"]["selectedNodes"] == ["UnityBuiltin_Cube_obj", "UnityBuiltin_Cube_obj.Cube"]
        assert groups[0]["nodeSelectionList"]["unselectedNodes"] == []
        assert BUILTIN_MESH_GUID not in processor.coverage.missing_meshes


def test_a_renderer_of_a_built_in_quad_gets_its_model_too():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, meshes = _convert(Path(tmp), QUAD)
        hint = ramp["Components"]["AZ::Render::EditorMeshComponent"]["Controller"]["Configuration"]["ModelAsset"]["assetHint"]
        assert hint.endswith("/meshes/UnityBuiltin_Quad-Quad.obj.azmodel"), hint
        assert not processor.coverage.warnings, processor.coverage.warnings


def test_a_mesh_id_that_names_no_built_in_mesh_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, _ = _convert(Path(tmp), "999")
        assert "AZ::Render::EditorMeshComponent" not in ramp["Components"]
        assert any("built-in mesh 999" in line for line in processor.coverage.warnings), processor.coverage.warnings


def test_a_mesh_collider_on_a_built_in_mesh_collides_with_the_written_mesh():
    with tempfile.TemporaryDirectory() as tmp:
        processor, ramp, meshes = _convert(Path(tmp), CUBE, _mesh_collider(CUBE, convex=1))
        collider = _component(ramp, "EditorMeshColliderComponent")
        hint = collider["ShapeConfiguration"]["PhysicsAsset"]["Asset"]["assetHint"]
        assert hint.endswith("/meshes/UnityBuiltin_Cube.obj.pxmesh"), hint

        groups = json.loads((meshes / "UnityBuiltin_Cube.obj.assetinfo").read_text(encoding="utf-8"))["values"]
        physics = [group for group in groups if "PhysicsMaterialSlots" in group]
        assert len(groups) == 2 and len(physics) == 1
        assert physics[0]["name"] == "UnityBuiltin_Cube" and physics[0]["export method"] == 1
        assert physics[0]["NodeSelectionList"]["selectedNodes"] == ["UnityBuiltin_Cube_obj.Cube"]


def test_a_flat_built_in_mesh_never_collides_as_a_hull():
    """A quad has no volume to make a convex hull of: its collision mesh is
    its two triangles, whatever the collider asks for."""
    with tempfile.TemporaryDirectory() as tmp:
        _, ramp, meshes = _convert(Path(tmp), QUAD, _mesh_collider(QUAD, convex=1))
        assert _component(ramp, "EditorMeshColliderComponent")["ShapeConfiguration"]["PhysicsAsset"]["Asset"][
            "assetHint"].endswith("/meshes/UnityBuiltin_Quad.obj.pxmesh")
        groups = json.loads((meshes / "UnityBuiltin_Quad.obj.assetinfo").read_text(encoding="utf-8"))["values"]
        physics = next(group for group in groups if "PhysicsMaterialSlots" in group)
        assert "export method" not in physics


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
