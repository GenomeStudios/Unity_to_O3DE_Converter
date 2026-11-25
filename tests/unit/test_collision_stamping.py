"""Unit tests for I.3 — stamping CollisionLayer / CollisionGroupId onto
emitted colliders.

  T-2: default layer + group → ColliderConfiguration carries
       CollisionLayer={Index:N} + CollisionGroupId={GroupId:uuid}.
  T-3: nothing configured → NO CollisionLayer/CollisionGroupId (byte-compat
       with pre-F-Collision output).
  T-4: per-entity override beats the default for that entity only.
  T-5: partial override (layer only) → layer overridden, group inherits.
"""

import itertools
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.components.base import ProcessingContext
from platforms.unity.components.box_collider import (
    _write_box_shape, _apply_collision_config,
)
from platforms.unity.components.sphere_collider import _write_sphere_shape
from integrated_asset_processor import IntegratedAssetProcessor


# --- Helpers ---

def _ctx(collision_config) -> ProcessingContext:
    counter = itertools.count(1)
    return ProcessingContext(
        material_mapping={}, mesh_mapping={}, fbx_material_labels={},
        collider_pxmesh_mapping={}, entities_dict={}, entity_id_map={},
        generate_component_id=lambda: f"cid{next(counter)}",
        generate_entity_id=lambda: f"eid{next(counter)}",
        make_bare_entity=lambda *a: {},
        log=lambda *_: None, stats={},
        collision_config=collision_config,
    )


def _box(go, ctx) -> dict:
    components: dict = {}
    collider = {"type": "BoxCollider", "center": (0, 0, 0),
                "size": (1, 1, 1), "is_trigger": False}
    _write_box_shape(components, collider, go, ctx)
    return components['EditorShapeColliderComponent']['ColliderConfiguration']


def _proc(settings) -> IntegratedAssetProcessor:
    proc = IntegratedAssetProcessor.__new__(IntegratedAssetProcessor)
    proc._collision_settings = settings
    return proc


# --- T-2: writer stamps both fields ---

def test_box_collider_stamps_layer_and_group():
    ctx = _ctx({"42": {"layer": 1, "group": "{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}"}})
    cc = _box(SimpleNamespace(file_id="42", name="Crate"), ctx)
    assert cc['CollisionLayer'] == {'Index': 1}
    assert cc['CollisionGroupId'] == {'GroupId': "{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}"}


def test_sphere_collider_path_also_stamps():
    ctx = _ctx({"7": {"layer": 3, "group": None}})
    components: dict = {}
    collider = {"type": "SphereCollider", "center": (0, 0, 0),
                "radius": 0.5, "is_trigger": False}
    _write_sphere_shape(components, collider, SimpleNamespace(file_id="7", name="Ball"), ctx)
    cc = components['EditorShapeColliderComponent']['ColliderConfiguration']
    assert cc['CollisionLayer'] == {'Index': 3}
    assert 'CollisionGroupId' not in cc        # group None → unset


# --- T-3: unconfigured → no stamping ---

def test_no_config_leaves_collider_default():
    cc = _box(SimpleNamespace(file_id="42", name="Crate"), _ctx({}))
    assert 'CollisionLayer' not in cc
    assert 'CollisionGroupId' not in cc


def test_layer_zero_is_stamped_not_skipped():
    # Index 0 ("Default") is a real, intentional layer — must not be treated
    # as "unset" the way None is.
    cc = _box(SimpleNamespace(file_id="9", name="Floor"), _ctx({"9": {"layer": 0, "group": None}}))
    assert cc['CollisionLayer'] == {'Index': 0}


def test_apply_helper_ignores_empty_group_string():
    cfg = {'MaterialSlots': {'Slots': [{'Name': 'Entire object'}]}}
    ctx = _ctx({"1": {"layer": None, "group": ""}})
    _apply_collision_config(cfg, SimpleNamespace(file_id="1", name="X"), ctx)
    assert 'CollisionLayer' not in cfg and 'CollisionGroupId' not in cfg


# --- T-4 / T-5: effective-value resolver ---

def test_override_beats_default_per_entity():
    settings = {
        "defaults":  {"collision_layer": 0, "collision_group_id": "{DEF}"},
        "overrides": {"G:222": {"collision_layer": 5, "collision_group_id": "{OV}"}},
    }
    go1 = SimpleNamespace(file_id="111", name="A", colliders=[{"type": "BoxCollider"}])
    go2 = SimpleNamespace(file_id="222", name="B", colliders=[{"type": "BoxCollider"}])
    m = _proc(settings)._build_collision_config_mapping("G", {"a": go1, "b": go2})
    assert m["111"] == {"layer": 0, "group": "{DEF}"}    # inherits default
    assert m["222"] == {"layer": 5, "group": "{OV}"}     # override wins


def test_partial_override_inherits_default_group():
    settings = {
        "defaults":  {"collision_layer": 0, "collision_group_id": "{DEF}"},
        "overrides": {"G:111": {"collision_layer": 9}},   # group omitted
    }
    go1 = SimpleNamespace(file_id="111", name="A", colliders=[{"type": "BoxCollider"}])
    m = _proc(settings)._build_collision_config_mapping("G", {"a": go1})
    assert m["111"] == {"layer": 9, "group": "{DEF}"}


def test_no_settings_or_all_none_yields_empty_mapping():
    go1 = SimpleNamespace(file_id="111", name="A", colliders=[{"type": "BoxCollider"}])
    go_none = SimpleNamespace(file_id="999", name="Pivot", colliders=[])
    # Empty settings.
    assert _proc({})._build_collision_config_mapping("G", {"a": go1}) == {}
    # Defaults explicitly None → still empty (don't stamp), and collider-less
    # entities are never present.
    settings = {"defaults": {"collision_layer": None, "collision_group_id": None}}
    m = _proc(settings)._build_collision_config_mapping("G", {"a": go1, "b": go_none})
    assert m == {}


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
