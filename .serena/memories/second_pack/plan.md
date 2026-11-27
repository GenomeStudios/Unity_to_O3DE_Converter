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

Plan change, 2026-11-26: the person walked `OfficePack_Example` and `GentlemensClubScene` in the Editor and asked for what they saw to be put right - lights, material overrides, glass, smoothness, cutout textures, collider drawing, the podiums - and for each attribute of a Unity material to get a rendition in O3DE even where it cannot be exact. So how a Lit material shades is in scope (stages I.5 to I.7 and the Material mapping section).

Out of scope: the pack's own shader-graph additions (a tint mask); baked lighting, reflection probes, light probes, audio, cameras, animation; terrain; a third pack; the GUI.

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
- D.16 The person may have their hand-tuned files overwritten (said on 2026-11-26: "they were not necessarily measurably working"): two materials, two texture settings and two saved levels in the converted output. Copies are in `user/Parity/hand_tuned_2026-11-26/` of the test project. Everything in the converted output is the converter's; no asset is adjusted by hand to reach parity.
- D.17 Lights.
  - An O3DE spot light shines along its entity's +Z (`SimpleSpotLightFeatureProcessor`: `transform.GetBasisZ()`); the converted Unity object points its light along +Y. A spot is written on a child entity turned -90 degrees about X, so the object's own entity keeps Unity's transform for whatever else it carries. Directional lights shine along +Y and need nothing.
  - Unity's Range ends the light. Every light is written with `AttenuationRadiusMode` Explicit (0) and that range; left at Automatic the engine works a radius out from the intensity.
- D.18 A collision mesh is written with its debug drawing off, like the shape colliders.
- D.19 A material override on a placed prefab reaches its renderer. Unity names the MeshRenderer; the entity map knew objects only, so every such override was skipped (1123 in the club level). The map now holds each renderer's object; the patch adds the slot's entry whole under the model's label for it, and slot 0 also as the entity's default slot. A material that only overrides use (the club's red carpet) is in no prefab: the scene stage converts it when it meets it.
- D.20 An object Unity has switched off does not show (found while checking the levels; not on the person's list). Unity hides an inactive object and everything below it; the converter ignored `m_IsActive`, so 140 switched-off instances stood in the club level and 22 in the Office example. An entity is written `IsRuntimeActive: false` with its Editor visibility off, for the object and everything below it (the runtime does not pass inactivity down). An instance's `m_IsActive` override is patched onto the entities of the nested prefab, by the entity map's parents.
- D.21 Opacity, from the engine's shaders (`AlphaInput.azsli`, `AlphaUtils.azsli`): alpha is the base colour texture's alpha times `opacity.factor`; a cutout discards where that alpha is below `1 - factor`.
  - A transparent surface blends, with the base colour's alpha as factor (the texture's alpha is then the same as Unity's) and its highlights unfaded unless Unity's "Preserve Specular Lighting" is off.
  - An alpha clip at a threshold of zero clips nothing: the Office pack's Glass is such a surface, and was written as a cutout.
  - A cutout's factor is one minus Unity's threshold (it was the threshold itself: right at 0.5 only).
- D.22 A colour texture whose alpha is the material's opacity gets its own texture settings beside it: the preset `Decal_AlbedoWithOpacity` at full resolution, as the person found by hand for the Office plant. Without it the image builder treats the file as plain colour and a cutout shows flat distorted planes. The converter writes the sidecar, replacing one that is there.
- D.23 O3DE reads roughness, metallic and occlusion each from the red channel of the texture bound to it. Unity's mask map holds metallic in red, occlusion in green and smoothness in alpha.
  - Roughness: the converter's baked texture kept `1 - smoothness` in the alpha channel, so the engine read the metallic channel as roughness. That is why the toilet mirror did not reflect and its fingerprints were gone. It is now a grey image of `1 - alpha`.
  - Occlusion: bound the mask map itself (red: metallic) to specular occlusion only. It is now a grey image of the green channel on both the diffuse and the specular occlusion, with Unity's strength on both.
- D.24 Emission. A Unity material glows when `_EMISSION` is set. Written as `emissive.enable`, a colour within one and `emissive.intensity` = 3 + log2(brightness), the engine giving off colour * 2^(intensity - 3) nits. Unity's numbers are taken as O3DE's, as the lights' intensities already are, so a Unity emission of one is one nit. That scale is an assumption; the person judges it (T.9). 47 materials of the Tirgames pack and 5 of the Office pack glow; none did.
- D.25 The base map's tiling and offset become the material's `uv.tileU/tileV/offsetU/offsetV` (five materials in the two packs). Which way a V offset runs is not checked.
- D.26 A geometric scaling that differs by axis is carried by the entity (closes the carried part of D.10). The rule's rotation maps axes onto axes for the quarter turns exporters write, so the node's scaling equals a scale along the model's axes; the entity's non-uniform scale holds it on top of the object's own. The rule's translation is written divided by it, a box collider on the same entity too; a capsule or sphere goes to its own entity (D.12); what hangs below is not stretched, since a non-uniform scale is not passed down. The report takes the stretch out of the transform row and measures it in the mesh row.
- D.27 Where a spot light sits is an option of the asset stage, `spot_light_placement` (the person, 2026-11-26: a child entity for every spot doubles the entities, and turning the entity is inconsequential where the light has an entity to itself). Replaces the first half of D.17.
  - `turn_entity`, the default: an object that holds only the light (no mesh, collider, body or child, and no scale that differs by axis) has its own entity turned the quarter about X, and no second entity is made. Any other spot goes on a child entity as before.
  - `child_entity`: every spot on a child entity; every object keeps Unity's transform.
  - The turn is made by the writer before the entity's rotation is written (`prefab_writer.with_light_turn`), noted on the object, and read by the light processor and the trace; the report takes it out of the transform row (`own_transform`), as it does a mesh's stretch.
- D.28 A Unity point light is an O3DE simple point light. It was written as a sphere light, which needs a sphere shape beside it; the Editor draws that shape over the light's range (the person, on `LightCeilingRetro02On`). Unity's point light has no size.
- D.29 A placed prefab's overrides of a light inside it are carried: range, intensity, colour (written whole, the channels not overridden kept from the light), spot angles (halved), shadows. The entity map holds, per Unity Light, the entity and component the light was written on and its colour (`light_owners`). Bounce intensity and lightmapping belong to baked lighting and are reported as not carried. The club level holds 13 intensity, 10 range, 9 shadow and 2 colour overrides; none was placed before.
- D.30 Tiling and offset, corrected (replaces D.25). O3DE's transform scales about `uv.center`, by default the middle of the image (`AZ::Render::CreateUvTransformMatrix`), and its V runs down the image (`AssImpUvMapImporter` stores `1 - v`). Unity's tiling is about the origin with V up. The material is written with the centre at the origin and the V offset `1 - tileV - offsetV`, kept within one image. D.25 passed tiling and offset through as they were, which picked another cell of an atlas: `DoorFrameLight04` (tiling 0.25, offset 0 and 0.75: the top left cell of a 4 by 4 atlas) showed off-white blocks.

## Q - Open questions
- Q.1 (answered, the Baseline section) What does the baseline of the new pack show: which clusters, and which of them are new kinds - blocks I.3.
- Q.5 Placed prefabs with a negative scale (43 in the club level: mirrored walls, bars, sofas, steps). The converter gives their root entity a non-uniform scale with the negative axis, and the Editor holds it: their transform rows pass. Whether the engine draws and collides a negative non-uniform scale right is not measured (the probe reads transforms, not pictures). The person said on 2026-11-25 that inverse scale needs Transform 2. To settle: the person looks at one mirrored piece in the level (T.6), and if it is wrong, how a mirrored instance is to be written for Transform 2 - blocks I.4.
- Q.6 (answered) Two renderers lack one material each (`LightEmission01`, `CommonLight01`). The model file holds two different materials under one name (`Material #35` twice); O3DE names a model's material slots by name, so the two parts share one slot and one material. Carried: whether the engine tells such slots apart by another id is not looked into.
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
  - [x] I.3e A geometric scaling that differs by axis, on the entity (D.26). Ran: 8 unit tests; cycle, meshes 328 -> 344 of 344, colliders 317 -> 322 of 323, prefabs 250 -> 260 of 263.
  - [x] I.3f The two materials of Q.6: carried with their reason.
- [ ] I.4 The formed levels - Done when: every row of `GentlemensClubScene` and of `OfficePack_Example` passes or is carried with a reason, and the person has walked both.
- [ ] I.5 Lights (ran) - Done when: a spot light shines where Unity's does, and lights end at Unity's range.
  - [x] I.5a Spot on a turned child entity; Explicit attenuation (D.17). Ran: 3 unit tests. Verified by the person, 2026-11-26: the lights match their orientation.
  - [x] I.5b The placement option; the entity turned where the object holds only the light (D.27). Ran: 4 unit tests; cycle of the Tirgames bed: transforms 439 of 439, "no change".
  - [x] I.5c A point light as a simple point (D.28). Ran: 1 unit test.
- [ ] I.6 What a level changes on its prefabs (ran) - Done when: a placed prefab shows the materials the level gave it, and what the level switched off does not show.
  - [x] I.6a Material overrides (D.19). Ran: 4 unit tests; conversion of the club level places 1123 of 1123 overrides (0 before), materials converted 131 -> 198. Verified by the person, 2026-11-26: material overrides and material imports work.
  - [x] I.6d Light overrides (D.29). Ran: 5 unit tests.
  - [x] I.6b Active state (D.20). Ran: 9 unit tests.
  - [x] I.6c Collision meshes not drawn (D.18). Ran: 1 unit test.
- [ ] I.7 Materials (ran) - Done when: each attribute of a Unity Lit material in the Material mapping table is carried or listed as not carried, and the person finds glass, mirror, plants and glowing parts rendered.
  - [x] I.7a Opacity rules and texture settings (D.21, D.22). Ran: 8 unit tests.
  - [x] I.7b Roughness and occlusion channels (D.23). Ran: 3 unit tests.
  - [x] I.7c Emission, tiling (D.24, D.25). Ran: 4 unit tests.
  - [x] I.7d Tiling about the origin with V running down (D.30). Ran: 3 unit tests.

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

## Material mapping (Unity URP Lit to O3DE StandardPBR)
What the converter does with each attribute, after I.7. "Carried" is by construction from the engine's shader sources, not from a compared picture.

| Unity | O3DE | State |
|---|---|---|
| `_BaseMap` colour, `_BaseColor` | `baseColor.textureMap`, `baseColor.color` | carried |
| `_BaseMap` alpha, `_Surface`, `_AlphaClip`, `_Cutoff`, Preserve Specular | `opacity.mode`, `alphaSource`, `factor`, `alphaAffectsSpecular`; the texture's settings | carried (D.21, D.22) |
| `_MetallicGlossMap` red, `_Metallic` | `metallic.textureMap`, `metallic.factor` | carried |
| `_MetallicGlossMap` alpha times `_Smoothness` | `roughness.textureMap` (grey, 1 - alpha), `lowerBound` 1 - s, `upperBound` 1 | carried (D.23) |
| `_Smoothness` without a map | `roughness.factor` = 1 - s | carried |
| smoothness from the albedo's alpha (`_SmoothnessTextureChannel` 1) | - | not carried; no case in the two packs |
| `_OcclusionMap` green, `_OcclusionStrength` | diffuse and specular occlusion texture and factor | carried (D.23) |
| `_BumpMap`, `_BumpScale` | `normal.textureMap`, `normal.factor` | carried; the green channel's direction not checked |
| `_EMISSION`, `_EmissionColor`, `_EmissionMap` | `emissive.enable`, `color`, `intensity`, `textureMap` | carried; the brightness scale is an assumption (D.24) |
| base map tiling and offset | `uv.center` at the origin, `uv.tileU`, `tileV`, `offsetU`, `offsetV` (V turned) | carried (D.30) |
| `_Cull` (two-sided) | `opacity.doubleSided` | not carried; every material of the two packs culls its back |
| `_SpecularHighlights`, `_EnvironmentReflections`, `_ReceiveShadows` | - | not carried |
| specular workflow (`_SpecGlossMap`, `_SpecColor`) | `specularF0` | the texture is bound; the workflow is not worked through |
| `_ParallaxMap`, `_Parallax` | `parallax` | the texture is bound; its depth is not |
| detail maps and mask | - | not carried |
| baked lightmaps, light and reflection probes | - | not converted (out of scope) |

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
| T.8 | Unit tests for I.5 to I.7 and I.3e; cycles of both beds with no regression | I.5, I.6, I.7 |
| T.10 | The person opens `GentlemensClubScene` again: `LightCeilingRetro02On` is a simple point light with the level's range of 6 and intensity of 1; `DoorFrameLight04` shows one flat cell of its atlas; a lamp that holds only a spot is one entity | I.5, I.6, I.7 |
| T.9 | The person walks `OfficePack_Example` and `GentlemensClubScene` again: spot lights point as in Unity; floors carry their overridden materials (the blue carpets, the red carpet); nothing stands that Unity has switched off; glass blends, the toilet mirror reflects with its smudges, plants are cut out; lamps and signs glow; the podiums have Unity's size with their colliders on them; no collision mesh is drawn | I.5, I.6, I.7, I.3 |

## Project
- Rules read: `AGENTICS_GUIDELINES.md`, `tests/README.md`, `parity/README.md`, the memories named at the top, the global CLAUDE.md. No CLAUDE.md or AGENTS.md in the repo.
  - Plain Python `assert` tests on `tests/harness.py`; section banner comments; no TODO comments; long docstrings on public surfaces; the vocabulary of guidelines section 8.
  - Platform code stays behind the `SourcePlatform` contract. Code runs on the installed Python 3.9.
  - A file whose working copy carries CRLF is brought to LF before it is edited (the index holds LF).
  - Never commit or push; never write to GitHub. Claude proposes commits.
- Proof commands: `QT_QPA_PLATFORM=offscreen python tests/run_all.py`; `python parity/parity.py cycle parity/configs/office.json`; `python parity/parity.py cycle parity/configs/tirgames.json` (Unity project, Editor and Asset Processor closed).
- Record: `.serena/memories/second_pack/record.md`
- Wipe: nothing. The plan and the working doc are kept (the person's standing answer for this repository).
