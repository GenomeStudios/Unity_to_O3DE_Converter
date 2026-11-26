---
name: second-pack-plan
description: PIT plan for the converter's second asset pack (Tirgames, measured by the parity harness) and for the objects of a scene that are not prefab instances - their meshes, materials and models dropped into a scene.
metadata:
  type: plan
---

Feature: `second_pack`. Working doc: `.serena/memories/second_pack/working_doc.md`. IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix.

Starts from `mem:parity_fixes/plan` (what was fixed on the Office pack and why) and `mem:parity_harness/record` (how the harness works). Machine facts: `mem:parity_harness/environment`.

## P - Deliverable
The converter holds on a pack it was not shaped on, and converts what a scene holds beside its prefab instances:
- the Tirgames pack (`D:/OffLocalDev/dellagolayover/Assets/TirgamesAssets`: 263 prefabs, 258 FBX, the level `GentlemensClubScene`) has a parity report that is clean at the agreed tolerance (1 mm, 0.1 degree, 1 mm), or says for each element that is not why it cannot be;
- an object of a scene that is not a prefab instance converts like an object of a prefab: its mesh and materials (also Unity's built-in cube), its colliders, and a model file dropped straight into the scene. The `Showcase` floor shows; the `OfficePack_Example` elevator doors stand;
- the two formed levels, `GentlemensClubScene` and `OfficePack_Example`, place everything, or list what they do not with the reason;
- nothing regresses on the Office pack.

For: the person. The reports of the two beds are the evidence.

Out of scope: how materials shade (the pack's shader graph, 19 materials); baked lighting, reflection probes, light probes, audio, cameras, animation; terrain; a third pack; the GUI.

## Design
- Two test beds side by side in the one O3DE project `D:/OffLocalDev/xxxxxDelete/ConverterTest`: the Office bed as it is, the Tirgames bed with its own output folder (`Assets/TirgamesPack`), measurement level (`Bench_Parity_Tirgames`) and run folder.
- The pack has no gallery scene. The harness's baked measurement level is the gallery: every prefab once, on a grid.
- One loop, as in `parity_fixes`: change the converter, run the cycle of the bed concerned, read the difference from the previous run; then the other bed for regressions.
- What the pack brings that the Office pack did not (survey of 2026-11-25): FBX in millimetres (104) and inches (2) beside centimetres (152), all Y-up; importer `globalScale` of 1.1 and 1.5 on five files; 42 capsule colliders; 49 lights inside prefabs; 5 built-in cubes; no LOD groups; no model instances; a scene of 1927 prefab instances and 105 objects of its own (lights, probes, a camera), ambient mode Color.

## D - Decisions
- D.1 One plan for the second pack and for scene objects - they share the harness, the O3DE project and the proof (a cycle), and the formed levels need both. The person asked for both on 2026-11-25.
- D.2 A bed names its own run folder: an optional `work` in its config, default `Parity`, under the O3DE project's `user/`. The Office bed keeps `user/Parity` with its baseline; the Tirgames bed gets `user/Parity_Tirgames`. Two beds must not overwrite each other's truth, trace and report.
- D.3 The tolerance of the Office bed (1 mm, 0.1 degree, 1 mm) and its verdicts (`mem:parity_fixes/plan` D.13, D.24) hold for the second bed unchanged. A verdict is not loosened for the new pack without a decision here.
- D.4 The harness refuses to cook or probe while the Editor or the Asset Processor runs on the project (it never closes them). The person opens converted levels in the Editor between runs, so a stage that needs a cycle waits until the Editor is closed, and says so.
- D.5 "Not a prefab instance" covers, from the person's example: a scene's own object with a mesh and materials (the `Showcase` floor: Unity's built-in cube with a project material); its colliders (already emitted); a model file instanced straight in a scene. Lights are converted already. The other kinds a scene holds are listed in the coverage, not converted (out of scope).
  - Corrected on 2026-11-25: neither scene of the Office pack nor the Tirgames level instances a model file. The four `W_3x_Elevator_Door` that `OfficePack_Example` missed are the prefab `W_3x_Elevator`, renamed in the scene (D.9). A model instanced in a scene is converted all the same, by the code that does it in a prefab, and is proven by unit test only.
- D.6 A fix made for the new pack is a fix to the rule, not a case for the pack: it has to be stated from the file or from Unity's behaviour, and the Office bed has to stay as it is (`mem:parity_fixes/plan` P).
- D.7 `parity_fixes`: the person passed T.10 (lighting and light direction, side by side) and T.11 (the report, Desk Metal reviewed) on 2026-11-25 and committed. It is concluded when the person calls for it.
- D.8 A scene's own objects go through Stage 1's asset conversion (answers Q.3). The part of `process_prefab` that converts what a set of objects shows became `IntegratedAssetProcessor.convert_assets_of`; the scene stage is handed one Stage 1 worker for the run (`stage_runner.asset_stage_arguments`, from the same project settings) and asks it for its own objects' materials, models and collision meshes. The worker's mesh fingerprints are merged into the project like Stage 1's, so a model file's groups are kept across the two stages.
- D.9 A placed prefab is found by the guid the scene names it by (answers Q.4). The scene stage looked prefabs up by the instance's name: the guid table was only ever filled from `.meta` files beside converted prefabs, which do not exist. A renamed instance was missed (`OfficePack_Example`: 5 kinds; `GentlemensClubScene`: 694 of 1927 instances) and one renamed to another prefab's name would have taken that prefab. The table is now filled from Stage 1's records; the name is tried only when the guid is unknown.
- D.10 The mesh import rule carries a scale (answers Q.2).
  - The engine brings a file's unit to metres itself: millimetre and inch files showed no residual of their unit.
  - A node's geometric transform also scales (93 of the pack's 323 mesh nodes, by 0.25 to 10; the Office pack has none), and Unity bakes it into the mesh. A scaling that is the same on all axes goes into the rule's `scale`, which the engine applies before the rule's rotation.
  - Unity's importer scale factor (`globalScale`, 1.1 and 1.5 on five files) multiplies the mesh and the nodes' places; it multiplies the rule's scale and translation, and a model's object positions.
  - Carried, I.3: a geometric scaling that differs by axis (16 mesh nodes, 8 prefabs) cannot be written into the rule. It can be had exactly as a non-uniform scale on the entity, with the rule's translation divided by it and box colliders on the entity sized against it, where the rule's rotation maps axes onto axes; not built yet.
- D.11 An entity's one scale for all axes is written to `UniformScale`. The converter wrote it to `Scale`, the engine's legacy three-axis field, where a number is not read (`EditorTransform::Reflect`). Every uniformly scaled object and instance lost its scale; the Office pack has none, so it never showed (the club level: 134 placements).
- D.12 A capsule that lies along Unity's X or Z, and a capsule or sphere on an object with a non-uniform scale, get an entity of their own under the object. An O3DE capsule stands along its entity's Z and cannot be turned as a shape; and the engine declares capsule and sphere shapes incompatible with a non-uniform scale, so a prefab or level holding the pair does not cook (`GentlemensClubScene` did not). On its own entity the collider takes the object's scale the way Unity applies it: the centre by axis, a capsule's height by the scale along it and its radius by the larger across it, a sphere's radius by the largest. A nested instance whose root carries such a collider cannot be handed a non-uniform scale from outside; that is reported, not patched.
- D.13 The harness allows the truth the step of Unity's own mesh compression (not a loosening for this pack: it holds for both beds and is stated from Unity's behaviour, D.3).
  - Unity's High compression keeps 10 bits of a position over the mesh's largest extent. Flat panels of 3.5, 7 and 14 m come out of Unity up to one step of size / 1023 off on each axis (4.2, 8.4, 16.8 mm in length), in proportion to their size, while the converter's model is the file's.
  - On a mesh of four vertices the noise left after the fit does not show it: the fit takes a shift that all vertices share. So the allowance of `mem:parity_fixes/plan` D.13 is the larger of that noise and one step on all three axes. Only High is measured; other settings get no allowance.
- D.14 The report's lighting row reads Unity's one-colour ambient mode as one colour: the sky colour counts for all three, as the converter writes it.
- D.15 The report measures a placed prefab at the prefab's own root entity, not at its container. Unity's instance root is both; in O3DE a placement's non-uniform scale can only sit on the root entity, so a container never shows it.

## Q - Open questions
- Q.1 (answered, the Baseline section) What does the baseline of the new pack show: which clusters, and which of them are new kinds - blocks I.3.
- Q.5 Placed prefabs with a negative scale (43 in the club level: mirrored walls, bars, sofas, steps). The converter gives their root entity a non-uniform scale with the negative axis, and the Editor holds it: their transform rows pass. Whether the engine draws and collides a negative non-uniform scale right is not measured (the probe reads transforms, not pictures). The person said on 2026-11-25 that inverse scale needs Transform 2. To settle: the person looks at one mirrored piece in the level (T.6), and if it is wrong, how a mirrored instance is to be written for Transform 2 - blocks I.4.
- Q.6 Two materials of the pack's shader graph are not emitted (`LightEmission01`, `CommonLight01`): is the material missing or only not assigned - blocks I.3.
- Q.2 (answered, D.10) Does the engine's scene pipeline bring a file's unit to metres under an advanced coordinate rule, and how does Unity's importer `globalScale` reach the model - blocks I.3 (the baseline answers it).
- Q.3 (answered, D.8) A scene has no asset stage of its own: by which path do a scene object's mesh and materials get copied, grouped and named - blocks I.2.
- Q.4 (answered, D.9) Which of the five things `OfficePack_Example` misses is the unnamed one - blocks I.2.

## I - Stages
- [ ] I.1 Second bed and baseline (ran) - Done when:
  - the harness runs two beds without one touching the other's run folder, and the Office bed's result is unchanged;
  - the Tirgames conversion project and bed exist, and a baseline cycle has run and is kept;
  - the baseline's clusters are listed here as suspects, Q.1 and Q.2 answered where the baseline answers them.
  - [x] I.1a A bed names its run folder (`work`, D.2); `parity/configs/tirgames.json` and its conversion project. Ran: 3 unit tests; the Office bed's cycle unchanged (221 pass, 1 unmeasured, Showcase 223 of 223).
  - [x] I.1b Baseline cycle of the Tirgames bed, kept in `user/Parity_Tirgames/baseline_2026-11-25/`. Ran: see the Baseline section.
- [ ] I.2 Scene objects - Done when:
  - a scene's own object with a mesh gets its model and materials, also for Unity's built-in cube;
  - a model file instanced in a scene becomes entities, as in a prefab;
  - the report measures a scene object's mesh, materials and colliders, not only its transform;
  - `Showcase`: the floor's rows pass. `OfficePack_Example`: nothing missing.
  - [x] I.2a `convert_assets_of` taken out of `process_prefab`; the scene stage uses it for its own objects; a model instanced in a scene becomes entities (D.8). Ran: 8 unit tests; in the probed `Showcase` the floor has its cube model loaded, its material, its scale and its box collider; the Office bed unchanged.
  - [x] I.2b A placed prefab is found by its guid (D.9). Ran: 3 unit tests; `OfficePack_Example` places 1507 of 1507 (5 kinds were missing), `GentlemensClubScene` 1927 of 1927 (694 instances were).
  - [ ] I.2c The report measures a scene object's mesh, materials and colliders. Not started: today it compares their transforms only.
- [ ] I.3 The new pack's clusters - Done when: each cluster of the Tirgames baseline is closed, or carried with a reason; the Office bed shows no regression.
  - [x] I.3a The rule's scale: geometric scaling and the importer's scale factor (D.10). Ran: 5 unit tests; cycle, prefabs 145 -> 221 of 263, meshes 210 -> 303 of 344, 119 elements fixed, 0 regressions.
  - [x] I.3b `UniformScale` (D.11). Ran: 3 unit tests.
  - [x] I.3c Capsules and spheres on entities of their own (D.12). Ran: 12 unit tests.
  - [x] I.3d Harness: the compression step (D.13), the one-colour ambient mode (D.14), placements at their root entity (D.15). Ran: 4 unit tests.
  - [x] I.3g Cycle with I.3a to I.3d. Ran: prefabs 250 of 263, the level cooks (failed jobs 1 -> 0), `GentlemensClubScene` 2021 of 2033 rows; against the baseline 154 elements fixed, 0 regressions, 40 of 44 clusters closed.
  - [ ] I.3e A geometric scaling that differs by axis (D.10, carried part).
  - [ ] I.3f The two materials of Q.6.
- [ ] I.4 The formed levels - Done when: every row of `GentlemensClubScene` and of `OfficePack_Example` passes or is carried with a reason, and the person has walked both.

## Baseline of the Tirgames bed (2026-11-25, before any change made for it)
| | Baseline |
|---|---|
| Prefabs | 145 pass, 117 fail, 1 unmeasured, of 263 |
| Transforms | 438 pass, 1 fail |
| Meshes | 210 pass (52 within Unity's rounding), 134 fail |
| Colliders | 282 pass, 40 fail, 1 unmeasured |
| Materials | 342 pass, 2 fail |
| `GentlemensClubScene` | 1220 pass, 119 fail, 694 not placed |
| Failed jobs | 1: the level itself |
| Clusters | 44 |

Suspects, with what became of them:
- S.1 Mesh "scale" and "scale + shift" (about 110 elements): geometric scaling and the importer's scale factor. Fixed, D.10.
- S.2 694 instances not placed: prefabs looked up by the instance's name. Fixed, D.9.
- S.3 88 placements (134 once all were placed) with a lost uniform scale, and `Refrigerator01Glass`: the `Scale` key. Fixed, D.11.
- S.4 The level's job failed on a capsule beside a non-uniform scale; four lying capsules 0.5 to 2.5 m off their surface. Fixed, D.12.
- S.5 About 28 meshes and collision meshes of large flat panels 3 to 17 mm off: Unity's compression step. Harness, D.13.
- S.6 14 meshes and 6 convex colliders "unexplained": a geometric scaling that differs by axis. Open, I.3e.
- S.7 43 placements mirrored in Unity and not in O3DE: negative scale. Open, Q.5.
- S.8 Two renderers missing one material each. Open, Q.6.
- S.9 The lighting row failed on the one-colour ambient mode. Harness, D.14.
- S.10 Two signs (`WC1Male`, `WC1Female`) are placed under an object that sits inside another placed prefab (a door's leaf). The scene stage does not know that object, so they stand at the level's origin, 63 and 68 m off. Open, I.4.
- S.11 Ten placements of `StripPole01_300cm` and `_275cm` are stretched in Unity; their root carries a capsule, so the scale cannot be handed to it (D.12). Open, I.4: the pole's mesh keeps its unstretched height.

State after the first session (2026-11-25): prefabs 250 pass, 12 fail, 1 unmeasured; transforms 439 pass; meshes 328 pass (93 within Unity's rounding), 16 fail; colliders 317 pass, 5 fail, 1 unmeasured; materials 342 pass, 2 fail; `GentlemensClubScene` 2021 of 2033 rows; failed jobs 0; clusters 4 (S.6 three times, S.8).

## T - Proofs
| ID | Proof | Stage |
|---|---|---|
| T.1 | Unit test: two beds resolve to two run folders; cycle of the Office bed: same counts as the last run of `parity_fixes` | I.1 |
| T.2 | `python parity/parity.py cycle parity/configs/tirgames.json` runs to a report; a copy kept as the baseline | I.1 |
| T.3 | Unit tests: a scene object with a mesh and a material; with the built-in cube; a model instanced in a scene | I.2 |
| T.4 | Cycle of the Office bed: the `Showcase` floor's mesh and material rows pass; conversion of `OfficePack_Example` reports no missing prefab | I.2 |
| T.5 | Cycle of the Tirgames bed: clusters closed or listed; cycle of the Office bed: no regression | I.3 |
| T.6 | The person opens `Showcase` (the floor is there), `OfficePack_Example` (the elevator doors stand) and `GentlemensClubScene` in the Editor | I.2, I.4 |
| T.7 | The person reads the Tirgames report against its baseline and accepts what is carried | P |

## Project
- Rules read: `AGENTICS_GUIDELINES.md`, `tests/README.md`, `parity/README.md`, the memories named at the top, the global CLAUDE.md. No CLAUDE.md or AGENTS.md in the repo.
  - Plain Python `assert` tests on `tests/harness.py`; section banner comments; no TODO comments; long docstrings on public surfaces; the vocabulary of guidelines section 8.
  - Platform code stays behind the `SourcePlatform` contract. Code runs on the installed Python 3.9.
  - A file whose working copy carries CRLF is brought to LF before it is edited (the index holds LF).
  - Never commit or push; never write to GitHub. Claude proposes commits.
- Proof commands: `QT_QPA_PLATFORM=offscreen python tests/run_all.py`; `python parity/parity.py cycle parity/configs/office.json`; `python parity/parity.py cycle parity/configs/tirgames.json` (Unity project, Editor and Asset Processor closed).
- Record: `.serena/memories/second_pack/record.md`
- Wipe: nothing. The plan and the working doc are kept (the person's standing answer for this repository).
