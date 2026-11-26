---
name: parity-harness-working-doc
description: Living log of the Unity-truth parity test bed (Unity bridge, converter CLI + trace, O3DE probe, compare, report). Plan - parity-harness-plan.
metadata:
  type: working_doc
---

# Parity harness - working doc

Plan: `.serena/memories/parity_harness/plan.md` (`mem:parity_harness/plan`). Environment facts: `mem:parity_harness/environment`.

IDs: P plan, D decision, Q open question, H suspect, I stage (increments I.na), T proof, F fix.
Report words: verified (the person ran it and confirmed), ran (executed with logs), built (compiles only).

Log, newest first.

## 2026-11-25 - Conclusion asked for; not concluded

### State
- `/pit-conclude` was run. The gate did not pass: no stage is ticked, because the person's own checks (T.3, T.8, T.15, T.16, T.19) are not done yet (their answer). No record was written, nothing was wiped.
- The person committed the work as `f572a9c`. Uncommitted since: `parity/report.py`, `tests/unit/test_parity_compare.py`, these memories.

### Decisions taken from the person
- Rendered pictures from the two engines are dropped from this plan (D.31).
- Q.2 is carried into the fix plans (D.32).

### Verification
- T.12 ran, failed, was fixed and ran again. `Carpet_round.FBX.assetinfo` was overwritten with text that is not JSON; cook, probe, compare. First run: the Asset Processor reported no failed job for it and the report said "fail: the entity shows no model". After F.9: the prefab is `uncooked`, "the model the prefab names was not produced: assets/officepack/meshes/Carpet_round-Carpet_round.fbx.azmodel". Convert, cook, probe, compare then gave the baseline back.
- Unit tests: 33 in `test_parity_compare.py` (two new, on the difference).

### Fixes
- F.9 A broken assetinfo was reported as a failing mesh, not as uncooked. Cause: the Asset Processor does not fail the job of an FBX whose assetinfo it cannot read; it falls back to default mesh groups, so the model the prefab names is simply absent. Fix: a model the entity does not show is checked against the product cache (D.33).
- F.10 A pass that became uncooked did not show in the difference. Fix: D.34.

### Behavioural notes
- The refined verdict moved the baseline's 11 "no mesh component" elements into "the converter emitted no model" (10, in 6 prefabs) and "the model the prefab names was not produced" (1, Bookshelf_A). The copy in `baseline_2026-11-25/` was refreshed with these labels; the measurements are the same.

## 2026-11-25 - I.5 sheets, I.6 cycle and baseline (ran)

### What landed
- `parity/views.py`: one sheet per prefab (front, top, left), Unity's geometry wide and pale, O3DE's thin on top, colliders in their own colours. 222 sheets.
- `parity/report.py`: scene placement parity (`compare_scene`), difference from the previous run, small shifts told from large ones.
- `platforms/unity/scene_converter.py`: a placed instance carries the file id of its `PrefabInstance` (`component_data["unity_prefab_instance_file_id"]`), for the trace only; nothing emitted changes.
- `converter_cli.py`: `--seed` also seeds the mesh group ids.
- Baseline kept in `<O3DE project>/user/Parity/baseline_2026-11-25/` (report.md, report.json, sheets).

### Verification
- T.16 ran in part: 222 sheets written and linked; Desk_metal's shows drawer C's mesh 1.26 m from its slot while its collider is in the slot; Door_Metal_Gray's shows the mesh a door's width beside its collider. The person's look is open. No rendered pictures.
- T.17 ran: three unattended cycles (218 s, 222 s, 199 s), exit 0 each; a repeat with nothing changed reports "no change".
- T.18 ran: `--set mesh_processor.overrides.1d79bf52826bdd6499d8c648714e3a06.default_position=[0.25, 0, 0]` (Dresser_B_drawer_A.FBX) gave regressions in Dresser_B and Dresser_B_drawer_A only; the next clean cycle reported 4 elements fixed, 0 regressions, 1 cluster closed.
- T.19 open: the person reads the baseline.
- Suite: 38 of 39 modules green; `unit/test_terrain_data.py` fails as it did before any change.

### Fixes
- F.6 All 217 scene instances were unmatched. Cause: the scene converter gives placed instances made-up ids (`prefab_instance_N`), so the trace had nothing to join on. Fix: the PrefabInstance's own file id is carried into the trace.
- F.7 The property scrub found no component. Cause: an entity id built from its number is not the Editor's own object. Fix: ids are taken from an entity search and matched by number.
- F.8 The difference counted two elements for four when objects shared a path. Fix: the object's index is part of the key.

### Behavioural notes
- A cycle with nothing changed cooks in about 50 s; the first cycle after the ids became stable cooked every mesh once more (80 s).
- The Editor opens the converted `Showcase` level although its prefab job fails in the Asset Processor.
- Output of a background cycle is buffered unless Python runs with `-u`.

### For the person
- T.3: compare three values of the truth dump with the Unity Inspector.
- T.8: start the GUI and run the asset processor stage once (the two stage bodies now live in `stage_runner.py`).
- T.15, T.16, T.19: read `baseline_2026-11-25/report.md`, look at a few sheets against both editors.
- Decide: the first cluster to fix. Evidence points at H.9 (auto-centre, 79 models) and H.1 (inverted rotation, D.17).
- Not done: rendered pictures from the two engines (I.5b, Q.7); T.12 as written.

## 2026-11-25 - I.3 O3DE bake, cook, probe and I.4 compare (ran)

### What landed
- `parity/o3de/ParityProbe/`: Editor-only gem, console command `parity_dump <folder>` (prefab identity, transforms, non-uniform scale, Transform 2 world when served, LOD 0 vertices of each model, geometry of each collider shape).
- `parity/level_bake.py` (baked level + recipe), `parity/o3de_run.py` (cook, Editor session, engine discovery), `parity/o3de/session.py` (runs in the Editor), `parity/parity.py` (steps `setup truth convert bake cook probe compare cycle`), `parity/configs/office.json`.
- `parity/records.py`, `parity/compare.py`, `parity/report.py`, `parity/views.py`, `parity/README.md`, `parity/requirements.txt`.
- `tests/unit/test_parity_compare.py`: 31 tests (math and baker).
- In the O3DE project: `project.json` gained the gem's path and name; `Levels/Bench_Parity_Office/`; `Assets/OfficePack/`; `user/Parity/`.

### Verification
- T.9 ran: configure 61 s, build of `ParityProbe.Editor` 30 s, 0 errors; the Editor starts with it and the command runs.
- T.10 ran: baker unit tests (recipe, changed recipe refused, level without a recipe never touched).
- T.11 ran: probe 42 s, exit 0, 1045 entities, 356 meshes (0 not loaded), 667 collider shapes, 254 models. Desk_metal's container reads its cell (228, -570, 0) and drawer_C its local (-0.014, 0.450, 0.808) = the prefab file's values.
- T.12 not run as written (no assetinfo was broken on purpose). The cook does report failed jobs: 3 elevator prefabs and both levels.
- T.13 ran: 31 unit tests.
- T.14 ran on real data: Desk_metal's six objects, four of them nested drawers, each match one entity; 6 objects in the pack do not match ("its nested instance is not in the trace").
- T.15 open: the person's spot check of three prefabs.

### Fixes
- F.1 Baked level failed its prefab job: "The name of the source template in the nested instance DOM does not match". Cause: the level named prefabs by project path while converted prefabs name each other by the lower-case asset hint path (H.6). Fix: the level uses the form the prefabs use (`level_bake.nested_source_folder`).
- F.2 Correction search called 100 imports "unexplained". Cause: both point sets were sampled, so equal sets looked apart. Fix: only the asking side is sampled; candidates are ranked on a sample and the best four measured against the whole sets.
- F.3 Every mesh failed at 1 mm. Cause: Unity's High mesh compression moves vertices by up to about 3 mm (H.7). Fix: verdict by placement fit (D.25).
- F.4 Each cycle cooked every mesh again. Cause: assetinfo group ids are random `uuid4`. Fix: the CLI's `--seed` seeds them too (D.28).
- F.5 `describe` crashed on the coverage section (a list where a dict was expected). Fixed.

### Behavioural notes
- First cook of the project: 4064 assets, about 25 minutes. A later cook with nothing changed: 45 s.
- The grid spacing is 114 m because `BG_Building` reaches 55.7 m; cells run to +-800 m. Float precision there is about 0.06 mm.
- A prefab instance's path in the Editor is `<level instance>/<level alias>/<nested alias>`; the container entity's alias is `ContainerEntity`.
- The converter's placement patches (replace on `Transform Data/Translate/n`, which the prefab's container does not have) do take effect in the Editor.
- `--only` on `compare` keeps the previous report from being differenced (the two cover different prefabs).

## 2026-11-25 - I.2 Converter CLI and trace (ran)

### What landed
- `conversion_trace.py`: `ConversionTrace`, coverage check (`uncovered_in_output`), FBX facts reader.
- `stage_runner.py`: `run_asset_processor`, `run_scene_converter`, `store_run`, `input_hash_for`.
- `converter_cli.py`: `run`, `describe` beside `truth`.
- Hooks (an optional `trace`): `integrated_asset_processor.py`, `targets/o3de/prefab_writer.py`, `targets/o3de/assetinfo_writer.py`, `platforms/unity/scene_converter.py`.
- `main_app.py`: the two stage bodies call `stage_runner`; `input_hash_for` re-exported.
- `tests/unit/test_conversion_trace.py` (11), `tests/unit/test_converter_cli.py` (10).

### Verification
- T.5 ran: both stages through the GUI's own run functions before the lift, then through the CLI, same seed: 916 files, 0 only on one side, 0 with different content (assetinfo group ids blanked).
- T.6 ran: unit test on a synthetic prefab; on the Office pack 222 prefabs, 1 scene, 233 assetinfo writes, 0 emitted values without a record.
- T.7 ran: `--set` on `describe` and `run` leaves the project file byte-identical.
- T.8 ran in part: suite 37 of 38 modules green (the one failing is `test_terrain_data.py`, as before any change). The person's GUI run is open.

### Behavioural notes
- A processor may rewrite the transform after it was built (the light's pitch flip); the trace records the entity after all processors ran and names the processor in `transform_modified_by`.
- Stage 1 on the pack: 32 s. Stage 2 on Showcase: 2 s.

## 2026-11-25 - I.1 Unity bridge: truth dump (ran)

### What landed
- `platforms/unity/bridge/`: `unity_bridge.py` (discovery, requirements, install, fingerprint, cache, Unity start), `Editor/U2OTruthDump.cs` + `U2OTruth.Editor.asmdef` (the Editor script), `README.md` (what the bridge needs).
- `converter_cli.py` with the `truth` command (`--check`, `--fresh`, `--only`, `--unity`, `--timeout`).
- `parity/configs/office.u2oproj.json`: the test bed's conversion project.
- `tests/unit/test_unity_bridge.py`: 20 tests, Unity replaced by a stand-in launcher.
- In the Unity project: `Assets/_U2OTruth/Editor/` (+ `.meta` files Unity made) and three lines in `.git/info/exclude`.

### Verification
- T.1 ran: `--check` 30 s exit 0; full dump 16 s exit 0. `git status --porcelain` of the Unity project identical before and after (68 entries, the person's own).
- T.2 ran: 222 prefabs and 232 models in the dump = 222 `.prefab` and 232 `.fbx` on disk. 1 scene, 1053 objects, 277 meshes, 123702 vertices, 0 matrix mismatches.
- T.3 ran: Desk_metal drawers as Unity reports them: A left (-0.602, 0.76, 0.448), A right (0.603, 0.76, 0.448), B (0.593 / -0.612, 0.586, 0.444), C (-0.014, 0.8081, 0.4502). The person's own three-value check against the Inspector is open.
- T.4 ran: `python tests/unit/test_unity_bridge.py` 20/20.
- Baseline before any change: 34 of 35 modules green; `unit/test_terrain_data.py` fails 2 tests on the untouched tree (splat layers 0, heightmap zero size). Not touched.

### Behavioural notes
- Unity Hub does not need to run: the Editor starts its own licensing client.
- D.8 fallback (throwaway project) was not needed: the full project opens headless in 16 to 30 s and compiles.
- All 232 FBX are Read/Write enabled, so vertices read directly. A mesh that is not readable gets a warning in `done.json` and no `.pos` file.
- What the dump already shows about import (H.2): `Desk_metal.FBX` root node at +2500 cm in the file is at (-25, -0.0013, 0) m in Unity with identity rotation: X is negated and the file's Z-up root is turned to Y-up. The child `Desk_metal_drawer_C` keeps its local values with only X negated. Mesh vertices are node-local: drawer A's mesh is centred on its pivot in X and Y.
- A nested object's identity chain reads `<outer guid>:<generated id> (inst <PrefabInstance fileID>) <- <inner guid>:<fileID>`; the last link is the fileID the converter keys by. For a scene object the first link's `prefabId` is the PrefabInstance's fileID in the scene file.
- `isInstanceRoot` is also true for roots of nested instances (322 in Showcase for 217 placed instances).
- `--only` does not filter scenes; a filtered dump still writes every marked scene.

### Open follow-ups
- H.4 (uniform scale key) found while reading the prefab writer; in the plan.

## 2026-11-25 - Plan written, nothing built

### What landed
- Read-only recon of the three legs (Unity, converter, O3DE); facts in `mem:parity_harness/environment`.
- The plan, with decisions D.1 to D.16 and open questions Q.1 to Q.8. No Q blocks I.1.
- No code. Nothing launched: Unity, the Editor and the Asset Processor were not started.

### Decisions taken from the person
- Unity bridge script may be added to the Unity project and Unity run headless on it (D.3).
- The O3DE test project is disposable (D.5).
- Tolerance 1 mm / 0.1 degree / 1 mm to start (D.4).
- The SDK was built from `Transform2-2026` (D.7).
- Non-uniform scale stays on the non-uniform component; Transform 2 only for negative scale (D.6).
- The truth dump belongs in the Converter if conversion needs it (D.1, Q.2).

### Verification
- H.1 ran as a numeric check only (1000 random rotations, pure Python): the converter's quaternion map is the inverse of the one its position map needs. Not looked at in the engine.

### Behavioural notes
- `numpy` and `scipy` are not installed in the Python 3.9 interpreter; the harness will need `numpy` (D.14).
- The O3DE project has no `Cache/`: the first cook also processes the engine's own assets and will be long.
- The Unity project is a Bitbucket repo with pending changes of the person's; the bridge must leave its status untouched.

### Open follow-ups
- Next pivot: I.1, opening with the headless start of Unity on the full project (D.8).
