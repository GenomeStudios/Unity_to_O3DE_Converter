---
name: orchestration-plan
description: Design + locked decisions for F-8 — Mission Command pre-flight gating + Run All / Patch All orchestration that drives every stage as one operation.
metadata:
  type: project
---

# F-8 Orchestration + Pre-flight — Plan

Roadmap entry: `project_system/feature_roadmap` § F-8.

Linked: [[output-propagation-plan]] (F-9 — owns the worker plumbing
that consumes the settings F-8 orchestrates),
[[project-system-plan]] (Mission Command),
[[dependency-banner-plan]] (the always-visible meta UI pattern that
F-8 reuses).

## Goal

Make Mission Command the single launch surface for the conversion.
Pre-flight runs a structured set of checks; the user sees the result
as a list of severity-tagged rows with drill-down details; green
unlocks **Run All**, yellow lets the user per-row Acknowledge and
proceed, red hard-blocks. **Run All** then walks the stages in
dependency order (asset_processor → scene_converter → terrain) with
per-stage progress, cancel, and skip.

F-9 still owns the per-stage workers — F-8 only orchestrates and
gates. The "Run All" worker is just an orchestrator that invokes the
existing per-tab workers with the same plumbing F-9 ships.

## Resolved Decisions (Q&A)

**Q1 — Pre-flight gate behavior?**
A: **Block on red, warn on yellow, allow override per-row**.
- Red items hard-block (Run All disabled, can't be acknowledged).
- Yellow items get an Acknowledge checkbox per row. Once every yellow
  row is either resolved (now green) or acknowledged, Run All
  unlocks.
- Green items are decorative — they confirm the check passed.

**Q2 — Pre-flight check catalogue?**
A: One check function per stage, plus cross-cutting checks.
Categories:
- **Environment** (cross-cutting): dependencies present (delegates to
  F-1 banner state); scope_root exists + contains `Assets/`.
- **Asset Processor**: at least 1 prefab marked; every marked prefab
  exists in scope; output root chosen.
- **Scene Converter**: at least 1 scene marked; every scene exists;
  output root chosen.
- **Mesh Processor**: every override entry's mesh GUID exists in the
  inventory (else stale → yellow, "Clean up overrides?").
- **Material Processor**: every detected shader has a mapping OR
  user has acknowledged the unmapped set (yellow → green on ack);
  every override entry's material GUID exists in inventory.
- **Terrain**: if user has terrain materials marked, output root
  chosen.

Each check returns a `PreflightItem`:
```python
{
  "category":  "material_processor",
  "severity":  "red" | "yellow" | "green",
  "title":     "Unmapped Unity shaders",
  "detail":    "3 shaders without mapping: A, B, C",
  "fix_hint":  "Open Materials → Edit Mappings…",
  "ack_key":   "material.unmapped" | None
}
```

**Q3 — Where does Acknowledge state persist?**
A: In the project file under `project.preflight_acks: Dict[str,
str]`. Each entry maps `ack_key → snapshot_hash` so re-acknowledging
is only needed when the underlying condition's signature changes
(e.g. user already acked 3 unmapped shaders, then a 4th appears →
ack re-arms).

Snapshot hash for `material.unmapped` = sha256 of the sorted list of
unmapped shader names. Different per check; check function owns its
own snapshot computation.

**Q4 — Run All worker structure?**
A: A new `PipelineOrchestrator` class in `main_app.py` (or its own
module if it grows large enough). Drives stages serially with a
shared log + progress callback. Each stage maps to its existing
worker invocation — orchestrator doesn't re-implement the worker
code.

Stage order:
1. `asset_processor` (prefabs → materials → meshes → textures)
2. `mesh_processor` (.assetinfo if F-9 introduces a separate pass;
   else collapses into asset_processor)
3. `material_processor` (.material patch pass if F-9 puts it
   standalone)
4. `scene_converter` (per selected scene)
5. `terrain_processor` (per selected terrain material)

In practice F-9 keeps material + mesh + texture emission inside
`IntegratedAssetProcessor.process_prefab`, so stages 2 and 3 may not
appear as separate orchestrator steps. They DO appear in the
pre-flight panel since the checks are per-stage.

**Q5 — Cancel + skip semantics?**
A:
- **Cancel** — each per-stage worker takes a `Qt.QObject` cancel
  token. Cancel is best-effort: the worker finishes its current asset
  then exits. Orchestrator surfaces a "Cancel" button while Run All
  is in flight; on cancel, partial state is recorded (the assets that
  did emit have state_index entries; the rest are noted as
  "interrupted" in the run log).
- **Skip** — pre-Run-All, each stage row in Mission Command has a
  Skip-this-stage checkbox. Orchestrator omits skipped stages from
  the run.

**Q6 — Patch All?**
A: A second action button below Run All. Walks the state_index from
F-9, identifies dirty entries, re-emits only those. Pre-flight still
applies. Patch All is the cheap iterative workflow once the project
has been Run Once.

**Q7 — Progress + log surface?**
A: The existing per-tab log widgets stay. Run All adds a Mission
Command-level log strip (compact, last-N-lines) plus a per-stage
progress bar. Detailed log per stage continues to live in each tab.

**Q8 — Failure handling?**
A: A stage that throws marks itself red in the run report and
stops the orchestrator. User decides whether to fix + retry (which
becomes a Patch run since state was partially recorded) or skip the
stage on the next attempt.

**Q9 — Re-run vs Patch?**
A: Run All always rebuilds the state_index from scratch (clears
previous entries, re-emits all). Patch All consults the existing
state_index and re-emits dirty entries only. The two are presented
as separate buttons to keep the model clear.

**Q10 — What's deferred?**
A:
- Resume after partial cancel (auto-continuation). Manual Patch is
  the workflow.
- Parallel stage execution. Serial is fine and predictable for
  conversion workloads.
- Stage timing telemetry beyond what each worker already logs.
- Pre-flight history / trend tracking.

## Design

### Mission Command layout addition

Above the existing Pipeline Status cards, add a Pre-flight panel:

```
+-- Pre-flight ------------------------------------+
| [Refresh]                              [Run All] |
|                                       [Patch All]|
|                                                   |
| ● Environment                          (3 checks) |
|   ✓ Dependencies present                          |
|   ✓ Scope root: D:/.../AlienFantasyForest         |
|   ✓ Assets/ subfolder present                     |
|                                                   |
| ⚠ Asset Processor                      (1 yellow) |
|   ✓ 42 prefabs marked                             |
|   ⚠ 3 marked prefabs missing from scope           |
|       [Acknowledge]   Open Prefabs →              |
|                                                   |
| ● Scene Converter                      (all green)|
|   ✓ 2 scenes marked                               |
|                                                   |
| ✗ Material Processor                   (1 red)    |
|   ✓ 87 materials extracted                        |
|   ✗ shader_mappings inventory empty (run prefabs) |
|       Open Materials →                            |
+--------------------------------------------------+
```

Severity dots: ✓ green, ⚠ yellow, ✗ red. Panel collapses each
category into a count summary when collapsed.

### `PreflightReport` data class

```python
@dataclass
class PreflightItem:
    category: str           # "material_processor", "environment", ...
    severity: str           # "green", "yellow", "red"
    title:    str
    detail:   str
    fix_hint: str
    ack_key:  str | None    # set on yellow items; None means not ack-able

@dataclass
class PreflightReport:
    items: list[PreflightItem]
    @property
    def has_red(self) -> bool
    @property
    def needs_ack(self) -> list[PreflightItem]   # unacked yellows
    @property
    def can_run(self) -> bool                    # green-light gate
```

### Check functions

One per stage. Each accepts the project (+ any global state like
dependency status) and returns a list of `PreflightItem`:

```python
def check_environment(project, deps_present: bool) -> list[PreflightItem]: ...
def check_asset_processor(project) -> list[PreflightItem]: ...
def check_scene_converter(project) -> list[PreflightItem]: ...
def check_material_processor(project) -> list[PreflightItem]: ...
def check_mesh_processor(project) -> list[PreflightItem]: ...
def check_terrain_processor(project) -> list[PreflightItem]: ...
```

Lives in a new `preflight.py` module.

### `PipelineOrchestrator`

```python
class PipelineOrchestrator(QObject):
    stage_started   = Signal(str)       # stage_key
    stage_finished  = Signal(str, bool) # stage_key, success
    progress        = Signal(str, int, int)  # stage_key, done, total
    run_finished    = Signal(bool)      # overall success
    log             = Signal(str)

    def run_all(self, project, skip_stages: set[str]) -> None: ...
    def patch_all(self, project, skip_stages: set[str]) -> None: ...
    def cancel(self) -> None: ...
```

Internally invokes each per-stage worker the same way the per-tab
buttons do today, threading the same `material_settings` /
`mesh_settings` / `state_index` kwargs F-9 introduces.

## Implementation Plan

### I.1 — `preflight.py` + check functions

**Done when:**
- `PreflightItem` + `PreflightReport` dataclasses in
  `preflight.py`.
- Check functions for every stage (environment, asset_processor,
  scene_converter, material_processor, mesh_processor,
  terrain_processor).
- Ack snapshot hashing per check key.
- Unit tests: each check function exercised against a hand-built
  project carrying known-good and known-bad state.

### I.2 — Pre-flight panel in Mission Command

**Done when:**
- DashboardTab gains a Pre-flight section above Pipeline Status.
- Each category renders as a header with an expand toggle + count
  summary; expanded view lists per-item rows.
- Yellow rows render an Acknowledge button; clicking it writes the
  current snapshot to `project.preflight_acks`.
- Refresh button re-runs checks; the panel auto-refreshes on
  `project_changed` and on `status_changed` for any stage.
- Run All button is enabled only when `report.can_run` is True.

**Pause + verify with user.**

### I.3 — `PipelineOrchestrator`

**Done when:**
- Class exists with signals + cancel hook.
- `run_all` drives the existing per-stage workers in dependency
  order.
- Each stage's existing log widget receives the log stream;
  orchestrator also keeps a Mission-Command-level log strip.
- Stage failure stops the run and surfaces the offending stage.

### I.4 — Patch All

**Done when:**
- `patch_all` delegates to the F-9 patch path per stage.
- UI button visible alongside Run All. Pre-flight gating applies
  identically.

### I.5 — Cancel + per-stage Skip

**Done when:**
- Each stage worker honours a cancel token. Cancel partially-runs
  the current asset then exits cleanly.
- Mission Command shows a Cancel button while a run is in flight.
- Skip toggle per stage row in the Pre-flight panel; skipped stages
  are omitted from the run.

**Pause + verify with user.**

### I.6 — Verification matrix

| ID | Proof |
|---|---|
| T-1 | Empty project: report has at least 1 red (no scope root); Run All disabled |
| T-2 | Set scope root: red drops; remaining items reflect actual state |
| T-3 | Mark prefabs + scenes + Run All on a tiny project → all stages execute in order; state_index populated |
| T-4 | After Run All, tweak shader mapping, Patch All → only affected materials re-emit |
| T-5 | Pre-flight surfaces "3 unmapped shaders" yellow; Acknowledge unlocks Run All; adding a 4th shader re-arms |
| T-6 | Skip terrain stage → terrain step omitted from log; other stages still run |
| T-7 | Cancel mid-run → current asset finishes; orchestrator stops; state_index reflects partial progress |
| T-8 | Failing stage (e.g. write to read-only output) → marked red in report; orchestrator stops |

## Out of scope (deliberately)

- F-7 Terrain heightmap v1 (delayed by user).
- Parallel stage execution.
- Resume after cancel (Patch handles iterative recovery).
- Pre-flight history / trend dashboards.
- Stage timing telemetry beyond per-worker logs.
- Auto-suggest fix actions inside the pre-flight rows (just a
  fix_hint string + Open-tab links).
