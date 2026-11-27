"""Unit tests for what the person found walking the converted levels
(second_pack I.5 to I.7):

  - a spot light shines the way Unity's does, on its own entity or on a child,
    a point light is a simple point, and every light ends at
    Unity's range;
  - a collision mesh is not drawn over its model;
  - a material override on a placed prefab reaches the renderer it targets;
  - a transparent surface blends, an alpha clip at zero clips nothing, and
    the opacity numbers are the engine's;
  - a texture whose alpha is the opacity is told to keep it;
  - roughness and occlusion are read from the channel Unity keeps them in.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import CoverageTracker, IntegratedAssetProcessor, PIL_AVAILABLE
from platforms.unity.asset_database import AssetDatabase, uv_transform
import matrix3
from platforms.unity.components.light import (
    ATTENUATION_EXPLICIT, LightComponentProcessor, O3DE_SIMPLE_POINT, PLACEMENT_CHILD, PLACEMENT_OPTION,
    PLACEMENT_TURN, SPOT_CHILD_ROTATION, UNITY_POINT, UNITY_SPOT, light_record,
)
from platforms.unity.components.mesh_collider import _write_mesh_collider
from platforms.unity.types import GameObject, Transform
from targets.o3de.prefab_writer import (
    light_override_patches, material_override_patches, mesh_override_patches, overrides_a_light, with_light_turn,
)
from targets.o3de.texture_settings import OPACITY_PRESET, write_opacity_texture_settings

LIGHT = "AZ::Render::EditorAreaLightComponent"


# =============================================================================
# FIXTURES
# =============================================================================

def _context():
    """The few things a component processor asks of its context."""
    entities, counter = {}, iter(range(1, 1000))

    def bare(entity_id, name, parent):
        return {"Id": entity_id, "Name": name,
                "Components": {"TransformComponent": {"Parent Entity": parent}}}

    return SimpleNamespace(
        entities_dict=entities, stats={}, log=lambda line: None,
        generate_component_id=lambda: next(counter),
        generate_entity_id=lambda: f"Entity_[{next(counter)}]",
        make_bare_entity=bare, collider_pxmesh_mapping={}, collision_config={})


def _lamp(light_type, **fields):
    """An object that holds a light, and whatever else ``fields`` give it."""
    go = GameObject(file_id="1", name="Lamp", transform=Transform(), **fields)
    go.component_data["unity_light"] = {"type": light_type, "color": [1.0, 0.9, 0.8], "intensity": 4.0,
                                        "range": 7.0, "shadows": True, "spot_outer": 30.0, "spot_inner": 15.0}
    go.component_ids["Light"] = "10800000"
    return go


def _light(light_type, go=None):
    go = go or _lamp(light_type)
    entity = {"Id": "Entity_[0]", "Name": "Lamp", "Components": {"TransformComponent": {}}}
    context = _context()
    children = LightComponentProcessor().emit(go, entity, context)
    return entity, context, children


def _forward(transform):
    """Where the +Z of an entity with this transform points, in its parent."""
    return [round(value, 6) for value in matrix3.mat_vec(matrix3.quat_to_matrix(transform.rotation), [0, 0, 1])]


# =============================================================================
# LIGHTS
# =============================================================================

def test_a_spot_light_sits_on_a_child_turned_to_shine_along_the_objects_forward():
    """An O3DE spot shines along its entity's +Z; the converted Unity
    object points its light along +Y. The child's quarter turn about X
    carries one onto the other, and the object keeps Unity's transform."""
    entity, context, children = _light(UNITY_SPOT)
    assert LIGHT not in entity["Components"] and len(children) == 1
    child = context.entities_dict[children[0]]
    assert child["Name"] == "Lamp_Light"
    assert child["Components"]["TransformComponent"]["Parent Entity"] == "Entity_[0]"
    assert child["Components"]["TransformComponent"]["Transform Data"]["Rotate"] == SPOT_CHILD_ROTATION == [-90.0, 0.0, 0.0]
    assert LIGHT in child["Components"]


def test_an_object_that_holds_only_a_spot_has_its_own_entity_turned():
    """No second entity is made: the entity's +Z, along which the spot
    shines, ends up where the object's +Y was."""
    go = _lamp(UNITY_SPOT)
    turned = with_light_turn(go, Transform(), False, {})          # the default placement
    assert _forward(turned) == [0.0, 1.0, 0.0]
    entity, context, children = _light(UNITY_SPOT, go)
    assert children == [] and LIGHT in entity["Components"] and context.entities_dict == {}
    assert go.component_data["light_entity"] == {"entity": "Entity_[0]", "component": LIGHT}


def test_the_turn_follows_the_objects_own_rotation():
    half = 0.5 ** 0.5
    facing_x = Transform(rotation=(0.0, 0.0, -half, half))        # +Y turned onto +X
    assert _forward(with_light_turn(_lamp(UNITY_SPOT), facing_x, False, {})) == [1.0, 0.0, 0.0]


def test_a_spot_keeps_the_child_when_asked_or_when_the_object_holds_more():
    """Turning the entity would turn the mesh, the collider or the children
    with it; and the option can ask for the child everywhere."""
    def kept(go, options=None, needs_nonuniform=False):
        plain = Transform()
        return (with_light_turn(go, plain, needs_nonuniform, options or {}) is plain
                and "light_turns_entity" not in go.component_data)

    assert kept(_lamp(UNITY_SPOT), {PLACEMENT_OPTION: PLACEMENT_CHILD})
    assert kept(_lamp(UNITY_SPOT, mesh_guid="abcd"))
    assert kept(_lamp(UNITY_SPOT, children_ids=["2"]))
    assert kept(_lamp(UNITY_SPOT, colliders=[{"type": "BoxCollider"}]))
    assert kept(_lamp(UNITY_SPOT), needs_nonuniform=True)
    assert kept(_lamp(UNITY_POINT)), "only a spot has a direction to turn"
    assert not kept(_lamp(UNITY_SPOT), {PLACEMENT_OPTION: PLACEMENT_TURN})


def test_every_light_ends_at_unitys_range():
    for light_type in (UNITY_SPOT, UNITY_POINT):
        entity, context, children = _light(light_type)
        holder = context.entities_dict[children[0]] if children else entity
        configuration = holder["Components"][LIGHT]["Controller"]["Configuration"]
        assert configuration["AttenuationRadiusMode"] == ATTENUATION_EXPLICIT == 0
        assert configuration["AttenuationRadius"] == 7.0


def test_a_point_light_is_a_simple_point_on_the_object_with_no_shape():
    """Unity's point light has no size. A sphere light needs a sphere shape
    beside it, which the Editor draws over the light's range."""
    entity, _, children = _light(UNITY_POINT)
    assert children == [] and "EditorSphereShapeComponent" not in entity["Components"]
    assert entity["Components"][LIGHT]["Controller"]["Configuration"]["LightType"] == O3DE_SIMPLE_POINT == 6


# =============================================================================
# LIGHT OVERRIDES ON A PLACED PREFAB
# The club level gives the lamp of `LightCeilingRetro02On` a range of 6 and an
# intensity of 1.
# =============================================================================

LIGHT_SIDECAR = {"light_owners": {
    "10800000": {"entity": "Entity_[9]", "component": LIGHT, "type": UNITY_POINT, "color": [1.0, 0.9, 0.8]},
    "10800002": {"entity": "Entity_[4]", "component": LIGHT, "type": UNITY_SPOT, "color": [1.0, 1.0, 1.0]},
}}
LAMP = "/Entities/Entity_[9]/Components/AZ::Render::EditorAreaLightComponent/Controller/Configuration"


def _light_modification(path, value, target="10800000"):
    return {"target": {"fileID": target}, "propertyPath": path, "value": value}


def _light_patches(*modifications):
    coverage = CoverageTracker()
    patches = light_override_patches(list(modifications), LIGHT_SIDECAR, coverage)
    return {patch["path"]: patch["value"] for patch in patches}, coverage.to_dict()["prefab_overrides"]


def test_a_lights_record_says_where_it_was_written():
    go = _lamp(UNITY_SPOT, mesh_guid="abcd")                      # holds more: the spot goes on a child
    _, _, children = _light(UNITY_SPOT, go)
    assert light_record(go) == {"entity": children[0], "component": LIGHT, "type": UNITY_SPOT,
                                "color": [1.0, 0.9, 0.8]}
    assert light_record(GameObject(file_id="2", name="Wall", transform=Transform())) is None


def test_an_override_of_range_and_intensity_lands_on_the_lights_entity():
    patches, seen = _light_patches(_light_modification("m_Range", "6"), _light_modification("m_Intensity", "1"))
    assert patches == {f"{LAMP}/AttenuationRadius": 6.0, f"{LAMP}/Intensity": 1.0}
    assert seen["m_Range"]["handled"] == 1 and seen["m_Intensity"]["handled"] == 1


def test_an_override_of_one_colour_channel_keeps_the_others():
    patches, _ = _light_patches(_light_modification("m_Color.g", "0.1"))
    assert patches == {f"{LAMP}/Color": [1.0, 0.1, 0.8]}


def test_a_spot_angle_is_halved_and_a_point_light_has_none():
    spot = "/Entities/Entity_[4]/Components/AZ::Render::EditorAreaLightComponent/Controller/Configuration"
    patches, seen = _light_patches(_light_modification("m_SpotAngle", "80", "10800002"),
                                   _light_modification("m_SpotAngle", "80"))
    assert patches == {f"{spot}/OuterShutterAngleDegrees": 40.0}
    assert seen["m_SpotAngle"] == {"seen": 2, "handled": 1, "examples": ["80", "80"]}


def test_what_belongs_to_baked_lighting_is_reported_and_not_written():
    patches, seen = _light_patches(_light_modification("m_BounceIntensity", "1"))
    assert patches == {} and seen["m_BounceIntensity"]["handled"] == 0
    assert overrides_a_light(_light_modification("m_BounceIntensity", "1"), LIGHT_SIDECAR)
    assert not overrides_a_light(_light_modification("m_Range", "6", target="999"), LIGHT_SIDECAR)


# =============================================================================
# COLLISION MESHES
# =============================================================================

def test_a_collision_mesh_is_not_drawn_in_the_editor():
    components = {}
    go = GameObject(file_id="1", name="Wall", transform=Transform())
    _write_mesh_collider(components, {"type": "MeshCollider"}, go, _context())
    assert components["EditorMeshColliderComponent"]["DebugDrawSettings"] == {"LocallyEnabled": False}


# =============================================================================
# MATERIAL OVERRIDES ON A PLACED PREFAB
# The Office example level lays `Floor_CarpetBlue` over a common floor tile.
# =============================================================================

SIDECAR = {
    "entity_aliases":       {"100": "Entity_[7]"},
    "renderer_owners":      {"2300000": "100"},
    "material_slots":       {"100": ["aaaa", "bbbb"]},
    "material_slot_labels": {"100": ["Floor", "Trim/Edge"]},
}
BASE = "/Entities/Entity_[7]/Components/EditorMaterialComponent/Controller/Configuration"


def _patches(overrides, sidecar=SIDECAR, hints=None):
    coverage = CoverageTracker()
    hints = {"carpet": "assets/pack/materials/floor_carpetblue.azmaterial"} if hints is None else hints
    return material_override_patches(overrides, sidecar, hints.get, "Floor_3x3", coverage), coverage


def test_an_override_names_the_renderer_and_lands_on_its_entity():
    patches, coverage = _patches({"2300000": {0: "carpet"}})
    entry = {"MaterialAsset": {"assetHint": "assets/pack/materials/floor_carpetblue.azmaterial"}}
    assert patches == [
        {"op": "add", "path": BASE + "/materialsByLabel/Floor", "value": entry},
        {"op": "add", "path": BASE + "/materials/{}", "value": entry},        # slot 0 is also the default slot
    ], patches
    assert coverage.warnings == []


def test_a_later_slot_is_set_by_its_label_escaped_for_the_path():
    patches, _ = _patches({"2300000": {1: "carpet"}})
    assert [patch["path"] for patch in patches] == [BASE + "/materialsByLabel/Trim~1Edge"]


def test_an_override_on_an_unknown_renderer_or_with_an_unknown_material_is_reported():
    patches, coverage = _patches({"999": {0: "carpet"}})
    assert patches == [] and any("fileID=999" in line for line in coverage.warnings)
    patches, coverage = _patches({"2300000": {0: "missing"}})
    assert patches == [] and "missing" in coverage.missing_materials


def test_an_older_entity_map_that_knows_objects_only_still_works():
    older = {key: value for key, value in SIDECAR.items() if key != "renderer_owners"}
    patches, _ = _patches({"100": {0: "carpet"}}, sidecar=older)
    assert len(patches) == 2


# =============================================================================
# A MESH OVERRIDE ON A PLACED PREFAB
# A prefab variant of the NatureManufacture pack shows a lower level of detail
# of its base prefab's model.
# =============================================================================

MESH_SIDECAR = {"entity_aliases": {"100": "Entity_[7]"}, "mesh_owners": {"3300000": "100"}}


def _mesh_patches(target="3300000", guid="70476273fc8e7f646ba881cc54df9661", hint="assets/pack/models/grass-grass_LOD1.fbx.azmodel"):
    coverage = CoverageTracker()
    asked = []

    def model_hint_for(mesh_guid, mesh_file_id, owner):
        asked.append((mesh_guid, mesh_file_id, owner))
        return hint

    modification = {"target": {"fileID": target}, "propertyPath": "m_Mesh", "value": "",
                    "objectReference": {"fileID": 4300002, "guid": guid, "type": 3}}
    patches = mesh_override_patches([modification], MESH_SIDECAR, model_hint_for, "prefab_grass_03_3", coverage)
    return patches, asked, coverage.to_dict()["prefab_overrides"]["m_Mesh"]


def test_a_mesh_override_names_the_filter_and_sets_its_entitys_model():
    patches, asked, seen = _mesh_patches()
    assert patches == [{
        "op": "add",
        "path": "/Entities/Entity_[7]/Components/AZ::Render::EditorMeshComponent/Controller/Configuration/ModelAsset",
        "value": {"assetHint": "assets/pack/models/grass-grass_LOD1.fbx.azmodel"}}]
    assert asked == [("70476273fc8e7f646ba881cc54df9661", "4300002", "prefab_grass_03_3")]
    assert seen["handled"] == 1


def test_a_mesh_override_that_cannot_be_placed_is_reported():
    """On a filter the entity map does not know (its object shows no model),
    or of a mesh no model can be made of."""
    for patches, _, seen in (_mesh_patches(target="999"), _mesh_patches(hint=None)):
        assert patches == [] and seen == {"seen": 1, "handled": 0, "examples": ["70476273fc8e7f646ba881cc54df9661"]}


# =============================================================================
# OPACITY
# =============================================================================

def _material(tmp: Path, floats: dict, base_alpha: float = 1.0, keywords=(), emission=(0, 0, 0),
              tiling=(1, 1), offset=(0, 0)) -> dict:
    """Parse a Unity material made of these float properties."""
    lines = ["%YAML 1.1", "%TAG !u! tag:unity3d.com,2011:", "--- !u!21 &2100000", "Material:",
             "  m_Name: Test", "  m_ValidKeywords:" + (" []" if not keywords else "")]
    lines += [f"  - {keyword}" for keyword in keywords]
    lines += ["  m_SavedProperties:", "    m_TexEnvs:", "    - _BaseMap:",
              "        m_Texture: {fileID: 2800000, guid: 6c1d2ce08507c2246994d3aa600a4ec7, type: 3}",
              f"        m_Scale: {{x: {tiling[0]}, y: {tiling[1]}}}",
              f"        m_Offset: {{x: {offset[0]}, y: {offset[1]}}}",
              "    m_Floats:" + (" []" if not floats else "")]
    lines += [f"    - {name}: {value}" for name, value in floats.items()]
    lines += ["    m_Colors:", f"    - _BaseColor: {{r: 0.13, g: 0.13, b: 0.13, a: {base_alpha}}}",
              f"    - _EmissionColor: {{r: {emission[0]}, g: {emission[1]}, b: {emission[2]}, a: 1}}"]
    path = tmp / "Test.mat"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return AssetDatabase(tmp).parse_material(path)["properties"]


def test_a_transparent_surface_with_a_clip_at_zero_blends():
    """The Office pack's Glass: transparent, alpha clipping ticked, threshold 0."""
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 1, "_AlphaClip": 1, "_Cutoff": 0})
        assert properties["opacity.mode"] == "Blended" and properties["opacity.alphaSource"] == "Packed"
        assert properties["opacity.factor"] == 1.0                    # the base colour's alpha
        assert properties["opacity.alphaAffectsSpecular"] == 0.0      # highlights stay at full strength


def test_a_blended_surfaces_factor_is_the_base_colours_alpha():
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 1, "_AlphaClip": 0}, base_alpha=0.25)
        assert properties["opacity.factor"] == 0.25


def test_preserve_specular_switched_off_lets_alpha_fade_the_highlights():
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 1, "_BlendModePreserveSpecular": 0})
        assert properties["opacity.alphaAffectsSpecular"] == 1.0


def test_a_cutouts_factor_is_one_minus_unitys_threshold():
    """The engine discards where alpha < 1 - factor; Unity where alpha < threshold."""
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 0, "_AlphaClip": 1, "_Cutoff": 0.3})
        assert properties["opacity.mode"] == "Cutout" and abs(properties["opacity.factor"] - 0.7) < 1e-9


def test_a_clipped_surface_on_a_transparent_shader_still_cuts():
    """The Office pack's MetalShelf: both signals set, a real threshold."""
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 1, "_AlphaClip": 1, "_Cutoff": 0.5})
        assert properties["opacity.mode"] == "Cutout"


def test_an_opaque_surface_has_no_opacity_settings():
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {"_Surface": 0, "_AlphaClip": 0})
        assert not any(key.startswith("opacity.") for key in properties)


# =============================================================================
# EMISSION AND TILING
# =============================================================================

def test_a_glowing_material_is_enabled_with_a_colour_within_one_and_its_brightness():
    """A neon colour of (4, 2, 0): colour (1, 0.5, 0), two doublings above one nit."""
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {}, keywords=("_EMISSION",), emission=(4.0, 2.0, 0.0))
        assert properties["emissive.enable"] is True
        assert properties["emissive.color"] == [1.0, 0.5, 0.0, 1.0]
        assert properties["emissive.intensity"] == 5.0


def test_a_dim_glow_keeps_its_colour_at_one_nit():
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {}, keywords=("_EMISSION",), emission=(0.5, 0.25, 0.0))
        assert properties["emissive.color"] == [0.5, 0.25, 0.0, 1.0] and properties["emissive.intensity"] == 3.0


def test_without_the_keyword_or_with_a_black_colour_nothing_glows():
    with tempfile.TemporaryDirectory() as folder:
        stored_only = _material(Path(folder), {}, emission=(4.0, 2.0, 0.0))
        black = _material(Path(folder), {}, keywords=("_EMISSION",))
        for properties in (stored_only, black):
            assert not any(key.startswith("emissive.") for key in properties), properties


def test_the_base_maps_tiling_and_offset_become_the_materials():
    """Scaled about the origin, as Unity does, not about the image's middle."""
    with tempfile.TemporaryDirectory() as folder:
        properties = _material(Path(folder), {}, tiling=(4, 2), offset=(0.5, 0))
        assert properties["uv.center"] == [0.0, 0.0]
        assert (properties["uv.tileU"], properties["uv.tileV"], properties["uv.offsetU"]) == (4.0, 2.0, 0.5)
        plain = _material(Path(folder), {})
        assert not any(key.startswith("uv.") for key in plain)


def test_an_atlas_cell_is_the_same_cell_with_v_running_down():
    """`DoorFrameLight04` shows the top left cell of a 4 by 4 atlas: Unity's
    tiling 0.25 with offset (0, 0.75). O3DE's V runs down the image, so the
    top row starts at 0 there."""
    assert uv_transform({'x': 0.25, 'y': 0.25}, {'x': 0, 'y': 0.75}) == {
        'uv.center': [0.0, 0.0], 'uv.tileU': 0.25, 'uv.tileV': 0.25, 'uv.offsetU': 0.0, 'uv.offsetV': 0.0}
    # The cell below it, and one in the bottom row.
    assert uv_transform({'x': 0.25, 'y': 0.25}, {'x': 0.5, 'y': 0.5})['uv.offsetV'] == 0.25
    assert uv_transform({'x': 0.25, 'y': 0.25}, {'x': 0, 'y': 0})['uv.offsetV'] == 0.75


def test_the_written_material_holds_the_centre_as_a_pair_and_the_colour_as_four():
    """The centre is two numbers. Written like a colour it would be read as
    (1, 1), and the tiling would scale about the wrong corner."""
    with tempfile.TemporaryDirectory() as folder:
        unity = Path(folder) / "unity"
        unity.mkdir()
        _material(unity, {}, tiling=(0.25, 0.25), offset=(0, 0.75))
        (unity / "Test.mat.meta").write_text("fileFormatVersion: 2\nguid: 7a1d2ce08507c2246994d3aa600a4e01\n",
                                             encoding="utf-8")
        random.seed(7)
        worker = IntegratedAssetProcessor(unity, Path(folder) / "out", log_callback=lambda line: None)
        assert worker._process_material("7a1d2ce08507c2246994d3aa600a4e01")
        written = json.loads((Path(folder) / "out" / "Materials" / "Test.material").read_text(encoding="utf-8"))
        values = written["propertyValues"]
        assert values["uv.center"] == [0.0, 0.0] and values["uv.tileV"] == 0.25 and values["uv.offsetV"] == 0.0
        assert values["baseColor.color"] == [0.13, 0.13, 0.13, 1.0]


def test_a_whole_image_of_offset_is_dropped():
    """A tiling of 2 would need a V offset of -1: the same texels as 0."""
    assert uv_transform({'x': 2, 'y': 2}, {})['uv.offsetV'] == 0.0
    assert uv_transform({'x': 1, 'y': 1}, {'x': 1.25, 'y': 0})['uv.offsetU'] == 0.25


# =============================================================================
# TEXTURE SETTINGS
# =============================================================================

def test_a_texture_whose_alpha_is_opacity_gets_the_opacity_preset_at_full_size():
    with tempfile.TemporaryDirectory() as folder:
        texture = Path(folder) / "Plant_Inside_BaseColor.tga"
        texture.write_bytes(b"")
        sidecar = write_opacity_texture_settings(texture, cutout=True)
        text = sidecar.read_text(encoding="utf-8")
        assert sidecar.name == "Plant_Inside_BaseColor.tga.assetinfo"
        assert f'field="Preset" value="{OPACITY_PRESET}"' in text and OPACITY_PRESET == "Decal_AlbedoWithOpacity"
        assert 'field="EngineReduce" value="true"' in text            # no reduction of its size
        assert 'field="MaintainAlphaCoverage" value="true"' in text


def test_a_blended_textures_mips_do_not_keep_a_cut():
    with tempfile.TemporaryDirectory() as folder:
        texture = Path(folder) / "Glass_BaseColor.tga"
        texture.write_bytes(b"")
        text = write_opacity_texture_settings(texture, cutout=False).read_text(encoding="utf-8")
        assert 'field="MaintainAlphaCoverage" value="false"' in text


# =============================================================================
# THE CHANNELS OF ROUGHNESS AND OCCLUSION
# Unity's mask map: metallic in red, occlusion in green, smoothness in alpha.
# O3DE reads each value from the red channel of the texture bound to it.
# =============================================================================

def _worker_with_mask(tmp: Path):
    from PIL import Image
    unity = tmp / "unity"
    unity.mkdir()
    Image.new("RGBA", (2, 2), (10, 200, 0, 240)).save(unity / "Mask.png")
    (unity / "Mask.png.meta").write_text("fileFormatVersion: 2\nguid: 6042ee429c4c0174aa45d7965f27d117\n", encoding="utf-8")
    random.seed(7)
    return IntegratedAssetProcessor(unity, tmp / "out", log_callback=lambda line: None)


def test_roughness_is_one_minus_the_alpha_as_a_grey_image():
    if not PIL_AVAILABLE:
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as folder:
        worker = _worker_with_mask(Path(folder))
        relative = worker._process_metallic_gloss_as_roughness("6042ee429c4c0174aa45d7965f27d117")
        assert relative == "Textures/Mask_Roughness.png"
        with Image.open(Path(folder) / "out" / relative) as image:
            assert image.mode == "L" and image.getpixel((0, 0)) == 15       # 255 - 240


def test_occlusion_is_the_green_channel_as_a_grey_image():
    if not PIL_AVAILABLE:
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as folder:
        worker = _worker_with_mask(Path(folder))
        relative = worker._process_channel_texture("6042ee429c4c0174aa45d7965f27d117", "G", "_Occlusion", invert=False)
        with Image.open(Path(folder) / "out" / relative) as image:
            assert image.mode == "L" and image.getpixel((0, 0)) == 200


def test_a_roughness_image_of_the_old_kind_is_written_again():
    """It kept the value in its alpha channel, which O3DE does not read."""
    if not PIL_AVAILABLE:
        return
    from PIL import Image
    with tempfile.TemporaryDirectory() as folder:
        worker = _worker_with_mask(Path(folder))
        old = Path(folder) / "out" / "Textures" / "Mask_Roughness.png"
        Image.new("RGBA", (2, 2), (10, 200, 0, 15)).save(old)
        worker._process_metallic_gloss_as_roughness("6042ee429c4c0174aa45d7965f27d117")
        with Image.open(old) as image:
            assert image.mode == "L"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
