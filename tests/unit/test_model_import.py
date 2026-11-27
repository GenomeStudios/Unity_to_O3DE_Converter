"""Unit tests for ``platforms.unity.model_import`` (parity_fixes I.4, proof
T.7): Unity's ids, which node a mesh reference means, the objects Unity
makes of a model file, and an instance of a model inside a prefab.

The expected ids are ones Unity 2021.3 wrote for files of the Office pack.
"""

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.model_import import (
    HASHED_ROOT_GAME_OBJECT, HASHED_ROOT_TRANSFORM, ModelMeta, ModelObject,
    assign_materials, hashed_mesh_id, hashed_object_ids, hashed_renderer_id, instance_object_id, mesh_id_of_node,
    import_scale, model_objects, node_for_mesh, read_model_meta, xxhash64,
)
from platforms.unity.prefab import UnityParseContext, parse_unity_prefab


# =============================================================================
# FIXTURES
# =============================================================================

def _node(parent=None, mesh=True, materials=(), translation=(0, 0, 0), rotation=(0, 0, 0),
          pre_rotation=(0, 0, 0), scaling=(1, 1, 1)):
    return {"kind": "Mesh" if mesh else "Null", "mesh": mesh, "parent": parent, "path": "",
            "materials": list(materials), "local_translation": list(translation),
            "local_rotation": list(rotation), "pre_rotation": list(pre_rotation),
            "post_rotation": [0.0, 0.0, 0.0], "local_scaling": list(scaling),
            "geometric_translation": [0.0, 0.0, 0.0], "geometric_rotation": [0.0, 0.0, 0.0],
            "geometric_scaling": [1.0, 1.0, 1.0]}


def _facts(nodes, up_axis=1, unit=0.01):
    facts = {"up_axis": up_axis, "unit_to_metres": unit, "order": list(nodes), "nodes": dict(nodes)}
    for name, node in facts["nodes"].items():
        chain, at = [], name
        while at is not None:
            chain.insert(0, at)
            at = facts["nodes"][at]["parent"]
        node["path"] = ".".join(["RootNode"] + chain)
    return facts


LEGACY_META = """fileFormatVersion: 2
guid: 4c1854d3e81e0854492ad68b4ad26613
ModelImporter:
  serializedVersion: 21300
  internalIDToNameTable:
  - first:
      1: 100000
    second: //RootNode
  - first:
      4: 400000
    second: //RootNode
  - first:
      1: 100002
    second: Handle
  - first:
      4: 400002
    second: Handle
  - first:
      43: 4300000
    second: Doors
  - first:
      43: 4300002
    second: Door_Metal_Gray
  externalObjects:
  - first:
      type: UnityEngine:Material
      assembly: UnityEngine.CoreModule
      name: Doors_Metal
    second: {fileID: 2100000, guid: 2b67611016e6bb74eaf6322e96470a76, type: 2}
  materials:
    materialImportMode: 1
  meshes:
    globalScale: 1
    bakeAxisConversion: 0
"""


def _meta(text) -> ModelMeta:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Model.FBX.meta"
        path.write_text(text, encoding="utf-8")
        return read_model_meta(path)


def _close(a, b, tolerance=1e-9):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b)) and len(a) == len(b)


# =============================================================================
# UNITY'S IDS
# =============================================================================

def test_xxhash64_of_nothing_is_the_published_value():
    assert xxhash64(b"") == 0xEF46DB3751D8E999


def test_a_mesh_id_is_the_hash_of_its_name():
    """Ids Unity wrote, short names and ones long enough for the hash's
    32-byte path."""
    assert hashed_mesh_id("Lockers_body") == "5885633510228919780"
    assert hashed_mesh_id("Locker_door_B") == "-4783852174138363629"
    assert hashed_mesh_id("Door_Bronze_Windows") == "-9050736217654793324"
    assert hashed_mesh_id("Watersprinklerpipe_L_COL") == "3973115676379215840"
    assert hashed_mesh_id("Storage_cardboard_box_open") == "-3584694870108730482"


def test_an_object_inside_an_instance_has_the_xor_of_the_two_ids():
    assert instance_object_id("6791355114786468700", "100000") == "6791355114786436604"
    assert instance_object_id("6791355114786468700", "400000") == "6791355114786859484"


# =============================================================================
# THE .META
# =============================================================================

def test_meta_gives_the_id_table_and_the_material_remap():
    meta = _meta(LEGACY_META)
    assert meta.id_table[43] == {"4300000": "Doors", "4300002": "Door_Metal_Gray"}
    assert meta.id_table[1]["100000"] == "//RootNode"
    assert meta.materials == {"Doors_Metal": "2b67611016e6bb74eaf6322e96470a76"}
    assert meta.import_materials is True and meta.unsupported == []


def test_meta_of_the_oldest_format_lists_ids_in_one_table():
    meta = _meta("ModelImporter:\n  fileIDToRecycleName:\n    100000: //RootNode\n    4300000: Door\n")
    assert meta.id_table == {1: {"100000": "//RootNode"}, 43: {"4300000": "Door"}}


def test_meta_says_when_materials_are_not_imported_and_which_switches_are_on():
    meta = _meta("ModelImporter:\n  internalIDToNameTable: []\n  materials:\n    materialImportMode: 0\n"
                 "  meshes:\n    bakeAxisConversion: 1\n  preserveHierarchy: 1\n")
    assert meta.import_materials is False
    assert meta.unsupported == ["bakeAxisConversion", "preserveHierarchy"]


def test_a_missing_meta_is_an_empty_one():
    meta = read_model_meta(Path("no/such/file.meta"))
    assert meta.id_table == {} and meta.materials == {} and meta.import_materials is True


# =============================================================================
# FROM A MESH REFERENCE TO THE NODE
# =============================================================================

def test_the_tables_id_names_the_node_even_where_the_position_would_not():
    """Door_Metal_Gray.FBX: one node, mesh id 4300002. Read as a position
    that is the second mesh of a file that has one."""
    facts = _facts({"Door_Metal_Gray": _node()})
    meta = _meta(LEGACY_META)
    assert mesh_id_of_node(meta, "Door_Metal_Gray") == "4300002"
    assert node_for_mesh("4300002", meta, facts) == "Door_Metal_Gray"


def test_a_hashed_id_names_its_node_whatever_the_object_is_called():
    """The lockers: the prefab's object is 'Lockers', the node 'Lockers_body'."""
    facts = _facts({"Lockers_body": _node(), "Locker_door_A": _node("Lockers_body"),
                    "Locker_door_B": _node("Lockers_body")})
    assert node_for_mesh("5885633510228919780", ModelMeta(), facts, "Lockers") == "Lockers_body"
    assert node_for_mesh("-4783852174138363629", ModelMeta(), facts, "Anything") == "Locker_door_B"


def test_two_objects_of_one_name_get_the_nodes_their_ids_name():
    """The spot lamp: both objects are called 'Lamp_spot'."""
    facts = _facts({"Lamp_spot_ceilingpart": _node(), "Lamp_spot": _node("Lamp_spot_ceilingpart")})
    meta = ModelMeta()
    first = node_for_mesh(hashed_mesh_id("Lamp_spot_ceilingpart"), meta, facts, "Lamp_spot")
    second = node_for_mesh(hashed_mesh_id("Lamp_spot"), meta, facts, "Lamp_spot")
    assert (first, second) == ("Lamp_spot_ceilingpart", "Lamp_spot")


def test_with_convert_units_off_unity_takes_one_unit_of_the_file_for_a_metre():
    """`SM_river_stone_01.fbx` of the NatureManufacture pack: a centimetre
    file, scale factor 0.1, "Convert Units" off. Unity makes it 0.1 m to the
    unit; the engine, going by the file's unit, a hundredth of that."""
    text = "fileFormatVersion: 2\nguid: 4c1854d3e81e0854492ad68b4ad26613\nModelImporter:\n  meshes:\n    globalScale: 0.1\n"
    centimetres = _facts({"Stone": _node()}, unit=0.01)
    assert import_scale(_meta(text + "    useFileScale: 1\n"), centimetres) == 0.1
    assert abs(import_scale(_meta(text + "    useFileScale: 0\n"), centimetres) - 10.0) < 1e-9
    assert _meta(text + "    useFileScale: 0\n").unsupported == []


def test_the_id_of_a_node_that_carries_no_mesh_names_no_node():
    """A file with an empty mesh (`flower_sunroot_01_detailed_1.002`, no
    vertices): Unity gives it an id like any other, and a prefab shows it.
    Read as a position it would be taken for the next node."""
    meta = _meta("""fileFormatVersion: 2
guid: 4c1854d3e81e0854492ad68b4ad26613
ModelImporter:
  fileIDToRecycleName:
    4300000: Flower
    4300002: Leftover
    4300004: Flower_LOD1
""")
    facts = _facts({"Leftover": _node(mesh=False), "Flower_LOD1": _node(), "Flower_LOD0": _node()})
    assert node_for_mesh("4300002", meta, facts, "Flower") is None
    assert node_for_mesh("4300004", meta, facts, "Flower") == "Flower_LOD1"


def test_an_id_that_cannot_be_placed_falls_back_in_order():
    two = _facts({"A": _node(), "B": _node()})
    one = _facts({"Only": _node(), "Group": _node(mesh=False)})
    assert node_for_mesh("12345", ModelMeta(), two, "B") == "B"              # the object's name
    assert node_for_mesh("12345", ModelMeta(), one, "Other") == "Only"       # the only mesh node
    assert node_for_mesh("4300002", ModelMeta(), two, "Other") == "B"        # the oldest scheme, by position
    assert node_for_mesh("4300099", ModelMeta(), two, "Other") is None
    assert node_for_mesh("", ModelMeta(), two, "Other") is None
    assert node_for_mesh("4300000", ModelMeta(), _facts({}), "Other") is None


# =============================================================================
# THE OBJECTS UNITY MAKES OF A MODEL
# =============================================================================

def test_one_top_node_is_the_root_and_is_named_after_the_file():
    facts = _facts({"Lockers_body": _node(translation=(30.0, 0.0, 15.0), materials=["Lockers"]),
                    "Locker_door_A": _node("Lockers_body", translation=(-10.0, 5.0, 2.0))})
    objects = model_objects(facts, "Lockers", ModelMeta())
    assert [(o.name, o.node, o.parent) for o in objects] == [
        ("Lockers", "Lockers_body", -1), ("Locker_door_A", "Locker_door_A", 0)]
    assert _close(objects[0].position, (-0.30, 0.0, 0.15))        # X negated, centimetres to metres
    assert _close(objects[1].position, (0.10, 0.05, 0.02))
    assert objects[0].mesh_file_id == hashed_mesh_id("Lockers_body") and objects[0].material_names == ["Lockers"]
    assert (objects[0].game_object_id, objects[0].transform_id) == (HASHED_ROOT_GAME_OBJECT, HASHED_ROOT_TRANSFORM)
    # Without a table an object's ids are the hash of where it sits.
    assert (objects[1].game_object_id, objects[1].transform_id) == hashed_object_ids(["Locker_door_A"])


def test_an_objects_hashed_ids_are_those_unity_gives_it():
    """The fire pit of the NatureManufacture pack: a root of Unity's own
    with ``pit`` and ``stones`` below it. A prefab that places the model
    names the three by these ids."""
    assert hashed_object_ids([]) == (HASHED_ROOT_GAME_OBJECT, HASHED_ROOT_TRANSFORM)
    assert hashed_object_ids(["pit"])[0] == "-2514649751388021329"
    assert hashed_object_ids(["stones"])[0] == "-133806350096315675"

    objects = model_objects(_facts({"pit": _node(), "stones": _node(), "ash": _node("pit")}), "fire_pit", ModelMeta())
    ids = {model_object.name: model_object.game_object_id for model_object in objects}
    assert ids == {"fire_pit": HASHED_ROOT_GAME_OBJECT, "pit": "-2514649751388021329",
                   "stones": "-133806350096315675", "ash": hashed_object_ids(["pit", "ash"])[0]}
    # In the prefab, the placement's id and the object's own give the id Unity uses there.
    assert instance_object_id("6251434300010707833", ids["pit"]) == "854457973822105302"
    # The prefab gives each part its material by an override that names the part's renderer.
    assert hashed_renderer_id(["pit"]) == "-1023025516197406309"
    assert hashed_renderer_id(["stones"]) == "-5387654234007473875"
    renderers = {model_object.name: model_object.renderer_id for model_object in objects}
    assert renderers == {"fire_pit": "", "pit": "-1023025516197406309",
                         "stones": "-5387654234007473875", "ash": hashed_renderer_id(["pit", "ash"])}


def test_several_top_nodes_get_a_root_of_unitys_own():
    facts = _facts({"ElevatorDoor_R": _node(), "ElevatorDoor_L": _node()})
    objects = model_objects(facts, "Elevator_Doors", ModelMeta())
    assert [(o.name, o.node, o.parent) for o in objects] == [
        ("Elevator_Doors", None, -1), ("ElevatorDoor_R", "ElevatorDoor_R", 0), ("ElevatorDoor_L", "ElevatorDoor_L", 0)]
    assert objects[0].mesh_file_id == "" and _close(objects[0].rotation, (0.0, 0.0, 0.0, 1.0))


def test_pre_rotation_and_local_rotation_compose_and_mirror():
    """A 3ds Max node: pre-rotation -90 about X, local rotation +90 about X.
    The two cancel; a further local turn about Y comes out mirrored."""
    plain = model_objects(_facts({"A": _node(pre_rotation=(-90, 0, 0), rotation=(90, 0, 0))}), "A", ModelMeta())[0]
    assert _close(plain.rotation, (0.0, 0.0, 0.0, 1.0))
    turned = model_objects(_facts({"A": _node(rotation=(0, 90, 0))}), "A", ModelMeta())[0]
    assert _close(turned.rotation, (0.0, -0.7071067811865476, 0.0, 0.7071067811865476))


def test_a_z_up_file_has_its_top_nodes_turned_and_its_children_not():
    facts = _facts({"Cell": _node(translation=(350.0, 160.0, 340.0)),
                    "Bars": _node("Cell", translation=(1.0, 2.0, 3.0))}, up_axis=2)
    objects = model_objects(facts, "Cell", ModelMeta())
    assert _close(objects[0].position, (-3.5, 3.4, -1.6))         # as Unity places Cell_COL
    # Unity's familiar (-90, 0, 0) on the root of a Z-up model.
    assert _close(objects[0].rotation, (-0.7071067811865476, 0.0, 0.0, 0.7071067811865476))
    assert _close(objects[1].position, (-0.01, 0.02, 0.03))
    assert _close(objects[1].rotation, (0.0, 0.0, 0.0, 1.0))


def test_scale_is_the_nodes_and_the_table_gives_the_ids():
    facts = _facts({"Door_Metal_Gray": _node(scaling=(1.0, 2.0, 3.0)), "Handle": _node("Door_Metal_Gray")})
    objects = model_objects(facts, "Door_Metal_Gray", _meta(LEGACY_META))
    assert objects[0].scale == (1.0, 2.0, 3.0)
    assert (objects[0].game_object_id, objects[0].transform_id) == ("100000", "400000")
    assert (objects[1].game_object_id, objects[1].transform_id) == ("100002", "400002")
    assert objects[0].mesh_file_id == "4300002"


def test_a_file_without_nodes_makes_no_objects():
    assert model_objects(_facts({}), "Empty", ModelMeta()) == []


# =============================================================================
# MATERIALS
# =============================================================================

def test_materials_come_from_the_remap_then_from_the_project_by_name():
    objects = [ModelObject(name="Door", node="Door", parent=-1, material_names=["Glass", "Doors_Metal", "Unknown"])]
    assign_materials(objects, _meta(LEGACY_META), {"Glass": "cb22"}.get)
    assert objects[0].material_guids == ["cb22", "2b67611016e6bb74eaf6322e96470a76"]


def test_a_model_that_imports_no_materials_gets_none():
    objects = [ModelObject(name="Door_COL", node="Door_COL", parent=-1, material_names=["Glass"])]
    assign_materials(objects, ModelMeta(import_materials=False), {"Glass": "cb22"}.get)
    assert objects[0].material_guids == []


# =============================================================================
# AN INSTANCE OF A MODEL INSIDE A PREFAB
# The cell door of the Office pack: a root, and under it the model itself,
# renamed, with a box collider added to it.
# =============================================================================

DOOR_PREFAB = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &4237051237172027966
GameObject:
  m_Component:
  - component: {fileID: 2140103544440162284}
  m_Name: Door_Cell
--- !u!4 &2140103544440162284
Transform:
  m_GameObject: {fileID: 4237051237172027966}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children:
  - {fileID: 6791355114786859484}
  m_Father: {fileID: 0}
--- !u!1001 &6791355114786468700
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 2140103544440162284}
    m_Modifications:
    - target: {fileID: 100000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_Name
      value: Door_Cell_mesh
      objectReference: {fileID: 0}
    - target: {fileID: 400000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_RootOrder
      value: 0
      objectReference: {fileID: 0}
    - target: {fileID: 400000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_LocalPosition.y
      value: 0.25
      objectReference: {fileID: 0}
    - target: {fileID: 400000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_LocalScale.x
      value: 2
      objectReference: {fileID: 0}
    - target: {fileID: 2300000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_Materials.Array.data[0]
      value:
      objectReference: {fileID: 2100000, guid: aaaa0000aaaa0000aaaa0000aaaa0000, type: 2}
    - target: {fileID: 2300000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
      propertyPath: m_CastShadows
      value: 0
      objectReference: {fileID: 0}
    m_RemovedComponents: []
  m_SourcePrefab: {fileID: 100100000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
--- !u!1 &6791355114786436604 stripped
GameObject:
  m_CorrespondingSourceObject: {fileID: 100000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
  m_PrefabInstance: {fileID: 6791355114786468700}
--- !u!65 &7947683326461300037
BoxCollider:
  m_GameObject: {fileID: 6791355114786436604}
  m_Size: {x: 1, y: 2, z: 0.1}
  m_Center: {x: -0.5, y: 1, z: 0}
--- !u!4 &6791355114786859484 stripped
Transform:
  m_CorrespondingSourceObject: {fileID: 400000, guid: 73d690fd3e333fa4fb707fefcf9d1d16, type: 3}
  m_PrefabInstance: {fileID: 6791355114786468700}
"""

DOOR_MODEL = [ModelObject(name="Door_Cell", node="Door_Cell", parent=-1,
                          position=(1.0, 2.0, 3.0), rotation=(0.0, 0.0, 0.0, 1.0), scale=(1.0, 1.0, 1.0),
                          mesh_file_id="4300000", material_names=["Cell_Props"], material_guids=["1d11"],
                          game_object_id="100000", transform_id="400000")]


class _Coverage:
    def record_component(self, *_):
        pass


class _Collider:
    def parse(self, comp_type, comp_data, go, log):
        go.colliders.append({"type": comp_type, "size": comp_data["m_Size"]})


def _parse(model_objects_for):
    log = []
    context = UnityParseContext(log=log.append, coverage=_Coverage(),
                                component_dispatch={"BoxCollider": _Collider()},
                                model_objects=model_objects_for)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "Door_Cell.prefab"
        path.write_text(DOOR_PREFAB, encoding="utf-8")
        game_objects, _ = parse_unity_prefab(context, path)
    return game_objects, log


def test_a_model_instance_becomes_a_plain_object_with_the_models_mesh():
    game_objects, _ = _parse(lambda guid: DOOR_MODEL if guid.startswith("73d6") else None)
    door = game_objects["6791355114786436604"]              # the id Unity gives it in this file
    assert door.is_prefab_instance is False
    assert door.mesh_guid == "73d690fd3e333fa4fb707fefcf9d1d16" and door.mesh_file_id == "4300000"
    assert door.parent_id == "4237051237172027966"
    assert game_objects["4237051237172027966"].children_ids == ["6791355114786436604"]


def test_the_instances_overrides_land_on_the_models_object():
    game_objects, log = _parse(lambda guid: DOOR_MODEL)
    door = game_objects["6791355114786436604"]
    assert door.name == "Door_Cell_mesh"
    assert door.transform.position == (1.0, 0.25, 3.0)       # the model's, with y overridden
    assert door.transform.scale == (2.0, 1.0, 1.0)
    assert door.material_guids == ["aaaa0000aaaa0000aaaa0000aaaa0000"]   # the only renderer's slot 0
    assert any("overrides=6 (1 not applied)" in line for line in log), log


def test_a_component_added_to_the_instance_attaches_to_the_object():
    game_objects, _ = _parse(lambda guid: DOOR_MODEL)
    assert game_objects["6791355114786436604"].colliders == [
        {"type": "BoxCollider", "size": {"x": 1, "y": 2, "z": 0.1}}]


def test_without_a_model_lookup_the_instance_stays_what_it_was():
    game_objects, _ = _parse(None)
    assert game_objects["6791355114786468700"].is_prefab_instance is True
    assert "6791355114786436604" not in game_objects


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
