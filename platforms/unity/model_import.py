"""
=============================================================================
UNITY MODEL IMPORT  (platforms.unity.model_import)
=============================================================================

What Unity makes of a model file (an FBX), worked out from the file and its
``.meta`` alone. Three questions are answered here:

  1. Which node of the file does a mesh reference mean?  A renderer names its
     mesh as ``{guid, fileID}``; the guid is the file, the fileID is Unity's
     own id of one mesh in it.
  2. Which objects does Unity make of the file?  A model dropped into a prefab
     or a scene is an instance of that object tree, not of a ``.prefab``.
  3. Which materials do those objects carry?

Everything below was measured against Unity 2021.3 on the Office pack (232
model files, 277 objects, 276 meshes; see ``mem:parity_fixes/plan`` D.16 and
D.17) with the importer's defaults: ``preserveHierarchy`` off and
``bakeAxisConversion`` off.

Unity's ids
-----------
- A mesh id is the id the ``.meta`` lists for the mesh's name
  (``internalIDToNameTable``, or ``fileIDToRecycleName`` in older files), and
  where the table has no such name, a hash of the name:
  ``xxHash64("Type:Mesh->" + name + "0")``, read as a signed number.
- An object *inside an instance* has the id
  ``(instance id XOR the object's id in its source) AND 0x7FFF...F``.
- The model's own objects have ids from the same table. Where the table is
  empty, the root object and its transform have two fixed ids; the hash of
  the other objects is not known, so their ids are left empty.

Unity's object tree
-------------------
- One object per node of the file. A file with one top node: that node is the
  model's root. Otherwise Unity makes a root of its own. Either way the root
  is named after the file.
- Unity negates X. A node's position is ``(-x, y, z)`` times the file's unit
  and the importer's scale factor, its rotation ``pre * local * post^-1``
  with X negated, its scale as stated.
- In a Z-up file the nodes at the top are also turned to Y-up.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

from fbx_reader import UP_AXIS_Z, mesh_node_names
from matrix3 import euler_xyz_matrix, mat_mul, mat_vec, matrix_to_quat, transpose

CLASS_GAME_OBJECT = 1
CLASS_TRANSFORM = 4
CLASS_MESH = 43

# The name the id table gives the model's root object.
ROOT_NAME = "//RootNode"

# The root object's ids in a file whose id table is empty.
HASHED_ROOT_GAME_OBJECT = "919132149155446097"
HASHED_ROOT_TRANSFORM = "-8679921383154817045"

# The first mesh id of the oldest scheme: mesh number n has 4300000 + 2n.
LEGACY_FIRST_MESH_ID = 4300000

_INSTANCE_ID_MASK = 0x7FFFFFFFFFFFFFFF

# Unity negates X on import; in a Z-up file it turns the top nodes to Y-up.
_NEGATE_X = [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
_Z_UP_TO_Y_UP = [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]


# =============================================================================
# THE MODEL'S .META
# =============================================================================

@dataclass
class ModelMeta:
    """What a model's ``.meta`` says that the conversion needs."""
    # {class id: {file id: name}}, e.g. {43: {"4300000": "Door"}}
    id_table: Dict[int, Dict[str, str]] = field(default_factory=dict)
    # {material name in the file: guid of the material it is remapped to}
    materials: Dict[str, str] = field(default_factory=dict)
    # False when the importer takes no materials from the file: Unity then
    # shows its default material, which is no asset of the project.
    import_materials: bool = True
    # The importer's "Scale Factor" (``globalScale``): Unity multiplies the
    # model by it - the vertices of every mesh and the place of every node.
    global_scale: float = 1.0
    # Importer switches this module's rules do not cover, when they are set
    # away from their default.
    unsupported: List[str] = field(default_factory=list)


def read_model_meta(meta_path: Path) -> ModelMeta:
    """Read a model's ``.meta``. A file that is missing or is not a model's
    gives an empty ``ModelMeta``."""
    meta = ModelMeta()
    try:
        # BaseLoader keeps every scalar a string: a mesh named "123" or "Yes"
        # stays what it is.
        document = yaml.load(Path(meta_path).read_text(encoding="utf-8", errors="ignore"),
                             Loader=yaml.BaseLoader) or {}
    except (OSError, yaml.YAMLError):
        return meta
    importer = document.get("ModelImporter") if isinstance(document, dict) else None
    if not isinstance(importer, dict):
        return meta

    for entry in importer.get("internalIDToNameTable") or []:
        for class_id, file_id in (entry.get("first") or {}).items():
            meta.id_table.setdefault(int(class_id), {})[str(file_id)] = str(entry.get("second", ""))
    # Older files: one flat table, the class is the id's leading digits.
    recycled = importer.get("fileIDToRecycleName")
    for file_id, name in (recycled.items() if isinstance(recycled, dict) else []):
        meta.id_table.setdefault(int(file_id) // 100000, {})[str(file_id)] = str(name)

    for entry in importer.get("externalObjects") or []:
        first, second = entry.get("first") or {}, entry.get("second") or {}
        if first.get("type") == "UnityEngine:Material" and second.get("guid"):
            meta.materials[str(first.get("name", ""))] = str(second["guid"])

    material_settings = importer.get("materials") if isinstance(importer.get("materials"), dict) else {}
    meta.import_materials = str(material_settings.get("materialImportMode", "1")) != "0"

    meshes = importer.get("meshes") if isinstance(importer.get("meshes"), dict) else {}
    try:
        meta.global_scale = float(meshes.get("globalScale", 1.0))
    except (TypeError, ValueError):
        meta.global_scale = 1.0
    for switch in ("bakeAxisConversion", "preserveHierarchy"):
        if str(meshes.get(switch, importer.get(switch, "0"))) == "1":
            meta.unsupported.append(switch)
    # With the file's unit switched off Unity reads the file's numbers as
    # centimetres, whatever the file says.
    if str(meshes.get("useFileScale", "1")) == "0":
        meta.unsupported.append("useFileScale off")
    return meta


# =============================================================================
# UNITY'S IDS
# =============================================================================

def xxhash64(data: bytes, seed: int = 0) -> int:
    """The 64-bit xxHash of ``data``, as an unsigned number."""
    p1, p2, p3 = 11400714785074694791, 14029467366897019727, 1609587929392839161
    p4, p5, mask = 9650029242287828579, 2870177450012600261, (1 << 64) - 1

    def rotate(value, bits):
        return ((value << bits) | (value >> (64 - bits))) & mask

    def step(accumulator, lane):
        return (rotate((accumulator + lane * p2) & mask, 31) * p1) & mask

    length, position = len(data), 0
    if length >= 32:
        lanes = [(seed + p1 + p2) & mask, (seed + p2) & mask, seed & mask, (seed - p1) & mask]
        while position <= length - 32:
            for index, lane in enumerate(struct.unpack_from("<QQQQ", data, position)):
                lanes[index] = step(lanes[index], lane)
            position += 32
        digest = (rotate(lanes[0], 1) + rotate(lanes[1], 7) + rotate(lanes[2], 12) + rotate(lanes[3], 18)) & mask
        for lane in lanes:
            digest = ((digest ^ step(0, lane)) * p1 + p4) & mask
    else:
        digest = (seed + p5) & mask

    digest = (digest + length) & mask
    while position <= length - 8:
        digest = (rotate(digest ^ step(0, struct.unpack_from("<Q", data, position)[0]), 27) * p1 + p4) & mask
        position += 8
    if position <= length - 4:
        digest = (rotate(digest ^ (struct.unpack_from("<I", data, position)[0] * p1 & mask), 23) * p2 + p3) & mask
        position += 4
    while position < length:
        digest = (rotate(digest ^ (data[position] * p5 & mask), 11) * p1) & mask
        position += 1

    digest ^= digest >> 33
    digest = (digest * p2) & mask
    digest ^= digest >> 29
    digest = (digest * p3) & mask
    digest ^= digest >> 32
    return digest


def hashed_mesh_id(mesh_name: str) -> str:
    """The id Unity gives a mesh whose name the id table does not list."""
    digest = xxhash64(f"Type:Mesh->{mesh_name}0".encode("utf-8"))
    return str(digest - (1 << 64) if digest >= (1 << 63) else digest)


def instance_object_id(instance_file_id: str, source_file_id: str) -> str:
    """The id, in the file that holds an instance, of one object inside it."""
    return str((int(instance_file_id) ^ int(source_file_id)) & _INSTANCE_ID_MASK)


def _id_of(meta: ModelMeta, class_id: int, name: str) -> str:
    """The id the table gives ``name`` in one class, or ""."""
    return next((file_id for file_id, listed in meta.id_table.get(class_id, {}).items() if listed == name), "")


# =============================================================================
# FROM A MESH REFERENCE TO THE FILE'S NODE
# =============================================================================

def mesh_id_of_node(meta: ModelMeta, node_name: str) -> str:
    """Unity's id of the mesh it imports from one node. Unity names the mesh
    after its node."""
    return _id_of(meta, CLASS_MESH, node_name) or hashed_mesh_id(node_name)


def node_for_mesh(mesh_file_id: str, meta: ModelMeta, facts: dict, object_name: str = "") -> Optional[str]:
    """The node of the file that a mesh reference means, or None.

    Order: Unity's own id of each node's mesh; then, for a reference whose id
    cannot be placed, the node named like the object that references it; the
    file's only mesh node; and last the oldest id scheme read as a position
    in the file."""
    names = mesh_node_names(facts)
    wanted = str(mesh_file_id or "")
    for name in names:
        if wanted and mesh_id_of_node(meta, name) == wanted:
            return name
    if object_name in names:
        return object_name
    if len(names) == 1:
        return names[0]
    if wanted.isdigit() and int(wanted) >= LEGACY_FIRST_MESH_ID:
        index = (int(wanted) - LEGACY_FIRST_MESH_ID) // 2
        if index < len(names):
            return names[index]
    return None


# =============================================================================
# THE OBJECTS UNITY MAKES OF A MODEL
# =============================================================================

@dataclass
class ModelObject:
    """One object of a model as Unity imports it. Transforms are Unity's:
    metres, Y-up, left-handed, rotation ``(x, y, z, w)``."""
    name:           str
    node:           Optional[str]        # the file's node; None for a root Unity made itself
    parent:         int                  # index in the list; -1 for the root
    position:       tuple = (0.0, 0.0, 0.0)
    rotation:       tuple = (0.0, 0.0, 0.0, 1.0)
    scale:          tuple = (1.0, 1.0, 1.0)
    mesh_file_id:   str = ""             # "" when the object shows no mesh
    material_names: List[str] = field(default_factory=list)
    material_guids: List[str] = field(default_factory=list)
    game_object_id: str = ""             # Unity's ids in the model; "" when not known
    transform_id:   str = ""


def model_objects(facts: dict, file_stem: str, meta: ModelMeta) -> List[ModelObject]:
    """The object tree Unity makes of a model file, root first and every
    parent before its children. Empty when the file has no nodes.

    ``facts`` comes from ``fbx_reader.read_import_facts``."""
    nodes = facts.get("nodes") or {}
    order = [name for name in facts.get("order", []) if name in nodes]
    if not order:
        return []
    top = [name for name in order if nodes[name]["parent"] is None]
    hashed = not meta.id_table.get(CLASS_GAME_OBJECT)

    def ids_for(table_name: str, is_root: bool) -> tuple:
        if hashed:
            return (HASHED_ROOT_GAME_OBJECT, HASHED_ROOT_TRANSFORM) if is_root else ("", "")
        return _id_of(meta, CLASS_GAME_OBJECT, table_name), _id_of(meta, CLASS_TRANSFORM, table_name)

    def object_for(name: str, parent: int, is_root: bool) -> ModelObject:
        node = nodes[name]
        position, rotation = _unity_node_transform(facts, node, meta.global_scale)
        game_object_id, transform_id = ids_for(ROOT_NAME if is_root else name, is_root)
        return ModelObject(
            name=file_stem if is_root else name, node=name, parent=parent,
            position=position, rotation=rotation, scale=tuple(node["local_scaling"]),
            mesh_file_id=mesh_id_of_node(meta, name) if node["mesh"] else "",
            material_names=list(node["materials"]) if node["mesh"] else [],
            game_object_id=game_object_id, transform_id=transform_id,
        )

    objects: List[ModelObject] = []
    if len(top) == 1:
        objects.append(object_for(top[0], -1, True))
        queue = [(top[0], 0)]
    else:
        game_object_id, transform_id = ids_for(ROOT_NAME, True)
        objects.append(ModelObject(name=file_stem, node=None, parent=-1,
                                   game_object_id=game_object_id, transform_id=transform_id))
        queue = []
        for name in top:
            objects.append(object_for(name, 0, False))
            queue.append((name, len(objects) - 1))

    while queue:
        parent_name, parent_index = queue.pop(0)
        for name in order:
            if nodes[name]["parent"] == parent_name:
                objects.append(object_for(name, parent_index, False))
                queue.append((name, len(objects) - 1))
    return objects


def _unity_node_transform(facts: dict, node: dict, global_scale: float = 1.0) -> tuple:
    """A node's local position (metres) and rotation (quaternion) as Unity
    imports them. ``global_scale`` is the importer's scale factor."""
    unit = float(facts.get("unit_to_metres") or 0.01) * global_scale
    translation = [value * unit for value in node["local_translation"]]
    rotation = mat_mul(mat_mul(euler_xyz_matrix(node["pre_rotation"]), euler_xyz_matrix(node["local_rotation"])),
                       transpose(euler_xyz_matrix(node["post_rotation"])))
    if facts.get("up_axis") == UP_AXIS_Z and node["parent"] is None:
        translation, rotation = mat_vec(_Z_UP_TO_Y_UP, translation), mat_mul(_Z_UP_TO_Y_UP, rotation)
    position = mat_vec(_NEGATE_X, translation)
    mirrored = mat_mul(mat_mul(_NEGATE_X, rotation), _NEGATE_X)
    return tuple(position), tuple(matrix_to_quat(mirrored))


# =============================================================================
# MATERIALS
# =============================================================================

def assign_materials(objects: List[ModelObject], meta: ModelMeta,
                     find_material: Callable[[str], Optional[str]]) -> None:
    """Fill each object's ``material_guids`` from its material names: the
    remap the ``.meta`` holds, else ``find_material(name)`` (the project's
    material of that name). A name that resolves to nothing is left out, and
    so is every name of a model whose importer takes no materials."""
    for model_object in objects:
        names = model_object.material_names if meta.import_materials else []
        guids = (meta.materials.get(name) or find_material(name) for name in names)
        model_object.material_guids = [guid for guid in guids if guid]
