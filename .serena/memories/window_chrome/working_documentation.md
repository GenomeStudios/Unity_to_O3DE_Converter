---
name: window-chrome-working-doc
description: Living status log for UX-2 (custom title bar + frameless window + banner compact restructure). Newest entries on top.
metadata:
  type: project
---

# UX-2 Custom Window Chrome — Working Documentation

Newest entries on top. Linked plan: [[window-chrome-plan]].

## 2026-05-26 — UX-2 polish pass ✓

### What landed
- **Outer window margin**: `MainWindow.centralWidget()`'s `QVBoxLayout`
  now has `setContentsMargins(8, 8, 8, 8)` and `setSpacing(6)`. The
  whole frameless window content (title bar + banner + tabs) sits
  inset 8 px from the window edge, with 6 px breathing room between
  sections. This gives the frameless window a visible inset against
  whatever sits behind it.
- **Margin collapse on maximize**: `changeEvent` now also sets the
  central margins to 0 when `isMaximized()` and back to 8 when
  restored. Prevents a dark ring of unused window space around
  maximized content. Verified: show → 8/8/8/8, maximize → 0/0/0/0,
  restore → 8/8/8/8.
- **Edit button reskinned**: was a transparent-bg ghost button that
  the user reported as "just a square with no identification". Now
  a filled `#313244` button with `#cdd6f4` text, `#585b70` border,
  bold font, `padding: 5px 18px`, `min-width: 64px`. Visible size
  hint: 106×30 px.
- **Save button** in the expanded form (replaces the old "Collapse"):
  - Renamed `_collapse_btn` → `_save_btn`.
  - Sapphire-fill style via new QSS rule (`background: #89b4fa`,
    `color: #11111b`). Primary-action visual weight.
  - New `_on_save_clicked` handler that calls `pm.save()` (no-op if
    no path yet) then toggles back to compact mode. Defensive save
    so any unblurred field gets committed.
  - Bottom row gets `setContentsMargins(0, 4, 0, 0)` so the button
    has space above it.
- **Expanded form padding**: `_build_expanded` outer layout now uses
  `setContentsMargins(14, 10, 14, 10)` and `setSpacing(8)` instead
  of 0/0/0/0 and 6. The form no longer butts against the banner
  border.

### Sanity gates passed
- `py -c "import main_app"` → OK.
- Polish verification against testbed:
  - Central margins 8/8/8/8 with spacing 6 ✓
  - Maximize → margins 0/0/0/0; restore → margins 8/8/8/8 ✓
  - Edit button: text `Edit`, objectName `banner_edit`, 106×30 ✓
  - Save button: text `Save`, objectName `banner_save`, 106×30 ✓
  - `_collapse_btn` attribute gone ✓
  - Save click: panel transitions from expanded → compact ✓

### Known nit (deferred)
- Initial WindowStateChange events while the window isn't shown
  yet (e.g. tests that call `showMaximized()` before `show()`) skip
  the margin flip. Not a real-use issue: interactive flow always
  shows the window first.

## 2026-05-26 — UX-2 shipped ✓

### What landed
- **`CustomTitleBar(QFrame)`** — 32 px high, three-zone layout:
  - Left: `File` `QToolButton` with popup `QMenu` (set by MainWindow
    from the banner's pre-built menu).
  - Middle: invisible `_drag_area` `QWidget` that catches mouse press /
    move events for window dragging via an event filter, and
    double-click for maximize toggle.
  - Right: three caption `QPushButton`s — minimize, maximize/restore,
    close — with Unicode glyphs (`–`, `☐`/`⧉`, `✕`).
  - Signals: `request_close`, `request_minimize`,
    `request_maximize_toggle`.
  - Public API: `set_file_menu(QMenu)`, `set_maximized(bool)`.
- **MainWindow now frameless**: `Qt.FramelessWindowHint`,
  `setMouseTracking(True)`, `setMinimumSize(720, 600)`,
  `setAttribute(Qt.WA_StyledBackground, True)`.
- **Edge-resize support** baked into MainWindow with 6 px hit zone.
- **`_toggle_max`** flips between `showNormal()` and `showMaximized()`.
- **`changeEvent`** override watches `WindowStateChange` and updates
  the title bar's max-button glyph + central margins (see polish
  entry above).
- **`ProjectHeaderBanner` restructured** — QStackedWidget gone;
  show/hide on sibling widgets fixes the "massive empty notes block"
  regression and lets the compact panel collapse tight.
- **Toggle bug fixed**: switched from `isVisible()` to `isHidden()`
  in `_toggle_expanded` so the first Edit click works even before
  the window has been shown.
- **QSS additions** under `#title_bar`, `#file_menu_btn`,
  `#win_min` / `#win_max` / `#win_close`, `#banner_project_name`,
  `#banner_notes`, `#banner_edit`, `#banner_save`.

### Behaviour notes / known limitations
- **No Aero snap on Windows**. Out of scope per Q10 — needs
  WM_NCHITTEST through `nativeEvent` or the `qframelesswindow` 3rd
  party lib.
- **No native window shadow** under the frameless window.
- **macOS traffic lights replaced** by our right-side caption
  buttons everywhere.
- **Drag-from-maximized** uses a width-ratio heuristic to position
  the un-maximized window such that the cursor stays roughly on
  the title bar.
- **Resize is suppressed while maximized**, consistent with native
  behaviour.

## 2026-05-26 — Plan locked; starting I.1

10 design Q's resolved.

## Pending / not yet shipped

- User live click-through (T-2, T-3, T-4, T-5, T-8) — needs a live
  window for drag / double-click / button interactions.
- Future polish (out of scope for UX-2): native Aero snap, drop
  shadow, geometry persistence across launches.
