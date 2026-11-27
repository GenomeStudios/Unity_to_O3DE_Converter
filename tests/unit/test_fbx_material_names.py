"""Unit tests for the materials of a model that share a name (nature_pack
I.6, found on the Alchemist House and Tirgames packs).

Two things 3ds Max writes, and what each engine makes of them:

  - one material connected to a mesh through several slots. Unity makes one
    sub-mesh of it, and so does O3DE: it is one material, listed once
    (``fbx_reader.read_import_facts``). The converter listed it once per
    slot, and paired a renderer's materials with the wrong names.
  - two materials of one name on one mesh. Unity keeps them apart by
    position; O3DE knows a material by its name and merges them. The copy
    of the model is rewritten so their names differ
    (``fbx_material_names``).
"""

import struct
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from fbx_material_names import give_materials_unique_names, names_to_change
from fbx_reader import read_import_facts, read_records
from tests.unit.test_fbx_node_tree import _file, _geometry, _link, _material, _model


def _write(folder: Path, objects, links, version=7400) -> Path:
    path = Path(folder) / "Model.fbx"
    data = _file([{"name": "Objects", "props": [], "children": objects},
                  {"name": "Connections", "props": [], "children": links}])
    path.write_bytes(data[:23] + struct.pack("<I", version) + data[27:])
    return path


def _materials(path: Path, node: str):
    return read_import_facts(path)["nodes"][node]["materials"]


# =============================================================================
# ONE MATERIAL THROUGH SEVERAL SLOTS
# =============================================================================

def test_a_material_connected_through_several_slots_is_one_material():
    """The cupboard of the Alchemist House: twenty-six slots, twelve of them
    used, five materials. Unity's renderer lists five."""
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder,
                      [_model(1, "Cupboard"), _geometry(20, slots=[0, 1, 2, 4, 3]),
                       _material(30, "Material #27"), _material(31, "Wall01"), _material(32, "Material #28")],
                      [_link(1, 0), _link(20, 1),
                       _link(30, 1), _link(30, 1), _link(31, 1), _link(32, 1), _link(32, 1)])
        facts = read_import_facts(path)["nodes"]["Cupboard"]
        assert facts["materials"] == ["Material #27", "Wall01", "Material #28"]
        assert facts["material_ids"] == [30, 31, 32]
        assert names_to_change(path) == {}, "one material under one name: nothing to rename"


# =============================================================================
# TWO MATERIALS OF ONE NAME
# =============================================================================

def test_the_second_material_of_a_name_gets_a_new_one():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder,
                      [_model(1, "Lamp"), _geometry(20, slots=[0, 1, 2]),
                       _material(30, "Material #35"), _material(31, "Material #35"), _material(32, "Glass")],
                      [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1), _link(32, 1)])
        assert names_to_change(path) == {31: "Material #35 (2)"}
        assert give_materials_unique_names(path) == [("Material #35", "Material #35 (2)")]
        assert _materials(path, "Lamp") == ["Material #35", "Material #35 (2)", "Glass"]
        assert give_materials_unique_names(path) == [], "nothing left to rename"


def test_a_new_name_avoids_the_names_the_file_has():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder,
                      [_model(1, "Lamp"), _geometry(20, slots=[0, 1, 2, 3]),
                       _material(30, "Brass"), _material(31, "Brass"), _material(32, "Brass (2)"), _material(33, "Brass")],
                      [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1), _link(32, 1), _link(33, 1)])
        give_materials_unique_names(path)
        assert _materials(path, "Lamp") == ["Brass", "Brass (3)", "Brass (2)", "Brass (4)"]


def test_materials_of_one_name_on_different_meshes_keep_it():
    """Each mesh becomes a model of its own: no two of its slots collide."""
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder,
                      [_model(1, "Frame"), _model(2, "Pane"), _geometry(20, slots=[0]), _geometry(21, slots=[0]),
                       _material(30, "Default"), _material(31, "Default")],
                      [_link(1, 0), _link(2, 1), _link(20, 1), _link(21, 2), _link(30, 1), _link(31, 2)])
        assert give_materials_unique_names(path) == []


def test_a_material_no_polygon_uses_is_left_alone():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder,
                      [_model(1, "Wall"), _geometry(20, slots=[0, 0]),
                       _material(30, "Material #26"), _material(31, "Material #26")],
                      [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)])
        before = path.read_bytes()
        assert give_materials_unique_names(path) == [] and path.read_bytes() == before


# =============================================================================
# THE REWRITTEN FILE
# =============================================================================

def test_everything_but_the_name_is_carried_over():
    """A longer name moves every record behind it; each still ends where it
    says, and holds what it held."""
    with tempfile.TemporaryDirectory() as folder:
        objects = [_model(1, "Lamp"), _geometry(20, slots=[1, 0], compressed=True, vertices=9),
                   _material(30, "M"), _material(31, "M"), _model(2, "Shade")]
        links = [_link(1, 0), _link(2, 1), _link(20, 1), _link(30, 1), _link(31, 1)]
        path = _write(folder, objects, links)
        before = read_records(path, int_arrays=("Materials",))
        give_materials_unique_names(path)
        after = read_records(path, int_arrays=("Materials",))

        def without_names(records):
            return [(record["name"], [p for p in record["props"] if not (isinstance(p, str) and p.startswith("M"))],
                     without_names(record["children"])) for record in records]
        assert without_names(after) == without_names(before)
        assert read_import_facts(path)["order"] == ["Lamp", "Shade"]
        # The polygons use the second slot first: its material keeps the name.
        assert _materials(path, "Lamp") == ["M", "M (2)"]
        assert read_import_facts(path)["nodes"]["Lamp"]["material_ids"] == [31, 30]


def test_a_file_of_64_bit_records_is_left_alone_if_it_does_not_read_back():
    """Version 7500 and later hold 64-bit record headers. This fixture is
    written with 32-bit ones under a 7500 version: it does not read, and is
    not touched."""
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder, [_model(1, "Lamp"), _geometry(20, slots=[0, 1]), _material(30, "M"), _material(31, "M")],
                      [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)], version=7500)
        before = path.read_bytes()
        assert give_materials_unique_names(path) == [] and path.read_bytes() == before


def test_a_file_that_connects_by_name_is_left_alone():
    with tempfile.TemporaryDirectory() as folder:
        path = _write(folder, [_model(1, "Lamp"), _geometry(20, slots=[0, 1]), _material(30, "M"), _material(31, "M")],
                      [_link(1, 0), _link(20, 1), _link(30, 1), _link(31, 1)], version=6100)
        before = path.read_bytes()
        assert give_materials_unique_names(path) == [] and path.read_bytes() == before


def test_a_file_that_is_not_fbx_is_left_alone():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Model.fbx"
        path.write_text("; FBX 7.4.0 project file", encoding="ascii")
        assert give_materials_unique_names(path) == []


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
