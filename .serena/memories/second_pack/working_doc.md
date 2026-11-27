---
name: second-pack-working-doc
description: Working doc of the second_pack plan - the log of its increments, proofs and fixes, newest first.
metadata:
  type: working_doc
---

# second_pack - working doc

Plan: `.serena/memories/second_pack/plan.md`.

IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix. Report words: verified (the person ran it and confirmed), ran (executed with logs), built (compiles only).

## Log (newest first)

## 2026-11-26 - this bed after the work of `nature_pack` (ran)

Work done under `mem:nature_pack/plan` on two other packs closed what this bed still carried:
- the two prefabs with `materials: set differs` (`LightCeiling01_2On`, `Stairs01_350x700cm`): one material connected to a mesh through several slots is one material (`nature_pack` D.27). The bed's prefabs: 262 pass, 0 fail, 1 unmeasured.
- the two door signs of the club level, placed below an object of a placed door (`nature_pack` D.28). The level: 2023 of 2033 rows.
- Left: ten poles stretched by axis, whose root carries a capsule (`nature_pack` Q.6).
The Office bed is unchanged through all of it.

## 2026-11-26 - the person's second walk; I.5b, I.5c, I.6d, I.7d ran

The person walked the levels again: material overrides and imports work, the lights match their orientation (T.9, in part). Asked for: an option between turning a light's entity and a child entity; and reported a point light written as a sphere with its level overrides lost, and `DoorFrameLight04` with off-white blocks. Decisions D.27 to D.30.

### What landed
- `components/light.py`: the placement option and its predicate (`turns_its_entity`, `holds_only_a_light`), the point light as a simple point, `light_record`, `override_configuration`; the sphere shape is gone.
- `prefab_writer.py`: `with_light_turn`, `light_override_patches`, `overrides_a_light`; the entity map's `light_owners`. Both instance emitters and the scene's own objects use them.
- The stage's options reach the worker in one dict (`IntegratedAssetProcessor.options`, from `stage_runner.asset_stage_options`); the window has a check box for the light option.
- `asset_database.uv_transform` (D.30).
- Trace: an entity's `light_turn`. Report: `own_transform`, `without_light_turn`.
- Tests: `test_scene_fidelity` 23 -> 33. Changed: `test_rotation_map` (the directional light's fixture has an entity id and an object).

### Cycles
- Tirgames, cycle 6 (lights, tiling): 260 pass, 2 fail, 1 unmeasured; the level 2021 of 2033; 0 failed jobs; "no change".

### Findings worth keeping
- D.25 was written from the property names, without the engine's transform in hand, and was wrong for every tiled material. A mapping stated "by construction" has to be read off the engine's code, not off the names of its properties.
- `DoorFrameLight04` is plain URP Lit (the shader's guid), whose every map follows the base map's tiling; the scales its other maps store are leftovers.

## 2026-11-26 - plan change; I.3e, I.5, I.6, I.7 ran

The person walked the two formed levels and listed what was wrong; the plan took their list in (stages I.5 to I.7, decisions D.16 to D.26, proofs T.8 and T.9). Asked whether assets are adjusted by hand to reach parity: no, everything in the converted output is the converter's (D.16).

### What landed
- New: `targets/o3de/texture_settings.py`.
- Lights and colliders: `components/light.py` (spot on a child entity, Explicit attenuation), `components/mesh_collider.py` (no debug draw).
- Overrides and active state: `GameObject.component_ids`, `is_active`; `prefab_writer.material_override_patches`, `inactive_objects`, `mark_inactive`, `active_state_patches`; the entity map's `renderer_owners`, `parents`, `inactive`, `extra_entities`; `IntegratedAssetProcessor.material_hint_for`; the scene stage converts override materials through its Stage 1 worker.
- Materials: `asset_database.py` (opacity rules, emission, tiling), `_process_channel_texture` (roughness and occlusion as grey images), opacity texture settings written from `_process_material`.
- Mesh stretch: `assetinfo_writer.source_mesh_stretch`, `prefab_writer.with_mesh_stretch`, the box collider's `on_object`, the entity map's `root_mesh_stretch`; report: `without_mesh_stretch`, `prefab_root_trace`.
- Tests, new: `test_scene_fidelity` (23), `test_active_state` (9), `test_mesh_stretch` (8). Suite: 53 of 54 modules; `test_terrain_data.py` as before.

### Cycles
- Tirgames, cycle 4 (everything above but emission and tiling): prefabs 260 pass, 2 fail, 1 unmeasured; meshes 344 of 344; colliders 322 pass, 1 unmeasured; transforms 439; the level 2021 of 2033 rows; 0 failed jobs; against the previous run 21 fixed, 0 regressions.
- Tirgames, cycle 5 (with emission and tiling): the same numbers, "no change"; 0 failed jobs. What fails: 2 material rows (Q.6); in the level 10 `StripPole01` placements (a stretch on a root that carries a capsule) and 2 signs parented to an object inside another placed prefab.
- Office, with everything: 221 pass, 1 unmeasured, Showcase 223 of 223, "no change"; 0 failed jobs.
- Conversions: `GentlemensClubScene` 1123 of 1123 material overrides placed, 295 entities switched off, 72 stretched placements; `OfficePack_Example` 1680 entities, 1507 placements, 267 of 267 material overrides, 29 of 30 active-state overrides (the one left switches on what is already on).
- Converted materials of the two packs: 261, of which 16 blend, 3 are cut out, 43 glow, 5 tile, 207 carry a roughness image and 132 an occlusion image.
- The harness measures none of I.5 to I.7: no row compares a light's direction, a material's properties or what is hidden. Those stand on unit tests and on T.9.

### Fixes
- F.3 Four patch scripts stopped half way on an anchor that did not match (indentation changed by the earlier extraction of `convert_assets_of`; a blank line with spaces). Each edit function checks before it writes, so no file was left half edited; the scripts were made to skip what was already applied and run again.
- F.4 `test_collision_stamping` uses an object stub without `component_data`: the box writer reads the mesh stretch with a default.

### Findings worth keeping
- The engine's cutout discards below `1 - opacity.factor`, not below the factor.
- O3DE's roughness, metallic and occlusion inputs all read the red channel.
- The person's hand-tuned mirror (roughness lower 1, upper 0.1) was an inversion of the wrong channel, not the wanted mapping: with the roughness texture right the bounds are `1 - smoothness` to 1.
- Two materials of one name inside a model cannot be told apart by label in O3DE (Q.6).

## 2026-11-25 - I.1 ran; I.2a, I.2b, I.3a to I.3d, I.3g ran

### What landed
- Harness: a bed's own run folder (`work`); `parity/configs/tirgames.json` and `tirgames.u2oproj.json`; `Truth.mesh_compression`, `truth_quantum_mm`, `instance_roots`, the lighting row's one-colour mode.
- Converter:
  - `IntegratedAssetProcessor.convert_assets_of` (taken out of `process_prefab`), `model_objects_for` (was private);
  - `stage_runner.asset_stage_arguments`, the scene stage's Stage 1 worker, guid mappings from Stage 1's records; the CLI and the GUI pass the asset stage;
  - `scene_converter.py`: own objects' assets, model instances, `UNIFORM_SCALE`;
  - `prefab.add_model_instance` takes a log; `GameObject.model_children`;
  - `assetinfo_writer.source_import_scale`, `import_scale`; `ModelMeta.global_scale`;
  - `prefab_writer.UNIFORM_SCALE`, the entity map's `root_refuses_non_uniform_scale`;
  - `box_collider.needs_own_entity`, `own_entity_placement`, `refuses_non_uniform_scale`; capsule and sphere processors use them.
- Tests, new: `test_parity_beds` (3), `test_scene_objects` (8), `test_collider_placement` (12). Changed: `test_import_rule` (14), `test_instance_overrides` (13), `test_parity_compare` (46), `test_conversion_trace`.

### Cycles of the Tirgames bed
| Cycle | In it | Prefabs pass / fail | Level rows pass | Notes |
|---|---|---|---|---|
| baseline | the converter as committed | 145 / 117 | 1220 of 2033 (694 not placed) | 44 clusters; the level's job fails |
| 2 | I.2b, I.3a | 221 / 41 | 1853 | 119 fixed, 0 regressions |
| 3 | + I.3b, I.3c, I.3d | 250 / 12 | 2021 | failed jobs 0; 4 clusters left |

The Office bed after I.2a: unchanged (221 pass, 1 unmeasured, Showcase 223 of 223, "no change").

### Fixes
- F.1 The comparison of cycle 3 crashed: `parity.py` loads `report` when the step starts and `records` at the start of the run, and the harness was edited in between. The probe data was whole; the comparison was run again alone. Do not edit `parity/*.py` while a cycle runs.
- F.2 A test fixture and a byte literal were broken by writing backslash escapes through a shell heredoc (three more times). Repaired with the Edit tool; `test_scene_objects` now builds its scaled instance from the fixture's own parameters.

### Findings worth keeping
- The Office pack had no uniform scale other than one, no geometric scaling, no renamed placement and no capsule off its axis: four defects in general code that only a second pack could show (D.9 to D.12).
- The scene stage's guid table existed and was never filled (D.9).
- Unity's High mesh compression is 10 bits over the mesh's largest extent; on large flat panels that is centimetres (D.13).

## 2026-11-25 - plan written

- The person passed T.10 and T.11 of `parity_fixes`, committed it, and asked for two things: objects of a scene that are not prefab instances, and the converter on a new pack, `Assets/TirgamesAssets`, with a conversion project of its own into the same O3DE project.
- `OfficePack_Example` was converted for the person to walk before this plan starts: 1653 entities, 1484 prefab placements, 0 failed jobs. It misses five things: `W_3x_Elevator_Door` four times and one unnamed instance (Q.4). First read as the model file instanced in the scene; wrong: they are the prefab `W_3x_Elevator` renamed in the scene (D.5, D.9).
- Survey of the new pack, by script over its files: in the plan's Design.
- Tracked `__pycache__` files (120) were taken out of the index and `.gitignore` now names `__pycache__/` at any depth; the old patterns matched one level only. Staged for the person's commit.
