"""Unit tests for a mesh whose geometric scaling differs by axis
(second_pack I.3, proof T.5).

The podiums of the Tirgames pack are modelled half their width and scaled
(2, 2, 1) on the node's geometry. The mesh import rule holds one scale for
all axes, so the entity carries the stretch as a non-uniform scale; the
rule's translation and any box collider on the entity are written against
it, since the entity's scale stretches them too.
"""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.components.box_collider import _write_box_shape
from platforms.unity.types import GameObject, Transform
from targets.o3de.assetinfo_writer import source_import_scale, source_mesh_stretch, write_fbx_assetinfo
from targets.o3de.prefab_writer import instance_non_uniform_scale_patches, with_mesh_stretch


def _facts(rotation, scaling, translation=(0.0, 0.0, 0.0)):
    return {"up_axis": 1, "unit_to_metres": 0.01, "order": ["Podium"], "nodes": {"Podium": {
        "mesh": True, "path": "RootNode.Podium", "geometric_rotation": list(rotation),
        "geometric_scaling": list(scaling), "geometric_translation": list(translation)}}}


# =============================================================================
# THE STRETCH, FROM THE FILE
# =============================================================================

def test_a_scaling_by_axis_becomes_a_stretch_in_the_models_axes():
    """With the usual quarter turn about X the factors keep their axes."""
    assert source_mesh_stretch(_facts((-90, 0, 0), (2, 2, 1)), "Podium") == [2.0, 2.0, 1.0]
    assert source_import_scale(_facts((-90, 0, 0), (2, 2, 1)), "Podium") is None


def test_without_a_turn_the_file_y_and_z_factors_swap_with_the_axes():
    """Unity's Y is O3DE's Z: a scaling of Y stretches the model's Z."""
    assert source_mesh_stretch(_facts((0, 0, 0), (1, 3, 1)), "Podium") == [1.0, 1.0, 3.0]


def test_no_stretch_for_one_scale_a_turn_that_mixes_axes_or_an_unknown_node():
    assert source_mesh_stretch(_facts((-90, 0, 0), (2, 2, 2)), "Podium") is None
    assert source_mesh_stretch(_facts((30, 0, 0), (2, 2, 1)), "Podium") is None
    assert source_mesh_stretch(_facts((-90, 0, 0), (2, 2, 1)), "Missing") is None


# =============================================================================
# ON THE ENTITY
# =============================================================================

def _podium(scale=(1.0, 1.0, 1.0), stretch=(2.0, 2.0, 1.0)):
    go = GameObject(file_id="1", name="Podium", transform=Transform(scale=scale))
    if stretch:
        go.component_data["mesh_stretch"] = list(stretch)
    return go


def test_the_stretch_multiplies_the_objects_own_scale_and_makes_it_non_uniform():
    converted = Transform((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.5, 1.05, 1.0))
    transform, non_uniform = with_mesh_stretch(_podium(), converted, True)
    assert transform.scale == (3.0, 2.1, 1.0) and non_uniform is True
    plain, non_uniform = with_mesh_stretch(_podium(), Transform(), False)
    assert plain.scale == (2.0, 2.0, 1.0) and non_uniform is True


def test_an_object_without_a_stretch_is_left_as_it_is():
    converted = Transform(scale=(2.0, 2.0, 2.0))
    assert with_mesh_stretch(_podium(stretch=None), converted, False) == (converted, False)


def test_a_box_on_the_stretched_entity_is_written_smaller_by_the_stretch():
    """The engine stretches the box with the entity; Unity's box is not stretched."""
    context = SimpleNamespace(generate_component_id=lambda: 1, collision_config={}, log=lambda line: None)
    collider = {"type": "BoxCollider", "center": (1.0, 0.5, 2.0), "size": (4.0, 1.0, 2.0)}

    components = {}
    _write_box_shape(components, collider, _podium(), context, on_object=True)
    box = components["EditorBoxShapeComponent"]["BoxShape"]["Configuration"]
    assert box["Dimensions"] == [2.0, 1.0, 1.0]            # (4, 2, 1) in O3DE axes, over (2, 2, 1)
    assert box["TranslationOffset"] == [0.5, 1.0, 0.5]     # (1, 2, 0.5) over (2, 2, 1)

    # On an entity of its own the box is not under the stretch.
    components = {}
    _write_box_shape(components, collider, _podium(), context, on_object=False)
    assert components["EditorBoxShapeComponent"]["BoxShape"]["Configuration"]["Dimensions"] == [4.0, 2.0, 1.0]


def test_a_scale_handed_to_a_stretched_root_keeps_the_stretch():
    """A podium placed at (1.5, 1, 1.05) in the club level."""
    sidecar = {"root_entity": "Entity_[1]", "entity_aliases": {"1": "Entity_[1]"}, "root_mesh_stretch": [2.0, 2.0, 1.0]}
    patches = instance_non_uniform_scale_patches((1.5, 1.05, 1.0), sidecar, 9, "Podium02_4", lambda line: None)
    assert patches[0]["value"]["NonUniformScale"] == [3.0, 2.1, 1.0]


# =============================================================================
# IN THE MODEL'S IMPORT RULE
# =============================================================================

def test_the_rules_translation_is_divided_by_the_stretch():
    """The entity's scale stretches the model's offset as well, so the rule
    carries it smaller."""
    from unittest import mock
    with tempfile.TemporaryDirectory() as tmp:
        fbx = Path(tmp) / "Podium.fbx"
        fbx.write_bytes(b"not an fbx")
        facts = _facts((-90, 0, 0), (2, 2, 1), translation=(100.0, 0.0, 0.0))
        with mock.patch("fbx_reader.read_import_facts", return_value=facts):
            write_fbx_assetinfo(fbx, "Podium", {"Podium": "RootNode.Podium"}, log=lambda line: None)
        group = json.loads((Path(tmp) / "Podium.fbx.assetinfo").read_text(encoding="utf-8"))["values"][0]
        rule = next(r for r in group["rules"]["rules"] if r["$type"] == "CoordinateSystemRule")
        assert "scale" not in rule                                  # the rule holds no scale by axis
        assert rule["translation"] == [-0.5, 0.0, 0.0]              # (-1, 0, 0) m over a stretch of 2 in X


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
