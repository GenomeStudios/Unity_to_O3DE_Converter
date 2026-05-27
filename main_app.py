#!/usr/bin/env python3
"""
Unity → O3DE Converter — Unified PySide6 Application

Two-tab interface:
  Tab 1 — Prefab Processor  (integrated_asset_processor.py)
  Tab 2 — Scene Converter   (unity_scene_converter_gui.py)

Run:
    python main_app.py
    python main_app.py --tab=prefab
    python main_app.py --tab=scene
"""

import json
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore    import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui     import QFont, QTextCursor, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QSizePolicy, QCheckBox,
    QComboBox, QToolButton, QMenu, QStackedWidget, QFrame,
    QFormLayout, QInputDialog,
)

from project_manager import (
    Project, ProjectScope, ProjectManager, project_manager,
    PROJECT_FILE_EXT, STAGE_KEYS, _utc_now_iso,
)


# =============================================================================
# SETTINGS
# =============================================================================

SETTINGS_FILE = Path(__file__).parent / "converter_settings.json"


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(data: dict) -> None:
    try:
        existing = load_settings()
        existing.update(data)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(existing, f, indent=4)
    except Exception:
        pass


# =============================================================================
# DARK THEME  (Catppuccin Mocha palette)
# =============================================================================

THEME_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 10pt;
}

QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    padding: 8px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #45475a;
}

/* Config "tab" lives as a corner widget so it can be right-pinned. Style
   it to match the QTabBar::tab look so the seam isn't obvious. */
QPushButton#config_corner {
    background: #313244;
    color: #cdd6f4;
    padding: 8px 20px;
    border: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-left: 8px;
    min-width: 0;
}
QPushButton#config_corner:hover {
    background: #45475a;
}
QPushButton#config_corner:checked {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}

QLineEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
    padding: 5px 8px;
    selection-background-color: #89b4fa;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}

QPushButton {
    background: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    min-width: 70px;
}
QPushButton:hover {
    background: #585b70;
}
QPushButton:pressed {
    background: #313244;
}
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QPushButton#primary:hover {
    background: #b4d0ff;
}
QPushButton#primary:disabled {
    background: #45475a;
    color: #6c7086;
}

QTextEdit {
    background: #11111b;
    color: #a6e3a1;
    font-family: Consolas, Courier New, monospace;
    font-size: 9pt;
    border: 1px solid #313244;
    border-radius: 4px;
}

QListWidget {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
}
QListWidget::item:selected {
    background: #89b4fa;
    color: #1e1e2e;
}
QListWidget::item:hover {
    background: #45475a;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    color: #89b4fa;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
}

QCheckBox {
    color: #cdd6f4;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #45475a;
    border-radius: 3px;
    background: #313244;
}
QCheckBox::indicator:hover {
    border: 1px solid #89b4fa;
}
QCheckBox::indicator:checked {
    background: #89b4fa;
    border: 1px solid #89b4fa;
}

QLabel#section {
    color: #89b4fa;
    font-weight: bold;
}
QLabel#status_ok {
    color: #a6e3a1;
    font-size: 9pt;
}
QLabel#status_warn {
    color: #f9e2af;
    font-size: 9pt;
}
QLabel#status_err {
    color: #f38ba8;
    font-size: 9pt;
}

QScrollBar:vertical {
    background: #1e1e2e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #89b4fa;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# =============================================================================
# THREAD WORKER  — runs blocking processing functions off the main thread
# =============================================================================

class LogEmitter(QObject):
    message = Signal(str)


class WorkerThread(QThread):
    """Generic background worker. Emits log messages and a finished signal."""
    finished = Signal(bool, str)   # success, summary_text

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn    = fn
        self._args  = args
        self._kwargs = kwargs
        self.emitter = LogEmitter()

    def _log(self, msg: str) -> None:
        self.emitter.message.emit(msg)

    def run(self) -> None:
        try:
            result = self._fn(*self._args, log=self._log, **self._kwargs)
            summary = result if isinstance(result, str) else "Done."
            self.finished.emit(True, summary)
        except Exception as exc:
            self.emitter.message.emit(f"\n✗ EXCEPTION: {exc}")
            self.emitter.message.emit(traceback.format_exc())
            self.finished.emit(False, str(exc))


# =============================================================================
# SHARED WIDGETS
# =============================================================================

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def _path_row(placeholder: str) -> tuple:
    """Returns (QLineEdit, browse_QPushButton) arranged in an HBoxLayout."""
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    btn  = QPushButton("Browse…")
    return edit, btn


# =============================================================================
# BROWSE-DIALOG START-PATH HELPERS
#
# Every browse button in every tab should reopen the dialog at the saved path
# it represents — not at whatever folder the OS last opened. The two helpers
# below resolve a stored line-edit string to something safe to hand to
# QFileDialog's `dir` argument: an existing directory (for getExistingDirectory)
# or an existing file/directory (for getOpenFileName / getSaveFileName).
#
# If the stored path no longer exists they walk up to the nearest existing
# parent directory rather than returning a broken path that Qt would discard.
# =============================================================================

def _resolve_start_dir(text: str, default: str = "") -> str:
    """Pick a starting directory for a `getExistingDirectory` call.

    text → return text if it's a directory, else its parent if it's a file,
    else the nearest existing ancestor. Falls back to `default` (which itself
    falls through to Qt's OS-default behavior when empty).
    """
    if text:
        try:
            p = Path(text).expanduser()
            if p.is_dir():
                return str(p)
            if p.is_file():
                return str(p.parent)
            for parent in p.parents:
                if parent.exists() and parent.is_dir():
                    return str(parent)
        except Exception:
            pass
    return default


def _resolve_start_path(text: str, default: str = "") -> str:
    """Pick a starting path for `getOpenFileName` / `getSaveFileName`.

    When `text` points at an existing file, return the full path so Qt
    pre-fills the filename. When it doesn't, fall back to the nearest
    existing parent directory so the dialog at least opens in the right area.
    """
    if text:
        try:
            p = Path(text).expanduser()
            if p.exists():
                return str(p)
            for parent in p.parents:
                if parent.exists() and parent.is_dir():
                    return str(parent)
        except Exception:
            pass
    return default


def _log_widget() -> QTextEdit:
    log = QTextEdit()
    log.setReadOnly(True)
    log.setLineWrapMode(QTextEdit.WidgetWidth)
    log.setMinimumHeight(220)
    return log


# =============================================================================
# TAB 0 — PROJECT (MISSION COMMAND)
# =============================================================================

class _NotesEdit(QTextEdit):
    """QTextEdit that emits a `blurred` signal when focus is lost. Used by
    ProjectTab so notes commit to the project on blur instead of per keystroke.
    """
    blurred = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.blurred.emit()


class ProjectTab(QWidget):
    """Mission Command — project header (name / scope / notes), pipeline
    status dashboard across the three converter stages, and the project file
    lifecycle controls (New / Open / Save / Save As / Recent / Close).

    The tab is decoupled from MainWindow: it emits `request_focus_stage(key)`
    when the user clicks an Open ▸ button on a pipeline row; MainWindow maps
    the stage key to the right tab index.
    """

    request_focus_stage = Signal(str)   # one of STAGE_KEYS

    # -------------------------------------------------------------------------
    # CONSTRUCTION
    # -------------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self._suppress_emits = False   # block field-change handlers during apply_project
        self._status_rows: dict = {}
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Toolbar ---------------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._btn_new     = QPushButton("New…")
        self._btn_open    = QPushButton("Open…")
        self._btn_save    = QPushButton("Save")
        self._btn_save_as = QPushButton("Save As…")
        self._btn_close   = QPushButton("Close")
        self._btn_new.clicked.connect(self._on_new)
        self._btn_open.clicked.connect(self._on_open)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_save_as.clicked.connect(self._on_save_as)
        self._btn_close.clicked.connect(self._on_close)

        self._btn_recent = QToolButton()
        self._btn_recent.setText("Recent ▾")
        self._btn_recent.setPopupMode(QToolButton.InstantPopup)
        self._recent_menu = QMenu(self._btn_recent)
        self._btn_recent.setMenu(self._recent_menu)
        self._recent_menu.aboutToShow.connect(self._populate_recent_menu)

        for btn in (self._btn_new, self._btn_open, self._btn_save,
                    self._btn_save_as, self._btn_recent, self._btn_close):
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)

        # --- Stacked: populated panel vs empty-state card --------------------
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_populated_panel())   # index 0
        self._stack.addWidget(self._build_empty_panel())       # index 1
        root.addWidget(self._stack, 1)

    def _build_populated_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setSpacing(10)
        v.setContentsMargins(0, 0, 0, 0)

        # --- Header ----------------------------------------------------------
        hdr_box  = QGroupBox("Project")
        hdr_form = QFormLayout(hdr_box)
        hdr_form.setSpacing(6)

        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)

        self._scope_combo = QComboBox()
        for scope in ProjectScope:
            self._scope_combo.addItem(scope.display_name(), scope.value)
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)

        self._created_label  = QLabel("—")
        self._modified_label = QLabel("—")
        self._path_label     = QLabel("(unsaved)")
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color: #a6adc8;")

        hdr_form.addRow("Name:",     self._name_edit)
        hdr_form.addRow("Scope:",    self._scope_combo)
        hdr_form.addRow("Created:",  self._created_label)
        hdr_form.addRow("Modified:", self._modified_label)
        hdr_form.addRow("File:",     self._path_label)
        v.addWidget(hdr_box)

        # --- Notes -----------------------------------------------------------
        notes_box = QGroupBox("Notes")
        notes_lay = QVBoxLayout(notes_box)
        self._notes_edit = _NotesEdit()
        self._notes_edit.setPlaceholderText("Free-form notes about this conversion project…")
        self._notes_edit.setMaximumHeight(120)
        self._notes_edit.blurred.connect(self._on_notes_changed)
        notes_lay.addWidget(self._notes_edit)
        v.addWidget(notes_box)

        # --- Pipeline Status -------------------------------------------------
        status_box = QGroupBox("Pipeline Status")
        status_lay = QVBoxLayout(status_box)
        status_lay.setSpacing(4)
        for stage_key, label in (
            ("asset_processor",   "Prefab Processor"),
            ("scene_converter",   "Scene Converter"),
            ("terrain_processor", "Terrain Materials"),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("○")
            dot.setFixedWidth(14)
            dot.setStyleSheet("color: #6c7086;")
            stage_lbl = QLabel(label)
            stage_lbl.setMinimumWidth(140)
            summary = QLabel("never run")
            summary.setObjectName("status_ok")
            open_btn = QPushButton("Open ▸")
            open_btn.setFixedWidth(80)
            open_btn.clicked.connect(
                lambda _checked=False, k=stage_key: self.request_focus_stage.emit(k)
            )
            row.addWidget(dot)
            row.addWidget(stage_lbl)
            row.addWidget(summary, 1)
            row.addWidget(open_btn)
            status_lay.addLayout(row)
            self._status_rows[stage_key] = (dot, summary)
        v.addWidget(status_box)

        # --- Activity log ----------------------------------------------------
        v.addWidget(_section_label("Activity Log"))
        self._activity_log = _log_widget()
        self._activity_log.setMinimumHeight(120)
        v.addWidget(self._activity_log, 1)

        return panel

    def _build_empty_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setMaximumWidth(520)
        cv = QVBoxLayout(card)
        cv.setSpacing(8)
        cv.setContentsMargins(20, 20, 20, 20)

        title = QLabel("No project loaded")
        title.setObjectName("section")
        title.setAlignment(Qt.AlignCenter)
        info = QLabel(
            "Click <b>New…</b> to start a new Conversion Project, "
            "<b>Open…</b> to load an existing <code>.u2oproj.json</code>, "
            "or pick one from <b>Recent ▾</b>."
        )
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignCenter)
        cv.addWidget(title)
        cv.addWidget(info)

        lay.addStretch(1)
        lay.addWidget(card, 0, Qt.AlignCenter)
        lay.addStretch(1)
        return panel

    # -------------------------------------------------------------------------
    # APPLY PROJECT  (the project_changed → UI sync path)
    # -------------------------------------------------------------------------

    def apply_project(self, project) -> None:
        self._suppress_emits = True
        try:
            if project is None:
                self._stack.setCurrentIndex(1)
                self._btn_save.setEnabled(False)
                self._btn_save_as.setEnabled(False)
                self._btn_close.setEnabled(False)
                return

            self._stack.setCurrentIndex(0)
            self._btn_save.setEnabled(True)
            self._btn_save_as.setEnabled(True)
            self._btn_close.setEnabled(True)

            self._name_edit.setText(project.name)
            idx = self._scope_combo.findData(project.scope.value)
            self._scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._created_label.setText(project.created or "—")
            self._modified_label.setText(project.modified or "—")
            self._path_label.setText(str(project.path) if project.path else "(unsaved)")
            self._notes_edit.setPlainText(project.notes)
            for key in self._status_rows:
                self._refresh_status_row(key, project)
        finally:
            self._suppress_emits = False

    def _refresh_status_row(self, stage_key: str, project) -> None:
        dot, summary = self._status_rows[stage_key]
        status = project.pipeline_status.get(stage_key, {}) if project else {}

        if not status.get("last_run"):
            dot.setText("○")
            dot.setStyleSheet("color: #6c7086;")
            summary.setText("never run")
            return

        last_run = status.get("last_run", "")
        if stage_key == "asset_processor":
            text = (
                f"{last_run}   "
                f"{status.get('prefabs_processed', 0)}/{status.get('prefabs_total', 0)} prefabs, "
                f"{status.get('materials_written', 0)} mats, "
                f"{status.get('errors', 0)} errors"
            )
            error_count = status.get("errors", 0)
        elif stage_key == "scene_converter":
            text = (
                f"{last_run}   "
                f"{status.get('entities', 0)} entities, "
                f"{status.get('prefab_references', 0)} prefab refs, "
                f"{status.get('missing_prefabs', 0)} missing"
            )
            error_count = status.get("missing_prefabs", 0)
        else:  # terrain_processor
            text = (
                f"{last_run}   "
                f"{status.get('materials_written', 0)}/{status.get('materials_total', 0)} materials, "
                f"{status.get('textures_written', 0)} textures, "
                f"{status.get('errors', 0)} errors"
            )
            error_count = status.get("errors", 0)

        dot.setText("●")
        dot.setStyleSheet("color: #f9e2af;" if error_count else "color: #a6e3a1;")
        summary.setText(text)

    def _on_status_changed(self, stage_key: str) -> None:
        proj = project_manager().current()
        if proj is None or stage_key not in self._status_rows:
            return
        self._refresh_status_row(stage_key, proj)
        self._modified_label.setText(proj.modified)
        self._log_activity(f"{stage_key}: status updated")

    # -------------------------------------------------------------------------
    # TOOLBAR HANDLERS
    # -------------------------------------------------------------------------

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New Project", "Project name:", text="Untitled Project",
        )
        if not ok:
            return
        name = name.strip() or "Untitled Project"
        proj = project_manager().new_project(name)
        self._log_activity(f"Created new project: {proj.name}")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            f"Conversion Project (*{PROJECT_FILE_EXT});;All files (*.*)",
        )
        if not path:
            return
        try:
            project_manager().open(Path(path))
            self._log_activity(f"Opened: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Open failed", f"Could not open project:\n{e}")

    def _on_save(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        if proj.path is None:
            self._on_save_as()
            return
        try:
            pm.save()
            self._modified_label.setText(proj.modified)
            self._log_activity(f"Saved: {proj.path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_save_as(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        suggestion = (proj.path.name if proj.path
                      else f"{proj.name or 'Untitled'}{PROJECT_FILE_EXT}")
        start = str(proj.path) if proj.path else suggestion
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", start,
            f"Conversion Project (*{PROJECT_FILE_EXT})",
        )
        if not path:
            return
        try:
            pm.save_as(Path(path))
            self._path_label.setText(str(proj.path))
            self._modified_label.setText(proj.modified)
            self._log_activity(f"Saved as: {proj.path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_close(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        name = proj.name
        pm.close()
        self._log_activity(f"Closed: {name}")

    def _populate_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = project_manager().recent()
        if not recent:
            empty = QAction("(no recent projects)", self._recent_menu)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return
        for path in recent:
            label = path.name
            action = QAction(label, self._recent_menu)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self._open_recent(p))
            self._recent_menu.addAction(action)

    def _open_recent(self, path) -> None:
        try:
            project_manager().open(Path(path))
            self._log_activity(f"Opened from recent: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))

    # -------------------------------------------------------------------------
    # METADATA FIELD HANDLERS
    # -------------------------------------------------------------------------

    def _on_name_changed(self) -> None:
        if self._suppress_emits:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        proj.set_name(self._name_edit.text().strip() or "Untitled")
        pm.commit_metadata()
        self._modified_label.setText(proj.modified)

    def _on_scope_changed(self, idx: int) -> None:
        if self._suppress_emits:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        scope_value = self._scope_combo.itemData(idx)
        proj.set_scope(ProjectScope.from_string(scope_value))
        pm.commit_metadata()
        self._modified_label.setText(proj.modified)

    def _on_notes_changed(self) -> None:
        if self._suppress_emits:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        new_notes = self._notes_edit.toPlainText()
        if new_notes == proj.notes:
            return
        proj.set_notes(new_notes)
        pm.commit_metadata()
        self._modified_label.setText(proj.modified)

    # -------------------------------------------------------------------------
    # ACTIVITY LOG
    # -------------------------------------------------------------------------

    def _log_activity(self, msg: str) -> None:
        ts = _utc_now_iso()
        self._activity_log.append(f"[{ts}] {msg}")


# =============================================================================
# TAB 1 — PREFAB PROCESSOR
# =============================================================================

class PrefabProcessorTab(QWidget):
    """
    Drives IntegratedAssetProcessor. Reads + writes the active project's
    `stages.asset_processor` section via the ProjectManager.
    """

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread = None
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Source folder ---
        root.addWidget(_section_label("Unity Assets Folder"))
        self._source_edit, src_btn = _path_row("Select Unity project Assets folder…")
        src_btn.clicked.connect(self._browse_source)
        row = QHBoxLayout()
        row.addWidget(self._source_edit)
        row.addWidget(src_btn)
        root.addLayout(row)

        # --- Output folder ---
        root.addWidget(_section_label("O3DE Output Folder"))
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        row.addWidget(out_btn)
        root.addLayout(row)

        # --- Output structure info ---
        info = QGroupBox("Output Structure")
        info_layout = QVBoxLayout(info)
        info_layout.addWidget(QLabel(
            "  Prefabs/        — O3DE prefabs with material references\n"
            "  Materials/      — O3DE PBR materials (.material)\n"
            "  Textures/       — All textures consolidated\n"
            "  Meshes/         — FBX models with .assetinfo sub-mesh definitions\n"
            "  .ImporterData/  — Converter bookkeeping (entity maps, asset\n"
            "                    index, coverage report). Not read by O3DE."
        ))
        root.addWidget(info)

        # --- Log ---
        root.addWidget(_section_label("Processing Log"))
        self._log_edit = _log_widget()
        root.addWidget(self._log_edit, stretch=1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        btn_row.addWidget(save_log_btn)
        btn_row.addStretch()
        self._process_btn = QPushButton("Process Assets")
        self._process_btn.setObjectName("primary")
        self._process_btn.clicked.connect(self._start_processing)
        btn_row.addWidget(self._process_btn)
        root.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "asset_processor"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._source_edit.setText(cfg.get("source_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))

    def _collect_stage_settings(self) -> dict:
        return {
            "source_path": self._source_edit.text(),
            "output_path": self._output_edit.text(),
        }

    def _save_settings(self) -> None:
        """Field-edit hook: push current UI state into the active project."""
        pm = project_manager()
        if pm.current() is None:
            return
        pm.update_stage(self.STAGE_KEY, self._collect_stage_settings())

    # -------------------------------------------------------------------------
    # BROWSE HELPERS
    # -------------------------------------------------------------------------

    def _browse_source(self) -> None:
        start = _resolve_start_dir(self._source_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select Unity Assets Folder", start)
        if d:
            self._source_edit.setText(d)
            self._log(f"Source: {d}")
            self._save_settings()

    def _browse_output(self) -> None:
        start = _resolve_start_dir(self._output_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select O3DE Output Folder", start)
        if d:
            self._output_edit.setText(d)
            self._log(f"Output: {d}")
            self._save_settings()

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_edit.append(msg)
        self._log_edit.moveCursor(QTextCursor.End)

    def _save_log(self) -> None:
        # Suggest <output>/prefab_processor_log.txt when an output dir is set,
        # otherwise just the bare filename so Qt opens in its OS default.
        out_dir = _resolve_start_dir(self._output_edit.text().strip())
        suggestion = str(Path(out_dir) / "prefab_processor_log.txt") if out_dir else "prefab_processor_log.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Processing Log", suggestion,
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._log_edit.toPlainText())

    # -------------------------------------------------------------------------
    # PROCESSING
    # -------------------------------------------------------------------------

    def _start_processing(self) -> None:
        source = self._source_edit.text().strip()
        output = self._output_edit.text().strip()

        if not source or not output:
            QMessageBox.critical(self, "Error", "Please select both source and output folders.")
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Error", f"Source folder not found:\n{source}")
            return

        self._save_settings()
        self._process_btn.setEnabled(False)
        self._log_edit.clear()

        self._worker = WorkerThread(self._do_processing, source, output)
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_processing(self, source_path: str, output_path: str, log) -> str:
        from integrated_asset_processor import IntegratedAssetProcessor

        log("\n" + "=" * 60)
        log("STARTING ASSET PROCESSING")
        log("=" * 60)

        cfg = get_config()
        processor = IntegratedAssetProcessor(
            Path(source_path),
            Path(output_path),
            log_callback=log,
            convert_smoothness_to_roughness=cfg["convert_smoothness_to_roughness"],
        )

        prefab_files = list(Path(source_path).rglob('*.prefab'))
        log(f"\nFound {len(prefab_files)} Unity prefab(s) to process")

        success_count = 0
        for i, prefab_file in enumerate(prefab_files, 1):
            log(f"\n[{i}/{len(prefab_files)}] {prefab_file.name}")
            if processor.process_prefab(prefab_file):
                success_count += 1

        # Write coverage.json and asset_index.json into the output root.
        processor.finalize()

        # Merge asset-level counts into stats dict (displayed first)
        asset_stats = {
            "Materials created": len(processor.processed_materials),
            "Textures copied":   len(processor.processed_textures),
            "Meshes copied":     len(processor.processed_meshes),
        }
        asset_stats.update(processor.stats)

        log("\n" + "=" * 60)
        log("PROCESSING COMPLETE!")
        log("=" * 60)
        log(f"Prefabs processed : {success_count}/{len(prefab_files)}")
        for label, count in asset_stats.items():
            log(f"{label:<20}: {count}")
        log(f"Output            : {output_path}")
        log("=" * 60)

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":          _utc_now_iso(),
            "prefabs_processed": success_count,
            "prefabs_total":     len(prefab_files),
            "materials_written": len(processor.processed_materials),
            "textures_copied":   len(processor.processed_textures),
            "meshes_copied":     len(processor.processed_meshes),
            "errors":            max(0, len(prefab_files) - success_count),
        })

        summary_parts = [f"Prefabs: {success_count}/{len(prefab_files)}"]
        summary_parts += [f"{label}: {count}" for label, count in asset_stats.items()]
        return "  |  ".join(summary_parts)

    def _on_finished(self, success: bool, summary: str) -> None:
        self._process_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Processing Complete", summary)
        else:
            QMessageBox.critical(self, "Processing Failed", summary)


# =============================================================================
# TAB 2 — SCENE CONVERTER
# =============================================================================

class SceneConverterTab(QWidget):
    """
    Drives UnitySceneConverter.  Mirrors the fields from the old
    SceneConverterGUI (tkinter), loading/saving under the key
    "scene_converter" in converter_settings.json.
    """

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread = None
        self._prefab_dirs: list = []
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Scene file ---
        root.addWidget(_section_label("Unity Scene File (.unity)"))
        self._scene_edit, scene_btn = _path_row("Select Unity .unity scene file…")
        scene_btn.clicked.connect(self._browse_scene)
        row = QHBoxLayout()
        row.addWidget(self._scene_edit)
        row.addWidget(scene_btn)
        root.addLayout(row)

        # --- Output folder ---
        root.addWidget(_section_label("Output Destination"))
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        row.addWidget(out_btn)
        root.addLayout(row)

        # --- Prefab directories ---
        root.addWidget(_section_label("O3DE Prefab Asset Directories"))
        self._prefab_list = QListWidget()
        self._prefab_list.setMinimumHeight(100)
        self._prefab_list.setMaximumHeight(160)
        root.addWidget(self._prefab_list)

        dir_btn_row = QHBoxLayout()
        add_btn    = QPushButton("Add Directory")
        remove_btn = QPushButton("Remove Selected")
        clear_btn  = QPushButton("Clear All")
        add_btn.clicked.connect(self._add_prefab_directory)
        remove_btn.clicked.connect(self._remove_prefab_directory)
        clear_btn.clicked.connect(self._clear_prefab_directories)
        dir_btn_row.addWidget(add_btn)
        dir_btn_row.addWidget(remove_btn)
        dir_btn_row.addWidget(clear_btn)
        dir_btn_row.addStretch()
        root.addLayout(dir_btn_row)

        # --- Log ---
        root.addWidget(_section_label("Conversion Log"))
        self._log_edit = _log_widget()
        root.addWidget(self._log_edit, stretch=1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        btn_row.addWidget(save_log_btn)
        btn_row.addStretch()
        self._convert_btn = QPushButton("Convert Scene")
        self._convert_btn.setObjectName("primary")
        self._convert_btn.clicked.connect(self._start_conversion)
        btn_row.addWidget(self._convert_btn)
        root.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "scene_converter"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._scene_edit.setText(cfg.get("scene_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))
        self._prefab_dirs = []
        self._prefab_list.clear()
        for d in cfg.get("prefab_dirs", []):
            self._add_dir_to_list(d)

    def _collect_stage_settings(self) -> dict:
        return {
            "scene_path":  self._scene_edit.text(),
            "output_path": self._output_edit.text(),
            "prefab_dirs": list(self._prefab_dirs),
        }

    def _save_settings(self) -> None:
        pm = project_manager()
        if pm.current() is None:
            return
        pm.update_stage(self.STAGE_KEY, self._collect_stage_settings())

    # -------------------------------------------------------------------------
    # BROWSE HELPERS
    # -------------------------------------------------------------------------

    def _browse_scene(self) -> None:
        start = _resolve_start_path(self._scene_edit.text().strip())
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Unity Scene File", start,
            "Unity Scene (*.unity);;All files (*.*)"
        )
        if f:
            self._scene_edit.setText(f)
            self._save_settings()

    def _browse_output(self) -> None:
        start = _resolve_start_dir(self._output_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select Output Destination", start)
        if d:
            self._output_edit.setText(d)
            self._save_settings()

    # -------------------------------------------------------------------------
    # PREFAB DIRECTORY LIST
    # -------------------------------------------------------------------------

    def _add_prefab_directory(self) -> None:
        # Start the picker inside the last prefab dir if there is one,
        # else the output folder. Either is a sensible neighborhood.
        last_dir = self._prefab_dirs[-1] if self._prefab_dirs else ""
        start    = _resolve_start_dir(last_dir) or _resolve_start_dir(self._output_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select O3DE Prefab Directory", start)
        if d and d not in self._prefab_dirs:
            self._add_dir_to_list(d)
            self._save_settings()

    def _add_dir_to_list(self, path: str) -> None:
        self._prefab_dirs.append(path)
        self._prefab_list.addItem(QListWidgetItem(path))

    def _remove_prefab_directory(self) -> None:
        for item in self._prefab_list.selectedItems():
            row = self._prefab_list.row(item)
            self._prefab_list.takeItem(row)
            self._prefab_dirs.pop(row)
        self._save_settings()

    def _clear_prefab_directories(self) -> None:
        self._prefab_list.clear()
        self._prefab_dirs.clear()
        self._save_settings()

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_edit.append(msg)
        self._log_edit.moveCursor(QTextCursor.End)

    def _save_log(self) -> None:
        out_dir = _resolve_start_dir(self._output_edit.text().strip())
        suggestion = str(Path(out_dir) / "scene_converter_log.txt") if out_dir else "scene_converter_log.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Conversion Log", suggestion,
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._log_edit.toPlainText())

    # -------------------------------------------------------------------------
    # CONVERSION
    # -------------------------------------------------------------------------

    def _start_conversion(self) -> None:
        scene  = self._scene_edit.text().strip()
        output = self._output_edit.text().strip()

        if not scene or not output:
            QMessageBox.critical(self, "Error", "Please select a scene file and output folder.")
            return
        if not os.path.exists(scene):
            QMessageBox.critical(self, "Error", f"Scene file not found:\n{scene}")
            return
        if not self._prefab_dirs:
            QMessageBox.warning(self, "Warning",
                "No prefab directories added. Prefabs will not be resolved.")

        self._save_settings()
        self._convert_btn.setEnabled(False)
        self._log_edit.clear()

        self._worker = WorkerThread(
            self._do_conversion, scene, output, self._prefab_dirs[:]
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_conversion(self, scene_path: str, output_dir: str,
                       prefab_dirs: list, log) -> str:
        from unity_scene_converter_gui import PrefabDatabase, UnitySceneConverter

        log("\n" + "=" * 60)
        log("STARTING SCENE CONVERSION")
        log("=" * 60)
        log(f"Scene  : {Path(scene_path).name}")
        log(f"Output : {output_dir}")
        log(f"Prefab directories: {len(prefab_dirs)}")

        prefab_db = PrefabDatabase()
        for d in prefab_dirs:
            prefab_db.add_search_directory(Path(d))

        converter = UnitySceneConverter(prefab_db, log_callback=log)

        log("\nParsing Unity scene…")
        converter.parse_unity_scene(scene_path)
        log(f"Found {len(converter.game_objects)} GameObject(s)")

        prefab_instances = sum(
            1 for go in converter.game_objects.values() if go.is_prefab_instance
        )
        log(f"Prefab instances in scene : {prefab_instances}")
        log(f"Prefabs resolved          : {len(converter.prefab_references)}")

        if converter.missing_prefabs:
            log(f"\nMissing prefabs ({len(converter.missing_prefabs)}):")
            for name in sorted(converter.missing_prefabs):
                log(f"  ⚠ {name}")

        scene_name  = Path(scene_path).stem
        output_path = os.path.join(output_dir, f"{scene_name}.prefab")

        log(f"\nGenerating O3DE level: {scene_name}.prefab")
        total, prefab_refs, blanks = converter.create_o3de_level(
            output_path, Path(output_dir)
        )

        # Write coverage.json next to the level output.
        converter.finalize(Path(output_dir))

        log("\n" + "=" * 60)
        log("CONVERSION COMPLETE!")
        log("=" * 60)
        log(f"Total entities     : {total}")
        log(f"Prefab references  : {prefab_refs}")
        log(f"Blank entities     : {blanks}")
        log(f"Output             : {output_path}")
        log("=" * 60)

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":          _utc_now_iso(),
            "entities":          total,
            "prefab_references": prefab_refs,
            "blank_entities":    blanks,
            "missing_prefabs":   len(converter.missing_prefabs),
        })

        return f"Entities: {total}  |  Prefab refs: {prefab_refs}  |  Blanks: {blanks}"

    def _on_finished(self, success: bool, summary: str) -> None:
        self._convert_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Conversion Complete", summary)
        else:
            QMessageBox.critical(self, "Conversion Failed", summary)


# =============================================================================
# TAB 3 — TERRAIN
# =============================================================================

class TerrainTab(QWidget):
    """
    Converts a user-picked set of Unity .mat files into O3DE terrain detail
    materials (TerrainBaseMaterial materialtype). Settings persist under
    "terrain_processor" in converter_settings.json.

    Source folder is independent from the Prefab Processor tab so the user
    can import terrain materials from a different Unity project than the
    one feeding the prefab pipeline.
    """

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread = None
        self._selected_materials: list = []   # absolute paths to .mat files
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Source folder ---
        root.addWidget(_section_label("Unity Assets Folder"))
        self._source_edit, src_btn = _path_row(
            "Select Unity project Assets folder (used to resolve texture GUIDs)…"
        )
        src_btn.clicked.connect(self._browse_source)
        row = QHBoxLayout()
        row.addWidget(self._source_edit)
        row.addWidget(src_btn)
        root.addLayout(row)

        # --- Output folder ---
        root.addWidget(_section_label("O3DE Output Folder"))
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        row.addWidget(out_btn)
        root.addLayout(row)

        # --- Selected materials list ---
        root.addWidget(_section_label("Selected Unity Materials"))
        self._material_list = QListWidget()
        self._material_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._material_list.setMinimumHeight(120)
        self._material_list.setMaximumHeight(220)
        root.addWidget(self._material_list)

        mat_btn_row = QHBoxLayout()
        add_btn    = QPushButton("Add Materials…")
        remove_btn = QPushButton("Remove Selected")
        clear_btn  = QPushButton("Clear All")
        add_btn.clicked.connect(self._add_materials)
        remove_btn.clicked.connect(self._remove_selected_materials)
        clear_btn.clicked.connect(self._clear_materials)
        mat_btn_row.addWidget(add_btn)
        mat_btn_row.addWidget(remove_btn)
        mat_btn_row.addWidget(clear_btn)
        mat_btn_row.addStretch()
        root.addLayout(mat_btn_row)

        # --- Output structure info ---
        info = QGroupBox("Output Structure")
        info_layout = QVBoxLayout(info)
        info_layout.addWidget(QLabel(
            "  Terrain/Materials/  — O3DE .material files referencing\n"
            "                          @gemroot:Terrain@/Assets/Materials/Types/\n"
            "                          TerrainBaseMaterial.materialtype\n"
            "  Terrain/Textures/   — Textures referenced by the materials above"
        ))
        root.addWidget(info)

        # --- Log ---
        root.addWidget(_section_label("Processing Log"))
        self._log_edit = _log_widget()
        root.addWidget(self._log_edit, stretch=1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        btn_row.addWidget(save_log_btn)
        btn_row.addStretch()
        self._generate_btn = QPushButton("Generate Terrain Materials")
        self._generate_btn.setObjectName("primary")
        self._generate_btn.clicked.connect(self._start_generation)
        btn_row.addWidget(self._generate_btn)
        root.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "terrain_processor"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._source_edit.setText(cfg.get("source_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))
        self._selected_materials = []
        self._material_list.clear()
        for path in cfg.get("selected_materials", []):
            self._add_material_to_list(path)

    def _collect_stage_settings(self) -> dict:
        return {
            "source_path":        self._source_edit.text(),
            "output_path":        self._output_edit.text(),
            "selected_materials": list(self._selected_materials),
        }

    def _save_settings(self) -> None:
        pm = project_manager()
        if pm.current() is None:
            return
        pm.update_stage(self.STAGE_KEY, self._collect_stage_settings())

    # -------------------------------------------------------------------------
    # BROWSE / LIST HELPERS
    # -------------------------------------------------------------------------

    def _browse_source(self) -> None:
        start = _resolve_start_dir(self._source_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select Unity Assets Folder", start)
        if d:
            self._source_edit.setText(d)
            self._log(f"Source: {d}")
            self._save_settings()

    def _browse_output(self) -> None:
        start = _resolve_start_dir(self._output_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select O3DE Output Folder", start)
        if d:
            self._output_edit.setText(d)
            self._log(f"Output: {d}")
            self._save_settings()

    def _add_materials(self) -> None:
        # Start the picker inside the source folder when one is set so the
        # user doesn't have to navigate from scratch each time.
        start_dir = _resolve_start_dir(self._source_edit.text().strip())
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Unity Material Files", start_dir,
            "Unity Materials (*.mat);;All files (*.*)"
        )
        added = 0
        for p in paths:
            if p not in self._selected_materials:
                self._add_material_to_list(p)
                added += 1
        if added:
            self._log(f"Added {added} material(s); list now has {len(self._selected_materials)}.")
            self._save_settings()

    def _add_material_to_list(self, path: str) -> None:
        self._selected_materials.append(path)
        self._material_list.addItem(QListWidgetItem(path))

    def _remove_selected_materials(self) -> None:
        rows = sorted(
            (self._material_list.row(item) for item in self._material_list.selectedItems()),
            reverse=True,
        )
        for row in rows:
            self._material_list.takeItem(row)
            self._selected_materials.pop(row)
        if rows:
            self._save_settings()

    def _clear_materials(self) -> None:
        self._material_list.clear()
        self._selected_materials.clear()
        self._save_settings()

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_edit.append(msg)
        self._log_edit.moveCursor(QTextCursor.End)

    def _save_log(self) -> None:
        out_dir = _resolve_start_dir(self._output_edit.text().strip())
        suggestion = str(Path(out_dir) / "terrain_processor_log.txt") if out_dir else "terrain_processor_log.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Processing Log", suggestion,
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._log_edit.toPlainText())

    # -------------------------------------------------------------------------
    # GENERATION
    # -------------------------------------------------------------------------

    def _start_generation(self) -> None:
        source = self._source_edit.text().strip()
        output = self._output_edit.text().strip()

        if not source or not output:
            QMessageBox.critical(self, "Error",
                "Please select both the Unity Assets folder and an output folder.")
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Error", f"Source folder not found:\n{source}")
            return
        if not self._selected_materials:
            QMessageBox.warning(self, "Warning",
                "No materials selected. Add at least one .mat file to convert.")
            return

        self._save_settings()
        self._generate_btn.setEnabled(False)
        self._log_edit.clear()

        self._worker = WorkerThread(
            self._do_generation, source, output, list(self._selected_materials),
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_generation(self, source_path: str, output_path: str,
                       material_paths: list, log) -> str:
        from terrain_material_processor import TerrainMaterialProcessor

        log("\n" + "=" * 60)
        log("STARTING TERRAIN MATERIAL GENERATION")
        log("=" * 60)
        log(f"Source        : {source_path}")
        log(f"Output        : {output_path}")
        log(f"Materials in  : {len(material_paths)}")

        processor = TerrainMaterialProcessor(
            Path(source_path), Path(output_path), log_callback=log,
        )
        result = processor.process_materials([Path(p) for p in material_paths])

        log("\n" + "=" * 60)
        log("GENERATION COMPLETE!")
        log("=" * 60)
        log(f"Materials written : {result['materials_written']}/{len(material_paths)}")
        log(f"Textures written  : {result['textures_written']}")
        if result["errors"]:
            log(f"Errors ({len(result['errors'])}):")
            for err in result["errors"]:
                log(f"  ⚠ {err}")
        log("=" * 60)

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":          _utc_now_iso(),
            "materials_written": result["materials_written"],
            "materials_total":   len(material_paths),
            "textures_written":  result["textures_written"],
            "errors":            len(result["errors"]),
        })

        return (
            f"Materials: {result['materials_written']}/{len(material_paths)}  |  "
            f"Textures: {result['textures_written']}  |  "
            f"Errors: {len(result['errors'])}"
        )

    def _on_finished(self, success: bool, summary: str) -> None:
        self._generate_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Generation Complete", summary)
        else:
            QMessageBox.critical(self, "Generation Failed", summary)


# =============================================================================
# TAB 4 — CONFIG
# =============================================================================

def get_config() -> dict:
    """Return the persisted `config` section, with defaults filled in."""
    cfg = load_settings().get("config", {}) or {}
    return {
        "convert_smoothness_to_roughness":
            bool(cfg.get("convert_smoothness_to_roughness", False)),
    }


# =============================================================================
# DEPENDENCY PROBE
#
# The converter has three pip-installable dependencies. The Config tab probes
# each one at startup (and on refresh) and renders a platform-specific install
# command bound to this Python interpreter's `sys.executable`.  Using the full
# interpreter path defeats the "pip is from a different python than the one
# running the GUI" failure mode — `python -m pip` vs `pip` mismatches are the
# single most common install issue on Windows machines with multiple Pythons.
# =============================================================================

# (import_name, pypi_name, role_text, is_hard_dep)
DEPENDENCIES = [
    ("PySide6", "PySide6", "GUI framework",                              True),
    ("yaml",    "PyYAML",  "Unity prefab / scene YAML parser",           True),
    ("PIL",     "Pillow",  "Smoothness→Roughness texture re-bake",       False),
]


def _probe_dependency(import_name: str, pypi_name: str):
    """Return (installed: bool, version: Optional[str])."""
    import importlib.util
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        return (False, None)
    try:
        import importlib.metadata as md
        return (True, md.version(pypi_name))
    except Exception:
        return (True, None)


def _platform_label() -> str:
    if sys.platform.startswith("win"):  return "Windows"
    if sys.platform == "darwin":        return "macOS"
    return "Linux"


def _install_command(pypi_names: list) -> str:
    """Build a pip-install command bound to the running interpreter.

    Quoting `sys.executable` is important — Windows user-install paths usually
    contain spaces (AppData\\Local\\Programs\\...).  Single quotes on POSIX
    are safe against shells that treat double quotes specially.
    """
    pkgs = " ".join(pypi_names) if pypi_names else " ".join(d[1] for d in DEPENDENCIES)
    exe  = sys.executable
    if sys.platform.startswith("win"):
        return f'"{exe}" -m pip install {pkgs}'
    return f"'{exe}' -m pip install {pkgs}"


class ConfigTab(QWidget):
    """
    Per-run conversion options. Settings are persisted on toggle to
    `converter_settings.json` under the `config` key and read back by the
    Prefab Processor when a run is launched.
    """

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_settings()

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Material conversion group ---
        mat_group = QGroupBox("Material Conversion")
        ml        = QVBoxLayout(mat_group)

        self._cb_smooth_to_rough = QCheckBox("Convert Smoothness Textures to Roughness")
        self._cb_smooth_to_rough.setToolTip(
            "When enabled, any Unity '_MetallicGlossMap' bound as the roughness "
            "slot is re-baked with an inverted alpha channel and written as "
            "<name>_Roughness.png in Textures/. O3DE samples roughness directly "
            "from the bound texture, so without this step Unity smoothness maps "
            "appear inverted (smooth surfaces look rough). Requires Pillow."
        )
        self._cb_smooth_to_rough.toggled.connect(self._save_settings)
        ml.addWidget(self._cb_smooth_to_rough)
        root.addWidget(mat_group)

        # --- Dependencies group (platform-specific install commands) ---
        dep_group = QGroupBox(f"Dependencies — {_platform_label()}")
        dl        = QVBoxLayout(dep_group)

        # Show the interpreter path so the user can confirm which Python is
        # the install target. This is the single piece of info that explains
        # "pip installed it but the app can't see it" failures.
        dl.addWidget(QLabel("Python interpreter:"))
        py_edit = QLineEdit(sys.executable)
        py_edit.setReadOnly(True)
        py_edit.setStyleSheet("font-family: Consolas, monospace;")
        dl.addWidget(py_edit)

        # Per-dependency status, refreshed by _refresh_dep_status().
        self._dep_status_labels: dict = {}
        for import_name, pypi_name, role, is_hard in DEPENDENCIES:
            lbl = QLabel("")
            lbl.setWordWrap(True)
            self._dep_status_labels[pypi_name] = lbl
            dl.addWidget(lbl)

        dl.addSpacing(6)
        dl.addWidget(QLabel("Install command (binds to the interpreter above):"))
        self._install_cmd_edit = QLineEdit("")
        self._install_cmd_edit.setReadOnly(True)
        self._install_cmd_edit.setStyleSheet(
            "font-family: Consolas, monospace; color: #a6e3a1;"
        )
        dl.addWidget(self._install_cmd_edit)

        # Linux's system Python is usually PEP 668 externally-managed; warn
        # there specifically so users don't bang their head against pip refusing
        # to install. macOS Homebrew is similar but typical desktop users will
        # have used the Python installer from python.org so we skip the macOS warn.
        if sys.platform.startswith("linux"):
            hint = QLabel(
                "Note: on modern Linux distributions, the system Python may refuse "
                "this install (PEP 668). If you see 'externally-managed-environment', "
                "either add  --user  to the command, or create a venv first:  "
                "python3 -m venv .venv && source .venv/bin/activate"
            )
            hint.setObjectName("status_warn")
            hint.setWordWrap(True)
            dl.addWidget(hint)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copy command")
        self._copy_btn.clicked.connect(self._copy_install_cmd)
        btn_row.addWidget(self._copy_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Re-probe installed packages")
        self._refresh_btn.clicked.connect(self._refresh_dep_status)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch(1)
        dl.addLayout(btn_row)

        root.addWidget(dep_group)
        root.addStretch(1)

        # Populate the dep section now.
        self._refresh_dep_status()

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    def _load_settings(self) -> None:
        cfg = get_config()
        self._cb_smooth_to_rough.setChecked(cfg["convert_smoothness_to_roughness"])

    def _save_settings(self) -> None:
        save_settings({"config": {
            "convert_smoothness_to_roughness": self._cb_smooth_to_rough.isChecked(),
        }})

    # -------------------------------------------------------------------------
    # DEPENDENCY STATUS
    # -------------------------------------------------------------------------

    def _refresh_dep_status(self) -> None:
        """Re-probe each dependency, update labels, rebuild install command.

        The install command lists only the missing packages by default; when
        nothing is missing it falls back to the "install all" form so a fresh
        clone can copy a single line to bootstrap everything.

        Flushes Python's import caches first so a package installed via
        `pip install` AFTER the app started can be detected without an app
        restart. Without this, `find_spec` can return stale negative results.
        """
        import importlib
        importlib.invalidate_caches()

        missing: list = []
        for import_name, pypi_name, role, is_hard in DEPENDENCIES:
            installed, version = _probe_dependency(import_name, pypi_name)
            lbl = self._dep_status_labels[pypi_name]
            if installed:
                ver = version or "version unknown"
                lbl.setText(f"  ✓  {pypi_name} {ver} — {role}")
                lbl.setStyleSheet("color: #a6e3a1;")  # green
            else:
                tag = "required" if is_hard else "optional"
                lbl.setText(f"  ✗  {pypi_name} — {role}  ({tag}, not installed)")
                lbl.setStyleSheet("color: #f9e2af;")  # warn yellow
                missing.append(pypi_name)

        # Empty `missing` list → _install_command emits the full install line.
        self._install_cmd_edit.setText(_install_command(missing))

    def _copy_install_cmd(self) -> None:
        QApplication.clipboard().setText(self._install_cmd_edit.text())
        # Brief visual confirmation on the button.
        self._copy_btn.setText("Copied ✓")
        QTimer.singleShot(1200, lambda: self._copy_btn.setText("Copy command"))


# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    """
    Config is registered as a real tab (so the QTabWidget owns its page
    widget and lifetime) but hidden from the tab bar via setTabVisible(False).
    A "Config" QPushButton placed in the tab bar's top-right corner switches
    to it on click. This is the only QTabWidget pattern that gives genuine
    right-alignment regardless of window width — the corner widget is laid
    out by QTabWidget itself, not the tab bar.
    """

    # Stage-key → tab index, populated in __init__. Used by ProjectTab's
    # Open ▸ buttons to switch focus to the correct converter tab.
    _STAGE_TAB_INDEX: dict = {}

    def __init__(self, start_tab: int = 0):
        super().__init__()
        self.setWindowTitle("Unity → O3DE Converter")
        self.resize(820, 760)

        self._tabs = QTabWidget()
        project_tab = ProjectTab()
        self._tabs.addTab(project_tab,           "Project")           # 0
        prefab_idx  = self._tabs.addTab(PrefabProcessorTab(), "Prefab Processor")  # 1
        scene_idx   = self._tabs.addTab(SceneConverterTab(),  "Scene Converter")   # 2
        terrain_idx = self._tabs.addTab(TerrainTab(),         "Terrain")           # 3
        self._config_index = self._tabs.addTab(ConfigTab(), "Config")              # 4
        self._tabs.tabBar().setTabVisible(self._config_index, False)
        self._tabs.setCurrentIndex(start_tab)

        self._STAGE_TAB_INDEX = {
            "asset_processor":   prefab_idx,
            "scene_converter":   scene_idx,
            "terrain_processor": terrain_idx,
        }
        project_tab.request_focus_stage.connect(self._focus_stage)

        # Corner button: Config, pinned to the top-right of the tab bar.
        self._config_btn = QPushButton("Config")
        self._config_btn.setObjectName("config_corner")
        self._config_btn.setCheckable(True)
        self._config_btn.setCursor(Qt.PointingHandCursor)
        self._config_btn.setChecked(self._tabs.currentIndex() == self._config_index)
        self._config_btn.clicked.connect(
            lambda: self._tabs.setCurrentIndex(self._config_index)
        )
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.setCornerWidget(self._config_btn, Qt.TopRightCorner)

        self.setCentralWidget(self._tabs)

        # Window title binds to the active project's name.
        pm = project_manager()
        pm.project_changed.connect(self._update_title)
        self._update_title(pm.current())

    def _on_tab_changed(self, index: int) -> None:
        # Keep the corner button visually in sync with whether Config is active.
        self._config_btn.setChecked(index == self._config_index)

    def _focus_stage(self, stage_key: str) -> None:
        idx = self._STAGE_TAB_INDEX.get(stage_key)
        if idx is not None:
            self._tabs.setCurrentIndex(idx)

    def _update_title(self, project) -> None:
        if project is None:
            self.setWindowTitle("Unity → O3DE Converter — (no project)")
        else:
            self.setWindowTitle(f"Unity → O3DE Converter — {project.name}")

    # -------------------------------------------------------------------------
    # SAVE-ON-CLOSE
    #
    # All converter-tab field edits autosave through the project manager, so
    # the only dirty state that can survive to closeEvent is a brand-new
    # project that the user created but never saved (path is still None).
    # Prompt before discarding it.
    # -------------------------------------------------------------------------

    def closeEvent(self, event):
        pm = project_manager()
        proj = pm.current()
        if proj is None or not proj.is_dirty():
            event.accept()
            return

        reply = QMessageBox.question(
            self,
            "Unsaved project",
            f"Project '{proj.name}' has unsaved changes.\n\n"
            f"Save before closing?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Cancel:
            event.ignore()
            return

        if reply == QMessageBox.Yes:
            if proj.path is None:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save Project As",
                    f"{proj.name or 'Untitled'}{PROJECT_FILE_EXT}",
                    f"Conversion Project (*{PROJECT_FILE_EXT})",
                )
                if not path:
                    event.ignore()
                    return
                try:
                    pm.save_as(Path(path))
                except Exception as e:
                    QMessageBox.critical(self, "Save failed", str(e))
                    event.ignore()
                    return
            else:
                try:
                    pm.save()
                except Exception as e:
                    QMessageBox.critical(self, "Save failed", str(e))
                    event.ignore()
                    return

        event.accept()


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    # Determine which tab to open from --tab= argument
    tab_name_to_index = {
        "project": 0,
        "prefab":  1,
        "scene":   2,
        "terrain": 3,
    }
    start_tab = 0
    for arg in sys.argv[1:]:
        if arg.startswith('--tab='):
            val = arg.split('=', 1)[1].lower()
            start_tab = tab_name_to_index.get(val, 0)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(THEME_QSS)

    # Bootstrap the project system BEFORE constructing tabs so that the
    # initial apply_project(pm.current()) call in each tab's __init__ sees
    # the auto-loaded project.
    project_manager().bootstrap()

    window = MainWindow(start_tab=start_tab)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
