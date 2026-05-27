---
name: project-system-feature-roadmap
description: Forward-looking roadmap for the converter after the base prop-up shipped. Compares each requested feature against current capability and sequences them with dependencies. Source: user planning conversation 2026-05-26.
metadata:
  type: project
---

# Feature Roadmap — post base-prop-up

This is the working roadmap. Each feature should later spawn its own
`<feature>_plan.md` + `<feature>_working_documentation.md` pair under
the appropriate sub-folder once the user picks it up for execution.
Until then this document is the single source of intent and sequencing.

Linked plans:
- [[project-system-plan]] — base prop-up (shipped).
- [[material-component-label-resolution-plan]] — pre-existing.
- [[terrain-tab-plan]] — pre-existing.

---

## Macro narrative

The converter today is "point at folders → press Process → hope". The
target state is: **scope a project once, pre-flight all the decisions
in a structured way, then execute a staged conversion whose outputs
can be patched and re-patched as overrides change** — without
rebuilding from scratch every iteration.

Two crosscutting themes drive the next phase:

1. **Pre-preparation over execution.** Most converter friction happens
   because decisions (which scenes, which prefabs, which mesh overrides,
   which shader mappings) get bundled into a single black-box run. The
   work below splits those decisions out into discrete, inspectable
   pre-processing stages that the user can review before pulling the
   trigger.
2. **Patchability over re-export.** Once a project converts, fixing one
   mesh or one shader mapping should patch that asset's outputs in
   place — not force a full re-run. The base already has the building
   blocks (entitymap.json, asset_index.json, coverage.json sidecars in
   `.ImporterData/`); they need to be extended to a per-asset state
   index that supports surgical re-emission.

---

## Capability baseline

What the base prop-up + prior work currently support:

- **Project system** (just shipped): named projects with save/load/recent,
  Mission Command dashboard, per-stage settings + pipeline_status, legacy
  migration, save-on-close.
- **Three converter stages**: Prefab Processor (single source/output),
  Scene Converter (single scene + prefab dirs), Terrain (user-picked .mat
  list).
- **Coverage reporting**: end-of-run punch list of unhandled component
  types, missing assets, unhandled override paths.
- **Override propagation**: Tier 1 transform + Tier 3 material slot
  overrides on prefab instances; tier 2 m_IsActive logged but not
  emitted.
- **Sidecars**: `<output>/.ImporterData/{<stem>.entitymap.json,
  asset_index.json, coverage.json}`.
- **Dependency probe**: ConfigTab already has a `_refresh_dep_status`
  that walks a hardcoded `DEPENDENCIES` list and reports status — but
  nothing surfaces it outside the Config tab.

The gaps below are organized by feature, with explicit dependencies.

---

## F-1  Startup dependency banner

**Goal.** On app start, check dependencies. If anything is missing,
show a yellow/red banner across the top of the window with a "Open
Config" jump and a "Don't show again" dismiss action. The dismiss
state persists across launches and is keyed per-dependency-set
(suggested: hash of the missing-dependency names so a new missing
dep re-arms the banner).

**Today.** `ConfigTab._refresh_dep_status` exists and probes
`DEPENDENCIES`; no banner; no persistent dismiss.

**Open questions.**
- Where does the banner sit? Above the QTabWidget? On the Project tab
  only? Recommended: above the QTabWidget so it's visible regardless
  of which tab is active.
- Dismiss is per-installation (global settings) or per-project? Per
  installation makes more sense — dependencies aren't project-scoped.

**Phase outline (small, ~1 session).**
- I.1 Add `check_dependencies() -> list[missing]` to a shared module
  (extract from ConfigTab).
- I.2 Add `DismissibleBanner(QFrame)` widget. State persists to
  global settings `dependencies.dismissed_signature`.
- I.3 Mount banner in `MainWindow` above the QTabWidget. Connect
  "Open Config" to the corner button click.

**Depends on.** Nothing (foundational standalone).

---

## F-2  Project-level scope path

**Goal.** Every project carries a single **Unity source root** (folder)
that defines what the conversion can see. Subsequent stages
(scene scrubbing, prefab scrubbing, mesh inventory, material inventory)
walk this root once and produce filtered lists for the user to act on.

**Today.** Each stage carries its own `source_path` independently
(`asset_processor.source_path`, `terrain_processor.source_path`).
There is no single project root. The `ProjectScope` enum already on
Project is a *category tag* (whole_game / asset_cluster / asset_set /
individual_action), not a path — they need to coexist.

**Reconciliation.** Add `Project.scope_root: Optional[Path]`. The enum
stays (it's a description tag). Per-stage `source_path` fields become
**optional overrides** — when blank, the stage uses `scope_root`. This
preserves backwards compatibility for the migrated Legacy project.

**Open questions.**
- Does the scope root pick a `Assets/` folder, or the Unity project
  root (the one containing `Assets/`, `ProjectSettings/`, etc.)?
  Recommended: **Unity project root**, then the converter internally
  resolves `<root>/Assets`. Lets us also pick up `ProjectSettings/`
  later for things like graphics-settings hints.
- Multiple scope roots in one project? Recommended **no** for v1 —
  one root keeps file scrubbing tractable. Multi-root is a Future
  Tag.

**Phase outline (~1–2 sessions).**
- I.1 Add `scope_root` to `Project` + Mission Command UI to set it.
- I.2 Add a `ScopeIndex` data class — lazy-walk the root, cache file
  lists (`*.unity`, `*.prefab`, `*.mat`, `*.fbx`, etc.).
- I.3 Tabs fall back to `scope_root` when their stage source is blank.

**Depends on.** Nothing (foundational; everything below builds on it).

---

## F-3  Scrubbed scene marking + multi-scene level output

**Goal.** Pick from a checklist of every `.unity` scene the scope
contains. Output is a chosen O3DE levels folder; each selected scene
becomes `<levels>/<SceneName>/<SceneName>.prefab` (O3DE's nested-folder
convention for levels).

**Today.** `SceneConverterTab` takes a single `scene_path`. Output is
`<output_dir>/<SceneName>.prefab` flat, not nested in a per-scene
folder. Prefab database is configured per-run via `prefab_dirs`.

**Two semantic changes.**
1. **Scene picker** → multi-select checklist sourced from the
   ScopeIndex (F-2).
2. **Output structure** → `<levels>/<SceneName>/<SceneName>.prefab`
   nested. Need to confirm against current O3DE level conventions:
   modern O3DE levels live as `<project>/Levels/<LevelName>/<LevelName>.prefab`,
   so this matches. **Verify** with a fresh O3DE project before locking.

**Open questions.**
- Per-scene output override? (rare; defer.)
- Skip scenes that already converted (idempotence)? Tied into F-9.
- Scene-database parse cost: every scene parse is heavy. Cache scene
  metadata (entity count, prefab references) in ScopeIndex so the
  checklist can show preview stats without full parse.

**Phase outline (~2 sessions).**
- I.1 SceneConverter output path change to nested folder form.
- I.2 Multi-scene worker: process selected scenes serially with a
  per-scene progress callback.
- I.3 Scene checklist UI replacing the single `scene_path` field.

**Depends on.** F-2 (scope root → scrubbed scene list).

---

## F-4  Scrubbed prefab marking

**Goal.** Replace "prefab dirs" with an auto-scrubbed checklist of
every `.prefab` in the scope. User toggles which prefabs to import.
The list becomes the source of truth for what Stage 1 processes.

**Today.** `PrefabProcessorTab` reads everything under
`asset_processor.source_path` matching `*.prefab` recursively. No
checklist. `SceneConverterTab` has a `prefab_dirs` list for matching
*existing* converted prefabs at level-build time.

**Two-way change.**
1. **Stage 1 input**: from "all prefabs in source" → checked subset
   of scrubbed prefabs.
2. **Stage 2 prefab database**: from "scan these dirs for matches"
   → "use the project's known converted prefab set" (populated by
   Stage 1's output index — already exists as `asset_index.prefabs`).

**Open questions.**
- Tree view vs flat list? Tree mirroring the folder structure is
  more usable for big projects.
- Default state: all checked, none checked, or smart-default
  (everything referenced by selected scenes)? Recommended **smart
  default** — drives off F-3's scene selection to auto-check just
  the prefabs the scenes need, with manual extras.
- Per-prefab preview: hover shows mesh count, material count,
  collider count from a parse cache. Defer to a later iteration.

**Phase outline (~2 sessions).**
- I.1 Prefab inventory in ScopeIndex (filename, GUID, mesh GUIDs,
  material GUIDs).
- I.2 Checklist widget on PrefabProcessorTab (or a new "Prefab
  Inventory" tab — see Sequencing notes).
- I.3 Stage 1 worker accepts a filtered list.
- I.4 Stage 2 prefab database backed by F-4 inventory + Stage 1
  asset_index, instead of `prefab_dirs`.

**Depends on.** F-2 (scope root → scrubbed prefab list).

---

## F-5  Mesh import preprocessing

**Goal.** A new tab (or section) for default mesh import behavior:
- Position zeroing on/off.
- Default position + rotation when zeroing.
- **Per-mesh overrides** — pick from the scrubbed mesh list and set
  custom values when an asset imports irregularly.

This is also the first feature that introduces the **patchability**
contract — when an override is added or changed, the converter
should be able to re-emit only the affected `.assetinfo` (and any
prefab that references it) without a full re-run.

**Today.** `IntegratedAssetProcessor.write_fbx_assetinfo` writes
Y-up coordinate-system rules; there is no positioning-zeroing knob;
there are no per-mesh overrides.

**Two-part deliverable.**
1. **Defaults tab**: project-wide mesh import defaults.
2. **Overrides table**: rows = mesh stem (or GUID), columns = override
   fields (zero-position, position, rotation, custom CoordinateSystemRule).

**Patching contract (first iteration).**
- When an override changes, mark the affected mesh + every prefab
  that references it as "dirty" in a new
  `<output>/.ImporterData/output_state.json` index.
- Add a "Patch" action that re-emits only dirty entries.
- Stage 1 full run resets dirty state.

**Open questions.**
- Override granularity: per-FBX (Unity .fbx file) or per-mesh-within-FBX
  (the sub-objects we already parse)? Per-FBX is simpler; per-mesh
  is more powerful. Recommend **per-FBX for v1** because the
  irregular-pivot case is almost always at the FBX root.
- Patch semantics: does a mesh-override change re-emit only the
  `.assetinfo`, or also the parent prefab(s)? `.assetinfo` only
  unless a coordinate change actually rotates the entity in the
  prefab (rare; today's pipeline applies coords at prefab-emit
  time so the prefab would need re-emission too).

**Phase outline (~3 sessions).**
- I.1 Mesh inventory in ScopeIndex (FBX paths, GUIDs).
- I.2 Mesh Defaults tab + project-level fields.
- I.3 Per-mesh override table UI + storage in
  `project.stages.mesh_processor.overrides`.
- I.4 IntegratedAssetProcessor honours defaults + overrides at
  `.assetinfo` write time.
- I.5 `output_state.json` per-asset dirty tracking + Patch worker.

**Depends on.** F-2 (scope) + F-4 (prefab inventory, so the user can
see *which* prefabs would patch when a mesh changes).

---

## F-6  Material shader mapping + unknown-shader detection

**Goal.** Scan the materials in scope, group them by Unity shader
type, surface any unrecognised shader types to the user. Build a
**shader-mapping library** that maps Unity shader → O3DE mapping
strategy:

- Map to existing O3DE material type with property remap (current
  StandardPBR / TerrainBaseMaterial behavior, generalised).
- Map to a custom O3DE materialtype the user has authored.
- Mark as "skip" / "manual".

Mapping library lives **per-installation** at
`<repo>/shader_mappings.json` so a shader resolved in one project
carries over to the next.

**Today.** Material conversion hardcodes property remaps for Unity
Standard / URP shaders in `components/material.py`. Unknown shaders
produce empty .material files or errors. No library.

**Two-part deliverable.**
1. **Pre-scan** (a "Materials Inventory" tab): group .mats by their
   `m_Shader` reference, count, surface unknowns prominently.
2. **Mapping editor**: per-shader-type entry in the library —
   target materialtype, property remap table (Unity property name
   → O3DE property path → conversion fn).

**Open questions.**
- Library scope: global (per-install) or project-overridable
  (project can shadow library entries)? Recommend **library
  global + project overrides** — common shaders solved once, weird
  per-project shaders override locally.
- Format: JSON for the library is fine; the property remap
  expressions need a small DSL or a Python expression hook. DSL
  is safer (no code-eval); recommend a constrained DSL with
  built-in conversion fns (`smoothness_to_roughness`, `invert`,
  `lerp`, `unchanged`).
- Custom O3DE materialtype hookup: user points at a
  `.materialtype` path; we read its property schema for the
  remap editor's right-hand side.

**Phase outline (~3 sessions; the biggest one).**
- I.1 `shader_mappings.json` schema + loader.
- I.2 Material inventory walk (groups .mats by shader, returns
  unknowns).
- I.3 Materials Inventory tab + unknown-shader list with
  "Resolve…" action that opens the mapping editor.
- I.4 Mapping editor dialog: remap table, target materialtype
  picker, save to library (with project-override toggle).
- I.5 Material conversion honours the library + project overrides.
- I.6 Patch hook: changing a mapping marks every affected
  .material as dirty.

**Depends on.** F-2 (scope) + F-5 (patch infrastructure can be
reused).

---

## F-7  Terrain extraction expansion

**Goal.** Extend the existing Terrain tab beyond per-.mat picker:
- Heightmap extraction: Unity terrain `m_Heightmap.m_Heights` →
  16-bit grayscale PNG (or .r16).
- Terrain material extraction (today's tab).
- (Later) Full terrain entity formation: TerrainSpawner,
  TerrainHeightGradientList, TerrainSurfaceMaterialsList
  components wired into a level prefab.

**Today.** Terrain tab handles material conversion only. No
heightmap path. No terrain entity emission.

**Open questions.**
- Where do height textures land? `<output>/Terrain/Heightmaps/`
  matches the existing convention.
- Multi-tile (Unity terrains can be tiled): one PNG per tile or
  one big stitched PNG? Defer multi-tile to v2.
- Terrain entity formation: requires a TerrainWorld prefab as
  output. Big enough that it deserves its own plan-and-WD pair
  when it's picked up; defer until heightmap + materials land.

**Phase outline (~2 sessions for v1, +unknown for v2).**
- I.1 Heightmap extractor: walk scope for Unity terrain assets,
  decode `.terrain` (or `.unity` scene-embedded terrain), write
  PNG.
- I.2 Terrain tab gains a "Heightmaps" section parallel to the
  existing materials list.
- I.3 (Future) Terrain entity prefab emission.

**Depends on.** F-2 (scope walk reaches terrain assets).

---

## F-8  Staged orchestration + pre-flight

**Goal.** Mission Command becomes the single button. Pre-flight runs:
1. Dependency check (F-1).
2. Scope validity (F-2): root exists, contains Assets/.
3. Scene selection check (F-3): at least 1 scene selected; each
   selected scene exists; missing scenes prompt user.
4. Prefab selection check (F-4): every prefab the selected scenes
   reference is either checked or explicitly skipped.
5. Mesh override sanity (F-5): no override points at a non-existent
   FBX.
6. Material mapping coverage (F-6): zero unknown shaders, or user
   acknowledges them.
7. Terrain (F-7): heightmaps and materials present if terrain is
   in scope.

Pre-flight produces a structured report. Green → unlock "Run All".
Yellow → user can override on a per-item basis. Red → block.

Run All executes stages serially: prefabs → materials → meshes
(.assetinfo) → terrain → scenes → finalize.

**Today.** Each stage runs independently from its own tab. No
pre-flight. No project-level dispatch.

**Open questions.**
- Cancellable Run All? Yes — each stage worker should be Qt-cancellable.
- Resume after failure? Tied to F-9 — if state.json knows what's
  done, resume = continue from first dirty entry.
- Per-stage skip toggle? Yes (e.g. "skip terrain this run").

**Phase outline (~3 sessions).**
- I.1 `PreflightReport` data class + runner.
- I.2 Mission Command "Pre-flight" panel: per-check rows, severity
  dots, drill-down details.
- I.3 "Run All" worker orchestrator.
- I.4 Per-stage Cancel + resume hooks.

**Depends on.** F-1 through F-7 (orchestrates them all).

---

## F-9  Output state persistence + patching

**Goal.** Every emitted asset is recorded in
`<output>/.ImporterData/output_state.json` with: source GUID + path,
timestamp, hash of inputs (scope path + override snapshot), output
files written. When *something* changes (override added, mapping
updated, scene re-selected), the converter can identify the dirty
subset and re-emit only those entries.

**Today.** Coverage + asset_index + entitymap sidecars exist but are
written end-of-run and don't track per-asset input fingerprints.

**Two-part deliverable.**
1. **State index**: extend the existing sidecars to track
   `{source_guid, source_path, output_files, input_hash}` per asset.
2. **Patch run**: a worker that walks the state index, computes
   current input hashes against stored hashes, marks dirty entries,
   re-emits each. Pre-flight gates apply (F-8).

**Open questions.**
- What counts as "input" for hash purposes? For a prefab: the .prefab
  file contents + every override that touches it. For a mesh: the FBX
  mtime + the project-level mesh defaults + per-mesh overrides. Hash
  semantics must be conservative enough that "I changed something"
  always = "rebuild this" but tight enough that we don't rebuild the
  world for every UI tweak.
- Delete propagation: a prefab removed from F-4's checklist — do we
  also remove its outputs? Recommend **opt-in clean** with a
  separate "Remove orphans" action.
- Migration: the existing Legacy project's outputs have no state
  index. First "Patch" call falls back to full re-emit + records
  state going forward.

**Phase outline (~3 sessions).**
- I.1 Extend sidecars to record per-asset state.
- I.2 Hash computation for each asset type.
- I.3 Patch worker (dirty detection + targeted re-emit).
- I.4 Mission Command "Patch" action separate from "Run All".
- I.5 Orphan detection + opt-in clean.

**Depends on.** F-5 (mesh overrides drove the first patchability
contract), F-6 (mapping overrides), F-8 (orchestrates pre-flight
before patch).

---

## Recommended sequencing

The dependency chain is real but not strict — F-1 and F-7 are
mostly independent and can interleave. Suggested order:

1. **F-1 Startup dependency banner** — small, independent, sets up
   the "always-visible meta UI" pattern Mission Command will reuse.
2. **F-2 Project scope path** — foundational. Everything below
   reads from ScopeIndex.
3. **F-4 Scrubbed prefab inventory** — comes before F-3 because
   F-3's smart-default scene checklist wants to know which prefabs
   are referenced.
4. **F-3 Multi-scene + nested output** — UX-blocking gap that
   pairs naturally with F-4.
5. **F-5 Mesh preprocessing + patch foundation** — introduces the
   patchability primitives that F-6 and F-9 reuse.
6. **F-6 Material shader library** — biggest single feature; lands
   on top of F-5's patch primitives.
7. **F-7 Terrain heightmap extraction (v1)** — independent enough
   that it could move earlier; placed here because terrain is a
   smaller user-volume than prefabs/materials.
8. **F-8 Staged orchestration + pre-flight** — binds everything
   above into a single Mission Command "Run".
9. **F-9 Output-state patching** — finalises the patchability
   theme; ships last because it depends on every other feature's
   own dirty-tracking hooks.

After F-9 the converter goes from "linear export tool" to
"continuously-updating conversion project". Future v2 work
(terrain entity formation, multi-scope projects, asset-checklist
approvals, run history) sits cleanly on top.

---

## Cross-cutting concerns to keep in mind

- **Memory clustering.** Each F-x feature gets its own folder under
  `.serena/memories/` (e.g. `mesh_preprocessing/`, `material_mapping/`,
  `orchestration/`) per the global CLAUDE.md convention. The plan
  + working-doc pair lives in that folder.
- **Schema versioning.** Every change to the .u2oproj.json shape
  needs `Project.from_json` to handle older versions gracefully.
  `SCHEMA_VERSION` is already bumped to 1; bump on each shape change
  and add a migration step in `from_json`.
- **Sidecar shape.** Every patchable artifact lives in
  `<output>/.ImporterData/`. Don't scatter state files at the
  output root; the Asset Processor will scan them.
- **Per-feature smoke proofs.** Every F-x plan should declare its
  testing matrix in the same format the base plan used (T-1, T-2,
  …) and ship the proofs alongside the implementation, not deferred.
