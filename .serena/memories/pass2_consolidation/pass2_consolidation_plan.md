# Pass-2 Consolidation — Plan

**Status:** Design-locked. Sequential implementation.
**Topic folder:** `pass2_consolidation/`
**Pair file:** `mem:pass2_consolidation/working_documentation`

---

## Why this exists

Pass-1 cleanup (2026-05-27) deleted the deprecation banner, trimmed the dead
Tkinter shell out of `unity_scene_converter_gui.py`, fixed `targets/o3de/__init__.py`
doc drift, and refreshed the working-status memory.

What's left after Pass-1 is **structural debt from the platform-abstraction
refactor**: two root-level Unity-specific workers (`unity_scene_converter_gui.py`,
`terrain_material_processor.py`) never made it into `platforms/unity/`,
a `components/` shim still sits at the root re-exporting from
`platforms.unity.components`, the same `Transform`/`GameObject` dataclasses
are defined twice, and the scene converter has its own copy of the
Unity-YAML parser that duplicates `platforms.unity.prefab.parse_unity_prefab`.

Pass-2 fully aligns the codebase with the Project + Platform format the
refactor established. User direction (2026-05-27): "no projects are
actively using this system yet, so we have no need to preserve dated
systems" — this lifts the back-compat constraint that prevented dropping
shims and renaming public symbols.

---

## Design

### Target structure

```
platforms/
    base.py
    types.py
    __init__.py
    unity/
        __init__.py
        unity_platform.py        # SourcePlatform impl
        asset_database.py
        coordinates.py
        prefab.py                # canonical parser (Pass-2 single source of truth)
        shader.py
        types.py                 # canonical Transform / GameObject / UnityComponent
        scene_converter.py       # NEW — was root-level unity_scene_converter_gui.py
        terrain.py               # NEW — was root-level terrain_material_processor.py
        components/              # canonical processor home
            __init__.py
            base.py
            <every individual processor>.py
targets/
    o3de/...                     # unchanged
integrated_asset_processor.py    # Stage-1 worker (still root for now)
main_app.py                      # GUI (still root)
project_manager.py               # schema (still root)
preflight.py                     # preflight (still root)
tools/                           # standalone helpers (unchanged)
tests/                           # unchanged
```

After Pass-2, the **root contains only the four orchestration scripts
(`main_app`, `integrated_asset_processor`, `project_manager`, `preflight`)
plus their two config/launcher files (`converter_settings.json`,
`UnityToO3DE_Converter.bat`)**. Every Unity-specific file lives under
`platforms/unity/`.

### What survives, what dies

| Path | Pass-2 outcome |
|---|---|
| `unity_scene_converter_gui.py` | **Moved** → `platforms/unity/scene_converter.py`. Duplicate `Transform`/`GameObject` deleted; imports `platforms.unity.types`. Internal `parse_unity_scene` deleted; delegates to `platforms.unity.prefab.parse_unity_scene`. Internal `convert_to_o3de_coordinates` deleted; calls `targets.o3de.prefab_writer.convert_to_o3de_coordinates`. |
| `terrain_material_processor.py` | **Moved** → `platforms/unity/terrain.py`. Class kept; imports rewritten. |
| `components/__init__.py` | **Deleted.** All callers switch to `platforms.unity.components`. |
| `components/base.py` | **Deleted.** All callers switch to `platforms.unity.components.base`. |
| `tests/unit/test_components_shim.py` | **Deleted.** Tests a contract that's being removed. |
| `integrated_asset_processor.py` lines 26-27 | Re-pointed: `from platforms.unity.components import build_dispatch_table` + `from platforms.unity.components.base import ProcessingContext`. |
| `targets/o3de/prefab_writer.py` line 51 | Re-pointed: `from platforms.unity.components.base import ProcessingContext`. |
| `main_app.py:3597` | Re-pointed: `from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter`. |
| `main_app.py:5850` | Re-pointed: `from platforms.unity.terrain import TerrainMaterialProcessor`. |
| `platforms/unity/prefab.py:418-424` | Stale comment about "two parser paths can be unified" gets deleted — Pass-2 IS the unification. |
| `.serena/memories/project/converter_working_status.md` | Sections referencing `unity_scene_converter_gui.py` and `terrain_material_processor.py` updated to use new paths. |

### What does NOT change

- `SourcePlatform` ABC. The contract is fine; the work is migrating
  Unity-specific code under the plugin folder, not redesigning the contract.
- Tab orchestration in `main_app.py`. Tab classes still construct
  `UnitySceneConverter` and `TerrainMaterialProcessor` directly. The
  speculative "platform exposes worker factories" abstraction is YAGNI
  until a second platform actually ships its own scene/terrain workers.
- `PlatformPrefab` / `PlatformScene` neutral types. The plugin's
  `parse_prefab` / `parse_scene` still produce these for plugin-contract
  callers. The worker continues to consume the Unity dict shape via
  `parse_unity_prefab` because the component-processor pipeline is
  Unity-shaped and rewriting it to consume `PlatformEntity.raw_components`
  is a separate, larger refactor.
- Stage-1 worker location. `integrated_asset_processor.py` stays at the
  root because main_app's tab classes still construct it as a worker.
  It already delegates to `platforms/unity/`; further migration would
  require splitting it into a platform-driven harness, which is also
  separate, larger work.

### Resolved decisions

**Q1: Drop the `components/` re-export shim, or keep it forever?**
A: **Drop it.** The user explicitly authorised dropping back-compat systems.
Three internal callers + one test ping it; all four are touchable in this
pass.

**Q2: Should `UnitySceneConverter` re-export from
`platforms.unity.scene_converter` like Pass-1 left it for legacy paths?**
A: **No re-export shim at the old path.** Root-level
`unity_scene_converter_gui.py` is deleted, not stubbed. Same for
`terrain_material_processor.py`.

**Q3: Does Stage 2 keep its own `Transform` / `GameObject` after the move?**
A: **No.** It imports them from `platforms.unity.types`. The dataclass
fields are already a superset of what Stage 2 needs.

**Q4: Two parser paths — unify them or leave for later?**
A: **Unify in I.4.** `platforms.unity.prefab.parse_unity_scene` already
delegates to `parse_unity_prefab`. The scene converter's local
`parse_unity_scene` + the four private parsers (`_parse_transform`,
`_parse_game_object`, `_parse_prefab_instance`, `_build_hierarchy`)
get deleted; the scene converter constructs a `UnityParseContext` and
calls the canonical free function.

**Q5: What goes in `targets/o3de/` now?**
A: Nothing changes in Pass-2. `targets/o3de/__init__.py` was fixed in
Pass-1 to reflect the actual contents. Future material_writer.py /
materialtype_resolver.py extractions are still future work.

**Q6: Does main_app know about the platform plugin yet?**
A: Not for worker construction. `main_app.py` keeps direct
`from platforms.unity.scene_converter import ...` imports. When a second
platform ships, switch to `project.platform_instance().scene_converter_cls()`.

**Q7: Does the scene converter pick up the same platform-DI seam Stage-1
uses (`platform.bind_asset_db(...)`)?**
A: **Not in Pass-2.** Stage 2 currently has no AssetDatabase at all (a
known limitation in the working-status memory). Wiring it up is a
separate, named follow-up — out of scope here. Pass-2 is a structural
move + dedup pass; it doesn't add features.

**Q8: Test suite migration?**
A: The 17 modules / 96 tests in `tests/` run after every stage. One
test module (`tests/unit/test_components_shim.py`) is deleted in I.3,
bringing the count to 16. No new test modules are added — Pass-2 is
mechanical refactoring, and existing tests cover the moved code's
behaviour.

---

## Implementation plan

Each stage ends with: **build green + `py -3.13 tests/run_all.py` passes**.

### I.1 — Migrate scene converter into the platform

**Steps**
1. Create `platforms/unity/scene_converter.py` with the body of the
   current `unity_scene_converter_gui.py:1-1117`, minus the duplicate
   `Transform` / `GameObject` definitions (delete lines 27-61).
2. Top of file imports `Transform`, `GameObject` from
   `platforms.unity.types`, and `CoverageTracker` from
   `integrated_asset_processor`. (CoverageTracker stays where it is for
   Pass-2; it's worker-side state, not platform-side.)
3. Update `main_app.py:3597` import.
4. Delete root-level `unity_scene_converter_gui.py`.
5. Run tests.

**Done when**
- `platforms/unity/scene_converter.py` exists with `PrefabDatabase` +
  `UnitySceneConverter` classes.
- Root `unity_scene_converter_gui.py` does not exist.
- `tests/run_all.py` green.
- `main_app.py` Scene tab still imports cleanly (verified by smoke import
  in the test harness via `test_engine_dropdown` / orchestrator tests).

**Test alongside**
- Existing tests cover the import path (orchestrator test, dirty markers
  test, engine dropdown). No new tests added.

---

### I.2 — Migrate terrain processor into the platform

**Steps**
1. Create `platforms/unity/terrain.py` with the body of
   `terrain_material_processor.py`.
2. Top-of-file import becomes `from platforms.unity.asset_database
   import AssetDatabase` (replacing the legacy
   `from integrated_asset_processor import AssetDatabase`).
3. Update `main_app.py:5850` import.
4. Update `tests/integration/test_material_emission.py:138` reference
   in comment (or in code if it imports this module).
5. Delete root-level `terrain_material_processor.py`.
6. Run tests.

**Done when**
- `platforms/unity/terrain.py` exists with `TerrainMaterialProcessor`.
- Root `terrain_material_processor.py` does not exist.
- `tests/run_all.py` green.

**Test alongside**
- `tests/integration/test_material_emission.py` already exercises the
  terrain path via the same `AssetDatabase.parse_material` it consumes.
  No new tests added.

---

### I.3 — Drop the `components/` shim

**Steps**
1. Update `integrated_asset_processor.py:26-27` to import from
   `platforms.unity.components` directly.
2. Update `targets/o3de/prefab_writer.py:51` likewise.
3. Update `platforms/unity/scene_converter.py:22-23` (post-I.1 path)
   likewise.
4. Delete `components/__init__.py` and `components/base.py`.
5. Delete root `components/` directory.
6. Delete `tests/unit/test_components_shim.py`.
7. Run tests.

**Done when**
- Root `components/` directory does not exist.
- `tests/run_all.py` green at 16 modules.

**Test alongside**
- The deleted shim test is replaced by the implicit coverage from every
  test that exercises a component processor end-to-end (material emission,
  prefab override propagation, etc.).

---

### I.4 — Unify Unity parser paths

**Steps**
1. In `platforms/unity/scene_converter.py`, delete:
   - `_parse_transform`
   - `_parse_game_object`
   - `_parse_prefab_instance`
   - `_build_hierarchy`
   - The body of `parse_unity_scene` (keep the method as a thin wrapper).
2. Rewrite `parse_unity_scene` to:
   - Construct a `UnityParseContext(log=self.log, coverage=self.coverage,
     component_dispatch=self.component_dispatch)`.
   - Call `platforms.unity.prefab.parse_unity_scene(ctx, scene_path)`.
   - Receive the worker-tuple `(game_objects, transforms)` and assign
     into `self.game_objects` / `self.transforms`.
   - Re-derive `self.transform_to_gameobject` and (if the worker tuple
     doesn't already populate it) `prefab_instances` from
     the parsed graph.
3. Delete `_convert_to_o3de_coordinates` in scene_converter; call
   `targets.o3de.prefab_writer.convert_to_o3de_coordinates` directly.
4. Delete the `platforms/unity/prefab.py` lines 418-424 comment about
   "the two parser paths can be unified into this one" (it's done).
5. Run tests.

**Done when**
- `platforms/unity/scene_converter.py` has NO duplicate parser code.
- Every parse goes through `platforms.unity.prefab`.
- `tests/run_all.py` green.
- A scene file with prefab instances + components still produces the
  same `PrefabDatabase` resolutions and emitted level structure as
  before (covered by `test_orchestrator` end-to-end).

**Test alongside**
- `test_orchestrator` exercises the full Stage-2 pipeline on a fixture
  scene with prefab instances. This is the unification's regression test.
- If parser semantics diverge in subtle ways (component-block collection
  ordering, prefab_instance fileID mapping), this test will catch it.
  If it surfaces a real divergence, **STOP** and re-evaluate I.4 before
  proceeding — do NOT paper over with a one-off shim.

---

### I.5 — Final verification + memory update

**Steps**
1. Full `py -3.13 tests/run_all.py` — must be 16/16 green.
2. Manual smoke launch `py -3.13 main_app.py` to confirm the GUI opens,
   the Scene tab + Terrain tab still construct.
3. Update `mem:project/converter_working_status` to reference the new
   paths and drop "pending Pass-2 migration" wording.
4. Update `AGENTICS_GUIDELINES.md` "First-session orientation" if any
   guidance references the old paths.
5. Update `mem:pass2_consolidation/working_documentation` with the
   final landed state.
6. Stop — Unity feature work resumes from a clean Project+Platform tree.

**Done when**
- Tests green at 16/16.
- GUI launches without error.
- Memories reflect post-Pass-2 reality.

---

## Testing matrix

| Stage | Proof |
|---|---|
| I.1 | `tests/run_all.py` green; main_app imports `UnitySceneConverter` from new path. |
| I.2 | `tests/run_all.py` green; main_app imports `TerrainMaterialProcessor` from new path. |
| I.3 | `tests/run_all.py` green at 16 modules; no caller still imports from root `components`. |
| I.4 | `tests/run_all.py` green; `test_orchestrator` passes the full Stage-2 path through the unified parser. |
| I.5 | Full suite green + GUI launches + memories refreshed. |

If I.4's `test_orchestrator` regresses, the unification is wrong — do not
proceed to I.5 until resolved.

---

## Out of scope

These are referenced for context but **NOT** part of Pass-2:

- **AssetDatabase wiring in Stage 2** — Stage 2 still has no asset DB,
  so unowned-entity mesh/material emission stays silent. Listed as
  "Next Priority" in working-status; gets its own plan when picked up.
- **Renderer-component fileIDs in entity-map** — listed as "Next Priority"
  in working-status; gets its own plan.
- **F-7 terrain heightmap extraction** — still deferred from F-roadmap.
- **F-10 profile editor UI** — has its own plan at
  `mem:profile_editor/profile_editor_plan`.
- **Material writer extraction to `targets/o3de/material_writer.py`** —
  documented as future in the now-corrected `targets/o3de/__init__.py`
  docstring; gets its own plan.
- **Stage-1 worker migration into `platforms/unity/`** — `IntegratedAssetProcessor`
  is large enough that moving it warrants its own pass + harness redesign.
- **Speculative second-platform plugin** — no Unreal/Godot/Blender plugin
  is being authored in Pass-2; SourceEngine slots stay non-destructive.
