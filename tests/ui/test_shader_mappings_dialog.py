"""UI test for the F-6 ShaderMappingsDialog popout — opens from
the MaterialTab, renders QComboBox rows per detected shader, edits
through commit back to the project file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

from PySide6.QtWidgets import QComboBox
import main_app
_app.setStyleSheet(main_app.THEME_QSS)


def _seed_project_with_detected_shaders():
    from main_app import MaterialTab
    from project_manager import project_manager, DEFAULT_PROFILE_NAME
    pm = project_manager()
    proj = pm.new_project("ShaderDialogUITest")
    proj.outputs["asset_processor"] = {
        "material_metadata": {
            "guid-a": {"shader_name": "Standard", "asset_hint": "a", "source_stem": "A"},
            "guid-b": {"shader_name": "CustomPack/Unmapped",
                        "asset_hint": "b", "source_stem": "B"},
        },
    }
    tab = MaterialTab()
    tab.apply_project(proj)
    return tab, proj


def test_dialog_opens_with_detected_shaders():
    from main_app import ShaderMappingsDialog
    tab, _ = _seed_project_with_detected_shaders()
    tab._open_mappings_dialog()
    dlg = tab._shader_dialog
    assert isinstance(dlg, ShaderMappingsDialog)
    # The dialog's summary reports detected/mapped/unmapped counts.
    summary = dlg._summary.text()
    assert "2 detected" in summary
    assert "1 mapped"   in summary or "1 unmapped" in summary, \
        f"summary should distinguish mapped/unmapped: {summary!r}"


def test_dialog_rows_use_qcombobox_picker():
    """F-9.I.1b shipped this — profile picker instead of materialtype path."""
    tab, _ = _seed_project_with_detected_shaders()
    tab._open_mappings_dialog()
    dlg = tab._shader_dialog
    # Walk the rows layout looking for QComboBox descendants.
    combos = []
    for i in range(dlg._rows_layout.count() - 1):  # last is the stretch
        item = dlg._rows_layout.itemAt(i)
        w = item.widget()
        if w is None:
            continue
        combos.extend(w.findChildren(QComboBox))
    assert len(combos) == 2, \
        f"expected one combo per detected shader, got {len(combos)}"


def test_dialog_mapping_change_persists():
    from project_manager import DEFAULT_PROFILE_NAME
    tab, proj = _seed_project_with_detected_shaders()
    tab._open_mappings_dialog()
    dlg = tab._shader_dialog

    # Trigger the dialog's handler directly (simpler than reaching into
    # the row's QComboBox.setCurrentText, which fires synchronously).
    dlg._on_mapping_changed("CustomPack/Unmapped", DEFAULT_PROFILE_NAME)

    mappings = proj.stage_settings("material_processor")["shader_mappings"]
    assert mappings.get("CustomPack/Unmapped") == DEFAULT_PROFILE_NAME


def test_default_field_is_combo_not_path():
    """Phase B + F-9.I.1b: the default-profile field on MaterialTab is
    a QComboBox now, not a _PathField."""
    tab, _ = _seed_project_with_detected_shaders()
    assert isinstance(tab._default_profile, QComboBox)
    items = [tab._default_profile.itemText(i)
             for i in range(tab._default_profile.count())]
    assert "Default — Anything to PBR" in items


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
