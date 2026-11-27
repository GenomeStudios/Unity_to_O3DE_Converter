"""Unit tests for what the engine's builders refuse (nature_pack I.4).

The first cook of the NatureManufacture pack left 149 failed jobs of three
kinds. Each is a rule of the engine the converter now writes for:

  - a model holds exactly the nodes its group selects: left to itself the
    engine files every node called ``..._LOD1`` under level of detail 1 of
    every model of the file, and a model made of such a node is empty;
  - an entity with a material component needs a mesh component;
  - the engine's TGA loader reads no greyscale file.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.fixtures.unity_tree import write_fake_fbx
from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor, PIL_AVAILABLE, is_greyscale_tga
from platforms.unity.components.material import MESH_COMPONENT, MaterialComponentProcessor
from platforms.unity.types import GameObject, Transform
from targets.o3de.assetinfo_writer import LOD_RULE_LEVELS, lod_rule_of_one_level, write_fbx_assetinfo

MATERIAL_GUID = "9e14b91c124f40844babf8171a66d570"
MATERIAL_COMPONENT = "EditorMaterialComponent"


# =============================================================================
# A MODEL IS ONE LEVEL OF DETAIL: THE NODES ITS GROUP SELECTS
# =============================================================================

def test_every_level_of_the_rule_is_written_and_selects_nothing():
    """The engine adds each level a rule does not hold yet, from the file's
    node names. A rule that holds them all is left as written."""
    nodes = ["RootNode", "RootNode.grass_LOD0", "RootNode.grass_LOD1"]
    rule = lod_rule_of_one_level(nodes)
    assert len(rule["nodeSelectionList"]) == LOD_RULE_LEVELS == 5
    for level in rule["nodeSelectionList"]:
        assert level == {"selectedNodes": [], "unselectedNodes": nodes}


def test_a_model_of_a_lower_level_node_carries_the_rule_like_any_other():
    """`grass_beech_forest_01_1.fbx`: a prefab shows the file's `_LOD1` node
    as its only model. Its group selects that node and nothing else."""
    with tempfile.TemporaryDirectory() as folder:
        model = Path(folder) / "grass.fbx"
        write_fake_fbx(model)
        write_fbx_assetinfo(model, "grass", {"grass_LOD0": "RootNode.grass_LOD0", "grass_LOD1": "RootNode.grass_LOD1"},
                            log=lambda line: None)
        groups = json.loads(Path(str(model) + ".assetinfo").read_text(encoding="utf-8"))["values"]
        assert [group["name"] for group in groups] == ["grass-grass_LOD0", "grass-grass_LOD1"]
        for group, own, other in zip(groups, ("RootNode.grass_LOD0", "RootNode.grass_LOD1"),
                                     ("RootNode.grass_LOD1", "RootNode.grass_LOD0")):
            assert group["nodeSelectionList"] == {"selectedNodes": ["RootNode", own], "unselectedNodes": [other]}
            rule = next(rule for rule in group["rules"]["rules"] if rule["$type"].endswith("LodRule"))
            assert len(rule["nodeSelectionList"]) == 5
            assert all(level["selectedNodes"] == [] and set(level["unselectedNodes"]) == {"RootNode", own, other}
                       for level in rule["nodeSelectionList"])


# =============================================================================
# NO MATERIAL COMPONENT WITHOUT A MESH COMPONENT
# =============================================================================

def _emit_materials(with_mesh: bool):
    go = GameObject(file_id="1", name="beech_tree_01_LOD0", transform=Transform(), material_guids=[MATERIAL_GUID])
    entity = {"Id": "Entity_[1]", "Components": {"TransformComponent": {}}}
    if with_mesh:
        entity["Components"][MESH_COMPONENT] = {"$type": MESH_COMPONENT}
    lines = []
    context = SimpleNamespace(material_mapping={MATERIAL_GUID: "assets/pack/materials/bark.azmaterial"},
                              fbx_material_labels={"1": ["Bark"]}, generate_component_id=lambda: 7,
                              log=lines.append, stats={})
    MaterialComponentProcessor().emit(go, entity, context)
    return entity, lines


def test_an_object_that_shows_no_model_gets_no_materials():
    """A tree whose best level is a Unity mesh asset the converter cannot
    read: with its materials and no mesh the engine refused the entity, and
    the whole prefab's job failed."""
    entity, lines = _emit_materials(with_mesh=False)
    assert MATERIAL_COMPONENT not in entity["Components"]
    assert any("shows no model" in line for line in lines)


def test_an_object_with_a_model_keeps_its_materials():
    entity, _ = _emit_materials(with_mesh=True)
    assert "bark.azmaterial" in json.dumps(entity["Components"][MATERIAL_COMPONENT])


# =============================================================================
# A GREYSCALE TGA IS WRITTEN AS A PNG
# =============================================================================

def _textures(tmp: Path):
    """A greyscale and a colour TGA under ``tmp/unity``, each with a guid."""
    from PIL import Image
    unity = tmp / "unity"
    unity.mkdir()
    Image.new("L", (2, 2), 120).save(unity / "Height.tga")
    Image.new("RGB", (2, 2), (10, 20, 30)).save(unity / "Colour.tga")
    for name, guid in (("Height.tga", "a" * 32), ("Colour.tga", "b" * 32)):
        (unity / f"{name}.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8")
    random.seed(7)
    return IntegratedAssetProcessor(unity, tmp / "out", log_callback=lambda line: None)


def test_a_tga_is_greyscale_by_its_headers_image_type():
    if not PIL_AVAILABLE:
        return
    with tempfile.TemporaryDirectory() as folder:
        _textures(Path(folder))
        assert is_greyscale_tga(Path(folder) / "unity" / "Height.tga")
        assert not is_greyscale_tga(Path(folder) / "unity" / "Colour.tga")
        assert not is_greyscale_tga(Path(folder) / "unity" / "Missing.tga")
        assert not is_greyscale_tga(Path(folder) / "unity" / "Height.tga.meta")


def test_a_greyscale_tga_is_written_as_png_and_a_colour_one_copied():
    """The engine's TGA loader reads true-colour and colour-mapped files
    only. A material names the file the converter wrote."""
    if not PIL_AVAILABLE:
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as folder:
        worker = _textures(Path(folder))
        assert worker._process_texture("a" * 32) == "Textures/Height.png"
        assert worker._process_texture("b" * 32) == "Textures/Colour.tga"
        out = Path(folder) / "out" / "Textures"
        assert sorted(path.name for path in out.iterdir()) == ["Colour.tga", "Height.png"]
        with Image.open(out / "Height.png") as image:
            assert image.mode == "L" and image.getpixel((0, 0)) == 120


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
