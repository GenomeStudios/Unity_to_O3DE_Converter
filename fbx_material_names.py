"""
=============================================================================
FBX MATERIAL NAMES  (fbx_material_names)
=============================================================================

A mesh in an FBX can use several materials that carry one name. 3ds Max
writes them so whenever sub-materials were left at their default names
("Material #27" twice on one cupboard). The two engines tell the materials
of a model apart differently:

  - Unity goes by position. Each material of the file is a slot of its own,
    and the renderer lists one Unity material per slot.
  - O3DE goes by name. The scene pipeline identifies a material by its name
    (``AssImpMaterialWrapper::GetUniqueId`` hashes it) and merges the
    sub-meshes of one identity into one slot; the Material component
    assigns by slot label, which is the name again.

So where Unity shows wood on one part and metal on another, O3DE has one
slot for both and one of the two materials is lost. No setting of the scene
pipeline keeps them apart: the names have to differ in the file.

The converter therefore renames such materials in the **copy** of the model
it puts into the O3DE project (never in the Unity project). The first
material of a name keeps it; the others become ``Name (2)``, ``Name (3)``.

How the file is rewritten
-------------------------
A binary FBX is a tree of records, each stating where it ends as an offset
from the start of the file. A longer name moves everything behind it, so
the tree is read whole, the names changed, and every record written again
with its new end. Nothing but the names is decoded: the properties of every
other record are carried over byte for byte.

Two checks guard the file. Before anything is changed, the tree read from
the file is written back unchanged and must give the file's own bytes; a
file this module does not understand is left alone. After the change, the
file is read again and must show the same nodes with the materials renamed.

Only files of version 7.0 and later are rewritten: earlier ones connect
their objects by name, not by id. An ASCII FBX is left alone as well.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fbx_reader import BINARY_MAGIC, object_name, read_import_facts, read_records

HEADER_SIZE = 27                    # the magic, two bytes, and the version
FIRST_VERSION_WITH_IDS = 7000       # objects are connected by id from here on
FIRST_WIDE_VERSION = 7500           # record headers hold 64-bit numbers from here on

# What separates an object's name from its class in the name property.
NAME_END = b"\x00\x01"


# =============================================================================
# THE WHOLE STEP
# =============================================================================

def give_materials_unique_names(fbx_path: Path) -> List[Tuple[str, str]]:
    """Rename, in the file itself, every material that shares its name with
    another material of the same mesh. Returns the renames made as
    ``[(old name, new name), ...]``; empty when there was nothing to rename
    or the file is not one this module rewrites (see the module's notes)."""
    fbx_path = Path(fbx_path)
    new_names = names_to_change(fbx_path)
    if not new_names:
        return []

    original = fbx_path.read_bytes()
    before = read_import_facts(fbx_path)
    try:
        header, records, tail = _read_tree(original)
        if _write_tree(header, records, tail) != original:
            return []                                   # not a layout this module knows: left alone
        renamed = _rename_materials(records, new_names)
        fbx_path.write_bytes(_write_tree(header, records, tail))
    except (ValueError, struct.error, IndexError):
        return []

    # The file must read as before, with nothing left to rename.
    after = read_import_facts(fbx_path)
    same_nodes = after["order"] == before["order"] and all(
        len(after["nodes"][name]["materials"]) == len(before["nodes"][name]["materials"])
        and after["nodes"][name]["mesh"] == before["nodes"][name]["mesh"] for name in before["order"])
    if not same_nodes or names_to_change(fbx_path):
        fbx_path.write_bytes(original)
        return []
    return renamed


# =============================================================================
# WHICH MATERIALS SHARE A NAME
# =============================================================================

def names_to_change(fbx_path: Path) -> Dict[int, str]:
    """``{material id: new name}`` for every material of the file that has
    to be renamed: one that shares its name with a material the same mesh
    uses before it. Empty for a file without such materials, and for one
    whose objects have no ids (before version 7.0, or not binary).

    Only materials a mesh uses count (``read_import_facts``): one that is
    connected to a node and used by none of its polygons makes no slot."""
    facts = read_import_facts(fbx_path)
    taken = {object_name(record) for top in read_records(fbx_path) if top["name"] == "Objects"
             for record in top["children"] if record["name"] == "Material"}
    new_names: Dict[int, str] = {}
    for node in facts["nodes"].values():
        owner_of_name: Dict[str, int] = {}
        for material, name in zip(node["material_ids"], node["materials"]):
            name = new_names.get(material, name)
            if not isinstance(material, int) or owner_of_name.setdefault(name, material) == material:
                continue
            # Another material of this mesh has the name already.
            number = 2
            while f"{name} ({number})" in taken:
                number += 1
            new_names[material] = f"{name} ({number})"
            taken.add(new_names[material])
            owner_of_name[new_names[material]] = material
    return new_names


# =============================================================================
# THE RECORD TREE, BYTE FOR BYTE
# A record: where it ends, how many properties it has and how many bytes they
# take, its name, the properties, and its nested records. A nested list is
# closed by an empty record (all zeros); whether one was there is kept, so
# the file is written back as it was.
# =============================================================================

def _read_tree(data: bytes) -> Tuple[bytes, List[dict], bytes]:
    """A binary FBX in three parts: its header, its top records, and what
    follows the record that closes them."""
    if data[:len(BINARY_MAGIC)] != BINARY_MAGIC:
        raise ValueError("not a binary FBX")
    if _version(data) < FIRST_VERSION_WITH_IDS:
        raise ValueError("objects are connected by name in this version")
    wide = _is_wide(data)

    records, position = [], HEADER_SIZE
    while True:
        record, position = _read_record(data, position, wide)
        if record is None:
            return data[:HEADER_SIZE], records, data[position:]
        records.append(record)


def _read_record(data: bytes, position: int, wide: bool) -> Tuple[Optional[dict], int]:
    """The record at ``position`` and where the next one starts; None for
    the empty record that closes a list."""
    numbers = struct.Struct("<QQQ" if wide else "<III")
    end, count, property_bytes = numbers.unpack_from(data, position)
    position += numbers.size
    name_length = data[position]
    name = data[position + 1:position + 1 + name_length]
    position += 1 + name_length
    if end == 0:
        return None, position

    properties = data[position:position + property_bytes]
    position += property_bytes
    children, closed = [], False
    while position < end:
        child, position = _read_record(data, position, wide)
        if child is None:
            closed = True
            break
        children.append(child)
    if position != end:
        raise ValueError("a record does not end where it says")
    return {"name": name, "count": count, "properties": properties, "children": children, "closed": closed}, end


def _write_tree(header: bytes, records: List[dict], tail: bytes) -> bytes:
    """The file made of these three parts (see ``_read_tree``), every
    record ending where it now ends."""
    wide = _is_wide(header)
    data = bytearray(header)
    for record in records:
        data += _write_record(record, len(data), wide)
    return bytes(data) + _closing_record(wide) + tail


def _write_record(record: dict, start: int, wide: bool) -> bytes:
    """One record written at ``start``, with the end that position gives it."""
    numbers = struct.Struct("<QQQ" if wide else "<III")
    position = start + numbers.size + 1 + len(record["name"]) + len(record["properties"])
    nested = bytearray()
    for child in record["children"]:
        nested += _write_record(child, position + len(nested), wide)
    if record["closed"]:
        nested += _closing_record(wide)
    end = position + len(nested)
    return (numbers.pack(end, record["count"], len(record["properties"])) + bytes([len(record["name"])])
            + record["name"] + record["properties"] + bytes(nested))


def _closing_record(wide: bool) -> bytes:
    return b"\x00" * (25 if wide else 13)


def _version(header: bytes) -> int:
    return struct.unpack_from("<I", header, 23)[0]


def _is_wide(header: bytes) -> bool:
    """Whether the file's record headers hold 64-bit numbers."""
    return _version(header) >= FIRST_WIDE_VERSION


# =============================================================================
# THE NAMES
# =============================================================================

def _rename_materials(records: List[dict], new_names: Dict[int, str]) -> List[Tuple[str, str]]:
    """Give the material records with these ids their new names, in the
    tree. Returns ``[(old name, new name), ...]``."""
    renamed = []
    for record in records:
        if record["name"] != b"Objects":
            continue
        for material in record["children"]:
            if material["name"] != b"Material":
                continue
            # A material's properties start with its id (a 64-bit integer)
            # and its name with its class (a string).
            properties = material["properties"]
            if properties[0:1] != b"L" or properties[9:10] != b"S":
                raise ValueError("a material record this module does not know")
            object_id = struct.unpack_from("<q", properties, 1)[0]
            if object_id not in new_names:
                continue
            length = struct.unpack_from("<I", properties, 10)[0]
            label = properties[14:14 + length]
            old_name, separator, object_class = label.partition(NAME_END)
            new_label = new_names[object_id].encode("utf-8") + separator + object_class
            material["properties"] = (properties[:10] + struct.pack("<I", len(new_label)) + new_label
                                      + properties[14 + length:])
            renamed.append((old_name.decode("utf-8", "ignore"), new_names[object_id]))
    return renamed
