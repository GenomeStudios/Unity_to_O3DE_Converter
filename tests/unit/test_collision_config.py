"""Unit tests for I.1 — collision_processor schema + the read-only
physxsystemconfiguration.setreg parser.

  T-1: the `collision_processor` stage is present with the expected defaults
       after `Project.from_json`.
  T-6: `parse_physx_collision_config` extracts {index:name} layers and
       {uuid:name} groups from a realistic .setreg (PhysX5 + legacy PhysX
       gem nodes; empty `{}` slots skipped; Id-less preset → null UUID).
"""

import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import Project
from targets.o3de.collision_config import (
    parse_physx_collision_config, NULL_GROUP_UUID,
)


# --- Sample .setreg shaped after AutomatedTesting/Registry/physxsystemconfiguration.setreg ---

def _sample_setreg(gem_key: str) -> dict:
    layer_names = ["Default"] + [{} for _ in range(62)] + ["TouchBend"]  # 64 slots
    return {
        "Amazon": {"Gems": {gem_key: {"PhysXSystemConfiguration": {
            "CollisionConfig": {
                "Layers": {"LayerNames": layer_names},
                "Groups": {"GroupPresets": [
                    {"Name": "All", "ReadOnly": True},  # no Id → null UUID
                    {"Id": {"GroupId": "{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}"},
                     "Name": "None", "Group": {"Mask": 0}, "ReadOnly": True},
                    {"Id": {"GroupId": "{22769429-5D46-429B-829A-0115239D9AAA}"},
                     "Name": "All_NoTouchBend", "Group": {"Mask": 9223372036854775807}},
                ]},
            },
        }}}}
    }


def _write_temp(data: dict) -> Path:
    fd = tempfile.NamedTemporaryFile("w", suffix=".setreg", delete=False, encoding="utf-8")
    json.dump(data, fd)
    fd.close()
    return Path(fd.name)


# --- T-1 ---

def test_collision_processor_schema_present():
    proj = Project.from_json({"name": "Coll", "stages": {}, "pipeline_status": {}}, None)
    cp = proj.stages["collision_processor"]
    assert cp["defaults"] == {"collision_layer": None, "collision_group_id": None}
    assert cp["overrides"] == {}
    assert cp["layer_names"] == {}
    assert cp["group_names"] == {}
    assert cp["setreg_override"] == ""


def test_collision_processor_survives_partial_user_data():
    """A saved project carrying only `overrides` deep-merges against the
    defaults so newly added keys still populate."""
    proj = Project.from_json({
        "name": "CollPartial",
        "stages": {"collision_processor": {
            "overrides": {"guidA:123": {"collision_layer": 2}},
        }},
        "pipeline_status": {},
    }, None)
    cp = proj.stages["collision_processor"]
    assert cp["overrides"]["guidA:123"]["collision_layer"] == 2
    assert cp["defaults"] == {"collision_layer": None, "collision_group_id": None}
    assert "layer_names" in cp


# --- T-6 ---

def test_parse_setreg_physx5():
    path = _write_temp(_sample_setreg("PhysX5"))
    layers, groups = parse_physx_collision_config(path)
    assert layers == {"0": "Default", "63": "TouchBend"}        # empty {} slots skipped
    assert groups[NULL_GROUP_UUID] == "All"                     # Id-less preset → null UUID
    assert groups["{CDB6B8D8-5CD0-40A8-874D-839B00A92EBB}"] == "None"
    assert groups["{22769429-5D46-429B-829A-0115239D9AAA}"] == "All_NoTouchBend"


def test_parse_setreg_legacy_physx_gem():
    path = _write_temp(_sample_setreg("PhysX"))
    layers, groups = parse_physx_collision_config(path)
    assert layers == {"0": "Default", "63": "TouchBend"}
    assert groups[NULL_GROUP_UUID] == "All"


def test_parse_missing_or_garbage_returns_empty():
    assert parse_physx_collision_config(None) == ({}, {})
    assert parse_physx_collision_config("Z:/does/not/exist.setreg") == ({}, {})
    bad = _write_temp({"Amazon": {"Gems": {}}})   # no PhysX node
    assert parse_physx_collision_config(bad) == ({}, {})


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
