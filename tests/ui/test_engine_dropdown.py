"""UI test for Phase E engine dropdown — switching the active
SourceEngine via the combo on ``ProjectHeaderBanner`` drives the
project's `active_platform` and fires the transient toast."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

from PySide6.QtWidgets import QComboBox
import main_app
_app.setStyleSheet(main_app.THEME_QSS)


def _build_banner_with_project():
    from main_app import ProjectHeaderBanner
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("DropdownUITest")
    proj.update_stage("asset_processor", {
        "source_path": "/unity",
        "selected_prefabs": ["Foo.prefab"],
        "output_path": "/unity_out",
    })
    banner = ProjectHeaderBanner()
    banner.apply_project(proj)
    return banner, proj


def _engine_combo(banner):
    combos = banner.findChildren(QComboBox)
    assert combos, "no QComboBox in banner"
    return combos[0]


def test_combo_carries_four_engines_in_order():
    banner, _ = _build_banner_with_project()
    combo = _engine_combo(banner)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["Unity", "Unreal", "Godot", "Blender"]


def test_switching_to_godot_changes_active_platform():
    banner, proj = _build_banner_with_project()
    combo = _engine_combo(banner)
    idx_godot = combo.findData("godot")
    assert idx_godot >= 0
    banner._suppress_emits = False
    combo.setCurrentIndex(idx_godot)
    _app.processEvents()
    assert proj.active_platform == "godot"


def test_switch_fires_toast():
    banner, proj = _build_banner_with_project()
    combo = _engine_combo(banner)
    banner._suppress_emits = False
    combo.setCurrentIndex(combo.findData("godot"))
    _app.processEvents()
    # The toast widget is parented to the (collapsed) expanded panel,
    # so isVisible() can be False; isHidden() reflects only the
    # explicit hide flag.
    assert not banner._switch_toast.isHidden()
    assert "Switched to Godot" in banner._switch_toast.text()
    # Old-platform summary mentions 1 prefab selection.
    assert "1 prefab" in banner._switch_toast.text()


def test_switch_back_to_unity_restores_data():
    banner, proj = _build_banner_with_project()
    combo = _engine_combo(banner)
    banner._suppress_emits = False
    combo.setCurrentIndex(combo.findData("godot"))
    _app.processEvents()
    combo.setCurrentIndex(combo.findData("unity"))
    _app.processEvents()
    assert proj.active_platform == "unity"
    ap = proj.stage_settings("asset_processor")
    assert ap["selected_prefabs"] == ["Foo.prefab"]
    assert "Switched to Unity" in banner._switch_toast.text()


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
