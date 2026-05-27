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


def test_y_up_does_not_auto_correct_rotation():
    """The legacy Y-up auto-correction has been removed (2026-05-27).
    Even when the source FBX is detected as Y-up, the writer emits the
    user's authored rotation directly, with NO composition with the
    platform's correction quaternion. The user authors whatever
    rotation they want via mesh_settings."""
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
        # Direct mapping — 90° Y → quaternion = [0, sin45, 0, cos45].
        s = math.sin(math.radians(45))
        c = math.cos(math.radians(45))
        assert _quat_close(rule["rotation"], [0, s, 0, c]), \
            f"Y-up FBX should NOT compose with correction; got {rule['rotation']}"


def test_zero_user_rotation_on_y_up_writes_no_rotation():
    """Y-up FBX + zero user rotation → CoordinateSystemRule has no
    rotation field at all. The legacy auto-correction would have
    injected the Y_UP_ROTATION quaternion here; the new behaviour
    leaves the rule rotation absent."""
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
        assert "rotation" not in rule, \
            f"zero user rotation on Y-up should leave no rotation field; got {rule}"


def test_physx_group_inherits_composed_rule():
    """Collider MeshGroup uses the same composed CoordinateSystemRule
    as the visual group."""
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
                             collider_entity_node_map={"Cube": "RootNode.Foo.Cube"},
                             mesh_settings=settings, mesh_guid="mesh-x")
        body  = json.loads(Path(str(fbx) + ".assetinfo").read_text(encoding="utf-8"))
        groups = body["values"]
        physx = [g for g in groups if "{5B03C8E6" in g.get("$type", "")]
        assert physx, "PhysX group not emitted"
        physx_rule = next(r for r in physx[0]["rules"]["rules"]
                          if r.get("$type") == "CoordinateSystemRule")
        s = math.sin(math.radians(45))
        c = math.cos(math.radians(45))
        assert _quat_close(physx_rule["rotation"], [0, s, 0, c])


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
