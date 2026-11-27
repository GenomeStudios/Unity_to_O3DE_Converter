---
name: nature-pack-working-doc
description: Working doc of the nature_pack plan - the log of its increments, proofs and fixes, newest first.
metadata:
  type: working_doc
---

# nature_pack - working doc

Plan: `.serena/memories/nature_pack/plan.md`.

IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix. Report words: verified (the person ran it and confirmed), ran (executed with logs), built (compiles only).

## Log (newest first)

## 2026-11-26 - the person back: the NatureManufacture levels did not open (F.10)

The person reported that the pack's scenes could not be loaded "due to unexpected characters".

- F.10 Symptom: the Editor's Open Level dialog refused all four levels of the pack. Cause: their paths held spaces (`Advanced Rock Pack/Demo and Maps/Overview Map`); the dialog's name field takes letters, digits, `_`, `-`, `.` and `/` only, and is checked on Open (plan D.6, corrected). Fix: `stage_runner.level_name_part`, `level_name_for` and `level_names_for`; the level's file named after its folder; `parity.Bed.level_name` and the probe step follow. Ran: 13 unit tests (`test_output_layout`, three new), suite 66 of 66.
- The four scenes were converted again (scene stage alone, from the last run's bookkeeping) while the person's Editor and Asset Processor were open; the Asset Processor cooked the four renamed levels and dropped the old products. The old level folders, which held nothing but the superseded files, were removed.
- Not run: a harness cycle of the bed (it refuses while the Editor is open). The bed's bookkeeping and its last report still name the levels as they were; the next cycle converts and measures under the new names.
- Why the harness missed it: it opens a level by script, which the dialog's rule does not bind. Worth a check of its own in the harness: every level path against the dialog's pattern.

## 2026-11-26 - the unattended run: I.4g to I.4k, I.5, I.6, I.7 ran

The person was away. Three more chains of all five beds ran after the baseline entry below; nothing was committed anywhere.

### What landed (decisions D.20 to D.33 of the plan)
- Converter, new modules: `platforms/unity/scale_carry.py` (D.22), `fbx_material_names.py` (D.27).
- Converter, changed:
  - `platforms/unity/builtin_meshes.py` written anew: the six meshes as sheets over a surface, through `mesh_asset.write_obj` (which takes an object name and labels now); `IntegratedAssetProcessor._builtin_mesh_model`, `_builtin_collision_hint` (D.24);
  - `components/box_collider.py`: `object_scale`, `scale_component`, a box's own entity on a mirrored object, the centre's sign in `own_entity_placement`; `mesh_collider.py` (D.25);
  - `platforms/unity/prefab.py`: `component_ranks`, `in_unity_order` (D.26), `lost_root` (D.30), the scale carry after the LOD strip, a model part's renderer in `add_model_instance`;
  - `fbx_reader.read_import_facts`: materials by object, `material_ids` (D.27);
  - `platforms/unity/scene_converter.py`: `stripped_transforms`, `_hang_below_placements`, `_create_objects_below_placement` (D.28), `_drop_lost_root_overrides` (D.30), components in Unity's order;
  - `platforms/unity/model_import.py`: `import_scale` (D.20), `hashed_object_ids`, `hashed_renderer_id` (D.29);
  - `targets/o3de/prefab_writer.py`: `mesh_override_patches` (D.21), `inherited_scale` in `instance_scale_patches` (D.22), the entity map's `mesh_owners`, `root_position`, `root_rotation`;
  - `platforms/unity/terrain_data.py`: `read_terrain_layer`, `terrain_layer_files`, the one resolution (D.33).
- Harness: `ParityProbe.cpp` `FileKey` (D.23); `report.o3de_shapes` by entity number, the lost prefab's row (D.31); `unity_bridge.scope_state` and the changed files (D.32).
- Tests, new: `test_scale_carry` (12), `test_collider_scale` (6), `test_component_order` (4), `test_fbx_material_names` (9), `test_scene_children` (9), `test_lost_root` (6). Written anew: `test_builtin_meshes` (15). Changed: `test_model_import`, `test_unity_bridge`, `test_terrain_data`, `test_non_uniform_scale`. Suite: every module passes.

### Cycles (prefabs: pass / LODs dropped / fail / unmatched / unmeasured)
| Bed | Baseline | Chain 5 | Chain 6 | Chain 7 |
|---|---|---|---|---|
| NatureManufacture | 232 / 681 / 140 / 1 / 2 uncooked | 259 / 790 / 3 / 1 / 3 | 261 / 790 / 1 / 1 / 3 | 261 / 790 / 2 / 0 / 3 |
| Alchemist House | | 134 / - / 17 / 0 / 6 | 145 / - / 6 / 0 / 6 | 149 / - / 1 / 0 / 7 |
| Alien Fantasy Forest | | 2 / 82 / 0 / 0 / 1 | the same | the same; Demo1 7005 of 7005 |
| Office | 221 and 1 unmeasured | no change | no change | no change |
| Tirgames | 260 / - / 2 / 0 / 1 | no change | no change | 262 / - / 0 / 0 / 1; the club level 2023 of 2033 (2021 before) |

- Chain 5 measured D.20 to D.23; chain 6 added D.24 to D.26; chain 7 added D.27 to D.31. No chain reported a regression on a bed it did not set out to change.
- Chain 8, the last (D.29's renderer ids, D.32, D.33): NatureManufacture 262 / 790 / 1 / 0 / 3, "2 fixed"; the four other beds "no change".
- NatureManufacture's second failure in chain 7 is one that was hidden: the fire pit's two parts were not found before D.29, and once found showed no materials (their overrides name the parts' renderers). The renderer ids of D.29 followed; see the last chain's line in the plan.
- Alchemist House scenes: `Scene` 1079 of 1101 rows at the baseline (15 mirrored books: D.22; 7 objects below placed prefabs: D.28), 1101 of 1101 in chain 7.

### Fixes
- F.6 The scale carry called a mirror under a turned object a skew and left the object unmirrored. A mirror skews nothing; it is carried by turning the rotation over (D.22). Found on fifteen books of the Alchemist scene.
- F.7 The first renamer of materials renamed by object only; the real files have one material object connected through several slots. The reader was wrong, not the file: it listed a material once per slot (D.27). Found by trying the renamer on copies of the 561 real files before wiring it in.
- F.8 Unity rewrote two materials of the artificer project during the first truth dump (D.32). Seen in that project's `git status` hours later, not by the harness; put back with `git restore` after keeping Unity's versions in the session's scratch folder. The harness now names such files itself.
- F.9 Putting the two files back changed their times, so the next chain's truth step started Unity again (16 s). It left the files alone that time.

### Findings worth keeping
- A harness that pairs by position hides what it cannot pair: thirty-three box colliders "failed" in the Alchemist baseline because the converter numbered an object's colliders in the file's order and Unity in the list's (D.26), and three more because one collider had no shape (D.31). Neither was a wrong collider.
- An entity of a level can be parented to an entity inside a placed prefab by path, and the Editor loads it there (D.28): the probe found all nine such objects in place.
- PhysX refuses a box with a negative side without a word in the cook; the entity just has no collider (D.25).
- Unity's ids for the parts of a model without an id table are hashes of where the part sits, and can be worked out (D.29). The harness showed the gap only as "unmatched".
- Unity's built-in primitives exported from an empty project in two minutes of batch mode; the scratch project is not kept.
- A chain of all five beds takes about 55 minutes with everything cooked before; the first cook of a new pack adds its textures once.

## 2026-11-26 - baseline; I.3, I.4a to I.4d ran; two more packs added

The person left the machine to the work and added two packs of the artificer project (plan change; beds written: `alchemist`, `alienforest`).

### What landed
- Harness: `level_bake.cell_side`, `lay_out` (D.8, writer version 2); the trace's assetinfo records carry the file's path; the report finds a model file placed in a scene by the id Unity gives its root there (`instance_object_id`); `Bed.level_path`. The nature bed's levels moved under `Levels/NatureManufacture`.
- Converter:
  - `assetinfo_writer.lod_rule_of_one_level` (D.9); `components/material.py` asks for a mesh component (D.10); `is_greyscale_tga` and the PNG copy (D.11);
  - `fbx_reader.scene_node_name` (D.12);
  - the root's scale kept, `prefab_writer.overridden_root_scale`, `instance_scale_patches`, the entity map's `root_scale` (D.13);
  - `platforms/unity/mesh_asset.py`, `IntegratedAssetProcessor._is_mesh_asset`, `_mesh_asset_model` (D.14);
  - `platforms/unity/shader_source.py` (D.16; not yet used by the material conversion); the shader name read past a byte order mark.
- Tests, new: `test_cook_rules` (6), `test_mesh_asset` (7), `test_shader_source` (8), `test_root_scale` (10). Changed: `test_parity_compare` (cells by size), `test_fbx_node_tree`, `test_output_layout`. Suite: 58 of 59 modules; `test_terrain_data.py` as before.

### Cycles
- First conversion: 1056 of 1056 prefabs, 179 materials, 384 models, 4 scenes, 0 missing prefabs. First cook: 149 failed jobs (87 models, 54 prefabs, 8 textures).
- Baseline (after D.8 to D.11): in the plan. Cook 321 s for the whole project with every model cooked again; probe 81 s; comparison 225 s.
- Office and Tirgames after the new layout and the LOD rule: "no change" (221 pass and 1 unmeasured; 260 pass, 2 fail, 1 unmeasured; the club level 2021 of 2033).

### Fixes
- F.3 The first baked level of this bed was 53 km wide (D.8). Seen in the bake's own line before anything was measured in it; the cycle was stopped around the cook, which was left to finish.
- F.4 `test_output_layout` used prefabs that show a material without a mesh; with D.10 they show none. The tests now read the material's hint from the worker.
- F.5 `uv.center` of D.30 (`second_pack`) was written as a colour, `[1, 1, 1, 1]`, because the material writer took every list for one. Found by reading the written `DoorFrameLight04.material`, not by a test: the test read the parsed properties, not the file. A test now reads the file.

### Findings worth keeping
- The Asset Processor's batch log stops printing errors after a number of them ("Too Many Compile Errors"); the reason of a failed job is then only in `user/log/JobLogs/<source path>-*.log`.
- The Asset Processor writes its log itself: stopping the harness around it left the cook to finish and its log whole.
- Unity keeps a mesh asset's vertex data in the text file as hexadecimal; with one stream the stride is the data size over the vertex count, whatever the channels are.
- A whole cook of the three packs after every model's `.assetinfo` changed took five minutes: the first cook of a pack is not the slow part, textures are, and they are cooked once.

## 2026-11-26 - plan written; I.1a, I.2a, I.2b ran

The person asked for the NatureManufacture assets of AGURP2024 to be run through the converter, and for the output to keep the folder structure of a distributor's folder that holds several packs.

### What landed
- Bed: `parity/configs/nature.json`, `nature.u2oproj.json` (scope: the whole `NatureManufacture Assets` folder; four scenes; `mirror_source_folders` on).
- Bridge: `U2OTruthDump.cs` writes a mesh when first met (`RegisterMesh`), and the index at the end (`WriteMeshIndex`).
- Layout: `integrated_asset_processor.py` (`MIRROR_OPTION`, `mirrored_folder`, `output_folder`, `prefab_output_path`, `hint_folder`, `output_relative`; the worker's `options`); `prefab_writer.create_o3de_prefab` and `write_entity_map_sidecar` take the source prefab; a nested instance's `Source` from `prefab_output_path`.
- Scene stage: `PrefabDatabase.add_converted_prefab`, `prefab_key`, entity maps by file; `stage_runner.asset_stage_options`, `converted_prefab_dirs`, `level_name_for`; scene records keyed by level name.
- Project and window: `asset_processor.mirror_source_folders` in the defaults; the check box "Use the same folder structure as the source".
- Harness: `Bed.converted`, `Bed.level_name`, `Bed.label`; `level_bake.make_recipe` takes the prefabs' `Source` strings (`nested_source_folder` is gone); `records.file_name_of`, `Trace.assetinfo_writes`, `Trace.facts_of`; the report's `Cycle.cell_for`, `Cycle.scene_file`; the probe session opens a level by its path and waits for its own name; the trace names a model file by its guid.
- Tests, new: `test_output_layout` (10). Changed: `test_parity_compare` (the recipe by `Source` strings; two prefabs of one name get a cell each), `test_prefab_source_name`.

### Fixes
- F.1 The first truth dump failed after 12 s of work: `MissingReferenceException: The object of type 'UnityEngine.Mesh' has been destroyed`. Cause: the bridge collected every mesh and wrote them at the end; a mesh stored in a scene is destroyed when the next scene opens. Fix: write on first meeting (D.3). The script is part of a dump's fingerprint, so the two older beds dump again once.
- F.2 Two patch scripts stopped on an anchor (a blank line with trailing spaces; backslash escapes through a shell heredoc). Nothing was half written: each file is written after all its replacements matched.

### Findings worth keeping
- Unity 6 opens AGURP2024 headless as fast as 2021.3 opens the layover project. The project's `Temp` folder was a leftover, not a sign of an open Editor (no lock file).
- The engine opens a level below folders of `Levels` by its path (`Pack/Demo Scenes/Overview`), and `get_current_level_name` then answers with the last part only.
