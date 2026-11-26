---
name: parity-fixes-plan
description: PIT plan for the converter fixes the parity baseline called for on the Office pack - rotation map, prefab source names, mesh import rule, missing models, non-uniform scale, colliders, scene lighting - each proven by a parity cycle.
metadata:
  type: plan
---

Feature: `parity_fixes`. Working doc: `.serena/memories/parity_fixes/working_doc.md`. IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix.

Starts from the baseline of `mem:parity_harness/plan` (its Baseline section and suspects H.1 to H.10). How the harness works: `mem:parity_harness/record`, `parity/README.md`. Machine facts: `mem:parity_harness/environment`.

## P - Deliverable
The Office pack converts so that the parity report is clean at the agreed tolerance (1 mm, 0.1 degree, 1 mm), or says for each element that is not why it cannot be:
- every cluster of the baseline is closed, or carried with a reason the person has accepted;
- the converted `Showcase` level cooks, and all of its instances and its light stand as in Unity;
- each fix is in the converter itself and holds for any pack, not for the Office pack by name.

For: the person. The report of the last cycle, beside the baseline `user/Parity/baseline_2026-11-25/`, is the evidence.

Out of scope: other asset packs (a second pack is the test of generality, and its own plan); `OfficePack_Example.unity`; shading; animation; terrain; rendered pictures; a GUI surface for the bridge and the trace.

## Design
- One loop for every stage: change the converter, run `python parity/parity.py cycle parity/configs/office.json`, read the difference from the previous run. The target cluster must close and nothing may regress.
- Baseline numbers to beat (whole pack): prefabs 13 pass / 203 fail / 5 unmatched / 1 unmeasured; transforms 355 / 32; meshes 28 pass / 338 fail / 1 uncooked; colliders 613 / 69; materials 360 / 7; Showcase 212 of 217 instances; 5 failed prefab jobs.
- Frame rule the fixes follow: a Unity point `(x, y, z)` is the O3DE point `(x, z, y)`. That swap `A` mirrors, so a Unity rotation `q = (x, y, z, w)` is the O3DE rotation `(-x, -z, -y, w)` and a Unity matrix `X` is `A X A`.
- A mesh is right when the model in its own space equals `A` times Unity's mesh in its own space; the entity's transform then places it. The mesh import rule (the assetinfo's coordinate rule) is what has to make that true.

## D - Decisions
- D.1 The clusters are worked as stages of one plan, not as a plan each - they share one proof (a cycle), one baseline, and they interact: the rotation map changes what the mesh rule and the collider offsets must do. (The concluded harness plan said "a plan each"; this replaces that.)
- D.2 A stage's proof is a full cycle with its difference, plus unit tests for the code it changes. A stage does not pass with a regression it cannot explain.
- D.3 The harness is extended inside a stage when the fix needs a measurement it does not make yet (I.1: objects of a scene that are not prefab instances, so the light is measured).
- D.4 The person left the machine free on 2026-11-25 and asked for the plans to be implemented. Stages are worked through without stopping at their boundaries; proofs that need the person are logged as ran and listed for them.
- D.5 Unity may be part of conversion where necessary (the person; `mem:parity_harness/plan` D.35). A fix prefers what the files alone give and uses the truth dump only where they do not.
- D.6 The plan and the working doc are kept after the conclusion (the person's standing answer for this repository).
- D.7 Checked before I.1, on the existing records: the converted `Showcase` directional light shines downward (not from below), and is 50.6 degrees off Unity's direction. The 180 degree pitch patch in `light.py` hides the inverted rotation; both go in I.1.
- D.8 Scene lighting is the last stage, not a plan of its own: the Gradient GI component is in the engine (`AtomLyIntegration/CommonFeatures/GradientGI`), Unity's three ambient colours are in the scene file's RenderSettings, and the person asked for it for visual parity in the level (one per level).
- D.9 Found in I.1: the converter read Euler angles off a rotation for the order Z*Y*X, and the engine composes them as `rotx * roty * rotz` (`AZ::Quaternion::SetFromEulerRadians`, `Transform2-2026`). Right for a turn about one axis, wrong for two or more. Fixed with the quaternion map, in the same place.
- D.10 A regression is accepted when it is a second defect uncovered by the fix. First case: `Table_corner/Table_cabinet_A`'s mesh passed only because its entity was turned the wrong way by 180 degrees and its model is off by `rot Z 180`; with the entity right, the model's error shows. It belongs to I.3.
- D.11 I.1 and I.2 were proven by one cycle: they touch different clusters (transforms and scene rows; the level's cook), so the difference attributes itself.
- D.12 The mesh import rule, from the file alone (answers Q.1 and Q.2).
  - Q.1, from `SceneAPI::Utilities::DetermineWorldTransform` and `ModelAssetBuilderComponent` (`Transform2-2026`): with an advanced coordinate rule the model's vertex is `rule * vertex`, where `vertex` is the node's own geometry. The node's transform in the file is not applied, the built-in axis converter is switched off, and the node's geometric transform is not applied either. Without an advanced rule the engine would bake the node's world transform and a half turn about Z instead.
  - Unity's mesh is the node's own geometry with the geometric transform `G` baked in and X negated.
  - So `rule = U * G * K`: `U` is `(x, y, z) -> (-x, z, y)` (Unity's negated X and the axis swap together), `K` takes the pipeline's vertices back to the file's raw ones and depends only on the file's up axis: `U` again for a Y-up file, a half turn about Z for a Z-up file (measured).
  - Q.2: yes for this pack. No node's place in the file enters, so there is nothing to "centre". Unity is not needed for the rule. Files with an up axis other than Y or Z get no rule and a log line.
  - Why the old heuristics seemed to work: 3ds Max writes a geometric rotation of -90 about X on every node, which makes the rule a quarter turn about X for Y-up files and nothing for Z-up files - the old "auto rotation". The auto-centre guessed at the geometric translation from centroids.
- D.13 A mesh passes when its fitted offset is within the position tolerance plus the noise of the fit (the per-vertex spread left after the fit), and its fitted turn within the rotation tolerance plus the angle that noise subtends at the mesh's own spread. Unity's compressed vertices carry errors that are not independent from vertex to vertex (a whole face moves together), so an offset smaller than that noise cannot be told from Unity's rounding. Such passes are counted apart in the report ("within Unity's rounding").
- D.14 The settings `auto_rotation` and `auto_center` keep their keys and now switch the file's rule: its rotation and its translation. Saved projects load unchanged; the Mesh tab's labels read "Axis rule from the file" and "Geometric offset from the file". (I.3's "gone, with their settings" is met for the heuristics; the keys stay.)
- D.15 `converter_cli.py run --seed` restores the plain `uuid4` when the run ends: within one process (the test suite) the seeded generator leaked into later code.
- D.16 A renderer's mesh is found through Unity's own id of it, never through the prefab's names or nesting (answers Q.3, first half).
  - A mesh reference is `{guid, fileID}`. The id is the one the model's `.meta` lists for the mesh's name (`internalIDToNameTable`, older files `fileIDToRecycleName`), and where the table has no such name, `xxHash64("Type:Mesh->" + name + "0")` read as a signed number. Unity names a mesh after its node. Checked on the truth dump: all 276 meshes of the pack's FBX files resolve to their node (211 hashed, 65 from tables).
  - The node's path for O3DE's selection is read from the file's own tree (`RootNode.Lockers_body.Locker_door_A`). The old path was built from the prefab's object names, which selected nodes that do not exist; a node no selection names follows its parent, so such a group held the whole file.
  - A group is named after its node (`{stem}-{node}`), so it is the same whichever prefab asks, and every group unselects every other mesh node of the file. Groups are kept across prefabs: the file's one `.assetinfo` carries all the groups known in the run, seeded from the last run's record for a partial run (H.5 of the baseline, "the last prefab wins").
  - Material labels come from the node: the materials its polygons use, in the order of first use (the order of Unity's renderer slots; 351 slots checked).
- D.17 An instance of a model file (an FBX dropped into a prefab) becomes plain entities, one per object Unity makes of the model (answers Q.3, second half).
  - Unity's object tree from the file alone: one object per node; a file with one top node has it as root, otherwise Unity makes a root; the root is named after the file. A node's position is `(-x, y, z)` times the unit, its rotation `pre * local * post^-1` with X negated, its scale as stated; in a Z-up file the top nodes are also turned to Y-up. Checked against the truth dump's model hierarchies: 232 models, 277 objects, worst miss 0.005 mm, 0 degrees.
  - An object inside an instance has the id `(instance id XOR its id in the source) AND 0x7FFF...F` (117 objects checked), so the components and children a prefab adds to a model's object attach by id. The parser had skipped them.
  - Limits, each reported at conversion: the id of a model's child object is not known where the `.meta` table is empty (28 of 277 objects; the hash for objects is not the one for meshes), so nothing can be added to or overridden on such a child; the importer switches `bakeAxisConversion` and `preserveHierarchy` are not modelled; only binary FBX is read.
- D.18 An instance's overrides go to the object they target. The parsers had applied every position override of a nested instance to the instance itself, so a door nudged inside its frame moved the whole door prefab (`Cell/Door_Cell` 1.67 m, `Showcase` `Door_Bronze_Windows` 17.7 m).
  - The root is the override target that carries position and rotation whole (Unity always stores those seven for an instance's root). Overrides on other targets become patches on the entity made of that object, through the nested prefab's entity map, which now also holds which object owns which transform.
  - For those patches to resolve: prefabs are converted nested-first, and every entity is written with a `Translate` (a patch can replace one axis only of a position that exists).
- D.19 A Unity built-in mesh has no file; the converter writes it. The cube is written as an OBJ with its own `.assetinfo`. An OBJ's top node is named after the file with the dot made an underscore, not `RootNode` (read off the job log after the first try cooked an empty model). Only the cube so far: it is the same under any turn of the axes, so the OBJ's orientation in the pipeline did not have to be measured. The other built-in meshes are reported, not written.
- D.20 The non-uniform scale component's field is `NonUniformScale` (`EditorNonUniformScaleComponent::Reflect`); the converter wrote `Scale`, which the engine ignores (answers Q.4). A nested instance's non-uniform scale is patched onto its root entity, since a container passes nothing down. Carried: O3DE does not pass a non-uniform scale to children; an object with children, or a nested prefab of several objects, is scaled at its root only and reported. That case needs Transform 2 and is not in this pack.
- D.21 A box collider's sides are written as magnitudes, a side of zero as 0.1 mm. The person saw the Editor log full of "Negative or zero values are invalid for box dimensions" (2026-11-25) and suspected Transform 2. The five lines per level load are five Unity colliders authored that way (`Whiteboard_standing` two with z = -0.02, `Paper_A/B/C` with y = 0); the pack has no negative scale at all. PhysX dropped the shape; Unity collides with the magnitudes.
- D.22 A collision group always carries its coordinate rule, also an identity one. Without an advanced rule the engine bakes the node's place in the file into the collision mesh (`Flag_wall` 20.5 m, `Table_corner` 48 m off). I.3 had left identity rules out.
- D.23 Scene lighting (answers Q.6). One entity per level with `AZ::Render::EditorGradientGIComponent`; the fields are `HighColor`, `MidColor`, `LowColor` under `Controller/Configuration` (`GradientGIComponentConfig::Reflect`, branch `Gradient-GI`), fed Unity's sky, equator and ground colours.
  - The colours are passed as stored. The component writes them unchanged into a floating-point cubemap, so it takes linear light; Unity's stored defaults sit, within the three places it writes, on the linear values of whole-number sRGB picks. Not checked against a rendered frame: T.10.
  - `m_AmbientMode` 1 (gradient) and 3 (one colour) map exactly. For 0 (skybox) and 4 (custom) Unity lights from the sky, not from the three colours; the stored colours are still written (the person asked for the scene's three colours) and the conversion says so. `Showcase` is such a scene: its three colours are Unity's defaults.
  - The component shares a service with the Global Skylight (IBL) component; a converted level carries neither a skylight nor a second gradient.
- D.24 Harness verdicts (measurement, not conversion), each needed to tell a real miss from the truth's own noise:
  - the turn allowance of D.13 is measured at the points' reach from the axis of the fitted turn (a pencil turns about its length by 0.37 degrees on 0.05 mm of noise);
  - a mesh collider is judged like a render mesh (D.13);
  - a Unity material that is no asset of the project (the default one on an editor-made cube) is listed, not asked for;
  - an object reached through an instance the converter flattened (D.17) is joined by its own id.

## Q - Open questions
- Q.1 (answered, D.12) What does the engine's scene pipeline do to a mesh node with a coordinate rule and without one (axis conversion, node world transform, unit scale, order of rotation and translation)? Read `Transform2-2026` and test by cycle - blocks I.3.
- Q.2 (answered, D.12) Is the rule every model needs derivable from its FBX alone? If not, which models need the truth dump (D.5) - blocks I.3.
- Q.3 (answered, D.16, D.17, D.19) Why does the converter emit no model for ten renderers (the StairsMod and elevator prefabs), and why are five door prefabs and six nested objects not converted - blocks I.4.
- Q.4 (answered, D.20) Why does an emitted `EditorNonUniformScaleComponent` not act in the Editor - blocks I.5.
- Q.5 (answered, D.21, D.22, D.24) Which collider clusters are left once I.1 to I.5 are in - blocks I.6.
- Q.6 (answered, D.23) The Gradient GI component's serialized fields, and which Unity ambient modes map onto it - blocks I.7.

## I - Stages
- [ ] I.1 Rotation map (ran) - Done when:
  - entities, nested instances and scene instances get the rotation `(-x, -z, -y, w)`;
  - the directional light needs no pitch patch and shines within tolerance of Unity's direction;
  - the report has no "rotation inverted" element in prefabs or in `Showcase`, and nothing regressed.
  - [x] I.1a Quaternion map `(-x, -z, -y, w)` in `convert_to_o3de_coordinates` and in the Unity plugin's copy; Euler angles extracted for the engine's order `rotx * roty * rotz` (D.9); the scene converter uses the writer's conversion; the light's pitch patch removed. Ran: 9 unit tests.
  - [x] I.1b The report compares the objects of a scene that are not prefab instances (the light, the camera, loose geometry).
  - [x] I.1c Cycle. Ran: failing transforms 32 -> 8, failing colliders 69 -> 34, no inverted rotation left, the Showcase light 0.000 degrees off Unity's. One regression, explained (D.10).
- [ ] I.2 One name per prefab (ran) - Done when:
  - a nested prefab's `Source` is spelled the same from a prefab and from a level;
  - the converted `Showcase` level no longer fails on the source name.
  - [x] I.2a A nested instance's `Source` is the converted prefab's path from the O3DE project root (it was computed from the Unity source path, found no project above it and fell back to the lower-case hint spelling). Ran: 3 unit tests; the level's prefab job now fails only for the elevator entity of I.4.
- [ ] I.3 Mesh import rule (ran) - Done when:
  - Q.1 and Q.2 are answered in writing with the evidence;
  - the mesh import table of the report reads "none" for every model, or lists what cannot be and why;
  - the auto-centre and collider-alignment heuristics that the rule replaces are gone, with their settings.
  - [x] I.3a Q.1 answered from the engine source, Q.2 from the measurements (D.12). The rule each of the 255 models needs was computed from the report and the trace, then a formula from the file's facts was searched and validated offline by applying it to every model's vertices: 230 of 255 fit.
  - [x] I.3b `fbx_reader.py` (record tree, import facts) and `source_import_rule` in the assetinfo writer; the centroid auto-centre, the bbox collider alignment and their helper functions removed; collision meshes get their own node's rule. The two toggles keep their keys (D.14). Ran: 9 unit tests; writer and FBX tests rewritten.
  - [x] I.3c Cycle. Ran: prefabs 13 -> 184 pass, meshes 27 -> 327 pass, colliders 648 -> 658, 310 elements fixed, 0 regressions, 53 clusters closed.
  - [x] I.3d Mesh verdict allows for the noise of Unity's own vertices (D.13).
- [ ] I.4 Missing models and objects (ran) - Done when:
  - no renderer is left without a model that Unity shows one for; an FBX used by several prefabs keeps every group each of them needs;
  - the five door prefabs and the six nested objects convert, or are listed with the reason;
  - the three elevator prefabs and both levels pass their prefab jobs.
  - [x] I.4a `fbx_reader` reads the node tree (parent, path, mesh, materials used); `platforms/unity/model_import.py` (ids, mesh to node, Unity's object tree, materials); `matrix3.py` holds the small matrix arithmetic. Ran: offline against the truth dump (T.12), 31 unit tests.
  - [x] I.4b The processor names each renderer's node from its mesh reference, groups by node, keeps groups across prefabs; the writer unselects every other mesh node (D.16). The parser flattens model instances (D.17). Ran: cycle, 196 -> 207 prefabs pass, failed prefab jobs 5 -> 0, 22 elements fixed, 0 regressions.
  - [x] I.4c Unity's built-in cube written as an OBJ (D.19). Ran: 5 unit tests; cooked on the second try.
  - [x] I.4d Overrides of a nested instance go to the object they target; prefabs converted nested-first (D.18). Ran: 12 unit tests; cycle, `Showcase` 220 -> 222 of 222.
- [ ] I.5 Non-uniform scale (ran) - Done when: the seven objects with a non-uniform Unity scale have it in the Editor.
  - [x] I.5a The component's field name (D.20), in the prefab writer and the scene converter. Ran: 4 unit tests; cycle, six of the seven objects and the `Showcase` cube pass their transform.
  - [x] I.5b A nested instance's non-uniform scale on its root entity (the seventh, `Storage_metalbox/Folder_C`). Ran: 3 unit tests.
- [ ] I.6 Colliders (ran) - Done when: the collider clusters left after I.5 are closed or carried with a reason.
  - [x] I.6a Box sides as magnitudes with a floor (D.21). Ran: 2 unit tests; cycle, "Box: no shape in O3DE" closed.
  - [x] I.6b A collision group always carries its rule (D.22); mesh colliders judged like meshes (D.24). Ran: 2 unit tests; cycle, every collider cluster closed.
- [ ] I.7 Scene lighting (ran) - Done when: a converted level carries one Gradient GI entity with the Unity scene's three ambient colours, and its directional light as in I.1; the person finds the level lit like the Unity scene.
  - [x] I.7a `platforms/unity/scene_lighting.py` reads the ambient gradient; the scene converter adds the entity (D.23). Ran: 9 unit tests.
  - [x] I.7b The scene probe reads the component back from the Editor and the report compares it with the Unity scene file (D.3). Ran: 4 unit tests; the lighting row passes.

## State after I.7 (2026-11-25, all stages ran, none verified by the person yet)
Last cycle against the baseline:

| | Baseline | Now |
|---|---|---|
| Prefabs passing | 13 of 222 | 221 of 222 (1 unmeasured) |
| Transforms | 355 pass, 32 fail | 393 pass |
| Meshes | 28 pass, 338 fail, 1 uncooked | 373 pass (22 within Unity's rounding, D.13) |
| Colliders | 613 pass, 69 fail | 688 pass, 1 unmeasured |
| Materials | 360 pass, 7 fail | 373 pass |
| Showcase | 212 of 217 instances | 223 of 223 rows (222 placements, the lighting) |
| Failed prefab jobs | 5 | 0 |
| Clusters | 83 | 0 |

Carried, each with its reason (for T.11):
- `FPS Controller`: its Unity `CharacterController` is unmeasured. The harness has no geometry for that collider type and the converter no processor for it.
- Objects of a scene that carry their own mesh get no model: the scene stage has no mesh stage (it hands the processors empty mesh and material maps). In `Showcase` that is the ground slab `Cube`; its transform and scale are right, it shows nothing. A feature of its own, not a fix.
- Built-in meshes other than the cube (sphere, capsule, cylinder, plane, quad) are reported, not written (D.19). None in this pack.
- The written cube's faces were checked for place, not for which way each face's texture runs.
- A non-uniform scale is not passed down to children (D.20). None left in this pack.
- A model's child object whose id is not known cannot take added components or overrides (D.17). None in this pack.
- `Showcase` takes its ambient light from Unity's default skybox; its Gradient GI carries the three stored colours, which are Unity's defaults and darker than that sky (D.23). T.10 will show it.
- The harness passes 22 meshes and collision meshes on the noise allowance of D.13 and D.24; the largest offset among them is 8.8 mm on the 55 m `BG_Building` (noise 34.9 mm), the next 3.2 mm.

## T - Proofs
| ID | Proof | Stage |
|---|---|---|
| T.1 | Unit tests: the rotation map against the matrix form `A X A` over random rotations; a yaw of +90 faces +X; the light emits no patch | I.1 |
| T.2 | Cycle: "rotation inverted" gone from prefabs and from `Showcase`; the light's transform passes; difference shows no regression | I.1 |
| T.3 | Unit test: a nested instance's `Source` equals the level's spelling for the same prefab | I.2 |
| T.4 | Cook: no "source template" error on the converted level | I.2 |
| T.5 | A written answer to Q.1 and Q.2 with the numbers behind it, in the working doc | I.3 |
| T.6 | Unit tests on the rule's arithmetic; cycle: mesh import table "none" for all but the listed exceptions; no regression | I.3 |
| T.7 | Cycle: no "emitted no model", no "not produced", no unmatched object beyond the listed ones; cook: no failed prefab job. Ran: holds | I.4 |
| T.8 | Cycle: the seven objects pass their transform with their scale. Ran: holds, and the `Showcase` cube | I.5 |
| T.9 | Cycle: collider clusters closed or listed. Ran: all closed; one collider unmeasured | I.6 |
| T.10 | The person opens the converted `Showcase` level and the Unity scene side by side: light direction and ambient tone agree. Ran so far: the Editor holds one Gradient GI component with Unity's three colours (read back by the probe), the light's direction is 0.000 degrees off. Verified by the person on 2026-11-25: side by side, lighting and light direction very close, a pass | I.7 |
| T.11 | The person reads the final report against the baseline and accepts what is carried. Verified by the person on 2026-11-25 (the Desk Metal sheet reviewed, everything in place); scene objects with their own mesh go to `mem:second_pack/plan` | P |
| T.12 | Offline, against the truth dump's model hierarchies: `platforms.unity.model_import` gives every model's objects, transforms, ids, mesh nodes and material slots as Unity has them. Ran: 232 models, 277 objects, 276 meshes, 351 material slots, 0 misses (249 object ids known, 28 not) | I.4 |

## Project
- Rules read: `AGENTICS_GUIDELINES.md`, `tests/README.md`, `parity/README.md`, the memories named at the top, the global CLAUDE.md. No CLAUDE.md or AGENTS.md in the repo.
  - Plain Python `assert` tests on `tests/harness.py`; section banner comments; no TODO comments; long docstrings on public surfaces; the vocabulary of guidelines section 8.
  - Platform code stays behind the `SourcePlatform` contract. Code runs on the installed Python 3.9.
  - A file whose working copy carries CRLF is brought to LF before it is edited (the index holds LF).
  - The probe gem is O3DE source: ASCII only, `m_` members.
  - Never commit or push; never write to GitHub. Claude proposes commits.
- Proof commands: `QT_QPA_PLATFORM=offscreen python tests/run_all.py`; `python parity/parity.py cycle parity/configs/office.json` (Unity project, Editor and Asset Processor closed); gem builds through the O3DE MCP.
- Record: `.serena/memories/parity_fixes/record.md`
- Wipe: nothing. The plan and the working doc are kept (D.6).
