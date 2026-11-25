"""Unit tests for I.2 — Stage-1 collision-object inventory.

  T-7: collider-bearing entities are recorded keyed "<prefab_guid>:<file_id>"
       with a readable collider summary, and surface through to_outputs().
"""

import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import IntegratedAssetProcessor


def _bare_processor() -> IntegratedAssetProcessor:
    """An IntegratedAssetProcessor with only the fields these tests touch —
    skips the heavy __init__ (asset DB, output dirs, etc.)."""
    proc = IntegratedAssetProcessor.__new__(IntegratedAssetProcessor)
    proc._collision_objects = {}
    return proc


def test_collision_objects_recorded_and_keyed():
    proc = _bare_processor()
    go_box  = SimpleNamespace(file_id="111", name="Crate",
                              colliders=[{"type": "BoxCollider", "is_trigger": False}])
    go_mix  = SimpleNamespace(file_id="222", name="Rock",
                              colliders=[{"type": "MeshCollider", "convex": True, "is_trigger": False},
                                         {"type": "BoxCollider", "is_trigger": True}])
    go_none = SimpleNamespace(file_id="333", name="JustAPivot", colliders=[])

    proc._record_collision_objects(
        "GUIDX", Path("MyPrefab.prefab"),
        {"a": go_box, "b": go_mix, "c": go_none},
    )
    co = proc._collision_objects

    # Entities with no colliders are not recorded.
    assert set(co.keys()) == {"GUIDX:111", "GUIDX:222"}

    assert co["GUIDX:111"]["prefab_name"] == "MyPrefab"
    assert co["GUIDX:111"]["entity_name"] == "Crate"
    assert co["GUIDX:111"]["entity_file_id"] == "111"
    assert co["GUIDX:111"]["collider_summary"] == "Box"

    # Mixed: convex mesh + trigger box, order preserved.
    assert co["GUIDX:222"]["collider_types"] == ["MeshCollider", "BoxCollider"]
    assert co["GUIDX:222"]["collider_summary"] == "Mesh (convex), Box (trigger)"


def test_collider_summary_collapses_duplicates():
    proc = _bare_processor()
    go = SimpleNamespace(file_id="1", name="Wall",
                         colliders=[{"type": "BoxCollider", "is_trigger": False},
                                    {"type": "BoxCollider", "is_trigger": False}])
    proc._record_collision_objects("G", Path("P.prefab"), {"x": go})
    assert proc._collision_objects["G:1"]["collider_summary"] == "Box ×2"


def test_to_outputs_includes_collision_objects():
    proc = _bare_processor()
    proc._project_prefab_records = {}
    proc._material_metadata = {}
    proc.asset_index = {"materials": {}, "meshes": {}}
    proc.coverage = SimpleNamespace(to_dict=lambda: {})
    proc._collision_objects = {"G:1": {"entity_name": "Wall"}}

    out = proc.to_outputs()
    assert out["collision_objects"] == {"G:1": {"entity_name": "Wall"}}


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
