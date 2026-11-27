"""
=============================================================================
FBX READER
=============================================================================

Reads what the converter needs from a binary FBX without any FBX library:
the record tree, a record's properties, and the **import facts** of a file -
its up axis, its unit, and for each node its place in the tree, its
transform, its geometric transform and its materials.

Why the geometric transform matters
-----------------------------------
A node of an FBX can carry a *geometric transform*: an offset, turn and scale
that apply to the node's own geometry and to nothing else (3ds Max writes one
for every object whose pivot was moved). Unity bakes it into the mesh it
imports. O3DE's scene pipeline, given an advanced coordinate rule, applies
only that rule to the node's raw vertices. So the rule has to carry the
geometric transform, or the model sits beside where Unity has the mesh.
``targets/o3de/assetinfo_writer.py`` builds that rule from these facts.

Why the node tree matters
-------------------------
O3DE selects the mesh of a model by the node's path in the file
(``RootNode.Body.Door``), and a node that is not named in a selection follows
its parent. A path built from anything but the file's own tree selects the
wrong nodes, or all of them. ``platforms/unity/model_import.py`` also needs
the tree: Unity makes one object per node.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, List

BINARY_MAGIC = b"Kaydara FBX Binary  \x00"

UP_AXIS_Y = 1
UP_AXIS_Z = 2
UP_AXIS_UNKNOWN = -1


# =============================================================================
# RECORD TREE
# =============================================================================

def read_records(fbx_path: Path, int_arrays=()) -> List[dict]:
    """The record tree of a binary FBX: ``[{name, props, children}, ...]``.
    Array payloads are skipped (their place in ``props`` holds None), except
    the 32-bit integer arrays of the records named in ``int_arrays``, which
    are read as lists, and an array of no elements, which is an empty list
    (so a geometry without vertices can be told). Empty for a file that is
    missing or is not binary FBX.
    Handles both the 32-bit record headers of files before version 7500 and
    the 64-bit ones after."""
    try:
        data = Path(fbx_path).read_bytes()
    except OSError:
        return []
    if data[:21] != BINARY_MAGIC:
        return []

    large = struct.unpack("<I", data[23:27])[0] >= 7500
    offset_format, offset_size = ("<Q", 8) if large else ("<I", 4)
    sentinel = 25 if large else 13
    scalar_formats = {"Y": ("<h", 2), "I": ("<i", 4), "F": ("<f", 4), "D": ("<d", 8), "L": ("<q", 8)}

    def read_properties(position: int, count: int, keep_int_arrays: bool):
        properties = []
        for _ in range(count):
            kind = chr(data[position]); position += 1
            if kind in scalar_formats:
                fmt, size = scalar_formats[kind]
                properties.append(struct.unpack(fmt, data[position:position + size])[0]); position += size
            elif kind == "C":
                properties.append(bool(data[position])); position += 1
            elif kind in "fdlib":
                length, encoding, stored = struct.unpack("<III", data[position:position + 12])
                position += 12
                values = [] if length == 0 else None
                if kind == "i" and keep_int_arrays and length:
                    payload = data[position:position + stored]
                    payload = zlib.decompress(payload) if encoding == 1 else payload
                    values = list(struct.unpack(f"<{length}i", payload[:4 * length]))
                position += stored
                properties.append(values)
            elif kind in "SR":
                length = struct.unpack("<I", data[position:position + 4])[0]; position += 4
                raw = data[position:position + length]; position += length
                properties.append(raw if kind == "R" else raw.decode("utf-8", "ignore"))
            else:
                raise ValueError(f"unknown FBX property type {kind!r}")
        return properties, position

    def read_record(position: int):
        end = struct.unpack(offset_format, data[position:position + offset_size])[0]; position += offset_size
        count = struct.unpack(offset_format, data[position:position + offset_size])[0]; position += offset_size
        position += offset_size
        name_length = data[position]; position += 1
        name = data[position:position + name_length].decode("utf-8", "ignore"); position += name_length
        if end == 0:
            return None, position
        properties, position = read_properties(position, count, name in int_arrays)
        children = []
        while position < end - sentinel:
            child, position = read_record(position)
            if child is None:
                break
            children.append(child)
        return {"name": name, "props": properties, "children": children}, end

    records, position = [], 27
    try:
        while position < len(data) - sentinel:
            record, position = read_record(position)
            if record is None:
                break
            records.append(record)
    except (ValueError, struct.error, IndexError, zlib.error):
        pass    # a damaged tail: keep what was read
    return records


def properties70(record: dict, wanted) -> Dict[str, list]:
    """The numeric values of the named ``P`` entries of a record's
    ``Properties70`` block, by property name."""
    found: Dict[str, list] = {}
    for block in (c for c in record.get("children", []) if c["name"] == "Properties70"):
        for entry in (c for c in block["children"] if c["name"] == "P"):
            if entry["props"] and entry["props"][0] in wanted:
                found[entry["props"][0]] = [
                    value for value in entry["props"][4:]
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
    return found


def object_name(record: dict) -> str:
    """The name of an object record: ``Name\\x00\\x01Model`` gives ``Name``."""
    label = next((p for p in record["props"] if isinstance(p, str)), "")
    return label.split("\x00\x01")[0].split("::")[0].strip()


# =============================================================================
# IMPORT FACTS
# =============================================================================

def read_import_facts(fbx_path: Path) -> dict:
    """What an import rule needs to know about a file::

        {"up_axis":          1 (Y), 2 (Z) or -1 (unknown),
         "unit_to_metres":   metres per file unit,
         "order":            [node name, ...] as the file lists them,
         "nodes": {node name: {
             "kind":                  "Mesh", "Null", "LimbNode", ...
             "mesh":                  True when the node carries geometry that has
                                      vertices (a file may hold an empty mesh),
             "parent":                the parent node's name, None at the top,
             "path":                  "RootNode.Parent.Node", as O3DE names it,
             "materials":             [material name, ...] the node's mesh uses, in the
                                      order its polygons first use them (the order
                                      of the sub-meshes Unity and O3DE make of it).
                                      A material connected through several slots
                                      is one material and is listed once,
             "material_ids":          [object id, ...] of those materials,
             "local_translation":     [x, y, z],   file units
             "local_rotation":        [x, y, z],   Euler degrees, order XYZ
             "pre_rotation":          [x, y, z],   applied before local_rotation
             "post_rotation":         [x, y, z],   its inverse applied after
             "local_scaling":         [x, y, z],
             "geometric_translation": [x, y, z],   file units
             "geometric_rotation":    [x, y, z],   Euler degrees, order XYZ
             "geometric_scaling":     [x, y, z]}}}

    A transform the file does not state is zero (a scaling: one). Two nodes
    of one name: the first is kept. A file that cannot be read gives an
    unknown up axis, centimetres, and no nodes."""
    facts = {"up_axis": UP_AXIS_UNKNOWN, "unit_to_metres": 0.01, "order": [], "nodes": {}}
    records = read_records(fbx_path, int_arrays=("Materials",))
    if not records:
        return facts
    by_name = {record["name"]: record for record in records}

    settings = properties70(by_name.get("GlobalSettings", {}), ("UpAxis", "UnitScaleFactor"))
    if settings.get("UpAxis"):
        facts["up_axis"] = int(settings["UpAxis"][0])
    if settings.get("UnitScaleFactor"):
        # The unit scale factor is the size of one file unit in centimetres.
        facts["unit_to_metres"] = float(settings["UnitScaleFactor"][0]) / 100.0

    # ---- The objects of the file, by their id: nodes, geometries, materials.
    wanted = ("Lcl Translation", "Lcl Rotation", "Lcl Scaling", "PreRotation", "PostRotation",
              "GeometricTranslation", "GeometricRotation", "GeometricScaling")
    node_of_id: Dict[int, str] = {}
    slots_used_of_geometry, material_of_id = {}, {}
    for record in by_name.get("Objects", {"children": []})["children"]:
        object_id = record["props"][0] if record["props"] else None
        if record["name"] == "Geometry" and not _is_empty(record):
            slots_used_of_geometry[object_id] = _material_slots_used(record)
        elif record["name"] == "Material":
            material_of_id[object_id] = object_name(record)
        if record["name"] != "Model":
            continue
        name = object_name(record)
        if not name or name in facts["nodes"]:
            continue
        found = properties70(record, wanted)
        node_of_id[object_id] = name
        facts["order"].append(name)
        facts["nodes"][name] = {
            "kind":                  record["props"][2] if len(record["props"]) > 2 else "",
            "mesh":                  False,
            "parent":                None,
            "path":                  "",
            "materials":             [],
            "material_ids":          [],
            "local_translation":     _three(found.get("Lcl Translation"), 0.0),
            "local_rotation":        _three(found.get("Lcl Rotation"), 0.0),
            "pre_rotation":          _three(found.get("PreRotation"), 0.0),
            "post_rotation":         _three(found.get("PostRotation"), 0.0),
            "local_scaling":         _three(found.get("Lcl Scaling"), 1.0),
            "geometric_translation": _three(found.get("GeometricTranslation"), 0.0),
            "geometric_rotation":    _three(found.get("GeometricRotation"), 0.0),
            "geometric_scaling":     _three(found.get("GeometricScaling"), 1.0),
        }

    # ---- The connections: a node's parent, its geometry, its materials.
    for record in by_name.get("Connections", {"children": []})["children"]:
        props = record["props"]
        if len(props) < 3 or props[0] != "OO" or props[2] not in node_of_id:
            continue
        child, node = props[1], facts["nodes"][node_of_id[props[2]]]
        if child in node_of_id:
            facts["nodes"][node_of_id[child]]["parent"] = node_of_id[props[2]]
        elif child in slots_used_of_geometry:
            node["mesh"] = True
            node["slots_used"] = slots_used_of_geometry[child]
        elif child in material_of_id:
            node["material_ids"].append(child)          # one per slot, in the file's order

    for name, node in facts["nodes"].items():
        node["path"] = ".".join(["RootNode"] + [scene_node_name(part) for part in _ancestry(facts["nodes"], name)])
        # The node lists a material for every slot; its mesh may use fewer
        # slots, and one material through several of them. Unity makes one
        # sub-mesh of each material used, and so does O3DE.
        by_slot = node["material_ids"]
        slots_used = node.pop("slots_used", None)
        if slots_used is not None:
            by_slot = [by_slot[slot] for slot in slots_used if slot < len(by_slot)]
        node["material_ids"] = list(dict.fromkeys(by_slot))
        node["materials"] = [material_of_id[material] for material in node["material_ids"]]
    return facts


def _is_empty(geometry: dict) -> bool:
    """Whether a geometry has no vertices. Such a mesh shows nothing in
    Unity, and O3DE cannot make a model of it: its node counts as carrying
    no mesh."""
    vertices = next((c for c in geometry["children"] if c["name"] == "Vertices"), None)
    return vertices is not None and bool(vertices["props"]) and vertices["props"][0] == []


def _material_slots_used(geometry: dict):
    """The material slots a geometry's polygons use, in the order of first
    use; None when the geometry does not say (every material then counts)."""
    layer = next((c for c in geometry["children"] if c["name"] == "LayerElementMaterial"), None)
    slots = next((c["props"][0] for c in (layer or {"children": []})["children"]
                  if c["name"] == "Materials" and c["props"]), None)
    if slots is None:
        return None
    return list(dict.fromkeys(slots))


def scene_node_name(name: str) -> str:
    """A node's name as O3DE's scene graph holds it. A dot separates the
    parts of a node path there, so the importer turns every dot of a name
    into an underscore (``RenamedNodesMap::SanitizeNodeName``): Blender's
    ``leaf.002`` is the node ``leaf_002``. Named by its own spelling, such a
    node is not found and its model comes out empty.

    The importer also numbers a name that repeats under one parent; that is
    not followed here."""
    return name.replace(".", "_")


def mesh_node_names(facts: dict) -> List[str]:
    """The names of the nodes that carry geometry, in the file's order."""
    return [name for name in facts.get("order", []) if facts["nodes"][name]["mesh"]]


def _ancestry(nodes: dict, name: str) -> List[str]:
    """A node's names from the top of the file down to itself."""
    chain: List[str] = []
    while name is not None and name in nodes and name not in chain:
        chain.insert(0, name)
        name = nodes[name]["parent"]
    return chain


def _three(values, default: float) -> List[float]:
    if values and len(values) >= 3:
        return [float(value) for value in values[:3]]
    return [default, default, default]
