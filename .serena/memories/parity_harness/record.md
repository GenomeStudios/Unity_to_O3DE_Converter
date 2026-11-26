---
name: parity-harness-record
description: Record of the Unity-truth parity harness as built - headless Unity truth dump (Unity bridge), converter command line and trace, O3DE probe gem, element-by-element comparison, clustered report and sheets.
metadata:
  type: project
---

# Parity harness

A test bed that measures what the converter makes against what Unity itself holds, element by element, and says what is wrong with each element that is not in place. It is for the developer and for co-developing LLM sessions, to find converter defects as clusters and to prove a fix by running a cycle. The harness lives in `parity/`. The parts it needs from the converter are converter features in their own right: `converter_cli.py`, `stage_runner.py`, `conversion_trace.py` and `platforms/unity/bridge/`.

## As built

### Entry points
```
python converter_cli.py describe <project.u2oproj.json> [--set stage.key=value] [--full]
python converter_cli.py run      <project.u2oproj.json> [--stage ...] [--only W] [--set k=v] [--trace DIR]
                                                        [--project-out FILE] [--seed N] [--log FILE] [--quiet]
python converter_cli.py truth    <project.u2oproj.json> --out DIR [--check] [--fresh] [--only W] [--unity EXE]
python parity/parity.py setup|truth|convert|bake|cook|probe|compare|cycle <config> [--only W] [--set k=v] [--fresh]
```
Exit codes everywhere: 0 done, 1 failed, 2 refused (the message names what is missing).

### Converter side
| File | Role |
|---|---|
| `converter_cli.py` | The converter without its window. Reads a conversion project file and never writes to it. `--set` changes a setting for one run; a project with no marked prefabs means every prefab under the stage's source; `--seed` fixes the random component ids and the mesh group ids. |
| `stage_runner.py` | `run_asset_processor`, `run_scene_converter`, `store_run`, `input_hash_for`. The GUI tabs in `main_app.py` and the command line both call these. Imports no widgets. |
| `conversion_trace.py` | `ConversionTrace`: for every emitted entity, instance and assetinfo write, the Unity values it came from, the emitted values and the rule or processor that made them. `uncovered_in_output` checks that nothing emitted lacks a record. `read_fbx_facts` reads a binary FBX's axes, unit scale, node transforms and geometry boxes. |
| Hooks | An optional `trace` on `IntegratedAssetProcessor`, `UnitySceneConverter` and `write_fbx_assetinfo`; `create_entity_recursive` records an entity after every component processor ran. Without a trace nothing changes. A placed scene instance carries its `PrefabInstance` file id in `component_data["unity_prefab_instance_file_id"]`. |

### Unity bridge (`platforms/unity/bridge/`)
- `unity_bridge.py`: finds the Unity project of a scope folder and the Editor of exactly its version (Hub folders, `--unity`, `U2O_UNITY_EDITOR`); refuses when the Editor is missing, the project is open or `Assets` is not writable; copies the script to `Assets/_U2OTruth/Editor/` and lists it in `.git/info/exclude`; starts `Unity -batchmode -nographics -executeMethod U2OTruth.TruthDump.Run -u2oRequest <request.json>`; caches the dump by a fingerprint of the scope's files, the script, the Editor version and the request.
- `Editor/U2OTruthDump.cs`: reads prefabs and models straight from the asset and scenes from an opened, unsaved scene. Writes `done.json`, `truth.json`, `prefabs/`, `models/`, `scenes/` (one hierarchy each), `meshes.json`, `meshes/<guid>_<fileId>.pos|.idx`. Values are Unity's own axes and metres.
- Each object carries an identity chain: itself, then what it was instanced from, down to the defining asset, with the file id of the `PrefabInstance` that brought it in.

### Harness (`parity/`)
| File | Role |
|---|---|
| `parity.py` | The steps and where runs go: `<O3DE project>/user/Parity/{truth,convert,cook,probe,report}`. |
| `configs/office.json`, `configs/office.u2oproj.json` | The test bed: project file, level name, seed, tolerances. |
| `level_bake.py` | The measurement level `Levels/Bench_Parity_<name>`: one instance of every converted prefab on a grid, written as JSON from the default level, with its recipe and hash in `parity_bake.json`. |
| `o3de_run.py`, `o3de/session.py` | Asset Processor batch run with the failed jobs listed by source asset; Editor session (`--autotest_mode --runpython`), watched and killed when it stops; closes only the Asset Processor it brought up. |
| `o3de/ParityProbe/` | Editor-only gem, registered in the O3DE project as an external gem. Console command `parity_dump <folder>`: prefab identity (template, instance path, alias), transforms, non-uniform scale, Transform 2 world when served, LOD 0 vertices of each model, geometry of each collider shape. |
| `records.py`, `compare.py` | Record readers; the math: frame mapping, nearest distances, placement fit, residual search over the 48 signed axis permutations with scale and shift. |
| `report.py` | Join (truth -> trace -> record), verdicts, clusters, mesh import table, scene placement, difference from the previous report. Writes `report.json` and `report.md`. |
| `views.py` | One sheet per prefab: front, top and left drawings of both measurements laid over each other. |

### What a comparison says
- Frames: O3DE's axes are the common frame; a Unity point `(x, y, z)` is `(x, z, y)` and a Unity transform `X` is `A X A`. A prefab is measured at zero position and identity rotation with its root's stored scale.
- Elements and verdicts: `transform`, `mesh`, `collider`, `materials`, each `pass`, `fail`, `uncooked`, `unmatched`, `unmeasured` or `lod_stripped`.
- A failing element carries a residual (the correction that would put it right) and a signature; equal signatures form a cluster.
- A mesh is measured three ways, kept apart: the entity's transform, the model in its own space against Unity's mesh in its own, and the two together in place.

### Needs
The Unity Editor of the project's own version; an O3DE project with the probe gem built (target `ParityProbe.Editor`); `numpy` and `Pillow` for the harness. Machine facts of the test bed: `mem:parity_harness/environment`.

## How to verify
- `QT_QPA_PLATFORM=offscreen python tests/run_all.py`: this feature's modules are `unit/test_unity_bridge.py`, `unit/test_conversion_trace.py`, `unit/test_converter_cli.py`, `unit/test_parity_compare.py`.
- `python converter_cli.py truth parity/configs/office.u2oproj.json --out <folder> --check`: Unity starts headless, compiles the script and counts the scope's prefabs and models; `git status` of the Unity project is unchanged.
- `python converter_cli.py run <project> --seed 1 --trace <folder>` ends with "0 emitted value(s) not covered"; the same seed twice writes the same files.
- `python parity/parity.py cycle parity/configs/office.json` twice: the second reports "no change".
- Injected regression: add `--set mesh_processor.overrides.<mesh guid>.default_position=[0.25, 0, 0]` to a cycle. The report names regressions in the prefabs that use that mesh and nowhere else; the next clean cycle names them fixed.
- Broken import file: overwrite one `.assetinfo` with text that is not JSON, then `cook`, `probe`, `compare`. That prefab's mesh is `uncooked`.
- GUI: run the Prefabs stage once; it goes through `stage_runner.py`.

## Decisions
- Unity is the truth, read from Unity itself by a headless run - a model of Unity's importer would be the thing under test. The run is a converter feature under the Unity platform plugin, and Unity may be a stage of conversion where it turns out to be needed.
- Nothing of Unity's is shipped: the Editor script is the converter's own source on the public Editor API. Dumps hold data derived from the user's assets, stay in run folders and are never committed; tests use synthetic fixtures.
- The dump reads assets directly, instances nothing and saves nothing, so a run leaves the Unity project's version control untouched.
- The command line takes the conversion project file the GUI opens, and never writes to it - one config for both, and a test run cannot disturb a project.
- GUI and command line share one set of stage functions - a stage does the same thing however it is started.
- The trace is taken after the component processors ran, attributing each added component by difference - processors stay untouched, and a processor that rewrites the transform is caught.
- Tolerance is 1 mm position, 0.1 degree rotation, 1 mm geometry, held in the config.
- A mesh is judged by the rigid motion fitted over all its vertex pairs, not vertex by vertex - Unity's mesh compression moves single vertices by millimetres; noise averages out, a real offset or turn does not. Box colliders stay exact, mesh colliders use the same fit, convex hulls are compared by their boxes with five times the tolerance.
- Elements are joined by identity keys (file ids and prefab aliases), never by position - the thing under test must not choose what it is compared with.
- The measurement level is baked from a recipe and checked against it; a level folder without a recipe file is never touched. It keeps prefab results independent of the scene converter.
- The level names prefabs the way the converted prefabs name each other - the engine wants one string per prefab.
- What Editor Python cannot read comes from a small C++ Editor gem kept in this repository and registered into the O3DE project.
- A model the entity does not show is told apart three ways: none was emitted, the named model was not produced (checked in the product cache), or it exists and is not shown.
- Between two runs, a pass that becomes failing, uncooked or unmatched is a regression, and the reverse is fixed.
- The sheets are drawn from the two records by one piece of code - a difference in the picture is a difference in the data, not of camera or lighting. Rendered pictures from the engines are not taken.
- Positive non-uniform scale stays on the non-uniform scale component; Transform 2 is for negative scale only. The probe reads Transform 2's exact world when an entity serves it.
- The harness may depend on `numpy`; the converter gains no dependency.
- The plan and the working doc of this feature are kept beside this record.

## Lessons
- Check `meshCompression` in a model's importer record before reading vertex-level numbers: with compression on, Unity's vertices are off the file's by millimetres and no per-vertex tolerance below that can pass.
- When sampling point sets for a nearest-distance test, sample only the side that asks. Sampling both makes equal sets look apart.
- The Asset Processor does not fail an FBX job when it cannot read the `.assetinfo`: it falls back to default mesh groups, and the model the prefab names is simply absent. Look for the product in the cache.
- A failed prefab job and what the Editor shows are separate facts: the Editor opens a level whose prefab job failed.
- The engine asserts that a nested prefab's `Source` string equals the path the template was first loaded under. Two spellings of one prefab (case, or hint path against project path) fail the job of whatever nests both.
- Random mesh group ids make the Asset Processor cook every mesh on every run. `--seed` on the command line fixes them; a GUI run still writes random ones.
- In Editor Python an entity id built from a number is not usable for component calls; take the ids from an entity search and match by number. Some property reads raise and are counted, not fatal.
- The scene converter gives placed instances made-up ids. Anything that must join them to Unity needs the `PrefabInstance` file id carried beside.
- A Unity object nested through an instance is found by the `PrefabInstance`'s file id; its own id in the outer asset is generated and appears in no YAML.
- The Editor splits `--runpythonargs` at spaces: the run folder must have none.
- A sheet shows only what is larger than about a pixel of its frame: a 4 mm offset on a 2.4 m prefab is invisible. The sheet does not mark which element fails; read the report line for small residuals.
- The grid's spacing follows the largest prefab. One 55 m prefab puts cells 800 m out, where single precision still resolves 0.06 mm; a much larger one would eat into the tolerance.
- The first Asset Processor run on a fresh project takes tens of minutes; start it before anything that waits on it.
- The repository's index holds LF while several working copies carry CRLF. Editing such a file shows it wholly changed; bring it to LF first.
- Run a background cycle with `python -u`, or its output arrives only at the end.

Plan: local plan, concluded (`mem:parity_harness/plan`; the first baseline's findings are in its Baseline section).
