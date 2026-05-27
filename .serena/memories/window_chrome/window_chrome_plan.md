---
name: window-chrome-plan
description: Design + locked decisions for UX-2 — replace native window chrome with our own custom title bar (File menu + window controls), make the project banner compact (h2 name + one-line notes + Edit), and fix the wasted vertical space caused by the QStackedWidget reserving expanded-mode height.
metadata:
  type: project
---

# UX-2 Custom Window Chrome — Plan

## Goal

Drop the native OS window frame and ship our own Catppuccin-themed title
bar. New chrome:

```
[File]                                       [─][▢][✕]
─────────────────────────────────────────────────────
  Project Name (h2)
  Info / Notes summary line                    [Edit]
─────────────────────────────────────────────────────
  [Dashboard][Scene][Prefab]…
─────────────────────────────────────────────────────
  ... tab content ...
```

Also fix the UX-1 regression where the project banner reserved a tall
empty area below the notes — the QStackedWidget grows to the height of
its largest page (the expanded form), so compact mode inherits that
unused vertical space. Switch to a show/hide pair so the banner
collapses tight when compact.

## Resolved Decisions (Q&A)

**Q1 — Native vs custom chrome?**
A: **Custom.** Set `Qt.FramelessWindowHint`, build a `CustomTitleBar`
widget at the top of the central layout. Cross-platform — Qt handles
the frameless flag identically on Windows / Linux / macOS. Losses
(acknowledged): no native window shadow, no Aero snap on Windows (
WM_NCHITTEST integration is out of scope), no native window
animations. Future polish if needed.

**Q2 — Title bar layout?**
A: `[File] ............ drag area ............ [─][▢][✕]`. File
button left, window controls right, the wide middle is the drag
target. No center app title text — the project banner below already
communicates app context. Title bar height: **32 px**.

**Q3 — Window control glyphs?**
A: Unicode characters styled via QSS — render cleanly across platforms
without bundled icons:
- Minimize: `🗕` (U+1F5D5) or `−` fallback
- Maximize: `🗖` (U+1F5D6) or `▢` fallback
- Restore (when maximized): `🗗` (U+1F5D7) or `❐` fallback
- Close: `✕` (U+2715)
Per-button width 46 px, height 32 px (matches Windows 11 caption
buttons). Hover highlights; close-on-hover gets a red tint.

**Q4 — Resize + drag handling?**
A: Manual handling on the MainWindow subclass:
- **Drag**: title bar's mousePress/Move tracks delta + calls
  `self._parent_window.move()`. Double-click toggles maximize.
- **Resize**: 6 px invisible margin around the window. Mouse cursor
  updates to size cursors when within margin; press+drag resizes the
  window edge/corner. `setMouseTracking(True)` on the window enables
  hover cursor changes.
- **Min size**: 720×600. Enforced inside the resize handler.

**Q5 — File menu contents?**
A: **Identical to today's `Project ▾` menu**, just moved to the title
bar and renamed `File`. New / Open / Save / Save As / Recent ▸ / Close
with the same Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S shortcuts.

**Q6 — Project banner compact mode?**
A: Two rows only:
- Row 1: **Project name** as a heading-style label (font-size 14pt,
  bold). Nothing else.
- Row 2: **Notes summary** (single-line, ellipsised, full tooltip)
  + right-aligned **Edit** button.
Scope and root-basename **disappear** from compact mode. They live in
the expanded form (which retains all editable fields). Rationale:
the ASCII spec the user shared shows only name + notes + Edit, and
the readiness panel on Dashboard already surfaces the scope info.

**Q7 — Stacked-widget sizing bug fix?**
A: **Replace QStackedWidget with show/hide on two sibling widgets**
(`_compact_panel`, `_expanded_panel`) in the banner's VBox. Hidden
widgets don't reserve layout space, so the banner collapses tight
in compact mode and grows when expanded.

**Q8 — Maximize state handling for drag?**
A: When the user starts dragging a maximized window, call
`showNormal()` first, then reposition the window so the cursor stays
in-bounds. Matches Windows / GNOME / macOS behaviour.

**Q9 — Lose-the-menu-button-on-banner trade-off?**
A: The `Project ▾` menu button currently on the banner row 1
**disappears** from the banner (moves to title bar's File button).
Scope/root labels also disappear from compact mode (see Q6). This is
why the banner shrinks visibly — compact becomes 2 thin rows instead
of 2 rows of dense content. Acceptable per the user's spec; the
expanded form still surfaces everything.

**Q10 — Aero snap / native-feel-on-Windows polish?**
A: **Out of scope** for UX-2. Requires WM_NCHITTEST wiring through
PySide6 or the `qframelesswindow` 3rd-party lib. Document as a known
limitation.

## Design

### `CustomTitleBar(QFrame)`

```python
class CustomTitleBar(QFrame):
    """32px high custom title bar. Hosts the File menu button on the
    left, a drag area in the middle, and minimize/maximize/close
    buttons on the right. Tracks mouse events for window drag and
    double-click maximize-toggle."""

    request_close   = Signal()
    request_minimize = Signal()
    request_maximize_toggle = Signal()
```

UI children:
- `_file_btn: QToolButton` with text `File` and a popup `QMenu`.
- `_drag_area: QWidget` — invisible widget filling the stretch,
  catches mouse events for window dragging (delegates to title bar's
  own move handler).
- `_min_btn`, `_max_btn`, `_close_btn`: each a `QPushButton` with
  the glyph from Q3.

Event behaviour:
- `mousePressEvent`: if click is on `_drag_area`, record drag start.
- `mouseMoveEvent`: if dragging, call `_parent_window.move(...)`.
- `mouseDoubleClickEvent`: if double-click is on `_drag_area`, emit
  `request_maximize_toggle`.

The bar exposes `file_menu()` so MainWindow can populate it via
the same handlers `ProjectHeaderBanner` used to call (lifted into a
shared helper or moved verbatim).

### MainWindow modifications

```python
class MainWindow(QMainWindow):
    RESIZE_MARGIN = 6

    def __init__(self, start_tab=0):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(720, 600)
        ...
        # Build title bar, hook signals
        self._title_bar = CustomTitleBar(parent_window=self)
        self._title_bar.request_close.connect(self.close)
        self._title_bar.request_minimize.connect(self.showMinimized)
        self._title_bar.request_maximize_toggle.connect(self._toggle_max)
        # ... populate File menu ...
        ...
        # Central layout
        central_lay.addWidget(self._title_bar)
        central_lay.addWidget(self._project_header)
        central_lay.addWidget(self._tabs, 1)
```

Plus new methods on MainWindow:

```python
def _toggle_max(self) -> None:
    if self.isMaximized():
        self.showNormal()
    else:
        self.showMaximized()

def mousePressEvent(self, event):
    if event.button() == Qt.LeftButton:
        edge = self._edge_at(event.position().toPoint())
        if edge:
            self._start_resize(edge, event.globalPosition().toPoint())
            event.accept()
            return
    super().mousePressEvent(event)

def mouseMoveEvent(self, event):
    if self._resize_edge:
        self._do_resize(event.globalPosition().toPoint())
        event.accept()
        return
    edge = self._edge_at(event.position().toPoint())
    self._update_cursor_for_edge(edge)
    super().mouseMoveEvent(event)

def mouseReleaseEvent(self, event):
    self._resize_edge = None
    self.unsetCursor()
    super().mouseReleaseEvent(event)
```

`_edge_at`, `_start_resize`, `_do_resize`, `_update_cursor_for_edge`
helpers handle the geometry math. Resize is blocked when the window
is maximized.

### `ProjectHeaderBanner` restructure

Replace the QStackedWidget with two sibling widgets in the outer
VBox, hidden via `setVisible`. New compact layout:

```python
def _build_compact(self) -> QWidget:
    panel = QWidget()
    v = QVBoxLayout(panel)
    v.setContentsMargins(14, 8, 14, 8)
    v.setSpacing(2)

    self._name_label = QLabel("(no project loaded)")
    self._name_label.setObjectName("banner_project_name")   # 14pt bold via QSS
    v.addWidget(self._name_label)

    info_row = QHBoxLayout()
    info_row.setSpacing(8)
    self._notes_label = QLabel("(no notes)")
    self._notes_label.setObjectName("banner_notes")
    self._notes_label.setWordWrap(False)
    info_row.addWidget(self._notes_label, 1)
    self._edit_btn = QPushButton("Edit")
    self._edit_btn.setObjectName("banner_edit")
    self._edit_btn.setCursor(Qt.PointingHandCursor)
    self._edit_btn.clicked.connect(self._toggle_expanded)
    info_row.addWidget(self._edit_btn)
    v.addLayout(info_row)

    return panel
```

Expanded form unchanged structurally; Collapse button stays.

Toggle:
```python
def _toggle_expanded(self) -> None:
    going_expanded = self._compact_panel.isVisible()
    self._compact_panel.setVisible(not going_expanded)
    self._expanded_panel.setVisible(going_expanded)
    if going_expanded:
        self.apply_project(project_manager().current())
```

The Project ▾ menu button on row 1 of the old compact layout is
**removed**. Its handlers move into the CustomTitleBar's File menu.

### QSS additions

```css
/* Custom title bar */
QFrame#title_bar {
    background: #11111b;
    border-bottom: 1px solid #313244;
}
QFrame#title_bar QToolButton#file_menu_btn {
    background: transparent;
    color: #cdd6f4;
    padding: 4px 14px;
    border: none;
}
QFrame#title_bar QToolButton#file_menu_btn:hover {
    background: #313244;
}
QFrame#title_bar QPushButton#win_btn {
    background: transparent;
    color: #cdd6f4;
    border: none;
    min-width: 46px;
    max-width: 46px;
    min-height: 32px;
    padding: 0;
}
QFrame#title_bar QPushButton#win_btn:hover {
    background: #313244;
}
QFrame#title_bar QPushButton#win_close:hover {
    background: #f38ba8;
    color: #11111b;
}

/* Banner — compact mode pruned */
QFrame#project_header_banner {
    background: #181826;
    border-bottom: 1px solid #45475a;
}
QFrame#project_header_banner QLabel#banner_project_name {
    color: #cdd6f4;
    font-weight: bold;
    font-size: 14pt;
}
QFrame#project_header_banner QLabel#banner_notes {
    color: #9399b2;
    font-size: 9pt;
}
QFrame#project_header_banner QPushButton#banner_edit {
    background: transparent;
    color: #89b4fa;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 3px 10px;
    min-width: 0;
}
QFrame#project_header_banner QPushButton#banner_edit:hover {
    background: #313244;
}
```

## Implementation Plan

### I.1 — `CustomTitleBar` widget
**Done when:**
- Class exists in `main_app.py`.
- File button on left with `QMenu` populated via `set_file_menu(menu)`
  method (MainWindow owns the menu so it can disable items based on
  project state).
- Three window-control QPushButtons on the right with glyphs from Q3.
- Drag detection: mousePress + mouseMove emit move-window calls.
- Double-click on drag area emits `request_maximize_toggle`.
- Min/max/close buttons emit `request_minimize`,
  `request_maximize_toggle`, `request_close`.
- `set_maximized(bool)` flips the max button glyph between maximize
  and restore.

### I.2 — Frameless window + edge-resize handlers
**Done when:**
- `MainWindow.__init__` sets `Qt.FramelessWindowHint`, mouse
  tracking, minimum size.
- `_edge_at`, `_update_cursor_for_edge`, `_start_resize`, `_do_resize`
  implemented. Resize blocked when maximized.
- `mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` handle
  the resize gesture.
- `changeEvent` (or windowStateChanged) updates the title bar's
  max-button glyph.

### I.3 — File menu migration
**Done when:**
- The `Project ▾` button on `ProjectHeaderBanner` is removed.
- A new `_build_file_menu` helper (module-level or MainWindow method)
  constructs the New/Open/Save/Save As/Recent/Close `QMenu`.
- The handlers (`_on_new`, `_on_open`, etc.) move into MainWindow
  (or stay in a small file-ops module shared between the title-bar
  menu and any future callers).
- `CustomTitleBar.set_file_menu()` receives the populated menu;
  enable-states update on project_changed.

### I.4 — Banner compact restructure
**Done when:**
- `ProjectHeaderBanner._build_compact` returns a 2-row layout: name
  heading + (notes ellipsised + Edit button).
- Scope and root labels removed from compact mode (live only in
  expanded form).
- `_compact_panel` and `_expanded_panel` are direct VBox children,
  show/hide via `setVisible`. The QStackedWidget is removed.
- The Project ▾ button is gone from the banner (its handlers
  migrated to the title bar via I.3).

### I.5 — Verification

Manual proofs:

| ID | Proof |
|---|---|
| T-1 | Launch app: native window frame is gone, custom title bar renders with `File` on left, min/max/close on right. |
| T-2 | Click File: menu shows New/Open/Save/Save As/Recent/Close with correct enabled states. |
| T-3 | Drag title bar: window moves. Double-click title bar: window maximizes; double-click again restores. |
| T-4 | Click each window-control button: minimize iconifies the window; maximize fills the screen and glyph flips to restore; close shuts the app. |
| T-5 | Mouse over window edges: cursor changes to size cursors; press + drag resizes. Min size = 720×600 enforced. |
| T-6 | Project banner is now thin: just project name (large) on row 1, notes (small, single-line) + Edit on row 2. No empty vertical space. |
| T-7 | Click Edit: banner expands to full form. Click Collapse: banner returns to thin compact view. |
| T-8 | Window state changes via title-bar buttons and via OS shortcuts (Win+Up/Down on Windows) both update the max button glyph. |

## Out of scope

- Native Aero snap on Windows (would need WM_NCHITTEST).
- Window shadow under the frameless window (Windows-only DWM tricks).
- Geometry persistence across launches (save/restore last window
  position + size).
- macOS-specific traffic-light alignment (we use the same right-side
  controls everywhere).
- App-level icon next to the File menu in the title bar.
- Tab bar restyling — left untouched.
