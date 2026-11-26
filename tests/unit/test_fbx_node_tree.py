"""Unit tests for the node tree ``fbx_reader.read_import_facts`` reads
(parity_fixes I.4): each node's parent and path, whether it carries a mesh,
and the materials its mesh uses, in the order its polygons first use them.

Uses hand-built minimal binary FBX files (version 7400), so the tests need no
asset pack.
"""

import struct
import sys
import tempfile
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from fbx_reader import mesh_node_names, read_import_facts


# =============================================================================
# A MINIMAL BINARY FBX
# =============================================================================

def _text(value):
    data = value.encode("utf-8")
    return b"S" + struct.pack("<I", len(data)) + data


def _number(value):
    return b"L" + struct.pack("<q", value)


def _int_array(values, compressed=False):
    body = struct.pack(f"<{len(values)}i", *values)
    stored = zlib.compress(body) if compressed else body
    return b"i" + struct.pack("<III", len(values), 1 if compressed else 0, len(stored)) + stored


def _record(spec, start):
    """Encode ``{"name", "props": [bytes], "children": [spec]}`` at ``start``."""
    name = spec["name"].encode("ascii")
    props = b"".join(spec.get("props", []))
    cursor = start + 13 + len(name) + len(props)
    nested = b""
    for child in spec.get("children", []):
        encoded = _record(child, cursor)
        nested += encoded
        cursor += len(encoded)
    if spec.get("children"):
        nested += b"\x00" * 13
        cursor += 13
    return struct.pack("<III", cursor, len(spec.get("props", [])), len(props)) + bytes([len(name)]) + name + props + nested


def _file(records) -> bytes:
    data = b"Kaydara FBX Binary  \x00" + bytes([0x1A, 0x00]) + struct.pack("<I", 7400)
    for spec in records:
        data += _record(spec, len(data))
    return data + b"\x00" * 13


def _model(object_id, name, kind="Mesh"):
    return {"name": "Model", "props": [_number(object_id), _text(f"{name}\x00\x01Model"), _text(kind)]}


def _geometry(object_id, slots=None, compressed=False):
    children = []
    if slots is not None:
        children.append({"name": "LayerElementMaterial", "props": [],
                         "children": [{"name": "Materials", "props": [_int_array(slots, compressed)]}]})
    return {"name": "Geometry", "props": [_number(object_id), _text("\x00\x01Geometry"), _text("Mesh")],
            "children": children}


def _material(object_id, name):
    return {"name": "Material", "props": [_number(object_id), _text(f"{name}\x00\x01Material"), _text("")]}


def _link(child, parent):
    return {"name": "C", "props": [_text("OO"), _number(child), _number(parent)]}


def _facts(objects, links):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Model.fbx"
        path.write_bytes(_file([{"name": "Objects", "props": [], "children": objects},
                                {"name": "Connections", "props": [], "children": links}]))
        return read_import_facts(path)


# =============================================================================
# PARENTS AND PATHS
# =============================================================================

def test_a_child_nodes_path_runs_through_its_parent():
    """The lockers of the Office pack: the doors hang under the body."""
    facts = _facts(
        [_model(1, "Lockers_body"), _model(2, "Locker_door_A"), _model(3, "Locker_door_B")],
        [_link(1, 0), _link(2, 1), _link(3, 1)])
    assert facts["order"] == ["Lockers_body", "Locker_door_A", "Locker_door_B"]
    assert facts["nodes"]["Lockers_body"]["parent"] is None
    assert facts["nodes"]["Lockers_body"]["path"] == "RootNode.Lockers_body"
    assert facts["nodes"]["Locker_door_B"]["parent"] == "Lockers_body"
    assert facts["nodes"]["Locker_door_B"]["path"] == "RootNode.Lockers_body.Locker_door_B"


def test_a_group_node_is_part_of_the_path_and_carries_no_mesh():
    facts = _facts(
        [_model(1, "Group", "Null"), _model(2, "Part"), _geometry(20)],
        [_link(1, 0), _link(2, 1), _link(20, 2)])
    assert facts["nodes"]["Part"]["path"] == "RootNode.Group.Part"
    assert facts["nodes"]["Group"]["mesh"] is False and facts["nodes"]["Part"]["mesh"] is True
    assert mesh_node_names(facts) == ["Part"]


def test_a_mesh_node_is_one_with_a_geometry_connected():
    facts = _facts([_model(1, "Empty"), _model(2, "Full"), _geometry(20)], [_link(1, 0), _link(2, 0), _link(20, 2)])
    assert mesh_node_names(facts) == ["Full"]


# =============================================================================
# MATERIALS
# =============================================================================

def test_materials_are_the_ones_the_polygons_use_in_order_of_first_use():
    """A door of the Office pack lists (Doors_Metal, Glass) and uses Glass
    first; Unity's renderer then shows (Glass, Doors_Metal)."""
    for compressed in (False, True):
        facts = _facts(
            [_model(1, "Door"), _geometry(20, slots=[1, 1, 0, 1, 0], compressed=compressed),
             _material(30, "Doors_Metal"), _material(31, "Glass")],
            [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)])
        assert facts["nodes"]["Door"]["materials"] == ["Glass", "Doors_Metal"], compressed


def test_a_material_no_polygon_uses_is_left_out():
    facts = _facts(
        [_model(1, "Door"), _geometry(20, slots=[0, 0, 0]), _material(30, "Doors_Metal"), _material(31, "Glass")],
        [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)])
    assert facts["nodes"]["Door"]["materials"] == ["Doors_Metal"]


def test_each_node_has_its_own_materials():
    facts = _facts(
        [_model(1, "Frame"), _model(2, "Pane"), _geometry(20, slots=[0]), _geometry(21, slots=[0]),
         _material(30, "Wood"), _material(31, "Glass")],
        [_link(1, 0), _link(2, 1), _link(20, 1), _link(21, 2), _link(30, 1), _link(31, 2)])
    assert facts["nodes"]["Frame"]["materials"] == ["Wood"]
    assert facts["nodes"]["Pane"]["materials"] == ["Glass"]


def test_a_geometry_that_does_not_say_keeps_every_material():
    facts = _facts(
        [_model(1, "Part"), _geometry(20), _material(30, "A"), _material(31, "B")],
        [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)])
    assert facts["nodes"]["Part"]["materials"] == ["A", "B"]


def test_a_file_that_is_not_fbx_has_no_nodes():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Thing.fbx"
        path.write_bytes(b"; FBX 7.4.0 project file\n")
        facts = read_import_facts(path)
        assert facts["nodes"] == {} and facts["order"] == [] and mesh_node_names(facts) == []


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
