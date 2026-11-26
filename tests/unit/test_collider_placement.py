"""Unit tests for where a capsule or sphere collider is placed
(second_pack I.3, proof T.5).

An O3DE capsule stands along its entity's Z, and the engine refuses a capsule
or a sphere on an entity that has a non-uniform scale. A Unity capsule that
lies along X or Z, and one on a stretched object, therefore get an entity of
their own under the object: turned, and with the object's scale worked into
its size the way Unity does it.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor
from platforms.unity.components.box_collider import (
    needs_own_entity, own_entity_placement, refuses_non_uniform_scale,
)
from platforms.unity.types import GameObject, Transform
from targets.o3de.prefab_writer import instance_non_uniform_scale_patches


def _capsule(direction=1, center=(0.0, 0.0, 0.0), radius=0.1, height=2.0, index=0):
    return {"type": "CapsuleCollider", "direction": direction, "center": center,
            "radius": radius, "height": height, "global_index": index}


def _sphere(radius=0.5, center=(0.0, 0.0, 0.0)):
    return {"type": "SphereCollider", "center": center, "radius": radius, "global_index": 0}


# =============================================================================
# WHICH COLLIDER NEEDS AN ENTITY OF ITS OWN
# =============================================================================

def test_an_upright_capsule_on_an_unstretched_object_stays_on_it():
    assert needs_own_entity(_capsule(direction=1), stretched=False) is False
    assert needs_own_entity(_sphere(), stretched=False) is False
    assert needs_own_entity({"type": "BoxCollider"}, stretched=True) is False


def test_a_lying_capsule_and_anything_round_on_a_stretched_object_do_not():
    assert needs_own_entity(_capsule(direction=0), stretched=False) is True
    assert needs_own_entity(_capsule(direction=2), stretched=False) is True
    assert needs_own_entity(_capsule(direction=1), stretched=True) is True
    assert needs_own_entity(_sphere(), stretched=True) is True


# =============================================================================
# HOW IT IS PLACED THERE
# =============================================================================

def test_a_capsule_along_unitys_x_is_laid_along_x():
    """The rope barrier of the Tirgames pack."""
    transform, placed = own_entity_placement(_capsule(direction=0, center=(0.5, 1.0, 0.25)), (1, 1, 1), False)
    assert transform == {"Translate": [0.5, 0.25, 1.0], "Rotate": [0.0, 90.0, 0.0]}
    assert placed["center"] == (0.0, 0.0, 0.0) and (placed["radius"], placed["height"]) == (0.1, 2.0)


def test_a_capsule_along_unitys_z_is_laid_along_o3des_y():
    transform, _ = own_entity_placement(_capsule(direction=2), (1, 1, 1), False)
    assert transform["Rotate"] == [90.0, 0.0, 0.0]


def test_a_stretched_objects_scale_goes_into_the_capsule_as_unity_applies_it():
    """A pole three times as tall: height by the scale along the capsule,
    radius by the larger of the two across it, the centre by each axis."""
    transform, placed = own_entity_placement(
        _capsule(direction=1, center=(0.0, 1.0, 0.0), radius=0.1, height=2.0), (1.5, 3.0, 1.2), True)
    assert transform == {"Translate": [0.0, 0.0, 3.0]}
    assert abs(placed["height"] - 6.0) < 1e-12 and abs(placed["radius"] - 0.15) < 1e-12


def test_a_stretched_objects_sphere_takes_the_largest_scale():
    _, placed = own_entity_placement(_sphere(radius=0.5), (1.0, -2.0, 0.5), True)
    assert placed["radius"] == 1.0


def test_an_unstretched_objects_scale_is_left_to_its_transform():
    _, placed = own_entity_placement(_capsule(direction=0), (3.0, 3.0, 3.0), False)
    assert (placed["radius"], placed["height"]) == (0.1, 2.0)


# =============================================================================
# IN A CONVERTED PREFAB
# =============================================================================

def _prefab(scale, direction) -> str:
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {{fileID: 400}}
  m_Name: Stand
--- !u!4 &400
Transform:
  m_GameObject: {{fileID: 100}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: 1, y: 1, z: 1}}
  m_Children:
  - {{fileID: 401}}
  m_Father: {{fileID: 0}}
--- !u!1 &101
GameObject:
  m_Component:
  - component: {{fileID: 401}}
  - component: {{fileID: 13600}}
  m_Name: Pole
--- !u!4 &401
Transform:
  m_GameObject: {{fileID: 101}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: {scale[0]}, y: {scale[1]}, z: {scale[2]}}}
  m_Children: []
  m_Father: {{fileID: 400}}
--- !u!136 &13600
CapsuleCollider:
  m_GameObject: {{fileID: 101}}
  m_IsTrigger: 0
  m_Radius: 0.1
  m_Height: 2
  m_Direction: {direction}
  m_Center: {{x: 0, y: 1, z: 0}}
"""


def _convert(tmp: Path, scale, direction) -> dict:
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Stand.prefab"
    prefab.write_text(_prefab(scale, direction), encoding="utf-8")
    (unity_root / "Stand.prefab.meta").write_text("fileFormatVersion: 2\nguid: aaaabbbbccccdddd0000111122226666\n",
                                                  encoding="utf-8")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None)
    assert processor.process_prefab(prefab)
    emitted = json.loads((tmp / "out" / "Prefabs" / "Stand.prefab").read_text(encoding="utf-8"))
    return {entity["Name"]: entity for entity in emitted["Entities"].values()}


def test_an_upright_capsule_is_written_on_the_object_itself():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (1, 1, 1), 1)
        assert "EditorCapsuleShapeComponent" in entities["Pole"]["Components"]
        assert not any(name.startswith("Pole_Collider") for name in entities)


def test_a_stretched_object_keeps_its_scale_and_its_capsule_moves_out():
    """Together on one entity the engine refuses them and the prefab does
    not cook (the club level of the Tirgames pack did not)."""
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (1, 3, 1), 1)
        pole, collider = entities["Pole"]["Components"], entities["Pole_Collider_0"]["Components"]
        assert "EditorNonUniformScaleComponent" in pole and "EditorCapsuleShapeComponent" not in pole
        assert collider["TransformComponent"]["Parent Entity"] == entities["Pole"]["Id"]
        assert collider["TransformComponent"]["Transform Data"] == {"Translate": [0.0, 0.0, 3.0]}
        capsule = collider["EditorCapsuleShapeComponent"]["CapsuleShape"]["Configuration"]
        assert (capsule["Height"], capsule["Radius"]) == (6.0, 0.1) and "TranslationOffset" not in capsule


def test_a_lying_capsule_gets_a_turned_entity_of_its_own():
    with tempfile.TemporaryDirectory() as tmp:
        entities = _convert(Path(tmp), (1, 1, 1), 0)
        assert "EditorCapsuleShapeComponent" not in entities["Pole"]["Components"]
        data = entities["Pole_Collider_0"]["Components"]["TransformComponent"]["Transform Data"]
        assert data == {"Translate": [0.0, 0.0, 1.0], "Rotate": [0.0, 90.0, 0.0]}


# =============================================================================
# A NESTED INSTANCE WHOSE ROOT CARRIES A CAPSULE
# =============================================================================

def test_a_root_with_its_own_capsule_refuses_a_scale_handed_to_it_later():
    upright = GameObject(file_id="1", name="Pole", transform=Transform(), colliders=[_capsule(direction=1)])
    lying = GameObject(file_id="2", name="Rope", transform=Transform(), colliders=[_capsule(direction=0)])
    boxed = GameObject(file_id="3", name="Crate", transform=Transform(), colliders=[{"type": "BoxCollider", "global_index": 0}])
    assert refuses_non_uniform_scale(upright) is True
    assert refuses_non_uniform_scale(lying) is False          # its capsule is on an entity of its own
    assert refuses_non_uniform_scale(boxed) is False


def test_a_stretched_instance_of_such_a_prefab_is_reported_not_patched():
    warnings = []
    sidecar = {"root_entity": "Entity_[1]", "entity_aliases": {"100": "Entity_[1]"},
               "root_refuses_non_uniform_scale": True}
    assert instance_non_uniform_scale_patches((1, 1, 3), sidecar, 5, "StripPole01_300cm", warnings.append) == []
    assert any("capsule or sphere collider" in line for line in warnings), warnings


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
