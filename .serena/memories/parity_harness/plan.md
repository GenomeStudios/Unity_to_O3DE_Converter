---
name: parity-harness-plan
description: PIT plan for the Unity-truth parity test bed - headless Unity truth dump (Unity bridge), converter CLI + trace, O3DE probe, element-by-element comparison and a clustered report on the Office pack.
metadata:
  type: plan
---

Concluded. Record: `.serena/memories/parity_harness/record.md`.

Feature: `parity_harness`. Working doc: `.serena/memories/parity_harness/working_doc.md`. IDs: P plan, D decision, Q open question, H suspect (a finding the baseline must confirm or clear), I stage (increments I.na), T proof, F fix.

Environment facts (paths, versions, counts): `mem:parity_harness/environment`. Earlier work on the same problem: `mem:transform_truth/transform_truth_plan`, `mem:transform_truth/working_documentation`.

## P - Deliverable
One command that runs a full parity cycle on the Office pack and ends in a report the person can act on.
- Unity is the truth. Every prefab of `Assets/OfficeAndPoliceStation` (222 prefabs, 232 FBX) is measured in Unity itself, converted, cooked, measured again in O3DE, and compared element by element: child objects, render meshes, colliders, material slots.
- Each element gets a verdict at the agreed tolerance (D.4). Failures are grouped into clusters by what is wrong with them. Every failing element links to the converter's own account of how it produced the value (the trace) and to the raw facts of its FBX.
- Front, top and left drawings of every prefab, made from the two measurements laid over each other. (Was: pictures rendered by both engines, side by side with an overlay. Changed by D.31.)
- The placement of every instance in `Scenes/Showcase.unity` is compared the same way.

For: the person and Claude, to drive converter fix cycles and prove each fix.
The first full report is the baseline. It names the clusters and fixes none of them.

Out of scope:
- Converter fixes. Each cluster gets its own plan, proven with this harness.
- A GUI surface for the Unity bridge and the trace (follows Q.2).
- `Scenes/OfficePack_Example.unity`. The harness takes any scene by config; the baseline does not run it.
- Shading parity. Which material sits on which slot is compared; how it looks is for eyes.
- Lights, animation, terrain, LOD selection, other asset packs.
- Transform 2 emission (D.6).

## Design

### Flow
```
Unity project  --I.1 Unity bridge (headless Unity)-->  truth dump
Unity files    --I.2 converter CLI-->                  O3DE assets + trace
O3DE assets    --I.3 bake, cook, probe (Editor)-->     O3DE record
truth dump + trace + O3DE record  --I.4 compare-->     report  (+ I.5 sheets)
```

### Where the code lives (converter repo)
| Part | Path | Kind |
|---|---|---|
| Unity bridge | `platforms/unity/bridge/` (`unity_bridge.py`, `Editor/U2OTruthDump.cs`) | converter feature |
| Headless entry | `converter_cli.py` | converter feature |
| Stage run functions | a UI-free module shared by the GUI and the CLI (named at I.2) | converter feature |
| Trace | collected by the workers and the component processors, written by the CLI | converter feature |
| Harness | `parity/` (`parity.py` and its modules, `configs/office.json`, `requirements.txt`) | development tool |
| O3DE probe gem | `parity/o3de/ParityProbe/` | development tool, O3DE source rules apply |
| Editor session script | `parity/o3de/session.py` | development tool |

### What is written outside the repo
- Unity project: `Assets/_U2OTruth/Editor/U2OTruthDump.cs`, installed by the bridge. The folder and its `.meta` files are listed in `.git/info/exclude` of that repo.
- O3DE project: converter output in `Assets/OfficePack/`; levels `Levels/Bench_Parity_Office` (baked grid, D.11) and the converted `Showcase`; runs in `user/Parity/<time>_<mode>/`; the truth cache in `user/Parity/truth/<hash>/`.

### Records
The truth dump and the O3DE record share one schema. Values are metres in each engine's own axes: truth is never converted when it is written.
- Identity of an element: the prefab's guid plus the fileID chain of the object (through nested instances), and on the O3DE side the template path, the instance alias path and the entity alias. The trace holds both, so it is the join.
- Per object: name, parent, local position, rotation and scale, and its 3x4 matrix composed from the stored local values, roots included. Compare derives the prefab frame from it.
- Per render mesh: the mesh reference, the material on each slot, and the vertex positions (one binary side file per mesh asset).
- Per collider: type, raw parameters, trigger flag, and its geometry.
- Per FBX, as three parties see it: the raw file (converter reader), Unity's import (truth dump), O3DE's cook (probe).
- Per scene: every instance root with its source prefab and world transform.

### Frames
- Canonical frame: O3DE axes. A Unity point maps by `A: (x, y, z) -> (x, z, y)`. A Unity transform `X` maps to `A X A`. Only compare applies `A`.
- Prefab frame: the prefab placed at zero position with identity rotation, root scale as stored (D.9).

### Compare
- Geometry is compared as point sets in the prefab frame. A mesh's distance is the largest distance from any vertex on one side to the nearest vertex on the other, taken both ways. This one number catches offset, rotation, mirror and scale.
- Colliders: box, sphere and capsule against the analytic Unity shape; triangle meshes as point sets; convex hulls per Q.8.
- Transforms: position, rotation angle and scale of `A X A` against the O3DE matrix.
- Residual: for a failing element, the correction that brings the O3DE geometry onto truth, searched over the 48 signed axis permutations plus a translation. It reads "rotate Z 180", "mirror X", "shift by (...)" or "none found".
- Signature: element kind + residual class + FBX facts (up axis, single or multi mesh, root or sub node, dedicated collider FBX). A cluster is a set of elements with one signature.
- Explain: the residual translation is tested against the quantities in the trace (node translation, geometry box centre, collider centre, with signs), so a cluster can read "equals minus the root node translation".

### Suspects the baseline must confirm or clear
- H.1 Rotation map. `targets/o3de/prefab_writer.py::convert_to_o3de_coordinates` maps positions `(x, z, y)` and quaternions `(qx, qz, qy, qw)`. For that position map the matching quaternion is `(-qx, -qz, -qy, qw)`; the emitted one is its inverse. Checked numerically on 2026-11-25 over 1000 random rotations: a Unity yaw of +90 comes out facing -X where it should face +X. It cannot show at 0 or 180 degrees. `platforms/unity/components/light.py` adds a 180 degree pitch flip to directional lights, which fits a local patch over the same thing. Not confirmed in the engine yet.
- H.2 Handedness. Unity negates X when it imports an FBX and O3DE does not. `mem:transform_truth/working_documentation` recorded it as `bake-vs-world-sign-flip` on every door and drawer. If it holds for all 232 FBX, the coordinate rule of a node has a closed form, `(A N) * inverse(node world)` with `N = diag(-1, 1, 1)`, and the centroid formulas of transform_truth can be retired.
- H.3 Root scale. The converter discards the whole stored transform of a prefab root. Unity always overrides a root's position and rotation in a scene, but applies the stored scale unless the scene overrides it.

- H.4 Uniform scale key. The prefab writer emits a uniform scale as `"Scale": <number>` inside `Transform Data`, and nested-instance patches target `/Transform Data/Scale`. The engine's `EditorTransform` reflects `Scale` as the legacy vector and `UniformScale` as the number (`Transform2-2026:.../TransformComponent.cpp`). A uniform scale other than 1 may be dropped on load. Seen while reading the writer for I.2; not checked in the engine.
- H.5 Assetinfo written once per prefab. `process_prefab` rewrites an FBX's `.assetinfo` for every prefab that uses the file, with mesh groups named after that prefab's object names. The last prefab wins, so an earlier prefab can point at a mesh group that no longer exists. The first trace shows three such files in the Office pack: `Bookshelf.FBX` (2 writes), `StairsMod_Ground_COL.FBX` (4), `StairsMod_Top_COL.FBX` (2).
- H.6 Prefab source names. Stage 1 names a nested prefab `assets/<pack>/prefabs/X.prefab` (lower case, from the asset hint root) and Stage 2 names the same prefab `Assets/<Pack>/Prefabs/X.prefab` in a level. The engine wants one prefab named by one string everywhere (`PrefabSystemComponent::ConnectTemplates`), so the converted `Showcase` level fails its prefab job in the Asset Processor. Confirmed: the baked level failed the same way until it used Stage 1's form.
- H.7 Unity mesh compression. Every FBX of the pack is imported with `meshCompression: High`; Unity's vertices are off the file's by up to about 3 mm. Not a converter fault, and it bounds what any per-vertex test can ask (D.25).
- H.8 Non-uniform scale lost. Objects with a non-uniform Unity scale come out at scale 1 in the Editor (StairsMod ramps, Storage_metalbox folders), although the converter emits an `EditorNonUniformScaleComponent`. Seen in the baseline; cause not looked into.
- H.9 Auto-centre translation. For most single-mesh FBX the shift a model needs is exactly the negative of the auto-centre translation the converter wrote into its coordinate rule: there the rule itself is the error.
- H.10 Three elevator prefabs carry a material component on an entity with no mesh; their prefab job fails ("MaterialComponent is missing another required service"), and with them any level that places them.

## D - Decisions
- D.1 The truth dump is built as a converter feature, the Unity bridge under `platforms/unity/bridge/`, and not as test scaffolding - the person wants it in the Converter if conversion turns out to need it (Q.2). The bridge states and checks what it needs: a Unity Editor of the project's own version, installed and licensed; the project not open in Unity; write access to its `Assets/`.
- D.2 Nothing of Unity's is distributed. The bridge is our own Editor script in source form, using the public Editor API; whoever runs it supplies Unity and the project. Truth dumps hold data derived from a bought pack, so they stay in run folders and are never committed; tests use synthetic fixtures.
- D.3 The bridge script goes into `D:\OffLocalDev\dellagolayover` at `Assets/_U2OTruth/Editor/`, kept out of that repo's status through `.git/info/exclude`. Nothing is committed there. The project is closed in Unity during a run (the person, 2026-11-25).
- D.4 Tolerance within a prefab: 1 mm position, 0.1 degree rotation, 1 mm geometry distance. Held in the config. It is the starting standard: the person expects to tune it once the library stops being "a mess" (2026-11-25).
- D.5 `D:\OffLocalDev\xxxxxDelete\ConverterTest` is dedicated to this work. The harness deletes and regenerates converter output, levels and run folders there without asking (the person, 2026-11-25). It deletes only what it made: its output folder, its baked level (which carries a recipe file) and its run folders.
- D.6 Transform 2 is used only where a scale is negative. Positive non-uniform scale keeps going out as `EditorNonUniformScaleComponent`, which the engine can convert later (the person, 2026-11-25). The pack has no negative scale, so this plan emits no Transform 2. The probe reads the plain transform and the non-uniform scale, and marks an entity that serves Transform 2 as unmeasured.
- D.7 Engine: GS_Play_Engine 2.9.0 SDK, built from `o3de_sourcedev` branch `Transform2-2026` (the person, 2026-11-25). Engine source questions are answered from that branch with `git show`, never by checking it out.
- D.8 Risk first. I.1 opens by proving that Unity 2021.3.14f1 starts headless on the full project and compiles the bridge. If it does not (a compile error in other code, a licence refusal, an unusable start time), the bridge runs on a throwaway project that holds only the pack, GUIDs kept through the `.meta` files.
- D.9 Prefab frame = zero position, identity rotation, root scale as stored. Unity serialises position and rotation of every instance root as overrides, so a stored root rotation never reaches a scene; a stored root scale does. The root's stored transform is reported as data beside the verdicts.
- D.10 Elements are joined by identity keys, never by position or by nearest geometry: the thing under test must not decide what it is compared with.
- D.11 The O3DE measurement level is baked by the harness, not converted: `Levels/Bench_Parity_Office`, one instance of every converted prefab on a grid, written as level JSON from the project's default level. Its recipe (prefab list, grid, base level hash, writer version) sits beside it with a hash; a probe refuses a level that no longer matches, and never touches a level without a recipe file. `--fresh` rebuilds it to check the baked one. This follows the person's baked-level rule and keeps Stage 1 results independent of the scene converter.
- D.12 What Editor Python cannot read comes from a small C++ gem, `ParityProbe`: model vertices, collision geometry, and the prefab alias of each entity. It lives in the converter repo and is registered into the O3DE project by `parity.py setup`. Everything else (orchestration, property scrub, pictures) stays in the session script.
- D.13 The harness starts the Editor itself, the way `gs_play/Tools/PerformerSmoke` does (`--autotest_mode --runpython`, run folder without spaces, a hung Editor is killed, logs kept), so one command works for the person as well. Configure and build of the gem go through the O3DE MCP.
- D.14 The harness may depend on `numpy` (`parity/requirements.txt`). The converter itself gains no dependency.
- D.15 Pictures are orthographic and share one camera spec per prefab, derived from the truth bounds. Colliders and outlines are drawn onto the sheet from the two records, not by either engine's debug drawing, so both sides are drawn by the same code.
- D.16 New code for this feature uses `plan.md` and `working_doc.md` (the global layout); the legacy pairs of older features stay as they are. Decisions here are appended, and a superseded one keeps its text with a note (project rule).
- D.17 H.1 is to be corrected (the person, 2026-11-25: "we need to correct that for sure"). The fix is not part of this plan's stages: it is made after the baseline exists, so the harness shows it before and after.
- D.18 The person left the machine free on 2026-11-25 and asked for the plan to be worked through I.6 without stopping at stage boundaries. Proofs that need the person are logged as ran, not verified, and listed for them at the end.
- D.19 `converter_cli.py` takes a conversion project file (`.u2oproj.json`) as its config, the same file the GUI opens. The test bed's is `parity/configs/office.u2oproj.json`; runs work on a copy so it stays as written. Output folders are given on the command line.
- D.20 The truth dump reads prefabs and models straight from the asset (`AssetDatabase.LoadAssetAtPath`); nothing is instanced into a scene. Scenes are opened and left unsaved. Unity runs with `-nographics` until pictures need a device (I.5).
- D.21 Q.1 resolved: the two stage bodies moved out of `main_app.py` into `stage_runner.py` (`run_asset_processor`, `run_scene_converter`, `store_run`, `input_hash_for`). The tabs keep only their dialogs and the storing of a run. The module imports no widgets; `main_app` re-exports `input_hash_for`.
- D.22 The trace is collected through an optional `trace` argument on the workers (`IntegratedAssetProcessor`, `UnitySceneConverter`, `write_fbx_assetinfo`). Component processors are not touched: an entity's record is taken after they ran, and each added component is attributed to the processor that added it.
- D.23 `converter_cli.py run` with no prefab marks in the project takes every prefab under the stage's source. `--seed` fixes the random component ids so two runs can be compared file by file; the harness always passes it.
- D.24 The index of this repo holds LF line endings while several working copies carry CRLF from an older checkout (`core.autocrlf` is false now). An edit to such a file shows the whole file as changed. Files this plan edits are brought back to LF first: `integrated_asset_processor.py`, `main_app.py`.
- D.25 Meshes are judged by a placement fit, not vertex by vertex (H.7). The rigid motion between Unity's vertices and the model's is fitted over all vertex pairs; the tolerances of D.4 apply to the fitted offset and rotation. Vertex noise averages out, a real offset or turn does not. Box colliders stay exact; mesh colliders use the same fit; convex hulls are compared by their boxes with five times the tolerance (resolves Q.8).
- D.26 Three measurements are kept apart for a mesh: the entity's transform, the model in its own space against Unity's mesh in its own (the import rule), and the two together in place. A converter that corrects one with the other shows in the first two and passes the third.
- D.27 The baked level names prefabs the way the converted prefabs name each other (H.6), so that it cooks.
- D.28 `converter_cli.py run --seed` also fixes the random mesh group ids of the assetinfo files (a seeded `uuid4` in the CLI process only). Without it every cycle changed every assetinfo and the Asset Processor cooked every mesh again.
- D.29 Resolved Q.3, Q.4, Q.5, Q.6: the probe gem links `Gem::Atom_RPI.Public` and `Gem::AtomLyIntegration_CommonFeatures.Public` against the SDK; editor colliders are read in edit mode through `SimulatedBodyComponentRequestsBus` (geometry in the shape's own space, composed with its local pose and the body's transform); a level places an instance with the converter's own patch paths; a Unity object joins the trace by `identity[k].fileId` for an own object and by `identity[k].instanceFileId` (the PrefabInstance's fileID) for a nested one.
- D.30 The sheets of views are drawn from the two records by one piece of code (`parity/views.py`). Rendered pictures from the two engines are not taken in this plan's run: see Q.7.
- D.31 Rendered pictures from the two engines are dropped from this plan (the person, 2026-11-25). The sheets drawn from the measured geometry are the deliverable; rendered pictures become a follow-up only if wanted. Supersedes the third bullet of P as first written, increment I.5b and Q.7.
- D.32 Q.2 is carried into the fix plans (the person, 2026-11-25): whether Unity is a required stage of conversion is answered while the auto-centre and rotation clusters are fixed, where the evidence is produced anyway. The baseline no longer has to answer it.
- D.33 A model that the entity does not show is told apart three ways: the converter named none (fail), the model it named was not produced (uncooked, checked against the product cache), the model exists and is not shown (fail). An FBX whose own job failed is uncooked whatever the Editor still shows.
- D.34 In the difference between two runs, a pass that becomes failing, uncooked or unmatched is a regression, and the reverse is fixed.
- D.35 Unity may be part of the conversion process where it is necessary (the person, 2026-11-25, after reading the baseline). This settles Q.2 as a matter of policy; where it is in fact needed is shown by the fix plans (D.32).
- D.36 T.15 counts as done on two prefabs checked in depth (Desk_metal, Cabinet_A) and the placement of three in the level (the person, 2026-11-25).

## Q - Open questions
- Q.1 (resolved, D.21) How much of the stage run logic can leave `main_app.py` without a change in behaviour, and what is the shared module called - blocks I.2.
- Q.2 (settled as policy by D.35; the evidence comes with the fix plans, D.32) Is Unity in the loop a required stage of conversion, or only the verifier? It is required if any of the 232 FBX cannot be explained from its file alone (H.2). Answered by the baseline; blocks the conclusion and the follow-up plan for a GUI surface.
- Q.3 (resolved, D.29) Can an external gem link `Gem::Atom_RPI.Public` and `AZ::AzToolsFramework` against the installed SDK, and which calls give model positions and the prefab alias of an entity - blocks I.3.
- Q.4 (resolved, D.29) Are the shapes of `EditorColliderComponent`, `EditorShapeColliderComponent` and `EditorMeshColliderComponent` in the Editor's physics scene in edit mode, readable through `Physics::Shape::GetGeometry`, and in which frame? If not, colliders are read in game mode - blocks I.3.
- Q.5 (resolved, D.29) The patch paths a level needs to place a nested instance (container transform alias, parent link) - blocks I.3; read from the scene converter's level writer.
- Q.6 (resolved, D.29) Which Unity API values equal the converter's fileID chain for objects inside nested instances and prefab variants - blocks I.4. I.1 dumps the whole correspondence chain so that no second dump is needed.
- Q.7 (dropped with the rendered pictures, D.31) Orthographic capture: `Camera.Render` under URP in batch mode on the Unity side; a camera entity with the Orthographic option and clip planes in the Editor viewport on the O3DE side. Fallback: matched perspective cameras - blocks I.5.
- Q.8 (resolved, D.25) Convex colliders: PhysX hull cooking moves vertices, so which measure and tolerance are fair - blocks the collider verdicts of I.4.

## I - Stages
- [x] I.1 Unity bridge: truth dump (verified) - Done when:
  - `python converter_cli.py truth <config>` finds the Unity Editor of the project's version, installs the bridge script, runs Unity headless, exits 0 and keeps the Editor log.
  - It refuses with a message that names what is missing: the Editor version, a project open in Unity, no write access.
  - The dump covers all 222 prefabs, all 232 FBX and the scenes of the config, in the schema of Design / Records.
  - A second run on unchanged files is answered from the cache unless `--fresh` is given.
  - `git status` in the Unity project shows nothing new.
  - [x] I.1a Headless start: Unity 2021.3.14f1 opens the full project in batch mode, compiles the bridge script and counts the assets (`--check`). Ran: 30 s, exit 0, Unity Hub closed.
  - [x] I.1b Prefab, model, scene and mesh dump with identity chains. Ran: 222 prefabs, 232 models, 1 scene, 1053 objects, 277 meshes, 123702 vertices, 0 matrix mismatches, 16 s.
  - [x] I.1c Cache, refusals, unit tests, README. Ran: second run cached; 20 unit tests pass.
- [x] I.2 Converter CLI and trace (verified) - Done when:
  - `python converter_cli.py run <config> [--stage ...] [--only <glob>] [--set key=value]` runs the same stage functions as the GUI with no display, and its exit code says whether errors occurred.
  - The GUI and the CLI call one set of stage run functions, in a module that imports no widgets.
  - `--set` alters one run and writes nothing back to the project file.
  - Every position, rotation and scale in an emitted prefab, and every coordinate rule in an emitted assetinfo, has a trace record with its inputs and the rule that produced it; each FBX has its facts (up axis, unit scale, every node's local and geometric transform, geometry box).
  - `python converter_cli.py describe <config>` prints the effective settings of every stage, the registered component processors with what they handle and emit, and the coverage of the last run.
  - [x] I.2a Trace collector and hooks (`conversion_trace.py`), FBX facts reader. Ran: 0 emitted values uncovered on the full pack.
  - [x] I.2b `stage_runner.py`; GUI tabs call it. Ran: CLI output equals the GUI's own pre-lift output, 916 files, 0 differences.
  - [x] I.2c CLI `run` (`--stage`, `--only`, `--set`, `--trace`, `--project-out`, `--seed`, `--log`, `--quiet`) and `describe`. Ran: 21 unit tests pass.
- [x] I.3 O3DE bake, cook and probe (verified) - Done when:
  - `python parity/parity.py setup <config>` registers the probe gem in the O3DE project and it builds.
  - `bake` writes `Levels/Bench_Parity_Office` with its recipe; `cook` runs the Asset Processor in batch and lists every failed job by source asset.
  - `probe` starts the Editor unattended on the baked level, writes the O3DE record in the schema of Design / Records plus a scrub of every property of every component, exits 0, and closes the Asset Processor it started.
  - A prefab whose assets did not cook is recorded as `uncooked`, not as missing.
  - [x] I.3a Probe gem `ParityProbe` (console command `parity_dump`). Built first try; ran in the Editor.
  - [x] I.3b Baked level with recipe (`level_bake.py`), cook with failed-job list, Editor session and launcher (`o3de_run.py`, `o3de/session.py`). Ran: probe 42 s, 1045 entities, 356 meshes all loaded, 667 collider shapes, exit 0.
  - [x] I.3c Component property scrub in the Editor. Ran: `properties.json` for 693 entities; some property reads raise in the Editor's Python and are counted as failures.
- [x] I.4 Compare and report (verified) - Done when:
  - `compare` joins truth, trace and O3DE record by identity keys and lists what is unmatched on either side.
  - Every element has a status: pass, fail, uncooked, unmatched or unmeasured, at the tolerances of the config.
  - Every failing element has its residual, its signature and a link to its trace record.
  - `report.json` and `report.md` list the clusters by size, each with its prefabs, and one line per prefab.
  - [x] I.4a Math (`compare.py`): frames, distances, placement fit, residual search over the 48 axis permutations. 31 unit tests.
  - [x] I.4b Join, verdicts, clusters, import table, report (`report.py`). Ran on the whole pack in 35 s.
  - [x] I.4c Shift explained against the trace ("= minus the rule's auto_center translation").
- [x] I.5 Views (verified, as changed by D.31) - Done when:
  - The truth dump and the probe each write front, top and left pictures per prefab from the shared camera spec.
  - `compare` builds one sheet per prefab: three views by three columns (Unity, O3DE, overlay of both records with colliders).
  - The report links every sheet.
  - [x] I.5a Sheets drawn from the records, one per prefab, linked from the report (D.30).
  - I.5b Rendered pictures from Unity and from the Editor: dropped (D.31).
- [x] I.6 Cycle and baseline (verified, as changed by D.32) - Done when:
  - `python parity/parity.py cycle <config> [--only <glob>]` runs truth (cached), convert, bake check, cook, probe and compare unattended, and prints the result with its difference from the previous run: clusters closed, clusters opened, regressions.
  - The converted `Showcase` level is probed and every instance placement is compared with the scene truth.
  - The baseline report on the whole pack exists, with a verdict on H.1 to H.3 and the answer to Q.2.
  - `parity/README.md` says how to run a cycle; the bridge's README says what it needs.
  - [x] I.6a `cycle` and the difference from the previous run. Ran three cycles unattended: 218 s, 222 s, 199 s. A repeat reports "no change"; an injected mesh override reports regressions in the two prefabs that use that mesh and nowhere else; removing it reports them fixed.
  - [x] I.6b Scene placement: the converted `Showcase` level is probed and each instance compared. Ran: 212 of 217 in place.
  - [x] I.6c Baseline report on the whole pack, kept in `user/Parity/baseline_2026-11-25/`. Verdicts below.
  - [x] I.6d `parity/README.md`, `platforms/unity/bridge/README.md`.

## Baseline (2026-11-25, ran)
Whole pack, tolerance 1 mm / 0.1 degree / 1 mm. 13 prefabs pass, 203 fail, 5 unmatched, 1 unmeasured.

| Element | pass | fail | other |
|---|---|---|---|
| transform | 355 | 32 | |
| mesh | 28 | 338 | 1 uncooked |
| collider | 613 | 69 | 1 unmeasured |
| materials | 360 | 7 | |
| object | | | 6 unmatched |

82 clusters: 59 of meshes, 11 of colliders, 9 of transforms, 2 of materials, 1 of objects.

Mesh import, 255 model and mesh pairs (the model in its own space against Unity's mesh in its own):
- 79 need a shift that is exactly minus the auto-centre translation the converter wrote (H.9): the rule is the error.
- 53 need another shift; 7 need less than 1 cm (the rule is close: the drawers it was calibrated on); 3 have no translation and need one.
- 17 need nothing.
- 18 need `rot X -90` and a shift (17 of them Y-up files); 35 need `rot Z 180`, half of them with a shift.
- 16 need a mirror; 8 are not explained by an axis-aligned correction.

Verdicts on the suspects:
- H.1 confirmed. 21 of the 32 failing transforms are an inverted rotation, 7 more are children of one. In `Showcase`, 4 of the 5 misplaced instances are inverted rotations (a 180 degree error on three floors and a door trim).
- H.2 not as feared. 156 of 255 models match Unity's mesh without a mirror or a turn: Unity's X negation and the axis swap together are a plain rotation, which O3DE's importer already makes. A mirror is needed for 16.
- H.3 and H.4 not exercised: no prefab root of the pack stores a scale or a rotation, and no object with a uniform scale other than 1 fails.
- H.5 confirmed on one case: three FBX get more than one assetinfo write, and Bookshelf_A names a model (`Bookshelf-Bookshelf_...`) that was not produced. Separately, 6 prefabs (10 renderers: the three StairsMod and the three elevator prefabs) have a renderer for which the converter emitted no model at all.
- H.6 confirmed: the converted `Showcase` level fails its prefab job; the baked level did until it named prefabs as Stage 1 does.
- H.7 fact: all 232 FBX use High mesh compression in Unity.
- H.8 seen: 7 objects with a non-uniform scale come out at scale 1.
- H.9 confirmed for 79 models.
- H.10 seen: the three elevator prefabs fail their prefab job.
- Not converted: 5 door prefabs have no instance in the level and 6 objects are not in the trace (nested instances the converter did not record); `FPS Controller` has nothing measurable.

Q.2 is not closed and is carried into the fix plans (D.32). For 61 per cent of the models no mirror and no turn is needed, so the file alone may be enough there; whether the remaining shifts and turns follow from the FBX facts has not been tested. The truth dump is what would show it: each model's residual is in `report.json` beside the file's node transforms in `fbx_facts.json`.

## T - Proofs
| ID | Proof | Stage | Result |
|---|---|---|---|
| T.1 | Headless Unity run exits 0 and writes the dump; `git status` of the Unity project is unchanged (ran, log kept) | I.1 | ran |
| T.2 | The dump's prefab and FBX counts equal the file counts on disk (222, 232) | I.1 | ran |
| T.3 | Desk_metal: the four drawer instances sit where transform_truth recorded them (Drawer A left at Unity local -0.602, 0.76, 0.448). The person compares three values of their choice with the Unity Inspector | I.1 | verified: the person read drawer C's position, its box centre and the left drawer A's position in the Inspector; each equals the dump to nine digits |
| T.4 | Unit tests: Editor discovery by project version, cache hash, each refusal message. Suite green | I.1 | ran (20 tests) |
| T.5 | `converter_cli.py run` on the Office config with no display exits 0, and its output equals the output captured from the GUI's own run function before the lift (file list and content hash) | I.2 | ran (916 files, 0 differences) |
| T.6 | Trace completeness: a unit test on a synthetic prefab, and a check over the whole Office output that no emitted transform or coordinate rule lacks a record | I.2 | ran (0 uncovered on the pack) |
| T.7 | Unit test: `--set` changes the run and leaves the project file byte-identical | I.2 | ran |
| T.8 | Suite green. The person starts the GUI and runs the asset processor stage once | I.2 | verified: the person ran the Prefabs stage of `Police Office 2.u2oproj.json` from the GUI |
| T.9 | The probe gem builds through the O3DE MCP and the Editor starts with it | I.3 | ran |
| T.10 | Unit tests on the baker: level and recipe written; an altered recipe is refused; a level without a recipe is not touched | I.3 | ran |
| T.11 | Probe run exits 0 with every instance of the level in the record; one entity's position read back equals its prefab JSON; one mesh's vertex count and box agree with a hand check | I.3 | verified: the person read the wrappers of Desk_metal, Door_Metal_Gray and Carpet_round at their recipe cells in the Editor |
| T.12 | A deliberately broken assetinfo shows its prefabs as `uncooked` | I.3 | ran (failed first; holds after D.33) |
| T.13 | Unit tests on the compare math: equal sets pass; a 2 mm shift fails with that shift as residual; yaw 180, mirror X and an inverted rotation are each named | I.4 | ran (33 tests) |
| T.14 | Join: Desk_metal's nested drawers, and one prefab with repeated child names, match one to one with none unmatched | I.4 | ran |
| T.15 | The person spot-checks three prefabs of the report against both editors | I.4 | verified, as D.36: Desk_metal and Cabinet_A in depth, three placements in the level |
| T.16 | A sheet exists for every prefab; the person confirms that Desk_metal's and Cabinet_A's show what the two editors show | I.5 | verified: the person saw Desk_metal's sheet show drawer C forward of and above its slot, and Cabinet_A's look right (its one fail is a 4.3 mm frame offset, under a pixel of the sheet) |
| T.17 | One `cycle` command runs start to finish unattended; a second cycle reports no change | I.6 | ran |
| T.18 | A mesh override injected with `--set` appears as a regression for that mesh's prefabs and nowhere else | I.6 | ran |
| T.19 | The person reads the baseline: clusters, counts, the H verdicts, the answer to Q.2 | I.6 | verified: the person read the baseline report |

## Project
- Rules read: `AGENTICS_GUIDELINES.md` (root), `tests/README.md`, the memories named at the top, the global CLAUDE.md. No CLAUDE.md or AGENTS.md in the repo.
  - Plain Python `assert` tests on `tests/harness.py`, no pytest. Section banner comments. No TODO comments: follow-ups go to the working doc. Long docstrings on public surfaces.
  - The vocabulary of guidelines section 8 is kept (stage, scope, mark, override, patch, state index). This plan adds: truth dump, Unity bridge, trace, probe, O3DE record.
  - Platform code stays behind the `SourcePlatform` contract: the bridge lives under `platforms/unity/` and does not reach into the worker.
  - Simplest legible code, ordered, with section titles. The installed interpreter is Python 3.9.13, so code runs on 3.9.
  - The probe gem is O3DE source: ASCII only, `m_` on members, reflection rules, `o3de-reflection-review` on any reflection.
  - Never commit or push in either repo; never write to GitHub. Claude proposes commits.
- Proof commands: `QT_QPA_PLATFORM=offscreen python tests/run_all.py`; one module with `python tests/unit/test_<name>.py`; GUI smoke with `python main_app.py`; gem configure and build through the O3DE MCP (`o3de_configure`, `o3de_build`).
- Record: `.serena/memories/parity_harness/record.md`
- Wipe: nothing. The plan and the working doc are kept after the conclusion (the person, 2026-11-25).
