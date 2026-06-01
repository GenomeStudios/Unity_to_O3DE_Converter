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

import copy
import json
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore    import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui     import QFont, QTextCursor, QAction, QDoubleValidator, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QSizePolicy, QCheckBox,
    QComboBox, QToolButton, QMenu, QStackedWidget, QFrame,
    QFormLayout, QInputDialog, QScrollArea, QDialog, QDialogButtonBox,
)

from project_manager import (
    Project, SourceEngine, ProjectScope, ProjectManager, project_manager,
    PROJECT_FILE_EXT, STAGE_KEYS, _utc_now_iso,
    get_dismissed_dependency_signature, set_dismissed_dependency_signature,
    detect_externally_modified,
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

/* Dropdowns share the QLineEdit look — same surface colour, same border
   radius, same focus glow — plus a styled arrow and a dark popup so the
   list doesn't fall back to the host OS's system-default beige rendering. */
QComboBox {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
    padding: 5px 28px 5px 10px;       /* extra right pad clears the arrow */
    min-height: 22px;
    font-size: 10pt;
    selection-background-color: #89b4fa;
}
QComboBox:hover {
    border: 1px solid #585b70;
}
QComboBox:focus,
QComboBox:on {
    border: 1px solid #89b4fa;
}
QComboBox:disabled {
    background: #1e1e2e;
    color: #6c7086;
    border: 1px solid #313244;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #45475a;
    background: transparent;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #cdd6f4;
    margin-right: 8px;
}
QComboBox::down-arrow:disabled {
    border-top: 5px solid #6c7086;
}
QComboBox QAbstractItemView {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 0;
    outline: 0;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QComboBox QAbstractItemView::item {
    padding: 6px 12px;
    min-height: 22px;
}
QComboBox QAbstractItemView::item:hover {
    background: #45475a;
}
QComboBox QAbstractItemView::item:selected {
    background: #89b4fa;
    color: #1e1e2e;
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

/* Dependency banner — sits above the QTabWidget at the top of MainWindow. */
QFrame#dep_banner_warn {
    background: #2b2718;
    border-bottom: 1px solid #f9e2af;
}
QFrame#dep_banner_warn QLabel#dep_banner_msg {
    color: #f9e2af;
    font-weight: bold;
}
QFrame#dep_banner_error {
    background: #2b1a1d;
    border-bottom: 1px solid #f38ba8;
}
QFrame#dep_banner_error QLabel#dep_banner_msg {
    color: #f38ba8;
    font-weight: bold;
}
QPushButton#dep_banner_action {
    background: transparent;
    color: inherit;
    border: 1px solid currentColor;
    padding: 4px 12px;
    min-width: 0;
}
QPushButton#dep_banner_action:hover {
    background: rgba(255, 255, 255, 0.06);
}
QPushButton#dep_banner_dismiss {
    background: transparent;
    color: #a6adc8;
    border: none;
    padding: 4px 8px;
    min-width: 0;
}
QPushButton#dep_banner_dismiss:hover {
    color: #cdd6f4;
}

/* Custom title bar — replaces the native OS window chrome. */
QFrame#title_bar {
    background: #11111b;
    border-bottom: 1px solid #313244;
}
QFrame#title_bar QToolButton#file_menu_btn {
    background: transparent;
    color: #cdd6f4;
    padding: 4px 14px;
    border: none;
    font-weight: bold;
}
QFrame#title_bar QToolButton#file_menu_btn:hover {
    background: #313244;
}
QFrame#title_bar QPushButton#win_min,
QFrame#title_bar QPushButton#win_max,
QFrame#title_bar QPushButton#win_close {
    background: transparent;
    color: #cdd6f4;
    border: none;
    min-width: 46px;
    max-width: 46px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
    font-size: 11pt;
    border-radius: 0;
}
QFrame#title_bar QPushButton#win_min:hover,
QFrame#title_bar QPushButton#win_max:hover {
    background: #313244;
}
QFrame#title_bar QPushButton#win_close:hover {
    background: #f38ba8;
    color: #11111b;
}

/* Pipeline status cards on the Dashboard tab. Each stage is its own card
   with a banner row + requirement list + last-run line. */
QFrame#stage_status_card {
    background: #181826;
    border: 1px solid #313244;
    border-radius: 4px;
}
QLabel#stage_card_name {
    color: #cdd6f4;
    font-weight: bold;
    font-size: 11pt;
}
QLabel#stage_card_status {
    /* color set dynamically by update_state */
    font-weight: bold;
    font-size: 10pt;
}
QLabel#stage_card_req {
    /* color set dynamically per met/unmet */
    font-size: 9pt;
}
QLabel#stage_card_lastrun {
    color: #6c7086;
    font-size: 9pt;
    margin-top: 2px;
    border-top: 1px solid #313244;
    padding-top: 4px;
}
QPushButton#stage_card_open {
    background: transparent;
    color: #89b4fa;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 3px 12px;
    min-width: 64px;
}
QPushButton#stage_card_open:hover {
    background: #313244;
    border-color: #89b4fa;
}
QPushButton#stage_card_process {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 3px 14px;
    min-width: 70px;
    font-weight: bold;
}
QPushButton#stage_card_process:hover {
    background: #45475a;
    border-color: #89b4fa;
    color: #89b4fa;
}
QPushButton#stage_card_process:disabled {
    background: #232334;
    color: #6c7086;
    border-color: #313244;
}
QLabel#stage_card_sync {
    /* color set dynamically per sync state */
    font-size: 9pt;
    margin-top: 4px;
    padding-top: 4px;
}

/* Project header banner — top of MainWindow, below the title bar. */
QFrame#project_header_banner {
    background: #181826;
    border-bottom: 1px solid #45475a;
}
QFrame#project_header_banner QLabel#banner_project_name {
    color: #cdd6f4;
    font-weight: bold;
    font-size: 14pt;
}
QFrame#project_header_banner QLabel#banner_meta {
    color: #a6adc8;
}
QFrame#project_header_banner QLabel#banner_notes {
    color: #9399b2;
    font-size: 9pt;
}
QFrame#project_header_banner QPushButton#banner_edit,
QFrame#project_header_banner QPushButton#banner_save {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #585b70;
    border-radius: 4px;
    padding: 5px 18px;
    margin: 0 2px;
    min-width: 64px;
    font-weight: bold;
}
QFrame#project_header_banner QPushButton#banner_edit:hover,
QFrame#project_header_banner QPushButton#banner_save:hover {
    background: #45475a;
    border-color: #89b4fa;
    color: #89b4fa;
}
QFrame#project_header_banner QPushButton#banner_save {
    background: #89b4fa;
    color: #11111b;
    border-color: #89b4fa;
}
QFrame#project_header_banner QPushButton#banner_save:hover {
    background: #b4d0ff;
    color: #11111b;
}
QFrame#project_header_banner QToolButton {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 10px;
}
QFrame#project_header_banner QToolButton:hover {
    background: #45475a;
}
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


class PipelineOrchestrator(QObject):
    """F-8 — drives Run All across stages.

    Listens to `project_manager.processing_changed` to know when each
    per-stage worker finishes, then dispatches the next stage in the
    queue. Each stage uses its existing per-tab worker (set up by F-9);
    the orchestrator is glue, not a reimplementation.

    Stage queue is derived from the project's current selections:
      - asset_processor   if ≥1 prefab is selected
      - scene_converter   if ≥1 scene is selected
      - terrain_processor if ≥1 terrain is selected

    `dispatch_callable(stage_key)` is what actually fires the worker;
    MainWindow passes `_process_stage` so the same code path the
    Dashboard's per-stage Process buttons use is reused.
    """

    stage_started  = Signal(str)
    stage_finished = Signal(str)
    run_finished   = Signal(bool, str)   # success, summary
    log            = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue:    list = []
        self._current:  Optional[str] = None
        self._dispatch = None
        self._running  = False

    def is_running(self) -> bool:
        return self._running

    def cancel(self) -> None:
        """Best-effort cancel. The orchestrator stops dispatching new
        stages; the currently-running stage runs to completion. Mid-stage
        cancellation requires worker-level cooperation that the per-tab
        workers don't yet expose — that's a follow-up."""
        if not self._running:
            return
        if self._queue:
            self.log.emit(
                f"[orchestrator] Cancel — dropping {len(self._queue)} "
                f"queued stage(s); current stage will finish."
            )
            self._queue = []
        else:
            self.log.emit("[orchestrator] Cancel — current stage will finish.")

    def run_all(self, project, dispatch_callable) -> None:
        if self._running:
            self.log.emit("[orchestrator] already running — ignoring duplicate Run All")
            return
        self._queue = self._compute_queue(project)
        if not self._queue:
            self.run_finished.emit(False,
                                    "No stages have selections — nothing to run.")
            return
        self._dispatch = dispatch_callable
        self._running  = True
        pm = project_manager()
        # Connect once per run; we disconnect on completion to avoid
        # piling up handlers across multiple invocations.
        pm.processing_changed.connect(self._on_processing_changed)
        self.log.emit(
            f"[orchestrator] queue: {', '.join(self._queue)}"
        )
        self._advance()

    def _compute_queue(self, project) -> list:
        if project is None:
            return []
        q: list = []
        ap = project.stage_settings("asset_processor")
        if ap.get("selected_prefabs"):
            q.append("asset_processor")
        sc = project.stage_settings("scene_converter")
        if sc.get("selected_scenes"):
            q.append("scene_converter")
        tp = project.stage_settings("terrain_processor")
        if tp.get("selected_terrains"):
            q.append("terrain_processor")
        return q

    def _advance(self) -> None:
        if not self._queue:
            self._teardown(ok=True, summary="All stages completed.")
            return
        self._current = self._queue.pop(0)
        self.log.emit(f"[orchestrator] → starting {self._current}")
        self.stage_started.emit(self._current)
        try:
            self._dispatch(self._current)
        except Exception as exc:
            self.log.emit(f"[orchestrator] dispatch failed: {exc}")
            self._teardown(ok=False,
                            summary=f"Failed to dispatch {self._current}: {exc}")

    def _on_processing_changed(self, stage_key: str, is_processing: bool) -> None:
        if is_processing:
            return
        if stage_key != self._current:
            return
        self.log.emit(f"[orchestrator] ✓ {stage_key} finished")
        self.stage_finished.emit(stage_key)
        self._current = None
        self._advance()

    def _teardown(self, ok: bool, summary: str) -> None:
        pm = project_manager()
        try:
            pm.processing_changed.disconnect(self._on_processing_changed)
        except (TypeError, RuntimeError):
            pass
        self._running  = False
        self._current  = None
        self._dispatch = None
        self.run_finished.emit(ok, summary)


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


def _section_groupbox(title: str) -> tuple:
    """Return (QGroupBox, QVBoxLayout) preconfigured with symmetric margins
    and consistent internal spacing. The top margin is taller than the
    horizontal/bottom to clear the QGroupBox title text, but the bottom
    margin is large enough that content doesn't seam against the section
    frame."""
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 18, 12, 14)
    lay.setSpacing(8)
    return box, lay


def _hbox(*widgets, spacing: int = 8, trailing_stretch: bool = False) -> QHBoxLayout:
    """Convenience: a QHBoxLayout with the given spacing, the given widgets
    added in order, and an optional trailing stretch."""
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for w in widgets:
        row.addWidget(w)
    if trailing_stretch:
        row.addStretch(1)
    return row


def _bound_list_height(list_widget, *, min_h: int = 120, max_h: int = 200):
    """Constrain a QListWidget to [min_h, max_h] pixels and enable as-needed
    scrollbars so overflow scrolls internally. Crucially, sets the vertical
    sizePolicy to Maximum — the widget shrinks toward its minimum if space
    is tight but does NOT try to claim extra space beyond its sizeHint.
    Without this the list's default Expanding policy fights with sibling
    sections in the parent layout, sometimes overflowing past its frame."""
    list_widget.setMinimumHeight(min_h)
    list_widget.setMaximumHeight(max_h)
    list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    return list_widget


def _list_action_block(list_widget, *buttons,
                       min_h: int = 120, max_h: int = 200,
                       button_gap: int = 12) -> QVBoxLayout:
    """Compose a height-bounded scrollable list with a clearly separated
    row of management buttons beneath it. `button_gap` is the vertical
    distance between the list bottom and the button row top (default 12 px
    so the buttons read as a distinct row, not stacked against the list).
    Returns a QVBoxLayout to add into a section layout."""
    _bound_list_height(list_widget, min_h=min_h, max_h=max_h)
    lay = QVBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(list_widget)
    lay.addSpacing(button_gap)
    lay.addLayout(_hbox(*buttons, trailing_stretch=True))
    return lay


def _managed_list_section(title: str, list_widget, *buttons,
                          min_h: int = 120, max_h: int = 200) -> QGroupBox:
    """One-shot: a `_section_groupbox` containing a `_list_action_block`.
    Use whenever you need a titled section with a scrollable list and a
    row of management buttons. The list and buttons are visually separated
    so the row doesn't look stacked against the list."""
    box, lay = _section_groupbox(title)
    lay.addLayout(_list_action_block(list_widget, *buttons, min_h=min_h, max_h=max_h))
    return box


def _fill_section(title: str, widget) -> QGroupBox:
    """A `_section_groupbox` containing a single widget that stretches to
    fill the section's vertical space. Use for logs and other content that
    should occupy all the space below the section title."""
    box, lay = _section_groupbox(title)
    lay.addWidget(widget, 1)
    return box


def _scroll_wrap(content_widget: QWidget) -> QScrollArea:
    """Wrap a tab's content widget in a QScrollArea so the tab scrolls
    vertically when the content's preferred height exceeds the viewport.
    When the viewport IS tall enough, the content widget stretches to
    fill the viewport, so `stretch=1` items (e.g. logs) still expand.
    Use this on every converter tab to keep them legible when the window
    is smaller than the natural content height."""
    scroll = QScrollArea()
    scroll.setWidget(content_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    return scroll


# =============================================================================
# SCOPE SCRUBBING
#
# Walks a project's scope (or per-stage override) for files matching a glob
# pattern. Returns paths RELATIVE to the walking root so persisted selections
# stay portable when the scope root moves. F-3 uses this for `*.unity` scene
# scrubbing; F-4 will use it for `*.prefab` and `*.mat` inventories.
# =============================================================================

def scrub_scope_for(root_text: str, pattern: str) -> list:
    """Return sorted list of paths under `root_text` matching `pattern`,
    each relative to `root_text`. Empty / non-existent root → []."""
    if not root_text:
        return []
    try:
        root = Path(root_text)
        if not root.exists() or not root.is_dir():
            return []
    except Exception:
        return []
    return sorted(
        (p.relative_to(root) for p in root.rglob(pattern) if p.is_file()),
        key=lambda p: str(p).lower(),
    )


# =============================================================================
# DISMISSIBLE BANNER
#
# Top-of-window banner that surfaces missing-dependency state (and is built
# generic enough to host future warnings). Two severity levels via objectName;
# emits `open_config_clicked` for the primary action and `dismissed` for
# permanent hide.
# =============================================================================

class DismissibleBanner(QFrame):
    open_config_clicked = Signal()
    dismissed           = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self._icon = QLabel("⚠")
        self._icon.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self._msg = QLabel("")
        self._msg.setObjectName("dep_banner_msg")
        self._msg.setWordWrap(True)

        self._action_btn = QPushButton("Open Config →")
        self._action_btn.setObjectName("dep_banner_action")
        self._action_btn.setCursor(Qt.PointingHandCursor)
        self._action_btn.clicked.connect(self.open_config_clicked.emit)

        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.setObjectName("dep_banner_dismiss")
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.clicked.connect(self.dismissed.emit)

        layout.addWidget(self._icon)
        layout.addWidget(self._msg, 1)
        layout.addWidget(self._action_btn)
        layout.addWidget(self._dismiss_btn)

        self.hide()

    def show_state(self, severity: str, message: str) -> None:
        """severity is 'warning' or 'error'."""
        obj_name = "dep_banner_error" if severity == "error" else "dep_banner_warn"
        self.setObjectName(obj_name)
        # Force QSS re-evaluation after objectName change.
        self.style().unpolish(self)
        self.style().polish(self)
        self._msg.setText(message)
        self.show()

    def clear(self) -> None:
        self.hide()


# =============================================================================
# CUSTOM TITLE BAR
#
# Replaces the native OS window frame: File menu on the left, drag area in
# the middle, minimize/maximize/close on the right. Handles window drag via
# mouse events; double-click on the drag area toggles maximize.
# =============================================================================

class CustomTitleBar(QFrame):
    request_close            = Signal()
    request_minimize         = Signal()
    request_maximize_toggle  = Signal()

    GLYPH_MIN     = "–"          # –
    GLYPH_MAX     = "☐"          # ☐
    GLYPH_RESTORE = "⧉"          # ⧉
    GLYPH_CLOSE   = "✕"          # ✕

    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self.setObjectName("title_bar")
        self.setFixedHeight(32)
        self._parent_window = parent_window
        self._drag_offset   = None
        self._maximized     = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._file_btn = QToolButton()
        self._file_btn.setObjectName("file_menu_btn")
        self._file_btn.setText("File")
        self._file_btn.setPopupMode(QToolButton.InstantPopup)
        self._file_btn.setCursor(Qt.PointingHandCursor)
        outer.addWidget(self._file_btn)

        # Drag area — invisible widget that fills the middle of the title bar
        # and receives mouse events for window dragging / double-click max.
        self._drag_area = QWidget()
        self._drag_area.setObjectName("title_drag_area")
        self._drag_area.installEventFilter(self)
        outer.addWidget(self._drag_area, 1)

        self._min_btn   = self._make_caption_btn(self.GLYPH_MIN,   "win_min")
        self._max_btn   = self._make_caption_btn(self.GLYPH_MAX,   "win_max")
        self._close_btn = self._make_caption_btn(self.GLYPH_CLOSE, "win_close")
        self._min_btn.clicked.connect(self.request_minimize.emit)
        self._max_btn.clicked.connect(self.request_maximize_toggle.emit)
        self._close_btn.clicked.connect(self.request_close.emit)
        outer.addWidget(self._min_btn)
        outer.addWidget(self._max_btn)
        outer.addWidget(self._close_btn)

    def _make_caption_btn(self, glyph: str, object_name: str) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setObjectName(object_name)
        # Common QSS object name for sizing rules.
        btn.setProperty("class", "win_btn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    # ── Public API ───────────────────────────────────────────────────────────

    def set_file_menu(self, menu: QMenu) -> None:
        self._file_btn.setMenu(menu)

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = maximized
        self._max_btn.setText(self.GLYPH_RESTORE if maximized else self.GLYPH_MAX)

    # ── Event filter on the drag area ────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._drag_area:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.LeftButton:
                if self._parent_window is not None:
                    self._drag_offset = (
                        event.globalPosition().toPoint()
                        - self._parent_window.frameGeometry().topLeft()
                    )
                return True
            if event.type() == event.Type.MouseMove and event.buttons() & Qt.LeftButton:
                if self._drag_offset is not None and self._parent_window is not None:
                    if self._parent_window.isMaximized():
                        # Restore first, recompute offset so cursor stays in-bounds.
                        ratio = event.position().x() / max(1, self._drag_area.width())
                        self._parent_window.showNormal()
                        new_w = self._parent_window.width()
                        self._drag_offset = type(self._drag_offset)(int(new_w * ratio), 8)
                    self._parent_window.move(
                        event.globalPosition().toPoint() - self._drag_offset
                    )
                return True
            if event.type() == event.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
            if event.type() == event.Type.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.request_maximize_toggle.emit()
                return True
        return super().eventFilter(obj, event)


# =============================================================================
# PROJECT HEADER BANNER
#
# Persistent top-of-window project header. Two modes:
#   compact  — name + scope + root-basename row, notes row, menu + edit btns
#   expanded — full editable form (name, scope, scope_root, notes, dates, file)
# Toggle via Edit / Collapse button. Project ▾ button pops up the file menu
# (New / Open / Save / Save As / Recent / Close).
# =============================================================================

class _NotesEdit(QTextEdit):
    """QTextEdit that emits `blurred` on focus loss — used by the project
    header so notes commit to the model on blur, not per-keystroke."""
    blurred = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.blurred.emit()


class ProjectHeaderBanner(QFrame):
    """Top banner showing the active project's header. Replaces the in-tab
    project header that used to live on the Project tab. Holds the Project
    menu (file ops) as well, so file commands stay reachable when no project
    is loaded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("project_header_banner")
        self._suppress_emits = False
        self._build_ui()

        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Show/hide on sibling widgets — NOT a QStackedWidget — so the banner
        # collapses to the compact panel's size instead of reserving expanded
        # panel height.
        self._compact_panel  = self._build_compact()
        self._expanded_panel = self._build_expanded()
        self._expanded_panel.hide()
        outer.addWidget(self._compact_panel)
        outer.addWidget(self._expanded_panel)

        # The project menu lives here (handlers + actions are class members)
        # but is hosted in the title bar's File button. MainWindow fetches it
        # via project_menu() and hands it to CustomTitleBar.set_file_menu().
        self._project_menu = QMenu(self)
        self._build_project_menu(self._project_menu)

    def _build_compact(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 8, 14, 8)
        v.setSpacing(2)

        # Row 1: large project name only.
        self._name_label = QLabel("(no project loaded)")
        self._name_label.setObjectName("banner_project_name")
        v.addWidget(self._name_label)

        # Row 2: notes summary (single-line, ellipsised) + Edit button.
        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        info_row.setContentsMargins(0, 0, 0, 0)

        self._notes_label = QLabel("(no notes)")
        self._notes_label.setObjectName("banner_notes")
        self._notes_label.setWordWrap(False)
        self._notes_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_row.addWidget(self._notes_label, 1)

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("banner_edit")
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.clicked.connect(self._toggle_expanded)
        info_row.addWidget(self._edit_btn)
        v.addLayout(info_row)

        # Stub attributes the previous design used. apply_project still tries
        # to address them, so keep no-op QLabels (off-screen, never added to
        # the layout) to preserve the existing apply_project flow without
        # forking the implementation. Future cleanup could prune apply_project
        # to drop these lookups.
        self._scope_label = QLabel("")
        self._root_label  = QLabel("")

        return w

    def _build_expanded(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._on_name_changed)

        self._scope_combo = QComboBox()
        for engine in SourceEngine:
            self._scope_combo.addItem(engine.display_name(), engine.value)
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)

        self._scope_root_edit, root_browse_btn = _path_row(
            "Unity assets walking root (blank = no scope set)"
        )
        self._scope_root_edit.editingFinished.connect(self._on_scope_root_changed)
        root_browse_btn.clicked.connect(self._browse_scope_root)
        root_row = QHBoxLayout()
        root_row.addWidget(self._scope_root_edit)
        root_row.addWidget(root_browse_btn)
        root_row.setContentsMargins(0, 0, 0, 0)
        root_wrap = QWidget()
        root_wrap.setLayout(root_row)
        self._scope_root_status = QLabel("")
        self._scope_root_status.setStyleSheet("color: #6c7086; font-size: 9pt;")

        self._notes_edit = _NotesEdit()
        self._notes_edit.setPlaceholderText("Free-form notes about this conversion project…")
        self._notes_edit.setMaximumHeight(80)
        self._notes_edit.blurred.connect(self._on_notes_changed)

        self._created_lbl  = QLabel("—")
        self._modified_lbl = QLabel("—")
        self._file_lbl     = QLabel("(unsaved)")
        self._file_lbl.setWordWrap(True)
        self._file_lbl.setStyleSheet("color: #a6adc8;")

        form.addRow("Name:",          self._name_edit)
        form.addRow("Source Engine:", self._scope_combo)
        form.addRow("Source Root:",   root_wrap)
        form.addRow("",             self._scope_root_status)
        form.addRow("Notes:",       self._notes_edit)
        form.addRow("Created:",     self._created_lbl)
        form.addRow("Modified:",    self._modified_lbl)
        form.addRow("File:",        self._file_lbl)
        v.addLayout(form)

        # Phase E — transient toast for platform-switch confirmation.
        # Hidden by default; populated + revealed by `_show_platform_switch_toast`
        # on engine change; auto-cleared by `_switch_toast_timer` after 4s.
        self._switch_toast = QLabel("")
        self._switch_toast.setObjectName("platform_switch_toast")
        self._switch_toast.setStyleSheet(
            "background: #313244; color: #a6e3a1; padding: 6px 10px; "
            "border: 1px solid #45475a; border-radius: 4px; font-size: 9pt;"
        )
        self._switch_toast.setWordWrap(True)
        self._switch_toast.setVisible(False)
        v.addWidget(self._switch_toast)
        self._switch_toast_timer = QTimer(self)
        self._switch_toast_timer.setSingleShot(True)
        self._switch_toast_timer.timeout.connect(self._hide_platform_switch_toast)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 4, 0, 0)
        bottom.addStretch(1)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("banner_save")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save_clicked)
        bottom.addWidget(self._save_btn)
        v.addLayout(bottom)

        return w

    def _on_save_clicked(self) -> None:
        """Save button on the expanded form: persist any pending changes,
        then collapse back to the compact view."""
        pm = project_manager()
        proj = pm.current()
        if proj is not None and proj.path is not None:
            try:
                pm.save()
            except Exception as e:
                QMessageBox.critical(self, "Save failed", str(e))
                return
        # Collapse the form (toggles to compact since expanded is showing).
        self._toggle_expanded()

    def _build_project_menu(self, menu: QMenu) -> None:
        self._act_new = QAction("New…", menu)
        self._act_new.setShortcut("Ctrl+N")
        self._act_new.triggered.connect(self._on_new)
        menu.addAction(self._act_new)

        self._act_open = QAction("Open…", menu)
        self._act_open.setShortcut("Ctrl+O")
        self._act_open.triggered.connect(self._on_open)
        menu.addAction(self._act_open)

        self._act_save = QAction("Save", menu)
        self._act_save.setShortcut("Ctrl+S")
        self._act_save.triggered.connect(self._on_save)
        menu.addAction(self._act_save)

        self._act_save_as = QAction("Save As…", menu)
        self._act_save_as.setShortcut("Ctrl+Shift+S")
        self._act_save_as.triggered.connect(self._on_save_as)
        menu.addAction(self._act_save_as)

        menu.addSeparator()

        self._recent_submenu = QMenu("Recent", menu)
        menu.addMenu(self._recent_submenu)
        self._recent_submenu.aboutToShow.connect(self._populate_recent_submenu)

        menu.addSeparator()

        self._act_close = QAction("Close", menu)
        self._act_close.triggered.connect(self._on_close)
        menu.addAction(self._act_close)

    # -------------------------------------------------------------------------
    # MODE TOGGLE
    # -------------------------------------------------------------------------

    def _toggle_expanded(self) -> None:
        # Use isHidden() (explicit-hidden flag) instead of isVisible()
        # (parent-chain dependent). isVisible() is False for both panels
        # before the window has been shown, which would make the toggle a
        # no-op on the first click — a real bug not just a test artifact.
        going_expanded = not self._compact_panel.isHidden()
        self._compact_panel.setVisible(not going_expanded)
        self._expanded_panel.setVisible(going_expanded)
        if going_expanded:
            # Sync form fields for the case where the user opens Edit
            # without a project_changed in between.
            self.apply_project(project_manager().current())

    def project_menu(self) -> QMenu:
        """Return the populated QMenu the title bar should host."""
        return self._project_menu

    # -------------------------------------------------------------------------
    # APPLY PROJECT — refresh compact + expanded views from the model
    # -------------------------------------------------------------------------

    def apply_project(self, project) -> None:
        self._suppress_emits = True
        try:
            has_project = project is not None
            self._edit_btn.setEnabled(has_project)
            self._act_save.setEnabled(has_project)
            self._act_save_as.setEnabled(has_project)
            self._act_close.setEnabled(has_project)

            # Compact row 1
            self._name_label.setText(project.name if has_project else "(no project loaded)")
            self._scope_label.setText(project.source_engine.display_name() if has_project else "")
            root_basename = self._root_basename(project) if has_project else ""
            self._root_label.setText(root_basename)
            self._root_label.setToolTip(str(project.scope_root) if (has_project and project.scope_root) else "")

            # Compact row 2 (notes)
            if has_project:
                notes = (project.notes or "").strip()
                if notes:
                    single = notes.splitlines()[0]
                    self._notes_label.setText(single)
                    self._notes_label.setToolTip(notes)
                else:
                    self._notes_label.setText("(no notes)")
                    self._notes_label.setToolTip("")
            else:
                self._notes_label.setText("Use File menu to open or create a project.")
                self._notes_label.setToolTip("")

            # Expanded form
            if has_project:
                self._name_edit.setText(project.name)
                idx = self._scope_combo.findData(project.source_engine.value)
                self._scope_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self._scope_root_edit.setText(str(project.scope_root) if project.scope_root else "")
                self._refresh_scope_root_status(project)
                self._notes_edit.setPlainText(project.notes)
                self._created_lbl.setText(project.created or "—")
                self._modified_lbl.setText(project.modified or "—")
                self._file_lbl.setText(str(project.path) if project.path else "(unsaved)")
            else:
                # Force collapse when no project loaded.
                if not self._expanded_panel.isHidden():
                    self._expanded_panel.hide()
                    self._compact_panel.show()
        finally:
            self._suppress_emits = False

    @staticmethod
    def _root_basename(project) -> str:
        if not project.scope_root:
            return "(no source)"
        try:
            return Path(project.scope_root).name or str(project.scope_root)
        except Exception:
            return "(invalid source)"

    def _refresh_scope_root_status(self, project) -> None:
        if project is None or not project.scope_root:
            self._scope_root_status.setText(
                "(unset — each stage will need its own source path)"
            )
            self._scope_root_status.setStyleSheet("color: #f9e2af; font-size: 9pt;")
            return
        if not Path(project.scope_root).exists():
            self._scope_root_status.setText(
                f"(path does not exist: {project.scope_root})"
            )
            self._scope_root_status.setStyleSheet("color: #f38ba8; font-size: 9pt;")
            return
        self._scope_root_status.setText("(stages with blank source will walk this root)")
        self._scope_root_status.setStyleSheet("color: #a6e3a1; font-size: 9pt;")

    # -------------------------------------------------------------------------
    # FORM-FIELD HANDLERS
    # -------------------------------------------------------------------------

    def _on_name_changed(self) -> None:
        if self._suppress_emits: return
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        proj.set_name(self._name_edit.text().strip() or "Untitled")
        pm.commit_metadata()

    def _on_scope_changed(self, idx: int) -> None:
        if self._suppress_emits: return
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        value = self._scope_combo.itemData(idx)
        new_engine = SourceEngine.from_string(value)
        old_active = proj.active_platform
        # Phase E — record a snapshot of the old platform's selections so
        # the log entry can quantify "non-destructive". The switch happens
        # via set_source_engine which is destructive at the active-slot
        # level (live views rebind) but not at the data level (the old
        # slot stays in stages_by_platform).
        old_summary = self._platform_summary(proj, old_active)
        proj.set_source_engine(new_engine)
        pm.commit_metadata()
        # Visible confirmation. Both surfaces:
        #   1. Transient toast on the banner (auto-clears after ~4s).
        #   2. Detailed entry on the Dashboard activity log.
        new_summary = self._platform_summary(proj, proj.active_platform)
        self._show_platform_switch_toast(old_active, proj.active_platform,
                                          old_summary)
        self._log_platform_switch(old_active, proj.active_platform,
                                   old_summary, new_summary)

    @staticmethod
    def _platform_summary(proj, plat_name: str) -> dict:
        """Snapshot the per-platform stages for log/toast context."""
        stages = (proj.stages_by_platform.get(plat_name) or {})
        ap = stages.get("asset_processor") or {}
        sc = stages.get("scene_converter") or {}
        mp = stages.get("material_processor") or {}
        return {
            "prefabs":   len(ap.get("selected_prefabs") or []),
            "scenes":    len(sc.get("selected_scenes")  or []),
            "overrides": len((mp.get("overrides") or {})),
        }

    def _show_platform_switch_toast(self, old: str, new: str,
                                     old_summary: dict) -> None:
        """Brief inline label on the banner — auto-clears via a QTimer.
        Lives in the toast slot so multiple rapid switches don't stack."""
        if not hasattr(self, "_switch_toast"):
            return
        msg = (f"  Switched to {new.capitalize()} — "
               f"{old.capitalize()} data preserved "
               f"({old_summary['prefabs']} prefab(s), "
               f"{old_summary['scenes']} scene(s), "
               f"{old_summary['overrides']} override(s))")
        self._switch_toast.setText(msg)
        self._switch_toast.setVisible(True)
        if hasattr(self, "_switch_toast_timer"):
            self._switch_toast_timer.stop()
            self._switch_toast_timer.start(4000)

    def _hide_platform_switch_toast(self) -> None:
        if hasattr(self, "_switch_toast"):
            self._switch_toast.setVisible(False)

    @staticmethod
    def _log_platform_switch(old: str, new: str,
                              old_summary: dict, new_summary: dict) -> None:
        """Append a switch entry to the Dashboard's activity log.

        Reaches the dashboard through MainWindow's `_log_to_dashboard`
        helper if it's available; falls back to print() when running
        headless (tests, smoke scripts)."""
        msg = (
            f"[Engine] Switched source engine: {old} -> {new}. "
            f"Non-destructive — {old} slot kept "
            f"({old_summary['prefabs']} prefab(s), "
            f"{old_summary['scenes']} scene(s), "
            f"{old_summary['overrides']} override(s)). "
            f"{new} slot loaded "
            f"({new_summary['prefabs']} prefab(s), "
            f"{new_summary['scenes']} scene(s), "
            f"{new_summary['overrides']} override(s))."
        )
        # Try to reach the Dashboard log. The window lives on
        # QApplication.activeWindow() / the singleton in main_app; safest
        # fallback is to walk MainWindow if it's been constructed.
        try:
            app = QApplication.instance()
            for w in (app.topLevelWidgets() if app else []):
                log_fn = getattr(w, "_log_to_dashboard", None)
                if callable(log_fn):
                    log_fn(msg)
                    return
        except Exception:
            pass
        print(msg)

    def _on_scope_root_changed(self) -> None:
        if self._suppress_emits: return
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        text = self._scope_root_edit.text().strip()
        new_root = Path(text) if text else None
        if new_root == proj.scope_root: return
        proj.set_scope_root(new_root)
        pm.commit_metadata()

    def _browse_scope_root(self) -> None:
        start = _resolve_start_dir(self._scope_root_edit.text().strip())
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Unity assets walking root", start,
        )
        if chosen:
            self._scope_root_edit.setText(chosen)
            self._on_scope_root_changed()

    def _on_notes_changed(self) -> None:
        if self._suppress_emits: return
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        new_notes = self._notes_edit.toPlainText()
        if new_notes == proj.notes: return
        proj.set_notes(new_notes)
        pm.commit_metadata()

    # -------------------------------------------------------------------------
    # PROJECT MENU HANDLERS
    # -------------------------------------------------------------------------

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New Project", "Project name:", text="Untitled Project",
        )
        if not ok: return
        project_manager().new_project(name.strip() or "Untitled Project")

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "",
            f"Conversion Project (*{PROJECT_FILE_EXT});;All files (*.*)",
        )
        if not path: return
        try:
            project_manager().open(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Open failed", f"Could not open project:\n{e}")

    def _on_save(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        if proj.path is None:
            self._on_save_as()
            return
        try:
            pm.save()
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_save_as(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None: return
        suggestion = (proj.path.name if proj.path
                      else f"{proj.name or 'Untitled'}{PROJECT_FILE_EXT}")
        start = str(proj.path) if proj.path else suggestion
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", start,
            f"Conversion Project (*{PROJECT_FILE_EXT})",
        )
        if not path: return
        try:
            pm.save_as(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _on_close(self) -> None:
        pm = project_manager()
        if pm.current() is None: return
        pm.close()

    def _populate_recent_submenu(self) -> None:
        self._recent_submenu.clear()
        recent = project_manager().recent()
        if not recent:
            empty = QAction("(no recent projects)", self._recent_submenu)
            empty.setEnabled(False)
            self._recent_submenu.addAction(empty)
            return
        for path in recent:
            action = QAction(path.name, self._recent_submenu)
            action.setToolTip(str(path))
            action.triggered.connect(lambda _checked=False, p=path: self._open_recent(p))
            self._recent_submenu.addAction(action)

    def _open_recent(self, path) -> None:
        try:
            project_manager().open(Path(path))
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))


# =============================================================================
# TAB 0 — DASHBOARD
#
# Dependency banner + pipeline readiness + activity log. Project header and
# file ops live in `ProjectHeaderBanner` at the window level — not on this
# tab anymore.
# =============================================================================

# Status-badge color map for `StageStatusCard`. Driven by the `status` key
# returned by `compute_stage_readiness`.
_STAGE_STATUS_COLORS = {
    "unset":      "#6c7086",  # grey  — no project loaded
    "incomplete": "#f9e2af",  # yellow — at least one requirement unmet
    "ready":      "#89dceb",  # sapphire — all requirements met, awaiting run
    "ok":         "#a6e3a1",  # green — last run clean
    "warn":       "#fab387",  # orange — last run had warnings/errors
    "error":      "#f38ba8",  # red — critical config problem (e.g. source has no assets)
}

# Green/red colors for individual requirement rows inside a card.
_REQ_MET_COLOR     = "#a6e3a1"  # Catppuccin green
_REQ_NOT_MET_COLOR = "#f38ba8"  # Catppuccin red


class StageStatusCard(QFrame):
    """One pipeline stage's status card. Banner row at the top with the
    stage name + overall readiness status + Process + Open ▸ buttons;
    a colored requirement list below (each row red if unmet, green if
    met); an optional last-run summary; and at the bottom a sync-state
    row showing how the outputs relate to current settings.

    Generic over stage — `update_state(readiness, sync_state)` takes the
    dicts returned by `compute_stage_readiness` and
    `compute_stage_sync_state`."""

    open_clicked    = Signal()
    process_clicked = Signal()

    def __init__(self, stage_name: str, *, action_label: str = "Process"):
        super().__init__()
        self.setObjectName("stage_status_card")
        # Empty action_label hides the button entirely — used for stages
        # whose status card has no meaningful one-shot action (or whose
        # action label flips dynamically via ``set_action_label``).
        self._action_label_default = action_label

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(6)

        # --- Banner row: name + status + <action> + Open ▸ -----------------
        banner = QHBoxLayout()
        banner.setSpacing(10)
        self._name_label = QLabel(stage_name)
        self._name_label.setObjectName("stage_card_name")
        banner.addWidget(self._name_label)
        self._status_label = QLabel("")
        self._status_label.setObjectName("stage_card_status")
        banner.addWidget(self._status_label)
        banner.addStretch(1)
        self._process_btn = QPushButton(action_label or "Process")
        self._process_btn.setObjectName("stage_card_process")
        self._process_btn.setCursor(Qt.PointingHandCursor)
        self._process_btn.clicked.connect(self.process_clicked.emit)
        self._process_btn.setVisible(bool(action_label))
        banner.addWidget(self._process_btn)
        self._open_btn = QPushButton("Open ▸")
        self._open_btn.setObjectName("stage_card_open")
        self._open_btn.setCursor(Qt.PointingHandCursor)
        self._open_btn.clicked.connect(self.open_clicked.emit)
        banner.addWidget(self._open_btn)
        outer.addLayout(banner)

        # --- Requirements container (rebuilt on each update_state) ---------
        self._reqs_box = QWidget()
        self._reqs_lay = QVBoxLayout(self._reqs_box)
        self._reqs_lay.setSpacing(3)
        self._reqs_lay.setContentsMargins(20, 2, 0, 0)
        outer.addWidget(self._reqs_box)

        # --- Last-run line (hidden when no run) ----------------------------
        self._last_run_label = QLabel("")
        self._last_run_label.setObjectName("stage_card_lastrun")
        self._last_run_label.setWordWrap(True)
        self._last_run_label.setVisible(False)
        outer.addWidget(self._last_run_label)

        # --- Sync-state row at the bottom ----------------------------------
        self._sync_label = QLabel("")
        self._sync_label.setObjectName("stage_card_sync")
        self._sync_label.setWordWrap(True)
        outer.addWidget(self._sync_label)

    def update_state(self, readiness: dict, sync_state: dict) -> None:
        """Repaint the card from the readiness + sync_state dicts."""
        # Readiness status badge in the banner.
        status = readiness.get("status", "unset")
        self._status_label.setText(readiness.get("status_label", ""))
        rcolor = _STAGE_STATUS_COLORS.get(status, _STAGE_STATUS_COLORS["unset"])
        self._status_label.setStyleSheet(
            f"color: {rcolor}; font-weight: bold; font-size: 10pt;"
        )

        # Rebuild the requirements list.
        while self._reqs_lay.count():
            item = self._reqs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for req in readiness.get("requirements", []):
            glyph = "✓" if req["met"] else "✗"
            if req["met"]:
                color = _REQ_MET_COLOR
            elif req.get("severity") == "error":
                color = "#f38ba8"   # red — critical config problem
            else:
                color = _REQ_NOT_MET_COLOR
            label = QLabel(f"{glyph}  {req['text']}")
            label.setObjectName("stage_card_req")
            weight = "font-weight: bold;" if req.get("severity") == "error" else ""
            label.setStyleSheet(f"color: {color}; font-size: 9pt; {weight}")
            label.setWordWrap(True)
            self._reqs_lay.addWidget(label)

        # Advisories (soft warnings) — render below requirements with a
        # warning icon. Don't affect readiness status; visible only.
        for advisory in readiness.get("advisories", []):
            label = QLabel(f"⚠  {advisory['text']}")
            label.setObjectName("stage_card_advisory")
            label.setStyleSheet("color: #fab387; font-size: 9pt;")
            label.setWordWrap(True)
            self._reqs_lay.addWidget(label)

        # Last-run summary line.
        lrs = readiness.get("last_run")
        if lrs:
            self._last_run_label.setText(lrs)
            self._last_run_label.setVisible(True)
        else:
            self._last_run_label.setText("")
            self._last_run_label.setVisible(False)

        # Sync-state row + Process button enable state.
        sstate = sync_state.get("state", "unconfigured")
        scolor = _SYNC_STATE_COLORS.get(sstate, _SYNC_STATE_COLORS["unconfigured"])
        glyph = {
            "unconfigured": "○",
            "ready":        "◐",
            "synchronized": "●",
            "unsynchronized": "◑",
            "writing":      "↻",
            "error":        "✕",
        }.get(sstate, "○")
        text = f"{glyph}  {sync_state.get('label', '')}"
        details = sync_state.get("details", "")
        if details:
            text += f"   ·   {details}"
        self._sync_label.setText(text)
        self._sync_label.setStyleSheet(
            f"color: {scolor}; font-size: 9pt; padding-top: 4px; "
            f"border-top: 1px solid #313244;"
        )

        # Default enable: stage can run when settings + outputs reach a
        # non-trivial sync state. ``set_action_label`` callers (e.g. the
        # mesh/material patch cards) override via ``set_action_enabled``
        # after this default fires.
        self._process_btn.setEnabled(sstate not in ("unconfigured", "writing", "error"))

    # -------------------------------------------------------------------------
    # ACTION BUTTON CONTROL
    # -------------------------------------------------------------------------
    # The stage card's action button text + visibility + enable state are
    # owned by the host (DashboardTab) since the meaning differs per stage:
    # full-pipeline stages (Scenes / Prefabs / Terrain) say "Process" and
    # gate on sync-state; iterative stages (Meshes / Materials) say
    # "Patch Dirty" and gate on whether the state-index says anything is
    # actually dirty. Cards with no actionable surface hide the button.

    def set_action_label(self, label: str) -> None:
        """Re-label the action button. Empty string hides the button."""
        self._process_btn.setText(label or "")
        self._process_btn.setVisible(bool(label))

    def set_action_enabled(self, enabled: bool, *, tooltip: str = "") -> None:
        """Force-set the action button's enabled state. Overrides the
        default sync-state gate (called after ``update_state``)."""
        self._process_btn.setEnabled(enabled)
        if tooltip:
            self._process_btn.setToolTip(tooltip)


def compute_stage_readiness(stage_key: str, project) -> dict:
    """Return a structured readiness report for a converter stage:

        {
          "status":       'unset' | 'incomplete' | 'error' | 'ready' | 'ok' | 'warn',
          "status_label": display string for the status badge,
          "requirements": [ {"met": bool, "text": str,
                             "severity": "error" | "incomplete"}, ... ],
          "advisories":   [ {"text": str}, ... ],   # non-blocking warnings
          "last_run":     post-run summary string (None if never run),
        }

    `requirements` lists each prerequisite as either met (green ✓) or
    not met (red ✗). Unmet requirements with `severity="error"` push
    overall status to `error` (red); otherwise unmet → `incomplete`
    (yellow). `advisories` are soft warnings that don't change status
    but render as warning rows on the card."""
    if project is None:
        return {
            "status":       "unset",
            "status_label": "No project",
            "requirements": [],
            "advisories":   [],
            "last_run":     None,
        }

    status_info = project.pipeline_status.get(stage_key, {})
    cfg         = project.stage_settings(stage_key)
    source      = project.effective_source(stage_key)
    output      = (cfg.get("output_path") or "").strip()
    last_run    = status_info.get("last_run")

    reqs: list = []
    advisories: list = []
    last_run_summary = None

    if stage_key == "scene_converter":
        reqs.append(_req_source(source))
        scrubbed = scrub_scope_for(source, "*.unity") if source else []
        scr_count = len(scrubbed)
        sel_count = len(cfg.get("selected_scenes", []) or [])
        if sel_count > 0:
            reqs.append({"met": True,  "text": f"{sel_count} of {scr_count} scenes selected"})
        elif source and scr_count == 0:
            reqs.append({"met": False, "text": "Source has no .unity scenes"})
        else:
            reqs.append({"met": False, "text": "No scenes selected"})
        reqs.append(_req_output(output))

        # Soft advisory: warn when no converted prefabs are available to
        # resolve scene references against. Run will technically succeed
        # but every prefab instance will land as `missing_prefabs`.
        ap_outputs = project.outputs.get("asset_processor", {}) or {}
        if len(ap_outputs.get("prefabs", {}) or {}) == 0:
            advisories.append({
                "text": "No processed prefabs yet — scene references will not "
                        "be mapped. Run the Prefab Processor first for a "
                        "complete conversion."
            })

        if last_run:
            last_run_summary = (
                f"Last run {last_run}: "
                f"{status_info.get('scenes_converted', 0)}/{status_info.get('scenes_total', 0)} scenes, "
                f"{status_info.get('total_entities', 0)} entities, "
                f"{status_info.get('total_prefab_references', 0)} prefab refs, "
                f"{status_info.get('total_missing_prefabs', 0)} missing"
            )
        had_errors = bool(status_info.get("total_missing_prefabs", 0))

    elif stage_key == "asset_processor":
        reqs.append(_req_source(source))
        scrubbed  = scrub_scope_for(source, "*.prefab") if source else []
        scr_count = len(scrubbed)
        sel_count = len(cfg.get("selected_prefabs", []) or [])
        if source and scr_count == 0:
            # ERROR: source is configured but contains no prefabs. The user
            # has pointed at a path with nothing to process — fix the path
            # before anything else makes sense.
            reqs.append({"met": False, "severity": "error",
                         "text": "Source has no .prefab files — check the scope "
                                 "root or this tab's source override"})
        elif sel_count > 0:
            reqs.append({"met": True,  "text": f"{sel_count} of {scr_count} prefabs selected"})
        else:
            reqs.append({"met": False, "text": "No prefabs selected"})
        reqs.append(_req_output(output))
        if last_run:
            last_run_summary = (
                f"Last run {last_run}: "
                f"{status_info.get('prefabs_processed', 0)}/{status_info.get('prefabs_total', 0)} prefabs, "
                f"{status_info.get('materials_written', 0)} mats, "
                f"{status_info.get('errors', 0)} errors"
            )
        had_errors = bool(status_info.get("errors", 0))

    elif stage_key == "terrain_processor":
        reqs.append(_req_source(source))
        terrains = cfg.get("selected_terrains", []) or []
        if terrains:
            reqs.append({"met": True,  "text": f"{len(terrains)} terrain(s) selected"})
        else:
            reqs.append({"met": False, "text": "No terrains selected"})
        reqs.append(_req_output(output))
        if last_run:
            last_run_summary = (
                f"Last run {last_run}: "
                f"{status_info.get('terrains_total', 0)} terrain(s), "
                f"{status_info.get('materials_written', 0)} materials, "
                f"{status_info.get('prefabs_written', 0)} prefab(s), "
                f"{status_info.get('errors', 0)} errors"
            )
        had_errors = bool(status_info.get("errors", 0))

    elif stage_key in ("mesh_processor", "material_processor"):
        # Mesh + Material stages derive from the Prefab Processor's outputs;
        # they don't have their own source/output settings. Their readiness
        # mirrors what the upstream run produced.
        ap_outputs = project.outputs.get("asset_processor", {}) or {}
        ap_last    = ap_outputs.get("last_run")
        if not ap_last:
            reqs.append({"met": False,
                         "text": "Prefab Processor hasn't run yet"})
            had_errors = False
        elif stage_key == "mesh_processor":
            meshes = ap_outputs.get("meshes", {}) or {}
            if not meshes:
                reqs.append({"met": False,
                             "text": "No meshes extracted from prefab run"})
                had_errors = False
            else:
                reqs.append({"met": True,
                             "text": f"{len(meshes)} mesh(es) extracted"})
                mp_cfg    = project.stage_settings("mesh_processor")
                overrides = (mp_cfg.get("overrides") or {})
                if overrides:
                    reqs.append({"met": True,
                                 "text": f"{len(overrides)} mesh(es) with override(s)"})
                last_run_summary = (
                    f"Inherited from Prefab Processor run {ap_last}: "
                    f"{len(meshes)} mesh(es), {len(overrides)} override(s)"
                )
                last_run = ap_last  # so the status code path treats this as run-complete
                had_errors = False
        else:  # material_processor
            meta = ap_outputs.get("material_metadata", {}) or {}
            if not meta:
                reqs.append({"met": False,
                             "text": "No materials extracted from prefab run"})
                had_errors = False
            else:
                reqs.append({"met": True,
                             "text": f"{len(meta)} material(s) extracted"})
                mp_cfg    = project.stage_settings("material_processor")
                mappings  = (mp_cfg.get("shader_mappings") or {})
                overrides = (mp_cfg.get("overrides") or {})
                unmapped  = [
                    g for g, rec in meta.items()
                    if (rec or {}).get("shader_name", "")
                    and (rec or {})["shader_name"] not in mappings
                ]
                if unmapped:
                    reqs.append({"met": False,
                                 "text": f"{len(unmapped)} material(s) have unmapped shaders"})
                else:
                    reqs.append({"met": True, "text": "All shaders mapped"})
                if overrides:
                    reqs.append({"met": True,
                                 "text": f"{len(overrides)} material(s) with override(s)"})
                last_run_summary = (
                    f"Inherited from Prefab Processor run {ap_last}: "
                    f"{len(meta)} material(s), {len(unmapped)} unmapped, "
                    f"{len(overrides)} override(s)"
                )
                last_run = ap_last
                had_errors = bool(unmapped)

    else:
        return {
            "status":       "unset",
            "status_label": "(unknown stage)",
            "requirements": [],
            "advisories":   [],
            "last_run":     None,
        }

    all_met       = all(r["met"] for r in reqs)
    any_error_req = any(
        (not r["met"]) and r.get("severity") == "error" for r in reqs
    )
    if any_error_req:
        status, label = "error", "Error"
    elif not all_met:
        status, label = "incomplete", "Incomplete"
    elif last_run and had_errors:
        status, label = "warn", "Completed with warnings"
    elif last_run:
        status, label = "ok", "Complete"
    else:
        status, label = "ready", "Ready"

    return {
        "status":       status,
        "status_label": label,
        "requirements": reqs,
        "advisories":   advisories,
        "last_run":     last_run_summary,
    }


def _req_source(source: str) -> dict:
    """Render the 'source set' requirement uniformly across stages."""
    if source:
        return {"met": True,  "text": f"Source: {source}"}
    return     {"met": False, "text": "No source set"}


def _req_output(output: str) -> dict:
    """Render the 'destination set' requirement uniformly across stages."""
    if output:
        return {"met": True,  "text": f"Destination: {output}"}
    return     {"met": False, "text": "No destination set"}


# =============================================================================
# INPUT HASH + SYNC STATE
#
# Sync state surfaces "do the outputs match the current settings?" — answered
# by hashing every input that affects a stage's output and comparing against
# the hash recorded at last run.
# =============================================================================

import hashlib as _hashlib
import json    as _hashjson


def _fingerprint_files_under(root: str, pattern: str) -> dict:
    """{relative_path: mtime_int} for files under `root` matching `pattern`.
    Empty / non-existent root → {}."""
    if not root:
        return {}
    try:
        root_path = Path(root)
        if not root_path.is_dir():
            return {}
        out = {}
        for p in root_path.rglob(pattern):
            if p.is_file():
                rel = str(p.relative_to(root_path)).replace("\\", "/")
                try:
                    out[rel] = int(p.stat().st_mtime)
                except OSError:
                    out[rel] = 0
        return out
    except Exception:
        return {}


def _fingerprint_file(p) -> int:
    try:
        return int(Path(p).stat().st_mtime)
    except Exception:
        return 0


def input_hash_for(stage_key: str, project) -> str:
    """Stable 16-char SHA-256 prefix over every input that affects this
    stage's output. Recomputing for the same inputs returns the same hash;
    changing any path / selection / file mtime changes the hash."""
    if project is None:
        return ""

    cfg     = project.stage_settings(stage_key)
    source  = project.effective_source(stage_key)
    payload = {
        "scope_root":       str(project.scope_root) if project.scope_root else "",
        "effective_source": source,
        "output_path":      (cfg.get("output_path") or "").strip(),
    }

    if stage_key == "asset_processor":
        selected = sorted(cfg.get("selected_prefabs", []) or [])
        payload["selected_prefabs"] = selected
        if source:
            payload["files"] = {
                rel: _fingerprint_file(Path(source) / rel) for rel in selected
            }
        else:
            payload["files"] = {}

    elif stage_key == "scene_converter":
        selected = sorted(cfg.get("selected_scenes", []) or [])
        payload["selected_scenes"] = selected
        payload["prefab_dirs"]     = sorted(cfg.get("prefab_dirs", []) or [])
        if source:
            payload["files"] = {
                rel: _fingerprint_file(Path(source) / rel)
                for rel in selected
            }
        else:
            payload["files"] = {}

    elif stage_key == "terrain_processor":
        selected = sorted(cfg.get("selected_terrains", []) or [])
        payload["selected_terrains"] = selected
        payload["outputs"] = sorted(cfg.get("outputs", []) or [])
        payload["files"] = {t: _fingerprint_file(t) for t in selected}

    blob = _hashjson.dumps(payload, sort_keys=True)
    return _hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# Sync-state colors. Keyed by `state` returned from compute_stage_sync_state.
_SYNC_STATE_COLORS = {
    "unconfigured":   "#6c7086",
    "ready":          "#89dceb",
    "synchronized":   "#a6e3a1",
    "unsynchronized": "#f9e2af",
    "writing":        "#89b4fa",
    "error":          "#f38ba8",
}

# Sync-state display labels.
_SYNC_STATE_LABELS = {
    "unconfigured":   "Unconfigured",
    "ready":          "Ready to export",
    "synchronized":   "Synchronized",
    "unsynchronized": "Unsynchronized",
    "writing":        "Writing…",
    "error":          "Error",
}


def compute_stage_sync_state(stage_key: str, project, *, writing: bool = False) -> dict:
    """Return {state, label, details}. `state` is one of the keys in
    `_SYNC_STATE_COLORS`. Pass `writing=True` while a worker is running
    for that stage so the card shows the writing badge.

    State machine (priority order):
      1. writing flag set         → writing
      2. readiness incomplete     → unconfigured
      3. no last_run recorded     → ready
      4. last_status was 'error'  → error
      5. last_input_hash matches  → synchronized
      6. otherwise                → unsynchronized
    """
    if writing:
        return {"state": "writing",
                "label": _SYNC_STATE_LABELS["writing"],
                "details": ""}
    if project is None:
        return {"state": "unconfigured",
                "label": "No project",
                "details": ""}

    # Mesh + Material stages have no independent worker yet; their state
    # mirrors what the Prefab Processor produced. Delegate.
    if stage_key in ("mesh_processor", "material_processor"):
        readiness = compute_stage_readiness(stage_key, project)
        if readiness["status"] in ("incomplete", "error"):
            # Use the first unmet requirement as the detail line so the
            # sync row gives an honest reason ("1 material(s) have unmapped
            # shaders") rather than a generic "configure requirements".
            first_unmet = next(
                (r["text"] for r in readiness["requirements"] if not r["met"]),
                "Configuration incomplete",
            )
            sync_state = "error" if readiness["status"] == "error" else "unconfigured"
            return {"state":   sync_state,
                    "label":   _SYNC_STATE_LABELS[sync_state],
                    "details": first_unmet}
        delegated = compute_stage_sync_state("asset_processor", project)
        # Re-label so the user understands this stage rides on the prefab run.
        delegated = dict(delegated)
        delegated["details"] = (
            f"Inherited from Prefab Processor · {delegated.get('details', '')}"
        ).rstrip(" ·")
        return delegated

    readiness = compute_stage_readiness(stage_key, project)
    if readiness["status"] == "error":
        # Critical config problem — pull the first error requirement's text
        # for the detail line so the user sees the specific issue.
        first_err = next(
            (r["text"] for r in readiness["requirements"]
             if not r["met"] and r.get("severity") == "error"),
            "Configuration error",
        )
        return {"state": "error",
                "label": _SYNC_STATE_LABELS["error"],
                "details": first_err}
    if readiness["status"] == "incomplete":
        return {"state": "unconfigured",
                "label": _SYNC_STATE_LABELS["unconfigured"],
                "details": "Configure requirements above"}

    outputs     = project.outputs.get(stage_key, {})
    last_run    = outputs.get("last_run")
    last_status = outputs.get("last_status")
    last_hash   = outputs.get("last_input_hash")

    if not last_run:
        return {"state": "ready",
                "label": _SYNC_STATE_LABELS["ready"],
                "details": "Click Process to export"}

    if last_status == "error":
        return {"state": "error",
                "label": _SYNC_STATE_LABELS["error"],
                "details": "Last run failed; outputs may be incomplete"}

    current_hash = input_hash_for(stage_key, project)
    if current_hash == last_hash:
        return {"state": "synchronized",
                "label": _SYNC_STATE_LABELS["synchronized"],
                "details": f"Last exported {last_run}"}
    return {"state": "unsynchronized",
            "label": _SYNC_STATE_LABELS["unsynchronized"],
            "details": f"Inputs changed since last export ({last_run})"}


class _ClickableDot(QLabel):
    """A single severity-coloured glyph that emits ``clicked(key)`` when
    pressed. Sized tightly to the glyph (≈18 px square) with a 2-px
    hover frame — much smaller than a flat QPushButton, which still
    reserves button chrome and pushes adjacent widgets off-screen.

    Used by ``_PreflightPanel`` to render one indicator per category."""

    clicked = Signal(str)

    def __init__(self, key: str, glyph: str, color: str,
                 tooltip: str = "", parent=None):
        super().__init__(glyph, parent)
        self._key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(18, 18)
        if tooltip:
            self.setToolTip(tooltip)
        self.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 13pt; "
            f"font-weight: bold; border: 1px solid transparent; "
            f"border-radius: 3px; padding: 0px; }}"
            f"QLabel:hover {{ border: 1px solid #6c7086; "
            f"background-color: #313244; }}"
        )

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)

    def click(self) -> None:
        """Programmatic click — emits the same signal as a mouse press.
        Used by tests so they can drive the widget without synthesising
        a real Qt mouse event."""
        self.clicked.emit(self._key)


class _PreflightPanel(QWidget):
    """Mission Command's Pre-flight surface — collapsed by default.

    Compact header row shows one coloured dot per preflight category
    plus a single-line summary (e.g. ``"Ready — 6 categories green"``
    or the topmost issue title). Mass-action buttons (Refresh / Patch
    All / Run All) sit to the right, gated by the report's severity
    state. A chevron toggles the detailed rows below — per-category
    breakdown with per-yellow ``Acknowledge`` buttons.

    Per-dot clicks AND the ``Jump to issue`` button emit
    ``category_clicked(stage_key)`` so the parent dashboard can scroll
    the matching status card into view. The detailed rows below the
    dots aren't redundant with the cards — they carry the ack
    affordances — but they stay collapsed by default because the cards
    are the user's primary surface.

    Signals:
        run_all_clicked     — user wants to start a full Run All pass.
        patch_all_clicked   — user wants to patch-emit dirty assets.
        refresh_clicked     — user requested an explicit re-run of the checks.
        category_clicked    — user clicked a status dot or Jump button.
    """

    run_all_clicked   = Signal()
    patch_all_clicked = Signal()
    refresh_clicked   = Signal()
    category_clicked  = Signal(str)

    SEVERITY_COLOR = {
        "green":  "#a6e3a1",
        "yellow": "#f9e2af",
        "red":    "#f38ba8",
    }
    SEVERITY_DOT = {
        "green":  "●",
        "yellow": "⚠",
        "red":    "✗",
    }
    # Severity ordering for "first issue" lookups.
    _SEVERITY_RANK = {"red": 0, "yellow": 1, "green": 2}

    # Canonical stage order — MUST match the DashboardTab's status-card
    # construction loop. One dot per stage, same sequence, so clicking the
    # n-th dot scrolls to the n-th card. ``environment`` is intentionally
    # NOT in this list: it has no status card, so env problems are
    # surfaced only in the summary line + the Jump-to-issue button +
    # the expanded detail rows.
    STAGE_ORDER = (
        "scene_converter",
        "asset_processor",
        "mesh_processor",
        "material_processor",
        "terrain_processor",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._report = None
        self._dot_widgets: list = []     # filled by apply_report; per-category buttons
        self._expanded = False
        self._build_ui()

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._box, lay = _section_groupbox("Pre-flight")
        lay.setSpacing(6)

        # =====================================================================
        # TOP ROW (always visible)
        # =====================================================================
        # [● ● ● ● ●]   Ready — 5 stages green.   [Jump] [Refresh] [Patch All] [Run All]
        header = QHBoxLayout()
        header.setSpacing(8)
        header.setContentsMargins(0, 0, 0, 0)

        # Container for the dot-buttons. Rebuilt on each apply_report.
        self._dots_box = QWidget()
        self._dots_layout = QHBoxLayout(self._dots_box)
        self._dots_layout.setSpacing(2)
        self._dots_layout.setContentsMargins(0, 0, 0, 0)
        self._dots_layout.setAlignment(Qt.AlignVCenter)
        header.addWidget(self._dots_box, 0, Qt.AlignVCenter)

        # Summary text — single line.
        self._summary_lbl = QLabel("(no project loaded)")
        self._summary_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 10pt; font-weight: bold;"
        )
        header.addWidget(self._summary_lbl, 1, Qt.AlignVCenter)

        # Jump to issue — shown only when reds/unack yellows exist.
        self._jump_btn = QPushButton("Jump to issue")
        self._jump_btn.setObjectName("preflight_jump")
        self._jump_btn.setCursor(Qt.PointingHandCursor)
        self._jump_btn.setVisible(False)
        self._jump_btn.clicked.connect(self._on_jump_to_issue)
        header.addWidget(self._jump_btn, 0, Qt.AlignVCenter)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)
        header.addWidget(self._refresh_btn, 0, Qt.AlignVCenter)

        self._patch_all_btn = QPushButton("Patch All")
        self._patch_all_btn.setCursor(Qt.PointingHandCursor)
        self._patch_all_btn.clicked.connect(self.patch_all_clicked.emit)
        self._patch_all_btn.setToolTip(
            "Re-emit only the assets whose inputs (profile / override / "
            "source file) have changed since the last run. Cheap "
            "iterative loop. Disabled when red preflight items exist."
        )
        header.addWidget(self._patch_all_btn, 0, Qt.AlignVCenter)

        self._run_all_btn = QPushButton("Run All")
        self._run_all_btn.setObjectName("primary")
        self._run_all_btn.setCursor(Qt.PointingHandCursor)
        self._run_all_btn.clicked.connect(self.run_all_clicked.emit)
        self._run_all_btn.setToolTip(
            "Full pipeline pass — every stage runs in dependency order. "
            "Pre-flight gates apply; resolve every red and acknowledge "
            "every yellow first."
        )
        header.addWidget(self._run_all_btn, 0, Qt.AlignVCenter)

        lay.addLayout(header)

        # =====================================================================
        # DETAIL ROWS (collapsed by default; toggled by the Show more row)
        # =====================================================================
        self._rows_container = QWidget()
        self._rows_layout    = QVBoxLayout(self._rows_container)
        self._rows_layout.setSpacing(4)
        self._rows_layout.setContentsMargins(0, 2, 0, 0)
        self._rows_container.setVisible(False)
        lay.addWidget(self._rows_container)

        # =====================================================================
        # SHOW MORE / SHOW LESS  (second row, below dots / detail rows)
        # =====================================================================
        # Flat text-with-arrow control. "▾ Show more" when collapsed,
        # "▴ Show less" when expanded. The arrow is downward-pointing,
        # NOT a play-button glyph, so it reads as a dropdown affordance.
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)
        toggle_row.setContentsMargins(0, 0, 0, 0)
        self._toggle_btn = QPushButton("▾  Show more")
        self._toggle_btn.setObjectName("preflight_toggle")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setStyleSheet(
            "QPushButton#preflight_toggle { color: #89b4fa; font-size: 9pt; "
            "padding: 2px 6px; border: 1px solid transparent; border-radius: 3px; "
            "text-align: left; }"
            "QPushButton#preflight_toggle:hover { background-color: #313244; }"
        )
        self._toggle_btn.clicked.connect(self._toggle_expanded)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch(1)
        lay.addLayout(toggle_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._box)

    # -------------------------------------------------------------------------
    # EXPAND / COLLAPSE
    # -------------------------------------------------------------------------

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._rows_container.setVisible(self._expanded)
        self._toggle_btn.setText("▴  Show less" if self._expanded else "▾  Show more")

    # -------------------------------------------------------------------------
    # APPLY REPORT
    # -------------------------------------------------------------------------

    def apply_report(self, report, project) -> None:
        from preflight import CATEGORY_LABELS

        self._report = report
        # Tear down existing rows + dots.
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        while self._dots_layout.count():
            item = self._dots_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._dot_widgets = []

        if report is None or project is None:
            self._summary_lbl.setText("(no project loaded)")
            self._run_all_btn.setEnabled(False)
            self._patch_all_btn.setEnabled(False)
            self._jump_btn.setVisible(False)
            return

        # ---------------------------------------------------------------
        # Dot row — one per stage in dashboard-card order (NOT report
        # order — the report's category sequence depends on which check
        # function runs first and doesn't match the user's mental layout
        # of the cards below). Stages that aren't in the report (platform
        # doesn't support them) are skipped so the row stays aligned with
        # the visible cards. Environment isn't a stage — its issues live
        # in the summary line + the Jump button + the chevron detail.
        # ---------------------------------------------------------------
        report_cats = set(report.categories())
        for cat in self.STAGE_ORDER:
            if cat not in report_cats:
                continue
            worst = report.worst_severity(cat)
            label = CATEGORY_LABELS.get(cat, cat)
            count = len(report.by_category(cat))
            dot = _ClickableDot(
                key=cat,
                glyph=self.SEVERITY_DOT[worst],
                color=self.SEVERITY_COLOR[worst],
                tooltip=f"{label} — {count} check(s); click to jump",
            )
            dot.clicked.connect(self.category_clicked.emit)
            self._dots_layout.addWidget(dot)
            self._dot_widgets.append((cat, dot))

        # ---------------------------------------------------------------
        # Summary line — single-line cue. Green: "N categories ready".
        # Otherwise: topmost issue title with severity-tinted dot.
        # ---------------------------------------------------------------
        # Summary text — no leading severity glyph. The dot row already
        # conveys severity at-a-glance; a leading dot in the text would
        # read as a 6th dot floating next to the row.
        n_red    = len(report.reds)
        n_unack  = len(report.needs_ack)
        n_stages = len(self._dot_widgets)
        if report.can_run:
            color = self.SEVERITY_COLOR["green"]
            self._summary_lbl.setText(
                f"Ready — {n_stages} stage"
                f"{'' if n_stages == 1 else 's'} green."
            )
            self._jump_btn.setVisible(False)
        else:
            first_issue = self._first_issue(report)
            if n_red:
                color = self.SEVERITY_COLOR["red"]
                prefix = "Blocked"
            else:
                color = self.SEVERITY_COLOR["yellow"]
                prefix = "Hold"
            if first_issue is not None:
                self._summary_lbl.setText(f"{prefix} — {first_issue.title}")
            else:
                self._summary_lbl.setText(
                    f"{prefix} — {n_red} red, {n_unack} unacknowledged yellow."
                )
            self._jump_btn.setVisible(True)
        self._summary_lbl.setStyleSheet(
            f"color: {color}; font-size: 10pt; font-weight: bold;"
        )

        # ---------------------------------------------------------------
        # Detail rows (rendered into the collapsible container — hidden
        # by default; chevron toggles). All report categories appear
        # here — including environment — because users opening the
        # detail pane want to see the full picture.
        # ---------------------------------------------------------------
        for cat in report.categories():
            self._rows_layout.addWidget(
                self._build_category_widget(cat, CATEGORY_LABELS.get(cat, cat),
                                            report, project),
            )

        # ---------------------------------------------------------------
        # Button gating.
        #   Run All   — gated by `report.can_run` (reds OR unack yellows).
        #   Patch All — gated by reds only. Patching is iterative and
        #               benign for unack yellows, but reds (e.g. missing
        #               output path) make patching nonsensical.
        # ---------------------------------------------------------------
        self._run_all_btn.setEnabled(report.can_run)
        self._patch_all_btn.setEnabled(n_red == 0)
        if n_red:
            self._patch_all_btn.setToolTip(
                f"Disabled — {n_red} red preflight item(s) must be "
                f"resolved before patching can run safely."
            )
        else:
            self._patch_all_btn.setToolTip(
                "Re-emit only the assets whose inputs (profile / override / "
                "source file) have changed since the last run."
            )

    # -------------------------------------------------------------------------
    # JUMP-TO-ISSUE
    # -------------------------------------------------------------------------

    def _first_issue(self, report):
        """Return the topmost (most severe + earliest in report order)
        non-green ``PreflightItem``, or None when everything is green."""
        for item in report.items:
            if item.severity == "red":
                return item
        # No reds — look for an unack yellow.
        for item in report.needs_ack:
            return item
        return None

    def _on_jump_to_issue(self) -> None:
        if self._report is None:
            return
        first = self._first_issue(self._report)
        if first is None:
            return
        self.category_clicked.emit(first.category)

    def _build_category_widget(self, cat: str, label: str, report, project) -> QWidget:
        from preflight import CATEGORY_LABELS  # noqa: F401

        bucket = report.by_category(cat)
        worst  = report.worst_severity(cat)
        wrap = QFrame()
        wrap.setObjectName("preflight_category")
        wrap.setFrameShape(QFrame.NoFrame)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(4)

        # Header line — one-glance summary of the category.
        header = QLabel(
            f"<span style='color: {self.SEVERITY_COLOR[worst]};'>"
            f"{self.SEVERITY_DOT[worst]}</span> "
            f"<b>{label}</b>  "
            f"<span style='color: #6c7086;'>· {len(bucket)} check(s)</span>"
        )
        header.setTextFormat(Qt.RichText)
        v.addWidget(header)

        # Per-item rows.
        for item in bucket:
            v.addWidget(self._build_item_row(item, report, project))
        return wrap

    def _build_item_row(self, item, report, project) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(20, 0, 0, 0)
        h.setSpacing(8)

        # Severity-aware text. Yellow that's already acknowledged renders
        # in a softer tone so the user knows it's gated through.
        acked = (item.ack_key is not None
                 and report.acks.get(item.ack_key) == (item.ack_snapshot or "")
                 and item.severity == "yellow")
        color = self.SEVERITY_COLOR[item.severity if not acked else "green"]
        dot   = self.SEVERITY_DOT  [item.severity if not acked else "green"]
        text_parts = [item.title]
        if item.detail:
            text_parts.append(f"<span style='color: #6c7086;'>· {item.detail}</span>")
        if acked:
            text_parts.append("<span style='color: #a6e3a1;'>(acknowledged)</span>")
        body = QLabel(
            f"<span style='color: {color};'>{dot}</span> " + " ".join(text_parts)
        )
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        if item.fix_hint:
            body.setToolTip(item.fix_hint)
        h.addWidget(body, 1)

        # Per-yellow-row Acknowledge / Clear button. Reds get nothing —
        # they must be fixed, not waved away.
        if item.severity == "yellow" and item.ack_key:
            if acked:
                btn = QPushButton("Clear Ack")
                btn.setObjectName("preflight_clear_ack")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, k=item.ack_key: self._on_clear_ack(k)
                )
            else:
                btn = QPushButton("Acknowledge")
                btn.setObjectName("preflight_ack")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, k=item.ack_key, s=(item.ack_snapshot or ""):
                        self._on_ack(k, s)
                )
            btn.setMinimumWidth(0)
            h.addWidget(btn)

        return wrap

    # -------------------------------------------------------------------------
    # ACK HANDLERS
    # -------------------------------------------------------------------------

    def _on_ack(self, ack_key: str, snapshot: str) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        proj.set_preflight_ack(ack_key, snapshot)
        pm.commit_metadata()
        # Refresh so the row flips colour without waiting for the next
        # project_changed event.
        self.refresh_clicked.emit()

    def _on_clear_ack(self, ack_key: str) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        proj.clear_preflight_ack(ack_key)
        pm.commit_metadata()
        self.refresh_clicked.emit()


class DashboardTab(QWidget):
    """Pipeline status dashboard. Hosts the dep banner (rehomed from
    MainWindow), three pipeline-status rows in configuration-workflow order
    (Scene → Prefab → Terrain), and an activity log. Project header /
    notes / file ops live in `ProjectHeaderBanner` at the window level."""

    request_focus_stage   = Signal(str)
    request_process_stage = Signal(str)
    # F-8 — Mission Command-level actions. MainWindow routes these to the
    # PipelineOrchestrator (Run All) and to MaterialTab._start_patch
    # (Patch All). Kept as signals so DashboardTab doesn't have to know
    # the tab layout.
    request_run_all       = Signal()
    request_patch_all     = Signal()

    def __init__(self, dep_banner=None):
        super().__init__()
        self._status_cards: dict = {}
        # Tracks which stage keys are currently running so sync-state cards
        # can render the `writing` state instead of recomputing the hash.
        self._stages_writing: set = set()
        self._dep_banner = dep_banner
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        pm.processing_changed.connect(self.mark_stage_writing)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outer holds a scroll area so the dashboard scrolls when the dep
        # banner + pipeline cards + log exceed the viewport.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        if self._dep_banner is not None:
            root.addWidget(self._dep_banner)

        # F-8 Pre-flight panel — gates Run All / Patch All.
        self._preflight = _PreflightPanel()
        self._preflight.refresh_clicked.connect(self._refresh_preflight)
        self._preflight.run_all_clicked.connect(self._on_run_all)
        self._preflight.patch_all_clicked.connect(self._on_patch_all)
        # Dot click / "Jump to issue" → scroll the matching status card.
        # ``category_clicked`` carries the same stage_key the cards keyed
        # off, except "environment" which has no card — we surface that
        # by scrolling to the first card so the user lands somewhere
        # sensible (the actual fix-hint is in the expanded preflight).
        self._preflight.category_clicked.connect(self._on_preflight_jump)
        root.addWidget(self._preflight)

        # Pipeline Status — one StageStatusCard per stage, workflow order.
        # Action button label is per-stage: full-pipeline stages say
        # "Process" (full run); iterative stages say "Patch Dirty" (the
        # state-index-driven re-emit loop). The enable gate for the
        # iterative stages is refined in `_refresh_status_card`.
        self._status_box, status_lay = _section_groupbox("Pipeline Status")
        status_lay.setSpacing(10)
        for stage_key, label, action_label in (
            ("scene_converter",    "Scenes",    "Process"),
            ("asset_processor",    "Prefabs",   "Process"),
            ("mesh_processor",     "Meshes",    "Patch Dirty"),
            ("material_processor", "Materials", "Patch Dirty"),
            ("terrain_processor",  "Terrain",   "Process"),
        ):
            card = StageStatusCard(label, action_label=action_label)
            card.open_clicked.connect(
                lambda k=stage_key: self.request_focus_stage.emit(k)
            )
            card.process_clicked.connect(
                lambda k=stage_key: self.request_process_stage.emit(k)
            )
            status_lay.addWidget(card)
            self._status_cards[stage_key] = card
        root.addWidget(self._status_box)

        # Activity log
        self._activity_log = _log_widget()
        self._activity_log.setMinimumHeight(120)
        root.addWidget(_fill_section("Activity Log", self._activity_log), stretch=1)

        outer.addWidget(_scroll_wrap(content))

    # -------------------------------------------------------------------------
    # SYNC
    # -------------------------------------------------------------------------

    def apply_project(self, project) -> None:
        for key in self._status_cards:
            self._refresh_status_card(key, project)
        self._refresh_preflight()

    def _refresh_preflight(self) -> None:
        """Re-run the pre-flight checks against the current project and
        apply the resulting report to the panel."""
        from preflight import run_preflight
        pm = project_manager()
        proj = pm.current()
        # Dependencies are surfaced by the F-1 banner. Mirror its state
        # into the preflight check; absent banner means "assume present"
        # so we don't double-red on a state we already surface elsewhere.
        deps_present = True
        if self._dep_banner is not None and hasattr(self._dep_banner, "missing"):
            deps_present = not bool(getattr(self._dep_banner, "missing", []))
        report = run_preflight(proj, deps_present=deps_present) if proj else None
        self._preflight.apply_report(report, proj)

    def _on_run_all(self) -> None:
        self.request_run_all.emit()

    def _on_patch_all(self) -> None:
        self.request_patch_all.emit()

    def _on_preflight_jump(self, category: str) -> None:
        """User clicked a preflight dot or the Jump-to-issue button.
        Categories that map 1:1 onto a status card (``asset_processor``,
        ``mesh_processor``, …) scroll to that card. ``environment``
        has no card — it surfaces dependency banners and project-root
        problems, which live in the expanded preflight detail rows — so
        we force the panel open and leave the user there."""
        if category == "environment":
            if not self._preflight._expanded:
                self._preflight._toggle_expanded()
            return
        if category in self._status_cards:
            self.scroll_to_card(category)

    def showEvent(self, event) -> None:
        """Tab activation re-runs preflight so opening the dashboard
        sees the freshest project state (e.g. after the user edited
        material settings on another tab)."""
        super().showEvent(event)
        self._refresh_preflight()

    def _refresh_status_card(self, stage_key: str, project) -> None:
        card = self._status_cards[stage_key]
        readiness  = compute_stage_readiness(stage_key, project)
        sync_state = compute_stage_sync_state(
            stage_key, project, writing=(stage_key in self._stages_writing),
        )
        card.update_state(readiness, sync_state)

        # Iterative stages (mesh / material) override the default sync-state
        # gate: their action is "Patch Dirty", which only makes sense when
        # at least one asset in the state index is dirty or externally
        # modified. Synchronised stages disable the button with an
        # explanatory tooltip so the user isn't left wondering why
        # clicking does nothing.
        if stage_key in ("mesh_processor", "material_processor") and project is not None:
            bucket = "meshes" if stage_key == "mesh_processor" else "materials"
            dirty, ext_mod = self._count_iterative_dirty(project, bucket)
            actionable = (dirty + ext_mod) > 0
            if actionable:
                tip = (f"Re-emit {dirty} dirty + {ext_mod} externally-modified "
                       f"{bucket}. Click runs the Patch worker.")
            else:
                tip = (f"All {bucket} in sync — nothing to patch. "
                       f"Edit overrides / settings or run the Prefabs stage "
                       f"to produce new assets.")
            card.set_action_enabled(actionable, tooltip=tip)

    @staticmethod
    def _count_iterative_dirty(project, bucket: str):
        """Return ``(dirty_count, externally_modified_count)`` for a
        state-index bucket (``materials`` or ``meshes``). Used to gate
        the iterative stages' Patch button without running the full
        worker."""
        from project_manager import detect_externally_modified
        state_root = project.outputs.get("state_index") or {}
        entries    = state_root.get(bucket) or {}
        dirty = 0
        for entry in entries.values():
            outputs = entry.get("output_files") or []
            if not outputs or any(not Path(p).exists() for p in outputs):
                dirty += 1
        ext_mod_bucket = detect_externally_modified(state_root).get(bucket) or set()
        return dirty, len(ext_mod_bucket)

    # -------------------------------------------------------------------------
    # SCROLL HELPERS
    # -------------------------------------------------------------------------

    def scroll_to_card(self, stage_key: str) -> None:
        """Scroll the dashboard so the named stage's status card is
        visible. Called from the pre-flight panel when the user clicks
        a status dot or the Jump-to-issue button. Falls back to no-op
        when the stage key is unknown.

        Briefly outlines the target card so the user can spot it. The
        outline is tracked + cancellable to prevent the "card stays
        highlighted" bug where rapid clicks left a card in a stuck
        bordered state because two QTimers raced over the same
        ``setStyleSheet`` slot."""
        card = self._status_cards.get(stage_key)
        if card is None:
            return
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtCore import QTimer
        scroll = next(iter(self.findChildren(QScrollArea)), None)
        if scroll is not None:
            scroll.ensureWidgetVisible(card, 0, 40)
        self._flash_highlight(card)

    def _flash_highlight(self, card) -> None:
        """Apply a 1.2s flash outline to ``card``. Cancels any pending
        clear from a previous flash on any card so the styling never
        sticks. The card's pristine style is stored once on the
        dashboard (``_card_base_qss``) so cumulative appends are
        impossible."""
        from PySide6.QtCore import QTimer
        # Capture pristine card style once, the first time we flash.
        if not hasattr(self, "_card_base_qss"):
            self._card_base_qss = {
                key: c.styleSheet() for key, c in self._status_cards.items()
            }
        # Cancel any pending clear; restore every card to pristine first
        # so a stuck previous-highlight can't survive.
        if getattr(self, "_highlight_timer", None) is not None:
            self._highlight_timer.stop()
            self._highlight_timer = None
        for key, c in self._status_cards.items():
            c.setStyleSheet(self._card_base_qss.get(key, ""))
        # Apply the highlight to the requested card only.
        target_key = next((k for k, v in self._status_cards.items() if v is card),
                          None)
        if target_key is None:
            return
        base = self._card_base_qss.get(target_key, "")
        card.setStyleSheet(
            base + " QFrame#stage_status_card { border: 2px solid #89b4fa; }"
        )
        # Single shared timer, captured on self so a follow-up flash can
        # stop it before applying its own.
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda c=card, b=base: c.setStyleSheet(b)
        )
        timer.start(1200)
        self._highlight_timer = timer

    def mark_stage_writing(self, stage_key: str, writing: bool) -> None:
        """Called by MainWindow when a stage's worker starts/finishes. Flips
        the card's sync state to 'writing' while a run is in-flight, and
        back to a recomputed state afterwards."""
        if writing:
            self._stages_writing.add(stage_key)
        else:
            self._stages_writing.discard(stage_key)
        self._refresh_status_card(stage_key, project_manager().current())

    def _on_status_changed(self, stage_key: str) -> None:
        proj = project_manager().current()
        if proj is None or stage_key not in self._status_cards:
            return
        self._refresh_status_card(stage_key, proj)
        self._log_activity(f"{stage_key}: status updated")

    def showEvent(self, event):
        # Refresh status cards whenever the Dashboard tab becomes visible.
        # `project_changed` fires on project open/close but NOT on per-stage
        # edits done in other tabs (those go through pm.update_stage which
        # saves silently). So when the user returns to the dashboard after
        # editing scenes / output / materials elsewhere, this hook picks up
        # the changes and refreshes the readiness display.
        super().showEvent(event)
        self.apply_project(project_manager().current())

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
        self._selected_prefabs: set = set()  # relative paths under effective_source
        self._suppress_prefab_signals = False
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Unity Assets Folder ─────────────────────────────────────────
        src_box, src_lay = _section_groupbox("Unity Assets Folder")
        self._source_edit, src_btn = _path_row(
            "Override (blank → use project scope root)"
        )
        src_btn.clicked.connect(self._browse_source)
        self._source_edit.editingFinished.connect(self._on_source_edited)
        src_lay.addLayout(_hbox(self._source_edit, src_btn))
        self._effective_source_label = QLabel("")
        self._effective_source_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._effective_source_label.setWordWrap(True)
        src_lay.addWidget(self._effective_source_label)
        root.addWidget(src_box)

        # ── Prefabs to Convert (F-4 scrubbed checklist) ─────────────────
        self._prefab_list = QListWidget()
        self._prefab_list.itemChanged.connect(self._on_prefab_item_changed)
        refresh_btn         = QPushButton("Refresh from Scope")
        select_all_btn      = QPushButton("Select All")
        clear_selection_btn = QPushButton("Clear Selection")
        clear_missing_btn   = QPushButton("Clear Missing")
        refresh_btn.clicked.connect(self._refresh_prefab_list)
        select_all_btn.clicked.connect(self._select_all_prefabs)
        clear_selection_btn.clicked.connect(self._clear_prefab_selection)
        clear_missing_btn.clicked.connect(self._clear_missing_prefabs)
        root.addWidget(_managed_list_section(
            "Prefabs to Convert", self._prefab_list,
            refresh_btn, select_all_btn, clear_selection_btn, clear_missing_btn,
            min_h=140, max_h=220,
        ))
        # Cross-stage usage summary (referenced meshes / materials)
        self._usage_label = QLabel("")
        self._usage_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._usage_label.setWordWrap(True)
        root.addWidget(self._usage_label)

        # ── O3DE Output Folder ──────────────────────────────────────────
        out_box, out_lay = _section_groupbox("O3DE Output Folder")
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        out_lay.addLayout(_hbox(self._output_edit, out_btn))
        info_label = QLabel(
            "  Prefabs/    — O3DE prefabs with material references\n"
            "  Materials/  — O3DE PBR materials (.material)\n"
            "  Textures/   — All textures consolidated\n"
            "  Meshes/     — FBX models with .assetinfo sub-mesh definitions\n\n"
            "  Converter bookkeeping (entity maps, asset index, coverage)\n"
            "  is stored in the project file, not on disk next to outputs."
        )
        info_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        out_lay.addWidget(info_label)
        root.addWidget(out_box)

        # ── Processing Log ──────────────────────────────────────────────
        self._log_edit = _log_widget()
        root.addWidget(_fill_section("Processing Log", self._log_edit), stretch=1)

        # ── Last Run Details (per-prefab breakdown, populated on success) ──
        self._last_run_box = _section_groupbox("Last Run Details")[0]
        self._last_run_box_lay = self._last_run_box.layout()
        self._last_run_box.setVisible(False)
        root.addWidget(self._last_run_box)

        # ── Action buttons ──────────────────────────────────────────────
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        self._process_btn = QPushButton("Process Assets")
        self._process_btn.setObjectName("primary")
        self._process_btn.clicked.connect(self._start_processing)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(save_log_btn)
        action_row.addStretch(1)
        action_row.addWidget(self._process_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "asset_processor"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._source_edit.setText(cfg.get("source_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))
        self._selected_prefabs = set(cfg.get("selected_prefabs", []))
        self._refresh_effective_source_label()
        self._refresh_prefab_list()
        self._refresh_usage_summary(project)
        self._refresh_last_run_details(project)

    def _refresh_effective_source_label(self) -> None:
        """Show the resolved walking root when the override is blank, hide
        the label when an override is set."""
        if self._source_edit.text().strip():
            self._effective_source_label.setText("")
            return
        proj = project_manager().current()
        if proj is None or not proj.scope_root:
            self._effective_source_label.setText(
                "→ no source set (set a project scope root, or fill this field)"
            )
            self._effective_source_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")
            return
        self._effective_source_label.setText(f"→ using scope root: {proj.scope_root}")
        self._effective_source_label.setStyleSheet("color: #89dceb; font-size: 9pt;")

    def _collect_stage_settings(self) -> dict:
        return {
            "source_path":      self._source_edit.text(),
            "selected_prefabs": sorted(self._selected_prefabs),
            "output_path":      self._output_edit.text(),
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
            self._on_source_edited()

    def _on_source_edited(self) -> None:
        self._save_settings()
        self._refresh_effective_source_label()
        self._refresh_prefab_list()

    def _effective_source_text(self) -> str:
        proj = project_manager().current()
        if proj is not None:
            return proj.effective_source(self.STAGE_KEY)
        return self._source_edit.text().strip()

    # ── Prefabs checklist (F-4) ─────────────────────────────────────────

    def _refresh_prefab_list(self) -> None:
        """Re-walk effective_source for *.prefab and rebuild the checklist,
        preserving the persisted selection. Previously-selected prefabs
        that no longer resolve appear at the bottom with a ⚠ glyph."""
        self._suppress_prefab_signals = True
        try:
            self._prefab_list.clear()
            root_text = self._effective_source_text()
            scrubbed = scrub_scope_for(root_text, "*.prefab")
            scrubbed_strs = {str(p).replace("\\", "/") for p in scrubbed}

            for rel in scrubbed:
                rel_str = str(rel).replace("\\", "/")
                item = QListWidgetItem(rel_str)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                state = Qt.Checked if rel_str in self._selected_prefabs else Qt.Unchecked
                item.setCheckState(state)
                item.setData(Qt.UserRole, rel_str)
                self._prefab_list.addItem(item)

            missing = sorted(self._selected_prefabs - scrubbed_strs)
            for rel_str in missing:
                item = QListWidgetItem(f"⚠ {rel_str}  (missing from scope)")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, rel_str)
                item.setForeground(Qt.darkYellow)
                item.setToolTip(
                    "This prefab was selected previously but is not under the "
                    "current effective source. Click 'Clear Missing' to drop it."
                )
                self._prefab_list.addItem(item)
        finally:
            self._suppress_prefab_signals = False

    def _on_prefab_item_changed(self, item) -> None:
        if self._suppress_prefab_signals:
            return
        rel = item.data(Qt.UserRole)
        if not rel:
            return
        if item.checkState() == Qt.Checked:
            self._selected_prefabs.add(rel)
        else:
            self._selected_prefabs.discard(rel)
        self._save_settings()

    def _select_all_prefabs(self) -> None:
        self._suppress_prefab_signals = True
        try:
            for i in range(self._prefab_list.count()):
                item = self._prefab_list.item(i)
                item.setCheckState(Qt.Checked)
                rel = item.data(Qt.UserRole)
                if rel:
                    self._selected_prefabs.add(rel)
        finally:
            self._suppress_prefab_signals = False
        self._save_settings()

    def _clear_prefab_selection(self) -> None:
        self._suppress_prefab_signals = True
        try:
            for i in range(self._prefab_list.count()):
                self._prefab_list.item(i).setCheckState(Qt.Unchecked)
            self._selected_prefabs.clear()
        finally:
            self._suppress_prefab_signals = False
        self._save_settings()

    def _clear_missing_prefabs(self) -> None:
        root_text = self._effective_source_text()
        scrubbed = {str(p).replace("\\", "/") for p in scrub_scope_for(root_text, "*.prefab")}
        self._selected_prefabs &= scrubbed
        self._refresh_prefab_list()
        self._save_settings()

    # ── Cross-stage usage summary + last-run details ───────────────────

    def _refresh_usage_summary(self, project) -> None:
        """Show what selected prefabs imply for downstream stages — counts
        of meshes and materials this Stage 1 run will produce, sourced from
        project.outputs after a run. Pre-run shows just the selection count."""
        if project is None:
            self._usage_label.setText("")
            return
        sel_count = len(self._selected_prefabs)
        outputs = project.outputs.get("asset_processor", {}) if project else {}
        meshes_n = len(outputs.get("meshes", {}))
        mats_n   = len(outputs.get("materials", {}))
        last_run = outputs.get("last_run")
        if last_run and (meshes_n or mats_n):
            self._usage_label.setText(
                f"{sel_count} selected · Last run produced {meshes_n} meshes, "
                f"{mats_n} materials (used by Mesh + Material tabs)."
            )
        else:
            self._usage_label.setText(
                f"{sel_count} prefab(s) selected · Mesh / Material counts populate after a run."
            )

    def _refresh_last_run_details(self, project) -> None:
        """Populate the per-prefab last-run breakdown section. Hidden until
        a prefab run has populated project.outputs.asset_processor.prefabs."""
        while self._last_run_box_lay.count():
            item = self._last_run_box_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if project is None:
            self._last_run_box.setVisible(False)
            return
        outputs = project.outputs.get("asset_processor", {})
        prefab_records = outputs.get("prefabs", {})
        last_run = outputs.get("last_run")
        if not last_run or not prefab_records:
            self._last_run_box.setVisible(False)
            return

        header = QLabel(
            f"{len(prefab_records)} prefab(s) recorded · Last run {last_run}"
        )
        header.setStyleSheet("color: #a6e3a1; font-size: 9pt; font-weight: bold;")
        self._last_run_box_lay.addWidget(header)
        shown_limit = 20
        for i, (key, rec) in enumerate(sorted(prefab_records.items())):
            if i >= shown_limit:
                break
            out_path  = rec.get("output_path", "?")
            entities  = len(rec.get("entity_aliases", {}))
            mat_slots = sum(len(v) for v in rec.get("material_slots", {}).values())
            label = QLabel(
                f"  • {out_path}  ·  {entities} entities, {mat_slots} material slot(s)"
            )
            label.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            label.setWordWrap(True)
            self._last_run_box_lay.addWidget(label)
        overflow = len(prefab_records) - shown_limit
        if overflow > 0:
            more = QLabel(f"  … and {overflow} more")
            more.setStyleSheet("color: #6c7086; font-size: 9pt; font-style: italic;")
            self._last_run_box_lay.addWidget(more)
        self._last_run_box.setVisible(True)

    def _on_status_changed(self, stage_key: str) -> None:
        if stage_key != self.STAGE_KEY:
            return
        proj = project_manager().current()
        self._refresh_usage_summary(proj)
        self._refresh_last_run_details(proj)

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
        proj = project_manager().current()
        source = proj.effective_source(self.STAGE_KEY) if proj else self._source_edit.text().strip()
        output = self._output_edit.text().strip()

        if not source or not output:
            QMessageBox.critical(
                self, "Error",
                "Please set both a source (this field or the project scope root) "
                "and an output folder.",
            )
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Error", f"Source folder not found:\n{source}")
            return
        if not self._selected_prefabs:
            QMessageBox.critical(self, "Error",
                "No prefabs selected. Check at least one prefab in the list.")
            return

        # Resolve selected relative paths to absolute files.
        root = Path(source)
        resolved: list = []
        missing:  list = []
        for rel in sorted(self._selected_prefabs):
            abs_path = root / rel
            if abs_path.is_file():
                resolved.append(abs_path)
            else:
                missing.append(rel)
        if missing:
            txt = "\n".join(f"  • {m}" for m in missing)
            reply = QMessageBox.question(
                self, "Some prefabs missing",
                f"{len(missing)} selected prefab(s) do not exist:\n{txt}\n\n"
                f"Continue with the {len(resolved)} that do?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply == QMessageBox.No:
                return
        if not resolved:
            QMessageBox.critical(self, "Error", "No selected prefabs exist on disk.")
            return

        self._save_settings()
        self._process_btn.setEnabled(False)
        self._log_edit.clear()
        pm = project_manager()
        pm.set_processing(self.STAGE_KEY, True)

        # F-9 — snapshot the material + mesh settings on the UI thread so
        # the worker doesn't reach back into the singleton. Both are
        # already in-process dicts; copy.deepcopy keeps the worker
        # isolated from concurrent edits while it runs.
        proj = pm.current()
        material_settings = (copy.deepcopy(proj.stage_settings("material_processor"))
                              if proj else None)
        mesh_settings     = (copy.deepcopy(proj.stage_settings("mesh_processor"))
                              if proj else None)

        self._worker = WorkerThread(
            self._do_processing, source, output, resolved,
            material_settings, mesh_settings,
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_processing(self, source_path: str, output_path: str,
                       prefab_files: list,
                       material_settings: dict, mesh_settings: dict,
                       log) -> str:
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
            material_settings=material_settings,
            mesh_settings=mesh_settings,
        )

        log(f"\nProcessing {len(prefab_files)} selected Unity prefab(s)")

        success_count = 0
        for i, prefab_file in enumerate(prefab_files, 1):
            log(f"\n[{i}/{len(prefab_files)}] {prefab_file.name}")
            if processor.process_prefab(prefab_file):
                success_count += 1

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

        run_ts  = _utc_now_iso()
        errors  = max(0, len(prefab_files) - success_count)
        sstatus = "warn" if errors else "ok"

        # Persist the run's bookkeeping into the project file (replaces
        # the old `.ImporterData/` sidecars).
        proc_outputs = processor.to_outputs()
        proc_outputs["last_run"]        = run_ts
        proc_outputs["last_status"]     = sstatus
        proc_outputs["last_input_hash"] = input_hash_for(
            self.STAGE_KEY, project_manager().current()
        )
        project_manager().update_outputs(self.STAGE_KEY, proc_outputs)

        # F-9.I.4 — merge this run's state_index onto the existing one so
        # assets the run didn't touch keep their prior fingerprints. The
        # patch worker (I.5) consults the merged index when deciding what's
        # dirty on the next run.
        run_state = processor.state_index()
        proj = project_manager().current()
        if proj is not None:
            existing = dict(proj.outputs.get("state_index") or {})
            for bucket_name, bucket in run_state.items():
                merged = dict(existing.get(bucket_name) or {})
                merged.update(bucket)
                existing[bucket_name] = merged
            project_manager().update_outputs("state_index", existing)

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":          run_ts,
            "prefabs_processed": success_count,
            "prefabs_total":     len(prefab_files),
            "materials_written": len(processor.processed_materials),
            "textures_copied":   len(processor.processed_textures),
            "meshes_copied":     len(processor.processed_meshes),
            "errors":            errors,
        })

        summary_parts = [f"Prefabs: {success_count}/{len(prefab_files)}"]
        summary_parts += [f"{label}: {count}" for label, count in asset_stats.items()]
        return "  |  ".join(summary_parts)

    def _on_finished(self, success: bool, summary: str) -> None:
        self._process_btn.setEnabled(True)
        project_manager().set_processing(self.STAGE_KEY, False)
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
        self._prefab_dirs: list = []          # legacy; UI removed in F-4
        self._selected_scenes: set = set()    # relative paths under effective_source
        self._suppress_scene_signals = False  # block itemChanged during apply
        self._last_run_totals: dict = {}
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outer layout holds a scroll area so the tab scrolls vertically
        # when the window is shorter than the natural content height.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Unity Assets Folder ─────────────────────────────────────────
        src_box, src_lay = _section_groupbox("Unity Assets Folder")
        self._source_edit, src_btn = _path_row(
            "Override (blank → use project scope root)"
        )
        src_btn.clicked.connect(self._browse_source)
        self._source_edit.editingFinished.connect(self._on_source_edited)
        src_lay.addLayout(_hbox(self._source_edit, src_btn))
        self._effective_source_label = QLabel("")
        self._effective_source_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._effective_source_label.setWordWrap(True)
        src_lay.addWidget(self._effective_source_label)
        root.addWidget(src_box)

        # ── Scenes to Convert ───────────────────────────────────────────
        self._scene_list = QListWidget()
        self._scene_list.itemChanged.connect(self._on_scene_item_changed)
        refresh_btn         = QPushButton("Refresh from Scope")
        select_all_btn      = QPushButton("Select All")
        clear_selection_btn = QPushButton("Clear Selection")
        clear_missing_btn   = QPushButton("Clear Missing")
        refresh_btn.clicked.connect(self._refresh_scene_list)
        select_all_btn.clicked.connect(self._select_all_scenes)
        clear_selection_btn.clicked.connect(self._clear_scene_selection)
        clear_missing_btn.clicked.connect(self._clear_missing_scenes)
        root.addWidget(_managed_list_section(
            "Scenes to Convert", self._scene_list,
            refresh_btn, select_all_btn, clear_selection_btn, clear_missing_btn,
            min_h=120, max_h=220,
        ))

        # ── Output Destination ──────────────────────────────────────────
        out_box, out_lay = _section_groupbox("Output Destination")
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        out_lay.addLayout(_hbox(self._output_edit, out_btn))
        info_label = QLabel(
            "Each selected scene emits to:\n"
            "    <output>/<SceneName>/<SceneName>.prefab\n\n"
            "Coverage and per-scene records are stored in the project file."
        )
        info_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        out_lay.addWidget(info_label)
        root.addWidget(out_box)

        # ── Project Prefab Inventory (F-4: derived from Prefab Processor) ──
        prefab_box, prefab_lay = _section_groupbox("Project Prefab Inventory")
        self._project_prefabs_label = QLabel("")
        self._project_prefabs_label.setWordWrap(True)
        self._project_prefabs_label.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        prefab_lay.addWidget(self._project_prefabs_label)
        root.addWidget(prefab_box)

        # ── Conversion Log ──────────────────────────────────────────────
        self._log_edit = _log_widget()
        root.addWidget(_fill_section("Conversion Log", self._log_edit), stretch=1)

        # ── Last Run Details (per-level breakdown, populated post-run) ──
        self._last_run_box = _section_groupbox("Last Run Details")[0]
        self._last_run_box_lay = self._last_run_box.layout()
        self._last_run_box.setVisible(False)
        root.addWidget(self._last_run_box)

        # ── Action buttons ──────────────────────────────────────────────
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        self._convert_btn = QPushButton("Convert Scenes")
        self._convert_btn.setObjectName("primary")
        self._convert_btn.clicked.connect(self._start_conversion)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(save_log_btn)
        action_row.addStretch(1)
        action_row.addWidget(self._convert_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "scene_converter"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._source_edit.setText(cfg.get("source_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))
        self._selected_scenes = set(cfg.get("selected_scenes", []))
        # `prefab_dirs` still present in the schema for backwards compat,
        # but no UI controls it any more. Stage 2 derives the prefab database
        # from project.outputs.asset_processor (populated by F-4 prefab runs).
        self._prefab_dirs = list(cfg.get("prefab_dirs", []))
        self._refresh_effective_source_label()
        self._refresh_scene_list()
        self._refresh_project_prefabs_label(project)
        self._refresh_last_run_details(project)

    def _collect_stage_settings(self) -> dict:
        return {
            "source_path":     self._source_edit.text(),
            "selected_scenes": sorted(self._selected_scenes),
            "output_path":     self._output_edit.text(),
            "prefab_dirs":     list(self._prefab_dirs),
        }

    def _save_settings(self) -> None:
        pm = project_manager()
        if pm.current() is None:
            return
        pm.update_stage(self.STAGE_KEY, self._collect_stage_settings())

    # -------------------------------------------------------------------------
    # BROWSE / SOURCE HELPERS
    # -------------------------------------------------------------------------

    def _browse_source(self) -> None:
        start = _resolve_start_dir(self._source_edit.text().strip())
        d = QFileDialog.getExistingDirectory(
            self, "Select Unity assets walking root (override)", start,
        )
        if d:
            self._source_edit.setText(d)
            self._on_source_edited()

    def _on_source_edited(self) -> None:
        self._save_settings()
        self._refresh_effective_source_label()
        self._refresh_scene_list()

    def _browse_output(self) -> None:
        start = _resolve_start_dir(self._output_edit.text().strip())
        d = QFileDialog.getExistingDirectory(self, "Select Output Destination", start)
        if d:
            self._output_edit.setText(d)
            self._save_settings()

    def _effective_source_text(self) -> str:
        """Resolve the scene-walking root via project.effective_source."""
        proj = project_manager().current()
        if proj is not None:
            return proj.effective_source(self.STAGE_KEY)
        return self._source_edit.text().strip()

    def _refresh_effective_source_label(self) -> None:
        if self._source_edit.text().strip():
            self._effective_source_label.setText("")
            return
        proj = project_manager().current()
        if proj is None or not proj.scope_root:
            self._effective_source_label.setText(
                "→ no source set (set a project scope root, or fill this field)"
            )
            self._effective_source_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")
            return
        self._effective_source_label.setText(f"→ using scope root: {proj.scope_root}")
        self._effective_source_label.setStyleSheet("color: #89dceb; font-size: 9pt;")

    # -------------------------------------------------------------------------
    # SCENE LIST  (checklist scrubbed from effective_source for *.unity)
    # -------------------------------------------------------------------------

    def _refresh_scene_list(self) -> None:
        """Re-walk the effective_source for *.unity and rebuild the list,
        preserving the persisted check state. Missing previously-selected
        scenes appear at the bottom with a ⚠ glyph."""
        self._suppress_scene_signals = True
        try:
            self._scene_list.clear()
            root_text = self._effective_source_text()
            scrubbed = scrub_scope_for(root_text, "*.unity")
            scrubbed_strs = {str(p).replace("\\", "/") for p in scrubbed}

            # Present scrubbed scenes first, in path order.
            for rel in scrubbed:
                rel_str = str(rel).replace("\\", "/")
                item = QListWidgetItem(rel_str)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                state = Qt.Checked if rel_str in self._selected_scenes else Qt.Unchecked
                item.setCheckState(state)
                item.setData(Qt.UserRole, rel_str)
                self._scene_list.addItem(item)

            # Then any persisted selections that no longer resolve.
            missing = sorted(self._selected_scenes - scrubbed_strs)
            for rel_str in missing:
                item = QListWidgetItem(f"⚠ {rel_str}  (missing from scope)")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setData(Qt.UserRole, rel_str)
                item.setForeground(Qt.darkYellow)
                item.setToolTip(
                    "This scene was selected previously but is not under the "
                    "current effective source. Click 'Clear Missing' to drop it."
                )
                self._scene_list.addItem(item)
        finally:
            self._suppress_scene_signals = False

    def _on_scene_item_changed(self, item) -> None:
        if self._suppress_scene_signals:
            return
        rel = item.data(Qt.UserRole)
        if not rel:
            return
        if item.checkState() == Qt.Checked:
            self._selected_scenes.add(rel)
        else:
            self._selected_scenes.discard(rel)
        self._save_settings()

    def _select_all_scenes(self) -> None:
        self._suppress_scene_signals = True
        try:
            for i in range(self._scene_list.count()):
                item = self._scene_list.item(i)
                item.setCheckState(Qt.Checked)
                rel = item.data(Qt.UserRole)
                if rel:
                    self._selected_scenes.add(rel)
        finally:
            self._suppress_scene_signals = False
        self._save_settings()

    def _clear_scene_selection(self) -> None:
        self._suppress_scene_signals = True
        try:
            for i in range(self._scene_list.count()):
                self._scene_list.item(i).setCheckState(Qt.Unchecked)
            self._selected_scenes.clear()
        finally:
            self._suppress_scene_signals = False
        self._save_settings()

    def _clear_missing_scenes(self) -> None:
        root_text = self._effective_source_text()
        scrubbed = {str(p).replace("\\", "/") for p in scrub_scope_for(root_text, "*.unity")}
        self._selected_scenes &= scrubbed
        self._refresh_scene_list()
        self._save_settings()

    # ── Project prefab inventory (read from F-4 outputs) ───────────────

    def _refresh_project_prefabs_label(self, project) -> None:
        """Show how many converted prefabs are available to resolve scene
        references, derived from `project.outputs.asset_processor.prefabs`.
        Updated on every apply_project + on status_changed."""
        if project is None:
            self._project_prefabs_label.setText(
                "(no project loaded — converted prefabs cannot be resolved)"
            )
            self._project_prefabs_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")
            return
        outputs = project.outputs.get("asset_processor", {})
        prefab_records = outputs.get("prefabs", {})
        sel_count = len(project.stage_settings("asset_processor").get("selected_prefabs", []) or [])
        if prefab_records:
            self._project_prefabs_label.setText(
                f"{len(prefab_records)} prefab(s) available from the last Prefab Processor "
                f"run. Selected scenes will resolve references against these. "
                f"({sel_count} prefab(s) currently marked for processing.)"
            )
            self._project_prefabs_label.setStyleSheet("color: #a6e3a1; font-size: 9pt;")
        elif sel_count > 0:
            self._project_prefabs_label.setText(
                f"{sel_count} prefab(s) selected in the Prefab Processor tab, but the "
                f"prefab run hasn't completed yet — scene references won't resolve "
                f"until you Process Assets first."
            )
            self._project_prefabs_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")
        else:
            self._project_prefabs_label.setText(
                "No prefabs available yet. Open the Prefab Processor tab to mark "
                "prefabs and run the conversion before processing scenes."
            )
            self._project_prefabs_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")

    # ── Last-run per-level breakdown (post-conversion details) ─────────

    def _refresh_last_run_details(self, project) -> None:
        """Populate the per-level breakdown of the last scene conversion.
        Hidden until `project.outputs.scene_converter.scenes` has entries."""
        while self._last_run_box_lay.count():
            item = self._last_run_box_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if project is None:
            self._last_run_box.setVisible(False)
            return
        outputs = project.outputs.get("scene_converter", {})
        scenes = outputs.get("scenes", {})
        last_run = outputs.get("last_run")
        if not last_run or not scenes:
            self._last_run_box.setVisible(False)
            return

        header = QLabel(
            f"{len(scenes)} level(s) generated · Last run {last_run}"
        )
        header.setStyleSheet("color: #a6e3a1; font-size: 9pt; font-weight: bold;")
        self._last_run_box_lay.addWidget(header)
        for name, rec in sorted(scenes.items()):
            stem = name.replace(".unity", "")
            entities = rec.get("entities", 0)
            refs     = rec.get("prefab_references", 0)
            blanks   = rec.get("blanks", 0)
            missing  = len(rec.get("missing_prefabs", []) or [])
            written  = rec.get("written_at", "")
            out_path = rec.get("output_path", "?")
            line1 = QLabel(
                f"  • {stem} → {out_path}  ·  {written}"
            )
            line1.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            line1.setWordWrap(True)
            self._last_run_box_lay.addWidget(line1)
            line2 = QLabel(
                f"        {entities} entities · {refs} prefab refs · "
                f"{blanks} blanks · {missing} missing"
            )
            color = "#fab387" if missing else "#a6adc8"
            line2.setStyleSheet(f"color: {color}; font-size: 9pt;")
            self._last_run_box_lay.addWidget(line2)
        self._last_run_box.setVisible(True)

    def _on_status_changed(self, stage_key: str) -> None:
        # Refresh both the cross-stage inventory (when prefab outputs change)
        # and the per-level breakdown (when scene outputs change).
        proj = project_manager().current()
        if stage_key == "asset_processor":
            self._refresh_project_prefabs_label(proj)
        elif stage_key == self.STAGE_KEY:
            self._refresh_last_run_details(proj)
            self._refresh_project_prefabs_label(proj)

    # -------------------------------------------------------------------------
    # PREFAB DIRECTORY LIST
    # -------------------------------------------------------------------------

    # Legacy `prefab_dirs` UI removed in F-4. The Scene Converter derives
    # its prefab database from `project.outputs.asset_processor.prefabs` —
    # see `_collect_prefab_db_paths` below — so the user no longer manages
    # the list explicitly. The schema field stays for backward compat.

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
        output = self._output_edit.text().strip()
        if not output:
            QMessageBox.critical(self, "Error", "Please select an output destination folder.")
            return
        if not self._selected_scenes:
            QMessageBox.critical(self, "Error",
                "No scenes selected. Check at least one scene in the list.")
            return

        # Resolve each selected scene to an absolute path via the effective source.
        root_text = self._effective_source_text()
        if not root_text:
            QMessageBox.critical(self, "Error",
                "No source set (this tab's override is blank and the project has "
                "no scope root). Selected scenes cannot be resolved.")
            return
        root = Path(root_text)

        resolved: list = []
        missing:  list = []
        for rel in sorted(self._selected_scenes):
            abs_path = root / rel
            if abs_path.is_file():
                resolved.append(abs_path)
            else:
                missing.append(rel)

        if missing:
            txt = "\n".join(f"  • {m}" for m in missing)
            reply = QMessageBox.question(
                self, "Some scenes missing",
                f"{len(missing)} selected scene(s) do not exist:\n{txt}\n\n"
                f"Continue with the {len(resolved)} that do?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.No:
                return
        if not resolved:
            QMessageBox.critical(self, "Error", "No selected scenes exist on disk.")
            return

        # Derive the prefab search dirs from the project's prefab outputs.
        # F-4 dropped the manual `prefab_dirs` UI; the Stage 1 output_path
        # is the canonical location for converted prefabs.
        prefab_search_dirs = self._collect_prefab_db_paths()
        if not prefab_search_dirs:
            reply = QMessageBox.question(self, "No prefab inventory",
                "The project has no Prefab Processor outputs yet, so scene "
                "references won't resolve to any prefabs. Continue anyway "
                "(all instances will be recorded as missing)?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        self._save_settings()
        self._convert_btn.setEnabled(False)
        self._log_edit.clear()
        self._last_run_totals = {}
        project_manager().set_processing(self.STAGE_KEY, True)

        self._worker = WorkerThread(
            self._do_multi_conversion, resolved, output, prefab_search_dirs,
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _collect_prefab_db_paths(self) -> list:
        """Build the list of directories Stage 2's PrefabDatabase should scan
        for converted .prefab files. F-4 derives this from
        `project.stages.asset_processor.output_path`; any legacy
        `prefab_dirs` entries are appended for backwards compat with
        projects that point at shared prefab libraries outside the project
        output."""
        dirs: list = []
        proj = project_manager().current()
        if proj is not None:
            ap_cfg = proj.stage_settings("asset_processor")
            ap_out = (ap_cfg.get("output_path") or "").strip()
            if ap_out:
                # Stage 1 writes prefabs into <output>/Prefabs/.
                dirs.append(str(Path(ap_out) / "Prefabs"))
        for d in (self._prefab_dirs or []):
            if d and d not in dirs:
                dirs.append(d)
        return dirs

    def _do_multi_conversion(self, scenes: list, output_dir: str,
                             prefab_dirs: list, log) -> str:
        """Serial multi-scene conversion. Each scene gets its own
        UnitySceneConverter, output goes into <output>/<SceneName>/."""
        from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter

        log("\n" + "=" * 60)
        log("STARTING MULTI-SCENE CONVERSION")
        log("=" * 60)
        log(f"Scenes : {len(scenes)}")
        log(f"Output : {output_dir}")
        log(f"Prefab search dirs: {len(prefab_dirs)}")
        log("=" * 60)

        prefab_db = PrefabDatabase()
        for d in prefab_dirs:
            prefab_db.add_search_directory(Path(d))

        # Pull Stage-1 outputs out of the project so the per-scene converters
        # can resolve entity-map and asset-index lookups without sidecar files.
        proj = project_manager().current()
        ap_outputs = (proj.outputs.get("asset_processor", {}) if proj else {})
        ap_prefabs = ap_outputs.get("prefabs", {})  # guid_or_stem → record
        entity_maps_by_stem: dict = {}
        for record in ap_prefabs.values():
            stem = Path(record.get("output_path", "")).stem
            if stem:
                entity_maps_by_stem[stem] = record
        asset_index_for_scene = {
            "materials": dict(ap_outputs.get("materials", {})),
            "meshes":    dict(ap_outputs.get("meshes",    {})),
            "prefabs":   {g: r.get("source_path", "") for g, r in ap_prefabs.items()},
        }

        totals = {
            "scenes_converted":      0,
            "total_entities":        0,
            "total_prefab_refs":     0,
            "total_missing_prefabs": 0,
            "failures":              [],
        }
        # Per-scene records accumulated into project.outputs.scene_converter.
        scene_records: dict = {}
        # Coverage from the last scene that converted (Stage 2's coverage
        # is global to the run rather than per-scene; this is one source).
        last_coverage: dict = {}

        for i, scene_path in enumerate(scenes, 1):
            scene_stem    = scene_path.stem
            scene_out_dir = Path(output_dir) / scene_stem
            scene_out_dir.mkdir(parents=True, exist_ok=True)
            level_prefab  = scene_out_dir / f"{scene_stem}.prefab"

            log(f"\n[{i}/{len(scenes)}] {scene_path.name}  →  {scene_out_dir.name}/")
            try:
                conv = UnitySceneConverter(
                    prefab_db, log_callback=log,
                    entity_maps_by_stem=entity_maps_by_stem,
                    asset_index=asset_index_for_scene,
                )
                conv.parse_unity_scene(str(scene_path))
                log(f"  Parsed {len(conv.game_objects)} GameObject(s)")
                prefab_instances = sum(
                    1 for go in conv.game_objects.values() if go.is_prefab_instance
                )
                log(f"  Prefab instances: {prefab_instances}, "
                    f"resolved: {len(conv.prefab_references)}, "
                    f"missing: {len(conv.missing_prefabs)}")

                total, refs, blanks = conv.create_o3de_level(
                    str(level_prefab), scene_out_dir
                )
                conv.finalize(scene_out_dir)

                # Record this scene's outputs for the project file.
                try:
                    output_rel = str(level_prefab.relative_to(Path(output_dir)))
                except Exception:
                    output_rel = level_prefab.name
                scene_records[scene_path.name] = {
                    "output_path":       output_rel.replace("\\", "/"),
                    "entities":          total,
                    "prefab_references": refs,
                    "blanks":            blanks,
                    "missing_prefabs":   sorted(conv.missing_prefabs),
                    "written_at":        _utc_now_iso(),
                }
                last_coverage = conv.to_coverage()

                totals["scenes_converted"]      += 1
                totals["total_entities"]        += total
                totals["total_prefab_refs"]     += refs
                totals["total_missing_prefabs"] += len(conv.missing_prefabs)
                log(f"  ✓ Wrote {level_prefab.name}")
            except Exception as exc:
                log(f"  ✗ Scene failed: {exc}")
                totals["failures"].append(scene_path.name)

        log("\n" + "=" * 60)
        log("CONVERSION COMPLETE!")
        log("=" * 60)
        log(f"Scenes converted   : {totals['scenes_converted']}/{len(scenes)}")
        log(f"Total entities     : {totals['total_entities']}")
        log(f"Total prefab refs  : {totals['total_prefab_refs']}")
        log(f"Total missing refs : {totals['total_missing_prefabs']}")
        if totals["failures"]:
            log(f"Failures           : {', '.join(totals['failures'])}")
        log("=" * 60)

        run_ts = _utc_now_iso()
        had_errors = (totals["total_missing_prefabs"] > 0
                      or len(totals["failures"]) > 0)
        sstatus = "warn" if had_errors else "ok"

        project_manager().update_outputs(self.STAGE_KEY, {
            "last_run":        run_ts,
            "last_status":     sstatus,
            "last_input_hash": input_hash_for(self.STAGE_KEY, project_manager().current()),
            "scenes":          scene_records,
            "coverage":        last_coverage,
        })

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":                run_ts,
            "scenes_converted":        totals["scenes_converted"],
            "scenes_total":            len(scenes),
            "total_entities":          totals["total_entities"],
            "total_prefab_references": totals["total_prefab_refs"],
            "total_missing_prefabs":   totals["total_missing_prefabs"],
        })
        self._last_run_totals = totals

        return (
            f"Scenes: {totals['scenes_converted']}/{len(scenes)}  |  "
            f"Entities: {totals['total_entities']}  |  "
            f"Prefab refs: {totals['total_prefab_refs']}  |  "
            f"Missing: {totals['total_missing_prefabs']}"
        )

    def _on_finished(self, success: bool, summary: str) -> None:
        self._convert_btn.setEnabled(True)
        project_manager().set_processing(self.STAGE_KEY, False)
        if success:
            QMessageBox.information(self, "Conversion Complete", summary)
        else:
            QMessageBox.critical(self, "Conversion Failed", summary)


# =============================================================================
# TAB 3 — MESH (stub for F-5)
# =============================================================================

class _InventoryStubTab(QWidget):
    """Shared scaffolding for the Mesh and Material stub tabs.

    Both render the same shape:
      - intro section explaining the cross-stage relationship
      - inventory list populated from `project.outputs.asset_processor.<key>`
        (filled by Prefab Processor runs)
      - last-run details footer
      - disabled Process button (real processing arrives with F-5/F-6)

    Subclasses set:
      STAGE_KEY        — informational only (no project schema yet)
      OUTPUTS_KEY      — sub-key under outputs.asset_processor (meshes/materials)
      TITLE            — tab title for the inventory section
      EMPTY_MSG        — placeholder when no inventory exists
      FUTURE_F         — "F-5" / "F-6" — surfaced in the disabled Process button
    """

    STAGE_KEY:    str = ""
    OUTPUTS_KEY:  str = ""
    TITLE:        str = ""
    EMPTY_MSG:    str = ""
    FUTURE_F:     str = ""

    def __init__(self):
        super().__init__()
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # Intro section.
        intro_box, intro_lay = _section_groupbox(self.TITLE)
        intro = QLabel(
            f"{self.TITLE} populates from the Prefab Processor's last run. "
            f"Run the Prefab Processor first; the inventory below will "
            f"populate, and Stage 1 will hold the extracted {self.OUTPUTS_KEY} "
            f"in the project file under outputs.asset_processor.{self.OUTPUTS_KEY}."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        intro_lay.addWidget(intro)
        root.addWidget(intro_box)

        # Inventory section (always visible; shows EMPTY_MSG when blank).
        inv_box, inv_lay = _section_groupbox("Inventory")
        self._inv_list = QListWidget()
        _bound_list_height(self._inv_list, min_h=140, max_h=260)
        inv_lay.addWidget(self._inv_list)
        self._inv_summary = QLabel("")
        self._inv_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._inv_summary.setWordWrap(True)
        inv_lay.addWidget(self._inv_summary)
        root.addWidget(inv_box)

        # Last-run details (mirrors the pattern used in Prefab + Scene tabs).
        self._last_run_box = _section_groupbox("Last Run Details")[0]
        self._last_run_box_lay = self._last_run_box.layout()
        self._last_run_box.setVisible(False)
        root.addWidget(self._last_run_box)

        # Action row — Process button is disabled; tooltip explains why.
        process_btn = QPushButton(f"Process ({self.FUTURE_F})")
        process_btn.setObjectName("primary")
        process_btn.setEnabled(False)
        process_btn.setToolTip(
            f"Not yet implemented — arrives with {self.FUTURE_F}. The Mesh / "
            f"Material processing stages will live here."
        )
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch(1)
        action_row.addWidget(process_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    def apply_project(self, project) -> None:
        self._refresh_inventory(project)
        self._refresh_last_run(project)

    def _on_status_changed(self, stage_key: str) -> None:
        # We listen for asset_processor updates because that's where our
        # inventory comes from.
        if stage_key != "asset_processor":
            return
        self.apply_project(project_manager().current())

    def _refresh_inventory(self, project) -> None:
        self._inv_list.clear()
        if project is None:
            self._inv_summary.setText("(no project loaded)")
            return
        outputs = project.outputs.get("asset_processor", {})
        inventory = outputs.get(self.OUTPUTS_KEY, {}) or {}
        if not inventory:
            self._inv_summary.setText(self.EMPTY_MSG)
            return

        for key, value in sorted(inventory.items(), key=lambda kv: str(kv[1])):
            # Materials store guid → asset_hint (string).
            # Meshes store guid → output stem (string).
            display = f"{value}      [guid {key[:8]}…]"
            item = QListWidgetItem(display)
            item.setToolTip(f"GUID: {key}\nValue: {value}")
            self._inv_list.addItem(item)

        prefab_count = len(outputs.get("prefabs", {}))
        last_run     = outputs.get("last_run", "")
        self._inv_summary.setText(
            f"{len(inventory)} {self.OUTPUTS_KEY} from {prefab_count} prefab(s) "
            f"· Last Prefab Processor run: {last_run or '(never)'}"
        )

    def _refresh_last_run(self, project) -> None:
        while self._last_run_box_lay.count():
            item = self._last_run_box_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if project is None:
            self._last_run_box.setVisible(False)
            return
        outputs = project.outputs.get("asset_processor", {})
        inventory = outputs.get(self.OUTPUTS_KEY, {}) or {}
        last_run  = outputs.get("last_run")
        if not last_run or not inventory:
            self._last_run_box.setVisible(False)
            return

        header = QLabel(
            f"{len(inventory)} {self.OUTPUTS_KEY} extracted · Last run {last_run}"
        )
        header.setStyleSheet("color: #a6e3a1; font-size: 9pt; font-weight: bold;")
        self._last_run_box_lay.addWidget(header)
        shown_limit = 20
        for i, (key, value) in enumerate(sorted(inventory.items(), key=lambda kv: str(kv[1]))):
            if i >= shown_limit:
                break
            label = QLabel(f"  • {value}  (guid {key[:8]}…)")
            label.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            label.setWordWrap(True)
            self._last_run_box_lay.addWidget(label)
        overflow = len(inventory) - shown_limit
        if overflow > 0:
            more = QLabel(f"  … and {overflow} more")
            more.setStyleSheet("color: #6c7086; font-size: 9pt; font-style: italic;")
            self._last_run_box_lay.addWidget(more)
        self._last_run_box.setVisible(True)


# =============================================================================
# F-5: Multi-edit numeric field
# =============================================================================

class _FloatField(QLineEdit):
    """Single-line float field for multi-select editing of mesh overrides.

    States:
      - `set_common(value)`: all selected meshes share this value → field
        displays it.
      - `set_common(None)`: selected meshes have differing values → field
        clears its text and shows the `…` placeholder.
      - `set_disabled_blank()`: no selection → field is empty + disabled.

    Emits `committed(float)` only when the user finishes editing with a
    parseable value AND the field isn't programmatically suppressed."""

    committed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        validator = QDoubleValidator(self)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.setValidator(validator)
        self.setFixedWidth(70)
        self.setAlignment(Qt.AlignRight)
        self._suppress = False
        self.editingFinished.connect(self._on_editing_finished)

    def set_common(self, value) -> None:
        """If `value` is None → mixed-state (placeholder `…`).
        Otherwise display the value."""
        self._suppress = True
        self.setEnabled(True)
        if value is None:
            self.setText("")
            self.setPlaceholderText("…")
        else:
            self.setText(f"{value:g}")
            self.setPlaceholderText("")
        self._suppress = False

    def set_disabled_blank(self) -> None:
        self._suppress = True
        self.setText("")
        self.setPlaceholderText("")
        self.setEnabled(False)
        self._suppress = False

    def _on_editing_finished(self) -> None:
        if self._suppress or not self.isEnabled():
            return
        text = self.text().strip()
        if not text:
            return
        try:
            self.committed.emit(float(text))
        except ValueError:
            pass


# =============================================================================
# TAB 3 — MESH (F-5 — defaults + per-mesh overrides)
# =============================================================================

# Field schema for both defaults + overrides. Each entry: (key, display label,
# kind). Kinds: 'bool', 'vec3'. Used to drive the form-rendering code below.
_MESH_FIELDS = [
    ("zero_position",    "Zero position on import",     "bool"),
    ("default_position", "Default position (X / Y / Z)", "vec3"),
    ("default_rotation", "Default rotation (X / Y / Z)", "vec3"),
    ("physx_mesh",       "Generate PhysX collision mesh", "bool"),
    ("auto_center",      "Auto-center single-mesh (⚙)",  "bool"),
    ("auto_rotation",    "Auto Y-up→Z-up rotation (⚙)",  "bool"),
]


# =============================================================================
# SHARED PATCH PLUMBING
# =============================================================================
# The F-9 Patch worker (`IntegratedAssetProcessor.patch()`) re-emits dirty
# materials AND meshes in a single pass. Every patch entry point — the
# Materials tab button, the Meshes tab button, and Mission Command's
# "Patch All" — drives that one operation, so they share this plumbing.
#
# Passing BOTH material_settings and mesh_settings is mandatory: the mesh
# loop recomputes each mesh's input hash from the effective mesh_settings,
# so a patch started without them would diff against empty defaults, flag
# every mesh dirty, and re-emit assetinfo that drops the user's rotation /
# position overrides. The same hazard applies to materials in reverse.
# Earlier per-tab workers each passed only their own half — fixed 2026-05-28.

def _patch_settings_snapshot(proj):
    """Return ``(source_root, output_root, material_settings, mesh_settings,
    state_index)`` for a patch run, or ``None`` when the project has no
    source/output configured (patch needs the Prefab Processor folders)."""
    ap = proj.stage_settings("asset_processor")
    source_root = ap.get("source_path") or str(proj.scope_root or "")
    output_root = ap.get("output_path") or ""
    if not source_root or not output_root:
        return None
    return (
        source_root,
        output_root,
        copy.deepcopy(proj.stage_settings("material_processor")),
        copy.deepcopy(proj.stage_settings("mesh_processor")),
        copy.deepcopy(proj.outputs.get("state_index") or {}),
    )


def _run_full_patch(source_root, output_root, material_settings,
                    mesh_settings, state_index, log) -> str:
    """Shared Patch worker body — re-emits dirty materials + meshes.
    Returns a JSON string the finish handlers decode. ``asset_hint_root``
    is derived in ``IntegratedAssetProcessor.__init__`` from the output
    root relative to the O3DE project root; it must NOT be overridden
    here (doing so was the 2026-05-28 hint-root regression)."""
    from integrated_asset_processor import IntegratedAssetProcessor
    log("=" * 60)
    log("PATCH — re-emit dirty materials + meshes")
    log("=" * 60)
    cfg = get_config()
    proc = IntegratedAssetProcessor(
        Path(source_root), Path(output_root),
        log_callback=log,
        convert_smoothness_to_roughness=cfg["convert_smoothness_to_roughness"],
        material_settings=material_settings,
        mesh_settings=mesh_settings,
        state_index=state_index,
    )
    summary = proc.patch()
    return json.dumps({
        "materials_dirty":     summary["materials_dirty"],
        "materials_emitted":   summary["materials_emitted"],
        "meshes_dirty":        summary["meshes_dirty"],
        "meshes_emitted":      summary["meshes_emitted"],
        "meshes_need_reparse": summary["meshes_need_reparse"],
        "state":               proc.state_index(),
    })


def _decode_patch_payload(payload: str) -> dict:
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _merge_patch_state(proj, run_state) -> None:
    """Merge a patch run's resulting state_index back onto the project."""
    if not run_state:
        return
    existing = dict(proj.outputs.get("state_index") or {})
    for bucket_name, bucket in run_state.items():
        merged = dict(existing.get(bucket_name) or {})
        merged.update(bucket)
        existing[bucket_name] = merged
    project_manager().update_outputs("state_index", existing)


def _format_patch_message(info: dict) -> str:
    """Human-readable summary covering materials, meshes, and meshes that
    need a full Run All. Used by every patch finish handler so the report
    is consistent no matter which button started it."""
    mat_d   = info.get("materials_dirty")     or []
    mat_e   = info.get("materials_emitted")   or []
    msh_d   = info.get("meshes_dirty")        or []
    msh_e   = info.get("meshes_emitted")      or []
    reparse = info.get("meshes_need_reparse") or []
    lines = []
    if mat_d:
        lines.append(f"Materials: {len(mat_d)} dirty · {len(mat_e)} re-emitted")
    if msh_d:
        lines.append(f"Meshes: {len(msh_d)} dirty · {len(msh_e)} re-emitted")
    if reparse:
        lines.append(
            f"⚠ {len(reparse)} mesh(es) need a full Run All "
            f"(cached node map missing or stale)"
        )
    if not lines:
        return "Nothing to patch — all materials and meshes are in sync."
    return "\n".join(lines)


class MeshTab(QWidget):
    """Mesh preprocessing — F-5.

    Layout (top to bottom):
      1. Default Mesh Settings — global values used when a mesh has no
         override entry.
      2. Mesh Inventory — read-only list of meshes from
         `outputs.asset_processor.meshes`. Multi-selectable. Meshes with
         overrides get a ★ marker.
      3. Selection Overrides — appears when ≥1 mesh is selected. Fields
         reflect common values across the selection (or `…` for mixed).
         Editing a field applies to every selected mesh.
      4. Last Run Details — same pattern as Prefab + Scene tabs.

    Mesh entries are NEVER de-selectable: they reflect the meshes the
    Prefab Processor produced, and removing them would break prefab /
    scene dependencies. The multi-selection here is purely for editing
    overrides, not for inclusion/exclusion.
    """

    STAGE_KEY = "mesh_processor"

    def __init__(self):
        super().__init__()
        self._suppress_field_signals = False
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Default Mesh Settings ───────────────────────────────────────
        defaults_box, defaults_lay = _section_groupbox("Default Mesh Settings")
        info = QLabel(
            "Project-wide defaults applied to every mesh unless an override "
            "exists for that mesh below. Changes here automatically affect "
            "every mesh that doesn't have its own override."
        )
        info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        info.setWordWrap(True)
        defaults_lay.addWidget(info)

        self._default_fields = self._build_field_form(defaults_lay, scope="defaults")
        root.addWidget(defaults_box)

        # ── Prefab Output ───────────────────────────────────────────────
        wrap_box, wrap_lay = _section_groupbox("Prefab Output")
        self._wrapper_editor_only_cb = QCheckBox("Make prefab wrappers Editor-only")
        self._wrapper_editor_only_cb.setToolTip(
            "Emit each converted prefab's ContainerEntity wrapper as an "
            "editor-only entity (dissolved at runtime, leaving its content "
            "entities). On by default."
        )
        self._wrapper_editor_only_cb.stateChanged.connect(
            lambda state: self._on_wrapper_editor_only_changed(state == Qt.Checked)
        )
        wrap_lay.addWidget(self._wrapper_editor_only_cb)
        root.addWidget(wrap_box)

        # ── Mesh Inventory ──────────────────────────────────────────────
        inv_box, inv_lay = _section_groupbox("Mesh Inventory")
        inv_info = QLabel(
            "Meshes the Prefab Processor produced. Selection is for editing "
            "overrides only — meshes can't be de-selected without breaking "
            "the prefabs that reference them. ★ marks meshes with overrides."
        )
        inv_info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        inv_info.setWordWrap(True)
        inv_lay.addWidget(inv_info)

        self._inv_list = QListWidget()
        _bound_list_height(self._inv_list, min_h=140, max_h=240)
        self._inv_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._inv_list.itemSelectionChanged.connect(self._on_selection_changed)
        inv_lay.addWidget(self._inv_list)

        self._inv_summary = QLabel("")
        self._inv_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._inv_summary.setWordWrap(True)
        inv_lay.addWidget(self._inv_summary)
        root.addWidget(inv_box)

        # ── Selection Overrides ─────────────────────────────────────────
        self._override_box, override_lay = _section_groupbox("Selection Overrides")
        self._override_header = QLabel("Select one or more meshes above to edit.")
        self._override_header.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._override_header.setWordWrap(True)
        override_lay.addWidget(self._override_header)

        self._override_fields = self._build_field_form(override_lay, scope="override")

        self._clear_override_btn = QPushButton("Clear Override for Selection")
        self._clear_override_btn.clicked.connect(self._clear_override_for_selection)
        self._clear_override_btn.setEnabled(False)
        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        clear_row.addWidget(self._clear_override_btn)
        override_lay.addLayout(clear_row)
        root.addWidget(self._override_box)

        # ── Last Run Details ────────────────────────────────────────────
        self._last_run_box = _section_groupbox("Last Run Details")[0]
        self._last_run_box_lay = self._last_run_box.layout()
        self._last_run_box.setVisible(False)
        root.addWidget(self._last_run_box)

        # ── Patch button — mesh side of the F-9 patch worker ─────────────
        # Re-emits .assetinfo for every mesh whose effective mesh_settings
        # / source mtime drifted since the last Run All, plus meshes whose
        # output file was edited in-engine (the scrub workflow). See
        # `mem:mesh_patch_worker/mesh_patch_worker_plan`.
        self._dirty_summary = QLabel("")
        self._dirty_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._dirty_summary.setWordWrap(True)

        self._patch_btn = QPushButton("Patch Dirty Meshes")
        self._patch_btn.setObjectName("primary")
        self._patch_btn.setToolTip(
            "Re-emit .assetinfo files for every mesh whose effective "
            "mesh_settings / source mtime has drifted since the last "
            "Prefab Processor run, or whose .assetinfo was edited in-engine. "
            "Rows marked ↻ point at outputs missing on disk; rows marked ✎ "
            "have in-engine edits that this action will OVERWRITE."
        )
        self._patch_btn.clicked.connect(self._start_patch)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self._dirty_summary, 1)
        action_row.addStretch(1)
        action_row.addWidget(self._patch_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    def showEvent(self, event) -> None:
        """Refresh inventory + dirty markers on tab activation so the
        externally-modified detection catches in-engine edits made while
        the user was on a different tab. Mirrors MaterialTab."""
        super().showEvent(event)
        proj = project_manager().current()
        if proj is not None:
            self.apply_project(proj)

    def _build_field_form(self, parent_lay: QVBoxLayout, *, scope: str) -> dict:
        """Construct widgets for every field in `_MESH_FIELDS`. Returns
        `{field_key: widgets}` where the value for `bool` is a single
        QCheckBox and for `vec3` is a 3-tuple of `_FloatField`s."""
        widgets: dict = {}
        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 4, 0, 4)
        for key, label, kind in _MESH_FIELDS:
            if kind == "bool":
                cb = QCheckBox(label)
                cb.setTristate(scope == "override")  # only the override form supports mixed
                cb.stateChanged.connect(
                    lambda state, k=key, s=scope:
                        self._on_field_changed(s, k, state == Qt.Checked)
                )
                widgets[key] = cb
                form.addRow(cb)
            elif kind == "vec3":
                fx, fy, fz = _FloatField(), _FloatField(), _FloatField()
                for axis, w in (("x", fx), ("y", fy), ("z", fz)):
                    w.committed.connect(
                        lambda value, k=key, a=axis, s=scope:
                            self._on_field_changed(s, (k, a), value)
                    )
                widgets[key] = (fx, fy, fz)
                row = _hbox(QLabel("X:"), fx, QLabel("Y:"), fy, QLabel("Z:"), fz,
                            trailing_stretch=True)
                form.addRow(label, _wrap_layout(row))
        parent_lay.addLayout(form)
        return widgets

    # -------------------------------------------------------------------------
    # APPLY / REFRESH
    # -------------------------------------------------------------------------

    def apply_project(self, project) -> None:
        self._refresh_defaults_fields(project)
        self._refresh_inventory(project)
        self._refresh_override_fields()
        self._refresh_last_run(project)

    def _on_status_changed(self, stage_key: str) -> None:
        # Inventory comes from asset_processor outputs; refresh on those.
        # Our own stage updates also need re-render (defaults changes).
        if stage_key not in ("asset_processor", self.STAGE_KEY):
            return
        self.apply_project(project_manager().current())

    def _refresh_defaults_fields(self, project) -> None:
        if project is None:
            return
        cfg = project.stage_settings(self.STAGE_KEY)
        defaults = cfg.get("defaults", {}) or {}
        self._suppress_field_signals = True
        try:
            self._wrapper_editor_only_cb.setChecked(
                bool(cfg.get("prefab_wrapper_editor_only", True)))
            for key, _, kind in _MESH_FIELDS:
                if kind == "bool":
                    cb = self._default_fields[key]
                    cb.setChecked(bool(defaults.get(key, False)))
                elif kind == "vec3":
                    vec = defaults.get(key, [0.0, 0.0, 0.0])
                    if not isinstance(vec, (list, tuple)) or len(vec) != 3:
                        vec = [0.0, 0.0, 0.0]
                    for axis_idx, w in enumerate(self._default_fields[key]):
                        w.set_common(float(vec[axis_idx]))
        finally:
            self._suppress_field_signals = False

    def _refresh_inventory(self, project) -> None:
        self._inv_list.clear()
        if project is None:
            self._inv_summary.setText("(no project loaded)")
            self._dirty_summary.setText("")
            return
        ap = project.outputs.get("asset_processor", {})
        meshes = ap.get("meshes", {}) or {}
        mp = project.stage_settings(self.STAGE_KEY)
        overrides = mp.get("overrides", {}) or {}

        # State-index lookup for dirty + externally-modified markers.
        state_index_root = project.outputs.get("state_index") or {}
        state_meshes     = state_index_root.get("meshes") or {}
        ext_mod          = detect_externally_modified(state_index_root)
        externally_modified = ext_mod.get("meshes") or set()

        if not meshes:
            self._inv_summary.setText(
                "No meshes extracted yet. Mark prefabs and run the Prefab Processor."
            )
            self._dirty_summary.setText("")
            return

        override_count = 0
        dirty_count    = 0
        ext_mod_count  = 0

        for guid, stem in sorted(meshes.items(), key=lambda kv: str(kv[1]).lower()):
            has_override = guid in overrides

            state_entry = state_meshes.get(guid)
            if state_entry is None:
                is_dirty = True
            else:
                outputs = state_entry.get("output_files") or []
                is_dirty = (not outputs) or any(not Path(p).exists() for p in outputs)

            is_externally_modified = guid in externally_modified

            # ⚙ auto-compensation flags recorded by the converter.
            auto_flags  = (state_entry or {}).get("auto_flags") or {}
            auto_center = auto_flags.get("auto_center")
            auto_y_up   = bool(auto_flags.get("y_up"))
            has_auto    = (auto_center is not None) or auto_y_up

            if has_override:
                override_count += 1
            if is_dirty:
                dirty_count += 1
            if is_externally_modified:
                ext_mod_count += 1

            prefix = ""
            if has_override:
                prefix += "★ "
            if has_auto:
                prefix += "⚙ "
            if is_dirty:
                prefix += "↻ "
            if is_externally_modified:
                prefix += "✎ "
            if not prefix:
                prefix = "   "

            text = f"{prefix}{stem}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, guid)
            tip_lines = [f"GUID: {guid}", f"Output stem: {stem}"]
            if has_override:
                tip_lines.append("Override applied")
            if auto_center is not None:
                tip_lines.append(f"⚙ Auto-centered (per-node) → {auto_center}")
            if auto_y_up:
                tip_lines.append("⚙ Y-up FBX → auto +90° X rotation")
            if is_dirty:
                tip_lines.append("Dirty — output missing or stale; run Patch")
            if is_externally_modified:
                tip_lines.append(
                    "✎ Output edited in-engine since last emit — "
                    "re-patching will OVERWRITE those changes."
                )
            item.setToolTip("\n".join(tip_lines))
            # Foreground colour priority (most → least urgent): external-mod
            # (orange — destructive risk) > override (cyan, bold).
            if is_externally_modified:
                item.setForeground(QColor("#fab387"))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif has_override:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                item.setForeground(Qt.cyan)
            self._inv_list.addItem(item)

        summary_parts = [
            f"{len(meshes)} mesh(es)",
            f"{override_count} with override(s)",
            f"{dirty_count} dirty",
        ]
        if ext_mod_count:
            summary_parts.append(f"{ext_mod_count} edited externally")
        self._inv_summary.setText(" · ".join(summary_parts))

        # Dirty summary band — external mods take precedence (destructive risk).
        if ext_mod_count:
            self._dirty_summary.setText(
                f"✎ {ext_mod_count} mesh(es) modified in-engine since "
                f"last emit — re-patching will overwrite their changes."
            )
            self._dirty_summary.setStyleSheet(
                "color: #fab387; font-size: 9pt; font-weight: bold;"
            )
        elif dirty_count:
            self._dirty_summary.setText(
                f"↻ {dirty_count} mesh(es) need re-emission"
            )
            self._dirty_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        else:
            self._dirty_summary.setText("")

    def _selected_mesh_guids(self) -> list:
        guids: list = []
        for item in self._inv_list.selectedItems():
            g = item.data(Qt.UserRole)
            if g:
                guids.append(g)
        return guids

    def _on_selection_changed(self) -> None:
        self._refresh_override_fields()

    def _refresh_override_fields(self) -> None:
        """Populate the override editor based on current selection. Show
        common values, `…` for mixed, disable when nothing selected."""
        guids = self._selected_mesh_guids()
        proj = project_manager().current()
        if not guids or proj is None:
            self._override_header.setText("Select one or more meshes above to edit.")
            self._clear_override_btn.setEnabled(False)
            for key, _, kind in _MESH_FIELDS:
                if kind == "bool":
                    cb = self._override_fields[key]
                    self._suppress_field_signals = True
                    cb.setCheckState(Qt.Unchecked)
                    cb.setEnabled(False)
                    self._suppress_field_signals = False
                elif kind == "vec3":
                    for w in self._override_fields[key]:
                        w.set_disabled_blank()
            return

        cfg = proj.stage_settings(self.STAGE_KEY)
        defaults  = cfg.get("defaults",  {}) or {}
        overrides = cfg.get("overrides", {}) or {}

        any_override = any(g in overrides for g in guids)
        self._override_header.setText(
            f"{len(guids)} mesh(es) selected · "
            f"{sum(1 for g in guids if g in overrides)} with override(s) · "
            f"editing applies to all selected"
        )
        self._clear_override_btn.setEnabled(any_override)

        self._suppress_field_signals = True
        try:
            for key, _, kind in _MESH_FIELDS:
                # Compute the effective value for each selected mesh, then
                # check whether they all agree.
                values = []
                for g in guids:
                    eff = overrides.get(g, {}).get(key, defaults.get(key))
                    values.append(eff)
                common = self._common_value(values)

                if kind == "bool":
                    cb = self._override_fields[key]
                    cb.setEnabled(True)
                    if common is None:
                        cb.setCheckState(Qt.PartiallyChecked)
                    else:
                        cb.setCheckState(Qt.Checked if common else Qt.Unchecked)
                elif kind == "vec3":
                    # Each axis is independently mixed/common.
                    if common is None:
                        # Per-axis comparison
                        axis_commons = []
                        for axis_idx in range(3):
                            axis_values = [
                                (v[axis_idx] if isinstance(v, (list, tuple)) and len(v) == 3
                                 else 0.0)
                                for v in values
                            ]
                            axis_commons.append(self._common_value(axis_values))
                    else:
                        axis_commons = list(common)
                    for axis_idx, w in enumerate(self._override_fields[key]):
                        ac = axis_commons[axis_idx]
                        if ac is None:
                            w.set_common(None)
                        else:
                            w.set_common(float(ac))
        finally:
            self._suppress_field_signals = False

    @staticmethod
    def _common_value(values: list):
        """Return the shared value if every entry matches, else None."""
        if not values:
            return None
        first = values[0]
        for v in values[1:]:
            if v != first:
                return None
        return first

    # -------------------------------------------------------------------------
    # FIELD EDIT HANDLERS
    # -------------------------------------------------------------------------

    def _on_wrapper_editor_only_changed(self, checked: bool) -> None:
        """Project-wide toggle (not a per-mesh field): emit prefab
        ContainerEntity wrappers as editor-only entities."""
        if self._suppress_field_signals:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        cfg["prefab_wrapper_editor_only"] = bool(checked)
        pm.update_stage(self.STAGE_KEY, cfg)

    def _on_field_changed(self, scope: str, key, value) -> None:
        """`scope` is 'defaults' or 'override'. `key` is either a field key
        ('zero_position', 'default_position', ...) or a (vec_key, axis)
        tuple for per-axis float commits."""
        if self._suppress_field_signals:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return

        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        defaults  = dict(cfg.get("defaults",  {}) or {})
        overrides = dict(cfg.get("overrides", {}) or {})

        if scope == "defaults":
            self._apply_field_value(defaults, key, value)
        else:  # 'override' — applies to every selected mesh
            for g in self._selected_mesh_guids():
                entry = dict(overrides.get(g, {}))
                self._apply_field_value(entry, key, value)
                overrides[g] = entry

        # Normalise: any override entry value-equal to defaults across
        # every key it carries is redundant — drop it so the ★ marker
        # honestly reflects "differs from default".
        overrides = self._prune_redundant_overrides(overrides, defaults)

        cfg["defaults"]  = defaults
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)

        # Re-render: defaults change cascades to inventory + override view,
        # override change updates the inventory marker + override readout.
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    @staticmethod
    def _apply_field_value(target: dict, key, value) -> None:
        """Apply a single committed value into a defaults / override dict."""
        if isinstance(key, tuple):
            vec_key, axis = key
            axis_idx = {"x": 0, "y": 1, "z": 2}[axis]
            vec = list(target.get(vec_key, [0.0, 0.0, 0.0]))
            while len(vec) < 3:
                vec.append(0.0)
            vec[axis_idx] = float(value)
            target[vec_key] = vec
        else:
            target[key] = value

    @staticmethod
    def _values_equal(a, b, tol: float = 1e-6) -> bool:
        """Field-value equality with vec3 tolerance. ``None`` on either
        side means "no opinion" and never compares equal to a real value."""
        if a is None or b is None:
            return False
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            return all(abs(float(x) - float(y)) < tol for x, y in zip(a, b))
        if isinstance(a, bool) or isinstance(b, bool):
            return a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < tol
        return a == b

    @classmethod
    def _prune_redundant_overrides(cls, overrides: dict, defaults: dict) -> dict:
        """Strip any GUID whose override entry is value-equal to ``defaults``
        on every key the entry carries. Missing keys in the entry are
        "no opinion" and don't block pruning. Returns a fresh dict."""
        out = {}
        for guid, entry in (overrides or {}).items():
            if not isinstance(entry, dict) or not entry:
                continue   # empty entries are also redundant — drop
            if all(cls._values_equal(entry[k], defaults.get(k)) for k in entry):
                continue   # value-equal to defaults → drop
            out[guid] = entry
        return out

    def _clear_override_for_selection(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in self._selected_mesh_guids():
            overrides.pop(g, None)
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    # -------------------------------------------------------------------------
    # LAST-RUN DETAILS (same shape as the other tabs)
    # -------------------------------------------------------------------------

    def _refresh_last_run(self, project) -> None:
        while self._last_run_box_lay.count():
            item = self._last_run_box_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if project is None:
            self._last_run_box.setVisible(False)
            return
        outputs = project.outputs.get("asset_processor", {})
        meshes  = outputs.get("meshes", {}) or {}
        last_run = outputs.get("last_run")
        if not last_run or not meshes:
            self._last_run_box.setVisible(False)
            return

        header = QLabel(
            f"{len(meshes)} mesh(es) extracted · Last Prefab Processor run {last_run}"
        )
        header.setStyleSheet("color: #a6e3a1; font-size: 9pt; font-weight: bold;")
        self._last_run_box_lay.addWidget(header)
        shown_limit = 20
        for i, (g, stem) in enumerate(sorted(meshes.items(), key=lambda kv: str(kv[1]).lower())):
            if i >= shown_limit:
                break
            label = QLabel(f"  • {stem}  (guid {g[:8]}…)")
            label.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            label.setWordWrap(True)
            self._last_run_box_lay.addWidget(label)
        overflow = len(meshes) - shown_limit
        if overflow > 0:
            more = QLabel(f"  … and {overflow} more")
            more.setStyleSheet("color: #6c7086; font-size: 9pt; font-style: italic;")
            self._last_run_box_lay.addWidget(more)
        self._last_run_box.setVisible(True)

    # -------------------------------------------------------------------------
    # PATCH — re-emit dirty .assetinfo files
    # -------------------------------------------------------------------------
    # Mesh side of the F-9 patch worker. Spawns a WorkerThread that runs
    # `IntegratedAssetProcessor.patch()`; only the mesh loop fires here
    # (materials run in parallel from MaterialTab's button). See
    # `mem:mesh_patch_worker/mesh_patch_worker_plan` §I.3.
    # -------------------------------------------------------------------------

    def _start_patch(self) -> None:
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            QMessageBox.information(self, "Patch", "Open a project first.")
            return
        snapshot = _patch_settings_snapshot(proj)
        if snapshot is None:
            QMessageBox.warning(
                self, "Patch",
                "Patch needs the Prefab Processor's source + output folders "
                "(set on the Prefabs tab). Run the Prefab Processor at least "
                "once before patching.",
            )
            return
        source_root, output_root, material_settings, mesh_settings, state_index = snapshot

        self._patch_btn.setEnabled(False)
        self._patch_worker = WorkerThread(
            _run_full_patch, source_root, output_root,
            material_settings, mesh_settings, state_index,
        )
        self._patch_worker.emitter.message.connect(self._on_patch_log)
        self._patch_worker.finished.connect(self._on_patch_finished)
        self._patch_worker.start()

    def _on_patch_log(self, msg: str) -> None:
        # No dedicated log widget — surface via stdout so the worker's
        # output joins the Prefab tab log via the shared log stream.
        print(msg)

    def _on_patch_finished(self, success: bool, payload: str) -> None:
        self._patch_btn.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "Patch", f"Patch failed:\n{payload}")
            return
        info = _decode_patch_payload(payload)
        pm = project_manager()
        proj = pm.current()
        if proj is not None:
            _merge_patch_state(proj, info.get("state") or {})
        QMessageBox.information(self, "Patch", _format_patch_message(info))
        self.apply_project(pm.current())


def _wrap_layout(layout) -> QWidget:
    """Wrap a QLayout in a transparent QWidget so it can be used wherever a
    widget is expected (e.g. QFormLayout.addRow's value slot)."""
    w = QWidget()
    w.setLayout(layout)
    return w


# =============================================================================
# TAB 4 — MATERIALS (F-6 — shader mappings + per-material overrides)
# =============================================================================

# O3DE StandardPBR texture slots that the material tab exposes for rebinding.
# Order is the visual order in the override section.
_MATERIAL_TEXTURE_SLOTS = [
    "baseColor",
    "normal",
    "metallic",
    "roughness",
    "occlusion",
    "emissive",
]


class _PathField(QWidget):
    """Editable file-path field with multi-select semantics. Row layout:
    [QLineEdit] [Browse…] [Clear]. Same `set_common(value)` /
    `set_common(None)` / `set_disabled_blank()` API as `_FloatField` so
    the multi-edit machinery reads the same way.

    `committed(str)` fires when the user finishes editing (Enter, focus
    loss, or picks a file via Browse). `cleared()` fires when the user
    hits Clear (distinguishes "set to empty" from "remove the override").
    """

    committed = Signal(str)
    cleared   = Signal()

    def __init__(self, parent=None, *, dialog_caption: str = "Select file",
                 dialog_filter: str = "All files (*.*)"):
        super().__init__(parent)
        self._dialog_caption = dialog_caption
        self._dialog_filter  = dialog_filter
        self._suppress = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._edit = QLineEdit()
        self._edit.editingFinished.connect(self._on_editing_finished)
        lay.addWidget(self._edit, 1)

        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setCursor(Qt.PointingHandCursor)
        self._browse_btn.setMinimumWidth(0)
        self._browse_btn.clicked.connect(self._on_browse)
        lay.addWidget(self._browse_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setMinimumWidth(0)
        self._clear_btn.clicked.connect(self.cleared.emit)
        lay.addWidget(self._clear_btn)

    def set_common(self, value) -> None:
        """`value=None` → mixed-state placeholder. Empty string → cleared
        (no path set). Otherwise display the path."""
        self._suppress = True
        self.setEnabled(True)
        self._edit.setEnabled(True)
        self._browse_btn.setEnabled(True)
        self._clear_btn.setEnabled(True)
        if value is None:
            self._edit.setText("")
            self._edit.setPlaceholderText("…")
        elif value == "":
            self._edit.setText("")
            self._edit.setPlaceholderText("(no path set)")
        else:
            self._edit.setText(str(value))
            self._edit.setPlaceholderText("")
        self._suppress = False

    def set_disabled_blank(self) -> None:
        self._suppress = True
        self._edit.setText("")
        self._edit.setPlaceholderText("")
        self.setEnabled(False)
        self._suppress = False

    def _on_editing_finished(self) -> None:
        if self._suppress or not self.isEnabled():
            return
        self.committed.emit(self._edit.text().strip())

    def _on_browse(self) -> None:
        start = _resolve_start_path(self._edit.text().strip())
        f, _ = QFileDialog.getOpenFileName(
            self, self._dialog_caption, start, self._dialog_filter,
        )
        if f:
            self._edit.setText(f)
            self.committed.emit(f)


class ShaderMappingsDialog(QDialog):
    """Popout editor for the project's Unity-shader → O3DE-materialtype table.

    Rows are populated from DETECTED shaders only — i.e. the union of shader
    names extracted across the project's material metadata. Mapped shaders
    render with a path-field showing the current target; unmapped shaders
    render the same way but with a ⚠ marker on the label so it's obvious
    what needs attention.

    Edits live-save through `project_manager.update_stage` and emit
    `mappings_changed` so the owning `MaterialTab` can refresh its summary
    and inventory immediately.
    """

    STAGE_KEY = "material_processor"

    mappings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shader Mappings")
        self.setModal(False)
        self.resize(640, 480)
        self._suppress_signals = False
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(lambda _p: self._populate(_p))
        self._populate(pm.current())

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        info = QLabel(
            "Map each detected Unity shader to an O3DE .materialtype. "
            "Unmapped shaders (⚠) fall back to the project's default "
            "materialtype. Edits save immediately."
        )
        info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        info.setWordWrap(True)
        outer.addWidget(info)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        self._summary.setWordWrap(True)
        outer.addWidget(self._summary)

        # Scrollable list of per-shader rows.
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setSpacing(6)
        self._rows_layout.setContentsMargins(0, 4, 0, 4)
        self._rows_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._rows_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        outer.addWidget(button_box)

    # -------------------------------------------------------------------------
    # POPULATE
    # -------------------------------------------------------------------------

    def _populate(self, project) -> None:
        # Tear down existing rows (keep the trailing stretch).
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if project is None:
            self._summary.setText("(no project loaded)")
            return

        cfg = project.stage_settings(self.STAGE_KEY)
        mappings = dict(cfg.get("shader_mappings", {}) or {})
        profile_names = sorted((cfg.get("shader_profiles") or {}).keys())

        ap_meta = (project.outputs.get("asset_processor", {}) or {}).get(
            "material_metadata", {}) or {}
        detected = sorted({
            (rec or {}).get("shader_name", "")
            for rec in ap_meta.values()
            if (rec or {}).get("shader_name")
        })

        if not detected:
            empty = QLabel(
                "(no shaders detected yet — run the Prefab Processor first)"
            )
            empty.setStyleSheet(
                "color: #6c7086; font-size: 9pt; font-style: italic;"
            )
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, empty)
            self._summary.setText("0 detected · 0 mapped · 0 unmapped")
            return

        # Unmapped shaders first so they're visible without scrolling.
        unmapped = [s for s in detected if s not in mappings]
        mapped   = [s for s in detected if s in mappings]
        ordered  = unmapped + mapped

        for sname in ordered:
            self._rows_layout.insertWidget(
                self._rows_layout.count() - 1,
                self._build_row(sname, mappings.get(sname, ""), profile_names),
            )

        self._summary.setText(
            f"{len(detected)} detected · {len(mapped)} mapped · "
            f"{len(unmapped)} unmapped"
        )

    def _build_row(self, shader_name: str, current_profile: str,
                   profile_names: list) -> QWidget:
        has_mapping = bool(current_profile)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        label = QLabel(f"{'  ' if has_mapping else '⚠ '}{shader_name}")
        label.setMinimumWidth(280)
        label.setToolTip(
            "Mapping present" if has_mapping else
            "Unmapped — falls back to the default profile"
        )
        label.setStyleSheet(
            "color: #cdd6f4; font-size: 9pt;" if has_mapping else
            "color: #f9e2af; font-size: 9pt;"
        )
        lay.addWidget(label, 1)

        # Profile picker (F-9). Replaces the legacy materialtype-path field.
        # The combo lists every profile in the project's shader_profiles
        # library; F-9 ships exactly one ("Default — Anything to PBR"), F-10
        # will add the authoring UI for additional profiles.
        combo = QComboBox()
        for name in profile_names:
            combo.addItem(name)
        # Preserve a value the user already had even if the profile no longer
        # exists (rendered with a distinguishable prefix so the mismatch is
        # visible). F-10's profile editor will surface a proper repair flow.
        if current_profile and current_profile not in profile_names:
            combo.addItem(f"(missing) {current_profile}")
            combo.setCurrentText(f"(missing) {current_profile}")
        elif current_profile:
            combo.setCurrentText(current_profile)
        elif profile_names:
            combo.setCurrentIndex(-1)
        combo.currentTextChanged.connect(
            lambda val, s=shader_name: self._on_mapping_changed(
                s, val if not val.startswith("(missing) ") else ""
            )
        )
        lay.addWidget(combo, 2)
        return row

    # -------------------------------------------------------------------------
    # EDIT HANDLERS
    # -------------------------------------------------------------------------

    def _on_mapping_changed(self, shader_name: str, value: str) -> None:
        if self._suppress_signals:
            return
        pm   = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        mappings = dict(cfg.get("shader_mappings", {}) or {})
        if value:
            mappings[shader_name] = value
        else:
            mappings.pop(shader_name, None)
        cfg["shader_mappings"] = mappings
        pm.update_stage(self.STAGE_KEY, cfg)
        # Repopulate so the row reorders (unmapped → top) and the label
        # marker flips.
        self._populate(proj)
        self.mappings_changed.emit()


class MaterialTab(QWidget):
    """Material preprocessing — F-6.

    Layout (top to bottom):
      1. Default Material Settings — global fallback target materialtype
         applied to every material when no shader-specific mapping
         exists.
      2. Shader Mappings — one row per Unity shader name detected across
         the project. Each row has an editable O3DE materialtype path.
         Shaders detected in inventory but missing from the mapping
         render with a ⚠ marker.
      3. Material Inventory — read-only list (multi-select for editing)
         showing material name + shader + override marker.
      4. Selection Overrides — appears when ≥1 material is selected.
         Editable: target materialtype + per-slot texture rebinds.
         Multi-edit semantics: common shown, mixed shown as `…`.
      5. Last Run Details — same pattern as Mesh / Scene / Prefab tabs.

    Materials are NEVER de-selectable from the inventory — removing them
    would break prefab + scene dependencies. Selection drives override
    editing only.
    """

    STAGE_KEY = "material_processor"

    def __init__(self):
        super().__init__()
        self._suppress_field_signals = False
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        pm.status_changed.connect(self._on_status_changed)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Default Material Settings ───────────────────────────────────
        defaults_box, defaults_lay = _section_groupbox("Default Material Settings")
        info = QLabel(
            "Fallback shader profile applied when a Unity shader has no "
            "explicit entry in the mappings list. Profiles bundle the "
            "target O3DE materialtype with the property remap (texture "
            "slots, scalar/colour properties). New profiles are authored "
            "in the upcoming Profile Editor."
        )
        info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        info.setWordWrap(True)
        defaults_lay.addWidget(info)

        self._default_profile = QComboBox()
        self._default_profile.currentTextChanged.connect(
            self._on_default_profile_changed
        )
        defaults_form = QFormLayout()
        defaults_form.setSpacing(8)
        defaults_form.setContentsMargins(0, 4, 0, 4)
        defaults_form.addRow("Default profile:", self._default_profile)
        defaults_lay.addLayout(defaults_form)
        root.addWidget(defaults_box)

        # ── Shader Mappings (summary + popout editor) ───────────────────
        self._shader_box, shader_lay = _section_groupbox("Shader Mappings")
        shader_info = QLabel(
            "Unity shader → O3DE materialtype. Detected shaders without a "
            "mapping fall back to the default above and mark their materials "
            "with ⚠. Open the editor to assign mappings."
        )
        shader_info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        shader_info.setWordWrap(True)
        shader_lay.addWidget(shader_info)

        self._shader_summary = QLabel("")
        self._shader_summary.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
        self._shader_summary.setWordWrap(True)
        shader_lay.addWidget(self._shader_summary)

        self._shader_status = QLabel("")
        self._shader_status.setWordWrap(True)
        shader_lay.addWidget(self._shader_status)

        edit_btn = QPushButton("Edit Mappings…")
        edit_btn.clicked.connect(self._open_mappings_dialog)
        edit_row = QHBoxLayout()
        edit_row.addStretch(1)
        edit_row.addWidget(edit_btn)
        shader_lay.addLayout(edit_row)
        root.addWidget(self._shader_box)

        # Dialog instance is lazy-created when the user opens it. Kept as an
        # attribute so the same window is reused across opens.
        self._shader_dialog = None

        # ── Material Inventory ──────────────────────────────────────────
        inv_box, inv_lay = _section_groupbox("Material Inventory")
        inv_info = QLabel(
            "Materials produced by the Prefab Processor. Multi-select to "
            "edit overrides — materials can't be de-selected here without "
            "breaking the prefabs that reference them. ★ marks materials "
            "with overrides; ⚠ marks materials whose shader has no mapping."
        )
        inv_info.setStyleSheet("color: #6c7086; font-size: 9pt;")
        inv_info.setWordWrap(True)
        inv_lay.addWidget(inv_info)

        self._inv_list = QListWidget()
        _bound_list_height(self._inv_list, min_h=140, max_h=240)
        self._inv_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._inv_list.itemSelectionChanged.connect(self._refresh_override_fields)
        inv_lay.addWidget(self._inv_list)

        self._inv_summary = QLabel("")
        self._inv_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._inv_summary.setWordWrap(True)
        inv_lay.addWidget(self._inv_summary)
        root.addWidget(inv_box)

        # ── Selection Overrides ─────────────────────────────────────────
        self._override_box, override_lay = _section_groupbox("Selection Overrides")
        self._override_header = QLabel("Select one or more materials above to edit.")
        self._override_header.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._override_header.setWordWrap(True)
        override_lay.addWidget(self._override_header)

        # Target materialtype override.
        self._override_materialtype = _PathField(
            dialog_caption="Select .materialtype",
            dialog_filter="Material type (*.materialtype);;All files (*.*)",
        )
        self._override_materialtype.committed.connect(
            lambda val: self._on_override_field_changed("materialtype", val)
        )
        self._override_materialtype.cleared.connect(
            lambda: self._on_override_field_cleared("materialtype")
        )

        # Per-slot texture rebind fields.
        self._override_textures: dict = {}
        for slot in _MATERIAL_TEXTURE_SLOTS:
            field = _PathField(
                dialog_caption=f"Select texture for '{slot}'",
                dialog_filter="Image files (*.png *.jpg *.jpeg *.tga *.tif *.tiff *.exr);;"
                              "All files (*.*)",
            )
            field.committed.connect(
                lambda val, s=slot: self._on_override_texture_changed(s, val)
            )
            field.cleared.connect(
                lambda s=slot: self._on_override_texture_cleared(s)
            )
            self._override_textures[slot] = field

        override_form = QFormLayout()
        override_form.setSpacing(8)
        override_form.setContentsMargins(0, 4, 0, 4)
        override_form.addRow("Target materialtype:", self._override_materialtype)
        for slot in _MATERIAL_TEXTURE_SLOTS:
            override_form.addRow(f"Texture · {slot}:", self._override_textures[slot])
        override_lay.addLayout(override_form)

        self._clear_override_btn = QPushButton("Clear Override for Selection")
        self._clear_override_btn.clicked.connect(self._clear_override_for_selection)
        self._clear_override_btn.setEnabled(False)
        clear_row = QHBoxLayout()
        clear_row.addStretch(1)
        clear_row.addWidget(self._clear_override_btn)
        override_lay.addLayout(clear_row)
        root.addWidget(self._override_box)

        # ── Last Run Details ────────────────────────────────────────────
        self._last_run_box = _section_groupbox("Last Run Details")[0]
        self._last_run_box_lay = self._last_run_box.layout()
        self._last_run_box.setVisible(False)
        root.addWidget(self._last_run_box)

        # ── Patch button (F-9.I.5/I.6) ─────────────────────────────────
        # Re-emits only the materials whose inputs (profile / mappings /
        # overrides / source mtime) have drifted since the last run. The
        # full prefab pass still lives on the Prefabs tab; this surface is
        # the cheap iterative loop.
        self._dirty_summary = QLabel("")
        self._dirty_summary.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._dirty_summary.setWordWrap(True)

        self._patch_btn = QPushButton("Patch Dirty Materials")
        self._patch_btn.setObjectName("primary")
        self._patch_btn.setToolTip(
            "Re-emit .material files for every material whose resolved "
            "profile / override / source file has changed since the last "
            "Prefab Processor run. Material rows marked ↻ point at outputs "
            "missing on disk."
        )
        self._patch_btn.clicked.connect(self._start_patch)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self._dirty_summary, 1)
        action_row.addStretch(1)
        action_row.addWidget(self._patch_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    # -------------------------------------------------------------------------
    # APPLY / REFRESH
    # -------------------------------------------------------------------------

    def apply_project(self, project) -> None:
        self._refresh_defaults(project)
        self._refresh_shader_mappings(project)
        self._refresh_inventory(project)
        self._refresh_override_fields()
        self._refresh_last_run(project)

    def showEvent(self, event) -> None:
        """F-9.I.6b — refresh on tab activation so the externally-modified
        detection (output mtime vs `last_emitted`) catches edits made in
        O3DE while the user was on a different tab. The full
        `apply_project` is intentionally re-run rather than just the
        inventory: a user editing a .material in-engine often goes hand in
        hand with editing a .materialtype the profile / default points
        at, and the dependent UI rows should reflect both."""
        super().showEvent(event)
        proj = project_manager().current()
        if proj is not None:
            self.apply_project(proj)

    def _on_status_changed(self, stage_key: str) -> None:
        if stage_key not in ("asset_processor", self.STAGE_KEY):
            return
        self.apply_project(project_manager().current())

    # ── Defaults ────────────────────────────────────────────────────────

    def _refresh_defaults(self, project) -> None:
        self._suppress_field_signals = True
        try:
            self._default_profile.clear()
            if project is None:
                self._default_profile.setEnabled(False)
                return
            self._default_profile.setEnabled(True)
            cfg = project.stage_settings(self.STAGE_KEY)
            profile_names = sorted((cfg.get("shader_profiles") or {}).keys())
            for name in profile_names:
                self._default_profile.addItem(name)
            current = (cfg.get("defaults", {}) or {}).get("profile", "")
            if current and current not in profile_names:
                # Stale default — keep the user's choice visible but flagged so
                # F-10's editor can repair it.
                self._default_profile.addItem(f"(missing) {current}")
                self._default_profile.setCurrentText(f"(missing) {current}")
            elif current:
                self._default_profile.setCurrentText(current)
            elif profile_names:
                self._default_profile.setCurrentIndex(0)
        finally:
            self._suppress_field_signals = False

    def _on_default_profile_changed(self, value: str) -> None:
        if self._suppress_field_signals:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        # Strip the "(missing) " prefix the refresh adds when the saved
        # default points at a profile no longer in the library.
        clean = value[len("(missing) "):] if value.startswith("(missing) ") else value
        if not clean:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        defaults = dict(cfg.get("defaults", {}) or {})
        defaults["profile"] = clean
        cfg["defaults"] = defaults
        pm.update_stage(self.STAGE_KEY, cfg)
        # Refresh shader-mapping summary — unmapped resolution chain ends at
        # this default, so changing it can flip the section status.
        self._refresh_shader_mappings(proj)

    # ── Shader mappings ─────────────────────────────────────────────────

    def _refresh_shader_mappings(self, project) -> None:
        if project is None:
            self._shader_summary.setText("(no project loaded)")
            self._shader_status.setText("")
            self._set_section_warn(False)
            return

        cfg = project.stage_settings(self.STAGE_KEY)
        mappings = dict(cfg.get("shader_mappings", {}) or {})

        ap_meta = (project.outputs.get("asset_processor", {}) or {}).get(
            "material_metadata", {}) or {}
        detected = sorted({
            (rec or {}).get("shader_name", "")
            for rec in ap_meta.values()
            if (rec or {}).get("shader_name")
        })
        mapped   = [s for s in detected if s in mappings]
        unmapped = [s for s in detected if s not in mappings]

        if not detected:
            self._shader_summary.setText(
                "No shaders detected yet — run the Prefab Processor to "
                "populate the mapping list."
            )
            self._shader_status.setText("")
            self._set_section_warn(False)
        else:
            self._shader_summary.setText(
                f"{len(detected)} detected · {len(mapped)} mapped · "
                f"{len(unmapped)} unmapped"
            )
            if unmapped:
                preview = ", ".join(unmapped[:3])
                if len(unmapped) > 3:
                    preview += f", +{len(unmapped) - 3} more"
                self._shader_status.setText(
                    f"⚠ Unmapped: {preview}"
                )
                self._shader_status.setStyleSheet(
                    "color: #f9e2af; font-size: 9pt; font-weight: bold;"
                )
                self._set_section_warn(True)
            else:
                self._shader_status.setText("✓ all detected shaders mapped")
                self._shader_status.setStyleSheet(
                    "color: #a6e3a1; font-size: 9pt;"
                )
                self._set_section_warn(False)

    def _set_section_warn(self, warn: bool) -> None:
        """Toggle a yellow border on the Shader Mappings group box so the
        unmapped-shaders condition is visible at a glance.

        Implemented via a local stylesheet on the box itself rather than a
        global selector so other QGroupBox sections stay untouched.
        """
        if warn:
            self._shader_box.setStyleSheet(
                "QGroupBox { border: 1px solid #f9e2af; border-radius: 4px; "
                "margin-top: 12px; padding-top: 4px; } "
                "QGroupBox::title { color: #f9e2af; }"
            )
        else:
            self._shader_box.setStyleSheet("")

    def _open_mappings_dialog(self) -> None:
        """Lazy-construct + show the popout shader mappings editor. The
        dialog drives edits through `project_manager.update_stage`; we
        listen for `mappings_changed` so the section summary + material
        inventory refresh as edits land."""
        if self._shader_dialog is None:
            self._shader_dialog = ShaderMappingsDialog(self)
            self._shader_dialog.mappings_changed.connect(
                self._on_dialog_mappings_changed
            )
        # Always repopulate from the current project before showing — covers
        # the case where the user ran the prefab processor while the dialog
        # was constructed but hidden.
        self._shader_dialog._populate(project_manager().current())
        self._shader_dialog.show()
        self._shader_dialog.raise_()
        self._shader_dialog.activateWindow()

    def _on_dialog_mappings_changed(self) -> None:
        proj = project_manager().current()
        if proj is None:
            return
        self._refresh_shader_mappings(proj)
        self._refresh_inventory(proj)

    # -------------------------------------------------------------------------
    # F-9.I.6 — Patch dirty materials
    # -------------------------------------------------------------------------

    def _start_patch(self) -> None:
        """Spawn a WorkerThread that runs IntegratedAssetProcessor.patch().
        Snapshots project state on the UI thread so the worker is isolated
        from concurrent edits. The patch covers materials AND meshes —
        see the shared patch plumbing above MeshTab."""
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            QMessageBox.information(self, "Patch", "Open a project first.")
            return
        snapshot = _patch_settings_snapshot(proj)
        if snapshot is None:
            QMessageBox.warning(
                self, "Patch",
                "Patch needs the Prefab Processor's source + output folders "
                "(set on the Prefabs tab). Run the Prefab Processor at least "
                "once before patching.",
            )
            return
        source_root, output_root, material_settings, mesh_settings, state_index = snapshot

        self._patch_btn.setEnabled(False)
        self._patch_worker = WorkerThread(
            _run_full_patch, source_root, output_root,
            material_settings, mesh_settings, state_index,
        )
        self._patch_worker.emitter.message.connect(self._on_patch_log)
        self._patch_worker.finished.connect(self._on_patch_finished)
        self._patch_worker.start()

    def _on_patch_log(self, msg: str) -> None:
        # No dedicated log widget on this tab; surface via the project
        # status bus so the Prefab tab's log shows the patch trail.
        print(msg)

    def _on_patch_finished(self, success: bool, payload: str) -> None:
        self._patch_btn.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "Patch", f"Patch failed:\n{payload}")
            return
        info = _decode_patch_payload(payload)
        pm = project_manager()
        proj = pm.current()
        if proj is not None:
            _merge_patch_state(proj, info.get("state") or {})
        QMessageBox.information(self, "Patch", _format_patch_message(info))
        # Refresh the inventory so any ↻ markers clear.
        self.apply_project(pm.current())

    # ── Inventory ───────────────────────────────────────────────────────

    def _refresh_inventory(self, project) -> None:
        self._inv_list.clear()
        if project is None:
            self._inv_summary.setText("(no project loaded)")
            return
        ap = project.outputs.get("asset_processor", {}) or {}
        meta = ap.get("material_metadata", {}) or {}
        legacy_materials = ap.get("materials", {}) or {}

        # Fall back to the legacy `materials` dict (older runs) when metadata
        # is empty — renders rows without shader info but still listable.
        if not meta and legacy_materials:
            meta = {
                g: {"asset_hint": hint, "shader_name": "", "source_stem": ""}
                for g, hint in legacy_materials.items()
            }

        mp = project.stage_settings(self.STAGE_KEY)
        overrides = mp.get("overrides", {}) or {}
        mappings  = mp.get("shader_mappings", {}) or {}
        # F-9.I.6 — per-material state-index entry (None when no run has
        # recorded the material yet). The cheap dirty check is: was the
        # output ever emitted, and does it still exist on disk?
        state_index_root = project.outputs.get("state_index") or {}
        state_materials  = state_index_root.get("materials") or {}
        # F-9.I.6b — externally-modified set. An entry lands in here when
        # one of its `output_files[i].mtime` is newer than the saved
        # `last_emitted` timestamp — i.e., someone opened the file in O3DE
        # and edited it between the converter's last emission and this
        # refresh. Re-emitting will overwrite those edits.
        ext_mod = detect_externally_modified(state_index_root)
        externally_modified = ext_mod.get("materials") or set()

        if not meta:
            self._inv_summary.setText(
                "No materials extracted yet. Mark prefabs and run the Prefab Processor."
            )
            self._dirty_summary.setText("")
            return

        unmapped_count  = 0
        override_count  = 0
        dirty_count     = 0
        ext_mod_count   = 0
        for guid, rec in sorted(meta.items(),
                                key=lambda kv: str(kv[1].get("source_stem")
                                                   or kv[1].get("asset_hint")
                                                   or kv[0]).lower()):
            stem        = rec.get("source_stem") or rec.get("asset_hint") or guid
            shader      = rec.get("shader_name", "") or "(unknown)"
            has_override = guid in overrides
            has_mapping  = shader in mappings if shader != "(unknown)" else False

            state_entry  = state_materials.get(guid)
            if state_entry is None:
                is_dirty = True
            else:
                outputs = state_entry.get("output_files") or []
                is_dirty = (not outputs) or any(not Path(p).exists() for p in outputs)

            is_externally_modified = guid in externally_modified

            if not has_mapping:
                unmapped_count += 1
            if has_override:
                override_count += 1
            if is_dirty:
                dirty_count += 1
            if is_externally_modified:
                ext_mod_count += 1

            prefix = ""
            if has_override:
                prefix += "★ "
            if not has_mapping:
                prefix += "⚠ "
            if is_dirty:
                prefix += "↻ "
            if is_externally_modified:
                prefix += "✎ "
            if not prefix:
                prefix = "   "

            text = f"{prefix}{stem:<32}  {shader}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, guid)
            tip_lines = [f"GUID: {guid}", f"Shader: {shader}"]
            if rec.get("textures_bound"):
                tip_lines.append(f"Bound slots: {', '.join(rec['textures_bound'])}")
            if has_override:
                tip_lines.append("Override applied")
            if not has_mapping:
                tip_lines.append("Shader has no explicit profile — uses the default profile")
            # F-9 provenance — show which profile (and recorded shader name)
            # last emitted this material's .material on disk. Empty / missing
            # means the file pre-dates the F-9 profile chain entirely
            # (legacy hardcoded extraction) and should be re-emitted to
            # gain provenance.
            if state_entry is not None:
                emitted_profile = state_entry.get("profile_name") or ""
                emitted_shader  = state_entry.get("shader_name")  or ""
                last_emitted    = state_entry.get("last_emitted") or ""
                if emitted_profile:
                    line = f"Last emitted by profile: {emitted_profile}"
                    if emitted_shader and emitted_shader != shader:
                        line += f"  (shader recorded as: {emitted_shader})"
                    tip_lines.append(line)
                else:
                    tip_lines.append(
                        "Last emitted via legacy hardcoded path "
                        "(no F-9 profile recorded — re-emit to capture provenance)."
                    )
                if last_emitted:
                    tip_lines.append(f"Last emitted: {last_emitted}")
            else:
                tip_lines.append(
                    "Never emitted by this converter — output on disk (if any) "
                    "is from a prior tool or hand-authored."
                )
            if is_dirty:
                tip_lines.append("Dirty — output is missing or stale; run Patch")
            if is_externally_modified:
                tip_lines.append(
                    "✎ Output edited in-engine since last emit — "
                    "re-patching will OVERWRITE those changes."
                )
            item.setToolTip("\n".join(tip_lines))
            # Foreground colour priority (most → least urgent): external-mod
            # (orange — destructive risk) > override (cyan, bold) > unmapped
            # (yellow). Dirty is signalled by the ↻ glyph alone since the
            # row's primary attention cue is the marker prefix.
            if is_externally_modified:
                item.setForeground(QColor("#fab387"))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif has_override:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                item.setForeground(Qt.cyan)
            elif not has_mapping:
                item.setForeground(Qt.darkYellow)
            self._inv_list.addItem(item)

        summary_parts = [
            f"{len(meta)} material(s)",
            f"{override_count} with override(s)",
            f"{unmapped_count} with unmapped shader(s)",
            f"{dirty_count} dirty",
        ]
        if ext_mod_count:
            summary_parts.append(f"{ext_mod_count} edited externally")
        self._inv_summary.setText(" · ".join(summary_parts))
        # Dirty summary band — external modifications take precedence
        # because they signal destructive risk, not just stale outputs.
        if ext_mod_count:
            self._dirty_summary.setText(
                f"✎ {ext_mod_count} material(s) modified in-engine since "
                f"last emit — re-patching will overwrite their changes."
            )
            self._dirty_summary.setStyleSheet(
                "color: #fab387; font-size: 9pt; font-weight: bold;"
            )
        elif dirty_count:
            self._dirty_summary.setText(
                f"↻ {dirty_count} material(s) need re-emission"
            )
            self._dirty_summary.setStyleSheet(
                "color: #89dceb; font-size: 9pt; font-weight: bold;"
            )
        else:
            self._dirty_summary.setText("All materials up to date.")
            self._dirty_summary.setStyleSheet(
                "color: #a6e3a1; font-size: 9pt;"
            )

    def _selected_material_guids(self) -> list:
        guids: list = []
        for item in self._inv_list.selectedItems():
            g = item.data(Qt.UserRole)
            if g:
                guids.append(g)
        return guids

    # ── Override editor ─────────────────────────────────────────────────

    def _refresh_override_fields(self) -> None:
        guids = self._selected_material_guids()
        proj  = project_manager().current()
        if not guids or proj is None:
            self._override_header.setText("Select one or more materials above to edit.")
            self._clear_override_btn.setEnabled(False)
            self._override_materialtype.set_disabled_blank()
            for slot, w in self._override_textures.items():
                w.set_disabled_blank()
            return

        cfg = proj.stage_settings(self.STAGE_KEY)
        overrides = cfg.get("overrides", {}) or {}

        # Under the F-9 profile model the override section's
        # "Target materialtype" is the RAW escape hatch — it writes
        # through to override.materialtype directly, bypassing the
        # profile's target_materialtype. The field displays the raw
        # value (or empty / "..." for mixed) so the user can see exactly
        # what they're overriding without it being confused with the
        # profile-driven default.
        def effective_materialtype(g):
            entry = overrides.get(g, {}) or {}
            return entry.get("materialtype", "") or ""

        def effective_texture(g, slot):
            entry = (overrides.get(g, {}) or {}).get("textures", {}) or {}
            return entry.get(slot)  # None if no override for this slot

        any_override = any(g in overrides for g in guids)
        self._override_header.setText(
            f"{len(guids)} material(s) selected · "
            f"{sum(1 for g in guids if g in overrides)} with override(s)"
        )
        self._clear_override_btn.setEnabled(any_override)

        self._suppress_field_signals = True
        try:
            mt_values = [effective_materialtype(g) for g in guids]
            self._override_materialtype.set_common(self._common_value(mt_values))
            for slot, w in self._override_textures.items():
                slot_values = [effective_texture(g, slot) for g in guids]
                w.set_common(self._common_value(slot_values))
        finally:
            self._suppress_field_signals = False

    @staticmethod
    def _common_value(values: list):
        if not values:
            return None
        first = values[0]
        for v in values[1:]:
            if v != first:
                return None
        return first

    def _on_override_field_changed(self, key: str, value) -> None:
        if self._suppress_field_signals:
            return
        guids = self._selected_material_guids()
        if not guids:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in guids:
            entry = dict(overrides.get(g, {}) or {})
            entry[key] = value
            overrides[g] = entry
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    def _on_override_field_cleared(self, key: str) -> None:
        # Remove the field from each selected material's override entry. If
        # the entry becomes empty, drop the whole entry.
        guids = self._selected_material_guids()
        if not guids:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in guids:
            entry = dict(overrides.get(g, {}) or {})
            entry.pop(key, None)
            if entry:
                overrides[g] = entry
            else:
                overrides.pop(g, None)
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    def _on_override_texture_changed(self, slot: str, value: str) -> None:
        if self._suppress_field_signals:
            return
        guids = self._selected_material_guids()
        if not guids:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in guids:
            entry = dict(overrides.get(g, {}) or {})
            textures = dict(entry.get("textures", {}) or {})
            textures[slot] = value
            entry["textures"] = textures
            overrides[g] = entry
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    def _on_override_texture_cleared(self, slot: str) -> None:
        guids = self._selected_material_guids()
        if not guids:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in guids:
            entry = dict(overrides.get(g, {}) or {})
            textures = dict(entry.get("textures", {}) or {})
            textures.pop(slot, None)
            if textures:
                entry["textures"] = textures
            else:
                entry.pop("textures", None)
            if entry:
                overrides[g] = entry
            else:
                overrides.pop(g, None)
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    def _clear_override_for_selection(self) -> None:
        guids = self._selected_material_guids()
        if not guids:
            return
        pm = project_manager()
        proj = pm.current()
        if proj is None:
            return
        cfg = dict(proj.stage_settings(self.STAGE_KEY))
        overrides = dict(cfg.get("overrides", {}) or {})
        for g in guids:
            overrides.pop(g, None)
        cfg["overrides"] = overrides
        pm.update_stage(self.STAGE_KEY, cfg)
        self._refresh_inventory(proj)
        self._refresh_override_fields()

    # ── Last Run Details ────────────────────────────────────────────────

    def _refresh_last_run(self, project) -> None:
        while self._last_run_box_lay.count():
            item = self._last_run_box_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if project is None:
            self._last_run_box.setVisible(False)
            return
        outputs = project.outputs.get("asset_processor", {}) or {}
        meta    = outputs.get("material_metadata", {}) or {}
        legacy  = outputs.get("materials", {}) or {}
        if not meta and legacy:
            meta = {
                g: {"source_stem": "", "asset_hint": hint, "shader_name": ""}
                for g, hint in legacy.items()
            }
        last_run = outputs.get("last_run")
        if not last_run or not meta:
            self._last_run_box.setVisible(False)
            return

        header = QLabel(
            f"{len(meta)} material(s) extracted · Last run {last_run}"
        )
        header.setStyleSheet("color: #a6e3a1; font-size: 9pt; font-weight: bold;")
        self._last_run_box_lay.addWidget(header)
        shown_limit = 20
        for i, (g, rec) in enumerate(sorted(
                meta.items(),
                key=lambda kv: str(kv[1].get("source_stem")
                                   or kv[1].get("asset_hint")
                                   or kv[0]).lower())):
            if i >= shown_limit:
                break
            stem   = rec.get("source_stem") or rec.get("asset_hint") or g
            shader = rec.get("shader_name") or "(unknown)"
            slots  = rec.get("textures_bound") or []
            label = QLabel(
                f"  • {stem}  ·  shader={shader}  ·  "
                f"{len(slots)} texture slot(s)"
            )
            label.setStyleSheet("color: #cdd6f4; font-size: 9pt;")
            label.setWordWrap(True)
            self._last_run_box_lay.addWidget(label)
        overflow = len(meta) - shown_limit
        if overflow > 0:
            more = QLabel(f"  … and {overflow} more")
            more.setStyleSheet("color: #6c7086; font-size: 9pt; font-style: italic;")
            self._last_run_box_lay.addWidget(more)
        self._last_run_box.setVisible(True)


# =============================================================================
# TAB 5 — TERRAIN
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
        self._selected_terrains: set = set()   # absolute paths to TerrainData .asset
        self._suppress_terrain_signals = False
        self._build_ui()
        pm = project_manager()
        pm.project_changed.connect(self.apply_project)
        self.apply_project(pm.current())

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Outer layout holds a scroll area so the tab scrolls vertically
        # when the window is shorter than the natural content height.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Unity Assets Folder ─────────────────────────────────────────
        src_box, src_lay = _section_groupbox("Unity Assets Folder")
        self._source_edit, src_btn = _path_row(
            "Override (blank → use project scope root)"
        )
        src_btn.clicked.connect(self._browse_source)
        self._source_edit.editingFinished.connect(self._refresh_effective_source_label)
        src_lay.addLayout(_hbox(self._source_edit, src_btn))
        self._effective_source_label = QLabel("")
        self._effective_source_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        self._effective_source_label.setWordWrap(True)
        src_lay.addWidget(self._effective_source_label)
        root.addWidget(src_box)

        # ── O3DE Output Folder ──────────────────────────────────────────
        out_box, out_lay = _section_groupbox("O3DE Output Folder")
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        out_lay.addLayout(_hbox(self._output_edit, out_btn))
        info_label = QLabel(
            "  Terrain/Materials/   — one detail .material per splat layer\n"
            "  Terrain/Textures/    — albedo + normal textures (deduped)\n"
            "  Terrain/Heightmaps/  — 16-bit heightmap PNG + world-size sidecar\n"
            "  Terrain/Splatmaps/   — per-layer weight masks\n"
            "  Terrain/Prefabs/     — terrain entity .prefab + .terrain.json manifest"
        )
        info_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        out_lay.addWidget(info_label)
        root.addWidget(out_box)

        # ── Detected Unity Terrains ─────────────────────────────────────
        self._terrain_list = QListWidget()
        self._terrain_list.itemChanged.connect(self._on_terrain_item_changed)
        scan_btn  = QPushButton("Scan for Terrains")
        clear_btn = QPushButton("Clear Selection")
        scan_btn.clicked.connect(self._scan_terrains)
        clear_btn.clicked.connect(self._clear_terrain_selection)
        root.addWidget(_managed_list_section(
            "Detected Unity Terrains  (TerrainData .asset)", self._terrain_list,
            scan_btn, clear_btn,
            min_h=110, max_h=190,
        ))

        # ── Outputs (à la carte) ────────────────────────────────────────
        out_toggle_box, out_toggle_lay = _section_groupbox("Outputs")
        self._output_checks = {}
        for key, label in (
            ("materials", "Detail Materials + Textures"),
            ("heightmap", "Heightmap image"),
            ("splatmaps", "Splatmap weight masks"),
            ("entity",    "Full Terrain Entity (.prefab)"),
        ):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda *_: self._save_settings())
            self._output_checks[key] = cb
            out_toggle_lay.addWidget(cb)
        hint = QLabel(
            "Outputs are independent — tick only \"Detail Materials\" to gather "
            "layer materials without rebuilding the terrain object."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6c7086; font-size: 9pt;")
        out_toggle_lay.addWidget(hint)
        root.addWidget(out_toggle_box)

        # ── Processing Log ──────────────────────────────────────────────
        self._log_edit = _log_widget()
        root.addWidget(_fill_section("Processing Log", self._log_edit), stretch=1)

        # ── Action buttons ──────────────────────────────────────────────
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        self._generate_btn = QPushButton("Generate Terrain Materials")
        self._generate_btn.setObjectName("primary")
        self._generate_btn.clicked.connect(self._start_generation)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(save_log_btn)
        action_row.addStretch(1)
        action_row.addWidget(self._generate_btn)
        root.addLayout(action_row)

        outer.addWidget(_scroll_wrap(content))

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    # ── Project contract ─────────────────────────────────────────────────────
    STAGE_KEY = "terrain_processor"

    def apply_project(self, project) -> None:
        cfg = project.stage_settings(self.STAGE_KEY) if project else {}
        self._source_edit.setText(cfg.get("source_path", ""))
        self._output_edit.setText(cfg.get("output_path", ""))

        # Migration: the old design persisted `selected_materials` (.mat list).
        # v2 is terrain-driven — drop the legacy key and load `selected_terrains`.
        self._selected_terrains = set(cfg.get("selected_terrains", []) or [])

        outputs = cfg.get("outputs")
        if isinstance(outputs, list):
            enabled = set(outputs)
            for key, cb in self._output_checks.items():
                cb.setChecked(key in enabled)

        # Show the persisted terrains without re-scanning (scan is explicit).
        self._rebuild_terrain_list(self._selected_terrains)
        self._refresh_effective_source_label()

    def _refresh_effective_source_label(self) -> None:
        if self._source_edit.text().strip():
            self._effective_source_label.setText("")
            return
        proj = project_manager().current()
        if proj is None or not proj.scope_root:
            self._effective_source_label.setText(
                "→ no source set (set a project scope root, or fill this field)"
            )
            self._effective_source_label.setStyleSheet("color: #f9e2af; font-size: 9pt;")
            return
        self._effective_source_label.setText(f"→ using scope root: {proj.scope_root}")
        self._effective_source_label.setStyleSheet("color: #89dceb; font-size: 9pt;")

    def _collect_stage_settings(self) -> dict:
        return {
            "source_path":       self._source_edit.text(),
            "output_path":       self._output_edit.text(),
            "selected_terrains": sorted(self._selected_terrains),
            "outputs":           self._selected_outputs(),
        }

    def _selected_outputs(self) -> list:
        return [key for key, cb in self._output_checks.items() if cb.isChecked()]

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

    def _effective_source_text(self) -> str:
        proj = project_manager().current()
        if proj is not None:
            return proj.effective_source(self.STAGE_KEY)
        return self._source_edit.text().strip()

    def _scan_terrains(self) -> None:
        """Walk the effective source for binary TerrainData .asset files and
        rebuild the checklist, preserving the current selection."""
        from platforms.unity import terrain_data as _td
        if not _td.unitypy_available():
            QMessageBox.warning(
                self, "UnityPy required",
                "Scanning Unity terrains needs the 'UnityPy' package.\n\n"
                "Install it with:  pip install -r requirements.txt")
            return

        root = self._effective_source_text()
        if not root or not os.path.isdir(root):
            QMessageBox.warning(self, "No source",
                "Set a Unity Assets source (this field or the project scope root) "
                "before scanning.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = _td.scan_for_terrains(Path(root))
        finally:
            QApplication.restoreOverrideCursor()

        found_strs = [str(p) for p in found]
        # Keep selections that still resolve; auto-select brand-new finds so a
        # fresh scan is immediately actionable.
        known = set(found_strs)
        self._selected_terrains = (self._selected_terrains & known) or set()
        for s in found_strs:
            self._selected_terrains.add(s)

        self._rebuild_terrain_list(set(found_strs))
        self._log(f"Scan found {len(found_strs)} terrain(s) under {root}")
        self._save_settings()

    def _rebuild_terrain_list(self, paths: set) -> None:
        """Populate the checkable terrain list from ``paths`` (absolute strings).
        Items in ``_selected_terrains`` are checked."""
        self._suppress_terrain_signals = True
        try:
            self._terrain_list.clear()
            for path in sorted(paths | self._selected_terrains):
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.UserRole, path)
                item.setToolTip(path)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if path in self._selected_terrains else Qt.Unchecked)
                self._terrain_list.addItem(item)
        finally:
            self._suppress_terrain_signals = False

    def _on_terrain_item_changed(self, item) -> None:
        if self._suppress_terrain_signals:
            return
        path = item.data(Qt.UserRole)
        if not path:
            return
        if item.checkState() == Qt.Checked:
            self._selected_terrains.add(path)
        else:
            self._selected_terrains.discard(path)
        self._save_settings()

    def _clear_terrain_selection(self) -> None:
        self._suppress_terrain_signals = True
        try:
            for i in range(self._terrain_list.count()):
                self._terrain_list.item(i).setCheckState(Qt.Unchecked)
        finally:
            self._suppress_terrain_signals = False
        self._selected_terrains.clear()
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
        proj = project_manager().current()
        source = proj.effective_source(self.STAGE_KEY) if proj else self._source_edit.text().strip()
        output = self._output_edit.text().strip()

        if not source or not output:
            QMessageBox.critical(self, "Error",
                "Please set both a Unity Assets source (this field or the project "
                "scope root) and an output folder.")
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Error", f"Source folder not found:\n{source}")
            return
        if not self._selected_terrains:
            QMessageBox.warning(self, "Warning",
                "No terrains selected. Click 'Scan for Terrains' and tick at "
                "least one TerrainData .asset to convert.")
            return
        if not self._selected_outputs():
            QMessageBox.warning(self, "Warning",
                "No outputs selected. Tick at least one output (Detail Materials, "
                "Heightmap, Splatmaps, or Full Terrain Entity).")
            return

        self._save_settings()
        self._generate_btn.setEnabled(False)
        self._log_edit.clear()
        project_manager().set_processing(self.STAGE_KEY, True)

        self._worker = WorkerThread(
            self._do_generation, source, output,
            sorted(self._selected_terrains), self._selected_outputs(),
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_generation(self, source_path: str, output_path: str,
                       terrain_paths: list, outputs: list, log) -> str:
        from platforms.unity.terrain import TerrainProcessor

        log("\n" + "=" * 60)
        log("STARTING TERRAIN CONVERSION")
        log("=" * 60)
        log(f"Source   : {source_path}")
        log(f"Output   : {output_path}")
        log(f"Terrains : {len(terrain_paths)}")
        log(f"Outputs  : {', '.join(outputs)}")

        processor = TerrainProcessor(
            Path(source_path), Path(output_path), log_callback=log,
        )

        totals = {
            "materials_written": 0, "textures_written": 0,
            "heightmaps_written": 0, "splatmaps_written": 0,
            "prefabs_written": 0, "errors": 0,
        }
        terrain_records: dict = {}
        run_ts = _utc_now_iso()

        for tp in terrain_paths:
            r = processor.process_terrain(Path(tp), set(outputs))
            totals["materials_written"]  += r["materials_written"]
            totals["textures_written"]   += r["textures_written"]
            totals["heightmaps_written"] += r["heightmaps_written"]
            totals["splatmaps_written"]  += r["splatmaps_written"]
            totals["prefabs_written"]    += 1 if r["prefab_written"] else 0
            totals["errors"]             += len(r["errors"])
            terrain_records[str(tp)] = {
                "source_path":       str(tp),
                "layers":            r["layers"],
                "outputs":           list(outputs),
                "materials_written": r["materials_written"],
                "prefab_written":    r["prefab_written"],
                "written_at":        run_ts,
            }

        log("\n" + "=" * 60)
        log("CONVERSION COMPLETE!")
        log("=" * 60)
        log(f"Terrains          : {len(terrain_paths)}")
        log(f"Materials written : {totals['materials_written']}")
        log(f"Textures written  : {totals['textures_written']}")
        log(f"Heightmaps written: {totals['heightmaps_written']}")
        log(f"Splatmaps written : {totals['splatmaps_written']}")
        log(f"Prefabs written   : {totals['prefabs_written']}")
        log(f"Errors            : {totals['errors']}")
        log("=" * 60)

        sstatus = "warn" if totals["errors"] else "ok"

        project_manager().update_outputs(self.STAGE_KEY, {
            "last_run":        run_ts,
            "last_status":     sstatus,
            "last_input_hash": input_hash_for(self.STAGE_KEY, project_manager().current()),
            "terrains":        terrain_records,
            "coverage":        {"errors": []},
        })

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":           run_ts,
            "terrains_total":     len(terrain_paths),
            "materials_written":  totals["materials_written"],
            "textures_written":   totals["textures_written"],
            "heightmaps_written": totals["heightmaps_written"],
            "splatmaps_written":  totals["splatmaps_written"],
            "prefabs_written":    totals["prefabs_written"],
            "errors":             totals["errors"],
        })

        return (
            f"Terrains: {len(terrain_paths)}  |  "
            f"Materials: {totals['materials_written']}  |  "
            f"Heightmaps: {totals['heightmaps_written']}  |  "
            f"Splatmaps: {totals['splatmaps_written']}  |  "
            f"Prefabs: {totals['prefabs_written']}  |  "
            f"Errors: {totals['errors']}"
        )

    def _on_finished(self, success: bool, summary: str) -> None:
        self._generate_btn.setEnabled(True)
        project_manager().set_processing(self.STAGE_KEY, False)
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

# (import_name, pypi_name, role_text, is_hard_dep, platform_gate)
# platform_gate=None → always relevant; otherwise only checked when the active
# project platform matches (so e.g. UnityPy is only flagged for Unity sources).
DEPENDENCIES = [
    ("PySide6", "PySide6", "GUI framework",                              True,  None),
    ("yaml",    "PyYAML",  "Unity prefab / scene YAML parser",           True,  None),
    ("PIL",     "Pillow",  "Smoothness→Roughness texture re-bake",       False, None),
    ("UnityPy", "UnityPy", "Unity terrain (TerrainData .asset) parser",  False, "unity"),
]


def _active_platform() -> str:
    """Lowercase active platform of the current project, defaulting to unity."""
    try:
        proj = project_manager().current()
        if proj is not None:
            return (proj.active_platform or "unity").strip().lower()
    except Exception:
        pass
    return "unity"


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


def check_dependencies() -> list:
    """Probe each entry in DEPENDENCIES. Returns a list of dicts:

        [{import_name, pypi_name, role, is_hard, installed, version}, …]

    Drives both ConfigTab._refresh_dep_status and the startup banner.
    Flushes the import cache first so deps installed via pip *after* the
    app started are detected on a probe rather than returning stale-no.
    """
    import importlib
    importlib.invalidate_caches()

    active = _active_platform()
    results = []
    for import_name, pypi_name, role, is_hard, platform_gate in DEPENDENCIES:
        # Skip platform-gated deps that don't apply to the active platform —
        # UnityPy is only a concern when converting a Unity source.
        if platform_gate is not None and platform_gate != active:
            continue
        installed, version = _probe_dependency(import_name, pypi_name)
        results.append({
            "import_name": import_name,
            "pypi_name":   pypi_name,
            "role":        role,
            "is_hard":     is_hard,
            "installed":   installed,
            "version":     version,
        })
    return results


def signature_for(missing: list) -> str:
    """Stable signature for a missing-dependency set. Used to key the
    dismiss-banner persistence so dismissing once for {Pillow} does
    NOT suppress the banner if PyYAML *also* goes missing later."""
    return ",".join(sorted(m["pypi_name"] for m in missing))


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
        for import_name, pypi_name, role, is_hard, platform_gate in DEPENDENCIES:
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

        Delegates probing to module-level `check_dependencies()` so the
        startup banner and this tab share a single source of truth. The
        install command lists only the missing packages by default; when
        nothing is missing it falls back to the "install all" form so a
        fresh clone can copy a single line to bootstrap everything.
        """
        # Platform-gated deps (e.g. UnityPy) drop out of check_dependencies()
        # when they don't apply — hide their labels so no blank row lingers.
        for lbl in self._dep_status_labels.values():
            lbl.setVisible(False)

        missing_pypi: list = []
        for entry in check_dependencies():
            pypi_name = entry["pypi_name"]
            lbl = self._dep_status_labels[pypi_name]
            lbl.setVisible(True)
            if entry["installed"]:
                ver = entry["version"] or "version unknown"
                lbl.setText(f"  ✓  {pypi_name} {ver} — {entry['role']}")
                lbl.setStyleSheet("color: #a6e3a1;")  # green
            else:
                tag = "required" if entry["is_hard"] else "optional"
                lbl.setText(f"  ✗  {pypi_name} — {entry['role']}  ({tag}, not installed)")
                lbl.setStyleSheet("color: #f9e2af;")  # warn yellow
                missing_pypi.append(pypi_name)

        self._install_cmd_edit.setText(_install_command(missing_pypi))

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

    # Stage-key → tab index. Used by DashboardTab's Open ▸ buttons to switch
    # focus to the correct converter tab.
    _STAGE_TAB_INDEX: dict = {}

    RESIZE_MARGIN = 6   # pixels at each edge that trigger resize gestures

    def __init__(self, start_tab: int = 0):
        super().__init__()
        self.setWindowTitle("Unity → O3DE Converter")
        self.resize(900, 820)
        self.setMinimumSize(720, 600)

        # Frameless: drop native OS chrome. Our CustomTitleBar replaces it.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)

        # Edge-resize state.
        self._resize_edge:   str = ""
        self._resize_origin     = None     # QPoint, global cursor when drag started
        self._resize_start_geom = None     # QRect, window geom when drag started

        # Dep banner is constructed at the window level (MainWindow drives the
        # one-shot evaluation) but parented into the DashboardTab so it shows
        # at the top of that tab — not above the whole tab widget.
        self._dep_banner = DismissibleBanner()
        self._dep_banner.open_config_clicked.connect(self._goto_config)
        self._dep_banner.dismissed.connect(self._on_banner_dismissed)

        # Custom title bar with File menu + minimize/maximize/close.
        self._title_bar = CustomTitleBar(parent_window=self)
        self._title_bar.request_close.connect(self.close)
        self._title_bar.request_minimize.connect(self.showMinimized)
        self._title_bar.request_maximize_toggle.connect(self._toggle_max)

        # Always-visible project header below the title bar.
        self._project_header = ProjectHeaderBanner()
        # Hand the project menu (built inside ProjectHeaderBanner) to the
        # title bar's File button. The header keeps ownership of the actions
        # so enable-states sync on project_changed.
        self._title_bar.set_file_menu(self._project_header.project_menu())

        # Tab order: Dashboard → Scenes → Prefabs → Meshes → Materials →
        # Terrain → Config(hidden). Workflow ordering by configuration stage.
        self._tabs = QTabWidget()
        dashboard_tab = DashboardTab(dep_banner=self._dep_banner)
        self._tabs.addTab(dashboard_tab,                      "Dashboard") # 0
        scene_idx    = self._tabs.addTab(SceneConverterTab(),  "Scenes")    # 1
        prefab_idx   = self._tabs.addTab(PrefabProcessorTab(), "Prefabs")   # 2
        mesh_idx     = self._tabs.addTab(MeshTab(),            "Meshes")    # 3
        material_idx = self._tabs.addTab(MaterialTab(),        "Materials") # 4
        terrain_idx  = self._tabs.addTab(TerrainTab(),         "Terrain")   # 5
        self._config_index = self._tabs.addTab(ConfigTab(),    "Config")    # 6
        self._tabs.tabBar().setTabVisible(self._config_index, False)
        self._tabs.setCurrentIndex(start_tab)

        self._STAGE_TAB_INDEX = {
            "scene_converter":    scene_idx,
            "asset_processor":    prefab_idx,
            "mesh_processor":     mesh_idx,
            "material_processor": material_idx,
            "terrain_processor":  terrain_idx,
        }
        # Follow-up 6 — per-platform tab gating. Map each tab to its
        # SUPPORTED_TABS key so platform switches can show/hide tabs
        # based on the active plugin's declared support set. Dashboard
        # + Config are always visible (cross-platform meta surfaces).
        self._PLATFORM_TAB_KEYS = {
            0:                       "dashboard",
            scene_idx:               "scenes",
            prefab_idx:              "prefabs",
            mesh_idx:                "meshes",
            material_idx:            "materials",
            terrain_idx:             "terrain",
            self._config_index:      "config",
        }
        # Hook the platform-tab refresh into project_changed so a
        # source-engine switch auto-applies the visibility set.
        project_manager().project_changed.connect(self._refresh_platform_tabs)
        # Initial sync against the current project (or Unity defaults).
        self._refresh_platform_tabs(project_manager().current())

        dashboard_tab.request_focus_stage.connect(self._focus_stage)
        dashboard_tab.request_process_stage.connect(self._process_stage)
        # F-8 — Mission Command-level dispatch.
        dashboard_tab.request_run_all.connect(self._on_run_all)
        dashboard_tab.request_patch_all.connect(self._on_patch_all)
        # Keep a reference so workers can flip the dashboard's writing flag.
        self._dashboard_tab = dashboard_tab

        # F-8 — Pipeline orchestrator instance lives on MainWindow so it
        # outlives any single Run All session.
        self._material_tab_index = material_idx
        self._orchestrator = PipelineOrchestrator(self)
        self._orchestrator.log.connect(self._log_to_dashboard)
        self._orchestrator.stage_started.connect(self._on_stage_started_in_run)
        self._orchestrator.run_finished.connect(self._on_run_all_finished)

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

        # Central layout: title bar → project header → tabs.
        # Outer margin gives the frameless window a visible inset; section
        # spacing breathes between title bar / banner / tabs.
        central = QWidget()
        central.setMouseTracking(True)
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(8, 8, 8, 8)
        central_lay.setSpacing(6)
        central_lay.addWidget(self._title_bar)
        central_lay.addWidget(self._project_header)
        central_lay.addWidget(self._tabs, 1)
        self.setCentralWidget(central)

        # Window title binds to the active project's name (still shown in
        # the taskbar / Alt-Tab UI even though the OS title bar is gone).
        pm = project_manager()
        pm.project_changed.connect(self._update_title)
        self._update_title(pm.current())

        # One-shot dependency evaluation at launch.
        self._evaluate_dep_banner()

    def _on_tab_changed(self, index: int) -> None:
        # Keep the corner button visually in sync with whether Config is active.
        self._config_btn.setChecked(index == self._config_index)

    def _focus_stage(self, stage_key: str) -> None:
        idx = self._STAGE_TAB_INDEX.get(stage_key)
        if idx is not None:
            self._tabs.setCurrentIndex(idx)

    def _process_stage(self, stage_key: str) -> None:
        """Action button on a dashboard card → fire the relevant tab's
        existing worker entry point. Full-pipeline stages (Scenes /
        Prefabs / Terrain) run their full processing path. Iterative
        stages (Meshes / Materials) run the F-9 Patch worker — the
        button label on those cards says "Patch Dirty" to match."""
        idx = self._STAGE_TAB_INDEX.get(stage_key)
        if idx is None:
            return
        tab = self._tabs.widget(idx)
        if stage_key == "scene_converter":
            tab._start_conversion()
        elif stage_key == "asset_processor":
            tab._start_processing()
        elif stage_key == "terrain_processor":
            tab._start_generation()
        elif stage_key in ("mesh_processor", "material_processor"):
            tab._start_patch()

    # -------------------------------------------------------------------------
    # F-8 — Mission Command actions
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # PLATFORM-AWARE TAB GATING (follow-up 6)
    # -------------------------------------------------------------------------

    def _refresh_platform_tabs(self, project) -> None:
        """Show / hide tabs based on the active platform's
        ``SUPPORTED_TABS`` list. Dashboard is always visible; Config
        stays hidden by default (toggled by the corner button). Other
        tabs flip visibility based on whether the platform supports
        them.

        Called on project_changed and on initial construction. When no
        project is loaded the Unity default (all tabs supported) is
        used so the chrome doesn't shift between "empty project" and
        "Unity project loaded" states."""
        from platforms import get as get_platform
        plat_name = (getattr(project, "active_platform", None)
                     or "unity") if project else "unity"
        platform  = get_platform(plat_name)
        supported = (set(platform.SUPPORTED_TABS) if platform is not None
                     else set(self._PLATFORM_TAB_KEYS.values()))
        for idx, key in self._PLATFORM_TAB_KEYS.items():
            # Dashboard always visible. Config visibility is owned by the
            # corner button (already excluded from the tab bar).
            if key == "dashboard":
                continue
            if key == "config":
                continue
            self._tabs.tabBar().setTabVisible(idx, key in supported)

    def _log_to_dashboard(self, msg: str) -> None:
        """Append a line to the Dashboard's activity log. Robust to the
        log widget not yet being constructed (early signal during init)."""
        log = getattr(getattr(self, "_dashboard_tab", None),
                       "_activity_log", None)
        if log is not None:
            log.append(msg)

    def _on_run_all(self) -> None:
        """Mission Command Run All clicked. The Pre-flight panel has
        already gated the button on `report.can_run`; this is just the
        dispatch."""
        proj = project_manager().current()
        if proj is None:
            QMessageBox.warning(self, "Run All", "Open a project first.")
            return
        if self._orchestrator.is_running():
            QMessageBox.information(self, "Run All",
                                     "A Run All pass is already in progress.")
            return
        self._log_to_dashboard("=" * 60)
        self._log_to_dashboard("RUN ALL — starting full pipeline pass")
        self._log_to_dashboard("=" * 60)
        self._orchestrator.run_all(proj, self._process_stage)

    def _on_stage_started_in_run(self, stage_key: str) -> None:
        """Focus the tab so the user sees the per-stage worker log
        streaming as the orchestrator walks the queue."""
        self._focus_stage(stage_key)

    def _on_run_all_finished(self, ok: bool, summary: str) -> None:
        self._log_to_dashboard(
            f"[orchestrator] Run All finished: "
            f"{'✓ ' if ok else '✗ '}{summary}"
        )
        # Bring focus back to the dashboard so the user sees the summary.
        self._focus_stage("asset_processor")  # no-op if already there
        if hasattr(self, "_dashboard_tab"):
            self._tabs.setCurrentWidget(self._dashboard_tab)

    def _on_patch_all(self) -> None:
        """Mission Command Patch All clicked. Runs the comprehensive F-9
        patch — dirty materials AND meshes — via its own worker, reporting
        both. Decoupled from the per-tab buttons so it works regardless of
        which tabs are constructed / visible for the active platform."""
        proj = project_manager().current()
        if proj is None:
            QMessageBox.warning(self, "Patch All", "Open a project first.")
            return
        snapshot = _patch_settings_snapshot(proj)
        if snapshot is None:
            QMessageBox.warning(
                self, "Patch All",
                "Patch needs the Prefab Processor's source + output folders "
                "(set on the Prefabs tab). Run the Prefab Processor at least "
                "once before patching.",
            )
            return
        source_root, output_root, material_settings, mesh_settings, state_index = snapshot
        self._log_to_dashboard("PATCH ALL — re-emit dirty materials + meshes")
        self._patch_all_worker = WorkerThread(
            _run_full_patch, source_root, output_root,
            material_settings, mesh_settings, state_index,
        )
        self._patch_all_worker.emitter.message.connect(self._log_to_dashboard)
        self._patch_all_worker.finished.connect(self._on_patch_all_finished)
        self._patch_all_worker.start()

    def _on_patch_all_finished(self, success: bool, payload: str) -> None:
        if not success:
            QMessageBox.critical(self, "Patch All", f"Patch failed:\n{payload}")
            return
        info = _decode_patch_payload(payload)
        proj = project_manager().current()
        if proj is not None:
            _merge_patch_state(proj, info.get("state") or {})
        self._log_to_dashboard(_format_patch_message(info).replace("\n", "  |  "))
        QMessageBox.information(self, "Patch All", _format_patch_message(info))
        # Refresh dashboard cards so dirty markers + Patch-button states update.
        dash = getattr(self, "_dashboard_tab", None)
        if dash is not None:
            dash.apply_project(proj)

    def _update_title(self, project) -> None:
        if project is None:
            self.setWindowTitle("Unity → O3DE Converter — (no project)")
        else:
            self.setWindowTitle(f"Unity → O3DE Converter — {project.name}")

    # -------------------------------------------------------------------------
    # DEPENDENCY BANNER
    #
    # Computed once at launch. Compares the current missing-deps signature
    # against the persisted dismissed signature; mismatch → show. The user
    # can re-probe via Config tab's Refresh, but this banner does not
    # auto-update mid-session.
    # -------------------------------------------------------------------------

    def _evaluate_dep_banner(self) -> None:
        missing = [d for d in check_dependencies() if not d["installed"]]
        if not missing:
            self._dep_banner.clear()
            return

        signature = signature_for(missing)
        if signature == get_dismissed_dependency_signature():
            self._dep_banner.clear()
            return

        any_hard = any(d["is_hard"] for d in missing)
        names = ", ".join(d["pypi_name"] for d in missing)
        if any_hard:
            msg = (f"Critical: required dependencies missing ({names}). "
                   f"The converter will fail without them.")
            self._dep_banner.show_state("error", msg)
        else:
            msg = (f"Optional dependencies missing ({names}). "
                   f"Some features (smoothness→roughness re-bake) are disabled.")
            self._dep_banner.show_state("warning", msg)

    def _on_banner_dismissed(self) -> None:
        missing = [d for d in check_dependencies() if not d["installed"]]
        set_dismissed_dependency_signature(signature_for(missing) if missing else None)
        self._dep_banner.clear()

    def _goto_config(self) -> None:
        self._tabs.setCurrentIndex(self._config_index)

    # -------------------------------------------------------------------------
    # SAVE-ON-CLOSE
    #
    # All converter-tab field edits autosave through the project manager, so
    # the only dirty state that can survive to closeEvent is a brand-new
    # project that the user created but never saved (path is still None).
    # Prompt before discarding it.
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # FRAMELESS WINDOW: maximize toggle, edge resize, mouse cursor feedback
    # -------------------------------------------------------------------------

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        # Keep the title bar's max-button glyph in sync with the window state,
        # and collapse the outer central-layout margin when maximized so the
        # window content reaches the screen edges instead of leaving a dark
        # frame inside the maximize.
        if event.type() == event.Type.WindowStateChange:
            self._title_bar.set_maximized(self.isMaximized())
            m = 0 if self.isMaximized() else 8
            self.centralWidget().layout().setContentsMargins(m, m, m, m)
        super().changeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge:
                self._resize_edge       = edge
                self._resize_origin     = event.globalPosition().toPoint()
                self._resize_start_geom = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_edge:
            self._do_edge_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if not self.isMaximized():
            self._update_cursor_for_edge(self._edge_at(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_edge:
            self._resize_edge       = ""
            self._resize_origin     = None
            self._resize_start_geom = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _edge_at(self, pos) -> str:
        """Return a code like 'tl', 'br', 't', 'l', or '' for the edge under
        `pos` (window-local coords). Empty string = inside, no resize."""
        m = self.RESIZE_MARGIN
        w, h = self.width(), self.height()
        left   = pos.x() < m
        right  = pos.x() > w - m
        top    = pos.y() < m
        bottom = pos.y() > h - m
        return (
            ("t" if top else "b" if bottom else "") +
            ("l" if left else "r" if right else "")
        )

    def _update_cursor_for_edge(self, edge: str) -> None:
        cursor_map = {
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
            "t":  Qt.SizeVerCursor,   "b":  Qt.SizeVerCursor,
            "l":  Qt.SizeHorCursor,   "r":  Qt.SizeHorCursor,
        }
        if edge in cursor_map:
            self.setCursor(cursor_map[edge])
        else:
            self.unsetCursor()

    def _do_edge_resize(self, global_pos) -> None:
        dx = global_pos.x() - self._resize_origin.x()
        dy = global_pos.y() - self._resize_origin.y()
        g = self._resize_start_geom
        new_x, new_y, new_w, new_h = g.x(), g.y(), g.width(), g.height()
        edge = self._resize_edge

        if "l" in edge:
            new_x = g.x() + dx
            new_w = g.width() - dx
        if "r" in edge:
            new_w = g.width() + dx
        if "t" in edge:
            new_y = g.y() + dy
            new_h = g.height() - dy
        if "b" in edge:
            new_h = g.height() + dy

        min_w = self.minimumWidth()  or 720
        min_h = self.minimumHeight() or 600
        if new_w < min_w:
            if "l" in edge:
                new_x = g.x() + (g.width() - min_w)
            new_w = min_w
        if new_h < min_h:
            if "t" in edge:
                new_y = g.y() + (g.height() - min_h)
            new_h = min_h

        self.setGeometry(new_x, new_y, new_w, new_h)

    # Class-level test hook: set to True in verification scripts to bypass
    # the unsaved-project prompt so closing the window doesn't block on a
    # modal dialog the test can't dismiss.
    SUPPRESS_CLOSE_PROMPT = False

    def closeEvent(self, event):
        if self.SUPPRESS_CLOSE_PROMPT or os.environ.get("U2O_SKIP_CLOSE_PROMPT"):
            event.accept()
            return
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
    # Determine which tab to open from --tab= argument. `project` retained
    # as a backwards-compat alias for `dashboard`.
    tab_name_to_index = {
        "dashboard": 0,
        "project":   0,
        "scene":     1,
        "prefab":    2,
        "mesh":      3,
        "material":  4,
        "terrain":   5,
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
