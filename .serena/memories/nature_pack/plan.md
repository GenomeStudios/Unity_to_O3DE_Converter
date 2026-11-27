---
name: nature-pack-plan
description: PIT plan for the converter's third asset pack - the NatureManufacture assets of the AGURP2024 Unity project (Unity 6, organic, LOD groups, the distributor's own shaders), measured by the parity harness - and for converted output that keeps the source's folder structure.
metadata:
  type: plan
---

Feature: `nature_pack`. Working doc: `.serena/memories/nature_pack/working_doc.md`. IDs: P plan, D decision, Q open question, I stage (increments I.na), T proof, F fix.

Starts from `mem:second_pack/plan` (the second bed, what a scene holds, the material mapping) and `mem:parity_harness/record` (how the harness works). The pack's collision and LOD conventions: `mem:asset_packs/import_catalogue`. Machine facts: `mem:parity_harness/environment`.

## P - Deliverable
The person asked on 2026-11-26 to run a new, very organic pack through the converter and see how close it gets, and raised that a distributor's folder holding several packs should keep its structure in the output.

- The NatureManufacture assets (`D:/OffLocalDev/AGURP2024/Assets/NatureManufacture Assets`) convert into the test project in the source's own folder structure, and have a parity report on a third bed: every element passes at the agreed tolerance (1 mm, 0.1 degree, 1 mm), or the report says why it cannot and the reason is carried here.
- The converter has an option to keep the source's folders in its output, off by default, with the flat layout unchanged.
- The pack's overview scenes are levels the person can walk.
- Nothing regresses on the Office and Tirgames beds.

For: the person. The three beds' reports are the evidence.

Plan change, 2026-11-26 (the person, leaving the machine to the work): once this pack has settled, two more are to be processed the same way, from the artificer Unity project (Unity 6000.3, URP 17) - `Assets/BK_AlchemistHouse` and `Assets/Alien Fantasy Forest` - "to uproot every possible quandary in how asset packs implement their work and be able to resolve all of them when importing into O3DE". They are stages I.6 and I.7 of this plan, each with a bed of its own.

Out of scope until the person asks: terrain and what is painted on it (trees, details), Vegetation Studio, particle systems (the Fire and Smoke pack), wind, the river and spline tools, baked lighting. The large demo scenes (6091 to 11754 placements on a terrain) are converted for walking, not measured.

## Design
- Third bed beside the two others in `D:/OffLocalDev/xxxxxDelete/ConverterTest`: `parity/configs/nature.json`, conversion project `nature.u2oproj.json`, output `Assets/NatureManufacture`, measurement level `Bench_Parity_Nature`, run folder `user/Parity_Nature`.
- The Unity side is another project and another Editor: AGURP2024 on Unity 6000.0.32f1 with URP 17 (the two other beds: 2021.3.14f1).
- Survey of the pack (2026-11-26, by script over its files): 12 GB; 1056 prefabs, 433 models, 443 materials, 1297 textures, 14 scenes, 56 shader files of the distributor.

| Folder | Prefabs | Models | Materials | Scenes |
|---|---|---|---|---|
| Advanced Rock Pack | 232 | 17 | 110 | 2 |
| Forest Environment Dynamic Nature | 302 | 191 | 97 | 3 |
| Meadow Environment Dynamic Nature | 436 | 219 | 85 | 4 |
| Fire and Smoke Particles | 68 | 3 | 68 | 5 |
| River Auto Material | 16 | 3 | 79 | 0 |
| Foliage, Object and Particle Shaders, Wind, Tools, Snow, Spline | 2 | 0 | 4 | 0 |

- File names repeat across the packs: 21 prefab names (42 files), 12 model names (24), 4 material names (8), 152 texture names (449). One folder per kind of asset would lay them over one another.
- From the import catalogue: 853 of the prefabs carry a LOD group; 607 non-convex mesh colliders, whose mesh is usually the LOD0 sub-mesh of the render model.
- Scenes of the bed: the three one-by-one overviews (`Overview Map` 133 placements, Forest `Overview Scene` 255, Meadow `Overview Scene` 224) and the small formed level `Small Demo Map` (33 placements and a terrain). Two of them share a file name.

## D - Decisions
- D.1 A plan of its own. `second_pack` put a third pack out of scope; this pack brings its own subjects (LOD groups, the distributor's shaders, repeated names, another Unity version).
- D.2 The truth comes from AGURP2024 itself. The Editor of its version is installed; it opens the project headless in 111 s the first time and 32 s after. The bridge adds `Assets/_U2OTruth/Editor` and lists it in the clone's own ignore file; `git status` there is the same before and after (three files the person had changed). The project is a working game project with a remote: nothing is committed there.
- D.3 The bridge writes a mesh when it first meets it. It kept every mesh for the end of the run; a mesh that lives in a scene (not in an asset) is destroyed when the scene is left, and the run failed on the first such mesh (F.1).
- D.4 Output in the source's folders is an option of the asset stage, `mirror_source_folders`, off by default; the window calls it "Use the same folder structure as the source".
  - On: a converted asset goes where its source lies below the source root (`IntegratedAssetProcessor.output_folder`); a derived texture beside the texture it is made from; a level below its scene's folders (`stage_runner.level_name_for`), opened by that path. What lies outside the source root goes under `_OutsideSource`, by its folder below the Unity project's `Assets`. What has no source file (a built-in mesh) keeps its folder by kind.
  - Off: the flat layout, as before. The two older beds stay on it, so their levels and baselines are untouched.
  - Every emitter asks one place where a file goes, and every hint is taken from the file it names (`hint_folder`), so the two layouts differ in that place only.
- D.5 An asset is known by its guid and its place, never by its file name. Found while making D.4 work; each was a silent wrong answer waiting for a repeated name:
  - the entity map looked its Unity prefab up by the output file's name (the first prefab of that name won);
  - the scene stage found a converted prefab by name, and its entity map by name;
  - the harness laid its measurement level out by prefab name, and joined cooked models, level cells and scenes by name.
  The writer is now told the source prefab; the scene stage is given each converted prefab by guid with its file (`PrefabDatabase.add_converted_prefab`), and entity maps by file; the harness reads what the last convert run wrote, by guid (`Bed.converted`), and names a model file by its guid in the trace. The report calls a prefab by its path below the scope in a mirrored bed, by its name in a flat one.
- D.6 A level's name is its scene's own, spaces kept: the engine refuses only characters a file system refuses (`CLevelFileDialog::ValidateSaveLevelPath`, `AZ::StringFunc::Path::IsValid`). The harness's own run folders may not hold a space (the Editor splits its script's arguments there), so they use the name with other characters replaced.
- D.7 A failed Asset Processor job is still joined to its row by file name. With a repeated name the note lands on both rows; it changes no verdict. Carried.
- D.8 The measurement level gives each prefab a cell of its own size, in rings around the origin with the smallest inside (`level_bake.lay_out`). One spacing for all, set by the largest prefab, put this pack's level 26 km from the origin: six background hills of 800 m among a thousand prefabs under 27 m. The Editor holds positions as 32-bit numbers, 2 mm apart that far out, which is more than the tolerance. Now the ordinary prefabs lie within 420 m and the hills one cell out (2048 m). The two older beds were baked anew and measure as before.
- D.9 A model holds exactly the nodes its group selects, as one level of detail. Read from the engine: without being told otherwise it files every node of the file called `..._LOD1` under level 1 of every model of that file, `..._LOD2` under level 2, and so on (`LodRuleBehavior::UpdateLodRules` adds each level a group's LOD rule does not hold yet), whatever the group selects. So
  - a model made of a node called `..._LOD1` had nothing at its top level and its job failed (87 model files: "Size of the buffer in the descriptor was 0");
  - a file holding two objects with levels of detail would get both objects' lower levels in each model;
  - a file whose nodes follow the naming got the engine's own LOD switching, unasked, although the asset stage says it keeps one level.
  Every visual group's LOD rule is now written with all five levels, each selecting nothing (`assetinfo_writer.lod_rule_of_one_level`); a rule that holds every level is left as written. The levels of Unity's LOD group would go into those lists (Q.1).
- D.10 An entity gets a material component only beside a mesh component. The engine refuses the entity otherwise, and the whole prefab's job fails with it (54 prefabs, and with them all four levels). An object whose model cannot be emitted shows nothing; an override of its materials is reported as not placed.
- D.11 A greyscale TGA is written as a PNG of the same name. The engine's TGA loader reads true-colour and colour-mapped files only (`TgaLoader.cpp`: "unsupported type code"); 8 height maps of the pack.
- D.12 A node's name in a path is the name O3DE's scene graph gives it: every dot an underscore (`RenamedNodesMap::SanitizeNodeName`; Blender's `leaf.002`). Named by its own spelling the node was not found and the model came out empty (1 file). A name repeated under one parent is also renumbered by the importer; that is not followed.
- D.13 A prefab root keeps its own scale; where it stands is left to whoever places it. Unity stores a placement's position and rotation always, its scale only when the placement changes it, axis by axis. The converter left the root's whole transform out, so the 79 prefabs saved at another scale than one (a rock at twice its model's size) came out at their model's size, in the measurement level and in every scene. Now
  - the root entity carries the root's scale (`create_entity_recursive`); the entity map keeps it as Unity stores it (`root_scale`);
  - a placement that sets no scale writes none; one that does replaces the root entity's scale with the result, an axis it does not name taken from the prefab (`prefab_writer.instance_scale_patches`). The container entity carries no scale any more: it would multiply with the root's, where Unity replaces.
- D.14 A mesh stored on its own in a Unity `.asset` file is read and written out as an OBJ (`platforms/unity/mesh_asset.py`): 19 trees of the pack take their best level of detail from one (50 prefabs with their variants). Read: the text form, uncompressed, one vertex stream - positions, normals, the first UV set, each sub-mesh's triangles; both channel layouts Unity has used. The reader agrees with Unity's own dump on all 92 meshes it could be checked against (no difference in any coordinate, the same triangles). The OBJ is written in O3DE's space with each triangle's corners turned around; a sub-mesh is a material slot, labelled `SubMesh<n>`. Not carried: vertex colours and further UV sets (the pack's wind data), and a collider that names such a mesh.
- D.15 The engine reads an OBJ as Y up and right-handed: a file point `(x, y, z)` ends up at the engine's `(-x, z, y)`. The file therefore holds Unity's coordinates with X mirrored, each triangle's corners in reverse. First stated from the engine's source as "taken as they are, Z up" (`GetUpVectorAndSign` answers Z without an axis in the file); the bed's mesh rows said otherwise - all 49 such models turned half round about the diagonal of Y and Z - and the measurement stands. The source tree read is not the SDK that cooks.
- D.16 What a shader file says counts before what a material stores (`platforms/unity/shader_source.py`). A material keeps the properties of every shader it ever had; the shader's `Properties` block says which it reads, its lit pass which faces it draws and whether it always cuts by alpha. All 55 shader files of the pack read in half a second. The name of a shader file is read past a byte order mark: behind one it was not found, and 142 of the pack's 179 converted materials went through the conversion unnamed.
- D.17 A material of a shader that ships its source is read by that source (uses D.16; `asset_database.live_properties` and the section above the class):
  - only the properties the shader declares are read. The pack's materials store what earlier shaders left: a rock with `_AlphaClip: 1` and `_Cutoff: 0.5` from a time as a URP Lit material, on a shader that cuts at `_AlphaCutoff: 0`, which is not at all;
  - a packed texture is taken apart by the shader's own label for it ("Base Mask Map MT(R) AO(G) H(B) SM(A)", "Metalic (R) Ambient Occlusion (G) Smoothness (A)", "AO (G) Sm (A)"; `shader_source.packed_channels`). Each value gets a grey image of its channel, as O3DE reads every such value from red (`second_pack` D.23). A property called a mask map without such a label is Unity's own (metallic, occlusion, detail, smoothness). Of two layers the first declared is taken; a detail map is not;
  - the first layer's numbers, by the names packs give them: a metallic scale (at zero the surface is no metal whatever the texture holds), smoothness and occlusion remaps (roughness bounds `1 - max` to `1 - min`; occlusion strength `1 - min`), a normal scale, a base colour, tiling and offset kept in one vector;
  - cut by alpha when the shader always cuts or its keyword is set, at the threshold property the shader declares; a shader that cuts at a threshold it does not declare (the pack's bark) is left opaque;
  - both faces show when the lit pass culls nothing, or takes its culling from a property the material sets to off (`general.doubleSided`). For one of Unity's own shaders that is its `_Cull`.
  A shader file that declares no property says nothing, and its materials are read as before. A material of one of Unity's own shaders, or of a Shader Graph kept as a graph, is read as before too: the two older beds are untouched by this.
  Not carried, and listed so: a second layer (cover, snow, bark over trunk, detail), a leaf's translucency (`_ThicknessMap`), wind, colour variation between a healthy and a dry colour (the healthy one is the base colour), and every water, particle and debug shader.
- D.18 A mesh without vertices is no mesh. One model of the pack holds one (`flower_sunroot_01_detailed_1.002`), and a prefab shows it; Unity draws nothing, the engine fails the whole file over a model made of it. The file reader counts no vertices and the node carries no mesh; the id Unity gives it names no node (it was taken for the next node by its position); the report measures nothing for it.
- D.19 An object of a scene that names a parent which does not list it is added to that parent (`scene_converter._build_hierarchy`, as the prefab parser already did). The meadow overview groups 70 model files placed straight in the scene under objects; each group lists a placement by a transform id of the scene's own, so the model's objects were neither roots nor anyone's children and were never written.
- D.20 A model whose importer has "Convert Units" off is taken at one file unit to the metre, times the importer's scale (`model_import.import_scale`). Two wet river stones came out a hundredth of their size.
- D.21 A placement that gives an object of its prefab another mesh is followed (`m_Mesh` on a MeshFilter: how a prefab variant swaps a model). The entity map lists each filter's object (`mesh_owners`); the placement patches that entity's model, converting the file if this run has not yet (`prefab_writer.mesh_override_patches`, `IntegratedAssetProcessor.model_hint_for`). Six grass variants.
- D.22 A scale that differs by axis is carried down to what hangs below it, before anything is written (`platforms/unity/scale_carry.py`). O3DE passes a uniform scale down and nothing else. A scale by axis is two things:
  - a mirror (the signs): the object below is turned over and mirrored along the same axes of its own (`M R = (M R M) M`). Exact however the object is turned;
  - a stretch (the magnitudes): along each of the object's own axes, by the length that axis has once scaled. Exact for an object turned by quarter turns; one turned otherwise would be skewed, which no entity can hold: it gets the right place and its size along its own axes, and is reported.
  A placed prefab below gets its place scaled and is told what it inherits (`inherited_scale`), which `instance_scale_patches` multiplies into its root's scale. Not carried: into the objects below the root of a placed prefab that is itself stretched by axis (Q.6).
- D.23 The probe names a model's file by a hash of its hint and the last 64 characters (`FileKey`). With mirrored folders a hint made a path Windows refused (10 write errors).
- D.24 All six of Unity's built-in meshes are written (`platforms/unity/builtin_meshes.py`), each made in Unity's space and written through the one OBJ writer.
  - Quad, Plane, Cube, Cylinder: Unity's own vertices, normals and texture coordinates, made by rule. Checked against the meshes Unity 2021.3 hands out, exported once from an empty scratch project: no difference in any position; the cylinder's side shows its texture twice around, as Unity's does.
  - Sphere, Capsule: the same size and lay of the texture on the converter's own grid. Unity's two are smoothed cubes whose vertices follow no rule; point for point they could only be copied from Unity's data, which the converter does not ship (Q.5).
  - A mesh collider on a built-in mesh collides with the written mesh; a quad or a plane is never a convex hull.
- D.25 A collider and its object's scale by axis (`components/box_collider.py`):
  - PhysX takes no box with a negative side, so a box on a mirrored entity left it without a collider. It gets an entity of its own without the mirror; the mirror goes into where the box's centre lies. A round collider's centre keeps its sign as well.
  - A second collider of an object sits on an entity of its own below the object's, which the engine hands nothing of the scale by axis: it carries the same scale itself (boxes and mesh colliders).
- D.26 An object's components are taken in the order of its `m_Component` list, not of the file (`prefab.in_unity_order`). Unity goes by the list; so which collider is an object's first, and sits on its own entity, is now Unity's.
- D.27 The materials of a model, by object and by name:
  - one material connected to a mesh through several slots is one material, listed once (`fbx_reader.read_import_facts`, with `material_ids`). Unity makes one sub-mesh of it and so does O3DE. Listed once per slot, a renderer's materials were paired with the wrong names (a cupboard: twelve slots used, five materials);
  - two materials of one name on one mesh are two slots in Unity and one in O3DE, which knows a material by its name (`AssImpMaterialWrapper::GetUniqueId`). In the converted copy of the model the later ones are renamed `Name (2)` (`fbx_material_names.py`). The file is rewritten record by record with nothing else decoded; it must first write back byte for byte unchanged (561 of 561 real files do), and read back as before afterwards.
- D.28 What a scene hangs below an object of a placed prefab is written as the level's own, with its parent named by path into the placement: `Instance_[n]/Entity_[m]` (the engine reads an entity reference relative to the prefab that holds it, `InstanceEntityIdMapper::MapJsonToId`; a placement below another placement's object: `../Instance_[n]/Entity_[m]`). Unity names such a parent by a stripped transform (`scene_converter.stripped_transforms`, both spellings). Before, these objects were never written: two rocks of the Alien Forest demo, seven empty objects of the Alchemist scene, two door signs of the Tirgames club.
- D.29 The objects below a model's root have ids the converter can work out when the file has no id table (Unity 2019.3 and later): the hash of where the object sits, `Type:GameObject->//RootNode/root/<path>0`, its transform `Type:Transform->.../Transform0`, its renderer `Type:MeshRenderer->.../MeshRenderer0` (`model_import.hashed_object_ids`, `hashed_renderer_id`). Read off a fire pit whose prefab names the model's parts by them; with them an override of a part's materials lands.
- D.30 A placement whose overrides name, as its root, a transform its prefab no longer has stands where the prefab's own root stands (`prefab.lost_root`; the entity map keeps `root_position` and `root_rotation`). Unity drops an override that names nothing; the converter applied it and put a drawer 2.5 m away. Only a root named with the prefab's own guid is judged.
- D.31 The harness compares a Unity collider with the shape made for it, found by the number in its entity's name (`<object>_Collider_<n>`), not by its place in a list: a collider without a shape (a mesh collider whose mesh the Unity project has lost) shifted every later pair. A placement of a prefab the Unity project itself has lost is unmeasured, not unmatched.
- D.32 The truth dump says which files of the project Unity itself changed while it was open, and files the dump under what the project looks like afterwards (`unity_bridge.scope_state`). On its first run on the artificer project Unity upgraded two materials of the Alchemist House pack and wrote them back (one line each); they were put back from the repository, and the next run left them alone. Whether the bridge should put such files back itself is the person's call (Q.7).
- D.33 A terrain saved by Unity 2018.3 or later keeps each layer in a `.terrainlayer` asset of its own and one heightmap resolution; both forms are read (`terrain_data.read_terrain_layer`, `terrain_layer_files`). The Alien Forest terrain had been upgraded by Unity 6 (its layers lie in `Assets/_TerrainAutoUpgrade`), which is why `test_terrain_data` failed. The terrain stage is still outside the harness and its terrain is not placed in the converted level (Q.4).

## Q - Open questions
- Q.1 LOD groups. The asset stage keeps LOD0 and drops the rest (`strip_lods`, on by default; see `mem:lod_handling/lod_handling_plan`), and since D.9 the engine no longer adds lower levels on its own. Is one level of detail what the person wants from a vegetation pack, or O3DE LODs inside one model? What it takes: a Unity LOD level may hold several renderers (trunk and leaves) where the next holds one, so a model per LOD group, not per object, with the group's levels in its LOD rule - one entity where there are several now. For the person; blocks nothing measured.
- Q.2 (answered by D.17 for the first layer of the lit shaders) The distributor's shaders: what has no rendition yet is listed at the end of D.17. A leaf's translucency would need EnhancedPBR's thin transmission instead of StandardPBR; the second layers a material type of their own. For the person to weigh once the levels have been walked.
- Q.3 The 68 particle prefabs hold nothing the converter converts. Report them as unmeasured, or leave the folder out of the bed - blocks I.3's reading.
- Q.4 Terrain: `Small Demo Map` and the demo scenes stand on one. The terrain stage exists (`mem:terrain/terrain_tab_plan`) and is outside the harness - blocks I.5 only if the person wants the demo scenes whole.
- Q.5 Unity's built-in sphere and capsule (D.24): the converter's own are the same size with the same lay of the texture, on other vertices (the harness would call them 65 mm off, vertex to vertex). Point for point needs Unity's own mesh data shipped with the converter. For the person; one object of the five beds shows a sphere.
- Q.6 A placed prefab stretched by axis: its root takes the scale, the objects below its root inside the prefab do not (the engine passes none of it down, and the converter carries a scale down inside one file only). The same gap keeps a prefab whose root carries a capsule from being stretched at all: ten poles of the Tirgames club stand at their model's height. What it takes: the entity map lists every entity below the root with its transform, and the placement patches each (place, scale, and a round collider's size). Not measured by the harness below the root; seen in the Editor.
- Q.7 Should the truth dump put back, from version control, the files Unity changes while it is open (D.32)? It names them now.
- Q.8 Components the converter makes nothing of, by what the three packs hold: Animator (6 in the Alchemist House), HingeJoint (4 there), ParticleSystem (the Fire and Smoke pack's prefabs and a few in the two other packs), a skinned mesh (one butterfly), Camera, AudioListener, ReflectionProbe, and what belongs to baked lighting and navigation. Which of them should become O3DE components (a camera, a PhysX hinge joint, a reflection probe are within reach; particles and animators have no counterpart in the engine as shipped)?
- Q.9 A convex collider on a model built very small and scaled up in the prefab (an apple 2 mm across at a scale of 35) is cooked by PhysX with tolerances meant for metres: its hull is 6 mm off. One collider of the three packs. Tighter cooking parameters by the mesh's size would be the way.

## I - Stages
- [ ] I.1 The bed and its truth (ran) - Done when: the bed's truth dump of the pack is complete.
  - [x] I.1a Bed files; the bridge writes a mesh when first met (D.3). Ran: truth dump ok, 1056 prefabs, 433 models, 4 scenes, 8010 objects, 1202 meshes, 1328407 vertices, 0 matrix mismatches, no warnings.
- [ ] I.2 Output in the source's folders (ran) - Done when: with the option on every asset lies at its source's place and repeated names stay apart; with it off the two older beds measure as before.
  - [x] I.2a The layout in the Stage 1 worker and the prefab writer (D.4). Ran: 10 unit tests (`test_output_layout`).
  - [x] I.2b The scene stage and the harness join by guid and place (D.5). Ran: unit tests; cycles of the two older beds: see the working doc.
- [ ] I.3 Baseline (ran) - Done when: a full cycle of the bed ran to a report, kept as the baseline, and its clusters are listed here.
  - [x] I.3a The harness for a pack of this shape: cells by size (D.8); the trace knows a written model file by its path. Ran: unit tests; the two older beds "no change".
  - [x] I.3b First cook: 149 failed jobs of three kinds, put right in general code (D.9, D.10, D.11). Ran: 6 unit tests (`test_cook_rules`); second cook 1 failed job (D.12).
  - [x] I.3c Baseline cycle, kept in `user/Parity_Nature/baseline_2026-11-26/`. Ran: see the Baseline section.
- [ ] I.4 The pack's clusters - Done when: each cluster of the baseline is closed in general code, or carried with a reason; the two older beds show no regression.
  - [x] I.4a Node names with a dot (D.12). Ran: 1 unit test.
  - [x] I.4b A prefab root's scale (D.13). Ran: 10 unit tests (`test_root_scale`).
  - [x] I.4c Unity mesh assets (D.14, D.15). Ran: 7 unit tests (`test_mesh_asset`); the reader against Unity's dump of 92 meshes.
  - [x] I.4d The report measures a model file placed straight in a scene; a bed's levels may lie below a folder of their own in `Levels`.
  - [x] I.4e Materials of the distributor's shaders (D.16, D.17). Ran: 14 unit tests (`test_material_by_shader`), 8 (`test_shader_source`).
  - [x] I.4f The OBJ's axes by the measurement (D.15); an empty mesh (D.18); a model placed below another object of a scene (D.19). Ran: unit tests.
  - [x] I.4g Import scale with "Convert Units" off (D.20); a placement that swaps a mesh (D.21). Ran: unit tests (`test_model_import`, `test_scene_fidelity`).
  - [x] I.4h A scale by axis carried down, mirror and stretch (D.22). Ran: 12 unit tests (`test_scale_carry`).
  - [x] I.4i The probe's file names (D.23). Built: `ParityProbe.Editor`, 0 errors.
  - [x] I.4j Colliders on mirrored and stretched objects (D.25). Ran: 6 unit tests (`test_collider_scale`).
  - [x] I.4k A model's hashed object and renderer ids (D.29). Ran: unit tests (`test_model_import`).
- [ ] I.5 The levels (ran) - Done when: every row of the four scenes passes or is carried with a reason, and the person has walked the overview levels. Ran: all four scenes pass every row (151, 40, 283, 244). Left: the person walks them (T.5).
- [ ] I.6 BK_AlchemistHouse (ran) - Done when: its bed (`parity/configs/alchemist.json`) has a baseline and every cluster is closed in general code or carried with a reason. 157 prefabs in Unity's old prefab format, 119 models, 3 scenes; rigid bodies, hinge joints, animators.
  - [x] I.6a The bed, its truth and its baseline (kept in `user/Parity_Alchemist/baseline_2026-11-26/`): 134 pass, 17 fail, 6 unmeasured.
  - [x] I.6b The built-in meshes (D.24); components in Unity's order (D.26). Ran: 15 unit tests (`test_builtin_meshes`), 4 (`test_component_order`).
  - [x] I.6c The materials of a model (D.27). Ran: 9 unit tests (`test_fbx_material_names`), 10 (`test_fbx_node_tree`).
  - [x] I.6d What a scene hangs below a placed prefab (D.28); a placement with a lost root (D.30). Ran: 9 unit tests (`test_scene_children`), 6 (`test_lost_root`).
  - [x] I.6e The harness pairs colliders by entity (D.31); the dump names what Unity changed (D.32). Ran: unit tests (`test_parity_compare`, `test_unity_bridge`).
- [ ] I.7 Alien Fantasy Forest (ran) - Done when: its bed (`parity/configs/alienforest.json`) has a baseline and every cluster is closed or carried. 85 prefabs, 442 models (one file per level of detail), 2 scenes on a terrain.
  - [x] I.7a The bed, its truth and its baseline (kept in `user/Parity_AlienForest/baseline_2026-11-26/`): no failing prefab; 2 scene objects not in the level (D.28).
  - [x] I.7b A terrain saved by a later Unity (D.33). Ran: 8 unit tests (`test_terrain_data`), on the pack's own terrain.

## Baseline of the bed (2026-11-26, after D.8 to D.11; before D.12 to D.16)
Kept in `user/Parity_Nature/baseline_2026-11-26/`. Cook: 1 failed job (149 on the very first cook).

| Element | Rows | Pass | Fail | Other |
|---|---|---|---|---|
| Prefabs | 1056 | 232, and 681 that pass but for the levels of detail dropped on purpose | 140 | 2 uncooked, 1 unmatched |
| transform | 2166 | 1882 | 284 | |
| mesh | 1186 | 922 | 261 | 3 uncooked |
| collider | 704 | 585 | 116 | 3 unmeasured |
| materials | 1186 | 1136 | 50 | |

| Cluster | Prefabs | Cause |
|---|---|---|
| transform, mesh and collider rows off by a scale | 79 | the prefab root's own scale left out (D.13) |
| no model, no materials | 50 | the mesh is a Unity mesh asset (D.14) |
| the four `Prefab_Bridge_*` (most of the small clusters) | 4 | objects scaled by axis, or mirrored, with objects below them: O3DE passes no such scale down |
| mesh in place but not the same shape | 6 | `prefab_grass_03_*`; not looked into yet |
| mesh scale at import | 2 | `SM_river_stone_*_wet`; not looked into yet |

Scenes: `Overview Map` 146 of 151 rows, `Small Demo Map` 39 of 40, Forest `Overview Scene` 232 of 283, Meadow `Overview Scene` 165 of 244. The failing rows are the scale of D.13 (62) and model files placed straight in the scene, which the report did not know how to find (74; I.4d).

The material rows compare which materials an object shows, not how they render: the 142 materials of the distributor's shaders pass them and are still wrong to the eye (I.4e).

## Where the five beds stand (2026-11-26, last chain of the unattended run)
Every bed cooks with 0 failed jobs. "LODs dropped" are prefabs that pass but for the lower levels of detail the asset stage drops on purpose (Q.1).

| Bed | Prefabs | Pass | LODs dropped | Fail | Unmeasured | Scenes |
|---|---|---|---|---|---|---|
| Office | 222 | 221 | | 0 | 1 | Showcase: all rows |
| Tirgames | 263 | 262 | | 0 | 1 | the club level 2023 of 2033 rows (ten poles: Q.6) | |
| NatureManufacture | 1056 | 262 | 790 | 1 | 3 | four scenes: all rows (151, 40, 283, 244) |
| Alchemist House | 157 | 149 | | 1 | 7 | Scene 1101 of 1101, Scene_Items 134 of 134, Props 129 and 4 unmeasured |
| Alien Fantasy Forest | 85 | 2 | 82 | 0 | 1 | Demo1 7005 of 7005, Update_1_2 15 of 15 |

Office: unchanged through every chain of the run.

What is left failing or unmeasured, and why:
- NatureManufacture: `prefab_Butterfly_Single` shows a skinned mesh, which the converter does not convert; three mesh colliders hold no mesh in Unity either.
- Alchemist House: the apple's convex hull (Q.9); seven mesh colliders and four placements name a mesh or a prefab the Unity project itself has lost.
- Alien Fantasy Forest: one mesh collider (`Plant_12`) names no mesh in Unity.
- Tirgames: ten poles stretched by axis in the club level (Q.6); one mesh collider unmeasured, as before this plan.
- Office: its character controller, unmeasured as before this plan.
- Not measured by the harness at all, and so listed here: how a material renders (second layers, translucency, detail maps: D.17), levels of detail (Q.1), terrain (Q.4), and the components of Q.8.

## T - Proofs
| ID | Proof | Stage |
|---|---|---|
| T.1 | `python parity/parity.py truth parity/configs/nature.json` ends ok with no matrix mismatch | I.1 |
| T.2 | `python tests/unit/test_output_layout.py`; cycles of the Office and Tirgames beds: "no change" | I.2 |
| T.3 | `python parity/parity.py cycle parity/configs/nature.json` runs to a report; a copy kept as the baseline | I.3 |
| T.4 | Cycle of the bed: clusters closed or listed; cycles of the two older beds: no regression | I.4 |
| T.5 | The person opens the overview levels in the Editor and finds the pack's folders under `Assets/NatureManufacture` | I.2, I.5 |
| T.6 | The person reads the report against its baseline and accepts what is carried | P |

## Project
- Rules read: `AGENTICS_GUIDELINES.md`, `tests/README.md`, `parity/README.md`, the memories named at the top, the global CLAUDE.md. No CLAUDE.md or AGENTS.md in the repo.
  - Plain Python `assert` tests on `tests/harness.py`; section banner comments; no TODO comments; long docstrings on public surfaces.
  - Platform code stays behind the `SourcePlatform` contract. Code runs on the installed Python 3.9.
  - A file whose working copy carries CRLF is brought to LF before it is edited (the index holds LF).
  - Never commit or push; never write to GitHub. Claude proposes commits. Nothing is committed in AGURP2024.
- Proof commands: `QT_QPA_PLATFORM=offscreen python tests/run_all.py`; `python parity/parity.py cycle parity/configs/nature.json` (and `office.json`, `tirgames.json`). The Unity project, the Editor and the Asset Processor must be closed.
- Record: `.serena/memories/nature_pack/record.md`
- Wipe: nothing. The plan and the working doc are kept (the person's standing answer for this repository).
