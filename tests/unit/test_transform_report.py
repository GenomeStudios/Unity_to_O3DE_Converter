"""Unit tests for the pure helpers of the transform reconciliation report
(`tools/transform_report.py`) — the diagnostic that exposes FBX-baked
node offsets vs Unity-authored placement. See
`mem:transform_truth/transform_truth_plan`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from tests.harness import run_module_tests
from transform_report import classify_bake, compose_world_pos, UNITY_TO_M


# --- classify_bake -------------------------------------------------------

def test_large_scene_offset_and_axis_bake():
    """The Office frame pattern: ~25m X layout bake + 90° Z-up→Y-up bake."""
    c = classify_bake([2500.0, 0.0, -0.134], [90.0, 0.0, 0.0])
    assert c["translation_m"] == [25.0, 0.0, round(-0.134 * UNITY_TO_M, 4)]
    assert "large-scene-offset" in c["tags"]
    assert "axis-90-bake" in c["tags"]


def test_furniture_scale_offset_is_sub_node_not_large():
    """A 1.25m door-height offset is real placement, not a layout bake."""
    c = classify_bake([62.42, 125.01, 22.22], [0.0, 0.0, 0.0])
    assert "large-scene-offset" not in c["tags"]
    assert "sub-node-offset" in c["tags"]
    assert "axis-90-bake" not in c["tags"]


def test_zero_bake_has_no_tags():
    c = classify_bake([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    assert c["tags"] == []
    assert c["translation_m"] == [0.0, 0.0, 0.0]


def test_270_counts_as_axis_bake():
    assert "axis-90-bake" in classify_bake([0, 0, 0], [0, 270.0, 0])["tags"]


# --- compose_world_pos ---------------------------------------------------

class _T:
    def __init__(self, p): self.position = p


class _GO:
    def __init__(self, pos, parent=None):
        self.transform = _T(pos); self.parent_id = parent


def test_world_pos_sums_parent_chain():
    gos = {
        "root": _GO((0.0, 0.0, 0.0), None),
        "mid":  _GO((1.0, 0.0, 0.0), "root"),
        "leaf": _GO((0.0, 2.0, 0.0), "mid"),
    }
    assert compose_world_pos(gos["leaf"], gos) == (1.0, 2.0, 0.0)


def test_world_pos_root_is_local():
    gos = {"root": _GO((-0.602, 0.76, 0.448), None)}
    assert compose_world_pos(gos["root"], gos) == (-0.602, 0.76, 0.448)


def test_world_pos_tolerates_cycle():
    a = _GO((1.0, 0.0, 0.0), "b"); b = _GO((0.0, 1.0, 0.0), "a")
    gos = {"a": a, "b": b}
    # Must terminate (cycle guard) — value is best-effort, just no hang.
    compose_world_pos(a, gos)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
