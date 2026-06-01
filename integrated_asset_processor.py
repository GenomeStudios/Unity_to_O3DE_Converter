#!/usr/bin/env python3
"""
Integrated Unity Prefab + Material Asset Processor

Reads Unity prefabs, finds referenced materials, generates O3DE materials
with textures, and copies everything to a homogenised folder structure.

Component processing is handled by auto-discovered modules in components/.
Add or remove processors by dropping files into that directory.
"""

import hashlib
import json
import os
import re
import shutil
import math
import random
import struct
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional, Set
# `dataclass`/`field` imports dropped — the Unity source-data dataclasses
# (Transform, UnityComponent, GameObject) moved to platforms.unity.types
# and CoverageTracker uses a hand-rolled `__init__` instead.

from platforms.unity.components import build_dispatch_table
from platforms.unity.components.base import ProcessingContext

# Pillow is a soft dependency, only required when the user enables
# "Convert Smoothness Textures to Roughness" in the Config tab. The plain
# copy path used everywhere else does not need it.
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None        # type: ignore
    PIL_AVAILABLE = False


# Unity source-data dataclasses moved to platforms.unity.types
# (follow-up: item 4). Re-exported here so existing call sites
# (`Transform`, `GameObject`, `UnityComponent` used throughout this
# module + by `unity_scene_converter_gui.py` and the component
# processors) keep working unchanged. Behaviour is byte-identical;
# the canonical home is `platforms/unity/types.py`.
from platforms.unity.types import Transform, UnityComponent, GameObject  # noqa: E402,F401


class CoverageTracker:
    """
    =============================================================================
    Records what the converter saw vs. what it actually emitted.

    Every Unity construct that crosses the converter — component types, prefab
    override propertyPaths, missing GUIDs, unsupported shaders — gets logged
    here so the end-of-run coverage.json gives the user an honest accounting of
    coverage and a punch list of what was lost.

    Intentionally append-only and cheap: no policy lives here, only counting.
    =============================================================================
    """

    def __init__(self):
        # Component types observed during parse, with handler resolution.
        # {unity_type: {"seen": int, "handled": bool, "emitted_handler": str|None}}
        self.components: Dict[str, Dict[str, Any]] = {}

        # Prefab override propertyPaths observed on PrefabInstance blocks.
        # {propertyPath_pattern: {"seen": int, "handled": int, "examples": [..]}}
        # The pattern strips Array.data[N] indices to "Array.data[*]" so a single
        # key collects all material-slot overrides regardless of slot number.
        self.prefab_overrides: Dict[str, Dict[str, Any]] = {}

        # Other prefab-instance override categories.
        self.added_components: int = 0
        self.removed_components: int = 0
        self.added_gameobjects: int = 0

        # Missing-asset reports, deduped.
        self.missing_textures: Set[str] = set()
        self.missing_meshes:   Set[str] = set()
        self.missing_materials: Set[str] = set()
        self.missing_prefabs:  Set[str] = set()

        # Light types seen, with counts (one bucket per Unity m_Type).
        self.light_types: Dict[int, int] = {}

        # Free-form notes the user should know about.
        self.warnings: List[str] = []

    # -------------------------------------------------------------------------
    # COMPONENT TYPES (observed during prefab/scene parse)
    # -------------------------------------------------------------------------

    def record_component(self, unity_type: str, handler_name: Optional[str]) -> None:
        bucket = self.components.setdefault(
            unity_type,
            {"seen": 0, "handled": handler_name is not None, "emitted_handler": handler_name},
        )
        bucket["seen"] += 1
        if handler_name and not bucket["handled"]:
            bucket["handled"] = True
            bucket["emitted_handler"] = handler_name

    # -------------------------------------------------------------------------
    # PREFAB OVERRIDES (m_Modifications + sibling fields)
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_property_path(prop_path: str) -> str:
        """
        Collapse indexed array entries into a single bucket so the report
        doesn't list 30 separate `m_Materials.Array.data[0..29]` lines.
        """
        return re.sub(r'\[\d+\]', '[*]', prop_path or '')

    def record_modification(self, prop_path: str, handled: bool,
                            example_value: Any = None) -> None:
        key    = self._normalize_property_path(prop_path)
        bucket = self.prefab_overrides.setdefault(
            key, {"seen": 0, "handled": 0, "examples": []}
        )
        bucket["seen"] += 1
        if handled:
            bucket["handled"] += 1
        if example_value is not None and len(bucket["examples"]) < 3:
            bucket["examples"].append(str(example_value)[:80])

    def record_added_component(self) -> None:
        self.added_components += 1

    def record_removed_component(self) -> None:
        self.removed_components += 1

    def record_added_gameobject(self) -> None:
        self.added_gameobjects += 1

    # -------------------------------------------------------------------------
    # ASSET RESOLUTION (missing GUIDs)
    # -------------------------------------------------------------------------

    def record_missing_texture(self, guid: str) -> None:
        if guid: self.missing_textures.add(guid)

    def record_missing_mesh(self, guid: str) -> None:
        if guid: self.missing_meshes.add(guid)

    def record_missing_material(self, guid: str) -> None:
        if guid: self.missing_materials.add(guid)

    def record_missing_prefab(self, guid: str) -> None:
        if guid: self.missing_prefabs.add(guid)

    # -------------------------------------------------------------------------
    # LIGHTS
    # -------------------------------------------------------------------------

    def record_light_type(self, unity_type: int) -> None:
        self.light_types[unity_type] = self.light_types.get(unity_type, 0) + 1

    # -------------------------------------------------------------------------
    # WARNINGS
    # -------------------------------------------------------------------------

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # -------------------------------------------------------------------------
    # SERIALIZE
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        unhandled_components = sorted(
            t for t, info in self.components.items() if not info["handled"]
        )
        unhandled_overrides = sorted(
            p for p, info in self.prefab_overrides.items() if info["handled"] == 0
        )
        return {
            "components": dict(sorted(self.components.items())),
            "unhandled_component_types": unhandled_components,
            "prefab_overrides":          dict(sorted(self.prefab_overrides.items())),
            "unhandled_override_paths":  unhandled_overrides,
            "prefab_added_components":   self.added_components,
            "prefab_removed_components": self.removed_components,
            "prefab_added_gameobjects":  self.added_gameobjects,
            "missing_assets": {
                "textures":  sorted(self.missing_textures),
                "meshes":    sorted(self.missing_meshes),
                "materials": sorted(self.missing_materials),
                "prefabs":   sorted(self.missing_prefabs),
            },
            "light_types_seen": {
                {0: "Spot", 1: "Directional", 2: "Point", 3: "Area"}.get(t, f"unknown({t})"):
                count for t, count in sorted(self.light_types.items())
            },
            "warnings": self.warnings,
        }


# AssetDatabase moved to platforms.unity.asset_database (Phase A of the
# platform-abstraction refactor). Re-exported here so existing call sites
# (`from integrated_asset_processor import AssetDatabase` in
# terrain_material_processor + any future tooling) keep working without
# code change. The original class body lived in this file at this line;
# behaviour is unchanged.
from platforms.unity.asset_database import AssetDatabase  # noqa: E402

# Phase A.4: shader-name resolution moved to platforms.unity.shader. The
# IntegratedAssetProcessor class keeps `_resolve_shader_name` as a thin
# wrapper that threads the worker's per-instance cache into the moved
# function. Imported under an alias so the wrapper inside the class body
# references it without colliding with the module name.
from platforms.unity import shader as _unity_shader_module  # noqa: E402




# ---------------------------------------------------------------------------
# FBX UTILITIES  (axis detection + mesh node name extraction)
# ---------------------------------------------------------------------------

def read_fbx_mesh_node_names(fbx_path: Path) -> List[str]:
    """Extract mesh node names from a binary FBX file.

    In binary FBX, each scene object is stored as a Model property string
    with the format  "NodeName\\x00\\x01Model".  Scanning backwards from
    that separator gives the node name.

    Returns a list of unique node names found, in file order.
    Returns [] for non-binary or unreadable FBX files.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(262144)   # 256 KB covers node table for all common FBX files
    except Exception:
        return []

    if data[:20] != b'Kaydara FBX Binary  ':
        return []

    names: List[str] = []
    marker = b'\x00\x01Model'
    pos = 0
    while True:
        idx = data.find(marker, pos)
        if idx < 0:
            break
        # Walk backwards collecting printable ASCII bytes — that's the node name
        end = idx
        start = end
        while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
            start -= 1
        name = data[start:end].decode('ascii', errors='ignore').strip()
        if len(name) >= 2 and name not in names:
            names.append(name)
        pos = idx + len(marker)

    return names


# ---------------------------------------------------------------------------
# FBX node transforms — the "truer state" the converter was blind to.
#
# Asset packs bake scene placement into FBX node Lcl Translation/Rotation
# (e.g. Office furniture roots sit 25-50m off in X + a 90° Z-up→Y-up bake).
# Unity's importer uses node-LOCAL vertices (drops the scene offset, bakes
# the axis); O3DE's SceneAPI bakes the node WORLD transform unless told
# otherwise — the source of the cross-pack "scatter". This reader exposes
# the baked transforms so the reconciliation report + compensation can see
# them. See `mem:transform_truth/transform_truth_plan`.
# ---------------------------------------------------------------------------

def read_fbx_node_transforms(fbx_path: Path) -> Dict[str, dict]:
    """Parse a binary FBX and return each Model node's local transform.

    Returns ``{node_name: {"translation": [x,y,z],   # FBX units (cm)
                           "rotation":    [x,y,z],   # Euler degrees
                           "scaling":     [x,y,z]}}`` in file order.
    Empty dict for non-binary / unreadable FBX. Handles FBX <7500 (32-bit
    record offsets) and >=7500 (64-bit)."""
    try:
        data = fbx_path.read_bytes()
    except Exception:
        return {}
    if data[:21] != b"Kaydara FBX Binary  \x00":
        return {}

    version = struct.unpack("<I", data[23:27])[0]
    large = version >= 7500
    off_fmt, off_sz = ("<Q", 8) if large else ("<I", 4)

    def read_props(pos: int, num: int):
        props = []
        for _ in range(num):
            typ = chr(data[pos]); pos += 1
            if   typ == "Y": props.append(struct.unpack("<h", data[pos:pos+2])[0]); pos += 2
            elif typ == "C": props.append(bool(data[pos])); pos += 1
            elif typ == "I": props.append(struct.unpack("<i", data[pos:pos+4])[0]); pos += 4
            elif typ == "F": props.append(struct.unpack("<f", data[pos:pos+4])[0]); pos += 4
            elif typ == "D": props.append(struct.unpack("<d", data[pos:pos+8])[0]); pos += 8
            elif typ == "L": props.append(struct.unpack("<q", data[pos:pos+8])[0]); pos += 8
            elif typ in "fdlib":   # arrays — skip payload, transforms don't need them
                _len, _enc, comp = struct.unpack("<III", data[pos:pos+12]); pos += 12 + comp
                props.append(None)
            elif typ in "SR":
                ln = struct.unpack("<I", data[pos:pos+4])[0]; pos += 4
                raw = data[pos:pos+ln]; pos += ln
                props.append(raw if typ == "R" else raw.decode("utf-8", "ignore"))
            else:
                raise ValueError(f"unknown FBX prop type {typ!r}")
        return props, pos

    def read_record(pos: int):
        end_off  = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        num_prop = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        pos += off_sz                                   # property-list length (unused)
        name_len = data[pos]; pos += 1
        name = data[pos:pos+name_len].decode("utf-8", "ignore"); pos += name_len
        if end_off == 0:
            return None, pos
        props, pos = read_props(pos, num_prop)
        children, sentinel = [], (25 if large else 13)
        while pos < end_off - sentinel:
            child, pos = read_record(pos)
            if child is None:
                break
            children.append(child)
        return {"name": name, "props": props, "children": children}, end_off

    # Top-level records.
    roots, pos = [], 27
    try:
        while pos < len(data) - (25 if large else 13):
            rec, pos = read_record(pos)
            if rec is None:
                break
            roots.append(rec)
    except (ValueError, struct.error, IndexError):
        pass   # be tolerant — return whatever Model nodes we resolved

    objects = next((r for r in roots if r["name"] == "Objects"), None)
    if not objects:
        return {}

    def lcl(model: dict) -> dict:
        out = {"translation": [0.0, 0.0, 0.0],
               "rotation":    [0.0, 0.0, 0.0],
               "scaling":     [1.0, 1.0, 1.0]}
        key_map = {"Lcl Translation": "translation",
                   "Lcl Rotation":    "rotation",
                   "Lcl Scaling":     "scaling"}
        for p70 in (c for c in model["children"] if c["name"] == "Properties70"):
            for p in (c for c in p70["children"] if c["name"] == "P"):
                if p["props"] and p["props"][0] in key_map:
                    nums = [v for v in p["props"] if isinstance(v, float)]
                    if len(nums) >= 3:
                        out[key_map[p["props"][0]]] = nums[:3]
        return out

    result: Dict[str, dict] = {}
    for obj in objects["children"]:
        if obj["name"] != "Model":
            continue
        label = next((p for p in obj["props"] if isinstance(p, str)), "")
        # "Name\x00\x01Model" → "Name"
        node_name = label.split("\x00\x01")[0].split("::")[0].strip()
        if node_name and node_name not in result:
            result[node_name] = lcl(obj)
    return result


def _read_fbx_geometry_stats(fbx_path: Path, scale: float = 0.01) -> List[dict]:
    """Parse a binary FBX and return per-Geometry vertex stats (file order):
    ``{"centroid": [x,y,z], "min": [x,y,z], "max": [x,y,z]}`` in metres. Shared
    by `read_fbx_geometry_centroids` (modeled offset → auto-center) and
    `read_fbx_geometry_bbox_centers` (collider↔render alignment)."""
    import zlib
    try:
        data = fbx_path.read_bytes()
    except Exception:
        return []
    if data[:21] != b"Kaydara FBX Binary  \x00":
        return []
    version = struct.unpack("<I", data[23:27])[0]
    large = version >= 7500
    off_fmt, off_sz = ("<Q", 8) if large else ("<I", 4)
    sentinel = 25 if large else 13
    stats: List[dict] = []

    def read_props(pos, num, grab_vertices):
        verts = None
        for _ in range(num):
            typ = chr(data[pos]); pos += 1
            if typ in "YCIFDL":
                pos += {"Y": 2, "C": 1, "I": 4, "F": 4, "D": 8, "L": 8}[typ]
            elif typ in "fdlib":
                if typ == "d" and grab_vertices and verts is None:
                    length, enc, comp = struct.unpack("<III", data[pos:pos+12]); pos += 12
                    payload = data[pos:pos+comp]; pos += comp
                    if enc == 1:
                        payload = zlib.decompress(payload)
                    verts = list(struct.unpack(f"<{length}d", payload[:length*8]))
                else:
                    _l, _e, comp = struct.unpack("<III", data[pos:pos+12]); pos += 12 + comp
            elif typ in "SR":
                ln = struct.unpack("<I", data[pos:pos+4])[0]; pos += 4 + ln
            else:
                raise ValueError(typ)
        return verts, pos

    def read_record(pos):
        end_off = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        num_prop = struct.unpack(off_fmt, data[pos:pos+off_sz])[0]; pos += off_sz
        pos += off_sz
        name_len = data[pos]; pos += 1
        name = data[pos:pos+name_len].decode("utf-8", "ignore"); pos += name_len
        if end_off == 0:
            return None, pos
        is_geom = (name == "Geometry")
        _props, pos = read_props(pos, num_prop, grab_vertices=(name == "Vertices"))
        child_verts = _props if name == "Vertices" else None
        my_verts = None
        while pos < end_off - sentinel:
            child, pos = read_record(pos)
            if child is None:
                break
            if is_geom and child is not None and child.get("verts") is not None:
                my_verts = child["verts"]
        if is_geom and my_verts:
            xs, ys, zs = my_verts[0::3], my_verts[1::3], my_verts[2::3]
            n = len(xs)
            stats.append({
                "centroid": [sum(xs) / n * scale, sum(ys) / n * scale, sum(zs) / n * scale],
                "min": [min(xs) * scale, min(ys) * scale, min(zs) * scale],
                "max": [max(xs) * scale, max(ys) * scale, max(zs) * scale],
            })
        return {"name": name, "verts": child_verts}, end_off

    pos = 27
    try:
        while pos < len(data) - sentinel:
            rec, pos = read_record(pos)
            if rec is None:
                break
    except (ValueError, struct.error, IndexError):
        pass
    return stats


def read_fbx_geometry_centroids(fbx_path: Path, scale: float = 0.01) -> List[list]:
    """Vertex centroid (metres) of each Geometry node, file order. The centroid
    reveals where a mesh's geometry sits — the modeled offset O3DE bakes but
    Unity neutralizes (source of the auto-center). Empty for non-binary FBX."""
    return [s["centroid"] for s in _read_fbx_geometry_stats(fbx_path, scale)]


def read_fbx_geometry_bbox_centers(fbx_path: Path, scale: float = 0.01) -> List[list]:
    """Per-Geometry bounding-box CENTER (min+max)/2 in metres, file order.

    The bbox center (not the vertex centroid) is what aligns a simplified
    collision mesh to its detailed render mesh — a box vs a dense mesh have
    different centroids even when their BOUNDS coincide, so centroid-alignment
    pushes them apart while bbox-center alignment matches (desk COL: bbox delta
    0.868 ≈ the user's +0.875; centroid delta 0.597 would be wrong)."""
    return [[(s["min"][i] + s["max"][i]) * 0.5 for i in range(3)]
            for s in _read_fbx_geometry_stats(fbx_path, scale)]


def compute_single_mesh_autocenter(fbx_path: Path) -> Optional[list]:
    """Auto-center compensation for a SINGLE-mesh FBX: the O3DE
    `default_position` that cancels where the cook bakes the geometry, so the
    entity/instance transform alone places it — reproducing Unity's
    node-local import. Returns None for multi-mesh FBX (sub-meshes keep their
    FBX-relative bake) or when data is unreadable.

    Formula (calibrated to the Office desk drawers, 5-8 mm):
    ``(centroid_X, node_Y, -node_Z)`` in metres. Self-limiting — an
    already-centred mesh yields ~0, so only off-origin-modeled props move.
    See `mem:transform_truth/working_documentation`."""
    nodes = read_fbx_node_transforms(fbx_path)
    if len(nodes) != 1:                                   # multi-mesh → keep bake
        return None
    centroids = read_fbx_geometry_centroids(fbx_path)
    if len(centroids) != 1:
        return None
    node_t = next(iter(nodes.values()))["translation"]   # cm
    n = [v * 0.01 for v in node_t]                        # metres
    c = centroids[0]                                      # metres
    return [round(c[0], 4), round(n[1], 4), round(-n[2], 4)]


def compute_node_autocenters(fbx_path: Path) -> Dict[str, list]:
    """Per-node auto-center compensation — centres each mesh node so its
    entity/instance transform alone places it (reproducing Unity's import).
    Returns ``{node_name: [x, y, z]}`` (metres, O3DE), Model↔Geometry paired by
    file order; empty when counts mismatch.

    The formula depends on the FBX up-axis, both calibrated in-engine on the
    Office furniture:
      - **Z-up** (up_axis=2): ``(X, node_Y, -node_Z)`` — drawers, drawer_C.
      - **Y-up** (up_axis=1): ``(X, -node_Z, -node_Y)`` — the +90°X up-correction
        rotates the mesh, so the offset is expressed in the ORIGINAL (pre-
        rotation) axes with Y/Z swapped + negated (cabinet doors:
        node (-0.625, 1.25, 0.222) → comp (-0.625, -0.222, -1.25), user-verified).
    X source: the geometry centroid (Z-up, or a Y-up ROOT whose node X is the
    huge scene-layout junk), else the node's real local X (Y-up sub-node).
    See `mem:transform_truth/working_documentation`."""
    nodes = read_fbx_node_transforms(fbx_path)
    cents = read_fbx_geometry_centroids(fbx_path)
    if not nodes or len(nodes) != len(cents):
        return {}
    up_axis = read_fbx_up_axis(fbx_path)
    out: Dict[str, list] = {}
    for (name, nt), c in zip(nodes.items(), cents):
        n = [v * 0.01 for v in nt["translation"]]   # cm → m
        x = n[0] if (up_axis == 1 and abs(n[0]) <= 5.0) else c[0]
        comp = [x, -n[2], -n[1]] if up_axis == 1 else [x, n[1], -n[2]]
        out[name] = [round(v, 4) for v in comp]
    return out


def compute_node_bbox_centers(fbx_path: Path) -> Dict[str, list]:
    """``{node_name: [x,y,z]}`` bounding-box centre (metres) per Model node,
    Model↔Geometry paired by file order. Empty when counts mismatch."""
    nodes = read_fbx_node_transforms(fbx_path)
    bboxes = read_fbx_geometry_bbox_centers(fbx_path)
    if not nodes or len(nodes) != len(bboxes):
        return {}
    return {name: b for name, b in zip(nodes.keys(), bboxes)}


def compute_collider_alignment(col_fbx: Path, col_node: str,
                               render_fbx: Path, render_node: str) -> Optional[list]:
    """Translation that aligns a collision sub-mesh to its render counterpart,
    by matching bounding-box centres (NOT centroids — see
    `read_fbx_geometry_bbox_centers`). The render mesh's final position is its
    bbox centre plus its own auto-center; the collider is shifted to match.
    Returns ``[x,y,z]`` (metres, O3DE) or None when data is missing."""
    col_bb    = compute_node_bbox_centers(col_fbx).get(col_node)
    render_bb = compute_node_bbox_centers(render_fbx).get(render_node)
    if col_bb is None or render_bb is None:
        return None
    render_ac = compute_node_autocenters(render_fbx).get(render_node, [0.0, 0.0, 0.0])
    # render's final world bbox-centre, then cancel the collider's bbox-centre.
    return [round(render_bb[i] + render_ac[i] - col_bb[i], 4) for i in range(3)]


def read_fbx_material_names(fbx_path: Path) -> List[str]:
    """Extract material names from a binary FBX file, in file order.

    Binary FBX stores each scene object as `<Name>\\x00\\x01<Class>`. The
    Material class marker is `\\x00\\x01Material`. Scanning backwards from
    that separator gives the material name as the FBX engine sees it —
    which is what SceneAPI's ModelAssetBuilderComponent later exposes as
    `MaterialAsset::m_name` / `ModelMaterialSlot::m_displayName`. That is
    the exact string the O3DE MaterialComponent label resolver matches
    against, so it is the only correct key for `materialsByLabel`.

    Returns [] for non-binary or unreadable FBX files. Uses a larger read
    window than `read_fbx_mesh_node_names` because the Materials block in
    the Objects section is typically further into the file than Models.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(1048576)   # 1 MB covers the Material block on common assets
    except Exception:
        return []

    if data[:20] != b'Kaydara FBX Binary  ':
        return []

    names: List[str] = []
    marker = b'\x00\x01Material'
    pos = 0
    while True:
        idx = data.find(marker, pos)
        if idx < 0:
            break
        end = idx
        start = end
        while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
            start -= 1
        name = data[start:end].decode('ascii', errors='ignore').strip()
        if len(name) >= 1 and name not in names:
            names.append(name)
        pos = idx + len(marker)

    return names


def read_fbx_up_axis(fbx_path: Path) -> int:
    """Read UpAxis from an FBX binary file's GlobalSettings block.

    FBX binary encodes: \x06\x00\x00\x00UpAxis ... I <int32 value>
    Value 1 = Y-up (Maya-style), 2 = Z-up (Blender-style), -1 = unknown.

    O3DE is Z-up.  Y-up FBX files need a coordinate correction sidecar so
    that O3DE's asset processor imports them in the correct orientation.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(65536)  # GlobalSettings appears near the top

        gs_pos = data.find(b'GlobalSettings')
        if gs_pos < 0:
            return -1

        # Binary FBX stores string "UpAxis" as: uint32-length(6) + "UpAxis"
        up_pos = data.find(b'\x06\x00\x00\x00UpAxis', gs_pos)
        if up_pos < 0:
            return -1

        # After the 10-byte prefix, the P-record continues:
        #   S + uint32(3) + "int" + S + uint32(7) + "Integer" + S + uint32(0)
        # then type marker 'I' (0x49) + int32 little-endian value.
        # Scan the next 60 bytes for: 0x49 + [0-2] + 0x00 0x00 0x00
        chunk = data[up_pos + 10 : up_pos + 70]
        for i in range(len(chunk) - 4):
            if (chunk[i] == 0x49
                    and chunk[i + 2] == 0
                    and chunk[i + 3] == 0
                    and chunk[i + 4] == 0):
                val = chunk[i + 1]
                if 0 <= val <= 2:
                    return val
        return -1

    except Exception:
        return -1


def build_fbx_node_paths(mesh_entities: list, all_game_objects: dict,
                          fbx_stem: str, fbx_node_names: List[str]) -> dict:
    """Derive FBX node paths from the Unity prefab hierarchy.

    Uses actual FBX node names (read from the binary FBX) for the path
    segments, not GO names — GO names can differ from FBX node names.

    Matching strategy per entity:
      1. Exact name match between go.name and a known FBX node name.
      2. Single-entity + single-node fallback: use the one available node.
      3. No match: fall back to go.name with a warning (may not resolve in O3DE).

    Returns {entity_file_id: "RootNode.ActualFBXNodeName[.Child...]"}.
    """
    mesh_ids = {go.file_id for go in mesh_entities}
    fbx_node_set = set(fbx_node_names)

    # Root of this FBX group = entity whose parent is not in the group
    root_go = next(
        (go for go in mesh_entities if go.parent_id not in mesh_ids),
        mesh_entities[0]
    )

    result = {}

    def resolve_node_name(go_name: str) -> str:
        """Map a GO name to the best available FBX node name."""
        if go_name in fbx_node_set:
            return go_name
        # Single entity, single FBX node — unambiguous fallback
        if len(mesh_entities) == 1 and len(fbx_node_names) == 1:
            return fbx_node_names[0]
        return go_name   # best-effort; O3DE may not find it

    def recurse(go, parent_path):
        node_name = resolve_node_name(go.name)
        node_path = f"{parent_path}.{node_name}"
        result[go.file_id] = node_path
        for child_id in go.children_ids:
            child = all_game_objects.get(child_id)
            if child and child.file_id in mesh_ids:
                recurse(child, node_path)

    recurse(root_go, "RootNode")
    return result


# =============================================================================
# COLLISION SUB-MESH RESOLUTION
# Maps a Unity MeshCollider's `m_Mesh = {guid, fileID}` to the FBX node that
# holds its collision geometry. See `mem:asset_packs/import_catalogue` for the
# topologies (T1–T4) and the verified fileID scheme.
# =============================================================================

def resolve_collision_node(mesh_file_id: str,
                            fbx_node_names: List[str],
                            render_node: Optional[str] = None) -> Optional[str]:
    """Resolve one collision sub-mesh to its FBX node path.

    Order:
      1. ``render_node`` — when a render entity uses the same (guid, fileID),
         reuse the node path ``build_fbx_node_paths`` derived for it, BUT only
         if it points at a real FBX node. That helper can fall back to the GO
         name, which may not exist in the FBX (e.g. NatureManufacture GO
         ``…_LOD2`` vs FBX node ``…_LOD02``); trusting that fallback would
         select an empty node. Genuine matches handle hash/negative fileIDs
         we can't decode arithmetically.
      2. Single-mesh FBX ⇒ the one node, regardless of fileID.
      3. Linear fileID decode against file-order ``fbx_node_names``:
         ``index = (fileID - 4300000) // 2`` (Unity's legacy mesh fileID
         scheme; verified ground-truth across all three target packs). This is
         the authority for the common positive-fileID case (T3 multi-LOD,
         T4 dedicated ``_COL``).
      4. Out-of-range / non-decodable ⇒ the correlated node if any, else the
         first node (best-effort whole-FBX).

    Returns ``RootNode.<NodeName>`` or None when the FBX has no mesh nodes.
    """
    if not fbx_node_names:
        return None
    node_set = set(fbx_node_names)
    if render_node and render_node.split(".")[-1] in node_set:
        return render_node
    if len(fbx_node_names) == 1:
        return f"RootNode.{fbx_node_names[0]}"
    try:
        fid = int(mesh_file_id)
    except (TypeError, ValueError):
        fid = None
    if fid is not None and fid >= 4300000:
        idx = (fid - 4300000) // 2
        if 0 <= idx < len(fbx_node_names):
            return f"RootNode.{fbx_node_names[idx]}"
    return render_node or f"RootNode.{fbx_node_names[0]}"


def physx_group_name(fbx_stem: str, node_path: str,
                     fbx_node_names: List[str]) -> str:
    """Deterministic PhysX MeshGroup name → `.pxmesh` product name.

    Single-mesh FBX collapses to the bare stem (matches the Mushroom
    reference: ``mushroom_big1.fbx.pxmesh``). Multi-mesh FBXs suffix the
    selected node's leaf so each sub-mesh yields a distinct product
    (e.g. ``StairsMod_Ground_COL-StairsMod_Ground_Collision``)."""
    if len(fbx_node_names) <= 1:
        return fbx_stem
    return f"{fbx_stem}-{node_path.split('.')[-1]}"


# Phase A.3: `Y_UP_ROTATION`, `_euler_deg_to_quat`, `_quat_mul`,
# `_resolve_mesh_settings`, and `write_fbx_assetinfo` moved to
# `targets.o3de.assetinfo_writer`. Re-exported here so existing call
# sites in this module + any tests reaching for them work unchanged.
from targets.o3de.assetinfo_writer import (  # noqa: E402
    Y_UP_ROTATION,
    _euler_deg_to_quat,
    _quat_mul,
    _resolve_mesh_settings,
    write_fbx_assetinfo,
)


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp. Mirrors `project_manager._utc_now_iso` so
    the worker doesn't pull project_manager just for a date string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_project_root(start: Path) -> Optional[Path]:
    """Walk up from ``start`` looking for the directory that contains
    ``project.json`` (the O3DE project root). Returns that directory,
    or None when no such ancestor exists within 24 levels."""
    probe = Path(start)
    for _ in range(24):
        if (probe / "project.json").is_file():
            return probe
        if probe.parent == probe:
            return None
        probe = probe.parent
    return None


def _project_relative_path(target: Path) -> Optional[str]:
    """Return ``target`` as a forward-slash path relative to its
    O3DE project root, preserving original case. Returns None when no
    project root is found above ``target``.

    Used by the prefab writer and scene converter for the ``Source``
    field on nested-instance entries — O3DE's ``PrefabLoader`` resolves
    that field as a project-root-relative filesystem path with original
    case, NOT a lowercased cache hint. Asset HINTS (mesh / material
    references) go through `_derive_asset_hint_root` instead, which is
    the lowercased variant of the same project-relative idea."""
    target = Path(target)
    start  = target if target.is_dir() else target.parent
    root   = _find_project_root(start)
    if root is None:
        return None
    try:
        rel = target.relative_to(root)
    except ValueError:
        return None
    return str(rel).replace("\\", "/")


def _derive_asset_hint_root(output_root: Path) -> str:
    """Compute the assetHint prefix every emitted reference must carry.

    O3DE resolves an ``assetHint`` by matching it against a product
    asset's cache-relative path: the path from the project's scan-folder
    root (the dir containing ``project.json``) down to the asset,
    lowercased with forward slashes. So the hint root must be the output
    directory's path relative to that project root.

    Resolution order:
      1. Walk up from ``output_root`` looking for ``project.json``. When
         found, return ``output_root`` relative to it (lowercased).
      2. No ``project.json`` above us → fall back to the first
         case-insensitive ``assets`` path segment and take everything
         from there. Handles output trees that aren't inside a built
         project yet but still follow the ``Assets/...`` convention.
      3. Last resort → ``assets/<leaf>`` (the legacy leaf-only behaviour).

    The leaf-only fallback was the ONLY behaviour before 2026-05-28 and
    silently dropped intermediate folders, leaving every mesh / material
    reference unresolved when output landed deeper than
    ``<proj>/Assets/<leaf>``.
    """
    output_root = Path(output_root)

    root = _find_project_root(output_root)
    if root is not None:
        try:
            rel = output_root.relative_to(root)
            return "/".join(part.lower() for part in rel.parts)
        except ValueError:
            pass

    # First `assets` segment in the path.
    parts = output_root.parts
    for i, part in enumerate(parts):
        if part.lower() == "assets":
            return "/".join(seg.lower() for seg in parts[i:])

    # Legacy leaf-only fallback.
    return f"assets/{output_root.name.lower()}"



class IntegratedAssetProcessor:
    """Processes Unity prefabs with materials to O3DE format"""
    
    def __init__(self, unity_assets_root: Path, output_root: Path,
                 log_callback=None,
                 convert_smoothness_to_roughness: bool = False,
                 *,
                 material_settings: Optional[Dict] = None,
                 mesh_settings:     Optional[Dict] = None,
                 scope_root:        Optional[Path] = None,
                 state_index:       Optional[Dict] = None,
                 platform=None):
        self.unity_assets_root = unity_assets_root
        self.output_root = output_root
        self.log = log_callback or print

        # Per-run config flags
        self.convert_smoothness_to_roughness = convert_smoothness_to_roughness

        # Phase C — source-platform plugin. Defaults to the Unity reference
        # plugin via the registry. Other plugins (Unreal / Godot / Blender)
        # plug in here once they're authored. The worker stays
        # platform-agnostic at the orchestration level; per-method calls
        # consult ``self.platform`` for platform-specific behaviour.
        if platform is None:
            from platforms import get as _get_platform
            platform = _get_platform("unity")
            if platform is None:
                raise RuntimeError(
                    "No 'unity' platform registered. The platforms package "
                    "must be importable before constructing the worker."
                )
        self.platform = platform

        # F-9 settings copied at construction time so worker mutations don't
        # round-trip back into the project state until to_outputs() runs.
        # `material_settings` carries {defaults, shader_profiles,
        # shader_mappings, overrides}; None falls back to the legacy
        # hard-coded extraction path so older call sites keep working.
        # `mesh_settings` is consumed in F-9.I.3. `state_index` carries the
        # last-emitted per-asset fingerprints for the F-9.I.5 patch worker.
        self._material_settings = material_settings or {}
        self._mesh_settings     = mesh_settings or {}
        self._scope_root        = scope_root
        self._state_index_in    = state_index or {}
        # F-9.I.4 — per-asset emission fingerprints. Populated as each
        # asset is written. `to_outputs()` returns it under the "state_index"
        # key; the call site merges onto `project.outputs.state_index`
        # (rather than replacing) so a partial run doesn't drop entries for
        # assets not touched in this pass.
        self._state_index_out: Dict[str, Dict[str, dict]] = {
            "materials": {},
            "meshes":    {},
            "textures":  {},
            "prefabs":   {},
        }

        self.asset_db = AssetDatabase(unity_assets_root)
        # Bind the worker-owned AssetDatabase into the active platform so
        # the platform's parse methods reuse this GUID index instead of
        # building a fresh one. Worker and platform share state until the
        # worker is destructed.
        if hasattr(self.platform, "bind_asset_db"):
            self.platform.bind_asset_db(self.asset_db)
        
        # Output structure
        self.prefabs_dir = output_root / "Prefabs"
        self.materials_dir = output_root / "Materials"
        self.textures_dir = output_root / "Textures"
        self.meshes_dir = output_root / "Meshes"

        # Create directories
        self.prefabs_dir.mkdir(parents=True, exist_ok=True)
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.textures_dir.mkdir(parents=True, exist_ok=True)
        self.meshes_dir.mkdir(parents=True, exist_ok=True)

        # The converter's bookkeeping (entity maps, asset index, coverage)
        # used to live in `<output_root>/.ImporterData/`. That directory is
        # gone: everything is now persisted into the project file by the
        # tab worker via `processor.to_outputs()`. Per-prefab entity maps
        # are also kept in `self._entity_map_cache` for cross-prefab
        # override reads within the same run.
        self._project_prefab_records: Dict[str, Dict] = {}
        # F-6: per-material metadata (shader name, source path, bound
        # texture slots). Surfaced on the Materials tab so the user can
        # see which shaders need a mapping.
        self._material_metadata: Dict[str, Dict] = {}
        # F-6: cached `shader_guid → "Shader Name"` so we don't re-read
        # the same .shader file once per material. Built-ins (Unity's
        # Standard, etc.) don't resolve to a file in the project; we
        # fall back to a small lookup table for those.
        self._shader_name_cache: Dict[str, str] = {}
        
        # Track processed assets
        self.processed_materials: Dict[str, str] = {}  # guid -> output_path
        self.processed_textures: Dict[str, str] = {}  # guid -> output_path
        # GUIDs whose Unity _MetallicGlossMap has been re-baked with an inverted
        # alpha channel for use as an O3DE roughness texture. Keyed by source
        # texture GUID; value is the output relative path (Textures/Foo_Roughness.png).
        self.processed_inverted_textures: Dict[str, str] = {}
        self.processed_meshes: Dict[str, Path] = {}  # guid -> output Path
        self.processed_prefabs: Set[str] = set()  # Track processed prefab GUIDs

        # Component processing stats — accumulated by processors via ctx.stats
        self.stats: Dict[str, int] = {}

        # =====================================================================
        # Coverage tracker — populated incrementally; written by finalize()
        # =====================================================================
        self.coverage = CoverageTracker()

        # =====================================================================
        # Cross-prefab asset index. Populated as materials/meshes/prefabs are
        # processed so nested-instance override emission can resolve a GUID to
        # an O3DE assetHint. Written by finalize() as <output_root>/asset_index.json.
        # =====================================================================
        self.asset_index: Dict[str, Dict[str, Any]] = {
            "materials": {},   # {unity_mat_guid: o3de_material_assetHint}
            "meshes":    {},   # {unity_mesh_guid: fbx_output_stem}
            "prefabs":   {},   # {unity_prefab_guid: source_path_in_assets}
        }

        # In-memory cache of source-prefab entity-map sidecars, keyed by the
        # source prefab's resolved path. Avoids re-reading the same sidecar
        # when a prefab is referenced from multiple consumers.
        self._entity_map_cache: Dict[str, Optional[Dict]] = {}

        # Get project folder name for asset hints (lowercase). This is the
        # output root's basename — kept for log/display use.
        self.project_name = output_root.name.lower()

        # Root prefix every assetHint must carry. O3DE resolves an assetHint
        # by matching it against the product asset's cache-relative path —
        # the path from the project's scan-folder root (the directory that
        # contains `project.json`) down to the asset, lowercased, forward
        # slashes. So the hint root MUST be the output directory's path
        # relative to the O3DE project root, not merely its leaf name.
        #
        # Example: output at `<proj>/Assets/Art/Alien Fantasy Forest` must
        # produce `assets/art/alien fantasy forest`, NOT
        # `assets/alien fantasy forest` (the old leaf-only behaviour, which
        # dropped intermediate folders like `Art/` and left every mesh /
        # material reference unresolved in-engine).
        self.asset_hint_root = _derive_asset_hint_root(output_root)

        self.entity_id_counter = 1000000

        # Component processor registry — sourced from the active platform
        # plugin. Phase C wires this through `SourcePlatform.component_processors()`
        # so a non-Unity plugin can ship its own per-engine processor set
        # (e.g. an Unreal plugin's StaticMeshActor / SpotLightComponent
        # translators) without touching the worker.
        self.component_processors = self.platform.component_processors()
        self.component_dispatch   = build_dispatch_table(self.component_processors)
        self.log(
            f"  Registered {len(self.component_processors)} component "
            f"processor(s) from platform '{self.platform.NAME}'"
        )

        # Surface the smoothness→roughness conversion mode at run start so
        # the log makes it obvious which texture pipeline is active.
        if self.convert_smoothness_to_roughness:
            if PIL_AVAILABLE:
                self.log("  [Config] Smoothness→Roughness texture conversion: ENABLED")
            else:
                self.log("  [Config] Smoothness→Roughness texture conversion REQUESTED "
                         "but Pillow is not installed. Install with: pip install Pillow")
    
    def process_prefab(self, prefab_path: Path) -> bool:
        """Process a single Unity prefab"""
        self.log(f"\n{'='*60}")
        self.log(f"Processing prefab: {prefab_path.name}")
        self.log(f"{'='*60}")
        
        try:
            # Parse Unity prefab
            game_objects, transform_map = self._parse_unity_prefab(prefab_path)
            
            if not game_objects:
                self.log("  ⚠ No GameObjects found in prefab")
                return False
            
            # Find root GameObject
            root_go = None
            for go in game_objects.values():
                if go.parent_id is None:
                    root_go = go
                    break
            
            if not root_go:
                self.log("  ⚠ No root GameObject found")
                return False
            
            self.log(f"  Found {len(game_objects)} GameObjects")
            
            # Process materials referenced by this prefab
            all_material_guids = set()
            all_mesh_guids = set()
            for go in game_objects.values():
                all_material_guids.update(go.material_guids)
                if go.mesh_guid:
                    all_mesh_guids.add(go.mesh_guid)
            
            # Count colliders and rigidbodies in this prefab
            prefab_collider_count = sum(len(go.colliders) for go in game_objects.values())
            prefab_rigidbody_count = sum(1 for go in game_objects.values() if go.has_rigidbody)

            self.log(f"  Found {len(all_material_guids)} unique material references")
            self.log(f"  Found {len(all_mesh_guids)} unique mesh references")
            self.log(f"  Found {prefab_collider_count} colliders, {prefab_rigidbody_count} rigidbodies")
            
            material_mapping = {}
            for mat_guid in all_material_guids:
                if mat_guid:
                    o3de_mat_path = self._process_material(mat_guid)
                    if o3de_mat_path:
                        material_mapping[mat_guid] = o3de_mat_path
            
            # --- Copy FBX files to output ---
            fbx_output_paths = {}   # {mesh_guid: Path}
            for mesh_guid in all_mesh_guids:
                if mesh_guid:
                    out_path = self._process_mesh(mesh_guid)
                    if out_path:
                        fbx_output_paths[mesh_guid] = out_path

            # --- Build per-entity mesh hints + write .assetinfo ---
            # mesh_mapping keyed by entity file_id (not guid) so each entity
            # gets its own named sub-mesh rather than the combined FBX model.
            mesh_mapping = {}   # {entity_file_id: assetHint}

            # FBX-internal material names per entity, in submesh order.
            # SceneAPI extracts these from the FBX as MaterialAsset::m_name,
            # and ModelMaterialSlot::m_displayName is set from that. The
            # O3DE MaterialComponent label resolver matches against exactly
            # these strings — they are the only valid keys for the
            # `materialsByLabel` map. Pair ordinally with go.material_guids.
            fbx_material_labels = {}   # {entity_file_id: [fbx_name_0, ...]}

            from collections import defaultdict
            entities_by_guid = defaultdict(list)
            for go in game_objects.values():
                if go.mesh_guid and go.mesh_guid in fbx_output_paths:
                    entities_by_guid[go.mesh_guid].append(go)

            # --- Collect MeshCollider collision-mesh references ---
            # A collider's geometry is the sub-mesh m_Mesh = {guid, fileID}
            # (see `mem:asset_packs/import_catalogue`). The guid may be a
            # dedicated _COL FBX or the GO's own render FBX; fileID picks the
            # sub-mesh. Fall back to the GO's render mesh when m_Mesh has no
            # guid of its own.
            # Each ref also carries the colliding entity's RENDER mesh
            # (render_guid, go_name, render_fileID) so a dedicated _COL FBX can
            # be aligned to the render mesh it collides for (bbox-center match).
            collider_refs = []
            for go in game_objects.values():
                for c in go.colliders:
                    if c.get('type') != 'MeshCollider':
                        continue
                    cg = c.get('mesh_guid') or go.mesh_guid
                    if cg:
                        collider_refs.append(
                            (cg, str(c.get('mesh_file_id', '') or ''),
                             bool(c.get('convex')),
                             go.mesh_guid or '', go.name, str(go.mesh_file_id or ''))
                        )

            # Axis A — scrape dedicated collision FBXs not already copied as
            # render meshes, so they get an output file + assetinfo to cook.
            for ref in collider_refs:
                cg = ref[0]
                if cg not in fbx_output_paths:
                    cpath = self._process_mesh(cg)
                    if cpath:
                        fbx_output_paths[cg] = cpath

            collider_refs_by_guid = defaultdict(list)
            for cg, cf, cx, rg, rname, rfid in collider_refs:
                if cg in fbx_output_paths:
                    collider_refs_by_guid[cg].append((cf, cx, rg, rname, rfid))

            # (guid, fileID) -> .pxmesh assetHint, consumed by the collider
            # component to point at the exact per-sub-mesh physics asset.
            collider_pxmesh_mapping = {}

            # Every FBX needing an assetinfo: render meshes ∪ collision meshes.
            assetinfo_guids = set(entities_by_guid) | set(collider_refs_by_guid)

            for mesh_guid in assetinfo_guids:
                entity_list = entities_by_guid.get(mesh_guid, [])
                fbx_path = fbx_output_paths[mesh_guid]
                fbx_stem = fbx_path.name.rsplit('.', 1)[0]  # "Closet_A.FBX" → "Closet_A"

                # Read actual mesh node names from the FBX binary
                fbx_node_names = read_fbx_mesh_node_names(fbx_path)
                self.log(f"    [Mesh] FBX nodes found: {fbx_node_names}")

                # Read FBX-internal material names (Material class objects in
                # the binary FBX), in file order. This is what SceneAPI will
                # expose as ModelMaterialSlot::m_displayName at runtime.
                fbx_mat_names = read_fbx_material_names(fbx_path)
                if fbx_mat_names:
                    self.log(f"    [Mesh] FBX materials found: {fbx_mat_names}")
                elif entity_list:
                    self.log(f"    [Mesh] ⚠ No FBX-internal material names "
                             f"read from {fbx_path.name} — materialsByLabel "
                             f"will be empty for entities using this mesh.")

                node_paths = (build_fbx_node_paths(entity_list, game_objects,
                                                   fbx_stem, fbx_node_names)
                              if entity_list else {})
                entity_node_map = {
                    go.name: node_paths[go.file_id]
                    for go in entity_list if go.file_id in node_paths
                }

                # Render-correlation index: a collider sharing a render
                # sub-mesh reuses the node path already derived for it.
                render_node_index = {
                    (mesh_guid, go.mesh_file_id or ''): node_paths[go.file_id]
                    for go in entity_list if go.file_id in node_paths
                }

                # Axis B — one PhysX group per distinct collision sub-mesh of
                # this FBX. Dedup by group name so two colliders on the same
                # sub-mesh share one group (and one pxmesh).
                physx_specs = []
                seen_groups = set()
                for cf, cx, rg, rname, rfid in collider_refs_by_guid.get(mesh_guid, []):
                    node = resolve_collision_node(
                        cf, fbx_node_names, render_node_index.get((mesh_guid, cf)))
                    if not node:
                        self.log(f"    [Physics] ⚠ could not resolve collision "
                                 f"node (fileID {cf}) in {fbx_path.name}")
                        continue
                    gname = physx_group_name(fbx_stem, node, fbx_node_names)
                    collider_pxmesh_mapping[(mesh_guid, cf)] = (
                        f"{self.asset_hint_root}/meshes/{gname}.fbx.pxmesh")
                    if gname in seen_groups:
                        continue
                    seen_groups.add(gname)
                    spec = {"name": gname, "node_paths": [node], "convex": cx}
                    # Align a dedicated _COL FBX to the render mesh it collides
                    # for (bbox-center match) — a collider FBX has its own
                    # geometry that doesn't self-center to the render. Skips when
                    # the collision IS the render mesh (same FBX → ~0).
                    if rg and rg != mesh_guid and rg in fbx_output_paths:
                        rfbx = fbx_output_paths[rg]
                        rnodes = read_fbx_mesh_node_names(rfbx)
                        rnode = (rname if rname in rnodes
                                 else (rnodes[0] if len(rnodes) == 1 else None))
                        if rnode:
                            align = compute_collider_alignment(
                                fbx_path, node.split(".")[-1], rfbx, rnode)
                            if align and any(abs(v) > 1e-4 for v in align):
                                spec["translation"] = align
                                self.log(f"    [Physics] collider→render align "
                                         f"{gname} → {align}")
                    physx_specs.append(spec)

                # F-5 `physx_mesh` override — force-generate a whole-mesh
                # ("everything") collision pxmesh for this FBX even when no
                # Unity MeshCollider references it. One triangle group over all
                # the FBX's mesh nodes, named after the stem.
                if _resolve_mesh_settings(self._mesh_settings, mesh_guid).get("physx_mesh"):
                    all_nodes = (list(entity_node_map.values())
                                 or [f"RootNode.{n}" for n in fbx_node_names])
                    if all_nodes and fbx_stem not in seen_groups:
                        seen_groups.add(fbx_stem)
                        physx_specs.append(
                            {"name": fbx_stem, "node_paths": all_nodes, "convex": False})
                        self.log(f"    [Physics] physx_mesh override → whole-mesh "
                                 f"collision for {fbx_path.name}")

                # Pass the platform's source-axis correction quaternion
                # (follow-up: item 5). Unity supplies its Y-up→Z-up quat;
                # other plugins ship their own constant via
                # `platforms.<name>.coordinates`.
                correction_quat = getattr(
                    self.platform, "correction_quat", None,
                )
                write_fbx_assetinfo(
                    fbx_path, fbx_stem, entity_node_map, self.log,
                    physx_specs=physx_specs or None,
                    mesh_settings=self._mesh_settings,
                    mesh_guid=mesh_guid,
                    correction_quat=correction_quat,
                )
                # F-9.I.4 — record mesh fingerprint AFTER the assetinfo
                # exists on disk so the recorded output_files list includes
                # both the .fbx copy and the .assetinfo sidecar. The cached
                # entity_node_map + physx_specs + fbx_stem are what the Patch
                # worker replays at re-emit time without re-parsing prefabs
                # (see `mem:mesh_patch_worker/mesh_patch_worker_plan` §I.1).
                source_mesh_path = self.asset_db.resolve_guid(mesh_guid)
                if source_mesh_path is not None:
                    self._record_mesh_state(
                        mesh_guid, source_mesh_path, fbx_path,
                        fbx_stem=fbx_stem,
                        entity_node_map=entity_node_map,
                        physx_specs=physx_specs,
                    )

                for go in entity_list:
                    if go.file_id in node_paths:
                        group_name = f"{fbx_stem}-{go.name}"
                        mesh_mapping[go.file_id] = (
                            f"{self.asset_hint_root}/meshes/{group_name}.fbx.azmodel"
                        )
                    # Per-entity material label list. Pair ordinally with the
                    # Unity MeshRenderer slot order; truncate to whichever is
                    # shorter so we never index past either array. Multi-mesh
                    # FBX caveat: this uses the FBX-wide material list, not a
                    # per-submesh Connections-resolved list. For single-mesh
                    # FBX (the common Unity case) this matches; for multi-mesh
                    # FBX with different materials per mesh node, a Connections
                    # parse would be needed.
                    if go.material_guids and fbx_mat_names:
                        slot_count = min(len(go.material_guids), len(fbx_mat_names))
                        fbx_material_labels[go.file_id] = list(fbx_mat_names[:slot_count])
            
            # Create O3DE prefab
            output_name = prefab_path.stem
            output_path = self.prefabs_dir / f"{output_name}.prefab"
            
            self._create_o3de_prefab(
                root_go,
                game_objects,
                transform_map,
                material_mapping,
                mesh_mapping,
                fbx_material_labels,
                output_path,
                collider_pxmesh_mapping,
            )

            # F-9.I.4 — record the prefab's fingerprint after every
            # dependent material/mesh has its own entry. The prefab hash
            # folds in their input_hashes so a profile or mesh-override
            # change downstream marks this prefab dirty too.
            prefab_guid = self.asset_db.path_to_guid(prefab_path) or str(prefab_path)
            self._record_prefab_state(
                prefab_guid,
                prefab_path,
                output_path,
                sorted(g for g in all_material_guids if g),
                sorted(g for g in all_mesh_guids if g),
            )

            self.log(f"  ✓ Created O3DE prefab: {output_path.name}")
            return True
        
        except Exception as e:
            self.log(f"  ✗ Error processing prefab: {e}")
            import traceback
            traceback.print_exc()
            return False

    # =========================================================================
    # FINALIZE — write coverage and asset-index reports
    # =========================================================================

    def finalize(self) -> None:
        """End-of-run hook. No disk writes — the tab worker fetches
        `to_outputs()` and persists it into the project file.

        Logs a one-line summary of what the run accumulated so the user
        sees the same end-of-run signal they used to get from the
        `.ImporterData/` writes."""
        ai = self.asset_index
        cov = self.coverage.to_dict()
        self.log(f"\n  ✓ Run recorded: "
                 f"{len(self._project_prefab_records)} prefabs, "
                 f"{len(ai['materials'])} mats, "
                 f"{len(ai['meshes'])} meshes, "
                 f"{len(cov.get('unhandled_component_types', {}))} unhandled "
                 f"component type(s), "
                 f"{len(cov.get('unhandled_override_paths', {}))} unhandled "
                 f"override path(s)")

    # -------------------------------------------------------------------------
    # F-9.I.5 — Patch worker
    # -------------------------------------------------------------------------

    def patch(self) -> Dict[str, list]:
        """Re-emit only the assets whose input fingerprint has changed
        since the last run.

        Compares each saved entry in `state_index_in` against a recomputed
        current input_hash. Mismatches are dirty: their cache is cleared
        and they're re-processed, which records a fresh entry in
        `state_index_out`.

        Scope:
          - **Materials** — hash diff on `{profile, override}` + missing
            outputs. Re-emit via ``_process_material``.
          - **Meshes** — hash diff on `mesh_settings_effective` + missing
            outputs. Re-emit via ``write_fbx_assetinfo`` using the cached
            ``entity_node_map`` / ``physx_specs`` /
            ``fbx_stem`` stored on the state-index entry. See
            `mem:mesh_patch_worker/mesh_patch_worker_plan` §I.2.
          - **Prefabs** — deferred. Go via the orchestrator's
            "re-run dirty prefabs" path in F-8, which calls
            ``process_prefab(...)`` on each dirty prefab's source.

        Returns a summary with keys: ``materials_dirty``,
        ``materials_emitted``, ``meshes_dirty``, ``meshes_emitted``,
        ``meshes_need_reparse``. The last bucket lists meshes whose
        cached node map went stale (FBX nodes renamed) — Run All is the
        recovery path.
        """
        summary: Dict[str, list] = {
            "materials_dirty":     [],
            "materials_emitted":   [],
            "meshes_dirty":        [],
            "meshes_emitted":      [],
            "meshes_need_reparse": [],
        }
        saved_materials = (self._state_index_in or {}).get("materials") or {}

        for guid, saved_entry in saved_materials.items():
            source_path_str = saved_entry.get("source_path") or ""
            if not source_path_str:
                continue
            source_path = Path(source_path_str)
            if not source_path.exists():
                # Source disappeared — orphan cleanup is a future feature.
                continue

            # Resolve profile chain for THIS material under current settings.
            shallow = self.asset_db.parse_material(source_path)
            if not shallow:
                continue
            shader_guid = shallow.get("shader_guid", "") or ""
            shader_fid  = shallow.get("shader_fileid", 0) or 0
            shader_name = self._resolve_shader_name(shader_guid, shader_fid)
            profile     = self._resolve_profile_for_material(guid, shader_name)
            override    = (self._material_settings.get("overrides") or {}).get(guid) or {}

            payload = {
                "asset_kind":   "material",
                "source_path":  str(source_path),
                "source_mtime": self._mtime_or_zero(source_path),
                "profile":      profile or {},
                "override":     override,
            }
            current_hash = self._canonical_hash(payload)
            saved_hash   = saved_entry.get("input_hash") or ""

            # Also dirty when the prior output is missing on disk.
            output_files = saved_entry.get("output_files") or []
            outputs_missing = any(not Path(p).exists() for p in output_files) if output_files else True

            if current_hash == saved_hash and not outputs_missing:
                continue   # clean

            summary["materials_dirty"].append(guid)

            # Drop caches so _process_material actually re-emits rather
            # than returning the cached asset_hint.
            self.processed_materials.pop(guid, None)
            self.asset_db.material_cache = {
                k: v for k, v in self.asset_db.material_cache.items()
                if k[0] != str(source_path)
            }

            result = self._process_material(guid)
            if result is not None:
                summary["materials_emitted"].append(guid)

        # ----- Mesh loop ----------------------------------------------------
        # Mirrors the material loop: hash diff + missing-output check +
        # in-engine modification covered by missing-output (since touching
        # the file in editor doesn't drop it).
        self._patch_meshes(summary)

        self.log(
            f"  Patch: materials {len(summary['materials_dirty'])} dirty / "
            f"{len(summary['materials_emitted'])} re-emitted; "
            f"meshes {len(summary['meshes_dirty'])} dirty / "
            f"{len(summary['meshes_emitted'])} re-emitted "
            f"({len(summary['meshes_need_reparse'])} need full reparse)"
        )
        return summary

    def _patch_meshes(self, summary: Dict[str, list]) -> None:
        """Mesh dirty-detect + assetinfo re-emit. Populates the three
        mesh-keyed buckets on ``summary``.

        Soundness gate: a saved entry without the cached
        ``entity_node_map`` cannot be patched (no map to replay). Those
        entries land in ``meshes_need_reparse`` and skip — one Run All
        repopulates them with the full set of fields. The same bucket
        catches the rare "FBX nodes were renamed in Unity" case where
        the cached map references nodes that no longer exist.
        """
        import shutil

        saved_meshes = (self._state_index_in or {}).get("meshes") or {}
        if not saved_meshes:
            return

        platform_correction = getattr(self.platform, "correction_quat", None)

        for guid, saved_entry in saved_meshes.items():
            source_path_str = saved_entry.get("source_path") or ""
            if not source_path_str:
                continue
            source_path = Path(source_path_str)
            if not source_path.exists():
                # Source disappeared — orphan cleanup is a future feature.
                continue

            output_files = saved_entry.get("output_files") or []
            if not output_files:
                continue
            fbx_path = Path(output_files[0])

            # Hash diff vs current effective mesh_settings.
            eff = _resolve_mesh_settings(self._mesh_settings, guid)
            payload = {
                "asset_kind":    "mesh",
                "source_path":   str(source_path),
                "source_mtime":  self._mtime_or_zero(source_path),
                "mesh_settings": eff,
            }
            current_hash = self._canonical_hash(payload)
            saved_hash   = saved_entry.get("input_hash") or ""

            outputs_missing = any(not Path(p).exists() for p in output_files)
            if current_hash == saved_hash and not outputs_missing:
                continue   # clean

            summary["meshes_dirty"].append(guid)

            entity_node_map = dict(saved_entry.get("entity_node_map") or {})
            physx_specs     = list(saved_entry.get("physx_specs") or [])
            fbx_stem        = saved_entry.get("fbx_stem") or ""

            if (not entity_node_map and not physx_specs) or not fbx_stem:
                # Pre-I.1 entry, or one written by older code. Cannot
                # replay without re-parsing the prefab — flag it. A
                # collision-only FBX legitimately has no entity_node_map
                # but does carry physx_specs, so don't flag that case.
                summary["meshes_need_reparse"].append(guid)
                self.log(
                    f"  [Patch] WARNING: mesh {guid[:8]}… has no cached "
                    f"node maps — needs full Run All to repopulate."
                )
                continue

            # Soundness check: cached node-path values must reference
            # nodes that still exist in the current FBX.
            current_node_names = set()
            if fbx_path.exists():
                try:
                    current_node_names = set(read_fbx_mesh_node_names(fbx_path))
                except Exception:
                    current_node_names = set()
            stale_paths = [
                v for v in entity_node_map.values()
                if v and v.split(".")[-1] not in current_node_names
                and v.split(".")[-1] != fbx_stem
            ]
            if current_node_names and stale_paths:
                summary["meshes_need_reparse"].append(guid)
                self.log(
                    f"  [Patch] WARNING: mesh {guid[:8]}… FBX node names "
                    f"changed (stale: {stale_paths[:3]}) — needs full "
                    f"Run All to re-derive node paths."
                )
                continue

            # Re-copy the source FBX if its mtime advanced since last emit.
            saved_mtime = float(saved_entry.get("source_mtime") or 0.0)
            current_mtime = self._mtime_or_zero(source_path)
            if current_mtime > saved_mtime and fbx_path.exists():
                try:
                    fbx_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, fbx_path)
                except Exception as exc:
                    self.log(
                        f"  [Patch] ERROR: failed to re-copy FBX "
                        f"{source_path.name}: {exc}"
                    )
                    continue

            # Re-emit the .assetinfo with current mesh_settings.
            try:
                write_fbx_assetinfo(
                    fbx_path, fbx_stem, entity_node_map, self.log,
                    physx_specs=physx_specs or None,
                    mesh_settings=self._mesh_settings,
                    mesh_guid=guid,
                    correction_quat=platform_correction,
                )
            except Exception as exc:
                self.log(
                    f"  [Patch] ERROR: failed to re-emit assetinfo for "
                    f"{fbx_path.name}: {exc}"
                )
                continue

            # Refresh the state-index entry (input_hash, last_emitted,
            # output_files reflect the post-patch state).
            self._record_mesh_state(
                guid, source_path, fbx_path,
                fbx_stem=fbx_stem,
                entity_node_map=entity_node_map,
                physx_specs=physx_specs,
            )
            summary["meshes_emitted"].append(guid)

    def to_outputs(self) -> dict:
        """Consolidate this run's bookkeeping into the dict the project
        file stores under `outputs.asset_processor`. Replaces the old
        `.ImporterData/` sidecars entirely.

        Caller (the tab worker) augments this with `last_run`,
        `last_input_hash`, and `last_status` before calling
        `pm.update_outputs("asset_processor", ...)`. The F-9 state index
        is a project-wide sibling of stage outputs, so the caller routes
        `self.state_index()` separately via
        `pm.update_outputs("state_index", ...)`.
        """
        return {
            "prefabs":           dict(self._project_prefab_records),
            "materials":         dict(self.asset_index["materials"]),
            "material_metadata": dict(self._material_metadata),
            "meshes":             dict(self.asset_index["meshes"]),
            "coverage":           self.coverage.to_dict(),
        }

    def state_index(self) -> dict:
        """F-9.I.4 — return the per-asset emission fingerprints recorded
        during this run. The caller merges this onto the project file's
        existing `outputs.state_index` so untouched assets keep their
        prior entries."""
        return {
            "materials": dict(self._state_index_out["materials"]),
            "meshes":    dict(self._state_index_out["meshes"]),
            "textures":  dict(self._state_index_out["textures"]),
            "prefabs":   dict(self._state_index_out["prefabs"]),
        }
    
    def _parser_context(self):
        """Build a fresh ``UnityParseContext`` from the worker's
        state. Each parser entry-point constructs one on demand."""
        from platforms.unity.prefab import UnityParseContext
        return UnityParseContext(
            log=self.log,
            coverage=self.coverage,
            component_dispatch=self.component_dispatch,
        )

    def _parse_unity_prefab(self, prefab_path: Path) -> Tuple[Dict[str, GameObject], Dict[str, str]]:
        """Parse Unity prefab and extract GameObjects.

        Body extracted to ``platforms.unity.prefab.parse_unity_prefab``
        (follow-up: item 1a). This method now builds a
        ``UnityParseContext`` and delegates."""
        from platforms.unity.prefab import parse_unity_prefab
        return parse_unity_prefab(self._parser_context(), prefab_path)

    def _parse_transform(self, transform_data: Dict, anchor: str,
                        game_objects: Dict, transform_map: Dict) -> None:
        """Body extracted to ``platforms.unity.prefab.parse_transform``."""
        from platforms.unity.prefab import parse_transform
        return parse_transform(self._parser_context(),
                                transform_data, anchor, game_objects, transform_map)

    def _parse_game_object(self, go_data: Dict, anchor: str,
                          game_objects: Dict, transform_map: Dict) -> None:
        """Body extracted to ``platforms.unity.prefab.parse_game_object``."""
        from platforms.unity.prefab import parse_game_object
        return parse_game_object(self._parser_context(),
                                  go_data, anchor, game_objects, transform_map)
    
    def _parse_prefab_instance_in_prefab(self, instance_data: Dict, anchor: str,
                                        game_objects: Dict, transform_map: Dict) -> None:
        """Body extracted to
        ``platforms.unity.prefab.parse_prefab_instance_in_prefab``."""
        from platforms.unity.prefab import parse_prefab_instance_in_prefab
        return parse_prefab_instance_in_prefab(
            self._parser_context(),
            instance_data, anchor, game_objects, transform_map,
        )

    def _build_hierarchy(self, game_objects: Dict, transform_map: Dict,
                         components_data: Dict) -> None:
        """Body extracted to ``platforms.unity.prefab.build_hierarchy``."""
        from platforms.unity.prefab import build_hierarchy
        return build_hierarchy(
            self._parser_context(),
            game_objects, transform_map, components_data,
        )
    
    
    # Phase A.4 — shader-name resolution moved to platforms.unity.shader.
    # The class keeps a thin wrapper so call sites
    # (`self._resolve_shader_name(...)` inside `_process_material`) read the
    # same way. The wrapper threads the worker's per-instance cache + its
    # AssetDatabase into the moved function.
    _UNITY_BUILTIN_SHADERS = _unity_shader_module.UNITY_BUILTIN_SHADERS

    def _resolve_shader_name(self, shader_guid: str, shader_fileid: int = 0) -> str:
        return _unity_shader_module.resolve_shader_name(
            self.asset_db, shader_guid, shader_fileid,
            cache=self._shader_name_cache,
        )

    def _resolve_profile_for_material(self, material_guid: str,
                                       shader_name: str) -> Optional[Dict]:
        """F-9 profile chain resolver — see :meth:`_resolve_profile_name_for_material`
        for the lookup precedence. Returns the profile DICT only;
        callers that need the profile *name* (for provenance / state-
        index recording) should use the sibling method."""
        return self._resolve_profile_name_for_material(material_guid, shader_name)[1]

    def _resolve_profile_name_for_material(self, material_guid: str,
                                            shader_name: str
                                            ) -> Tuple[str, Optional[Dict]]:
        """F-9 profile chain resolver returning ``(profile_name, profile_dict)``.

            overrides[guid].profile
              → shader_mappings[shader_name]
              → defaults.profile

        ``profile_name`` is the empty string when no settings were
        supplied (legacy mode — extraction falls back to the
        hard-coded TEXTURE_MAP / PROPERTY_MAP path) or when the chain
        resolved no name. The two are returned together so the state-
        index recorder can record provenance without re-walking the
        chain.
        """
        settings = self._material_settings or {}
        if not settings:
            return "", None
        profiles = settings.get("shader_profiles") or {}

        overrides = settings.get("overrides") or {}
        guid_entry = overrides.get(material_guid) or {}
        profile_name = guid_entry.get("profile") or ""

        if not profile_name:
            mappings = settings.get("shader_mappings") or {}
            profile_name = mappings.get(shader_name) or ""

        if not profile_name:
            defaults = settings.get("defaults") or {}
            profile_name = defaults.get("profile") or ""

        if not profile_name:
            return "", None
        return profile_name, profiles.get(profile_name)

    def _resolve_effective_materialtype(self, material_guid: str,
                                         profile: Optional[Dict]) -> str:
        """Resolve the materialType string that lands in the emitted
        `.material` file. The chain is:

            overrides[guid].materialtype  (raw escape hatch)
              → profile.target_materialtype
              → resolve_materialtype_path() default

        The result always passes through `resolve_materialtype_path` so a
        bare filename like 'StandardPBR.materialtype' expands to its
        @gemroot path before landing on disk.
        """
        from project_manager import resolve_materialtype_path
        settings = self._material_settings or {}
        overrides = settings.get("overrides") or {}
        raw_escape = (overrides.get(material_guid) or {}).get("materialtype") or ""
        if raw_escape:
            return resolve_materialtype_path(raw_escape)
        if profile is not None:
            return resolve_materialtype_path(profile.get("target_materialtype"))
        return resolve_materialtype_path(None)

    # -------------------------------------------------------------------------
    # F-9.I.4 — State index recording
    # -------------------------------------------------------------------------

    @staticmethod
    def _canonical_hash(payload) -> str:
        """sha256 digest over a JSON-canonical encoding of `payload`. Keys
        sorted, separators tight, default str fallback so Path / set show up
        as strings — all to keep the hash stable across runs that differ only
        in dict-iteration order or Python-version representation quirks."""
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          default=str)
        return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _mtime_or_zero(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except (OSError, ValueError):
            return 0.0

    def _record_material_state(self, guid: str, source_path: Path,
                                output_path: Path,
                                profile: Optional[Dict],
                                profile_name: str = "",
                                shader_name: str = "") -> None:
        """Record fingerprint + F-9 provenance on the material's
        state-index entry. ``profile_name`` and ``shader_name`` are
        recorded as plain strings so the MaterialTab can surface
        "last emitted by profile X (shader Y)" in the row tooltip — the
        user's way to verify a .material on disk was produced by the
        F-9 chain rather than legacy hardcoded extraction. Empty
        strings mean "no profile resolved" (legacy fall-back path)."""
        override_entry = (self._material_settings.get("overrides") or {}).get(guid) or {}
        payload = {
            "asset_kind":   "material",
            "source_path":  str(source_path),
            "source_mtime": self._mtime_or_zero(source_path),
            "profile":      profile or {},
            "override":     override_entry,
        }
        self._state_index_out["materials"][guid] = {
            "source_path":  str(source_path),
            "source_mtime": payload["source_mtime"],
            "output_files": [str(output_path)],
            "input_hash":   self._canonical_hash(payload),
            "last_emitted": _utc_now_iso(),
            "profile_name": profile_name,
            "shader_name":  shader_name,
        }

    def _record_texture_state(self, guid: str, source_path: Path,
                               output_rel: str) -> None:
        output_abs = (self.output_root / output_rel) if output_rel else None
        payload = {
            "asset_kind":   "texture",
            "source_path":  str(source_path),
            "source_mtime": self._mtime_or_zero(source_path),
        }
        self._state_index_out["textures"][guid] = {
            "source_path":  str(source_path),
            "source_mtime": payload["source_mtime"],
            "output_files": [str(output_abs)] if output_abs else [],
            "input_hash":   self._canonical_hash(payload),
            "last_emitted": _utc_now_iso(),
        }

    def _record_mesh_state(self, guid: str, source_path: Path,
                            output_path: Path,
                            fbx_stem: str = "",
                            entity_node_map: Optional[Dict[str, str]] = None,
                            physx_specs: Optional[list] = None,
                            ) -> None:
        """Record a mesh's fingerprint + the cached prefab-parse state the
        Patch worker replays to re-emit `.assetinfo` without re-parsing
        every consumer prefab: ``fbx_stem``, ``entity_node_map`` (visual
        groups) and ``physx_specs`` (per-sub-mesh PhysX groups). See
        `mem:mesh_patch_worker/mesh_patch_worker_plan` §I.1 and
        `mem:physx_mesh_collider/physx_mesh_collider_plan`."""
        eff = _resolve_mesh_settings(self._mesh_settings, guid)
        assetinfo = Path(str(output_path) + ".assetinfo")
        payload = {
            "asset_kind":     "mesh",
            "source_path":    str(source_path),
            "source_mtime":   self._mtime_or_zero(source_path),
            "mesh_settings":  eff,
        }
        outputs = [str(output_path)]
        if assetinfo.exists():
            outputs.append(str(assetinfo))
        # Transform-truth auto-compensation flags — which auto-processes are
        # APPLICABLE to this FBX, so the Mesh tab can mark the mesh and the
        # user can toggle them. `auto_center` carries the per-node derived
        # values (filtered to non-trivial); `y_up` flags the Y-up rotation.
        acs = {k: v for k, v in compute_node_autocenters(output_path).items()
               if any(abs(float(x)) > 1e-4 for x in v)}
        auto_center_value = acs or None
        self._state_index_out["meshes"][guid] = {
            "source_path":              str(source_path),
            "source_mtime":             payload["source_mtime"],
            "output_files":             outputs,
            "input_hash":               self._canonical_hash(payload),
            "last_emitted":             _utc_now_iso(),
            "fbx_stem":                 fbx_stem,
            "entity_node_map":          dict(entity_node_map or {}),
            "physx_specs":              list(physx_specs or []),
            "auto_flags": {
                "auto_center": auto_center_value,            # [x,y,z] or None
                "y_up":        read_fbx_up_axis(output_path) == 1,
            },
        }

    def _record_prefab_state(self, guid: str, source_path: Path,
                              output_path: Path,
                              dep_material_guids: List[str],
                              dep_mesh_guids:     List[str]) -> None:
        """Prefab hash is derivative — it folds in the input_hash of every
        material/mesh the prefab references. Editing a profile invalidates
        the dependent materials, which then invalidates this prefab via the
        propagated hash."""
        dep_material_hashes = sorted(
            (self._state_index_out["materials"].get(g, {}) or {}).get("input_hash", "")
            for g in (dep_material_guids or [])
        )
        dep_mesh_hashes = sorted(
            (self._state_index_out["meshes"].get(g, {}) or {}).get("input_hash", "")
            for g in (dep_mesh_guids or [])
        )
        payload = {
            "asset_kind":     "prefab",
            "source_path":    str(source_path),
            "source_mtime":   self._mtime_or_zero(source_path),
            "dep_materials":  dep_material_hashes,
            "dep_meshes":     dep_mesh_hashes,
        }
        self._state_index_out["prefabs"][guid] = {
            "source_path":  str(source_path),
            "source_mtime": payload["source_mtime"],
            "output_files": [str(output_path)],
            "input_hash":   self._canonical_hash(payload),
            "last_emitted": _utc_now_iso(),
        }

    def _process_material(self, material_guid: str) -> Optional[str]:
        """Process Unity material and create O3DE material"""
        # Check if already processed
        if material_guid in self.processed_materials:
            return self.processed_materials[material_guid]
        
        # Find material file
        material_path = self.asset_db.resolve_guid(material_guid)
        if not material_path:
            self.log(f"    ⚠ Material GUID not found: {material_guid}")
            self.coverage.record_missing_material(material_guid)
            return None
        
        self.log(f"    Processing material: {material_path.name}")

        # F-9 profile resolution:
        # 1. Shallow parse (no profile) to read the m_Shader ref. YAML body
        #    is cached so the subsequent profile-aware parse is cheap.
        # 2. Resolve the friendly shader name via the .shader file (or the
        #    built-in lookup table for Unity Standard etc.).
        # 3. Walk the profile chain  override → mapping → default. None
        #    keeps the legacy hard-coded extraction.
        # 4. Re-parse with the selected profile.
        shallow = self.asset_db.parse_material(material_path)
        if not shallow:
            self.log(f"      ⚠ Failed to parse material")
            return None
        shader_guid = shallow.get("shader_guid", "") or ""
        shader_fid  = shallow.get("shader_fileid", 0) or 0
        shader_name = self._resolve_shader_name(shader_guid, shader_fid)
        profile_name, profile = self._resolve_profile_name_for_material(
            material_guid, shader_name)
        if profile is not None:
            material_data = self.asset_db.parse_material(material_path, profile=profile)
            if not material_data:
                self.log(f"      ⚠ Failed to re-parse material with profile")
                return None
        else:
            material_data = shallow

        # Warn about texture-bound property names the active extraction map
        # doesn't know how to route. Almost always indicates a custom /
        # asset-store shader using non-standard slot names. Author or pick a
        # different profile in F-10 if one of these recurs across a pack.
        unmapped = material_data.get('unmapped_texture_props', [])
        if unmapped:
            shader_path = material_data.get('shader') or shader_name or '<unknown shader>'
            self.log(
                f"      ⚠ '{material_path.stem}' has bound textures on "
                f"unrecognized property names {unmapped} "
                f"(shader: {shader_path}). Those textures will be skipped — "
                f"add the aliases to the active shader profile's texture_map "
                f"(or its ignore_unmapped list) to handle them."
            )

        # Process textures
        texture_paths = {}
        mg_source_guids = material_data.get('metallic_gloss_source_guids', set())
        for o3de_prop, texture_guid in material_data.get('textures', {}).items():
            # The roughness slot wants an INVERTED alpha when the source came
            # from Unity's _MetallicGlossMap (alpha=smoothness, not roughness).
            # The metallic slot still uses the raw texture — its RGB is correct.
            if (o3de_prop == 'roughness'
                    and self.convert_smoothness_to_roughness
                    and texture_guid in mg_source_guids):
                texture_output = self._process_metallic_gloss_as_roughness(texture_guid)
            else:
                texture_output = self._process_texture(texture_guid)
            if texture_output:
                texture_paths[o3de_prop] = texture_output

        # F-9 per-slot texture overrides — overrides[guid].textures wins per
        # slot. Stored as the user wrote them; no copy / repath. Set after
        # the auto-extraction loop so the user override always wins over
        # whatever Unity bound on that slot.
        override_entry = (self._material_settings.get("overrides") or {}).get(material_guid) or {}
        override_textures = override_entry.get("textures") or {}
        for slot, override_path in override_textures.items():
            if override_path:
                texture_paths[slot] = override_path

        # Create O3DE material
        output_name = material_path.stem
        output_path = self.materials_dir / f"{output_name}.material"

        # F-9 materialType resolution: override.materialtype (raw escape
        # hatch) → profile.target_materialtype → builtin StandardPBR
        # fallback. The resolver expands bare filenames into @gemroot paths.
        material_type_path = self._resolve_effective_materialtype(material_guid, profile)

        o3de_material = {
            "materialType": material_type_path,
            "materialTypeVersion": 5,
            "propertyValues": {}
        }
        
        # Add texture properties with RELATIVE paths (../Textures/filename)
        for o3de_prop, texture_rel_path in texture_paths.items():
            # Convert "Textures/filename" to "../Textures/filename" for relative path from Materials/ folder
            if texture_rel_path.startswith("Textures/"):
                relative_texture_path = f"../{texture_rel_path}"
            else:
                relative_texture_path = texture_rel_path
            
            # Handle special property naming
            # For "occlusion.specular", it becomes "occlusion.specularTextureMap"
            if o3de_prop == 'occlusion.specular':
                property_name = 'occlusion.specularTextureMap'
            else:
                property_name = f"{o3de_prop}.textureMap"
            
            o3de_material["propertyValues"][property_name] = relative_texture_path
        
        # Add scalar/color/enum properties
        for o3de_prop, value in material_data.get('properties', {}).items():
            if isinstance(value, list):
                # Color property - ensure 4 components
                color = value[:3] if len(value) >= 3 else [1.0, 1.0, 1.0]
                alpha = value[3] if len(value) >= 4 else 1.0
                o3de_material["propertyValues"][o3de_prop] = [
                    float(color[0]),
                    float(color[1]),
                    float(color[2]),
                    float(alpha)
                ]
            elif isinstance(value, str):
                # Enum property (e.g. opacity.mode = "Blended")
                o3de_material["propertyValues"][o3de_prop] = value
            else:
                # Scalar property
                o3de_material["propertyValues"][o3de_prop] = float(value)
        
        # ---------------------------------------------------------------
        # Opacity sanity pass.
        # `opacity.alphaSource = "Packed"` tells O3DE to read alpha from the
        # bound baseColor texture. With no baseColor texture in the final
        # material, that sample returns 0 → a Cutout material renders fully
        # invisible and a Blended material renders fully transparent.
        # Strip the opacity flags in that case so the material falls back to
        # the (correct) Opaque default and at least shows the constant
        # baseColor.color. The most common cause is a Unity material whose
        # _MainTex/_BaseMap GUID does not resolve in the project being
        # converted (missing texture, package-only texture, etc.).
        # ---------------------------------------------------------------
        prop_values = o3de_material["propertyValues"]
        opacity_mode = prop_values.get('opacity.mode')
        if opacity_mode in ('Cutout', 'Blended') and 'baseColor.textureMap' not in prop_values:
            prop_values.pop('opacity.mode', None)
            prop_values.pop('opacity.alphaSource', None)
            prop_values.pop('opacity.factor', None)
            self.log(
                f"      ⚠ '{output_name}' source declared opacity.mode="
                f"{opacity_mode} but no baseColor texture survived "
                f"resolution — opacity flags dropped to avoid an invisible "
                f"material. Check that the Unity material's _MainTex / "
                f"_BaseMap GUID is resolvable in this project."
            )

        # Write material file
        with open(output_path, 'w') as f:
            json.dump(o3de_material, f, indent=4)

        # Generate gem-style asset hint: assets/projectname/materials/filename.azmaterial
        asset_hint = f"{self.asset_hint_root}/materials/{output_path.stem}.azmaterial"
        self.processed_materials[material_guid] = asset_hint
        self.asset_index["materials"][material_guid] = asset_hint
        # F-6 metadata. shader_name was already resolved up front to drive
        # the F-9 profile chain; reuse it here.
        self._material_metadata[material_guid] = {
            "asset_hint":     asset_hint,
            "shader_name":    shader_name,
            "shader_guid":    shader_guid,
            "source_path":    str(material_path),
            "source_stem":    material_path.stem,
            "textures_bound": sorted(texture_paths.keys()),
        }
        # F-9.I.4 — record fingerprint for the patch worker, with the
        # resolved profile name + shader name as provenance so the
        # MaterialTab tooltip can show "last emitted by profile X".
        self._record_material_state(
            material_guid, material_path, output_path, profile,
            profile_name=profile_name, shader_name=shader_name,
        )

        self.log(f"      ✓ Created material with {len(texture_paths)} textures")

        return asset_hint
    
    def _process_texture(self, texture_guid: str) -> Optional[str]:
        """Process texture - copy to output directory"""
        if texture_guid in self.processed_textures:
            return self.processed_textures[texture_guid]
        
        texture_path = self.asset_db.resolve_guid(texture_guid)
        if not texture_path or texture_path.suffix.lower() not in self.asset_db.texture_extensions:
            self.coverage.record_missing_texture(texture_guid)
            return None
        
        # Copy texture to output
        output_path = self.textures_dir / texture_path.name
        
        try:
            if not output_path.exists():
                shutil.copy2(texture_path, output_path)

            relative_path = f"Textures/{output_path.name}"
            self.processed_textures[texture_guid] = relative_path
            # F-9.I.4 — fingerprint for the patch worker.
            self._record_texture_state(texture_guid, texture_path, relative_path)

            return relative_path

        except Exception as e:
            self.log(f"      ⚠ Failed to copy texture {texture_path.name}: {e}")
            return None

    # =========================================================================
    # SMOOTHNESS → ROUGHNESS  (alpha-channel re-bake)
    # =========================================================================

    def _process_metallic_gloss_as_roughness(self, texture_guid: str) -> Optional[str]:
        """
        Re-bake a Unity `_MetallicGlossMap` texture for use as an O3DE roughness map.

        Unity packs smoothness into the alpha channel of the metallic-gloss map.
        O3DE samples the roughness texture directly — it has no built-in
        smoothness-to-roughness inversion. To make the texture sample correctly
        as roughness we invert the alpha channel (alpha = 1 − alpha) and write
        the result as `<stem>_Roughness.png` into the Textures/ folder.

        The RGB channels are left untouched: the metallic slot still references
        the original texture and reads metallic from RGB exactly as Unity wrote
        it. Only the roughness slot routes through this method.

        Returns None if Pillow isn't installed, the source can't be loaded, or
        the file lacks an alpha channel (in which case the caller falls back to
        plain copy via _process_texture and the user gets a coverage warning).
        """
        if texture_guid in self.processed_inverted_textures:
            return self.processed_inverted_textures[texture_guid]

        if not PIL_AVAILABLE:
            self.log("      ⚠ Smoothness→roughness conversion requested but Pillow is "
                     "not installed; falling back to raw texture copy.")
            self.coverage.warn(
                "Smoothness→Roughness conversion enabled but Pillow is missing. "
                "Install with: pip install Pillow"
            )
            return self._process_texture(texture_guid)

        texture_path = self.asset_db.resolve_guid(texture_guid)
        if not texture_path or texture_path.suffix.lower() not in self.asset_db.texture_extensions:
            self.coverage.record_missing_texture(texture_guid)
            return None

        # Re-baked file lives next to the originals but always as PNG, because
        # PNG preserves alpha losslessly and O3DE's image processor accepts it.
        output_name = f"{texture_path.stem}_Roughness.png"
        output_path = self.textures_dir / output_name
        relative_path = f"Textures/{output_name}"

        try:
            if not output_path.exists():
                with Image.open(texture_path) as img:
                    # Force RGBA so we always have an alpha channel to invert,
                    # even when the source was RGB-only (in which case the
                    # synthetic alpha is fully opaque → inverted is fully
                    # transparent → roughness=0, which is correct for a
                    # "fully smooth" interpretation of a missing smoothness map).
                    rgba = img.convert('RGBA')
                    r, g, b, a = rgba.split()
                    # Pillow's `Image.eval` runs `1 − x` on the 8-bit channel.
                    inverted_a = a.point(lambda v: 255 - v)
                    out = Image.merge('RGBA', (r, g, b, inverted_a))
                    out.save(output_path, format='PNG')
                self.log(f"      ✓ Wrote inverted-alpha roughness map: {output_name}")
            else:
                self.log(f"      Inverted-alpha roughness map already exists: {output_name}")

            self.processed_inverted_textures[texture_guid] = relative_path
            return relative_path

        except Exception as e:
            self.log(f"      ⚠ Failed to invert alpha for {texture_path.name}: {e}")
            self.coverage.warn(
                f"Failed to re-bake smoothness→roughness for {texture_path.name}: {e}"
            )
            # Fall back to the plain copy so the slot still has SOMETHING bound.
            return self._process_texture(texture_guid)

    def _process_mesh(self, mesh_guid: str) -> Optional[Path]:
        """Process mesh — copy to output directory. Returns output Path or None."""
        if mesh_guid in self.processed_meshes:
            cached = self.processed_meshes[mesh_guid]
            # Return Path if cached, or None
            return cached if isinstance(cached, Path) else None

        mesh_path = self.asset_db.resolve_guid(mesh_guid)
        if not mesh_path or mesh_path.suffix.lower() not in self.asset_db.mesh_extensions:
            self.coverage.record_missing_mesh(mesh_guid)
            return None

        self.log(f"    Processing mesh: {mesh_path.name}")
        output_path = self.meshes_dir / mesh_path.name

        try:
            if not output_path.exists():
                shutil.copy2(mesh_path, output_path)
                self.log(f"      Copied mesh file")
            else:
                self.log(f"      Mesh already exists")

            self.processed_meshes[mesh_guid] = output_path
            # Record the FBX stem; per-entity sub-mesh hints are computed
            # later (see process_prefab() FBX assetinfo block).
            self.asset_index["meshes"][mesh_guid] = output_path.stem
            return output_path

        except Exception as e:
            self.log(f"      Failed to process mesh {mesh_path.name}: {e}")
            return None
    
    
    # =========================================================================
    # PREFAB / ENTITY EMITTERS  (target-side bodies live in
    # `targets.o3de.prefab_writer`. The class keeps thin wrappers so every
    # existing call site reads the same way; the worker is passed in as
    # the first argument so the writers can reach `self.log`,
    # `self.coverage`, `self.asset_db`, etc.).
    # =========================================================================

    def _generate_component_id(self) -> int:
        from targets.o3de.prefab_writer import generate_component_id
        return generate_component_id(self)

    def _generate_entity_id(self) -> str:
        from targets.o3de.prefab_writer import generate_entity_id
        return generate_entity_id(self)

    def _quaternion_to_euler(self, quaternion: Tuple[float, float, float, float]) -> List[float]:
        from targets.o3de.prefab_writer import quaternion_to_euler
        return quaternion_to_euler(quaternion)

    def _convert_to_o3de_coordinates(self, unity_transform: Transform) -> Tuple[Transform, bool]:
        from targets.o3de.prefab_writer import convert_to_o3de_coordinates
        return convert_to_o3de_coordinates(unity_transform)

    def _create_o3de_prefab(self, root_go: GameObject, all_game_objects: Dict,
                           transform_map: Dict, material_mapping: Dict,
                           mesh_mapping: Dict,
                           fbx_material_labels: Dict[str, List[str]],
                           output_path: Path,
                           collider_pxmesh_mapping: Optional[Dict] = None) -> None:
        from targets.o3de.prefab_writer import create_o3de_prefab
        return create_o3de_prefab(
            self, root_go, all_game_objects, transform_map,
            material_mapping, mesh_mapping, fbx_material_labels, output_path,
            collider_pxmesh_mapping or {},
        )

    def _write_entity_map_sidecar(self, prefab_output_path: Path,
                                  root_go: GameObject,
                                  all_game_objects: Dict,
                                  entity_id_map: Dict[str, str],
                                  fbx_material_labels: Dict[str, List[str]]) -> None:
        from targets.o3de.prefab_writer import write_entity_map_sidecar
        return write_entity_map_sidecar(
            self, prefab_output_path, root_go, all_game_objects,
            entity_id_map, fbx_material_labels,
        )

    def _load_entity_map_sidecar(self, source_prefab_path: Path) -> Optional[Dict]:
        from targets.o3de.prefab_writer import load_entity_map_sidecar
        return load_entity_map_sidecar(self, source_prefab_path)

    def _create_container_entity(self, root_go: GameObject) -> Dict:
        from targets.o3de.prefab_writer import create_container_entity
        return create_container_entity(self, root_go)

    def _create_nested_prefab_instance(self, go: GameObject, prefab_path: Path,
                                       parent_entity_id: str) -> Dict:
        from targets.o3de.prefab_writer import create_nested_prefab_instance
        return create_nested_prefab_instance(self, go, prefab_path, parent_entity_id)

    def _make_bare_entity(self, entity_id: str, name: str,
                          parent_entity_id: str) -> Dict:
        from targets.o3de.prefab_writer import make_bare_entity
        return make_bare_entity(self, entity_id, name, parent_entity_id)

    def _create_entity_recursive(self, go: GameObject, all_game_objects: Dict,
                                 entities_dict: Dict, instances_dict: Dict,
                                 entity_id_map: Dict,
                                 material_mapping: Dict, mesh_mapping: Dict,
                                 fbx_material_labels: Dict[str, List[str]],
                                 parent_entity_id: str = None) -> str:
        from targets.o3de.prefab_writer import create_entity_recursive
        return create_entity_recursive(
            self, go, all_game_objects, entities_dict, instances_dict,
            entity_id_map, material_mapping, mesh_mapping,
            fbx_material_labels, parent_entity_id,
        )

SETTINGS_FILE = Path(__file__).parent / "converter_settings.json"


def main():
    """Launch the unified PySide6 GUI, opening directly on the Prefab tab."""
    import sys
    from main_app import main as app_main
    sys.argv.append('--tab=prefab')
    app_main()


if __name__ == '__main__':
    main()
