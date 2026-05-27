---
name: project-system-working-doc
description: Living status log for the Conversion Project system (Mission Command tab + named projects). Newest entries on top. Tracks shipped pieces, regressions, decisions in flight, and pending items.
metadata:
  type: project
---

# Conversion Project System — Working Documentation

Newest entries on top. Linked plan: [[project-system-plan]].

## 2026-05-26 — I.4 closed; base prop-up complete

### What landed
- **Save-on-close hook**: `MainWindow.closeEvent` checks
  `pm.current().is_dirty()`. The only path that can be dirty at close
  is a freshly-created New project the user never saved (the converter
  tabs auto-save via `pm.update_stage` which writes immediately when
  `path` is set; `commit_metadata` does the same for header edits).
  If dirty:
  - Prompt Yes / No / Cancel.
  - **Yes** + path is None → Save As… dialog; abort close if user cancels.
  - **Yes** + path is set → `pm.save()`.
  - **No** → discard, close.
  - **Cancel** → ignore the event, keep the window open.

### I.4 done-when items
- ✓ Window title binds to current project name (landed in I.3 pass).
- ✓ `--tab=project` / `--tab=terrain` CLI args supported.
- ✓ Default tab on launch is Project (index 0).
- ✓ Closing the app saves any dirty project state (prompts when needed).

### What's left for I.5
End-to-end verification with the user's actual data (T-2 → T-8 in the
plan's testing matrix). User runs `UnityToO3DE_Converter.bat`.

### Status of the base prop-up
**Shipped:** I.0 / I.1 / I.2 / I.3 / I.4. Ready for feature development
on top.

## 2026-05-26 — I.2 + I.3 landed; awaiting user verification

### What shipped this pass
- **`main_app.py` imports updated**: pulls `Project`, `ProjectScope`,
  `ProjectManager`, `project_manager`, `PROJECT_FILE_EXT`, `STAGE_KEYS`,
  and `_utc_now_iso` from `project_manager`. New PySide6 widgets added
  for the Mission Command UI: `QComboBox`, `QToolButton`, `QMenu`,
  `QStackedWidget`, `QFrame`, `QFormLayout`, `QInputDialog`, `QAction`.
- **`main()` bootstraps the project system**: `project_manager().bootstrap()`
  runs after `QApplication` and before `MainWindow`, so each tab's
  `__init__` sees the auto-loaded project. `--tab=` now accepts
  `project|prefab|scene|terrain`, mapped to indices 0–3.
- **PrefabProcessorTab / SceneConverterTab / TerrainTab refactored**
  to the project contract:
  - Class constant `STAGE_KEY`.
  - `apply_project(project)` replaces `_load_settings()`. Reads from
    `project.stage_settings(STAGE_KEY)` (or clears fields if project=None).
  - `_collect_stage_settings()` returns the current UI's dict.
  - `_save_settings()` is now a thin field-edit hook that calls
    `project_manager().update_stage(STAGE_KEY, self._collect_stage_settings())`
    — no-op when no project is loaded.
  - `__init__` subscribes to `project_changed` and calls
    `apply_project(pm.current())` to catch up on the already-loaded
    project (signal-emit during bootstrap predates subscription).
  - End-of-run `_do_*` workers call `project_manager().update_status(...)`
    with stage-specific summary dicts (see schema below).
- **`ProjectTab` (Mission Command) added** as new TAB 0:
  - Toolbar: New… / Open… / Save / Save As… / Recent ▾ / Close.
  - Stacked: populated panel (header, notes, pipeline-status rows,
    activity log) vs empty-state card ("No project loaded").
  - Header form: Name (QLineEdit), Scope (QComboBox of ProjectScope),
    Created / Modified labels, File path label (shows "(unsaved)" pre-saveas).
  - Notes: `_NotesEdit` subclass of QTextEdit that emits `blurred` on
    focusOut → commits notes via `pm.commit_metadata()`.
  - Pipeline status: 3 rows (Prefab Processor / Scene Converter /
    Terrain Materials), each row = dot + label + summary + Open ▸ btn.
    Dot: ○ grey (never run) / ● green (clean run) / ● amber (errors).
    Open ▸ emits `request_focus_stage(stage_key)` → MainWindow switches tab.
  - Activity log shows in-memory session events (open/save/close/status).
- **`ProjectManager.commit_metadata()`** added — used by the Project tab
  after `Project.set_name` / `set_scope` / `set_notes` to save and re-emit
  `project_changed` (so window title and other observers refresh).
- **`MainWindow` wires**:
  - Tab order: Project (0) / Prefab (1) / Scene (2) / Terrain (3) /
    Config (hidden, corner button).
  - `_STAGE_TAB_INDEX` map + `_focus_stage(key)` slot connect ProjectTab's
    Open ▸ signal to the correct tab index.
  - Window title binds to `project_changed`: `Unity → O3DE Converter — <name>`
    or `… — (no project)` when nothing is loaded.

### `pipeline_status.<stage>` shape (locked from worker integrations)
```
asset_processor:
  { last_run, prefabs_processed, prefabs_total,
    materials_written, textures_copied, meshes_copied, errors }

scene_converter:
  { last_run, entities, prefab_references, blank_entities, missing_prefabs }

terrain_processor:
  { last_run, materials_written, materials_total, textures_written, errors }
```

### Sanity gates passed
- `py -c "import ast; ast.parse(...)"` → parse OK
- `py -c "import main_app"` → import OK (all symbols resolve)
- `py project_manager.py` → smoke OK (8 invariants; `commit_metadata`
  added without disturbing existing tests).

### What the user verifies (T-2 through T-8)
Launch `UnityToO3DE_Converter.bat`. Expected:

1. **First launch migration (T-2)**: existing `converter_settings.json`
   has `asset_processor` and `scene_converter` keys → on launch, a
   `Projects/Legacy.u2oproj.json` is created next to it, the global
   file is rewritten to keep only `config` + `projects.{current,recent}`,
   and the title bar reads
   `Unity → O3DE Converter — Legacy (auto-migrated)`.
2. **Tab population (T-3)**: Prefab + Scene tabs show the same paths
   they had before; Terrain tab is empty (no legacy `terrain_processor`).
   Edit a path on any tab → relaunch → path restored from
   `Legacy.u2oproj.json`, NOT from `converter_settings.json`.
3. **Project lifecycle (T-4)**: Project tab → New… → enter a name →
   header populates, stack switches to populated panel, file label shows
   "(unsaved)". Save As… to a chosen path → file label updates, .json
   ends with `.u2oproj.json` regardless of what the user typed.
4. **Recent menu (T-5)**: Open 2–3 projects in sequence → Recent ▾ shows
   them most-recent-first; clicking re-opens. Missing files are silently
   filtered out.
5. **Status dashboard (T-6)**: run any converter → returning to Project
   tab shows the dot turn green/amber and the summary populate with the
   stage's `pipeline_status.<key>` fields.
6. **Empty state (T-7)**: from Project tab, click Close → stack swaps
   to "No project loaded" card; other tabs clear; window title shows
   "(no project)". Browse/Add buttons in converter tabs are still
   clickable but `_save_settings` no-ops (intentional, not a bug).
7. **CLI (T-8)**: `py main_app.py --tab=terrain` lands on the Terrain
   tab (index 3) with the active project's terrain settings.

## 2026-05-26 — I.1 shipped (data model + manager) ✓

### What landed
- `project_manager.py` at repo root, ~360 lines, single self-contained module.
- `ProjectScope` enum: `whole_game` / `asset_cluster` / `asset_set` / `individual_action`, each with a `display_name()`.
- `Project` dataclass with `to_json` / `from_json`, mutation helpers
  (`update_stage`, `update_status`, `set_name`, `set_scope`, `set_notes`)
  and dirty-flag tracking.
- `ProjectManager(QObject)` with `project_changed(object)` and
  `status_changed(str)` signals. Methods:
  `bootstrap`, `current`, `new_project`, `open`, `save`, `save_as`,
  `close`, `recent`, `push_recent`, `update_stage`, `update_status`,
  `commit_metadata` (added during I.2 wiring).
- `project_manager()` singleton accessor (caller invokes `bootstrap()`
  once after the QApplication is constructed).
- Legacy migration helper `_migrate_legacy_settings` runs from `bootstrap()`,
  sweeps `asset_processor` / `scene_converter` / `terrain_processor` keys
  from the global settings file into `<settings_dir>/Projects/Legacy.u2oproj.json`,
  rewrites the global file to point at it. Idempotent.
- File extension: `.u2oproj.json`. `_normalize_project_path` enforces it on
  `save_as` regardless of what the user typed in the dialog.
- `__main__` smoke test exercises 8 invariants. Result: **OK**.

### T-1 status: ✓ passed
Smoke proof from the plan's testing matrix. Run with `py project_manager.py`.
(Note: smoke test must be invoked through the `py` launcher, not bare
`python` — the user's default `python` on PATH is a 3.9 install without
PySide6. `py` resolves to the install that has PySide6.)

## Pending / not yet shipped

- **I.5** — End-to-end smoke verification with the user's actual data
  (T-2 through T-8 above).
- Future iterations (out-of-scope, see plan): dispatch from Mission
  Command, multi-run history, persisted activity log, asset checklist.

## Resolved follow-ups
*(none yet)*
