---
name: state-management-plan
description: Architectural refactor — replace the `.ImporterData/` sidecar pattern with project-owned output state, add an input-hash-driven sync model with per-stage states (unconfigured / ready / synchronized / unsynchronized / writing / error), and surface that state on each StageStatusCard.
metadata:
  type: project
---

# State Management & Sync — Plan

## Goal

Move from "the converter writes sidecars and the user trusts them" to
"the project file IS the state of the world". After this refactor:

- **`.ImporterData/` no longer exists.** Entity maps, asset index, and
  coverage reports live inside the `.u2oproj.json` file under a new
  `outputs` section.
- Every stage tracks an **input hash** alongside its last-run record.
  When current inputs hash differently than the last-run hash, the
  output is stale.
- Each `StageStatusCard` gains a **sync-state row** at the bottom
  reflecting how outputs relate to current settings, and a **Process**
  button alongside `Open ▸` so the user can re-export without
  switching tabs.

The user's stated motivation: while editing overrides and content fixes,
they sometimes find their changes didn't propagate to the O3DE editor
state despite expecting them to. This refactor makes staleness visible.

## Resolved Decisions (Q&A)

**Q1 — Sync model: manual export with sync badge, pure auto-propagate,
or pure manual?**
A: **Manual export with sync badge.** Process button per card; sync
state computed from input-hash comparison. Auto-patch (cheap
single-asset re-emit on override change) is a later opt-in for F-9.

**Q2 — How much state lives in the project file vs sidecars?**
A: **Full bookkeeping in the project file.** Entity maps, asset index,
coverage all absorb. `.ImporterData/` directory deleted on migration.

**Q3 — How many sync states?**
A: **Six**, separating configuration readiness from output freshness:
- `unconfigured` — requirements unmet; nothing to sync yet
- `ready`        — configured but never run; nothing exported yet
- `synchronized` — output exists and matches current inputs (✓ green)
- `unsynchronized` — inputs changed since last run; output is stale (amber)
- `writing`      — worker is currently processing (animated blue)
- `error`        — last run failed; output state is unknown (red)

**Q4 — Schema version bump?**
A: **Yes, v2.** `project.schema_version` becomes `2`. Migration: v1
projects load with an empty `outputs` section; first run populates it.
Existing `.ImporterData/` on disk is folded into the project on first
load post-upgrade (one-shot, idempotent).

**Q5 — What goes into the input hash for each stage?**
A: A stable JSON-canonicalized representation of:
- The stage's settings dict (source override, output, selected_*, prefab_dirs)
- The project's `scope_root` (since `effective_source` resolves through it)
- The set of relevant files' mtimes-or-hashes under the walking root,
  filtered to the file types that stage cares about (`*.unity` for
  scene_converter, `*.prefab` for asset_processor, `*.mat` for terrain)

Mtime-based for v1 (cheap); content-hash-based as a future polish if
mtime turns out to lie too often.

**Q6 — What gets stored under `outputs.<stage>`?**
A: Per stage:
- `last_run`        — ISO timestamp of the last successful run
- `last_input_hash` — hash that produced the current outputs
- `last_status`     — "ok" | "warn" | "error"
- `summary`         — same shape as today's pipeline_status
- `assets`          — per-asset records (entity maps, asset index, etc.)
- `coverage`        — punch list

**Q7 — Does the Process button block on the worker?**
A: **No.** It fires the same `WorkerThread` the tab uses today.
While it's running, the card's sync state shows `writing`. The
Process button disables; the Open ▸ button keeps working so the user
can watch the live log.

**Q8 — Should sync state surface on the project header banner too?**
A: **Not in this plan.** The banner stays high-level. Sync state is a
per-stage concern and lives on the cards. Could revisit if there's
demand for an aggregated "all stages synced" indicator.

**Q9 — When inputs change while writing, what state?**
A: The card stays `writing` until the worker finishes. On finish, the
hash is recomputed against current inputs — if they changed mid-run,
the card immediately shows `unsynchronized` because the just-written
outputs no longer match. This is the right behaviour: the user is
informed their in-flight edit didn't make it into the run.

**Q10 — Auto-patch / auto-sync toggle?**
A: **Deferred. Documented as a stretch goal for post-F-9.** A new
checkbox on the Config tab — `Auto-Sync changes` — will let the user
opt into automatic re-emit when stage settings or content change.
Until that toggle exists, all exports are explicitly manual via the
per-card Process button. When the toggle ships:
- `On`: editing an override (mesh / material / scope selection) fires
  a background patch worker that re-emits only the affected
  artifacts. Sync state transitions `unsynchronized → writing →
  synchronized` automatically.
- `Off` (default): same behaviour as v1; manual Process clicks only.

The toggle is wholly opt-in because automatic re-runs are expensive
for projects with hundreds of prefabs and the auto-patch worker's
correctness depends on F-9's patchability infrastructure being in
place. Hence post-F-9.

## Design

### Project file schema v2

```json
{
  "schema_version": 2,
  "name": "...",
  "scope": "...",
  "scope_root": "...",
  "notes": "...",
  "created": "...",
  "modified": "...",
  "stages": {
    "asset_processor":   { "source_path": "...", "output_path": "..." },
    "scene_converter":   { ... },
    "terrain_processor": { ... }
  },
  "pipeline_status": {
    "asset_processor":   { "last_run": "...", ... },
    "scene_converter":   { ... },
    "terrain_processor": { ... }
  },
  "outputs": {
    "asset_processor": {
      "last_run":        "2026-05-27T15:00:00Z",
      "last_input_hash": "a1b2c3...",
      "last_status":     "ok",
      "prefabs": {
        "<guid>": {
          "source_path":     "...",
          "output_path":     "Prefabs/Foo.prefab",
          "container_alias": "...",
          "entity_aliases":  { "<unity_fileID>": "<o3de_alias>", ... },
          "material_slots":  { "<unity_fileID>": ["<mat_guid_0>", ...] },
          "go_names":        { ... },
          "written_at":      "..."
        }
      },
      "materials": { "<guid>": { "output_path": "Materials/X.material", ... } },
      "meshes":    { "<guid>": { "output_path": "Meshes/Y.fbx", ... } },
      "coverage":  {
        "unhandled_component_types": { ... },
        "unhandled_override_paths":  { ... },
        "warnings":                   [ ... ]
      }
    },
    "scene_converter": {
      "last_run":        "...",
      "last_input_hash": "...",
      "last_status":     "ok",
      "scenes": {
        "<rel_path>": {
          "output_path":         "Levels/<stem>/<stem>.prefab",
          "entities":            42,
          "prefab_references":   8,
          "missing_prefabs":     [],
          "written_at":          "..."
        }
      },
      "coverage": { ... }
    },
    "terrain_processor": {
      "last_run":        "...",
      "last_input_hash": "...",
      "last_status":     "ok",
      "materials": {
        "<source_path>": {
          "output_path": "Terrain/Materials/X.material",
          "textures":    [ "Terrain/Textures/diffuse.png", ... ],
          "written_at":  "..."
        }
      },
      "coverage": { ... }
    }
  }
}
```

`pipeline_status` stays (it's the cheap summary the dashboard reads
without parsing all of `outputs`). `outputs` is the source of truth
for "what was actually produced".

### Sync-state computation

```python
def compute_stage_sync_state(stage_key: str, project) -> dict:
    """Return:
        {
          "state":   one of 'unconfigured' | 'ready' | 'synchronized'
                            | 'unsynchronized' | 'writing' | 'error',
          "label":   display string,
          "details": optional one-line detail (e.g. "5 files changed
                     since last export"),
        }
    """
```

Implementation:

1. If stage worker is currently running → `writing`.
2. Else if readiness's `status == 'incomplete'` → `unconfigured`.
3. Else if `outputs.<stage>.last_run` is None → `ready`.
4. Else if `outputs.<stage>.last_status == 'error'` → `error`.
5. Else compute `current_hash = input_hash_for(stage_key, project)`:
   - `== outputs.<stage>.last_input_hash` → `synchronized`
   - otherwise → `unsynchronized`

The `details` field provides specifics when unsynchronized — e.g.
"output dir missing", "3 selected scenes changed", "scope_root moved".

### Input hash function

```python
def input_hash_for(stage_key: str, project) -> str:
    """Stable hash of every input that affects this stage's output."""
```

Per stage, the hash inputs:

- **asset_processor**:
  - `effective_source` (after resolving scope_root override)
  - `stages.asset_processor.output_path`
  - For each `*.prefab` under the walking root: its relative path +
    mtime (or file content hash, future)
  - Project-level config that influences this stage
    (e.g. `convert_smoothness_to_roughness` from the global config)

- **scene_converter**:
  - `effective_source`
  - `selected_scenes` (sorted list)
  - `output_path`
  - `prefab_dirs` (sorted list) — until F-4 replaces this
  - For each selected scene file: relative path + mtime
  - For prefabs referenced by selected scenes: relative path + mtime
    (skipped if too expensive — defer to F-4 inventory)

- **terrain_processor**:
  - `effective_source`
  - `selected_materials` (sorted list)
  - `output_path`
  - For each selected `.mat` file: relative path + mtime

Hash algorithm: SHA-256 over the JSON-canonicalized blob. First 16 hex
chars for compact display in the project file.

### `StageStatusCard` extension

Current card layout (post-recent-restructure):
```
┌─────────────────────────────────────────────┐
│ Stage Name   Status      [Open ▸]           │
│   ✓ Source: …                               │
│   ✓ N of M scenes selected                  │
│   ✗ No destination set                      │
│   ───────                                   │
│   Last run … (only if completed)            │
└─────────────────────────────────────────────┘
```

Post-refactor:
```
┌─────────────────────────────────────────────┐
│ Stage Name   Status      [Process] [Open ▸] │
│   ✓ Source: …                               │
│   ✓ N of M scenes selected                  │
│   ✗ No destination set                      │
│   ───────                                   │
│   Last run … (only if completed)            │
│   ⚡ Synchronized   Last exported 2 min ago │
└─────────────────────────────────────────────┘
```

- New **sync-state row** at the bottom: glyph + label + details.
- New **Process** button next to Open ▸. Disabled when the stage isn't
  ready (`unconfigured`) or already running (`writing`).
- Card object names get an additional `stage_card_sync` for QSS.

### Process button wiring

The Process button on the card emits `request_process(stage_key)`.
MainWindow connects this to a slot that delegates to the relevant tab's
existing worker entry point:

```python
def _process_stage(self, stage_key: str) -> None:
    target_widget = self._tabs.widget(self._STAGE_TAB_INDEX[stage_key])
    if stage_key == "scene_converter":   target_widget._start_conversion()
    elif stage_key == "asset_processor": target_widget._start_processing()
    elif stage_key == "terrain_processor": target_widget._start_generation()
```

No new worker shapes; just exposes the existing handlers to the card.

### Migration

On `ProjectManager.bootstrap()`:

1. Read project file. If `schema_version < 2` → run migration:
   - Add empty `outputs` section.
   - For each stage's `output_path`: if `<output_path>/.ImporterData/`
     exists, parse the sidecar files and absorb:
     - `asset_index.json` → `outputs.asset_processor.{prefabs,
       materials, meshes}` (lifted to project-keyed records)
     - `<stem>.entitymap.json` → `outputs.asset_processor.prefabs[<guid>]`
       (entity_aliases, material_slots, etc.)
     - `coverage.json` → `outputs.<stage>.coverage`
   - Compute `last_input_hash` from CURRENT inputs (so the first
     post-migration state shows `synchronized` rather than
     `unsynchronized` — assumes the user hasn't edited since the run).
   - Bump `schema_version` to 2.
   - Save.
   - Optionally (off by default for v1): delete the `.ImporterData/`
     dir. Leave it for now so the user can roll back manually if
     anything goes wrong; we sweep it in a later cleanup.
2. If `schema_version == 2` → no-op.

Migration is idempotent: re-running finds `schema_version == 2` and
does nothing.

### Worker integration

Each stage's `_do_*` worker, on success, now:

1. Computes the asset-level records (already done today, just written
   to sidecars).
2. Persists those records to `project.outputs.<stage>` via a new
   `ProjectManager.update_outputs(stage_key, outputs_dict)` method
   (which saves the project file).
3. Computes and stores `last_input_hash` = `input_hash_for(stage_key, project)`.
4. Updates `pipeline_status` (existing behaviour).
5. Stops writing to `.ImporterData/`.

The consumers of the old sidecars (Stage 1 override propagation,
Stage 2 prefab database) get refactored to read from `project.outputs`
instead.

## Implementation Plan

### I.1 — Schema v2 + Project model changes
**Done when:**
- `SCHEMA_VERSION = 2` in `project_manager.py`.
- `Project.outputs: dict` field exists with `_default_outputs()` shape.
- `from_json` reads `outputs` if present, defaults to empty otherwise.
- `to_json` writes `outputs`.
- `ProjectManager.update_outputs(stage_key, outputs)` method (analogous
  to `update_status`, but persists to `outputs.<stage>`).
- Smoke test grows assertions for outputs round-trip.

### I.2 — Input hash + sync-state computation
**Done when:**
- `input_hash_for(stage_key, project) -> str` exists in `main_app.py`
  (or a new `sync_state.py` if main_app gets too big).
- `compute_stage_sync_state(stage_key, project) -> dict` returns the
  6-state dict described above.
- Unit-ish smoke: same inputs → same hash; perturb any input → hash
  changes.

### I.3 — `StageStatusCard` sync row + Process button
**Done when:**
- Card has a new bottom row with sync-state glyph + label + details.
- `request_process` signal added; wired from a new Process button next
  to Open ▸.
- Process button disabled when state is `unconfigured` or `writing`.
- QSS rules for `#stage_card_sync` (color follows the 6 states).
- DashboardTab passes `request_process` through to MainWindow's
  `_process_stage` slot.

### I.4 — Worker persistence to `outputs`
**Done when:**
- IntegratedAssetProcessor.finalize and UnitySceneConverter.finalize
  (and TerrainMaterialProcessor's equivalent) write into
  `project.outputs` via `pm.update_outputs` instead of (or alongside)
  the sidecars.
- Workers compute and store `last_input_hash` at end of run.
- Toggle: keep sidecar writes for ONE release cycle as a fallback so
  manual diff'ing is possible. Removed in a follow-up after migration
  stabilises.

### I.5 — Consumer refactor (read from outputs, not sidecars)
**Done when:**
- Stage 1 override propagation reads entity maps from `project.outputs.asset_processor.prefabs[<guid>]` instead of `<stem>.entitymap.json`.
- Stage 2 prefab database (until F-4 replaces it) reads from
  `project.outputs.asset_processor.prefabs` when available, falls back
  to disk scan otherwise.
- `coverage.json` writes go to `project.outputs.<stage>.coverage`.

### I.6 — Migration: `.ImporterData/` → project
**Done when:**
- `migrate_schema_v1_to_v2(project)` helper exists.
- Called from `ProjectManager.open` and `bootstrap` when project's
  `schema_version` < 2.
- Sweeps any `.ImporterData/` under the project's output paths into
  the new `outputs` section.
- `schema_version` bumped to 2; project saved.
- Idempotent.
- Sidecar files NOT deleted yet (rolled back in I.4 follow-up).

### I.7 — Sidecar removal (deferred until I.4 stabilises)
**Done when:**
- IntegratedAssetProcessor + UnitySceneConverter stop writing
  `.ImporterData/` files entirely.
- Migration helper deletes any leftover `.ImporterData/` dirs after
  successful absorption.
- Release-notes entry documents the change so users with custom
  scripts referencing those sidecars get a heads-up.

### I.8 — Verification

| ID | Proof |
|---|---|
| T-1 | Empty project: all three cards show `unconfigured` |
| T-2 | Fully configured project, never run: cards show `ready` (Process enabled) |
| T-3 | Run scene_converter: card transitions `ready → writing → synchronized` |
| T-4 | After run, edit selected_scenes: card flips to `unsynchronized` |
| T-5 | Re-run: card flips back to `synchronized` |
| T-6 | Force an exception inside the worker: card shows `error` |
| T-7 | Load a v1 project: migration sweeps `.ImporterData/` (if present), bumps schema, leaves card in `synchronized` (since current inputs == last-run inputs at migration time) |
| T-8 | Round-trip: open v2 project saved by another session, all `outputs` fields restored intact |

## Out of scope (deliberately)

- **`Auto-Sync changes` Config toggle.** Stretch goal for post-F-9 —
  a Config-tab checkbox that opts the user into automatic background
  re-emit when overrides / selections change. Requires F-9's
  patchability infrastructure to be correct on the auto-side, so it
  lands AFTER F-9. Default off when shipped.
- **Cross-stage sync** (e.g. "if asset_processor is unsynchronized,
  scene_converter must also be unsynchronized because it depends on
  prefabs"). Each stage's sync is independent for now; pre-flight
  in F-8 can add cross-stage rules later.
- **File-system watcher** so the card auto-updates when files change
  externally. v1 recomputes on tab focus / project_changed; user can
  add a Refresh action if needed.
- **History of runs.** Only the latest run is recorded. F-9 may extend.
- **Project file diff/merge tooling.** The file is single-user single-machine.

## F-Roadmap Implications

| F | Was | Becomes |
|---|---|---|
| **F-4 prefab checklist** | Just UI | UI + feeds `input_hash_for("asset_processor")` |
| **F-5 mesh preprocessing** | Sidecar + dirty bit | Writes mesh overrides into `project.outputs.asset_processor.meshes` directly; sync state already surfaces them |
| **F-6 material library** | Library + remap | Same library; per-project material remap stored in `project.outputs.asset_processor.materials` |
| **F-8 orchestration** | Pre-flight + Run All | Pre-flight now includes cross-stage sync checks |
| **F-9 patching** | Build state index from scratch | **State index is the project. Much smaller scope.** |
