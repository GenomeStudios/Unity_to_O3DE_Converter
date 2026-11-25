"""Unit tests for Unity LODGroup stripping in the Stage-1 prefab parser.

O3DE has no LODGroup component — LODs live inside one model asset and are
selected by a single MeshComponent. Unity LODGroups are instead separate child
GameObjects (LOD0/LOD1/…), each with its own renderer. Emitting every Unity LOD
child as its own enabled O3DE entity makes them all render at once. The parser
collapses each LODGroup to a single level (LOD0 by default), gated by the
`UnityParseContext.strip_lods` flag (wired from the Prefab Processor tab's
`asset_processor.strip_lods` setting → the worker `strip_lods` constructor param).

See mem:lod_handling/lod_handling_plan.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.types import GameObject, Transform
from platforms.unity.prefab import (
    UnityParseContext,
    parse_unity_prefab,
    strip_lod_groups,
    _extract_lod_renderer_levels,
    _remove_go_subtree,
)


class _StubCoverage:
    def record_component(self, *args, **kwargs):
        pass


def _ctx(strip_lods=True, keep_level=0, dispatch=None):
    return UnityParseContext(
        log=lambda *_: None,
        coverage=_StubCoverage(),
        component_dispatch=dispatch or {},
        strip_lods=strip_lods,
        lod_keep_level=keep_level,
    )


def _go(file_id, parent=None, children=None):
    return GameObject(
        file_id=file_id, name=f"GO{file_id}", transform=Transform(),
        parent_id=parent, children_ids=list(children or []),
    )


# ---------------------------------------------------------------------------
# _extract_lod_renderer_levels — m_LODs → per-level renderer fileID lists
# ---------------------------------------------------------------------------

def test_extract_levels_orders_lod0_first():
    lod_group = {
        "m_LODs": [
            {"renderers": [{"renderer": {"fileID": "23010"}}]},
            {"renderers": [{"renderer": {"fileID": "23020"}},
                           {"renderer": {"fileID": "23021"}}]},
            {"renderers": [{"renderer": {"fileID": "0"}}]},  # null ref dropped
        ]
    }
    assert _extract_lod_renderer_levels(lod_group) == [
        ["23010"], ["23020", "23021"], [],
    ]


def test_extract_levels_handles_empty():
    assert _extract_lod_renderer_levels({}) == []
    assert _extract_lod_renderer_levels({"m_LODs": []}) == []


# ---------------------------------------------------------------------------
# strip_lod_groups — keep LOD0, drop the rest
# ---------------------------------------------------------------------------

def test_strip_keeps_lod0_drops_lower_levels():
    # Root holds the LODGroup; LOD0/LOD1/LOD2 are sibling children.
    gos = {
        "100": _go("100", children=["110", "120", "130"]),
        "110": _go("110", parent="100"),
        "120": _go("120", parent="100"),
        "130": _go("130", parent="100"),
    }
    lod_groups = {"205": [["r0"], ["r1"], ["r2"]]}
    owner = {"r0": "110", "r1": "120", "r2": "130"}

    strip_lod_groups(_ctx(), gos, lod_groups, owner, keep_level=0)

    assert set(gos) == {"100", "110"}          # LOD0 kept, LOD1/LOD2 gone
    assert gos["100"].children_ids == ["110"]  # parent unlinked from dropped


def test_strip_removes_dropped_subtree():
    # LOD1 child has its own descendant; both must go.
    gos = {
        "100": _go("100", children=["110", "120"]),
        "110": _go("110", parent="100"),
        "120": _go("120", parent="100", children=["121"]),
        "121": _go("121", parent="120"),
    }
    lod_groups = {"205": [["r0"], ["r1"]]}
    owner = {"r0": "110", "r1": "120"}

    strip_lod_groups(_ctx(), gos, lod_groups, owner, keep_level=0)

    assert set(gos) == {"100", "110"}


def test_shared_renderer_keep_wins():
    # A renderer referenced by both LOD0 and LOD1 → its GO is kept.
    gos = {
        "100": _go("100", children=["110", "120"]),
        "110": _go("110", parent="100"),
        "120": _go("120", parent="100"),
    }
    lod_groups = {"205": [["r0"], ["r0", "r1"]]}  # r0 in both levels
    owner = {"r0": "110", "r1": "120"}

    strip_lod_groups(_ctx(), gos, lod_groups, owner, keep_level=0)

    assert "110" in gos          # shared renderer GO survives
    assert "120" not in gos      # LOD1-only renderer GO dropped


def test_keep_guard_protects_nested_kept_go():
    # Defensive: a kept GO nested under a dropped GO must survive even though
    # the dropped GO's subtree is removed.
    gos = {
        "100": _go("100", children=["120"]),
        "120": _go("120", parent="100", children=["110"]),  # dropped LOD1
        "110": _go("110", parent="120"),                    # kept LOD0, nested
    }
    lod_groups = {"205": [["r0"], ["r1"]]}
    owner = {"r0": "110", "r1": "120"}

    strip_lod_groups(_ctx(), gos, lod_groups, owner, keep_level=0)

    assert "110" in gos          # keep guard prevented its removal
    assert "120" not in gos


def test_remove_subtree_returns_count():
    gos = {
        "120": _go("120", children=["121", "122"]),
        "121": _go("121", parent="120"),
        "122": _go("122", parent="120"),
    }
    removed = _remove_go_subtree(gos, "120", set(), lambda *_: None)
    assert removed == 3
    assert gos == {}


# ---------------------------------------------------------------------------
# Full parse_unity_prefab — strip on/off through the real parse path
# ---------------------------------------------------------------------------

_LOD_PREFAB = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 200}
  - component: {fileID: 205}
  m_Name: LODRoot
--- !u!4 &200
Transform:
  m_GameObject: {fileID: 100}
  m_Father: {fileID: 0}
  m_Children:
  - {fileID: 210}
  - {fileID: 220}
--- !u!205 &205
LODGroup:
  m_GameObject: {fileID: 100}
  m_LODs:
  - renderers:
    - renderer: {fileID: 23010}
  - renderers:
    - renderer: {fileID: 23020}
--- !u!1 &110
GameObject:
  m_Component:
  - component: {fileID: 210}
  - component: {fileID: 23010}
  m_Name: LOD0
--- !u!4 &210
Transform:
  m_GameObject: {fileID: 110}
  m_Father: {fileID: 200}
  m_Children: []
--- !u!23 &23010
MeshRenderer:
  m_GameObject: {fileID: 110}
--- !u!1 &120
GameObject:
  m_Component:
  - component: {fileID: 220}
  - component: {fileID: 23020}
  m_Name: LOD1
--- !u!4 &220
Transform:
  m_GameObject: {fileID: 120}
  m_Father: {fileID: 200}
  m_Children: []
--- !u!23 &23020
MeshRenderer:
  m_GameObject: {fileID: 120}
"""


def _parse(text, strip_lods):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".prefab", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        path = f.name
    try:
        gos, _ = parse_unity_prefab(_ctx(strip_lods=strip_lods), Path(path))
    finally:
        Path(path).unlink(missing_ok=True)
    return gos


def test_full_parse_strip_on_drops_lod1():
    gos = _parse(_LOD_PREFAB, strip_lods=True)
    assert "110" in gos            # LOD0 survives
    assert "120" not in gos        # LOD1 stripped
    assert gos["100"].children_ids == ["110"]


def test_full_parse_strip_off_keeps_all_lods():
    gos = _parse(_LOD_PREFAB, strip_lods=False)
    assert "110" in gos
    assert "120" in gos            # both LODs retained when toggle off
    assert set(gos["100"].children_ids) == {"110", "120"}


# ---------------------------------------------------------------------------
# Worker wiring — strip_lods constructor param reaches the parse context
# ---------------------------------------------------------------------------

def test_worker_threads_strip_flag_into_context():
    from integrated_asset_processor import IntegratedAssetProcessor
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"; src.mkdir()
        out = Path(d) / "out"; out.mkdir()
        on = IntegratedAssetProcessor(src, out, log_callback=lambda *_: None,
                                      strip_lods=True)
        off = IntegratedAssetProcessor(src, out, log_callback=lambda *_: None,
                                       strip_lods=False)
        assert on._parser_context().strip_lods is True
        assert off._parser_context().strip_lods is False


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
