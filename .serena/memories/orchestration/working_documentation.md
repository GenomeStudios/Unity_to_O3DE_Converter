---
name: orchestration-working-doc
description: Living status log for F-8 — Mission Command pre-flight + Run All / Patch All orchestration.
metadata:
  type: project
---

# F-8 Orchestration + Pre-flight — Working Documentation

Newest entries on top. Linked plan: [[orchestration-plan]].
Sibling: [[output-propagation-plan]] (F-9 — owns the worker plumbing
F-8 orchestrates).

## 2026-05-27 — F-8 shipped ✓ (I.1 → I.6)

### What landed

**`preflight.py`** — new module with:
- `PreflightItem(category, severity, title, detail, fix_hint, ack_key, ack_snapshot)` dataclass.
- `PreflightReport(items, acks)` with `has_red`, `needs_ack`, `can_run`,
  `categories()`, `by_category()`, `worst_severity()`.
- `_snapshot_hash(payload)` — sha256 over canonical JSON. The per-yellow
  ack_snapshot is computed against a stable representation of the
  underlying condition so adding/removing items drifts the hash.
- Six check functions: `check_environment`, `check_asset_processor`,
  `check_scene_converter`, `check_material_processor`,
  `check_mesh_processor`, `check_terrain_processor`. Each is pure (no
  UI, no signals, no project mutation), returns a list of items.
- `run_preflight(project, deps_present=True) -> PreflightReport`
  iterates `CHECK_REGISTRY` and snapshots `project.preflight_acks`.
- `CATEGORY_LABELS` — display strings for the panel.

**`Project.preflight_acks: Dict[str, str]`** — new field.
- Stored as a JSON-serializable map of `ack_key → snapshot_hash`.
- `to_json` / `from_json` round-trip it; legacy projects get `{}`.
- `set_preflight_ack(key, snapshot)` and `clear_preflight_ack(key)`
  mutators on Project. Both mark dirty on actual change.

**`_PreflightPanel(QWidget)`** in main_app.py — Mission Command surface:
- Top row: status banner + Refresh / Patch All / Run All buttons.
- One header per category showing the worst severity dot + count.
- Per-item rows with severity-coloured dot, title, optional detail,
  fix-hint tooltip.
- Yellow items with `ack_key` get an `Acknowledge` button; clicking
  writes the snapshot to `project.preflight_acks` and refreshes.
- Acknowledged-but-still-yellow rows render with the green dot + a
  "(acknowledged)" suffix so the user can see what's gated through.
- `Run All` enabled only when `report.can_run`. `Patch All` always
  enabled (its own internal dirty check decides what to do).
- Signals: `run_all_clicked`, `patch_all_clicked`, `refresh_clicked`.

**DashboardTab integration:**
- Panel rendered above Pipeline Status.
- `apply_project` calls `_refresh_preflight()` which runs the checks
  + applies the report.
- `showEvent` re-runs preflight so opening Mission Command sees the
  freshest state.
- Two new signals — `request_run_all`, `request_patch_all` — bubble
  the panel's button clicks to MainWindow.

**`PipelineOrchestrator(QObject)`** at module scope:
- `run_all(project, dispatch_callable)` computes the stage queue
  from selections (asset_processor / scene_converter /
  terrain_processor) and walks it in dependency order.
- Listens to `pm.processing_changed(stage, False)` to know when each
  per-tab worker finishes — no need to reimplement the workers.
- `dispatch_callable(stage_key)` is `MainWindow._process_stage`,
  the same hook the per-stage Dashboard buttons already use.
- Signals: `stage_started(stage_key)`, `stage_finished(stage_key)`,
  `run_finished(success, summary)`, `log(msg)`.
- `cancel()` drops queued stages; the currently-running stage runs
  to completion (best-effort cancel; mid-asset cancellation is a
  follow-up that needs per-worker cooperation).
- Implicit Skip: stages with no selections never enter the queue.

**MainWindow wiring:**
- Holds `self._orchestrator: PipelineOrchestrator`.
- `_on_run_all` checks for a loaded project, refuses to start if a
  pass is already running, then calls `_orchestrator.run_all(proj,
  _process_stage)`.
- `_on_stage_started_in_run` focuses the active stage's tab so the
  user sees the per-stage log scroll.
- `_on_run_all_finished` logs to the Dashboard activity log and
  switches focus back to the Dashboard.
- `_on_patch_all` delegates to MaterialTab's existing F-9 patch path
  (the only stage with a patch worker in F-9 scope).
- `_log_to_dashboard` — safe append-to-activity-log helper that
  no-ops when the log widget isn't constructed yet.

### Verification matrix (final)

| ID  | Proof                                                          | Status |
|-----|----------------------------------------------------------------|--------|
| T-1 | Empty project: at least 1 red, `can_run=False`                 | ✓      |
| T-2 | Set scope root + asset-proc fields: reds drop                  | ✓      |
| T-3 | Orchestrator walks asset_processor then scene_converter        | ✓      |
| T-4 | Patch All re-emits only affected materials                     | ✓ (via F-9.I.5) |
| T-5a| Unmapped shader → yellow with `ack_key`, blocks `can_run`      | ✓      |
| T-5b| Acknowledge → `can_run` flips to True                          | ✓      |
| T-5c| New unmapped shader → snapshot drifts → row re-arms            | ✓      |
| T-6 | Terrain stage with no `selected_materials` omitted from queue  | ✓      |
| T-7 | `cancel()` drops queued stages; current finishes               | ✓      |
| T-8 | Failing stage → marked red, orchestrator stops                 | deferred |

T-8 (per-stage failure routing) deferred — current orchestrator treats
all `processing_changed(stage, False)` as success. The plan to surface
worker exceptions through the orchestrator's `run_finished(False, ...)`
path needs cooperation from each per-tab worker to flag failure state
distinctly from completion. Tracked as a follow-up.

### Behavioural notes

- `PipelineOrchestrator.run_all` connects to `processing_changed`
  once per session and disconnects on completion — no listener
  accumulation across multiple runs.
- The orchestrator does NOT skip preflight on its own; Run All is
  gated on the panel side via `_run_all_btn.setEnabled(can_run)`.
  The panel re-runs preflight on every refresh + on every tab show.
- Acknowledge state persists into the project file. Re-opening a
  project with a still-matching condition leaves the row gated
  through; condition drift re-arms automatically.
- Mid-stage cancellation requires per-worker support. The current
  cancel is "stop the queue at the next stage boundary" — useful
  for "I started Run All by accident, don't queue more work".
- Patch All currently calls `MaterialTab._start_patch` because that's
  the only patch worker F-9 ships. When F-9's deferred mesh / prefab
  patch entrypoints land, Patch All becomes a multi-stage dispatcher
  (same orchestrator pattern, different dispatch_callable).

## F-8 Phase Status

- [x] I.1   — `preflight.py` module
- [x] I.1b  — `Project.preflight_acks` field + serialization
- [x] I.2   — Pre-flight panel in DashboardTab
- [x] I.3   — `PipelineOrchestrator` + Run All wiring
- [x] I.4   — Patch All wiring
- [x] I.5   — Cancel (orchestrator-level)
- [x] I.6   — Verification matrix (this entry)

## What this unlocks

- Mission Command is the single launch surface — Pre-flight gates,
  Run All orchestrates, Patch All iterates.
- New stages slot in as a single line in `_compute_queue` + a check
  function in `CHECK_REGISTRY`.
- F-10's profile editor can introduce new ack_keys (e.g.
  "profile.unused", "profile.has_missing_transform") that follow the
  same snapshot-drift pattern.

## Deferred follow-ups

- Per-worker failure routing (T-8) — surface `success=False` distinct
  from `processing_changed(False)` so a worker exception lands as a
  red on the orchestrator.
- Worker-level cancel — interrupt a running prefab loop mid-asset.
- Per-stage Skip toggle on the panel header (currently implicit via
  empty selection lists).
- Pre-flight history / trend tracking.
- Patch All across mesh + prefab when F-9's deferred patch
  entrypoints land.

## Open work / next session

F-8 is complete. Outstanding items in the roadmap:

- **F-7** (Terrain heightmap v1) — was explicitly delayed earlier in
  this project's history. Now unblocked: F-9 + F-8 are both in place,
  so adding a new stage is well-trodden ground.
- **F-10** (Profile editor) — the spinoff from F-9. Texture-map /
  property-map editor, profile duplication / deletion, cross-project
  library. See [[profile-editor-plan]].
- T-8 (per-worker failure routing).
- Worker-level cancellation.
