---
name: project-system-plan
description: Design + locked decisions for the Conversion Project system — first-class named projects with save/load/recent, a Project (Mission Command) tab, and per-project storage of all converter settings/state.
metadata:
  type: project
---

# Conversion Project System — Plan

## Goal

Upgrade the Unity → O3DE Converter from a single-shared-settings tool into a **multi-project workspace**:

- A **Conversion Project** is a named, savable bundle of every path, every selected asset, every per-stage state for one importation pipeline.
- The user can **New / Open / Save / Save As / Recent** projects from the GUI.
- A new **Project** tab (the *Mission Command* dashboard) lives at tab index 0, before all converter tabs, summarising the loaded project and showing pipeline status across the Prefab / Scene / Terrain stages.
- Projects scope flexibly: whole game conversion, asset cluster, single asset set, or individual action (e.g. a one-off terrain material export).

The base implementation here is the **prop-up** — the load-bearing data model, file format, manager, Mission Command shell, and integration with the existing tabs. Future features (richer dashboard widgets, dispatch-from-cockpit, asset checklists, run history) build on top.

## Resolved Decisions (Q&A history)

**Q1 — Where do project files live on disk?**
A: **User-chosen path** via Save As dialog. Each `.u2oproj.json` lives wherever the user picks (typical: alongside the O3DE output folder, or in a per-game working dir). Recent list tracks absolute paths.

**Q2 — How is project scope modeled?**
A: **Enum + freeform notes.** Scope is one of:
- `whole_game` — entire game project conversion
- `asset_cluster` — a group of related asset sets
- `asset_set` — one self-contained set of assets
- `individual_action` — one-off micro-task (e.g. a single terrain material export)
Plus a separate `notes` freeform text field.

**Q3 — Empty state on launch?**
A: **Last-opened project auto-loads.** App stores `current_project_path` in the global settings. On launch, if that path exists, reload it; otherwise fall back to a *no-project* empty state (tabs render with placeholder header "No project loaded — File ▸ New / Open").

**Q4 — Project tab role?**
A: **Navigate + dashboard only** for the base. Mission Command shows pipeline status (Prefab / Scene / Terrain — each with last-run timestamp + summary counts) and offers Jump-To-Tab buttons. Dispatching converters from the cockpit is a follow-up phase.

## Design

### Project file (`<user-chosen>.u2oproj.json`)

```json
{
  "schema_version": 1,
  "name": "Alien Fantasy Forest Demo",
  "scope": "whole_game",
  "notes": "Demo1.unity + props + terrain materials",
  "created":  "2026-05-26T12:00:00Z",
  "modified": "2026-05-26T14:32:00Z",
  "stages": {
    "asset_processor": {
      "source_path": "...",
      "output_path": "..."
    },
    "scene_converter": {
      "scene_path":  "...",
      "output_path": "...",
      "prefab_dirs": [ "..." ]
    },
    "terrain_processor": {
      "source_path":        "...",
      "output_path":        "...",
      "selected_materials": [ "..." ]
    }
  },
  "pipeline_status": {
    "asset_processor":   { "last_run": "2026-05-26T13:00:00Z", "prefabs_written": 42, "errors": 0 },
    "scene_converter":   { "last_run": null, "instances_placed": 0, "missing_prefabs": 0 },
    "terrain_processor": { "last_run": "2026-05-26T14:15:00Z", "materials_written": 8, "errors": 0 }
  }
}
```

- `schema_version` is reserved for forward compatibility.
- `stages.<stage>` exactly mirrors the section shapes used today in `converter_settings.json`. Migration is trivial.
- `pipeline_status.<stage>` is populated by the converter at the end of a run (replacing the previous record); never authored by hand. Used by Mission Command to render the dashboard.

### Global settings (`converter_settings.json`) — repurposed

The legacy flat file becomes app-level state only:

```json
{
  "config": {
    "convert_smoothness_to_roughness": true
  },
  "projects": {
    "current": "D:/.../MyGame.u2oproj.json",
    "recent": [
      "D:/.../MyGame.u2oproj.json",
      "D:/.../OtherGame.u2oproj.json"
    ],
    "recent_limit": 10
  }
}
```

The `asset_processor` / `scene_converter` / `terrain_processor` keys are migrated **once** on first launch into a default project file (`<repo>/Projects/Legacy.u2oproj.json`) and removed from the global file. Migration is one-shot and idempotent (no-op if those keys are absent).

### `Project` data model (`project_manager.py` — new module)

```python
class ProjectScope(str, Enum):
    WHOLE_GAME        = "whole_game"
    ASSET_CLUSTER     = "asset_cluster"
    ASSET_SET         = "asset_set"
    INDIVIDUAL_ACTION = "individual_action"

@dataclass
class Project:
    path: Path | None              # None = unsaved
    name: str
    scope: ProjectScope
    notes: str
    created:  str                  # ISO-8601 UTC
    modified: str                  # ISO-8601 UTC
    stages:           dict         # nested per-stage settings dicts
    pipeline_status:  dict         # per-stage status dicts

    def to_json(self) -> dict: ...
    @classmethod
    def from_json(cls, data: dict, path: Path) -> "Project": ...
    def stage_settings(self, key: str) -> dict: ...
    def update_stage(self, key: str, settings: dict) -> None: ...
    def update_status(self, key: str, status: dict) -> None: ...
    def is_dirty(self) -> bool: ...   # tracked via modified-since-save
```

### `ProjectManager` singleton

```python
class ProjectManager(QObject):
    project_changed = Signal(object)   # emits current Project (or None)
    status_changed  = Signal(str)      # stage key whose status updated

    def current(self) -> Project | None: ...
    def new_project(self, name: str, scope: ProjectScope) -> Project: ...
    def open(self, path: Path) -> Project: ...
    def save(self) -> None: ...
    def save_as(self, path: Path) -> None: ...
    def close(self) -> None: ...
    def recent(self) -> list[Path]: ...
    def push_recent(self, path: Path) -> None: ...
```

Singleton accessor: `project_manager()` returns a process-wide instance.
On construction, attempts to auto-load `projects.current` from global settings; emits `project_changed`. Tabs subscribe to that signal.

### Tab integration contract

Every converter tab (`PrefabProcessorTab`, `SceneConverterTab`, `TerrainTab`) gains two methods:

```python
STAGE_KEY: ClassVar[str]   # e.g. "asset_processor"

def apply_project(self, project: Project | None) -> None:
    """Repaint UI fields from the project's stage settings (or clear if None)."""

def collect_into_project(self, project: Project) -> None:
    """Write the current UI field values into project.stages[STAGE_KEY]."""
```

Behaviour:

- On `ProjectManager.project_changed`, every tab calls `apply_project(new)`.
- On any field edit (browse-path, add-material, etc.), the tab calls `collect_into_project(current)` and then `ProjectManager.save()` — the project file is the authoritative store. If there is no current project, the tab silently skips persistence (user is in *no-project* mode).
- Pipeline-status updates: at the end of `_do_processing` / `_do_conversion` / `_do_generation`, the worker writes a status dict via `ProjectManager.update_status(STAGE_KEY, {...})`.

### Mission Command tab (`ProjectTab`)

Layout (top to bottom):

1. **Toolbar row** — `New ▾`, `Open…`, `Save`, `Save As…`, `Recent ▾`, `Close`. (Recent is a `QToolButton` with popup menu.)
2. **Header group** —
   - Project name (`QLineEdit`)
   - Scope (`QComboBox` populated from `ProjectScope`)
   - Created / Modified labels (readonly)
   - Project file path label (readonly, shows `(unsaved)` when `path is None`)
3. **Notes** — multi-line `QTextEdit` (autosave on focusOut).
4. **Pipeline Status** group — three rows, one per stage:

   ```
   Prefab Processor   ● 2026-05-26 13:00   42 prefabs, 0 errors        [Open ▸]
   Scene Converter    ○ never run                                       [Open ▸]
   Terrain Materials  ● 2026-05-26 14:15   8 materials, 0 errors        [Open ▸]
   ```

   - `●` = green when `last_run` set + 0 errors; amber when errors > 0; `○` grey when never run.
   - `[Open ▸]` switches `QTabWidget` to that stage's tab index.
5. **Activity log** (small) — last N project events (project opened/saved, stage run finished). Persisted to the project file under a future `activity` key (stub for now — base implementation just shows in-memory current-session events).

When no project is loaded, the header + status panes show a placeholder card: *"No project loaded — click **New** or **Open** to begin."* The toolbar `New` / `Open` / `Recent` buttons remain active.

### `MainWindow` wiring

- Tab order becomes: **Project** (new, index 0) / Prefab Processor / Scene Converter / Terrain / Config.
- Window title shows `Unity → O3DE Converter — <project_name>` (or `… — (no project)`).
- `ProjectManager.project_changed` updates the window title.
- `--tab=` CLI arg gains a `project` value (default), in addition to existing `prefab` / `scene` (+ now `terrain`). `project` opens tab index 0.

### Backwards compatibility / migration

On first launch after the upgrade:

1. Read legacy `converter_settings.json`.
2. If any of `asset_processor` / `scene_converter` / `terrain_processor` keys exist:
   - Create `<repo>/Projects/Legacy.u2oproj.json` with scope=`whole_game`, name="Legacy (auto-migrated)", populated from those keys.
   - Set `projects.current` to that path.
   - Remove the migrated keys from `converter_settings.json`.
3. Save the rewritten global file.

This is one-shot and idempotent. Users with no legacy data land in *no-project* state cleanly.

## Implementation Plan

### I.0 — Plan + working doc memories
**Done when:** this file + `working_documentation.md` exist under `.serena/memories/project_system/`. *(this stage, in progress)*

### I.1 — Data model + `ProjectManager` module
**Done when:**
- `project_manager.py` exists with `Project`, `ProjectScope`, `ProjectManager` classes.
- `Project.to_json` / `from_json` round-trips a project file losslessly.
- `ProjectManager.new_project`, `open`, `save`, `save_as`, `close`, `recent`, `push_recent` all functional.
- `project_changed` / `status_changed` Qt signals defined.
- Singleton `project_manager()` accessor returns a stable instance.
- Migration helper `migrate_legacy_settings()` implemented and called once on first ProjectManager construction; idempotent.
- Unit-style smoke test (a small `if __name__ == "__main__"` block at the bottom of the module) creates, saves, loads, and updates a project against a temp file and prints OK.

### I.2 — Tab integration contract (no UI changes yet)
**Done when:**
- `PrefabProcessorTab`, `SceneConverterTab`, `TerrainTab` each:
  - Declare `STAGE_KEY` class constant.
  - Implement `apply_project(project)` (replaces today's `_load_settings`).
  - Implement `collect_into_project(project)` (replaces today's `_save_settings` body shape).
  - Subscribe to `ProjectManager.project_changed`.
  - On end-of-run, call `ProjectManager.update_status(STAGE_KEY, summary_dict)`.
- Field-edit handlers (`_browse_*`, `_add_*`, `_remove_*`, `_clear_*`) call into the manager instead of the legacy save path.
- Legacy `load_settings()` / `save_settings()` retained but only used by `ConfigTab` and the migration step.
- App launches with an auto-migrated `Legacy.u2oproj.json` from existing `converter_settings.json` and all three tabs render the same paths as before.

**Verification pause** — user runs app, confirms paths populate from the migrated project, edits a path, confirms it persists on relaunch into the project file (not into `converter_settings.json`).

### I.3 — `ProjectTab` Mission Command UI
**Done when:**
- New `ProjectTab(QWidget)` class added in `main_app.py`, placed at tab index 0 in `MainWindow.__init__`.
- Toolbar (New / Open / Save / Save As / Recent / Close) wired to `ProjectManager` methods.
- Header (name, scope combo, created/modified labels, file path label) reads + writes the current project.
- Notes `QTextEdit` autosaves on focus loss.
- Pipeline Status group renders three stage rows with status dot + summary text + `[Open ▸]` button (button calls `self._tabs.setCurrentIndex(...)` via a parent signal).
- Activity log shows in-memory session events (no persistence yet).
- When no project is loaded, the panel shows the empty-state card; toolbar remains usable.

**Verification pause** — user creates a new project, edits paths in other tabs, returns to Project tab, confirms name/notes/scope persist and pipeline status accurately reflects last runs.

### I.4 — `MainWindow` wiring + window title + CLI
**Done when:**
- Window title binds to current project name.
- `--tab=project` (and `--tab=terrain`) CLI args supported in addition to existing two.
- Default tab on launch is Project (tab 0) unless `--tab=` overrides.
- Closing the app saves any dirty project state.

### I.5 — Full smoke test
**Done when:** `python main_app.py` launches, the Project tab is the default, the auto-migrated Legacy project loads, all three converter tabs show their populated paths, a New project can be created + saved + reopened, Recent menu populated.

## Testing matrix

| ID | Proof | Lands with |
|----|-------|-----------|
| T-1 | `project_manager.py` __main__ smoke block: create → save → load → mutate → save → re-load, equality checks pass | I.1 |
| T-2 | First-launch migration: existing `converter_settings.json` with all three stage sections produces `<repo>/Projects/Legacy.u2oproj.json` with the same paths, and the global file is rewritten without those keys | I.2 |
| T-3 | Tabs read + write through ProjectManager: edit a path in Prefab tab → file written → relaunch app → path restored from project file (NOT from legacy settings) | I.2 |
| T-4 | Project tab toolbar: New project, set scope + notes, Save As to a chosen path, close, Open same path, fields restored verbatim | I.3 |
| T-5 | Recent menu: opening 3 projects in sequence populates Recent with the 3 paths, most-recent-first; selecting one reopens it | I.3 |
| T-6 | Pipeline status: running Prefab stage updates `pipeline_status.asset_processor.last_run` and the dashboard row reflects the new timestamp + counts without needing app restart | I.3 |
| T-7 | Empty state: with `projects.current=null` and no recent, app launches into Project tab with the "no project loaded" card; other tabs render with empty fields and do not crash on browse / add / clear | I.3 |
| T-8 | CLI: `python main_app.py --tab=terrain` lands on the Terrain tab with the active project's terrain settings populated | I.4 |

T-2 / T-3 / T-4 / T-5 / T-6 / T-7 / T-8 are user-verified behavioural proofs (PySide6 GUI; no headless harness). T-1 is a literal script smoke test.

## Out of scope (deliberately)

- **Run from Mission Command.** Dispatching the converters from the Project tab itself is a follow-up phase. The base ships with Jump-To-Tab navigation only.
- **Multi-project compare / diff.** No "what changed between projects" view.
- **Project-level locking / multi-user concurrency.** Single-user local tool; the file is just JSON.
- **Asset-level checklist tracking.** A future feature could record which prefabs/materials are "approved" or "needs rework"; not in base.
- **Run history (more than one entry per stage).** Base records *latest* run only in `pipeline_status`; history is a future extension.
- **Activity log persistence.** In-memory only for base; future iteration writes it into the project file.
- **Cross-project asset sharing.** Each project is self-contained.
