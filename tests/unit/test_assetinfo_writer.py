"""Unit tests for ``targets.o3de.assetinfo_writer`` — quaternion
math + per-mesh-setting composition + Y-up correction. F-9.I.3
verification."""

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.unity_tree import write_fake_fbx

from targets.o3de.assetinfo_writer import (
    Y_UP_ROTATION, _euler_deg_to_quat, _quat_mul,
    _resolve_mesh_settings, write_fbx_assetinfo,
)
import integrated_asset_processor as iap


def _read_coord_rule(asset_path: Path) -> dict:
    body  = json.loads(asset_path.read_text(encoding="utf-8"))
    rules = body["values"][0]["rules"]["rules"]
    for r in rules:
        if r.get("$type") == "CoordinateSystemRule":
            return r
    raise AssertionError("CoordinateSystemRule not found in emitted assetinfo")


def _quat_close(a, b, tol=1e-5) -> bool:
    return len(a) == len(b) == 4 and all(abs(x - y) < tol for x, y in zip(a, b))


# ---- pure helpers --------------------------------------------------------

def test_euler_zero_returns_identity_quat():
    assert _quat_close(_euler_deg_to_quat([0, 0, 0]), [0, 0, 0, 1])


def test_euler_90_y_axis():
    s = math.sin(math.radians(45))
    c = math.cos(math.radians(45))
    assert _quat_close(_euler_deg_to_quat([0, 90, 0]), [0, s, 0, c])


def test_quat_mul_identity():
    q = [0.1, 0.2, 0.3, 0.4]
    ident = [0, 0, 0, 1]
    assert _quat_close(_quat_mul(q, ident), q)
    assert _quat_close(_quat_mul(ident, q), q)


def test_resolve_mesh_settings_defaults():
    eff = _resolve_mesh_settings(None, None)
    assert eff["zero_position"] is True
    assert eff["default_position"] == [0, 0, 0]
    assert eff["default_rotation"] == [0, 0, 0]


def test_resolve_mesh_settings_override_merges():
    settings = {
        "defaults":  {"zero_position": True, "default_position": [0, 0, 0],
                      "default_rotation": [0, 0, 0]},
        "overrides": {"mesh-x": {"default_position": [1, 2, 3]}},
    }
    eff = _resolve_mesh_settings(settings, "mesh-x")
    assert eff["default_position"] == [1, 2, 3]
    # Unrelated key inherits the default.
    assert eff["zero_position"] is True


def test_resolve_mesh_settings_physx_mesh():
    """`physx_mesh` defaults False and is override-able per mesh."""
    assert _resolve_mesh_settings(None, None)["physx_mesh"] is False
    settings = {"defaults": {}, "overrides": {"g": {"physx_mesh": True}}}
    assert _resolve_mesh_settings(settings, "g")["physx_mesh"] is True
    # A different mesh inherits the (False) default.
    assert _resolve_mesh_settings(settings, "other")["physx_mesh"] is False


# ---- writer end-to-end ---------------------------------------------------

def test_default_emission_bare_rule():
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                             log=lambda *_: None)
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        assert rule == {"$type": "CoordinateSystemRule", "useAdvancedData": True}


def test_user_rotation_only_lands_in_rule():
    settings = {
        "defaults":  {"zero_position": True, "default_position": [0, 0, 0],
                      "default_rotation": [0, 90, 0]},
        "overrides": {},
    }
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                             log=lambda *_: None,
                             mesh_settings=settings, mesh_guid="mesh-x")
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        s = math.sin(math.radians(45))
        c = math.cos(math.radians(45))
        assert _quat_close(rule["rotation"], [0, s, 0, c])
        # zero_position True + zero default_position → no translation.
        assert "translation" not in rule


def test_zero_position_false_suppresses_translation():
    settings = {
        "defaults":  {"zero_position": False, "default_position": [9, 9, 9],
                      "default_rotation": [0, 0, 0]},
        "overrides": {},
    }
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                             log=lambda *_: None,
                             mesh_settings=settings, mesh_guid="mesh-x")
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        assert "translation" not in rule, \
            f"zero_position=False should suppress translation: {rule}"


def test_y_up_composes_90x_correction_over_user_rotation():
    """Per-FBX Y-up→Z-up correction (re-introduced 2026-05-28, confirmed via
    the Office Cabinet cook): a Y-up FBX (up_axis=1) composes a +90° X
    correction UNDER the user's authored rotation."""
    settings = {
        "defaults":  {"zero_position": True, "default_position": [0, 0, 0],
                      "default_rotation": [0, 90, 0]},
        "overrides": {},
    }
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        original = iap.read_fbx_up_axis
        iap.read_fbx_up_axis = lambda _p: 1  # type: ignore[assignment]
        try:
            write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                                 log=lambda *_: None,
                                 mesh_settings=settings, mesh_guid="mesh-x")
        finally:
            iap.read_fbx_up_axis = original
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        expected = _quat_mul(_euler_deg_to_quat([0, 90, 0]),
                             _euler_deg_to_quat([90, 0, 0]))
        assert _quat_close(rule["rotation"], expected), \
            f"Y-up should compose 90°X under user rot; got {rule['rotation']}"


def test_z_up_does_not_auto_correct():
    """Z-up FBX (up_axis=2) gets NO rotation correction — the desk case that
    imports upright. With zero user rotation the rule carries no rotation."""
    settings = {"defaults": {"zero_position": True, "default_position": [0, 0, 0],
                             "default_rotation": [0, 0, 0]}, "overrides": {}}
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        original = iap.read_fbx_up_axis
        iap.read_fbx_up_axis = lambda _p: 2  # type: ignore[assignment]
        try:
            write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                                 log=lambda *_: None,
                                 mesh_settings=settings, mesh_guid="mesh-x")
        finally:
            iap.read_fbx_up_axis = original
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        assert "rotation" not in rule, f"Z-up must not auto-correct: {rule}"


def test_zero_user_rotation_on_y_up_writes_90x():
    """Y-up FBX + zero user rotation → rule rotation IS the +90° X
    correction quaternion (= [sin45, 0, 0, cos45])."""
    settings = {
        "defaults":  {"zero_position": True, "default_position": [0, 0, 0],
                      "default_rotation": [0, 0, 0]},
        "overrides": {},
    }
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        original = iap.read_fbx_up_axis
        iap.read_fbx_up_axis = lambda _p: 1  # type: ignore[assignment]
        try:
            write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                                 log=lambda *_: None,
                                 mesh_settings=settings, mesh_guid="mesh-x")
        finally:
            iap.read_fbx_up_axis = original
        rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
        s = math.sin(math.radians(45)); c = math.cos(math.radians(45))
        assert _quat_close(rule["rotation"], [s, 0, 0, c]), \
            f"Y-up + zero user rot should be the +90°X correction; got {rule}"


def test_auto_center_toggle_gates_translation():
    """auto_center=False suppresses the single-mesh auto-center; =True applies
    the derived value. (compute_single_mesh_autocenter monkeypatched.)"""
    orig = iap.compute_node_autocenters
    iap.compute_node_autocenters = lambda _p: {"Cube": [0.5, 0.0, 0.0]}
    try:
        with tempfile.TemporaryDirectory() as td:
            for flag, expect in ((True, [0.5, 0.0, 0.0]), (False, None)):
                fbx = Path(td) / f"Foo_{flag}.fbx"
                write_fake_fbx(fbx)
                write_fbx_assetinfo(
                    fbx, "Foo", {"Cube": "RootNode.Foo.Cube"}, log=lambda *_: None,
                    mesh_settings={"defaults": {"auto_center": flag,
                                                "zero_position": True}, "overrides": {}},
                    mesh_guid="m")
                rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
                assert rule.get("translation") == expect, (flag, rule)
    finally:
        iap.compute_node_autocenters = orig


def test_auto_rotation_toggle_gates_rotation():
    """auto_rotation=False suppresses the Y-up +90°X correction."""
    orig = iap.read_fbx_up_axis
    iap.read_fbx_up_axis = lambda _p: 1  # Y-up
    try:
        with tempfile.TemporaryDirectory() as td:
            fbx = Path(td) / "Foo.fbx"
            write_fake_fbx(fbx)
            write_fbx_assetinfo(
                fbx, "Foo", {"Cube": "RootNode.Foo.Cube"}, log=lambda *_: None,
                mesh_settings={"defaults": {"auto_rotation": False,
                                            "default_rotation": [0, 0, 0]}, "overrides": {}},
                mesh_guid="m")
            rule = _read_coord_rule(Path(str(fbx) + ".assetinfo"))
            assert "rotation" not in rule, rule
    finally:
        iap.read_fbx_up_axis = orig


def _physx_groups(asset_path: Path) -> list:
    body = json.loads(asset_path.read_text(encoding="utf-8"))
    return [g for g in body["values"] if "{5B03C8E6" in g.get("$type", "")]


def _spec(name, node, convex=False):
    return {"name": name, "node_paths": [node], "convex": convex}


def test_physx_group_inherits_composed_rule():
    """Collider MeshGroup uses the same composed CoordinateSystemRule
    as the visual group when mesh settings rotate/translate."""
    settings = {
        "defaults":  {"zero_position": True, "default_position": [0, 0, 0],
                      "default_rotation": [0, 90, 0]},
        "overrides": {},
    }
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(fbx, "Foo", {"Cube": "RootNode.Foo.Cube"},
                             log=lambda *_: None,
                             physx_specs=[_spec("Foo", "RootNode.Foo.Cube")],
                             mesh_settings=settings, mesh_guid="mesh-x")
        physx = _physx_groups(Path(str(fbx) + ".assetinfo"))
        assert physx, "PhysX group not emitted"
        physx_rule = next(r for r in physx[0]["rules"]["rules"]
                          if r.get("$type") == "CoordinateSystemRule")
        s = math.sin(math.radians(45))
        c = math.cos(math.radians(45))
        assert _quat_close(physx_rule["rotation"], [0, s, 0, c])


def test_collider_default_is_triangle_mesh():
    """T-5a: a non-convex spec emits a bare TriMesh group — no
    'export method' field and no ConvexAssetParams (matches O3DE's own
    default serialization)."""
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(
            fbx, "Foo", {"Cube": "RootNode.Foo.Cube"}, log=lambda *_: None,
            physx_specs=[_spec("Foo", "RootNode.Foo.Cube")])
        g = _physx_groups(Path(str(fbx) + ".assetinfo"))[0]
        assert "export method" not in g, "triangle group must omit export method"
        assert "ConvexAssetParams" not in g
        assert g["name"] == "Foo"


def test_collider_convex_sets_export_method():
    """T-5b: a convex spec emits 'export method': 1
    (MeshExportMethod::Convex)."""
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(
            fbx, "Foo", {"Cube": "RootNode.Foo.Cube"}, log=lambda *_: None,
            physx_specs=[_spec("Foo", "RootNode.Foo.Cube", convex=True)])
        g = _physx_groups(Path(str(fbx) + ".assetinfo"))[0]
        assert g.get("export method") == 1


def test_collider_node_selection():
    """T-5c: the group selects its spec node(s), unselects RootNode and
    the other visual nodes."""
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(
            fbx, "Foo",
            {"Cube": "RootNode.Foo.Cube", "Lid": "RootNode.Foo.Lid"},
            log=lambda *_: None,
            physx_specs=[_spec("Foo-Cube", "RootNode.Foo.Cube")])
        g = _physx_groups(Path(str(fbx) + ".assetinfo"))[0]
        sel = g["NodeSelectionList"]
        assert sel["selectedNodes"] == ["RootNode.Foo.Cube"]
        assert "RootNode" in sel["unselectedNodes"]
        assert "RootNode.Foo.Lid" in sel["unselectedNodes"]


def test_collider_identity_omits_rules():
    """T-5d: with default mesh settings the coordinate rule is identity,
    so the PhysX group carries no 'rules'."""
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Foo.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(
            fbx, "Foo", {"Cube": "RootNode.Foo.Cube"}, log=lambda *_: None,
            physx_specs=[_spec("Foo", "RootNode.Foo.Cube")])
        g = _physx_groups(Path(str(fbx) + ".assetinfo"))[0]
        assert "rules" not in g


def test_multiple_physx_specs_emit_distinct_groups():
    """T-4/T-5e (multi-submesh): several specs in one assetinfo emit one
    PhysX group each, with the spec names preserved (→ distinct .pxmesh
    products). Mirrors the StairsMod _COL FBX (3 collision sub-meshes)."""
    with tempfile.TemporaryDirectory() as td:
        fbx = Path(td) / "Stairs_COL.fbx"
        write_fake_fbx(fbx)
        write_fbx_assetinfo(
            fbx, "Stairs_COL", {}, log=lambda *_: None,
            physx_specs=[
                _spec("Stairs_COL-Ground",  "RootNode.Ground"),
                _spec("Stairs_COL-RailIn",  "RootNode.RailIn"),
                _spec("Stairs_COL-RailOut", "RootNode.RailOut"),
            ])
        groups = _physx_groups(Path(str(fbx) + ".assetinfo"))
        assert len(groups) == 3
        names = {g["name"] for g in groups}
        assert names == {"Stairs_COL-Ground", "Stairs_COL-RailIn",
                         "Stairs_COL-RailOut"}
        # Collision-only FBX: no visual groups present.
        body = json.loads(Path(str(fbx) + ".assetinfo").read_text(encoding="utf-8"))
        visual = [g for g in body["values"] if "{07B356B7" in g.get("$type", "")]
        assert visual == []


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
