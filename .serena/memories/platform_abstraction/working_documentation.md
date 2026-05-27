---
name: platform-abstraction-working-doc
description: Living status log for the platform-abstraction refactor. Phase tracker, follow-ups, what's shipped, what remains.
metadata:
  type: project
---

# Platform Abstraction — Working Documentation

Newest entries on top. Linked plan: [[platform-abstraction-plan]].
Audit: [[platform-abstraction-audit]]. Tests: [[platform-abstraction-test-suite]].

## 2026-05-27 — All follow-ups (items 1–7) shipped ✓

The 7 deferred follow-ups from the prior pass are all closed. The
refactor is now structurally clean: every Unity-coupled body lives
under `platforms/unity/`, every O3DE-target body under `targets/o3de/`,
and the worker (`IntegratedAssetProcessor`) is a thin orchestration
shell that delegates to the platform plugin for source parsing and to
the O3DE target for output emission.

### Items shipped

**Item 6 — `legacy_unity_prefab_to_o3de.py` deprecated.**
Single-pass converter predecessor replaced with a deprecation banner
script. Body removed; the file now prints a clear message pointing at
`main_app.py` / `integrated_asset_processor.py` and exits with code 2.
Git history retains the 590-line original.

**Item 7 — `bake_fbx_transforms.py` moved to `tools/`.**
Standalone Blender headless companion (uses `bpy`; runs inside
Blender's Python, not the converter pipeline). Moved to
`tools/bake_fbx_transforms.py`; new `tools/__init__.py` documents
that scripts in this directory run outside the live converter.

**Item 4 — `Transform / UnityComponent / GameObject` promoted.**
The three Unity-source dataclasses moved to
`platforms/unity/types.py`. Re-exported from
`integrated_asset_processor` so every existing call site (worker
internals, scene converter, component processors) keeps working
unchanged. Stale `from dataclasses import dataclass, field` import
dropped from `integrated_asset_processor.py`.

**Item 5 — `Y_UP_ROTATION` promoted; writer takes `correction_quat`.**
New `platforms/unity/coordinates.py` owns
`UNITY_Y_UP_TO_O3DE_Z_UP_QUAT`. `targets/o3de/assetinfo_writer.py`
re-exports it as `Y_UP_ROTATION` for back-compat and accepts a new
optional `correction_quat` parameter on `write_fbx_assetinfo`. The
worker reads `self.platform.correction_quat` and passes it through.
`UnityPlatform.correction_quat` is a property returning the Unity
constant. Non-Unity plugins supply their own correction quaternion
via the same property.

**Item 1a — Unity prefab parsers extracted as free functions.**
`_parse_unity_prefab`, `_parse_transform`, `_parse_game_object`,
`_parse_prefab_instance_in_prefab`, `_build_hierarchy` — ~300 lines
total — moved to `platforms/unity/prefab.py` as free functions
accepting a `UnityParseContext` dataclass (`log`, `coverage`,
`component_dispatch`). The worker now carries 5-line wrappers that
build a context and delegate. Behaviour is byte-identical.

**Item 1b — O3DE prefab writers extracted as free functions.**
`_create_o3de_prefab`, `_create_container_entity`,
`_create_nested_prefab_instance`, `_create_entity_recursive`,
`_make_bare_entity`, `_write_entity_map_sidecar`,
`_load_entity_map_sidecar`, `_generate_component_id`,
`_generate_entity_id`, `_quaternion_to_euler`,
`_convert_to_o3de_coordinates` — ~720 lines total — moved to
`targets/o3de/prefab_writer.py` as free functions taking the worker
as first arg (the worker IS the natural context for these — every
state field they touch is on it). The class now carries thin
wrappers. Behaviour is byte-identical.

**Item 2 — `UnityPlatform.parse_prefab` returns a real
`PlatformPrefab`.** No longer `NotImplementedError`. The method
builds a minimal `UnityParseContext` (no-op log, throwaway coverage,
plugin's component dispatch), calls the canonical
`parse_unity_prefab` from `platforms.unity.prefab`, and converts the
resulting worker-tuple `(game_objects, transform_map)` into the
neutral `PlatformPrefab` shape. Each GameObject becomes a
`PlatformEntity` whose `transform` is converted via
`unity_transform_to_platform_transform` (Unity Transform tuples →
PlatformTransform lists; identity-preserving — no coordinate swap
since `to_o3de_coordinates` is the dedicated swizzler).

**Item 3 — `parse_unity_scene` delegates to `parse_unity_prefab`.**
Unity scene files use the same multi-document YAML format as prefabs;
the prefab walker already handles Transform / GameObject /
PrefabInstance / component blocks. `parse_unity_scene` is now a
single-line delegate. `UnityPlatform.parse_scene` reuses
`parse_prefab` (both contract methods return the same shape since
`PlatformScene` currently aliases `PlatformPrefab`).

### Final verification gate

`python tests/run_all.py` → **17 modules, 96 tests, all green.**

Three new tests landed in `unit/test_platform_contract.py` to cover
the new functional surfaces:
- `test_correction_quat_is_unity_y_up` — UnityPlatform supplies the
  expected correction quaternion.
- `test_parse_prefab_returns_platform_prefab` — `parse_prefab` builds
  a populated `PlatformPrefab` from a synthetic minimal prefab.
- `test_parse_scene_delegates_to_parse_prefab` — `parse_scene` works
  on a `.unity` file with the same multi-doc YAML shape.

### Filesystem layout (final)

```
platforms/
    __init__.py                 # PLATFORM_REGISTRY + register()
    base.py                     # SourcePlatform ABC + SUPPORTED_TABS
    types.py                    # PlatformMaterial / PlatformPrefab / ...
    unity/
        __init__.py
        types.py                # Transform / UnityComponent / GameObject (item 4)
        asset_database.py       # AssetDatabase (GUID index, .mat parser)
        shader.py               # UNITY_BUILTIN_SHADERS + resolve_shader_name
        coordinates.py          # UNITY_Y_UP_TO_O3DE_Z_UP_QUAT (item 5)
        prefab.py               # parse_unity_prefab + UnityParseContext (item 1a)
        unity_platform.py       # UnityPlatform (SourcePlatform impl)
        components/             # auto-discovered component processors

targets/
    __init__.py
    o3de/
        __init__.py
        assetinfo_writer.py     # write_fbx_assetinfo + math helpers
        prefab_writer.py        # create_o3de_prefab family (item 1b)

components/                     # LEGACY SHIM only
    __init__.py
    base.py

tools/                          # standalone helper scripts
    __init__.py
    bake_fbx_transforms.py      # Blender headless tool (item 7)

integrated_asset_processor.py   # Worker — IntegratedAssetProcessor.
                                # Thin wrappers delegate to:
                                #   platforms.unity.prefab   (parse)
                                #   targets.o3de.prefab_writer (emit)
                                #   targets.o3de.assetinfo_writer
                                #   platforms.unity.shader / .asset_database
                                # Worker bodies remaining:
                                #   - process_prefab orchestration
                                #   - _process_material / _process_mesh / _process_texture
                                #   - state-index recording + patch worker
                                #   - FBX binary readers (read_fbx_*)
                                #   - _process_metallic_gloss_as_roughness (Pillow path)

legacy_unity_prefab_to_o3de.py  # DEPRECATION BANNER (item 6)
```

### Reduction summary

`integrated_asset_processor.py` shrank from **2987 → 1536 lines** (a
~49% reduction). The removed bodies now live in their canonical homes
under `platforms/unity/` and `targets/o3de/`.

| Module                                       | Lines |
|----------------------------------------------|------:|
| `platforms/unity/asset_database.py`          |  ~430 |
| `platforms/unity/shader.py`                  |   ~85 |
| `platforms/unity/prefab.py`                  |  ~360 |
| `platforms/unity/coordinates.py`             |   ~55 |
| `platforms/unity/types.py`                   |  ~105 |
| `platforms/unity/unity_platform.py`          |  ~475 |
| `targets/o3de/assetinfo_writer.py`           |  ~245 |
| `targets/o3de/prefab_writer.py`              |  ~600 |
| `platforms/base.py`                          |  ~165 |
| `platforms/types.py`                         |  ~145 |
| `platforms/__init__.py`                      |   ~90 |
| **Total extracted to platform / target homes** | **~2755** |

The worker keeps the F-9 / F-8 / F-9.I.x specific logic — state index
recording, dirty detection, patch worker, the assetinfo-mesh state
join — because those are PAC orchestration, not platform code.

## Phase + follow-up tracker — final

- [x] Phase A — Mechanical move (directory scaffolding + AssetDatabase + writers + shader)
- [x] Phase B — SourcePlatform ABC + neutral types + UnityPlatform + registry
- [x] Phase C — Wire platform registry into worker
- [x] Phase D — Project schema namespacing + migration
- [x] Phase E — Switch UX (dropdown + toast + tab refresh)
- [x] Follow-up 1a — `platforms/unity/prefab.py` body extraction
- [x] Follow-up 1b — `targets/o3de/prefab_writer.py` body extraction
- [x] Follow-up 2 — `UnityPlatform.parse_prefab` returns real `PlatformPrefab`
- [x] Follow-up 3 — `parse_unity_scene` delegates to `parse_unity_prefab`
- [x] Follow-up 4 — Unity source-data types promoted
- [x] Follow-up 5 — `correction_quat` parameter + Unity coordinates module
- [x] Follow-up 6 — Per-platform UI tab gating
- [x] Follow-up 7 — `bake_fbx_transforms.py` moved to `tools/`

Bonus:
- [x] `legacy_unity_prefab_to_o3de.py` deprecated.
- [x] Test suite (`tests/`) with 17 modules, 96 tests covering every
      verifiable surface. Replaces the ad-hoc `verify_*.py` scripts
      that lived briefly during the refactor.

## Third-party plugin developer contract (final)

A non-Unity developer landing on this codebase finds the following
artefacts when authoring a `platforms/<engine>/` plugin:

1. **Audit memo** (`platform_abstraction/audit.md`) — PAC vs UNS map.
2. **Plan memo** (`platform_abstraction/platform_abstraction_plan.md`) —
   the locked refactor sequence + design Q&A.
3. **Test-suite memo** (`platform_abstraction/test_suite.md`) — the
   verification coverage matrix + extension recipe for new plugins.
4. **Contract** (`platforms/base.py::SourcePlatform`) — ABC with full
   docstrings on every abstract method + `SUPPORTED_TABS` for UI
   gating.
5. **Neutral types** (`platforms/types.py`) — `PlatformMaterial`,
   `PlatformEntity`, `PlatformPrefab`, `PlatformTransform`,
   `AssetIndex`.
6. **Reference plugin** (`platforms/unity/`) — fully fleshed out
   reference at ~1450 lines across 7 modules.
7. **Target-side writers** (`targets/o3de/`) — shared O3DE emission
   code the plugin doesn't need to re-implement.
8. **Test recipe** (`tests/README.md`) — how to mirror Unity's test
   coverage for a new plugin's parse/emit paths.

Estimated plugin size for a new engine: **1500–2000 lines** —
matched against Unity's reference. The contract is fully
documented; every layer above is shared infrastructure.

## What remains in the worker (post-refactor)

`integrated_asset_processor.py` (~1536 lines) now holds only the
genuinely PAC orchestration logic:

- `CoverageTracker` (~115 lines) — engine-neutral; tracks what was
  handled vs unhandled during a run.
- `read_fbx_mesh_node_names` / `read_fbx_material_names` /
  `read_fbx_up_axis` / `build_fbx_node_paths` (~165 lines) — FBX
  binary primitives. Could move to a future `format/fbx/` module if
  non-FBX mesh formats land.
- `IntegratedAssetProcessor` (~1170 lines) — the worker class:
  `__init__`, `process_prefab` (orchestrates the parse → emit flow),
  `_process_material` / `_process_mesh` / `_process_texture` / `_process_metallic_gloss_as_roughness`
  (per-asset emission orchestration; profile chain resolution + state
  index recording), `patch()` (F-9 dirty-detect re-emit), `to_outputs`
  / `state_index` (project-file persistence). Plus the thin wrappers
  to the moved code.

The worker is now a true orchestration shell. Adding a new source
engine doesn't touch this file at all.

## Earlier entries

(See git history for prior phase-completion entries: Phase A→E shipped,
test suite shipped, the initial 6-follow-up batch.)
