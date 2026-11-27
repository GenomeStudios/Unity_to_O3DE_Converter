"""Unit tests for where the converter writes what it converts (nature_pack I.2).

The flat layout has one folder per kind of asset. A distributor's folder that
holds several packs repeats file names (the NatureManufacture assets: 21
prefab names, 12 model names and 152 texture names used more than once), and
flat they land on one another. With the stage option
``mirror_source_folders`` every asset keeps its source's folder:

  - two packs' prefabs, materials and textures of one name stay apart, and
    each prefab shows its own pack's material;
  - a material names its texture from its own folder, and every hint
    follows the file it names;
  - a prefab that nests another names the nested one where it was written;
  - a scene finds a placed prefab by its guid, and its level keeps the
    scene's folders, so two scenes of one name are two levels;
  - the flat layout is what it was.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import (
    IntegratedAssetProcessor, MIRROR_OPTION, OUTSIDE_SOURCE_FOLDER, mirrored_folder,
)
from stage_runner import level_name_for, run_scene_converter

HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
META = "fileFormatVersion: 2\nguid: {guid}\n"
PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082")

# One distributor's folder with two packs. Each has a prefab `Rock`, a material
# `Stone` and a texture `stone.png` of its own.
PACKS = {
    "Forest": {"prefab": "f0000000000000000000000000000001", "material": "f0000000000000000000000000000002",
               "texture": "f0000000000000000000000000000003"},
    "Meadow": {"prefab": "e0000000000000000000000000000001", "material": "e0000000000000000000000000000002",
               "texture": "e0000000000000000000000000000003"},
}
PILE_GUID = "f0000000000000000000000000000009"


# =============================================================================
# FIXTURES
# =============================================================================

def _write(path: Path, text: str, guid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    Path(str(path) + ".meta").write_text(META.format(guid=guid), encoding="utf-8")


def _rock(material_guid: str) -> str:
    """A prefab of one object that shows one material."""
    return HEADER + f"""--- !u!1 &100000
GameObject:
  m_Component:
  - component: {{fileID: 400000}}
  - component: {{fileID: 2300000}}
  m_Name: Rock
--- !u!4 &400000
Transform:
  m_GameObject: {{fileID: 100000}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children: []
  m_Father: {{fileID: 0}}
--- !u!23 &2300000
MeshRenderer:
  m_GameObject: {{fileID: 100000}}
  m_Materials:
  - {{fileID: 2100000, guid: {material_guid}, type: 2}}
"""


def _material(texture_guid: str) -> str:
    return HEADER + f"""--- !u!21 &2100000
Material:
  m_Name: Stone
  m_Shader: {{fileID: 46, guid: 0000000000000000f000000000000000, type: 0}}
  m_SavedProperties:
    m_TexEnvs:
    - _MainTex:
        m_Texture: {{fileID: 2800000, guid: {texture_guid}, type: 3}}
        m_Scale: {{x: 1, y: 1}}
        m_Offset: {{x: 0, y: 0}}
    m_Floats: []
    m_Colors:
    - _Color: {{r: 1, g: 1, b: 1, a: 1}}
"""


def _placed(anchor: str, source_guid: str, parent: str = "0") -> str:
    """A PrefabInstance of one of the rocks, in a prefab or at the top of a scene."""
    return f"""--- !u!1001 &{anchor}
PrefabInstance:
  m_Modification:
    m_TransformParent: {{fileID: {parent}}}
    m_Modifications:
    - target: {{fileID: 100000, guid: {source_guid}, type: 3}}
      propertyPath: m_Name
      value: Rock
      objectReference: {{fileID: 0}}
    m_RemovedComponents: []
  m_SourcePrefab: {{fileID: 100100000, guid: {source_guid}, type: 3}}
"""


def _pile() -> str:
    """A prefab that nests the Forest rock."""
    return HEADER + """--- !u!1 &100000
GameObject:
  m_Component:
  - component: {fileID: 400000}
  m_Name: Pile
--- !u!4 &400000
Transform:
  m_GameObject: {fileID: 100000}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children: []
  m_Father: {fileID: 0}
""" + _placed("7000", PACKS["Forest"]["prefab"], parent="400000")


def _project(tmp: Path, mirror: bool):
    """The two packs under ``unity/Assets/Vendor``, converted into
    ``o3de/Assets/Vendor``. Returns ``(worker, source root, output root)``."""
    source, output = tmp / "unity" / "Assets" / "Vendor", tmp / "o3de" / "Assets" / "Vendor"
    (tmp / "o3de").mkdir(parents=True, exist_ok=True)
    (tmp / "o3de" / "project.json").write_text("{}", encoding="utf-8")
    for pack, guids in PACKS.items():
        _write(source / pack / "Prefabs" / "Rock.prefab", _rock(guids["material"]), guids["prefab"])
        _write(source / pack / "Materials" / "Stone.mat", _material(guids["texture"]), guids["material"])
        (source / pack / "Textures").mkdir(parents=True, exist_ok=True)
        (source / pack / "Textures" / "stone.png").write_bytes(PNG + pack.encode("ascii"))
        (source / pack / "Textures" / "stone.png.meta").write_text(META.format(guid=guids["texture"]), encoding="utf-8")
    _write(source / "Forest" / "Sets" / "Pile.prefab", _pile(), PILE_GUID)

    random.seed(7)
    worker = IntegratedAssetProcessor(source, output, log_callback=lambda line: None,
                                      options={MIRROR_OPTION: mirror})
    for prefab in (source / "Forest" / "Prefabs" / "Rock.prefab", source / "Meadow" / "Prefabs" / "Rock.prefab",
                   source / "Forest" / "Sets" / "Pile.prefab"):
        assert worker.process_prefab(prefab), prefab
    return worker, source, output


def _material_hint(worker, pack: str) -> str:
    """The hint the worker names a pack's converted `Stone` material by."""
    return worker.asset_index["materials"][PACKS[pack]["material"]]


# =============================================================================
# WHERE A SOURCE FILE GOES
# =============================================================================

def test_a_file_keeps_its_folder_below_the_source_root():
    root = Path("U:/Game/Assets/Vendor")
    assert mirrored_folder(root, root / "Forest" / "Rocks" / "Rock.fbx") == Path("Forest/Rocks")
    assert mirrored_folder(root, root / "Rock.fbx") == Path(".")


def test_a_file_outside_the_source_root_is_kept_apart_by_its_place_in_the_unity_project():
    """A prefab may show a texture of another pack. It is neither dropped
    nor mixed into the packs' own folders."""
    root = Path("U:/Game/Assets/Vendor")
    assert mirrored_folder(root, Path("U:/Game/Assets/Shared/Noise/noise.png")) == Path(OUTSIDE_SOURCE_FOLDER, "Shared", "Noise")
    assert mirrored_folder(root, Path("U:/Elsewhere/Loose/noise.png")) == Path(OUTSIDE_SOURCE_FOLDER, "Loose")


# =============================================================================
# THE MIRRORED LAYOUT
# =============================================================================

def test_two_packs_assets_of_one_name_stay_apart():
    with tempfile.TemporaryDirectory() as folder:
        _, _, output = _project(Path(folder), mirror=True)
        for pack in PACKS:
            assert (output / pack / "Prefabs" / "Rock.prefab").is_file()
            assert (output / pack / "Materials" / "Stone.material").is_file()
            assert (output / pack / "Textures" / "stone.png").read_bytes().endswith(pack.encode("ascii"))
        # Nothing is left in folders by kind.
        assert not (output / "Prefabs").exists() and not (output / "Textures").exists()


def test_each_packs_material_is_named_where_it_was_written():
    with tempfile.TemporaryDirectory() as folder:
        worker, _, _ = _project(Path(folder), mirror=True)
        assert _material_hint(worker, "Forest") == "assets/vendor/forest/materials/Stone.azmaterial"
        assert _material_hint(worker, "Meadow") == "assets/vendor/meadow/materials/Stone.azmaterial"


def test_a_material_names_its_texture_from_its_own_folder():
    with tempfile.TemporaryDirectory() as folder:
        _, _, output = _project(Path(folder), mirror=True)
        material = json.loads((output / "Meadow" / "Materials" / "Stone.material").read_text(encoding="utf-8"))
        assert material["propertyValues"]["baseColor.textureMap"] == "../Textures/stone.png"
        assert (output / "Meadow" / "Materials" / material["propertyValues"]["baseColor.textureMap"]).resolve() \
            == (output / "Meadow" / "Textures" / "stone.png").resolve()


def test_the_bookkeeping_knows_each_prefab_by_its_guid_and_its_place():
    with tempfile.TemporaryDirectory() as folder:
        worker, source, _ = _project(Path(folder), mirror=True)
        records = worker._project_prefab_records
        for pack, guids in PACKS.items():
            assert records[guids["prefab"]]["output_path"] == f"{pack}/Prefabs/Rock.prefab"
            assert Path(records[guids["prefab"]]["source_path"]) == source / pack / "Prefabs" / "Rock.prefab"


def test_a_nested_prefab_is_named_where_it_was_written():
    with tempfile.TemporaryDirectory() as folder:
        _, _, output = _project(Path(folder), mirror=True)
        pile = json.loads((output / "Forest" / "Sets" / "Pile.prefab").read_text(encoding="utf-8"))
        assert [instance["Source"] for instance in pile["Instances"].values()] == [
            "Assets/Vendor/Forest/Prefabs/Rock.prefab"]


# =============================================================================
# THE FLAT LAYOUT IS WHAT IT WAS
# =============================================================================

def test_flat_every_kind_has_its_folder_and_a_repeated_name_is_one_file():
    with tempfile.TemporaryDirectory() as folder:
        worker, _, output = _project(Path(folder), mirror=False)
        assert sorted(path.name for path in output.iterdir()) == ["Materials", "Meshes", "Prefabs", "Textures"]
        assert sorted(path.name for path in (output / "Prefabs").iterdir()) == ["Pile.prefab", "Rock.prefab"]
        material = json.loads((output / "Materials" / "Stone.material").read_text(encoding="utf-8"))
        assert material["propertyValues"]["baseColor.textureMap"] == "../Textures/stone.png"
        assert _material_hint(worker, "Forest") == _material_hint(worker, "Meadow") == "assets/vendor/materials/Stone.azmaterial"
        pile = json.loads((output / "Prefabs" / "Pile.prefab").read_text(encoding="utf-8"))
        assert [instance["Source"] for instance in pile["Instances"].values()] == ["Assets/Vendor/Prefabs/Rock.prefab"]


# =============================================================================
# THE SCENE STAGE
# =============================================================================

def _asset_stage(source: Path, output: Path, mirror: bool) -> dict:
    return {"source_path": str(source), "output_path": str(output), "options": {MIRROR_OPTION: mirror}}


def test_a_level_keeps_its_scenes_folders_when_the_output_mirrors_the_source():
    source = Path("U:/Game/Assets/Vendor")
    scene = source / "Forest" / "Demo Scenes" / "Overview Scene.unity"
    assert level_name_for(scene, _asset_stage(source, Path("O:/out"), mirror=True)) == "Forest/Demo Scenes/Overview Scene"
    assert level_name_for(scene, _asset_stage(source, Path("O:/out"), mirror=False)) == "Overview Scene"
    assert level_name_for(scene, None) == "Overview Scene"


def test_two_scenes_of_one_name_place_their_own_packs_prefab():
    """Each scene places `Rock` of its pack. By file name both would get the
    same prefab, and the second level would be written over the first."""
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        worker, source, output = _project(tmp, mirror=True)
        scenes = []
        for pack, guids in PACKS.items():
            scene = source / pack / "Demo" / "Overview.unity"
            scene.parent.mkdir(parents=True, exist_ok=True)
            scene.write_text(HEADER + _placed("9000", guids["prefab"]), encoding="utf-8")
            scenes.append(scene)

        levels = tmp / "o3de" / "Levels"
        run = run_scene_converter(scenes, str(levels), [str(output)], worker.to_outputs(), lambda line: None,
                                  asset_stage=_asset_stage(source, output, mirror=True))
        assert run.errors == 0 and sorted(run.outputs["scenes"]) == ["Forest/Demo/Overview.unity", "Meadow/Demo/Overview.unity"]
        for pack in PACKS:
            level = json.loads((levels / pack / "Demo" / "Overview" / "Overview.prefab").read_text(encoding="utf-8"))
            assert [instance["Source"] for instance in level["Instances"].values()] == [
                f"Assets/Vendor/{pack}/Prefabs/Rock.prefab"]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
