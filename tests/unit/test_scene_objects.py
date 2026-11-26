"""Unit tests for what a scene holds beside its prefab instances
(second_pack I.2 and I.4, proof T.3):

  - a scene's own object with a mesh gets its model and materials, through
    the same asset conversion a prefab's objects go through;
  - Unity's built-in cube (the floor of the Office pack's Showcase) is
    written and shown;
  - a model file instanced straight in a scene becomes entities;
  - a placed prefab is found by its guid, whatever the scene calls it.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.builtin_meshes import BUILTIN_MESH_GUID
from platforms.unity.model_import import ModelObject
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter
from stage_runner import run_scene_converter

MODEL_GUID = "73d690fd3e333fa4fb707fefcf9d1d16"
PREFAB_GUID = "0a57bd4f560b8c84b9a753256274131c"
MATERIAL_GUID = "9e14b91c124f40844babf8171a66d570"
MESH = "AZ::Render::EditorMeshComponent"


# =============================================================================
# FIXTURES
# =============================================================================

HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"

FLOOR = f"""--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  - component: {{fileID: 3300}}
  - component: {{fileID: 2300}}
  m_Name: Cube
--- !u!4 &400
Transform:
  m_GameObject: {{fileID: 100}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: -0.5, z: 0}}
  m_LocalScale: {{x: 400, y: 0.99, z: 282.8}}
  m_Children: []
  m_Father: {{fileID: 0}}
--- !u!33 &3300
MeshFilter:
  m_GameObject: {{fileID: 100}}
  m_Mesh: {{fileID: 10202, guid: {BUILTIN_MESH_GUID}, type: 0}}
--- !u!23 &2300
MeshRenderer:
  m_GameObject: {{fileID: 100}}
  m_Materials:
  - {{fileID: 2100000, guid: {MATERIAL_GUID}, type: 2}}
"""


def _instance(anchor: str, source_guid: str, name: str, scale: float = 0.0) -> str:
    """A PrefabInstance at the top of a scene, renamed by the scene, and
    scaled the same on all axes when ``scale`` is given."""
    lines = [f"--- !u!1001 &{anchor}", "PrefabInstance:", "  m_Modification:",
             "    m_TransformParent: {fileID: 0}", "    m_Modifications:"]
    overrides = [("100000", "m_Name", name), ("400000", "m_RootOrder", 0)]
    overrides += [("400000", f"m_LocalPosition.{axis}", value) for axis, value in zip("xyz", (1, 2, 3))]
    overrides += [("400000", f"m_LocalRotation.{axis}", value) for axis, value in zip("xyzw", (0, 0, 0, 1))]
    if scale:
        overrides += [("400000", f"m_LocalScale.{axis}", scale) for axis in "xyz"]
    for target, path, value in overrides:
        lines += [f"    - target: {{fileID: {target}, guid: {source_guid}, type: 3}}",
                  f"      propertyPath: {path}", f"      value: {value}", "      objectReference: {fileID: 0}"]
    lines += ["    m_RemovedComponents: []", f"  m_SourcePrefab: {{fileID: 100100000, guid: {source_guid}, type: 3}}"]
    return "\n".join(lines) + "\n"


def _level(scene_text: str, asset_processor=None, tmp: Path = None) -> dict:
    """Convert a scene given as text; return the level it wrote."""
    scene = tmp / "Gallery.unity"
    scene.write_text(HEADER + scene_text, encoding="utf-8")
    level = tmp / "Gallery.prefab"
    converter = UnitySceneConverter(PrefabDatabase(), log_callback=lambda line: None,
                                    asset_processor=asset_processor)
    converter.parse_unity_scene(str(scene))
    converter.create_o3de_level(str(level), tmp)
    return json.loads(level.read_text(encoding="utf-8"))


def _named(level: dict, name: str) -> dict:
    return next(entity for entity in level["Entities"].values() if entity["Name"] == name)


class _Assets:
    """Stands in for the Stage 1 worker: says what each object shows."""

    def __init__(self, model=None):
        self.model = model
        self.asked_for = []

    def model_objects_for(self, guid):
        return self.model if guid == MODEL_GUID else None

    def convert_assets_of(self, game_objects, owner_name):
        self.asked_for = sorted(go.name for go in game_objects.values())
        return {
            "materials":        {MATERIAL_GUID: "assets/pack/materials/wall.azmaterial"},
            "meshes":           {go.file_id: f"assets/pack/meshes/{go.name.lower()}.azmodel"
                                 for go in game_objects.values() if go.mesh_guid},
            "material_labels":  {go.file_id: ["Wall"] for go in game_objects.values() if go.mesh_guid},
            "collision_meshes": {},
        }


# =============================================================================
# A SCENE'S OWN OBJECT WITH A MESH
# =============================================================================

def test_a_scene_object_gets_the_model_and_material_the_asset_conversion_names():
    with tempfile.TemporaryDirectory() as folder:
        assets = _Assets()
        cube = _named(_level(FLOOR, assets, Path(folder)), "Cube")
        hint = cube["Components"][MESH]["Controller"]["Configuration"]["ModelAsset"]["assetHint"]
        assert hint == "assets/pack/meshes/cube.azmodel"
        assert "assets/pack/materials/wall.azmaterial" in json.dumps(cube["Components"])
        assert assets.asked_for == ["Cube"]


def test_without_the_stage_1_worker_a_scene_object_is_placed_bare():
    with tempfile.TemporaryDirectory() as folder:
        cube = _named(_level(FLOOR, None, Path(folder)), "Cube")
        assert MESH not in cube["Components"]
        assert cube["Components"]["EditorNonUniformScaleComponent"]["NonUniformScale"] == [400.0, 282.8, 0.99]


def test_the_built_in_cube_of_a_scene_is_written_and_shown():
    """The floor of the Showcase, through the real Stage 1 worker."""
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        (tmp / "unity").mkdir()
        random.seed(7)
        worker = IntegratedAssetProcessor(tmp / "unity", tmp / "out", log_callback=lambda line: None)
        cube = _named(_level(FLOOR, worker, tmp), "Cube")
        hint = cube["Components"][MESH]["Controller"]["Configuration"]["ModelAsset"]["assetHint"]
        assert hint.endswith("/meshes/UnityBuiltin_Cube-Cube.obj.azmodel"), hint
        assert (tmp / "out" / "Meshes" / "UnityBuiltin_Cube.obj").is_file()
        assert (tmp / "out" / "Meshes" / "UnityBuiltin_Cube.obj.assetinfo").is_file()


# =============================================================================
# A MODEL FILE INSTANCED IN A SCENE
# =============================================================================

MODEL = [
    ModelObject(name="Door", node="Door", parent=-1, position=(0.0, 0.0, 0.0),
                mesh_file_id="4300000", material_guids=[MATERIAL_GUID],
                game_object_id="100000", transform_id="400000"),
    ModelObject(name="Handle", node="Handle", parent=0, position=(0.5, 1.0, 0.0),
                mesh_file_id="4300002", material_guids=[MATERIAL_GUID],
                game_object_id="100002", transform_id="400002"),
]


def test_a_model_instanced_in_a_scene_becomes_entities_with_its_meshes():
    with tempfile.TemporaryDirectory() as folder:
        assets = _Assets(MODEL)
        level = _level(_instance("7000", MODEL_GUID, "Front_door"), assets, Path(folder))
        assert level["Instances"] == {}
        door, handle = _named(level, "Front_door"), _named(level, "Handle")
        assert door["Components"]["TransformComponent"]["Transform Data"]["Translate"] == [1.0, 3.0, 2.0]
        assert MESH in door["Components"] and MESH in handle["Components"]
        # The handle hangs under the door, placed as the model has it (y and z swapped).
        assert handle["Components"]["TransformComponent"]["Parent Entity"] == door["Id"]
        assert handle["Components"]["TransformComponent"]["Transform Data"]["Translate"] == [0.5, 0.0, 1.0]
        assert assets.asked_for == ["Front_door", "Handle"]


# =============================================================================
# A PLACED PREFAB IS FOUND BY ITS GUID
# =============================================================================

def _run(tmp: Path, scene_text: str, records: dict):
    prefabs = tmp / "out" / "Prefabs"
    prefabs.mkdir(parents=True)
    for name in ("W_3x_Elevator", "Door"):
        (prefabs / f"{name}.prefab").write_text("{}", encoding="utf-8")
    scene = tmp / "Example.unity"
    scene.write_text(HEADER + scene_text, encoding="utf-8")
    run = run_scene_converter([scene], str(tmp / "levels"), [str(prefabs)], {"prefabs": records}, lambda line: None)
    level = json.loads((tmp / "levels" / "Example" / "Example.prefab").read_text(encoding="utf-8"))
    return run, level


def test_a_renamed_instance_is_found_by_the_guid_of_its_prefab():
    """The Office pack's example level: `W_3x_Elevator` placed and called
    `W_3x_Elevator_Door`. By name there is no such prefab."""
    with tempfile.TemporaryDirectory() as folder:
        records = {PREFAB_GUID: {"source_guid": PREFAB_GUID, "output_path": "Prefabs/W_3x_Elevator.prefab"}}
        run, level = _run(Path(folder), _instance("7000", PREFAB_GUID, "W_3x_Elevator_Door"), records)
        assert run.totals["total_missing_prefabs"] == 0, run.totals
        sources = [instance["Source"] for instance in level["Instances"].values()]
        assert len(sources) == 1 and sources[0].endswith("W_3x_Elevator.prefab"), sources


def test_the_guid_wins_over_a_name_that_belongs_to_another_prefab():
    with tempfile.TemporaryDirectory() as folder:
        records = {PREFAB_GUID: {"source_guid": PREFAB_GUID, "output_path": "Prefabs/W_3x_Elevator.prefab"}}
        _, level = _run(Path(folder), _instance("7000", PREFAB_GUID, "Door"), records)
        sources = [instance["Source"] for instance in level["Instances"].values()]
        assert sources[0].endswith("W_3x_Elevator.prefab"), sources


def test_a_placed_prefabs_uniform_scale_is_patched_under_the_engines_field_name():
    """88 glasses and bottles of the Tirgames level are placed at 0.796 of
    their size. Written to `Scale`, the engine's legacy field, that was lost."""
    with tempfile.TemporaryDirectory() as folder:
        _, level = _run(Path(folder), _instance("7000", PREFAB_GUID, "Door", scale=0.796), {})
        patches = list(level["Instances"].values())[0]["Patches"]
        scale = [patch for patch in patches if "Scale" in patch["path"]]
        assert len(scale) == 1 and scale[0]["value"] == 0.796, scale
        assert scale[0]["path"] == "/ContainerEntity/Components/TransformComponent/Transform Data/UniformScale"


def test_without_a_record_the_name_is_still_tried():
    with tempfile.TemporaryDirectory() as folder:
        run, level = _run(Path(folder), _instance("7000", PREFAB_GUID, "Door (2)"), {})
        assert run.totals["total_missing_prefabs"] == 0
        assert list(level["Instances"].values())[0]["Source"].endswith("Door.prefab")


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
