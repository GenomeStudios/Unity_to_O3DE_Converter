# Pass-2 Consolidation — Working Documentation

Newest entries at top.

Pair plan: `mem:pass2_consolidation/pass2_consolidation_plan`.

---

## 2026-05-27 — Pass-2 landed

Pass-2 is complete. All 5 implementation stages shipped in one session
after the Pass-1 mechanical cleanup. Tests green at 16/16 modules under
`py -3.13`. `main_app` smoke-imports clean.

### What's now on disk

Root `.py` files (4 — orchestration only):
- `main_app.py` — GUI entry point.
- `integrated_asset_processor.py` — Stage-1 worker.
- `project_manager.py` — schema, `SourceEngine`, `Project`, materialtype resolver.
- `preflight.py` — Mission Command preflight engine.

Root packages:
- `platforms/` — plugin contract + Unity reference.
- `targets/` — O3DE reference target.
- `tools/` — standalone helpers (Blender FBX baker).
- `tests/` — 16 modules / ~95 tests.

`platforms/unity/` now contains the full Unity plugin:
- `unity_platform.py` (the `SourcePlatform` impl)
- `asset_database.py`
- `coordinates.py`
- `prefab.py` (canonical YAML parsers)
- `scene_converter.py` (Stage-2 worker, moved from root)
- `shader.py`
- `terrain.py` (Stage-3 worker, moved from root)
- `types.py` (canonical `Transform` / `GameObject` / `UnityComponent`)
- `components/` (auto-discovered processor library)

### What each stage delivered

**I.1 — Scene converter migration (done).**
- `platforms/unity/scene_converter.py` created with the body of the
  old `unity_scene_converter_gui.py:1-1117` minus its duplicate
  `Transform` / `GameObject` dataclasses.
- Imports `Transform`, `GameObject` from `platforms.unity.types`.
- Added `prefab_name: Optional[str] = None` to canonical `GameObject`
  in `platforms/unity/types.py` (was on the old local copy; needed
  by `PrefabDatabase` name-fallback resolution).
- `main_app.py:3597` now imports from the new path.
- Root `unity_scene_converter_gui.py` deleted.
- Tests: 17/17 green.

**I.2 — Terrain processor migration (done).**
- `platforms/unity/terrain.py` created from
  `terrain_material_processor.py`.
- `AssetDatabase` import re-pointed from
  `integrated_asset_processor` → `platforms.unity.asset_database`.
- `main_app.py:5850` now imports from the new path.
- Root `terrain_material_processor.py` deleted.
- Tests: 17/17 green.

**I.3 — `components/` shim deletion (done).**
- 3 internal callers re-pointed: `integrated_asset_processor.py`,
  `platforms/unity/scene_converter.py`, `targets/o3de/prefab_writer.py`.
- Root `components/__init__.py` + `components/base.py` deleted; the
  whole `components/` directory is gone.
- `tests/unit/test_components_shim.py` deleted (it pinned the contract
  that's now gone).
- Docstring updated in `platforms/unity/components/__init__.py` (its
  usage example pointed at the old import path).
- Tests: 16/16 green (down from 17 by design — the shim test was the
  delta).

**I.4 — Parser unification (partial, by design).**
- **Done:** `UnitySceneConverter.convert_to_o3de_coordinates` now
  delegates to `targets.o3de.prefab_writer.convert_to_o3de_coordinates`.
  The local duplicate (an identical 18-line function) is gone.
- **Deferred:** the YAML parser (`parse_unity_scene` +
  `_parse_transform` / `_parse_game_object` / `_parse_prefab_instance` /
  `_build_hierarchy`) was NOT unified with
  `platforms.unity.prefab.parse_unity_scene`.
- **Why:** scene-level vs prefab-level ``PrefabInstance`` blocks have
  different emission semantics. In a prefab, a PrefabInstance is a
  nested reference and gets folded INTO `game_objects`. In a scene,
  a PrefabInstance is a top-level placement and goes into a separate
  `self.prefab_instances` list that drives the O3DE level's
  `Instances` map directly. Forcing the canonical parser onto the
  scene converter would change that semantic and break
  `_process_prefab_instances`.
- **What landed instead:** the docstring on
  `platforms.unity.prefab.parse_unity_scene` was updated to spell out
  the divergence and stop calling for unification as "future work".
  The "two parser paths can be unified" comment was deleted.
- **Future work, separate plan:** if unification is wanted, the right
  approach is to extend the canonical parser with a flag like
  `prefab_instance_mode=("nested"|"scene_placement")` and migrate
  scene_converter once that contract is settled. This is a behaviour
  change, not a refactor — it gets its own plan + working doc.

**I.5 — Final verification (done).**
- `py -3.13 tests/run_all.py` → 16/16 modules green.
- `py -3.13 -c "import main_app"` → clean.
- This memory + the plan memory + `mem:project/converter_working_status`
  were refreshed to reflect post-Pass-2 reality.

### Pre-existing diagnostic hints (unchanged)

While re-pointing the components import in `integrated_asset_processor.py`,
the IDE surfaced several unused-import / unused-symbol hints that pre-date
Pass-2 (`os`, `math`, `random`, `ProcessingContext`, `UnityComponent`,
unused helpers in the FBX assetinfo path). These are out of scope for
the structural refactor and weren't touched. Listed here so a future
cleanup pass can address them deliberately.

### What's NOT done after Pass-2

Per the plan's "Out of scope" section, still deferred:
- AssetDatabase wiring in Stage 2 (no mesh/material emit on unowned
  scene entities).
- Renderer-component fileIDs in the entity-map.
- F-7 terrain heightmap extraction.
- F-10 profile editor UI.
- `targets/o3de/material_writer.py` extraction.
- Stage-1 worker migration into `platforms/unity/`.
- Full parser unification (see I.4 deferred note above).

These each warrant their own plan + working-doc pair when picked up.

---

## 2026-05-27 — Pass-2 plan written, Pass-1 cleanup landed

**Pass-1 (mechanical, done):**
- Deleted `legacy_unity_prefab_to_o3de.py` (66-line deprecation banner, no
  importers). Git history retains the original 590-line implementation.
- Trimmed `unity_scene_converter_gui.py` from 1422 → 1117 lines. Removed
  the dead `SceneConverterGUI` Tkinter class and the `main()` shim.
- Cleared root `__pycache__/`.
- Fixed `targets/o3de/__init__.py` docstring drift.
- Refreshed `mem:project/converter_working_status` to drop the obsolete
  "ignore legacy_unity_prefab_to_o3de.py" instruction.
- Tests green: 17/17 modules, 96 tests under `py -3.13`.

**Pass-2 plan landed:** `mem:pass2_consolidation/pass2_consolidation_plan`.

5 implementation stages I.1–I.5.

**User direction lifting back-compat:** "no projects are actively using
this system yet, we have no need to preserve dated systems." This
authorised dropping the `components/` shim outright and deleting (not
stubbing) the root-level workers.
