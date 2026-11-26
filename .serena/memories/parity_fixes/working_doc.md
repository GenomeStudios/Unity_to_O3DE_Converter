---
name: parity-fixes-working-doc
description: Living log of the converter fixes driven by the parity baseline on the Office pack. Plan - parity-fixes-plan.
metadata:
  type: working_doc
---

# Parity fixes - working doc

Plan: `.serena/memories/parity_fixes/plan.md` (`mem:parity_fixes/plan`).

IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix.
Report words: verified (the person ran it and confirmed), ran (executed with logs), built (compiles only).

Numbers of each cycle are written as: prefabs pass / fail / unmatched / other; transforms pass / fail; meshes pass / fail / uncooked; colliders pass / fail; Showcase instances in place; failed prefab jobs.

Log, newest first.

## 2026-11-25 - I.4 to I.7 (ran)

### What landed
- Converter, new: `matrix3.py`; `platforms/unity/model_import.py`, `builtin_meshes.py`, `scene_lighting.py`.
- Converter, changed: `fbx_reader.py` (node tree, polygon materials); `integrated_asset_processor.py` (node from the mesh reference, groups by node and across prefabs, model objects for the parser, built-in cube; `build_fbx_node_paths` removed); `platforms/unity/prefab.py` (`add_model_instance`, `root_override_target`, `nested_prefabs_first`); `platforms/unity/scene_converter.py` (root overrides only, child patches, non-uniform scale, Gradient GI entity); `targets/o3de/prefab_writer.py` (`non_uniform_scale_component`, `gradient_gi_component`, `child_transform_patches`, `instance_non_uniform_scale_patches`, every entity written with a `Translate`, the entity map's `transform_owners`); `targets/o3de/assetinfo_writer.py` (unselect every other mesh node, the top node from the path, a collision group always with its rule); `platforms/unity/components/box_collider.py` (`box_dimensions`); `stage_runner.py` (nested prefabs first); `conversion_trace.py` (the scale's field name).
- Harness: `parity/report.py` (`placement_verdict`, the join through a flattened instance, Unity's default material, the lighting row), `parity/compare.py` (the fit's axis, `spread_about_axis`), `parity/o3de/session.py` and `parity/parity.py` (a scene probe reads the Gradient GI component back).
- Tests, new: `test_fbx_node_tree` (8), `test_model_import` (23), `test_instance_overrides` (12), `test_builtin_meshes` (5), `test_non_uniform_scale` (7), `test_scene_lighting` (9). Changed: `test_parity_compare` (43), `test_assetinfo_writer`, `test_conversion_trace`.
- Docs: README architecture list, three vocabulary rows in `AGENTICS_GUIDELINES.md`, `mem:project/converter_working_status`.

### Cycles
| Cycle | In it | Prefabs pass / fail / other | Notes |
|---|---|---|---|
| 3 | I.4a, I.4b | 207 / 14 / 1 unmeasured | failed prefab jobs 5 -> 0; 22 fixed, 0 regressions |
| 4 | + I.4c, I.4d, I.5a, I.6a | 212 / 9 / 1 | Showcase 222 of 222; the cube's model empty (F.2) |
| 5 | + I.5b, I.6b, D.24, I.7a | 221 / 0 / 1 | 0 clusters; 24 fixed, 0 regressions |
| probe + compare | + I.7b | 221 / 0 / 1 | Showcase 223 of 223 with the lighting row |

Suite: 47 of 48 modules green; `test_terrain_data.py` fails two tests as before this plan.

### Proofs
- T.12 ran, offline: `C:/Users/gaian/AppData/Local/Temp/claude/8ee8bb45496eb813/055ed084-5223-4cce-935c-8c8863e1c606/scratchpad/model_validate.py` (the scratchpad does not outlive the session; the unit tests carry the same rules on synthetic files).
- T.7, T.8, T.9 ran: see the cycles.
- T.10, T.11: the person's.

### Fixes
- F.2 The written cube cooked to an empty model ("No valid ModelLodAssets"). Cause: an OBJ's top node is named after the file (`UnityBuiltin_Cube_obj`), and the group selected `RootNode`. Fix: `builtin_mesh_node_path`; the writer takes the top node from the path.
- F.3 Two harness verdicts failed meshes that sit within a tenth of a millimetre (`Pencil`, `Sign_exitway_ceilingpart`): the fitted turn of a thin mesh is noise about its own length. Fix: D.24, the allowance at the reach from the turn's axis.
- F.4 A test fixture written through a shell heredoc lost its `\n` escapes twice. Text with backslashes goes through the Write or Edit tool, not through a heredoc.

### Findings worth keeping
- A collision group without an advanced coordinate rule is not "no rule": the engine bakes the node's world transform (D.22).
- A selection that names no existing node does not select nothing: with `RootNode` selected, every unnamed node follows it and the group holds the whole file (D.16).
- The log lines about negative box dimensions came from five Unity colliders, not from Transform 2 (D.21).

## 2026-11-25 - I.3 mesh import rule (ran)

### What landed
- `fbx_reader.py`: `read_records`, `properties70`, `object_name`, `read_import_facts` (up axis, unit, each node's geometric transform). `conversion_trace.py` uses it.
- `targets/o3de/assetinfo_writer.py`: `source_import_rule(facts, node)` = `U * G * K`; the user's `default_rotation` and `default_position` are applied after it; collision groups get their own node's rule; small pure-Python matrix helpers (the converter has no numpy).
- `integrated_asset_processor.py`: removed `read_fbx_geometry_bbox_centers`, `compute_single_mesh_autocenter`, `compute_node_autocenters`, `compute_node_bbox_centers`, `compute_collider_alignment` and the alignment of dedicated collider files; the mesh state's `auto_flags` come from the file's rule.
- `main_app.py`: the two Mesh tab labels and one tooltip. `converter_cli.py`: D.15.
- Tests: `tests/unit/test_import_rule.py` (9, models both importers); `test_assetinfo_writer.py` and `test_fbx_node_transforms.py` rewritten where they encoded the heuristics (4 heuristic tests removed).

### Verification
- T.5 ran: D.12, with these numbers. Needed rule per model computed from report and trace; hypothesis search over `K1 * X * K2` with X among the node's transforms: `U * geometric * U` matches 106 of 127 Y-up models and `U * geometric * (half turn Z)` 105 of 120 Z-up models on rule parameters (symmetric meshes fit in more than one way); applied to the vertices offline, 230 of 255 fit at 1 mm and 0.1 degree.
- T.6 ran. Suite 41 of 42 modules green. Cycle (209 s): 184 / 31 / 5 / 1 uncooked, 1 unmeasured; transforms 379 / 8; meshes 327 / 39 / 1; colliders 658 / 24; Showcase 220 of 222; 5 failed prefab jobs. Difference: 310 fixed, 0 regressions, 53 clusters closed, 7 opened.
- Desk_metal: drawer C's rule is the identity turn with translation (0.014, -0.4502, -0.8081) m, the value the baseline's residual asked for; the frame's rule is empty.

### The 39 meshes still failing after the rule
- 16 within Unity's rounding: offsets of 1.0 to 3.2 mm (8.8 mm on the 55 m `BG_Building`) where the per-vertex noise is 1.2 to 35 mm; three thin meshes 0.14 to 0.37 degrees. Handled by D.13.
- 12 in multi-mesh files whose model holds the wrong nodes: `Lockers` (every entity shows one 2487-vertex model), `Lamp_spot`, the elevator doors (72 vertices for a 40-vertex door). I.4.
- 10 where the converter emitted no model: the StairsMod `Cube` renderers (a Unity built-in mesh) and `ElevatorDoor_L`. I.4.
- 1 not produced: `Bookshelf_A`. I.4.

### Fixes
- F.1 `test_material_opacity_mode.py` failed only inside the whole suite. Cause: a CLI test ran with `--seed` in-process and left the seeded `uuid4` installed. Fix: D.15.

## 2026-11-25 - I.1 rotation map and I.2 prefab names (ran)

### What landed
- `targets/o3de/prefab_writer.py`: `convert_to_o3de_coordinates` maps a rotation to `(-x, -z, -y, w)`; `quaternion_to_euler` extracts the angles the engine reads back (`rotx * roty * rotz`); a nested instance's `Source` is the converted prefab's project path.
- `platforms/unity/unity_platform.py`: the plugin's copy of the map. `platforms/unity/scene_converter.py`: its Euler conversion is the writer's. `platforms/unity/components/light.py`: no pitch patch.
- `parity/report.py`: scene objects that are not prefab instances are compared.
- Tests: `tests/unit/test_rotation_map.py` (9), `tests/unit/test_prefab_source_name.py` (3); `test_platform_contract.py` expected the old swizzle and was corrected.

### Verification
- T.1 ran, T.3 ran. Suite: 40 of 41 modules green (`test_terrain_data.py` as before).
- T.2 and T.4 ran, one cycle (195 s): 13 / 203 / 5 / 1; transforms 379 / 8; meshes 27 / 339 / 1; colliders 648 / 34; Showcase 220 of 222 rows (the two left: a cube with a lost non-uniform scale, a door 17.7 m off); 5 failed prefab jobs, none on the source name.
- Difference from the baseline: 59 fixed, 1 regression (D.10), 16 clusters closed, 5 opened.
- The Showcase light: transform passes, rotation 0.000 degrees off Unity's (it was 50.6).

### What is left of transforms
- 7 objects with a lost non-uniform scale (I.5); `Cell/Door_Cell` 1.67 m off (I.4).

### Collider clusters now (34 elements)
- Mesh colliders: 6 shifted, 4 `rot Z 180 + shift`, 1 `rot X -90`, 1 `rot Z -90` (follow the mesh rule, I.3); 10 with no shape (StairsMod, I.4).
- Box colliders: 7 unexplained (StairsMod ramps: scale lost, I.5), 5 with no shape (Paper_A and others).

## 2026-11-25 - Plan written

### State
- Baseline: 13 / 203 / 5 / 1 unmeasured; transforms 355 / 32; meshes 28 / 338 / 1; colliders 613 / 69; Showcase 212 of 217; 5 failed prefab jobs.
- The person asked for the next plans to be implemented, machine free (D.4), and added: check that the directional light no longer shines from below; a Gradient GI component can carry Unity's three ambient colours (D.8).

### Verification
- Light check on the existing records (D.7): Unity's light shines along (0.175, -0.303, -0.937) in O3DE axes; the converted one along (-0.175, 0.473, -0.863). Downward, 50.6 degrees off.
- Unity `Showcase` RenderSettings: sky (0.212, 0.227, 0.259), equator (0.114, 0.125, 0.133), ground (0.047, 0.043, 0.035), ambient mode 0.

### Open follow-ups
- Next pivot: I.1.
