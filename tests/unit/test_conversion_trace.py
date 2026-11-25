"""Unit tests for the conversion trace (parity_harness I.2, proof T.6).

A small synthetic Unity prefab - a root, and a child that is moved, turned
and carries a box collider - is run through the real asset processor with a
trace. The tests check that:

  - every transform the prefab file holds has a trace record with the same
    values, the Unity values it came from and the rule that made it;
  - the collider component is recorded with the processor that added it,
    beside the Unity collider data;
  - a prefab or an assetinfo that differs from its trace is reported;
  - a run without a trace writes the same prefab;
  - the patch reader and the FBX facts reader behave on their edge cases.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from conversion_trace import (
    ConversionTrace, read_fbx_facts, transform_from_patches,
    uncovered_in_assetinfo, uncovered_in_output, uncovered_in_prefab,
)
from integrated_asset_processor import IntegratedAssetProcessor


# =============================================================================
# FIXTURE: one prefab, root + child with a box collider
# =============================================================================

PREFAB_GUID = "aaaabbbbccccdddd0000111122223333"

_PREFAB_YAML = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_ObjectHideFlags: 0
  serializedVersion: 6
  m_Component:
  - component: {fileID: 400}
  m_Layer: 0
  m_Name: Crate
  m_TagString: Untagged
  m_IsActive: 1
--- !u!4 &400
Transform:
  m_ObjectHideFlags: 0
  m_GameObject: {fileID: 100}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 5, y: 6, z: 7}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children:
  - {fileID: 401}
  m_Father: {fileID: 0}
  m_RootOrder: 0
--- !u!1 &101
GameObject:
  m_ObjectHideFlags: 0
  serializedVersion: 6
  m_Component:
  - component: {fileID: 401}
  - component: {fileID: 6500}
  m_Layer: 0
  m_Name: Lid
  m_TagString: Untagged
  m_IsActive: 1
--- !u!4 &401
Transform:
  m_ObjectHideFlags: 0
  m_GameObject: {fileID: 101}
  m_LocalRotation: {x: 0, y: 0.38268343, z: 0, w: 0.92387953}
  m_LocalPosition: {x: 1, y: 2, z: 3}
  m_LocalScale: {x: 2, y: 2, z: 2}
  m_Children: []
  m_Father: {fileID: 400}
  m_RootOrder: 0
--- !u!65 &6500
BoxCollider:
  m_ObjectHideFlags: 0
  m_GameObject: {fileID: 101}
  m_Material: {fileID: 0}
  m_IsTrigger: 0
  m_Enabled: 1
  serializedVersion: 2
  m_Size: {x: 1, y: 0.5, z: 0.25}
  m_Center: {x: 0.1, y: 0.2, z: 0.3}
"""


def _convert(tmp: Path, with_trace: bool = True):
    """Write the prefab under ``tmp/unity`` and convert it into ``tmp/out``.
    Returns ``(trace, prefab_file)``."""
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Crate.prefab"
    prefab.write_text(_PREFAB_YAML, encoding="utf-8")
    (unity_root / "Crate.prefab.meta").write_text(
        f"fileFormatVersion: 2\nguid: {PREFAB_GUID}\n", encoding="utf-8")

    trace = ConversionTrace() if with_trace else None
    out = tmp / ("out_traced" if with_trace else "out_plain")
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, out, log_callback=lambda line: None, trace=trace)
    assert processor.process_prefab(prefab), "the fixture prefab must convert"
    return trace, out / "Prefabs" / "Crate.prefab"


def _entity(record: dict, name: str) -> dict:
    return next(entity for entity in record["entities"] if entity["name"] == name)


# =============================================================================
# THE TRACE OF A PREFAB
# =============================================================================

def test_trace_covers_every_emitted_transform():
    with tempfile.TemporaryDirectory() as tmp:
        trace, prefab_file = _convert(Path(tmp))
        assert prefab_file.is_file()
        assert uncovered_in_output(trace) == []
        assert list(trace.prefabs) == [PREFAB_GUID]


def test_child_entity_records_unity_values_and_emitted_values():
    with tempfile.TemporaryDirectory() as tmp:
        trace, prefab_file = _convert(Path(tmp))
        lid = _entity(trace.prefabs[PREFAB_GUID], "Lid")

        assert lid["rule"] == "axis_swap"
        assert lid["unity"]["position"] == [1.0, 2.0, 3.0]
        assert lid["unity"]["scale"] == [2.0, 2.0, 2.0]
        assert abs(lid["unity"]["rotation"][1] - 0.38268343) < 1e-6

        # What the trace says was emitted is what the file holds.
        emitted = json.loads(prefab_file.read_text(encoding="utf-8"))
        data = emitted["Entities"][lid["entity_id"]]["Components"]["TransformComponent"]["Transform Data"]
        assert lid["emitted"]["translate"] == data["Translate"] == [1.0, 3.0, 2.0]
        assert lid["emitted"]["rotate_euler"] == data["Rotate"]
        assert lid["emitted"]["scale"] == data["Scale"] == 2.0
        assert lid["go_file_id"] == "101"


def test_root_entity_records_the_discarded_transform():
    with tempfile.TemporaryDirectory() as tmp:
        trace, _ = _convert(Path(tmp))
        root = _entity(trace.prefabs[PREFAB_GUID], "Crate")
        assert root["rule"] == "root_discarded"
        assert root["unity"]["position"] == [5.0, 6.0, 7.0]
        assert root["emitted"]["translate"] is None
        assert root["parent_entity_id"] == "ContainerEntity"


def test_collider_component_is_attributed_to_its_processor():
    with tempfile.TemporaryDirectory() as tmp:
        trace, _ = _convert(Path(tmp))
        lid = _entity(trace.prefabs[PREFAB_GUID], "Lid")

        unity_colliders = lid["unity_components"]["colliders"]
        assert len(unity_colliders) == 1 and unity_colliders[0]["type"] == "BoxCollider"

        owners = {component["key"]: component["processor"] for component in lid["components"]}
        assert owners, "the collider's components must be in the trace"
        assert all(owner for owner in owners.values()), owners
        assert any("Collider" in key or "Shape" in key for key in owners), owners
        emitted = next(c["emitted"] for c in lid["components"] if "ShapeCollider" in c["key"])
        assert "ColliderConfiguration" in emitted


def test_run_without_a_trace_writes_the_same_prefab():
    with tempfile.TemporaryDirectory() as tmp:
        _, traced_file = _convert(Path(tmp), with_trace=True)
        _, plain_file = _convert(Path(tmp), with_trace=False)
        assert traced_file.read_text(encoding="utf-8") == plain_file.read_text(encoding="utf-8")


def test_written_trace_can_be_read_back():
    with tempfile.TemporaryDirectory() as tmp:
        trace, _ = _convert(Path(tmp))
        catalog_file = trace.write(Path(tmp) / "trace")
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        record = json.loads((Path(tmp) / "trace" / catalog["prefabs"][PREFAB_GUID]).read_text(encoding="utf-8"))
        assert {entity["name"] for entity in record["entities"]} == {"Crate", "Lid"}
        assert json.loads((Path(tmp) / "trace" / "assetinfos.json").read_text(encoding="utf-8")) == []


# =============================================================================
# THE COVERAGE CHECK FINDS WHAT IS NOT COVERED
# =============================================================================

def test_changed_prefab_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        trace, prefab_file = _convert(Path(tmp))
        record = trace.prefabs[PREFAB_GUID]
        lid = _entity(record, "Lid")

        data = json.loads(prefab_file.read_text(encoding="utf-8"))
        data["Entities"][lid["entity_id"]]["Components"]["TransformComponent"]["Transform Data"]["Translate"][0] = 9.0
        prefab_file.write_text(json.dumps(data), encoding="utf-8")

        problems = uncovered_in_prefab(prefab_file, record)
        assert len(problems) == 1 and lid["entity_id"] in problems[0], problems


def test_untraced_entity_and_instance_are_reported():
    with tempfile.TemporaryDirectory() as tmp:
        prefab_file = Path(tmp) / "Made.prefab"
        prefab_file.write_text(json.dumps({
            "Entities": {"Entity_[9]": {"Components": {"TransformComponent": {
                "Transform Data": {"Translate": [1, 2, 3]}}}}},
            "Instances": {"Instance_[5]": {"Source": "a.prefab", "Patches": []}},
        }), encoding="utf-8")
        problems = uncovered_in_prefab(prefab_file, {"entities": [], "instances": []})
        assert len(problems) == 2, problems
        assert any("Entity_[9]" in problem for problem in problems)
        assert any("Instance_[5]" in problem for problem in problems)


def test_assetinfo_rule_must_match_its_last_write():
    with tempfile.TemporaryDirectory() as tmp:
        assetinfo = Path(tmp) / "Desk.FBX.assetinfo"
        assetinfo.write_text(json.dumps({"values": [{
            "name": "Desk-Desk",
            "rules": {"rules": [{"$type": "CoordinateSystemRule", "translation": [0.0, 1.0, 2.0]}]},
        }]}), encoding="utf-8")

        def write(translation):
            return {"fbx": "Desk.FBX", "groups": [
                {"name": "Desk-Desk", "rotation": None, "translation": translation}]}

        # An earlier write with another rule does not matter; the last one does.
        assert uncovered_in_assetinfo(assetinfo, [write([9.0, 9.0, 9.0]), write([0.0, 1.0, 2.0])]) == []
        assert len(uncovered_in_assetinfo(assetinfo, [write([0.0, 1.0, 2.0]), write([9.0, 9.0, 9.0])])) == 1
        assert len(uncovered_in_assetinfo(assetinfo, [])) == 1


# =============================================================================
# HELPERS
# =============================================================================

def test_transform_from_patches_reads_only_transform_patches():
    prefix = "/ContainerEntity/Components/TransformComponent/"
    emitted = transform_from_patches([
        {"op": "replace", "path": prefix + "Parent Entity", "value": "../Entity_[1]"},
        {"op": "replace", "path": prefix + "Transform Data/Translate/0", "value": 1.5},
        {"op": "replace", "path": prefix + "Transform Data/Translate/2", "value": -2.0},
        {"op": "replace", "path": prefix + "Transform Data/Rotate/1", "value": 90.0},
        {"op": "replace", "path": prefix + "Transform Data/Scale", "value": 3.0},
        {"op": "replace", "path": "/Entities/Entity_[2]/Components/X/assetHint", "value": "a"},
    ])
    assert emitted == {"translate": [1.5, 0.0, -2.0], "rotate_euler": [0.0, 90.0, 0.0], "scale": 3.0}
    assert transform_from_patches([]) == {"translate": None, "rotate_euler": None, "scale": None}


def test_fbx_facts_of_a_file_that_is_not_fbx_are_empty():
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "stub.fbx"
        stub.write_bytes(b"FBX-stub\x00\x00")
        assert read_fbx_facts(stub) == {}
        assert read_fbx_facts(Path(tmp) / "missing.fbx") == {}


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
