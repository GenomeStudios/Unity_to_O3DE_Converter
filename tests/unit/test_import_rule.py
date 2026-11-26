"""Unit tests for the mesh import rule read from the file (parity_fixes I.3,
proof T.6).

The rule has to make O3DE's model of a mesh node equal the mesh Unity
imports from the same node. Both importers are modelled here from what was
measured on real files:

    Unity's mesh        N * (G * raw)         N negates X, G is the node's
                                              geometric transform
    O3DE before a rule  K^-1 * raw            K depends on the file's up axis
    O3DE's target       A * (Unity's mesh)    A swaps Y and Z

so the rule ``R, T`` must satisfy ``R * (K^-1 raw) + T == A N (G raw)`` for
every vertex. The tests check exactly that, with made-up vertices.
"""

import math
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from fbx_reader import read_import_facts
from targets.o3de.assetinfo_writer import (
    _euler_xyz_matrix, _mat_mul, _mat_vec, _matrix_to_quat, _quat_to_matrix,
    _RAW_FROM_PIPELINE, source_import_rule, source_import_scale, write_fbx_assetinfo,
)


# =============================================================================
# THE TWO IMPORTERS, AS MEASURED
# =============================================================================

def _transpose(m):
    return [[m[column][row] for column in range(3)] for row in range(3)]


def _facts(up_axis, rotation=(0.0, 0.0, 0.0), translation=(0.0, 0.0, 0.0), unit=0.01):
    return {"up_axis": up_axis, "unit_to_metres": unit, "nodes": {"Part": {
        "geometric_translation": list(translation), "geometric_rotation": list(rotation),
        "geometric_scaling": [1.0, 1.0, 1.0]}}}


def _unity_mesh_in_o3de_axes(facts, raw):
    """Where Unity has a raw file vertex, mapped to O3DE axes, in metres."""
    node, unit = facts["nodes"]["Part"], facts["unit_to_metres"]
    turned = _mat_vec(_euler_xyz_matrix(node["geometric_rotation"]), raw)
    with_offset = [(turned[i] + node["geometric_translation"][i]) * unit for i in range(3)]
    negated = [-with_offset[0], with_offset[1], with_offset[2]]          # Unity negates X
    return [negated[0], negated[2], negated[1]]                          # Unity (x, y, z) -> O3DE (x, z, y)


def _o3de_vertex_before_a_rule(facts, raw):
    """A raw file vertex as O3DE's scene pipeline holds it, in metres."""
    pipeline = _mat_vec(_transpose(_RAW_FROM_PIPELINE[facts["up_axis"]]), raw)
    return [value * facts["unit_to_metres"] for value in pipeline]


def _largest_miss(facts, **switches):
    rotation, translation = source_import_rule(facts, "Part", **switches)
    generator = random.Random(4)
    worst = 0.0
    for _ in range(50):
        raw = [generator.uniform(-300.0, 300.0) for _ in range(3)]
        ruled = _mat_vec(rotation, _o3de_vertex_before_a_rule(facts, raw))
        ruled = [ruled[i] + translation[i] for i in range(3)]
        wanted = _unity_mesh_in_o3de_axes(facts, raw)
        worst = max(worst, max(abs(ruled[i] - wanted[i]) for i in range(3)))
    return worst


# =============================================================================
# THE RULE PUTS THE MODEL WHERE UNITY HAS THE MESH
# =============================================================================

def test_rule_matches_unity_for_both_up_axes_and_any_geometric_transform():
    for up_axis in (1, 2):
        for rotation in ((0, 0, 0), (-90, 0, 0), (90, 0, 0), (0, 0, 90), (-90, 0, 180), (30, -20, 70)):
            for translation in ((0, 0, 0), (-1.4, -80.8, -45.0), (120.6, 0.0, -0.4)):
                miss = _largest_miss(_facts(up_axis, rotation, translation))
                assert miss < 1e-9, (up_axis, rotation, translation, miss)


def test_a_3ds_max_export_needs_the_turns_the_pack_was_seen_to_need():
    """Max writes a geometric rotation of -90 about X. For such a node a Z-up
    file needs no turn, and a Y-up file a quarter turn about X."""
    z_up, _ = source_import_rule(_facts(2, (-90, 0, 0)), "Part")
    assert max(abs(z_up[r][c] - (1.0 if r == c else 0.0)) for r in range(3) for c in range(3)) < 1e-12
    y_up, _ = source_import_rule(_facts(1, (-90, 0, 0)), "Part")
    quarter_turn_x = [[1, 0, 0], [0, 0, -1], [0, 1, 0]]
    assert max(abs(y_up[r][c] - quarter_turn_x[r][c]) for r in range(3) for c in range(3)) < 1e-12


def test_geometric_offset_becomes_the_translation_in_metres():
    """The drawer of the Office pack's metal desk."""
    _, translation = source_import_rule(_facts(2, (-90, 0, 0), (-1.4017680883, -80.8071594238, -45.015380859)), "Part")
    assert max(abs(a - b) for a, b in zip(translation, [0.014017681, -0.45015381, -0.80807159])) < 1e-8


def test_the_units_of_the_file_are_respected():
    assert _largest_miss(_facts(1, (0, 0, 0), (10.0, 20.0, 30.0), unit=1.0)) < 1e-9
    _, translation = source_import_rule(_facts(1, (0, 0, 0), (1.0, 2.0, 3.0), unit=0.0254), "Part")
    assert max(abs(a - b) for a, b in zip(translation, [-0.0254, 0.0762, 0.0508])) < 1e-12


def test_switches_turn_rotation_and_translation_off_separately():
    facts = _facts(1, (-90, 0, 0), (10.0, 0.0, 0.0))
    rotation, translation = source_import_rule(facts, "Part", axis_rule=False)
    assert rotation == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]] and translation != [0.0, 0.0, 0.0]
    rotation, translation = source_import_rule(facts, "Part", geometric_offset=False)
    assert translation == [0.0, 0.0, 0.0] and rotation[1][1] != 1.0


def test_unknown_axis_or_node_gives_no_rule():
    for facts, node in ((_facts(-1, (-90, 0, 0), (1, 2, 3)), "Part"), (_facts(1), "Missing")):
        rotation, translation = source_import_rule(facts, node)
        assert rotation == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        assert translation == [0.0, 0.0, 0.0]


# =============================================================================
# THE RULE'S SCALE
# A node's geometric scaling, and the source importer's own scale factor.
# =============================================================================

def _scaled_facts(scaling, translation=(0.0, 0.0, 0.0)):
    facts = _facts(1, (-90, 0, 0), translation)
    facts["nodes"]["Part"]["geometric_scaling"] = list(scaling)
    return facts


def test_a_geometric_scaling_that_is_one_on_all_axes_is_the_rules_scale():
    """The bar stool rope of the Tirgames pack: geometric scaling 4.0116."""
    assert abs(source_import_scale(_scaled_facts((4.0116, 4.0116, 4.0116)), "Part") - 4.0116) < 1e-12
    assert source_import_scale(_facts(1), "Part") == 1.0


def test_the_importers_scale_factor_multiplies_scale_and_translation():
    """The same file with Unity's Scale Factor at 1.1: the mesh is 4.413
    times the file's, and its geometric offset is scaled with it."""
    facts = _scaled_facts((4.0116, 4.0116, 4.0116), translation=(10.0, 0.0, 0.0))
    assert abs(source_import_scale(facts, "Part", import_scale=1.1) - 4.41276) < 1e-9
    _, plain = source_import_rule(facts, "Part")
    _, scaled = source_import_rule(facts, "Part", import_scale=1.1)
    assert max(abs(s - 1.1 * p) for s, p in zip(scaled, plain)) < 1e-12 and abs(plain[0] + 0.1) < 1e-12


def test_a_scaling_that_differs_by_axis_cannot_be_written_into_the_rule():
    assert source_import_scale(_scaled_facts((0.3657, 0.3657, 1.0)), "Part") is None


def test_a_node_the_file_does_not_have_keeps_the_importers_scale():
    assert source_import_scale(_facts(1), "Missing", import_scale=1.5) == 1.5


def test_the_writer_puts_the_scale_into_the_rule_of_render_and_collision_groups():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        fbx = Path(tmp) / "Thing.fbx"
        fbx.write_bytes(b"FBX-stub\x00\x00")
        write_fbx_assetinfo(fbx, "Thing", {"Thing": "RootNode.Thing"}, log=lambda line: None,
                            physx_specs=[{"name": "Thing", "node_paths": ["RootNode.Thing"], "convex": True}],
                            import_scale=1.5)
        groups = json.loads((Path(tmp) / "Thing.fbx.assetinfo").read_text(encoding="utf-8"))["values"]
        rules = [next(r for r in group["rules"]["rules"] if r["$type"] == "CoordinateSystemRule") for group in groups]
        assert [rule.get("scale") for rule in rules] == [1.5, 1.5], rules


# =============================================================================
# QUATERNIONS WRITTEN TO THE FILE
# =============================================================================

def test_matrix_and_quaternion_agree_also_for_half_turns():
    generator = random.Random(9)
    cases = [_euler_xyz_matrix(angles) for angles in ((180, 0, 0), (0, 180, 0), (0, 0, 180), (90, 0, 180))]
    cases += [_euler_xyz_matrix([generator.uniform(-180, 180) for _ in range(3)]) for _ in range(200)]
    cases.append(_mat_mul([[-1, 0, 0], [0, 0, 1], [0, 1, 0]], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
    for matrix in cases:
        back = _quat_to_matrix(_matrix_to_quat(matrix))
        assert max(abs(back[r][c] - matrix[r][c]) for r in range(3) for c in range(3)) < 1e-9
        assert abs(math.sqrt(sum(v * v for v in _matrix_to_quat(matrix))) - 1.0) < 1e-9


# =============================================================================
# THE WRITER, ON A FILE THAT CANNOT BE READ
# =============================================================================

def test_a_file_that_is_not_fbx_gets_no_rule_and_still_an_assetinfo():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        fbx = Path(tmp) / "Thing.fbx"
        fbx.write_bytes(b"FBX-stub\x00\x00")
        assert read_import_facts(fbx)["up_axis"] == -1
        write_fbx_assetinfo(fbx, "Thing", {"Thing": "RootNode.Thing"}, log=lambda line: None)
        group = json.loads((Path(tmp) / "Thing.fbx.assetinfo").read_text(encoding="utf-8"))["values"][0]
        rule = next(r for r in group["rules"]["rules"] if r["$type"] == "CoordinateSystemRule")
        assert "rotation" not in rule and "translation" not in rule


def test_the_users_position_is_added_after_the_files_rule():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        fbx = Path(tmp) / "Thing.fbx"
        fbx.write_bytes(b"FBX-stub\x00\x00")
        settings = {"defaults": {"default_position": [1.0, 2.0, 3.0], "default_rotation": [0.0, 0.0, 90.0]}}
        write_fbx_assetinfo(fbx, "Thing", {"Thing": "RootNode.Thing"}, log=lambda line: None,
                            mesh_settings=settings)
        group = json.loads((Path(tmp) / "Thing.fbx.assetinfo").read_text(encoding="utf-8"))["values"][0]
        rule = next(r for r in group["rules"]["rules"] if r["$type"] == "CoordinateSystemRule")
        assert rule["translation"] == [1.0, 2.0, 3.0]
        assert max(abs(a - b) for a, b in zip(rule["rotation"], [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)])) < 1e-9


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
