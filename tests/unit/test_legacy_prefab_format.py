"""Unit tests for legacy (pre-Unity-2018.3) prefab-instance parsing in the
Stage-2 scene converter.

Regression for the Alien Fantasy Forest case: the Demo1.unity scene places
its entire jungle as ~7000 prefab instances serialized in the OLD format
(doc key `Prefab:` / source ref `m_ParentPrefab:`), but the parser only
recognized the modern format (`PrefabInstance:` / `m_SourcePrefab:`), so the
scene converted to an empty level. The m_Modification block is byte-identical
across both formats, so only detection + the source-ref field name differ.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.scene_converter import UnitySceneConverter, PrefabDatabase


GUID = "d8a157b6edda2424bb6c18df74edcd70"


def _converter() -> UnitySceneConverter:
    return UnitySceneConverter(PrefabDatabase(), log_callback=lambda *_: None)


# ---------------------------------------------------------------------------
# Direct _parse_prefab_instance: format-agnostic body, legacy source field
# ---------------------------------------------------------------------------

def _legacy_prefab_dict():
    """A legacy `Prefab:` instance body as yaml.safe_load would yield it."""
    return {
        "m_Modification": {
            "m_TransformParent": {"fileID": 0},
            "m_Modifications": [
                {"propertyPath": "m_LocalPosition.x", "value": 10.5},
                {"propertyPath": "m_LocalPosition.y", "value": 2.0},
                {"propertyPath": "m_LocalPosition.z", "value": -3.25},
                {"propertyPath": "m_Name", "value": "Tree_01_1"},
            ],
            "m_RemovedComponents": [],
        },
        "m_ParentPrefab": {"fileID": 100100000, "guid": GUID, "type": 2},
        "m_IsPrefabParent": 0,
    }


def test_legacy_parent_prefab_guid_is_read():
    conv = _converter()
    conv._parse_prefab_instance(_legacy_prefab_dict())
    assert len(conv.prefab_instances) == 1
    assert conv.prefab_instances[0]["guid"] == GUID


def test_legacy_transform_overrides_project_onto_position():
    conv = _converter()
    conv._parse_prefab_instance(_legacy_prefab_dict())
    inst = conv.prefab_instances[0]
    assert inst["position"] == (10.5, 2.0, -3.25)
    assert inst["name"] == "Tree_01_1"


def test_modern_source_prefab_still_read():
    """Regression: modern m_SourcePrefab path is untouched by the fallback."""
    conv = _converter()
    conv._parse_prefab_instance({
        "m_Modification": {"m_Modifications": []},
        "m_SourcePrefab": {"fileID": 100100000, "guid": GUID, "type": 3},
    })
    assert len(conv.prefab_instances) == 1
    assert conv.prefab_instances[0]["guid"] == GUID


# ---------------------------------------------------------------------------
# Full parse_unity_scene: exercises the !u!1001 regex + doc-key dispatch
# ---------------------------------------------------------------------------

_LEGACY_SCENE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &707150
Prefab:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    m_TransformParent: {fileID: 0}
    m_Modifications:
    - target: {fileID: 4394570554888152, guid: __GUID__, type: 2}
      propertyPath: m_LocalPosition.x
      value: 10.5
      objectReference: {fileID: 0}
    - target: {fileID: 4394570554888152, guid: __GUID__, type: 2}
      propertyPath: m_LocalPosition.z
      value: -3.25
      objectReference: {fileID: 0}
    m_RemovedComponents: []
  m_ParentPrefab: {fileID: 100100000, guid: __GUID__, type: 2}
  m_IsPrefabParent: 0
""".replace("__GUID__", GUID)


# A legacy prefab-ASSET reference (m_IsPrefabParent: 1) that must be ignored.
_LEGACY_ASSET_REF = """--- !u!1001 &900900
Prefab:
  m_ObjectHideFlags: 0
  serializedVersion: 2
  m_Modification:
    m_TransformParent: {fileID: 0}
    m_Modifications: []
    m_RemovedComponents: []
  m_ParentPrefab: {fileID: 100100000, guid: ffffffffffffffffffffffffffffffff, type: 2}
  m_IsPrefabParent: 1
"""


def _parse_scene_text(text: str) -> UnitySceneConverter:
    conv = _converter()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".unity", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        path = f.name
    try:
        conv.parse_unity_scene(path)
    finally:
        Path(path).unlink(missing_ok=True)
    return conv


def test_full_parse_picks_up_legacy_instance():
    conv = _parse_scene_text(_LEGACY_SCENE)
    assert len(conv.prefab_instances) == 1
    assert conv.prefab_instances[0]["guid"] == GUID
    # A prefab-instance GameObject is materialized for it.
    pi = [g for g in conv.game_objects.values() if g.is_prefab_instance]
    assert len(pi) == 1
    assert pi[0].prefab_source_guid == GUID


def test_full_parse_skips_prefab_asset_reference():
    """m_IsPrefabParent: 1 is a prefab-asset doc, not a placement — skip it."""
    conv = _parse_scene_text(_LEGACY_SCENE + _LEGACY_ASSET_REF)
    # Only the m_IsPrefabParent: 0 instance survives.
    assert len(conv.prefab_instances) == 1
    assert conv.prefab_instances[0]["guid"] == GUID


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
