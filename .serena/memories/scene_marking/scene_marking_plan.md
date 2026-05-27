---
name: scene-marking-plan
description: Design + locked decisions for F-3 — replace single-scene picker with a scrubbed multi-scene checklist; output each selected scene into the O3DE-convention nested folder (<output>/<SceneName>/<SceneName>.prefab).
metadata:
  type: project
---

# F-3 Scene Marking + Multi-Scene Output — Plan

## Goal

Replace the SceneConverterTab's single `scene_path` picker with a
**checklist of every `.unity` scene found inside the project's scope
walking root**. The output structure becomes nested per scene:
`<output>/<SceneName>/<SceneName>.prefab` plus per-scene
`.ImporterData/coverage.json` — matching O3DE's level-folder convention.

The testbed [TestObjects/TestProject.u2oproj.json](TestObjects/TestProject.u2oproj.json)
will run against `TestObjects/TestOffice/` as scope_root. (TestOffice
currently has no `.unity` scenes, so the checklist UI will demonstrate
empty-scope behaviour. Add a scene file there during user verification
to exercise the full path.)

## Resolved Decisions (Q&A history)

**Q1 — Where do scenes come from?**
A: Walk `effective_source("scene_converter")` (per the F-2 fallback
contract) for `*.unity` files via rglob. Override → scope_root → empty.

**Q2 — Output folder structure?**
A: **Nested per-scene folders.** Each selected scene `Demo/Demo1.unity`
emits to `<output>/Demo1/Demo1.prefab` with sidecars under
`<output>/Demo1/.ImporterData/`. Matches O3DE levels convention.
The user-chosen output folder is the parent that contains all the
per-scene level folders. (Considered: flat output —
rejected because O3DE expects nested.)

**Q3 — Worker model: serial loop or parallel?**
A: **Serial.** Each scene gets its own fresh `UnitySceneConverter`
instance, parses, emits, finalises. Parallel would force per-scene
`PrefabDatabase` instances and log interleaving. Serial keeps the
log readable and matches the existing worker pattern.

**Q4 — Persistence of the scene selection?**
A: New list `stages.scene_converter.selected_scenes: list[str]`. Each
string is a **scene path RELATIVE to the effective_source walking root**.
Relative paths make the project portable (move scope_root → selections
still resolve). Resolving at runtime: `<effective_source> / rel_path`.

**Q5 — Default selection state?**
A: **None checked.** Explicit user consent for each scene. F-4 will add
"auto-check scenes whose prefabs you've selected" once the prefab
checklist exists; not in F-3.

**Q6 — When does the scene list refresh?**
A: **Manually via Refresh button + automatically on `project_changed`**
(covers scope_root changes, project switches, project open). No
file-system watcher.

**Q7 — Existing `prefab_dirs` setting?**
A: **Left untouched.** F-4 replaces it with a project-aware prefab
checklist. F-3 keeps the directory list working so scenes can still
resolve their prefab references.

**Q8 — Missing-scene handling?**
A: A selected scene whose relative path no longer resolves under the
effective_source is rendered in the list with a ⚠ glyph and a tooltip.
Persists in `selected_scenes` (doesn't auto-evict). User can manually
uncheck or use the **Clear Missing** button.

**Q9 — `pipeline_status.scene_converter` shape with multi-scene runs?**
A: Aggregated across all scenes converted in the run:
```
{ last_run, scenes_converted, scenes_total,
  total_entities, total_prefab_references, total_missing_prefabs }
```
Replaces (additively, no breaking change for old single-scene runs)
the existing `entities / prefab_references / blank_entities /
missing_prefabs` shape. Old keys can drop with the schema change.

**Q10 — Migration of an existing JSON with a `scene_path`?**
A: **No automatic migration.** `scene_path` is a legacy single-file
field; the new flow is multi-scene checklists. Old projects open
cleanly (the new code ignores `scene_path`) and the user re-selects
scenes via the new UI. Document this in the working doc.

**Q11 — Source override field (the F-2 fallback pattern)?**
A: Add it for parity with the other tabs. Tab gains a `source_path`
override line edit + Browse + effective-source info label.
`source_path` empty + `scope_root` set → scenes scrub from scope.
Override → scenes scrub from override. Both empty → empty checklist,
clear empty-state message.

## Design

### Persistence — `stages.scene_converter`

```json
"scene_converter": {
  "source_path":     "",                         // F-2 override
  "selected_scenes": ["Demo/Demo1.unity"],       // relative to effective_source
  "output_path":     "D:/.../Levels",
  "prefab_dirs":     ["D:/.../Prefabs"]          // unchanged (F-4 will replace)
  // "scene_path" (legacy single-file path) silently ignored if present
}
```

### `SceneConverterTab` UI rebuild

Top-to-bottom:

1. **Unity Assets Folder** (new section, mirrors Prefab tab):
   - QLineEdit override + Browse + effective-source info label.
   - editingFinished + browse-pick trigger `_save_settings()` and
     `_refresh_scene_list()`.
2. **Scenes to Convert** (replaces old scene_path single picker):
   - `QListWidget` with `Qt.ItemIsUserCheckable` items.
   - Each item: display text = relative path; check state = inclusion;
     `setData(Qt.UserRole, abs_path)` for resolved absolute path;
     missing items get ⚠ prefix + grey-yellow tooltip.
   - Buttons: **Refresh from Scope** / **Select All** /
     **Clear Selection** / **Clear Missing**.
3. **O3DE Output Folder** (unchanged).
4. **Prefab Search Directories** (existing, unchanged for now).
5. **Output Structure** info box updated:
   `Each selected scene → <output>/<SceneName>/<SceneName>.prefab`.
6. **Log + actions** (unchanged shape).

### Scrubbing helper

Module-level in `main_app.py` (or a small `scope_scrubber.py` if the
file gets too big):

```python
def scrub_scope_for(root: Path, pattern: str) -> list[Path]:
    """Return relative paths under `root` matching `pattern`.
    Empty / non-existent root → []."""
```

Called once on Refresh + on `project_changed`. Returns paths sorted
case-insensitively.

### Selection-state model

In `SceneConverterTab`:

```python
self._selected_scenes: set[str] = set()    # relative paths, persisted
self._scope_scenes:    list[Path] = []     # relative paths currently scrubbed
```

Apply-project loads `_selected_scenes` from JSON. Refresh rebuilds
`_scope_scenes` from disk. List render merges both: any path in
`_scope_scenes` shows as a regular item with its persisted check state;
any path in `_selected_scenes` NOT in `_scope_scenes` shows as a
missing item.

`_collect_stage_settings()` writes back `_selected_scenes` as a sorted
list for stable diffs.

### Worker rewrite

```python
def _do_multi_conversion(
    scenes:      list[Path],       # absolute paths
    output_dir:  str,              # parent levels folder
    prefab_dirs: list[str],
    log,
) -> str:
    log("=" * 60)
    log("STARTING MULTI-SCENE CONVERSION")
    log(f"Scenes : {len(scenes)}")
    log(f"Output : {output_dir}")
    log("=" * 60)

    prefab_db = PrefabDatabase()
    for d in prefab_dirs:
        prefab_db.add_search_directory(Path(d))

    totals = { "scenes_converted": 0, "entities": 0,
               "prefab_references": 0, "missing_prefabs_total": 0 }

    for i, scene_path in enumerate(scenes, 1):
        scene_stem = scene_path.stem
        scene_out_dir = Path(output_dir) / scene_stem
        scene_out_dir.mkdir(parents=True, exist_ok=True)

        log(f"\n[{i}/{len(scenes)}] {scene_path.name}")
        try:
            conv = UnitySceneConverter(prefab_db, log_callback=log)
            conv.parse_unity_scene(str(scene_path))
            out_prefab = scene_out_dir / f"{scene_stem}.prefab"
            total, refs, blanks = conv.create_o3de_level(
                str(out_prefab), scene_out_dir
            )
            conv.finalize(scene_out_dir)
            totals["scenes_converted"]    += 1
            totals["entities"]             += total
            totals["prefab_references"]    += refs
            totals["missing_prefabs_total"] += len(conv.missing_prefabs)
        except Exception as e:
            log(f"  ✗ Scene failed: {e}")

    # Status update fires from _on_finished, not here, so the WorkerThread
    # signal model stays unchanged. We return both summary string AND
    # totals dict for status; the WorkerThread expects a string so the
    # tab stashes the totals on self before _on_finished reads them.
    return ("Scenes: {scenes_converted}/{total}  |  Entities: {entities}  |  "
            "Prefab refs: {prefab_references}  |  Missing: {missing_prefabs_total}"
           ).format(total=len(scenes), **totals)
```

### Status hook

Tab tracks `self._last_run_totals: dict` populated as a side-effect of
`_do_multi_conversion` (stash on `self` via a closure or attribute).
`_on_finished` reads it and calls `pm.update_status(...)`. Old single-
scene status shape is replaced.

## Implementation Plan

### I.1 — Persistence schema change
**Done when:**
- `_default_stages()` in `project_manager.py` updates the
  `scene_converter` entry to:
  `{"source_path": "", "selected_scenes": [], "output_path": "",
    "prefab_dirs": []}`.
- Smoke test still passes (existing scene_converter assertions don't
  break — they don't reference the legacy `scene_path` field directly).

### I.2 — UI rebuild
**Done when:**
- SceneConverterTab `_build_ui` emits the new layout (override field +
  effective-source label, scenes checklist, refresh/select-all/clear/
  clear-missing buttons, unchanged output + prefab dirs).
- `apply_project` loads `selected_scenes` and calls `_refresh_scene_list()`.
- `_collect_stage_settings()` writes `source_path`, `selected_scenes`,
  `output_path`, `prefab_dirs`.
- Refresh button re-scrubs from `effective_source(scene_converter)`.
- Missing-scene rendering (⚠ glyph, tooltip).

### I.3 — Worker rewrite
**Done when:**
- `_do_conversion` → `_do_multi_conversion` matching the design block
  above.
- `_start_conversion` validates: at least 1 scene selected, output set;
  resolves selected relative paths to absolute via effective_source.
- Output structure verified by inspecting one converted scene folder.

### I.4 — Status aggregation
**Done when:**
- `_on_finished` (or the worker, via a stashed-totals trick) calls
  `pm.update_status("scene_converter", {…aggregated fields…})`.
- Mission Command status row renders the new shape: "N/M scenes,
  X entities, Y prefab refs, Z missing".

### I.5 — Verification with testbed

Manual proofs (drop a `.unity` file under `TestObjects/TestOffice/` to
exercise the full path):

| ID | Proof |
|---|---|
| T-1 | Open TestProject in app, scope_root = TestOffice → Scene tab scenes list is empty + helper message visible |
| T-2 | Drop a `.unity` file at `TestOffice/Demo/Foo.unity`, click Refresh → list shows `Demo/Foo.unity` unchecked |
| T-3 | Check the scene, click Process → run completes; output folder contains `<output>/Foo/Foo.prefab` + `<output>/Foo/.ImporterData/coverage.json` |
| T-4 | Project tab status row reads `1/1 scenes, X entities, Y prefab refs, Z missing` |
| T-5 | Delete the scene from disk, restart app → list shows `Demo/Foo.unity` with ⚠ glyph and tooltip |
| T-6 | Clear Missing button removes the orphan; relaunch → it stays cleared |
| T-7 | Open an old project that still has a legacy `scene_path` key → app loads cleanly, scenes list is empty (no crash, no migration) |

## Out of scope

- Smart-default selection (e.g. auto-check scenes whose referenced
  prefabs are selected). Lands with F-4.
- Replacing the `prefab_dirs` directory list with a scope-driven
  prefab checklist. That is F-4.
- Watch the filesystem for new `.unity` files; user-triggered Refresh
  only.
- Scene parse cache (entity count, prefab refs preview before
  conversion). Defer to a polish iteration on F-3 once F-4 lands.
- Per-scene output override (e.g. one scene → custom folder name).
  Sticks to `<SceneName>/<SceneName>.prefab` for v1.
- Cancellable mid-run. Worker still runs to completion; a Cancel
  button is F-8 (orchestration) work.
