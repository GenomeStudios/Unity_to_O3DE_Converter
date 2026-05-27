---
name: ui-reorganization-working-doc
description: Living status log for UX-1 (project header banner + dashboard rebuild + tab reorder + readiness summaries). Newest entries on top.
metadata:
  type: project
---

# UX-1 UI Reorganization — Working Documentation

Newest entries on top. Linked plan: [[ui-reorganization-plan]].

## 2026-05-26 — UX-1 shipped ✓

### What landed
- **`ProjectHeaderBanner(QFrame)`** added at the top of MainWindow,
  always visible. Two modes via `QStackedWidget`:
  - **Compact**: row 1 = bold project name + scope + scope-root
    basename, right-aligned `Project ▾` menu + `Edit` button; row 2 =
    single-line notes summary with full-text tooltip.
  - **Expanded**: full editable form (name, scope combo, scope_root
    with browse, notes editor, created/modified/file labels,
    Collapse button).
  - Toggle between modes via Edit / Collapse button.
- **`Project ▾` popup menu** (replaces the old Project-tab toolbar)
  with New / Open / Save / Save As / Recent ▸ / Close. Keyboard
  shortcuts: Ctrl+N, Ctrl+O, Ctrl+S, Ctrl+Shift+S. Save / Save As /
  Close auto-disable when no project loaded. Recent submenu
  rebuilds via `aboutToShow`.
- **`_NotesEdit`** (subclass of QTextEdit emitting `blurred` on
  focusOutEvent) lives next to the banner widget. The earlier
  duplicate definition inside the removed `ProjectTab` block was
  swept out with that class.
- **`ProjectTab` → `DashboardTab`** — header form, notes editor,
  file-ops toolbar, and empty-state QStackedWidget all stripped.
  Dashboard now contains: dep banner (rehomed from MainWindow) +
  Pipeline Status group + Activity Log.
- **`compute_stage_readiness(stage_key, project)`** module-level
  helper returns `(severity, message)` describing the highest-
  priority current state for a stage. Five severities:
  - `unset`  (grey ○)   — nothing configured
  - `partial`(yellow ●) — some pieces set, others missing
  - `ready`  (sapphire ●)— configured, awaiting run
  - `ok`     (green ●)  — last run clean
  - `warn`   (orange ●) — last run had warnings/errors
- **Dashboard `_refresh_status_row`** consumes `compute_stage_readiness`.
  Activity log retained for runtime updates (`status_changed` signal).
- **Tab order** reshuffled to: Dashboard → Scene Converter →
  Prefab Processor → Terrain → Config (corner). Both visual and
  `_STAGE_TAB_INDEX` mapping updated.
- **MainWindow rewire**:
  - Dep banner constructed at window level but parented into
    DashboardTab via constructor arg.
  - `ProjectHeaderBanner` inserted above the QTabWidget in the
    central VBox (0-margin / 0-spacing for flush look).
  - Window resized 820×800 (slightly taller to accommodate banner).
- **CLI `--tab=`** updated: `dashboard|project → 0`, `scene → 1`,
  `prefab → 2`, `terrain → 3`. `project` retained as backwards-compat
  alias.
- **QSS**: new rules for `#project_header_banner`,
  `#banner_project_name`, `#banner_meta`, `#banner_notes`, and
  `QToolButton` inside the banner. Catppuccin-consistent palette
  (`#181826` background, `#cdd6f4` text, etc.).

### Behaviour notes
- Edit button is **disabled when no project is loaded**, but the
  Project menu stays accessible — so New / Open / Recent are always
  reachable.
- Header banner stays visible even with no project; compact row 1
  shows `(no project loaded)` and row 2 shows `Use Project ▾ to
  open or create one.`
- Pipeline-status rows on Dashboard fall back to `unset · "no
  project loaded"` when no project is loaded.
- Dep banner now only appears on the Dashboard tab. Users on other
  tabs won't see it mid-session — by design per Q5 + user spec.
  Since Dashboard is the default tab on launch, the banner is still
  visible whenever it fires.

### Sanity gates passed
- `py project_manager.py` → smoke OK (10 invariants).
- `py -c "import main_app"` → OK.
- End-to-end UX-1 verification against the actual testbed:
  - Testbed has `scope_root` set to
    `D:/OffLocalDev/Contracting/artificer/Assets/Alien Fantasy Forest`.
  - Scrubbing detected **2 .unity scenes**:
    `Demo/Demo1.unity`, `Demo/Update_1_2.unity`.
  - Tab labels: Dashboard / Scene Converter / Prefab Processor /
    Terrain / Config ✓
  - `_STAGE_TAB_INDEX` maps `scene_converter→1, asset_processor→2,
    terrain_processor→3` ✓
  - Header banner: name=TestProject, scope=Asset Set,
    root-basename="Alien Fantasy Forest", notes truncated to one line
    with full-text tooltip ✓
  - Edit toggle: compact (idx 0) ↔ expanded (idx 1) — both work ✓
  - Dashboard row order: scene_converter / asset_processor /
    terrain_processor ✓
  - Readiness chains fire correctly on real testbed:
    - scene_converter: `partial · No scenes selected (0 of 2)` ✓
    - asset_processor: `partial · No destination set` ✓
      (source inherits from scope_root via effective_source)
    - terrain_processor: `partial · No materials selected` ✓

### T-series status
| ID | Status |
|---|---|
| T-1 (banner shows project name + scope + root + notes) | ✓ programmatic |
| T-2 (Edit toggles to expanded; Collapse reverses) | ✓ programmatic |
| T-3 (Project ▾ menu items + enabled states) | needs visual click test |
| T-4 (tab order left→right) | ✓ programmatic |
| T-5 (Dashboard: dep-banner + Pipeline Status + Activity Log) | ✓ programmatic |
| T-6 (empty testbed: all "No source set") | covered before user populated scope_root |
| T-7 (scope set, no scenes selected → "X of Y scenes selected · No destination") | ✓ programmatic with real data |
| T-8 (post-run summaries) | needs an actual conversion run to verify |
| T-9 (no-project state) | logic verified, needs visual click test |

### Open follow-ups
- Mid-session re-evaluation of the dep banner from ConfigTab's
  Refresh button (already noted in F-1 follow-ups — still pending).
- Polish: subtle visual divider between scope/scope_root and the
  status sub-label in the expanded form.
- Polish: keyboard shortcut display in the Project ▾ menu items.
  Currently set via `setShortcut` but not rendered in menu text by
  default Qt — could add `\tCtrl+S` style hints.
- Potential bug to watch: the dep banner stays inside DashboardTab
  even after dismiss. The banner is hidden via `clear()` (calls
  `self.hide()`), so it occupies zero space when not visible. Verified
  the DashboardTab layout doesn't reserve space for the hidden widget.

## 2026-05-26 — Plan locked; starting I.1

9 design Q's resolved. The big move is splitting today's Project tab
into two pieces:
- **Top banner**: project header (name/scope/notes/root) + Project
  menu (file ops). Always visible above the tabs.
- **Dashboard tab**: dep banner + Pipeline Status + Activity Log.

## Pending / not yet shipped

- Visual click-through verification of menu actions (New/Open/Save/
  Recent/Close, Edit/Collapse, Open ▸ buttons) — best done by the
  user since I can't see a live GUI.
- T-8 post-run aggregation visual confirmation — requires an actual
  scene conversion to fire.
