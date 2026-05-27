---
name: scene-marking-working-doc
description: Living status log for F-3 (multi-scene marking + nested O3DE level output). Newest entries on top.
metadata:
  type: project
---

# F-3 Scene Marking — Working Documentation

Newest entries on top. Linked plan: [[scene-marking-plan]].

## 2026-05-26 — Verification model clarified

The testbed is **the project file itself** —
`TestObjects/TestProject.u2oproj.json` — not the folder around it.
User populates fields via the GUI (scope_root, selected_scenes,
prefab_dirs, etc.); my verification reads whatever is populated and
exercises the new code against that. I do not author or mutate the
testbed's data fields from verification scripts (the F-3 verification
below briefly violated this — corrected in approach going forward).

Practical effect on the F-3 visual proof: the testbed currently has
`scope_root: ""` and `selected_scenes: []`, so I can't programmatically
exercise the scrubbing path off the testbed. User will set a real
scope_root (likely a Unity assets root under their working tree)
via the GUI; I'll re-verify against those values when populated.

## 2026-05-26 — F-3 shipped ✓

### What landed
- **`scrub_scope_for(root_text, pattern)`** module-level helper in
  `main_app.py`. Returns sorted relative paths. F-3 uses `"*.unity"`;
  F-4 will reuse for `"*.prefab"` and `"*.mat"`.
- **`_default_stages()['scene_converter']`** shape updated to
  `{source_path, selected_scenes, output_path, prefab_dirs}`. Old
  `scene_path` key is no longer emitted; old projects with the key
  load cleanly (it's just ignored).
- **`SceneConverterTab._build_ui` rewritten**:
  - Single scene file picker → multi-scene `QListWidget` checklist
    sourced from `scrub_scope_for(effective_source, "*.unity")`.
  - New top section: "Unity Assets Folder" override + Browse +
    effective-source info label (cyan when scope-fallback resolves,
    yellow when nothing set, hidden when override is filled).
  - Scene-list controls: Refresh from Scope / Select All /
    Clear Selection / Clear Missing.
  - Output structure info box updated to describe
    `<output>/<SceneName>/<SceneName>.prefab` nested layout.
  - Prefab Search Directories section retained (F-4 will replace).
- **`SceneConverterTab.apply_project`** loads `selected_scenes` into a
  `set[str]` (relative paths) + repopulates the checklist via
  `_refresh_scene_list()`. Missing-selection items render with the
  ⚠ glyph + tooltip; "Clear Missing" intersects the selection with
  the currently-scrubbed set.
- **`SceneConverterTab._start_conversion`** validates: ≥1 scene
  selected, output set, effective_source non-empty. Resolves each
  selected relative path to an absolute file. Missing selections
  trigger a Yes/No prompt before continuing with the resolved subset.
- **`SceneConverterTab._do_multi_conversion`** (replaces
  `_do_conversion`):
  - Serial loop over resolved scene paths.
  - Per-scene: fresh `UnitySceneConverter`, `<output>/<stem>/` dir
    created, `<output>/<stem>/<stem>.prefab` written, `finalize()`
    drops `.ImporterData/coverage.json` inside the per-scene folder.
  - Aggregates totals across scenes; logs progress per scene; catches
    per-scene exceptions and records them in `totals["failures"]`
    without aborting the run.
  - Writes `pipeline_status.scene_converter` with the new aggregated
    shape: `{last_run, scenes_converted, scenes_total,
    total_entities, total_prefab_references, total_missing_prefabs}`.
- **`ProjectTab._refresh_status_row`** updated to render the new
  multi-scene shape: `<ts>  N/M scenes, X entities, Y prefab refs,
  Z missing`. Amber dot fires on missing > 0.

### Sanity gates passed
- `py project_manager.py` → smoke OK (10 invariants).
- `py -c "import main_app"` → OK.
- Initial behavioural test used a synthetic temp scope tree (not the
  right approach — see model-clarified note above). Logic-side proofs
  for scrubbing, selection persistence, missing-glyph render, output
  path resolution, and pipeline_status shape passed. Will re-verify
  against real testbed values once the user populates scope_root.

### T-series status

| ID | Status |
|---|---|
| T-1 | covered by logic proof; awaiting real testbed values |
| T-2 | covered by logic proof; awaiting real testbed values |
| T-3 | covered by output-path logic proof; needs real Unity scene for full run |
| T-4 | covered by status-shape proof; needs a real run to visually confirm |
| T-5 | covered by missing-glyph logic proof |
| T-6 | covered by Clear-Missing logic proof |
| T-7 | logic confirmed (legacy `scene_path` key not referenced anywhere) |

### Visual QA the user can do
Launch `UnityToO3DE_Converter.bat`, with TestProject loaded:

1. Project tab → Browse to a real Unity assets folder containing
   one or more `.unity` scenes (e.g. an Alien Fantasy Forest
   assets root).
2. Set Source Root → save.
3. Switch to Scene Converter tab. Confirm the checklist has all
   `.unity` paths under that root, sorted, unchecked.
4. Check 1-2 scenes. Pick an output folder. Click Convert Scenes.
5. Watch the log show `[i/N]` per scene. Confirm each scene gets
   its own `<output>/<SceneName>/` folder with `<SceneName>.prefab`
   inside, plus `.ImporterData/coverage.json`.
6. Return to Project tab. Pipeline-status row for Scene Converter
   should read e.g. `2/2 scenes, 412 entities, 38 prefab refs,
   0 missing` with a green dot (or amber if missing > 0).
7. Delete one of the converted scenes from the source folder and
   relaunch the app → Scene Converter list shows ⚠ for it.

### Behaviour notes / known quirks
- The `scene_path` legacy field is no longer persisted but is silently
  tolerated in old project JSON (apply_project doesn't reference it).
- The "Refresh from Scope" button is also auto-triggered by
  `apply_project` (covers `project_changed` events including scope_root
  edits). No file-system watcher.
- The empty-state "no scenes scrubbed" rendering is implicit — when
  effective_source is empty or the directory has no `.unity` files,
  the checklist is just empty. We could add a placeholder "(scope
  has no Unity scenes — set a scope root in the Project tab)" text
  in a polish iteration.
- Per-scene `coverage.json` lives under
  `<output>/<SceneName>/.ImporterData/coverage.json`. Multiple scenes
  in one run = multiple coverage files. No aggregate cross-scene
  coverage today (could be a polish item).
- Failures per scene don't abort the run; they accumulate into the
  log + `totals["failures"]` list (not yet surfaced in pipeline_status,
  could be added as `failed_scenes` field).

## 2026-05-26 — Plan locked; starting I.1

11 design Q's resolved. User chose F-3 before F-4; analysis confirmed
F-3 and F-4 are more independent than the roadmap implied (only
coupling is the smart-default scene-by-prefab UX polish, not
structural).

## Pending / not yet shipped

- User-driven visual verification against real testbed values.
- Per-scene failure surfacing in `pipeline_status` (currently log-only).
- Empty-state placeholder text in the checklist.
- Smart-default selection by F-4 prefab inventory (lands after F-4).
- Cross-scene aggregate coverage report (polish).
