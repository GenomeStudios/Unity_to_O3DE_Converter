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
    QFormLayout, QInputDialog, QScrollArea,
)

from project_manager import (
    Project, ProjectScope, ProjectManager, project_manager,
    PROJECT_FILE_EXT, STAGE_KEYS, _utc_now_iso,
    get_dismissed_dependency_signature, set_dismissed_dependency_signature,
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
        for scope in ProjectScope:
            self._scope_combo.addItem(scope.display_name(), scope.value)
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

        form.addRow("Name:",        self._name_edit)
        form.addRow("Scope:",       self._scope_combo)
        form.addRow("Source Root:", root_wrap)
        form.addRow("",             self._scope_root_status)
        form.addRow("Notes:",       self._notes_edit)
        form.addRow("Created:",     self._created_lbl)
        form.addRow("Modified:",    self._modified_lbl)
        form.addRow("File:",        self._file_lbl)
        v.addLayout(form)

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
            self._scope_label.setText(project.scope.display_name() if has_project else "")
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
                idx = self._scope_combo.findData(project.scope.value)
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
        proj.set_scope(ProjectScope.from_string(value))
        pm.commit_metadata()

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

    def __init__(self, stage_name: str):
        super().__init__()
        self.setObjectName("stage_status_card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(6)

        # --- Banner row: name + status + Process + Open ▸ ------------------
        banner = QHBoxLayout()
        banner.setSpacing(10)
        self._name_label = QLabel(stage_name)
        self._name_label.setObjectName("stage_card_name")
        banner.addWidget(self._name_label)
        self._status_label = QLabel("")
        self._status_label.setObjectName("stage_card_status")
        banner.addWidget(self._status_label)
        banner.addStretch(1)
        self._process_btn = QPushButton("Process")
        self._process_btn.setObjectName("stage_card_process")
        self._process_btn.setCursor(Qt.PointingHandCursor)
        self._process_btn.clicked.connect(self.process_clicked.emit)
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
            color = _REQ_MET_COLOR if req["met"] else _REQ_NOT_MET_COLOR
            label = QLabel(f"{glyph}  {req['text']}")
            label.setObjectName("stage_card_req")
            label.setStyleSheet(f"color: {color}; font-size: 9pt;")
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

        self._process_btn.setEnabled(sstate not in ("unconfigured", "writing"))


def compute_stage_readiness(stage_key: str, project) -> dict:
    """Return a structured readiness report for a converter stage:

        {
          "status":       'unset' | 'incomplete' | 'ready' | 'ok' | 'warn',
          "status_label": display string for the status badge,
          "requirements": [ {"met": bool, "text": str}, ... ],
          "last_run":     post-run summary string (None if never run),
        }

    `requirements` lists each prerequisite for the stage as either met
    (green ✓) or not met (red ✗). `status` summarises overall state:
    `incomplete` when any requirement is unmet, `ready` when all are met
    but nothing has run yet, `ok` after a clean run, `warn` after a run
    with warnings/errors.
    """
    if project is None:
        return {
            "status":       "unset",
            "status_label": "No project",
            "requirements": [],
            "last_run":     None,
        }

    status_info = project.pipeline_status.get(stage_key, {})
    cfg         = project.stage_settings(stage_key)
    source      = project.effective_source(stage_key)
    output      = (cfg.get("output_path") or "").strip()
    last_run    = status_info.get("last_run")

    reqs: list = []
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
        materials = cfg.get("selected_materials", []) or []
        if materials:
            reqs.append({"met": True,  "text": f"{len(materials)} materials selected"})
        else:
            reqs.append({"met": False, "text": "No materials selected"})
        reqs.append(_req_output(output))
        if last_run:
            last_run_summary = (
                f"Last run {last_run}: "
                f"{status_info.get('materials_written', 0)}/{status_info.get('materials_total', 0)} materials, "
                f"{status_info.get('textures_written', 0)} textures, "
                f"{status_info.get('errors', 0)} errors"
            )
        had_errors = bool(status_info.get("errors", 0))

    else:
        return {
            "status":       "unset",
            "status_label": "(unknown stage)",
            "requirements": [],
            "last_run":     None,
        }

    all_met = all(r["met"] for r in reqs)
    if not all_met:
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
        payload["files"] = _fingerprint_files_under(source, "*.prefab")

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
        selected = sorted(cfg.get("selected_materials", []) or [])
        payload["selected_materials"] = selected
        payload["files"] = {mat: _fingerprint_file(mat) for mat in selected}

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

    readiness = compute_stage_readiness(stage_key, project)
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


class DashboardTab(QWidget):
    """Pipeline status dashboard. Hosts the dep banner (rehomed from
    MainWindow), three pipeline-status rows in configuration-workflow order
    (Scene → Prefab → Terrain), and an activity log. Project header /
    notes / file ops live in `ProjectHeaderBanner` at the window level."""

    request_focus_stage   = Signal(str)
    request_process_stage = Signal(str)

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

        # Pipeline Status — one StageStatusCard per stage, workflow order.
        status_box, status_lay = _section_groupbox("Pipeline Status")
        status_lay.setSpacing(10)
        for stage_key, label in (
            ("scene_converter",   "Scene Converter"),
            ("asset_processor",   "Prefab Processor"),
            ("terrain_processor", "Terrain Materials"),
        ):
            card = StageStatusCard(label)
            card.open_clicked.connect(
                lambda k=stage_key: self.request_focus_stage.emit(k)
            )
            card.process_clicked.connect(
                lambda k=stage_key: self.request_process_stage.emit(k)
            )
            status_lay.addWidget(card)
            self._status_cards[stage_key] = card
        root.addWidget(status_box)

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

    def _refresh_status_card(self, stage_key: str, project) -> None:
        card = self._status_cards[stage_key]
        readiness  = compute_stage_readiness(stage_key, project)
        sync_state = compute_stage_sync_state(
            stage_key, project, writing=(stage_key in self._stages_writing),
        )
        card.update_state(readiness, sync_state)

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
        self._refresh_effective_source_label()

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

        self._save_settings()
        self._process_btn.setEnabled(False)
        self._log_edit.clear()
        project_manager().set_processing(self.STAGE_KEY, True)

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
        self._prefab_dirs: list = []
        self._selected_scenes: set = set()    # relative paths under effective_source
        self._suppress_scene_signals = False  # block itemChanged during apply
        self._last_run_totals: dict = {}
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

        # ── Prefab Search Directories (legacy; F-4 will replace) ────────
        self._prefab_list = QListWidget()
        add_btn    = QPushButton("Add Directory")
        remove_btn = QPushButton("Remove Selected")
        clear_btn  = QPushButton("Clear All")
        add_btn.clicked.connect(self._add_prefab_directory)
        remove_btn.clicked.connect(self._remove_prefab_directory)
        clear_btn.clicked.connect(self._clear_prefab_directories)
        root.addWidget(_managed_list_section(
            "Prefab Search Directories", self._prefab_list,
            add_btn, remove_btn, clear_btn,
            min_h=80, max_h=140,
        ))

        # ── Conversion Log ──────────────────────────────────────────────
        self._log_edit = _log_widget()
        root.addWidget(_fill_section("Conversion Log", self._log_edit), stretch=1)

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
        self._prefab_dirs = []
        self._prefab_list.clear()
        for d in cfg.get("prefab_dirs", []):
            self._add_dir_to_list(d)
        self._refresh_effective_source_label()
        self._refresh_scene_list()

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

        if not self._prefab_dirs:
            QMessageBox.warning(self, "Warning",
                "No prefab search directories added. Prefab references will not "
                "be resolved.")

        self._save_settings()
        self._convert_btn.setEnabled(False)
        self._log_edit.clear()
        self._last_run_totals = {}
        project_manager().set_processing(self.STAGE_KEY, True)

        self._worker = WorkerThread(
            self._do_multi_conversion, resolved, output, self._prefab_dirs[:]
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_multi_conversion(self, scenes: list, output_dir: str,
                             prefab_dirs: list, log) -> str:
        """Serial multi-scene conversion. Each scene gets its own
        UnitySceneConverter, output goes into <output>/<SceneName>/."""
        from unity_scene_converter_gui import PrefabDatabase, UnitySceneConverter

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
            "  Terrain/Materials/  — O3DE .material files referencing\n"
            "                          @gemroot:Terrain@/Assets/Materials/Types/\n"
            "                          TerrainBaseMaterial.materialtype\n"
            "  Terrain/Textures/   — Textures referenced by the materials above"
        )
        info_label.setStyleSheet("color: #6c7086; font-size: 9pt;")
        out_lay.addWidget(info_label)
        root.addWidget(out_box)

        # ── Selected Unity Materials ────────────────────────────────────
        self._material_list = QListWidget()
        self._material_list.setSelectionMode(QListWidget.ExtendedSelection)
        add_btn    = QPushButton("Add Materials…")
        remove_btn = QPushButton("Remove Selected")
        clear_btn  = QPushButton("Clear All")
        add_btn.clicked.connect(self._add_materials)
        remove_btn.clicked.connect(self._remove_selected_materials)
        clear_btn.clicked.connect(self._clear_materials)
        root.addWidget(_managed_list_section(
            "Selected Unity Materials", self._material_list,
            add_btn, remove_btn, clear_btn,
            min_h=120, max_h=200,
        ))

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
        self._selected_materials = []
        self._material_list.clear()
        for path in cfg.get("selected_materials", []):
            self._add_material_to_list(path)
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
        if not self._selected_materials:
            QMessageBox.warning(self, "Warning",
                "No materials selected. Add at least one .mat file to convert.")
            return

        self._save_settings()
        self._generate_btn.setEnabled(False)
        self._log_edit.clear()
        project_manager().set_processing(self.STAGE_KEY, True)

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

        run_ts = _utc_now_iso()
        errors  = len(result["errors"])
        sstatus = "warn" if errors else "ok"

        # Build per-material records for the project outputs.
        material_records: dict = {
            str(p): {
                "source_path": str(p),
                "written_at":  run_ts,
            }
            for p in material_paths
        }

        project_manager().update_outputs(self.STAGE_KEY, {
            "last_run":        run_ts,
            "last_status":     sstatus,
            "last_input_hash": input_hash_for(self.STAGE_KEY, project_manager().current()),
            "materials":       material_records,
            "coverage":        {"errors": list(result.get("errors", []))},
        })

        project_manager().update_status(self.STAGE_KEY, {
            "last_run":          run_ts,
            "materials_written": result["materials_written"],
            "materials_total":   len(material_paths),
            "textures_written":  result["textures_written"],
            "errors":            errors,
        })

        return (
            f"Materials: {result['materials_written']}/{len(material_paths)}  |  "
            f"Textures: {result['textures_written']}  |  "
            f"Errors: {len(result['errors'])}"
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


def check_dependencies() -> list:
    """Probe each entry in DEPENDENCIES. Returns a list of dicts:

        [{import_name, pypi_name, role, is_hard, installed, version}, …]

    Drives both ConfigTab._refresh_dep_status and the startup banner.
    Flushes the import cache first so deps installed via pip *after* the
    app started are detected on a probe rather than returning stale-no.
    """
    import importlib
    importlib.invalidate_caches()

    results = []
    for import_name, pypi_name, role, is_hard in DEPENDENCIES:
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

        Delegates probing to module-level `check_dependencies()` so the
        startup banner and this tab share a single source of truth. The
        install command lists only the missing packages by default; when
        nothing is missing it falls back to the "install all" form so a
        fresh clone can copy a single line to bootstrap everything.
        """
        missing_pypi: list = []
        for entry in check_dependencies():
            pypi_name = entry["pypi_name"]
            lbl = self._dep_status_labels[pypi_name]
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

        # Tab order: Dashboard → Scene → Prefab → Terrain → Config(hidden).
        # Workflow ordering, not execution ordering.
        self._tabs = QTabWidget()
        dashboard_tab = DashboardTab(dep_banner=self._dep_banner)
        self._tabs.addTab(dashboard_tab,                      "Dashboard")        # 0
        scene_idx   = self._tabs.addTab(SceneConverterTab(),  "Scene Converter")  # 1
        prefab_idx  = self._tabs.addTab(PrefabProcessorTab(), "Prefab Processor") # 2
        terrain_idx = self._tabs.addTab(TerrainTab(),         "Terrain")          # 3
        self._config_index = self._tabs.addTab(ConfigTab(),   "Config")           # 4
        self._tabs.tabBar().setTabVisible(self._config_index, False)
        self._tabs.setCurrentIndex(start_tab)

        self._STAGE_TAB_INDEX = {
            "scene_converter":   scene_idx,
            "asset_processor":   prefab_idx,
            "terrain_processor": terrain_idx,
        }
        dashboard_tab.request_focus_stage.connect(self._focus_stage)
        dashboard_tab.request_process_stage.connect(self._process_stage)
        # Keep a reference so workers can flip the dashboard's writing flag.
        self._dashboard_tab = dashboard_tab

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
        """Process button on a dashboard card → fire the relevant tab's
        existing worker entry point. Same code path as clicking the tab's
        bottom action button."""
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
    # Determine which tab to open from --tab= argument. `project` retained
    # as a backwards-compat alias for `dashboard`.
    tab_name_to_index = {
        "dashboard": 0,
        "project":   0,
        "scene":     1,
        "prefab":    2,
        "terrain":   3,
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
