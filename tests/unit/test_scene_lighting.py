"""Unit tests for a level's ambient light (parity_fixes I.7): the Unity
scene's three ambient colours, carried by one Gradient GI entity.
"""

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter
from platforms.unity.scene_lighting import ambient_gradient
from targets.o3de.prefab_writer import gradient_gi_component

UNITY_DEFAULTS = {
    "m_AmbientSkyColor":     {"r": 0.212, "g": 0.227, "b": 0.259, "a": 1},
    "m_AmbientEquatorColor": {"r": 0.114, "g": 0.125, "b": 0.133, "a": 1},
    "m_AmbientGroundColor":  {"r": 0.047, "g": 0.043, "b": 0.035, "a": 1},
}


# =============================================================================
# READING THE SCENE'S AMBIENT LIGHT
# =============================================================================

def test_gradient_mode_gives_the_three_colours_exactly():
    ambient = ambient_gradient(dict(UNITY_DEFAULTS, m_AmbientMode=1))
    assert ambient == {"sky": (0.212, 0.227, 0.259), "equator": (0.114, 0.125, 0.133),
                       "ground": (0.047, 0.043, 0.035), "mode": "Gradient", "exact": True}


def test_colour_mode_is_one_colour_all_round():
    ambient = ambient_gradient(dict(UNITY_DEFAULTS, m_AmbientMode=3))
    assert ambient["sky"] == ambient["equator"] == ambient["ground"] == (0.212, 0.227, 0.259)
    assert ambient["exact"] is True


def test_skybox_mode_gives_the_stored_colours_and_says_they_are_not_the_source():
    ambient = ambient_gradient(dict(UNITY_DEFAULTS, m_AmbientMode=0))
    assert ambient["ground"] == (0.047, 0.043, 0.035)
    assert (ambient["mode"], ambient["exact"]) == ("Skybox", False)


def test_a_scene_without_ambient_colours_has_no_gradient():
    assert ambient_gradient(None) is None
    assert ambient_gradient({"m_Fog": 0}) is None


def test_unitys_default_colours_read_as_linear_values_of_srgb_picks():
    """Why the colours are not converted: Unity's defaults sit, within the
    three places Unity writes, on the linear values of whole-number sRGB
    picks. Read as sRGB they would be no round colours at all."""
    def to_linear(byte):
        value = byte / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    picks = {"m_AmbientSkyColor": (127, 131, 139), "m_AmbientEquatorColor": (95, 99, 102),
             "m_AmbientGroundColor": (61, 59, 53)}
    for key, bytes_ in picks.items():
        stored = UNITY_DEFAULTS[key]
        for channel, byte in zip("rgb", bytes_):
            assert abs(to_linear(byte) - stored[channel]) < 0.001, (key, channel)


# =============================================================================
# THE COMPONENT
# =============================================================================

def test_the_component_holds_the_colours_top_to_bottom_under_the_engines_names():
    component = gradient_gi_component(9, (0.2, 0.3, 0.4), (0.1, 0.1, 0.1), (0.0, 0.01, 0.02))
    assert component["$type"].endswith("AZ::Render::EditorGradientGIComponent")
    assert component["Id"] == 9
    assert component["Controller"]["Configuration"] == {
        "HighColor": [0.2, 0.3, 0.4, 1.0], "MidColor": [0.1, 0.1, 0.1, 1.0], "LowColor": [0.0, 0.01, 0.02, 1.0]}


# =============================================================================
# IN A CONVERTED LEVEL
# =============================================================================

def _scene(ambient_mode) -> str:
    render_settings = "" if ambient_mode is None else f"""--- !u!104 &2
RenderSettings:
  m_Fog: 0
  m_AmbientSkyColor: {{r: 0.5, g: 0.6, b: 0.7, a: 1}}
  m_AmbientEquatorColor: {{r: 0.3, g: 0.3, b: 0.3, a: 1}}
  m_AmbientGroundColor: {{r: 0.1, g: 0.05, b: 0.02, a: 1}}
  m_AmbientIntensity: 1
  m_AmbientMode: {ambient_mode}
"""
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
{render_settings}--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  m_Name: Marker
--- !u!4 &400
Transform:
  m_GameObject: {{fileID: 100}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 1, y: 2, z: 3}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children: []
  m_Father: {{fileID: 0}}
"""


def _convert(ambient_mode):
    with tempfile.TemporaryDirectory() as folder:
        scene = Path(folder) / "Gallery.unity"
        scene.write_text(_scene(ambient_mode), encoding="utf-8")
        level = Path(folder) / "Gallery.prefab"
        converter = UnitySceneConverter(PrefabDatabase(), log_callback=lambda line: None)
        converter.parse_unity_scene(str(scene))
        converter.create_o3de_level(str(level), Path(folder))
        return converter, json.loads(level.read_text(encoding="utf-8"))


def _lights(level: dict) -> list:
    return [entity for entity in level["Entities"].values() if "EditorGradientGIComponent" in entity["Components"]]


def test_a_level_gets_one_gradient_gi_entity_with_the_scenes_colours():
    converter, level = _convert(1)
    lights = _lights(level)
    assert len(lights) == 1 and lights[0]["Name"] == "Gradient GI"
    configuration = lights[0]["Components"]["EditorGradientGIComponent"]["Controller"]["Configuration"]
    assert configuration["HighColor"] == [0.5, 0.6, 0.7, 1.0]
    assert configuration["MidColor"] == [0.3, 0.3, 0.3, 1.0]
    assert configuration["LowColor"] == [0.1, 0.05, 0.02, 1.0]
    # It hangs under the level and is listed among its children.
    assert lights[0]["Components"]["TransformComponent"]["Parent Entity"] == "Entity_[1000000]"
    order = level["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"]
    assert lights[0]["Id"] in order
    assert converter.coverage.warnings == []


def test_a_scene_lit_by_its_skybox_gets_the_gradient_and_a_warning():
    converter, level = _convert(0)
    assert len(_lights(level)) == 1
    assert any("takes its ambient light from its skybox" in line for line in converter.coverage.warnings)


def test_a_scene_without_render_settings_gets_no_gradient_gi():
    _, level = _convert(None)
    assert _lights(level) == []


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
