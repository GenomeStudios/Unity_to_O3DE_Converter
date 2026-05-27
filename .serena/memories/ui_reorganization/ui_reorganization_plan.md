---
name: ui-reorganization-plan
description: Design + locked decisions for UX-1 — the post-base UI restructure. Project file ops collapse into a popup menu; Project header/notes move into a persistent top banner above the tabs; the Project tab becomes the Dashboard tab; tabs reorder by configuration workflow; Pipeline Status surfaces readiness instead of "never run".
metadata:
  type: project
---

# UX-1 UI Reorganization — Plan

## Goal

Restructure the main window so project state is always visible at the
top, file operations collapse into a small menu, and the
"Project" tab becomes a focused **Dashboard** showing dependency
state + pipeline readiness. Pipeline status messages describe the
highest-priority blocker for each stage instead of a flat "never
run / completed" binary.

This is a UX/structural pass — no new converter functionality,
no new stages. It's a foundation for F-4 onward to land cleanly.

## Resolved Decisions (Q&A)

**Q1 — File-menu shape: QMenuBar vs popup button?**
A: **Single `QToolButton` with popup menu** labelled `Project ▾`,
right-aligned inside the new top banner. Cross-platform (Qt popup
menus work identically on Windows/macOS/Linux). Avoids the macOS
auto-merge-to-global-menubar behaviour of QMenuBar which would
hide the menu off-window on macOS — keeps the menu visually anchored
to the project section.

**Q2 — Edit mode: inline expansion vs modal vs sidebar?**
A: **Inline expansion.** Edit button toggles the banner between a
compact 2-row mode and an expanded form mode that shows the full
editable header (name, scope, scope_root + browse, notes, created,
modified, file path). Label flips to **Collapse** when expanded.
Preserves context — no modal interruption.

**Q3 — Pipeline Status ordering?**
A: **Scene Converter → Prefab Processor → Terrain Materials**, matching
the user's configuration-workflow order. Note: execution order is
still prefabs-then-scenes (scenes reference prefabs at conversion
time); the dashboard rows reflect the *configuration* order the user
walks through, not the execution sequence. When F-8 ships orchestration,
"Run All" will fire stages in their proper execution order regardless
of dashboard ordering.

**Q4 — Tab ordering?**
A: **Dashboard → Scene → Prefab → Terrain → Config (corner)**. Same
rationale as Q3 — left-to-right by configuration workflow stage.
Future tabs slot in by their place in the configuration journey
(Mesh between Prefab and Material, etc.).

**Q5 — Dashboard contents?**
A: **Dep-banner (top) + Pipeline Status + Activity Log**. Dep-banner
rehomed from MainWindow level into this tab. Activity log retained as
operational session state. Project header/notes leave the Dashboard —
they live in the top banner now.

**Q6 — Banner visibility when no project loaded?**
A: Banner **always visible**. Compact mode shows `(no project loaded)`
placeholder; the `Project ▾` menu stays accessible (so New / Open /
Recent are reachable); Edit button is disabled. Otherwise we'd
strand the user with no way to open a project.

**Q7 — Pipeline-status readiness chain per stage?**
A: A per-stage **highest-priority-blocker-wins** chain. Each stage
exposes a `compute_readiness(project) → (severity, message)` function.
Severity drives dot colour; message is the human-readable summary.
Chains are:

- **Scene Converter:**
  1. No effective source → `"No source set"` (grey ○)
  2. No scenes scrubbed under source → `"Source has no .unity scenes"` (yellow ●)
  3. No scenes selected → `"No scenes selected"` (yellow ●)
  4. No output → `"X of Y scenes selected · No destination set"` (yellow ●)
  5. Ready, never run → `"Ready · X of Y scenes selected"` (blue ●)
  6. Last run → existing aggregated summary (green ● / amber ● if missing)

- **Prefab Processor:**
  1. No effective source → `"No source set"` (grey ○)
  2. No output → `"No destination set"` (yellow ●)
  3. Ready, never run → `"Ready"` (blue ●). *(F-4 will insert a
     selection-check step here once prefab checklists land.)*
  4. Last run → existing summary

- **Terrain Materials:**
  1. No effective source → `"No source set"` (grey ○)
  2. No materials selected → `"No materials selected"` (yellow ●)
  3. No output → `"X materials selected · No destination set"` (yellow ●)
  4. Ready, never run → `"Ready · X materials selected"` (blue ●)
  5. Last run → existing summary

The fifth (blue) state introduces a new colour to the dot palette:
`#89dceb` (sapphire). Grey/yellow/blue/green/amber covers the
state space cleanly.

**Q8 — Notes truncation in compact banner?**
A: **Single line, ellipsis on overflow**, tooltip shows full notes.
Empty notes show `(no notes)` placeholder in muted text.

**Q9 — Source-root display in compact banner?**
A: **Final folder name only** (e.g. `TestOffice` for
`D:/.../TestObjects/TestOffice`). Tooltip shows full path. Shows
`(no source)` muted when unset.

## Design

### Top banner widget (`ProjectHeaderBanner`)

New class in `main_app.py`. Owns the menu button + edit-toggle button
+ both compact and expanded layouts (swapped via a QStackedWidget,
matching the empty-state pattern already in the current Project tab).

**Compact row 1** (HBox):
- Name label (bold, font-size +2pt)
- Scope label (muted)
- Source-root basename label (muted)
- *(stretch)*
- `Project ▾` QToolButton (popup menu)
- `Edit` QPushButton

**Compact row 2** (HBox):
- Notes single-line label (truncated with ellipsis, tooltip = full)

**Expanded form** (QFormLayout, replaces compact rows when Edit
is clicked):
- Name (QLineEdit, editingFinished → commit_metadata)
- Scope (QComboBox, currentIndexChanged → commit_metadata)
- Source Root (QLineEdit + Browse + status sub-label)
- Notes (QTextEdit, blurred → commit_metadata)
- Created (read-only label)
- Modified (read-only label)
- File (read-only label, shows `.u2oproj.json` path or "(unsaved)")
- Collapse button at bottom-right (replaces Edit's text when expanded)

The expanded form's widgets are the canonical source of project state;
the compact row labels mirror them and refresh on `project_changed`.

### Project menu (popup attached to `Project ▾`)

Items:
- **New…** (`Ctrl+N`)
- **Open…** (`Ctrl+O`)
- **Save** (`Ctrl+S`) — disabled when no project loaded
- **Save As…** (`Ctrl+Shift+S`) — disabled when no project loaded
- separator
- **Recent ▸** — submenu populated from `project_manager().recent()`
- separator
- **Close** — disabled when no project loaded

Each item calls the same `project_manager()` methods the current
Project tab toolbar already drives. The toolbar in the current
Project tab is removed; methods migrate to the banner widget.

### MainWindow layout

Current central widget structure:
```
QWidget
└─ QVBoxLayout
   ├─ DismissibleBanner (dep_banner)
   └─ QTabWidget
```

New central widget structure:
```
QWidget
└─ QVBoxLayout
   ├─ ProjectHeaderBanner    ← new
   └─ QTabWidget
       ├─ DashboardTab        ← renamed from ProjectTab
       │   ├─ DismissibleBanner (dep_banner, rehomed)
       │   ├─ Pipeline Status group (3 rows, new order + readiness)
       │   └─ Activity log
       ├─ SceneConverterTab
       ├─ PrefabProcessorTab
       ├─ TerrainTab
       └─ ConfigTab (corner button, hidden tab)
```

### Readiness summary API

Single module-level helper:

```python
def compute_stage_readiness(stage_key: str, project: Project) -> tuple:
    """Returns (severity, message). severity is one of:
      'unset'  → grey dot ○
      'partial'→ yellow dot ●
      'ready'  → blue dot ●
      'ok'     → green dot ●
      'warn'   → amber dot ●
    """
```

Replaces the inline `_refresh_status_row` logic in DashboardTab.
The dot-colour map lives in DashboardTab next to the renderer.

### `_STAGE_TAB_INDEX` update

New mapping driven by the new tab order:
```python
self._STAGE_TAB_INDEX = {
    "scene_converter":   scene_idx,    # 1
    "asset_processor":   prefab_idx,   # 2
    "terrain_processor": terrain_idx,  # 3
}
```

### Save-on-close

Stays in MainWindow.closeEvent. References to project state still
go through `project_manager()`. No change to that code path.

## Implementation Plan

### I.1 — `ProjectHeaderBanner` widget + menu
**Done when:**
- New class in `main_app.py`.
- Compact mode renders name/scope/root-basename row + notes row.
- Expanded mode renders the editable form (name, scope, scope_root +
  browse + status, notes, created, modified, file path).
- Edit button toggles between compact and expanded; label switches
  Edit ↔ Collapse.
- `Project ▾` button popups New/Open/Save/Save As/Recent/Close —
  identical wiring to current Project tab toolbar.
- Subscribes to `project_changed`, refreshes both modes.

### I.2 — Mount banner above tabs
**Done when:**
- `MainWindow.__init__` constructs the banner, inserts above the
  QTabWidget in the central VBox.
- `DismissibleBanner` no longer mounted at MainWindow level —
  passed to DashboardTab.

### I.3 — Rename Project tab → DashboardTab; rehome dep banner
**Done when:**
- Class `ProjectTab` renamed to `DashboardTab`. (Same file; tab
  registration uses the new label `"Dashboard"`.)
- Header form, notes editor, file-ops toolbar removed from the tab
  body — that content lives in `ProjectHeaderBanner` now.
- `DismissibleBanner` accepted as a constructor arg (or fetched from
  MainWindow via a method) and inserted at the top of DashboardTab.
- Pipeline Status group + Activity Log remain; positioned in that order.

### I.4 — Tab reorder
**Done when:**
- `MainWindow.__init__` registers tabs in order:
  Dashboard / Scene Converter / Prefab Processor / Terrain /
  Config (corner).
- `_STAGE_TAB_INDEX` updated accordingly.
- `--tab=` CLI mapping updated:
  `dashboard→0, scene→1, prefab→2, terrain→3`. `project` alias
  retained for backwards compat → 0.

### I.5 — Readiness summary chain
**Done when:**
- `compute_stage_readiness(stage_key, project)` module-level function
  exists with the per-stage chains from Q7.
- `DashboardTab._refresh_status_row` consumes it: dot text + dot
  colour from severity, summary label text from message.
- A new sapphire `#89dceb` dot colour represents the "ready" severity.

### I.6 — Verification

Manual proofs (against `TestObjects/TestProject.u2oproj.json` once
user populates real fields, or with the current empty fields):

| ID | Proof |
|---|---|
| T-1 | Launch app with TestProject loaded: banner shows project name + scope + (no source) on row 1; truncated notes on row 2; Project ▾ + Edit buttons right-aligned |
| T-2 | Click Edit: banner expands to show full form with all fields; click Collapse: banner returns to 2-row view |
| T-3 | Click Project ▾: menu shows New/Open/Save/Save As/Recent/Close with correct enabled states (Save grey when no path; all enabled when project loaded) |
| T-4 | Tab order left-to-right: Dashboard, Scene Converter, Prefab Processor, Terrain. Config still corner-button. |
| T-5 | Dashboard tab contents: dep-banner at top (when applicable), Pipeline Status with 3 rows in Scene-Prefab-Terrain order, Activity Log below |
| T-6 | Pipeline Status messages reflect testbed state. With empty TestProject: Scene row says "No source set" (grey); Prefab row says "No source set" (grey); Terrain row says "No source set" (grey) |
| T-7 | Set scope_root + select 2 scenes (no output) via Scene tab → Pipeline Status Scene row reads "2 of N scenes selected · No destination set" (yellow) |
| T-8 | Set output + click Convert Scenes → after run, Scene row reads "<ts> 2/2 scenes, X entities, Y prefab refs, 0 missing" (green) |
| T-9 | Close project from menu → banner shows "(no project loaded)" placeholder, Project ▾ still accessible, Edit disabled |

## Out of scope (deliberately)

- Per-stage skip toggles in pipeline status (F-8 work).
- Run All / dispatch buttons in the dashboard (F-8).
- Per-stage settings preview inside the dashboard status rows
  (defer until configuration is more complex).
- Sidebar navigation / collapsible left panel — straight tab bar
  stays.
- Drag-to-reorder tabs — tab order is fixed.
- Theming the new dot colours; reuses Catppuccin palette
  already in `THEME_QSS`.
