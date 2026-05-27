"""UI test for the MaterialTab dirty (↻) and externally-modified (✎)
markers. F-9.I.6 + F-9.I.6b."""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

import main_app
_app.setStyleSheet(main_app.THEME_QSS)


DIRTY_GLYPH = "↻"
EXT_GLYPH   = "✎"


def _build_inventory_with_state(material_states):
    """material_states: dict of guid → (output_path|None, last_emitted_iso|None).
    Returns the populated MaterialTab + the project."""
    from main_app import MaterialTab
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("DirtyMarkerTest")
    meta = {}
    state_materials = {}
    for guid, (out_path, last_emitted) in material_states.items():
        meta[guid] = {"asset_hint": guid, "shader_name": "Standard",
                      "source_stem": guid.replace("guid-", "Mat")}
        entry = {}
        if out_path is not None:
            entry["output_files"] = [str(out_path)]
        if last_emitted is not None:
            entry["last_emitted"] = last_emitted
        state_materials[guid] = entry
    proj.outputs["asset_processor"] = {"material_metadata": meta}
    proj.outputs["state_index"]     = {"materials": state_materials}
    tab = MaterialTab()
    tab.apply_project(proj)
    return tab, proj


def _row_text_for_guid(tab, guid: str) -> str:
    """Find the row whose UserRole data matches the given GUID."""
    from PySide6.QtCore import Qt
    for i in range(tab._inv_list.count()):
        item = tab._inv_list.item(i)
        if item.data(Qt.UserRole) == guid:
            return item.text()
    raise AssertionError(f"no row found for guid {guid!r}")


def test_dirty_marker_on_missing_output():
    """Missing output file → ↻ on the row."""
    td = Path(tempfile.mkdtemp(prefix="u2o_dirty_"))
    try:
        # guid-a: file exists → clean. guid-b: file missing → dirty.
        clean = td / "MatA.material"
        clean.write_text("{}", encoding="utf-8")
        missing = td / "MatB.material"  # never written
        tab, _ = _build_inventory_with_state({
            "guid-a": (clean,   None),
            "guid-b": (missing, None),
        })
        row_a = _row_text_for_guid(tab, "guid-a")
        row_b = _row_text_for_guid(tab, "guid-b")
        assert DIRTY_GLYPH not in row_a, f"clean row should not be dirty: {row_a!r}"
        assert DIRTY_GLYPH in row_b,     f"missing-output row should be dirty: {row_b!r}"
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_dirty_marker_on_never_emitted():
    """No state entry at all → ↻."""
    tab, _ = _build_inventory_with_state({
        "guid-never": (None, None),
    })
    row = _row_text_for_guid(tab, "guid-never")
    assert DIRTY_GLYPH in row


def test_external_mod_marker():
    """File mtime newer than last_emitted → ✎."""
    td = Path(tempfile.mkdtemp(prefix="u2o_ext_"))
    try:
        from project_manager import _utc_now_iso
        f = td / "MatX.material"
        f.write_text("{}", encoding="utf-8")
        past   = time.time() - 5
        future = time.time() + 10
        # Anchor file mtime in the past, then "emit", then bump mtime
        # to the future to simulate an in-engine edit.
        os.utime(f, (past, past))
        emitted = _utc_now_iso()
        os.utime(f, (future, future))
        tab, _ = _build_inventory_with_state({
            "guid-x": (f, emitted),
        })
        row = _row_text_for_guid(tab, "guid-x")
        assert EXT_GLYPH in row, f"row should carry ext-mod marker: {row!r}"
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_dirty_summary_band_copy():
    """Inventory summary line + dirty_summary band reflect counts."""
    td = Path(tempfile.mkdtemp(prefix="u2o_summary_"))
    try:
        missing = td / "M.material"
        tab, _ = _build_inventory_with_state({
            "guid-missing": (missing, None),
        })
        summary = tab._inv_summary.text()
        assert "1 dirty" in summary
        assert "need re-emission" in tab._dirty_summary.text()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


# ---------------------------------------------------------------------------
# MeshTab — mirrors the MaterialTab patterns above. F-9 patch worker
# mesh extension (`mem:mesh_patch_worker/mesh_patch_worker_plan` §I.3).
# ---------------------------------------------------------------------------


def _build_mesh_inventory_with_state(mesh_states):
    """mesh_states: dict of guid → (output_path|None, last_emitted_iso|None).
    Returns the populated MeshTab + the project."""
    from main_app import MeshTab
    from project_manager import project_manager
    pm = project_manager()
    proj = pm.new_project("MeshDirtyMarkerTest")
    meshes = {}
    state_meshes = {}
    for guid, (out_path, last_emitted) in mesh_states.items():
        meshes[guid] = guid.replace("guid-", "Mesh")
        entry = {}
        if out_path is not None:
            entry["output_files"] = [str(out_path)]
        if last_emitted is not None:
            entry["last_emitted"] = last_emitted
        state_meshes[guid] = entry
    proj.outputs["asset_processor"] = {"meshes": meshes}
    proj.outputs["state_index"]     = {"meshes": state_meshes}
    tab = MeshTab()
    tab.apply_project(proj)
    return tab, proj


def _mesh_row_text_for_guid(tab, guid: str) -> str:
    from PySide6.QtCore import Qt
    for i in range(tab._inv_list.count()):
        item = tab._inv_list.item(i)
        if item.data(Qt.UserRole) == guid:
            return item.text()
    raise AssertionError(f"no mesh row found for guid {guid!r}")


def test_mesh_dirty_marker_on_missing_output():
    td = Path(tempfile.mkdtemp(prefix="u2o_mesh_dirty_"))
    try:
        clean = td / "MeshA.fbx"
        clean.write_bytes(b"FBX-stub")
        missing = td / "MeshB.fbx"
        tab, _ = _build_mesh_inventory_with_state({
            "guid-a": (clean,   None),
            "guid-b": (missing, None),
        })
        row_a = _mesh_row_text_for_guid(tab, "guid-a")
        row_b = _mesh_row_text_for_guid(tab, "guid-b")
        assert DIRTY_GLYPH not in row_a, row_a
        assert DIRTY_GLYPH in row_b, row_b
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_mesh_external_mod_marker():
    td = Path(tempfile.mkdtemp(prefix="u2o_mesh_ext_"))
    try:
        from project_manager import _utc_now_iso
        f = td / "MeshX.fbx"
        f.write_bytes(b"FBX-stub")
        past   = time.time() - 5
        future = time.time() + 10
        os.utime(f, (past, past))
        emitted = _utc_now_iso()
        os.utime(f, (future, future))
        tab, _ = _build_mesh_inventory_with_state({
            "guid-x": (f, emitted),
        })
        row = _mesh_row_text_for_guid(tab, "guid-x")
        assert EXT_GLYPH in row, row
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_mesh_summary_band_copy():
    td = Path(tempfile.mkdtemp(prefix="u2o_mesh_summary_"))
    try:
        missing = td / "M.fbx"
        tab, _ = _build_mesh_inventory_with_state({
            "guid-missing": (missing, None),
        })
        assert "1 dirty" in tab._inv_summary.text()
        assert "need re-emission" in tab._dirty_summary.text()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
