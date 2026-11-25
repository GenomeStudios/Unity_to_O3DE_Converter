# LOD Handling — Plan (P/I/T)

Status: **P locked; I.1–I.3 SHIPPED (2026-06-01), tests green.** Owner-facing problem:
Stage-1 generated prefabs emit every Unity LOD level (LOD0/LOD1/LOD2…) as its own
enabled O3DE entity with its own MeshComponent. O3DE has no LODGroup component and
nothing culls them, so all LODs render simultaneously → severe Editor perf loss.

See `mem:project/converter_working_status` for the parse→emit pipeline this rides on,
and `mem:lod_handling/working_documentation` for the build log.

---

## Design

### O3DE LOD reality (source-verified against `d:/OffLocalDev/o3de_sourcedev`)
O3DE has a complete LOD system, structured **nothing** like Unity's:
- **Pipeline layer — `LodRule`** (`Code/Tools/SceneAPI/SceneData/Rules/LodRule.h`,
  iface `SceneCore/DataTypes/Rules/ILodRule.h`; EMotionFX has a parallel one for
  skinned meshes). At FBX import you assign FBX nodes to LOD levels via per-level
  `SceneNodeSelectionList`s. All LODs bake into **one** `.azmodel`.
- **Runtime layer — `LodConfiguration`** (`Gems/Atom/RPI/Code/Include/Atom/RPI.Public/Culling.h:81-97`):
  `enum LodType {Default, ScreenCoverage, SpecificLod}`, `m_lodOverride` (serialized
  `"LodOverride": 255` = none), `m_minimumScreenCoverage`, `m_qualityDecayRate`.
  ONE `EditorMeshComponent` swaps the model's baked LODs automatically by screen
  coverage (`MeshFeatureProcessor.cpp`).

**Crux:** O3DE LODs live INSIDE a single model asset, auto-selected by one mesh
component. They are NOT separate entities. Unity LODGroups ARE separate child
GameObjects (LOD0/LOD1…), each with its own renderer. The converter had zero
LODGroup awareness — `LODGroup` (`!u!205`) is not in the component dispatch, so its
data was discarded and every LOD child became an enabled entity.

### Two deliverables (both chosen by user 2026-06-01)
1. **Strip toggle (this work, I.1–I.3 — DONE):** parse the LODGroup, keep only the
   chosen level's renderers (LOD0), drop the rest. Default-ON (fixes a real regression).
2. **LodRule bake (future, I.4+):** emit the LODn FBX nodes as ONE model with a
   `LodRule` in the `.assetinfo`, one MeshComponent. Native O3DE LOD switching.
   Larger; deferred. Plan section below is a stub to be expanded when picked up.

### Strip mechanics (authoritative on LODGroup data, not names)
- Unity LODGroup (`!u!205`) serializes `m_LODs`: an ordered list (index 0 = highest
  detail). Each level has `renderers: [{renderer: {fileID: <MeshRenderer comp fileID>}}]`.
- Renderer fileID is a **component** fileID → resolve to its owning GameObject via a
  `component_owner[comp_fileID] = m_GameObject.fileID` map captured during parse.
- Keep set = GOs owning `keep_level`'s renderers. Drop set = GOs owning all OTHER
  levels' renderers, minus the keep set (shared renderer → keep wins).
- Remove each dropped GO **and its subtree**, unlinking from its parent's
  `children_ids`. Guard: never remove a GO that is in the keep set.
- Name heuristic (`LOD\d+`) is **fallback only** — used solely when no LODGroup
  component is present (not implemented in I.1; LODGroup-driven path covers the packs).

### Settings home — **`asset_processor.strip_lods`** (Prefab Processor stage)
Top-level flag on the `asset_processor` stage settings, **`strip_lods: bool = True`**,
toggled from the **Prefab Processor tab** "Conversion Options" section. (Initially
landed under `mesh_processor` mirroring `prefab_wrapper_editor_only`; **moved to
`asset_processor` at user request** — LOD stripping is a prefab-import transformation,
not a per-mesh concern, so it belongs on the Prefab page.) `lod_keep_level` stays an
internal `UnityParseContext` param fixed at 0 (LOD0) — no UI until the "configurable
level" option is requested.

Threading: Prefab tab `asset_processor.strip_lods` → snapshot at Run → `WorkerThread`
→ `_do_processing` → `IntegratedAssetProcessor(strip_lods=…)` → `self._strip_lods` →
`_parser_context()` sets `UnityParseContext.strip_lods` → `parse_unity_prefab` runs
the strip after `build_hierarchy`. Patch worker does NOT re-parse prefabs, so it keeps
the constructor default (True) and is unaffected.

---

## Resolved Decisions (Q&A history)

- **Q: Does O3DE have a LOD system at all (user's premise: "if none exists, strip")?**
  A: Yes — model-internal LodRule + runtime LodConfiguration. Premise flips: LODs
  exist but are structured per-model, not per-entity. Both strip (quick) and bake
  (proper) are valid; user chose "strip now + plan the bake".
- **Q: Which level to keep?** A: **LOD0 only** (highest detail). User-selected.
- **Q: Settings home / which tab?** A: **`asset_processor.strip_lods`, Prefab Processor
  tab** (user moved it here from the initial Mesh-tab placement). Default True.
- **Q: Detect by name or by LODGroup component?** A: LODGroup component `m_LODs` is
  authoritative. Names are fallback-only, deferred.
- **Q: Stage 2 (scene) raw LODGroups?** A: Out of scope for I.1 — scene-placed prefab
  instances inherit the already-stripped Stage-1 prefab. Raw in-scene LODGroup GOs are
  rare; tracked as a follow-up (I.3b) against `scene_converter.py`'s own parse loop.

---

## Implementation Plan

### I.1 — LODGroup parse + LOD0 strip in `platforms/unity/prefab.py` ✅
- Captured `component_owner` (comp fileID → GO fileID) for every component doc in the
  `else` branch of `parse_unity_prefab`.
- Captured `lod_groups` via `_extract_lod_renderer_levels` when `'LODGroup' in doc`.
- Added `strip_lod_groups(...)` + `_remove_go_subtree(..., keep, ...)`; called after
  `build_hierarchy` when `ctx.strip_lods` and `lod_groups`.
- Added `strip_lods: bool = True`, `lod_keep_level: int = 0` to `UnityParseContext`.
- **Done:** fixture parse keeps LOD0 GO, drops LOD1/LOD2 + subtrees (strip on); keeps
  all with strip off.

### I.2 — Thread the toggle (worker param, asset_processor stage) ✅
- `IntegratedAssetProcessor.__init__` gained `strip_lods: bool = True` → `self._strip_lods`;
  `_parser_context()` passes `strip_lods=self._strip_lods`.
- `project_manager.py` `asset_processor` defaults gained `"strip_lods": True`.
- Run path snapshots `asset_processor.strip_lods` → WorkerThread → `_do_processing`
  → worker ctor.
- **Done:** worker built `strip_lods=False` → context False; default → True (unit test).

### I.3 — Prefab Processor tab GUI checkbox ✅
- "Conversion Options" section with "Strip LODs — keep LOD0 only" checkbox in
  `PrefabProcessorTab`: load in `apply_project` (suppressed), persist via
  `_collect_stage_settings` + `_on_strip_lods_changed` → `asset_processor.strip_lods`.
- **Done when:** toggling round-trips to the project file (manual GUI verify pending).

### I.3b — Stage-2 scene raw LODGroups (follow-up, deferred)
Apply the same strip to `scene_converter.py`'s in-scene non-prefab GameObjects.

### I.4+ — LodRule bake (future feature, stub)
Combine LODn FBX nodes into one model + `LodRule` in `.assetinfo`; emit one
MeshComponent with `LodConfiguration`. Requires: per-level FBX node selection wired
into `write_fbx_assetinfo`, all LOD meshes resolvable into a single model, and a
`asset_processor.lod_mode` setting (`strip` | `bake`). Expand this section on pickup.

---

## Testing matrix

| Proof | Phase | Form | Status |
|---|---|---|---|
| `strip_lod_groups` keeps LOD0 GO, drops LOD1/LOD2 GOs + subtrees | I.1 | unit | ✅ pass |
| Shared renderer across levels → keep wins | I.1 | unit | ✅ pass |
| `keep` guard: a kept GO nested under a dropped one survives | I.1 | unit | ✅ pass |
| `_extract_lod_renderer_levels` ordering / empty / null-ref | I.1 | unit | ✅ pass |
| Full `parse_unity_prefab` on LODGroup fixture, strip on/off | I.1 | unit (behavioral) | ✅ pass |
| Worker `strip_lods` ctor param reaches parse context | I.2 | unit | ✅ pass |
| Checkbox round-trips to project file | I.3 | manual/GUI | ⏳ pending |
| Editor perf recovery on a real LOD-heavy pack | I.1–I.3 | field | ⏳ pending |

Tests live in `tests/unit/test_lod_strip.py` (10 passing), run via
`QT_QPA_PLATFORM=offscreen python tests/run_all.py`. Full suite green except the
pre-existing, unrelated `tests/unit/test_terrain_data.py` external-sample decode.
