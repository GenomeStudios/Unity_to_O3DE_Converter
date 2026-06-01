"""Unit tests for `read_fbx_node_transforms` — the FBX node-transform
reader that exposes the baked scene offsets behind the Office/Police
furniture scatter (`mem:transform_truth/transform_truth_plan`).

Uses a hand-built minimal binary FBX (v7400, 32-bit records) so the test
is portable and deterministic — no dependency on the real asset packs.
"""

import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import (
    read_fbx_node_transforms, read_fbx_geometry_centroids,
    read_fbx_geometry_bbox_centers,
    compute_single_mesh_autocenter, compute_node_autocenters,
)


# --- minimal binary-FBX builder (just enough for Objects>Model>Properties70) ---

def _pD(v):   # double property
    return b"D" + struct.pack("<d", float(v))


def _pS(s):   # string property
    b = s.encode("utf-8")
    return b"S" + struct.pack("<I", len(b)) + b


def _pL(v):   # int64 property
    return b"L" + struct.pack("<q", v)


def _record(spec, start):
    """spec = {name, props:[bytes], children:[spec]}. Returns the encoded
    record bytes with an absolute EndOffset (FBX <7500, 32-bit)."""
    name_b = spec["name"].encode("ascii")
    prop_blob = b"".join(spec["props"])
    header_len = 4 + 4 + 4 + 1
    cursor = start + header_len + len(name_b) + len(prop_blob)
    child_blobs = []
    for child in spec["children"]:
        cb = _record(child, cursor)
        child_blobs.append(cb)
        cursor += len(cb)
    nested = b"".join(child_blobs)
    if spec["children"]:
        nested += b"\x00" * 13   # null-record terminator for the nested list
        cursor += 13
    end_offset = cursor
    header = struct.pack("<III", end_offset, len(spec["props"]), len(prop_blob))
    header += bytes([len(name_b)])
    return header + name_b + prop_blob + nested


def _p70(key, x, y, z):
    return {"name": "P",
            "props": [_pS(key), _pS(key), _pS(""), _pS("A+"), _pD(x), _pD(y), _pD(z)],
            "children": []}


def _varray(vals):
    """Encode a 'd' double-array property (encoding 0 = uncompressed)."""
    body = struct.pack(f"<{len(vals)}d", *vals)
    return b"d" + struct.pack("<III", len(vals), 0, len(body)) + body


def _geometry(node_name, verts_flat):
    return {
        "name": "Geometry",
        "props": [_pL(7), _pS(f"{node_name}\x00\x01Geometry"), _pS("Mesh")],
        "children": [{"name": "Vertices", "props": [_varray(verts_flat)],
                      "children": []}],
    }


def _model(node_name, t, r, s):
    return {
        "name": "Model",
        "props": [_pL(123), _pS(f"{node_name}\x00\x01Model"), _pS("Mesh")],
        "children": [{
            "name": "Properties70",
            "props": [],
            "children": [
                _p70("Lcl Translation", *t),
                _p70("Lcl Rotation", *r),
                _p70("Lcl Scaling", *s),
            ],
        }],
    }


def _build_fbx(models) -> bytes:
    header = b"Kaydara FBX Binary  \x00" + bytes([0x1A, 0x00]) + struct.pack("<I", 7400)
    objects = {"name": "Objects", "props": [], "children": models}
    body = _record(objects, len(header))
    body += b"\x00" * 13   # top-level null-record terminator
    return header + body


def _tmp(suffix=".fbx") -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)   # Windows can't unlink a file with an open descriptor
    return Path(path)


def _write(models) -> Path:
    fbx = _tmp()
    fbx.write_bytes(_build_fbx(models))
    return fbx


# --- tests ---

def test_single_model_translation_rotation():
    fbx = _write([_model("Desk_frame", (2500.0, 0.0, -0.134), (90.0, 0.0, 0.0), (1, 1, 1))])
    try:
        out = read_fbx_node_transforms(fbx)
        assert "Desk_frame" in out, out
        t = out["Desk_frame"]["translation"]
        r = out["Desk_frame"]["rotation"]
        assert abs(t[0] - 2500.0) < 1e-6 and abs(t[2] + 0.134) < 1e-6, t
        assert abs(r[0] - 90.0) < 1e-6, r
    finally:
        fbx.unlink(missing_ok=True)


def test_multi_model_file_order_and_defaults():
    fbx = _write([
        _model("Root", (4943.0, 0.3, 0.5), (90.0, 0.0, 0.0), (1, 1, 1)),
        _model("door_R", (62.4, 125.0, 22.2), (0, 0, 0), (1, 1, 1)),
    ])
    try:
        out = read_fbx_node_transforms(fbx)
        assert list(out.keys()) == ["Root", "door_R"], list(out.keys())
        assert abs(out["door_R"]["translation"][0] - 62.4) < 1e-6
        # Identity rotation parsed as zeros; scaling defaults to ones.
        assert out["door_R"]["rotation"] == [0.0, 0.0, 0.0]
        assert out["door_R"]["scaling"] == [1.0, 1.0, 1.0]
    finally:
        fbx.unlink(missing_ok=True)


def test_non_binary_returns_empty():
    p = _tmp()
    p.write_text("; FBX 7.4.0 project file\nObjects: { }\n", encoding="utf-8")
    try:
        assert read_fbx_node_transforms(p) == {}
    finally:
        p.unlink(missing_ok=True)


def test_missing_file_returns_empty():
    assert read_fbx_node_transforms(Path("does-not-exist.fbx")) == {}


# --- geometry centroid + auto-center -------------------------------------

def test_geometry_centroid_metres():
    """Vertices in cm → centroid in metres. Verts centred at (100,200,-50)cm."""
    verts = [90, 190, -60,  110, 210, -40]   # cm; mean = (100,200,-50)
    fbx = _write([_geometry("Cube", verts)])
    try:
        cs = read_fbx_geometry_centroids(fbx)
        assert len(cs) == 1
        assert abs(cs[0][0] - 1.0) < 1e-6 and abs(cs[0][1] - 2.0) < 1e-6 \
            and abs(cs[0][2] + 0.5) < 1e-6, cs
    finally:
        fbx.unlink(missing_ok=True)


def test_bbox_center_vs_centroid():
    """bbox center = (min+max)/2; differs from the vertex centroid for a
    skewed vertex distribution (the box-vs-detailed-mesh case)."""
    # 3 verts: heavy on the low end → centroid < bbox center.
    verts = [-100, 0, 0,  -100, 0, 0,  +100, 0, 0]   # cm; centroidX=-33.3, bboxX=0
    fbx = _write([_geometry("M", verts)])
    try:
        assert abs(read_fbx_geometry_bbox_centers(fbx)[0][0] - 0.0) < 1e-6
        assert abs(read_fbx_geometry_centroids(fbx)[0][0] + 0.3333) < 1e-3
    finally:
        fbx.unlink(missing_ok=True)


def test_single_mesh_autocenter_formula():
    """default_position = (centroid_X, node_Y, -node_Z). Single Model + single
    Geometry. node T=(2440,-45,76)cm → (-,-0.45,-0.76); centroid X from verts."""
    verts = [-65, 0, 0,  -55, 0, 0]   # cm; centroid X = -60cm = -0.6m
    fbx = _write([
        _model("Drawer", (2440.0, -45.0, 76.0), (90.0, 0.0, 0.0), (1, 1, 1)),
        _geometry("Drawer", verts),
    ])
    try:
        ac = compute_single_mesh_autocenter(fbx)
        assert ac is not None
        assert abs(ac[0] + 0.60) < 1e-3, ac      # centroid_X
        assert abs(ac[1] + 0.45) < 1e-3, ac      # node_Y
        assert abs(ac[2] + 0.76) < 1e-3, ac      # -node_Z
    finally:
        fbx.unlink(missing_ok=True)


def test_multi_mesh_autocenter_is_none():
    """Multi-mesh FBX (2 Models) → None for the SINGLE-mesh helper."""
    fbx = _write([
        _model("A", (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        _model("B", (0, 0, 0), (0, 0, 0), (1, 1, 1)),
        _geometry("A", [0, 0, 0, 1, 1, 1]),
    ])
    try:
        assert compute_single_mesh_autocenter(fbx) is None
    finally:
        fbx.unlink(missing_ok=True)


def test_per_node_autocenters_multi_mesh():
    """compute_node_autocenters pairs Model↔Geometry by file order and gives a
    per-node (centroid_X, node_Y, -node_Z). Two nodes → two centers."""
    fbx = _write([
        # node Frame: Y/Z tiny; geometry centred → ~0 compensation.
        _model("Frame", (4900.0, 0.0, 0.0), (90.0, 0.0, 0.0), (1, 1, 1)),
        _model("Door",  (62.0, 125.0, 22.0), (0.0, 0.0, 0.0), (1, 1, 1)),
        _geometry("Frame", [-10, 0, 0,  10, 0, 0]),          # centroid X = 0
        _geometry("Door",  [10, 0, 0,   30, 0, 0]),          # centroid X = 20cm = 0.2m
    ])
    try:
        ac = compute_node_autocenters(fbx)
        assert set(ac) == {"Frame", "Door"}, ac
        assert abs(ac["Frame"][0]) < 1e-3, ac                # frame centred
        assert abs(ac["Door"][0] - 0.20) < 1e-3, ac          # centroid_X
        assert abs(ac["Door"][1] - 1.25) < 1e-3, ac          # node_Y
        assert abs(ac["Door"][2] + 0.22) < 1e-3, ac          # -node_Z
    finally:
        fbx.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
