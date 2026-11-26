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
