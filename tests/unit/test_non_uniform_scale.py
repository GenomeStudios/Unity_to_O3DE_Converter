"""Unit tests for an object's non-uniform scale (parity_fixes I.5, proof T.8).

O3DE's transform holds one scale for all axes; a scale that differs by axis
lives in an ``EditorNonUniformScaleComponent``, which the engine reads from
the field ``NonUniformScale``. Written under any other key the component
loads with a scale of one - which is what the converter did.
"""

import json
import random
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from conversion_trace import ConversionTrace, uncovered_in_output
from integrated_asset_processor import IntegratedAssetProcessor
from targets.o3de.prefab_writer import instance_non_uniform_scale_patches, non_uniform_scale_component


# =============================================================================
# FIXTURE: a root, a stretched leaf, and a stretched object with a child
# =============================================================================

PREFAB_GUID = "aaaabbbbccccdddd0000111122224444"


def _object(game_object_id, transform_id, name, scale, father, children=()):
    child_lines = "".join(f"\n  - {{fileID: {child}}}" for child in children) or " []"
    return f"""--- !u!1 &{game_object_id}
GameObject:
  m_Component:
  - component: {{fileID: {transform_id}}}
  m_Name: {name}
--- !u!4 &{transform_id}
Transform:
  m_GameObject: {{fileID: {game_object_id}}}
  m_LocalRotation: {{x: 0, y: 0, z: 0, w: 1}}
  m_LocalPosition: {{x: 0, y: 0, z: 0}}
  m_LocalScale: {{x: {scale[0]}, y: {scale[1]}, z: {scale[2]}}}
  m_Children:{child_lines}
  m_Father: {{fileID: {father}}}
"""


_PREFAB_YAML = ("%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"
                + _object(100, 400, "Stairs", (1, 1, 1), 0, children=(401, 402))
                + _object(101, 401, "Ramp", (1.821, 4.182, 0.5), 400)
                + _object(102, 402, "Frame", (2, 1, 1), 400, children=(403,))
                + _object(103, 403, "Bolt", (1, 1, 1), 402))


def _convert(tmp: Path):
    unity_root = tmp / "unity"
    unity_root.mkdir(parents=True, exist_ok=True)
    prefab = unity_root / "Stairs.prefab"
    prefab.write_text(_PREFAB_YAML, encoding="utf-8")
    (unity_root / "Stairs.prefab.meta").write_text(f"fileFormatVersion: 2\nguid: {PREFAB_GUID}\n", encoding="utf-8")

    trace = ConversionTrace()
    random.seed(7)
    processor = IntegratedAssetProcessor(unity_root, tmp / "out", log_callback=lambda line: None, trace=trace)
    assert processor.process_prefab(prefab), "the fixture prefab must convert"
    emitted = json.loads((tmp / "out" / "Prefabs" / "Stairs.prefab").read_text(encoding="utf-8"))
    by_name = {entity["Name"]: entity for entity in emitted["Entities"].values()}
    return processor, trace, by_name


# =============================================================================
# TESTS
# =============================================================================

def test_the_component_holds_the_scale_under_the_engines_field_name():
    component = non_uniform_scale_component(7, (1.5, 2, 0.25))
    assert component == {"$type": "EditorNonUniformScaleComponent", "Id": 7, "NonUniformScale": [1.5, 2.0, 0.25]}


def test_a_stretched_object_gets_the_component_with_its_axes_swapped():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, by_name = _convert(Path(tmp))
        components = by_name["Ramp"]["Components"]
        # Unity (x, y, z) is O3DE (x, z, y).
        assert components["EditorNonUniformScaleComponent"]["NonUniformScale"] == [1.821, 0.5, 4.182]
        assert "Scale" not in components["EditorNonUniformScaleComponent"]
        assert "Scale" not in components["TransformComponent"].get("Transform Data", {})


def test_the_trace_holds_the_scale_that_was_written():
    with tempfile.TemporaryDirectory() as tmp:
        _, trace, _ = _convert(Path(tmp))
        ramp = next(e for e in trace.prefabs[PREFAB_GUID]["entities"] if e["name"] == "Ramp")
        assert ramp["emitted"]["nonuniform_scale"] == [1.821, 0.5, 4.182]
        assert uncovered_in_output(trace) == []


def test_what_hangs_below_a_stretched_object_is_stretched_with_it():
    """Unity scales everything below an object with it; the engine passes a
    scale by axis to nothing below its entity. The converter carries it
    down: the bolt in the frame is as wide as Unity shows it, and nothing
    is left to report."""
    with tempfile.TemporaryDirectory() as tmp:
        processor, _, by_name = _convert(Path(tmp))
        assert by_name["Frame"]["Components"]["EditorNonUniformScaleComponent"]["NonUniformScale"] == [2.0, 1.0, 1.0]
        assert by_name["Bolt"]["Components"]["EditorNonUniformScaleComponent"]["NonUniformScale"] == [2.0, 1.0, 1.0]
        assert not any("'Frame'" in line or "'Bolt'" in line for line in processor.coverage.warnings)


# =============================================================================
# A NESTED INSTANCE
# The folder in the Office pack's metal box: a prefab of one object, nested
# with a scale of (2.098, 1.156, 1.223).
# =============================================================================

def test_a_nested_instances_scale_goes_onto_its_root_entity():
    warnings = []
    sidecar = {"root_entity": "Entity_[1000007]", "entity_aliases": {"100": "Entity_[1000007]"}}
    patches = instance_non_uniform_scale_patches((2.098, 1.223, 1.156), sidecar, 41, "Folder_C", warnings.append)
    assert patches == [{
        "op": "add",
        "path": "/Entities/Entity_[1000007]/Components/EditorNonUniformScaleComponent",
        "value": {"$type": "EditorNonUniformScaleComponent", "Id": 41, "NonUniformScale": [2.098, 1.223, 1.156]},
    }]
    assert warnings == []


def test_a_nested_prefab_of_several_objects_is_scaled_at_its_root_and_reported():
    warnings = []
    sidecar = {"root_entity": "Entity_[1]", "entity_aliases": {"100": "Entity_[1]", "101": "Entity_[2]"}}
    assert len(instance_non_uniform_scale_patches((2, 1, 1), sidecar, 5, "Desk", warnings.append)) == 1
    assert any("objects below the root keep" in line for line in warnings), warnings


def test_without_the_nested_prefabs_entity_map_nothing_is_patched():
    warnings = []
    assert instance_non_uniform_scale_patches((2, 1, 1), None, 5, "Desk", warnings.append) == []
    assert any("entity map is not known" in line for line in warnings)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
