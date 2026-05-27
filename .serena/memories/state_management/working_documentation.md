---
name: state-management-working-doc
description: Living status log for the state-management refactor — sidecars absorbed into the project file, input-hash-driven sync state, Process buttons + sync rows on status cards.
metadata:
  type: project
---

# State Management & Sync — Working Documentation

Newest entries on top. Linked plan: [[state-management-plan]].

## 2026-05-27 — State management shipped ✓

### What landed

**I.1 — Project.outputs model**
- `Project.outputs: dict` field with `_default_outputs()` shape:
  per-stage `{last_run, last_input_hash, last_status, ..., coverage}`.
- `Project.update_outputs(key, dict)` mutator + `Project.to_json` /
  `from_json` round-trip.
- `ProjectManager.update_outputs(stage_key, dict)` — worker-facing API
  that updates + saves + emits `status_changed`.
- `SCHEMA_VERSION` bumped to **2**. Old format projects without
  `outputs` load cleanly (defaults to empty per-stage dicts).
- Smoke test grew to **11 invariants**, including outputs round-trip
  and old-format compatibility.

**I.2 — Input hash + sync state**
- `input_hash_for(stage_key, project) -> str` (16-char SHA-256
  prefix) over: scope_root, effective_source, output_path, stage
  selections, and mtime fingerprints of relevant files
  (`*.prefab` for asset_processor, the selected `*.unity` for
  scene_converter, each `*.mat` for terrain_processor).
- `compute_stage_sync_state(stage_key, project, *, writing=False)`
  returns `{state, label, details}` with the 6-state machine:
  - `writing` (flag override)
  - `unconfigured` (readiness incomplete)
  - `ready` (configured, never run)
  - `error` (last_status == 'error')
  - `synchronized` (current hash == last_input_hash)
  - `unsynchronized` (hash mismatch)
- Color palette in `_SYNC_STATE_COLORS`.

**I.3 — `StageStatusCard` extension**
- Banner row gains a **Process** button between the status badge and
  Open ▸. `Process` emits `process_clicked` signal; disabled when
  sync state is `unconfigured` or `writing`.
- New bottom row: `_sync_label` with state-colored glyph + label +
  details. Visual sync-state palette:
  - `○` grey (unconfigured)
  - `◐` sapphire (ready)
  - `●` green (synchronized)
  - `◑` amber (unsynchronized)
  - `↻` blue (writing)
  - `✕` red (error)
- QSS additions: `#stage_card_process` (filled button with disabled
  state styling), `#stage_card_sync` (color set dynamically).
- `update_state(readiness, sync_state)` signature replaces the old
  single-arg version.

**I.4 — Process buttons wired through MainWindow**
- `DashboardTab.request_process_stage(stage_key)` Qt signal added.
- `MainWindow._process_stage(stage_key)` dispatches to the relevant
  tab's existing worker entry point (`_start_conversion` /
  `_start_processing` / `_start_generation`). Same code path the
  in-tab bottom button uses.
- `dashboard_tab.request_process_stage.connect(self._process_stage)`
  wired up in `MainWindow.__init__`.

**I.5 — Workers persist outputs to project; sidecars dropped**
- `IntegratedAssetProcessor`:
  - `self.importer_data_dir` removed (and its mkdir).
  - `_write_entity_map_sidecar` now stores records in
    `self._project_prefab_records` (keyed by guid or stem) and the
    in-memory `self._entity_map_cache` (keyed by source path). No
    disk write.
  - `_load_entity_map_sidecar` reads from the in-memory cache only;
    cross-prefab override propagation within a run still works.
  - `_write_asset_index` and `_write_coverage_report` removed.
    `finalize()` is now a one-line summary log.
  - New `to_outputs() -> dict` returns the consolidated bookkeeping
    (prefabs / materials / meshes / coverage).
- `UnitySceneConverter`:
  - `finalize(output_dir=None)` no longer writes
    `.ImporterData/coverage.json`. One-line summary log instead.
  - New `to_coverage()` returns the run's coverage dict.
- `TerrainMaterialProcessor` was already sidecar-free; no change.
- Tab workers (`_do_processing`, `_do_multi_conversion`,
  `_do_generation`) now call `pm.update_outputs(STAGE_KEY, ...)`
  with `last_run`, `last_input_hash`, `last_status` plus the
  processor's consolidated dict.

**I.6 — Consumer refactor**
- `UnitySceneConverter.__init__` takes optional
  `entity_maps_by_stem={}` and `asset_index={}` kwargs. These
  replace the old sidecar-reading methods.
- `_load_entity_map_sidecar(prefab_path)` returns
  `self._entity_maps_by_stem.get(prefab_path.stem)`.
- `_get_asset_index(hint_path)` returns the injected dict.
- `SceneConverterTab._do_multi_conversion` builds both dicts from
  `project.outputs.asset_processor` and passes them into each
  per-scene `UnitySceneConverter`.

**Writing-flag wiring**
- `ProjectManager.processing_changed(str, bool)` signal added.
- `ProjectManager.set_processing(stage_key, writing)` is called by
  each tab's `_start_*` (set True) and `_on_finished` (set False).
- `DashboardTab` connects `processing_changed` to
  `mark_stage_writing`, which flips the card's sync state to
  `writing` while in flight.

**UI polish**
- Prefab tab's "Output Structure" info no longer references
  `.ImporterData/` — replaced with a one-liner explaining outputs
  live in the project file.
- Scene tab info likewise updated.

### Sanity gates passed

- `py project_manager.py` → smoke OK (11 invariants).
- `py -c "import main_app, integrated_asset_processor,
  unity_scene_converter_gui"` → OK.
- E2E sync-state transitions against the live testbed:
  - **Initial**: all three stages `unconfigured` (missing destinations).
  - **Simulate ok run**: `unconfigured → synchronized` ✓
  - **Mutate inputs**: `synchronized → unsynchronized` ✓
  - **Writing flag**: any state → `writing` ✓
  - **last_status='error'**: → `error` ✓
- **Live processing flow**: `Ready → Writing → Ready` cycle via
  `set_processing(True)` / `set_processing(False)` with Process
  button auto-disable during writing ✓
- Input hash stable across calls + changes deterministically when
  any input changes ✓

### Files no longer written by the converter

- `<output>/.ImporterData/asset_index.json` — gone
- `<output>/.ImporterData/<stem>.entitymap.json` per prefab — gone
- `<output>/.ImporterData/coverage.json` (Stage 1 + Stage 2) — gone

All this data now lives in `<project>.u2oproj.json` under
`outputs.<stage>.{prefabs, materials, meshes, scenes, coverage,
last_run, last_input_hash, last_status}`.

### Stretch goal carried forward

- **`Auto-Sync changes` Config-tab toggle (post-F-9).** Default off.
  When enabled, edits to overrides / selections / mappings fire a
  background patch worker so sync state transitions
  `unsynchronized → writing → synchronized` without a manual Process
  click. Depends on F-9 patchability for correctness.

### F-roadmap state going forward

The state-management refactor pays the largest dividend at F-9
(patching). Because the project file now holds every output's
fingerprint + record, F-9 collapses from "build a state index" to
"use the data the project already records". F-4 (prefab checklist)
feeds the input hash naturally. F-5 (mesh overrides) and F-6
(material library) write directly into `outputs.<stage>`. F-8 pre-
flight gains a "cross-stage sync check" rung.

## 2026-05-27 — Plan locked; awaiting go-ahead

10 design Q's resolved. Two key user choices:
- **Manual export with sync badge** — Process button per card, sync
  state surfaces input-hash mismatches. Auto-patch deferred to F-9.
- **Full bookkeeping in project file** — `.ImporterData/` absorbs.

User then said: abandon all legacy versioning. Migration step collapses
to "drop schema_version checks, default `outputs` to empty if missing".
Sidecar removal happens in I.5 directly (no transitional fallback).

## Pending / not yet shipped

- F-4 onward (feature implementation resumes).
- Auto-Sync Config toggle (deliberate post-F-9 work).
