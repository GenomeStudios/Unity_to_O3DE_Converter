"""UI test for the redesigned _PreflightPanel.

Covers the collapsed-by-default header, the per-category dot row, the
Jump-to-issue button visibility, and the gating of Patch All / Run All
on red preflight items.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

import main_app  # noqa: F401


def _build_panel_with_report(items):
    """Return a populated `_PreflightPanel` driven by a synthetic
    `PreflightReport`. `items` is a list of (category, severity, title,
    ack_key) tuples."""
    from preflight import PreflightItem, PreflightReport
    from project_manager import project_manager

    pm = project_manager()
    proj = pm.new_project("PreflightUITest")
    report = PreflightReport(
        items=[
            PreflightItem(category=cat, severity=sev, title=title,
                          ack_key=ak, ack_snapshot=("snap" if ak else None))
            for (cat, sev, title, ak) in items
        ],
        acks=dict(proj.preflight_acks),
    )
    panel = main_app._PreflightPanel()
    panel.apply_report(report, proj)
    return panel, proj


def test_collapsed_by_default():
    """A fresh panel is collapsed — detail rows hidden, toggle says 'Show more'."""
    panel, _ = _build_panel_with_report([
        ("asset_processor", "green", "ok", None),
    ])
    assert panel._rows_container.isHidden() is True
    assert "Show more" in panel._toggle_btn.text()


def test_dot_row_skips_environment_and_uses_dashboard_order():
    """Environment isn't a stage — it has no status card — so it's
    excluded from the dot row. Stage dots render in dashboard-card
    order (scene_converter → asset_processor → mesh → material →
    terrain), NOT preflight-report-call order."""
    panel, _ = _build_panel_with_report([
        # Pass them in deliberately-jumbled report order to prove the
        # panel sorts by STAGE_ORDER, not by report order.
        ("environment",        "green", "deps", None),
        ("asset_processor",    "green", "ok",   None),
        ("terrain_processor",  "green", "ok",   None),
        ("scene_converter",    "green", "ok",   None),
        ("material_processor", "green", "ok",   None),
        ("mesh_processor",     "green", "ok",   None),
    ])
    cats = [c for (c, _w) in panel._dot_widgets]
    # No environment dot.
    assert "environment" not in cats
    # Exact dashboard order.
    assert cats == [
        "scene_converter",
        "asset_processor",
        "mesh_processor",
        "material_processor",
        "terrain_processor",
    ]
    assert panel._dots_layout.count() == 5


def test_dot_row_skips_stages_not_in_report():
    """Stages absent from the report (platform doesn't expose them)
    don't get a dot — the row stays aligned with the visible cards."""
    panel, _ = _build_panel_with_report([
        ("asset_processor", "green", "ok", None),
        ("mesh_processor",  "green", "ok", None),
    ])
    cats = [c for (c, _w) in panel._dot_widgets]
    assert cats == ["asset_processor", "mesh_processor"]


def test_all_green_summary_and_no_jump():
    panel, _ = _build_panel_with_report([
        ("environment",     "green", "deps", None),
        ("asset_processor", "green", "ok",   None),
        ("mesh_processor",  "green", "ok",   None),
    ])
    text = panel._summary_lbl.text()
    assert "Ready" in text, text
    # Environment is NOT counted as a stage. Two stage dots → "2 stages green".
    assert "2 stages green" in text, text
    assert panel._jump_btn.isHidden() is True
    # Both buttons enabled.
    assert panel._run_all_btn.isEnabled()
    assert panel._patch_all_btn.isEnabled()


def test_red_disables_run_all_and_patch_all_and_shows_jump():
    panel, _ = _build_panel_with_report([
        ("environment",     "green", "deps",       None),
        ("asset_processor", "red",   "Missing source root", None),
    ])
    assert panel._run_all_btn.isEnabled() is False
    assert panel._patch_all_btn.isEnabled() is False
    assert panel._jump_btn.isHidden() is False
    assert "Missing source root" in panel._summary_lbl.text()


def test_unack_yellow_blocks_run_all_but_not_patch_all():
    panel, _ = _build_panel_with_report([
        ("environment",     "green",  "deps", None),
        ("asset_processor", "yellow", "Profiles unmapped", "shaders.unmapped"),
    ])
    assert panel._run_all_btn.isEnabled() is False
    # Yellows alone should not block patching.
    assert panel._patch_all_btn.isEnabled() is True
    assert panel._jump_btn.isHidden() is False


def test_dot_click_emits_category():
    panel, _ = _build_panel_with_report([
        ("asset_processor", "red", "x", None),
        ("mesh_processor",  "green", "ok", None),
    ])
    captured = []
    panel.category_clicked.connect(lambda c: captured.append(c))
    # Click the mesh_processor dot.
    for cat, btn in panel._dot_widgets:
        if cat == "mesh_processor":
            btn.click()
            break
    assert captured == ["mesh_processor"]


def test_jump_button_emits_first_red_category():
    panel, _ = _build_panel_with_report([
        ("environment",     "green", "deps", None),
        ("asset_processor", "red",   "missing", None),
        ("mesh_processor",  "yellow", "unmapped", "k"),
    ])
    captured = []
    panel.category_clicked.connect(lambda c: captured.append(c))
    panel._jump_btn.click()
    assert captured == ["asset_processor"]


def test_show_more_expands_rows_and_label_flips():
    panel, _ = _build_panel_with_report([
        ("environment", "green", "deps", None),
    ])
    assert panel._rows_container.isHidden() is True
    assert "Show more" in panel._toggle_btn.text()
    panel._toggle_btn.click()
    assert panel._rows_container.isHidden() is False
    assert "Show less" in panel._toggle_btn.text()


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
