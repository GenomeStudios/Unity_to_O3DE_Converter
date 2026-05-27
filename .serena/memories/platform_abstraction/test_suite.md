---
name: platform-abstraction-test-suite
description: Persistent verification surface for the converter. Replaces the ad-hoc verify_*.py scripts that lived briefly during the refactor. Designed to be extended by non-Unity plugin authors.
metadata:
  type: project
---

# Converter Test Suite

Plain-Python assert-based tests living under `tests/`. Replaces the
`verify_*.py` scripts that were written and deleted between phases of
the F-7/F-8/F-9 + platform-abstraction work. The suite is the
permanent verification surface — every behavioural commitment from
those features is covered.

## Layout

```
tests/
    harness.py                    # run_module_tests() + path bootstrap + UTF-8 stdout
    run_all.py                    # walk + dispatch every test_*.py
    README.md                     # how to add tests + extend for new platforms
    fixtures/
        unity_tree.py             # synthetic Unity asset tree + GUIDS constants
        qt_app.py                 # headless QApplication helper
    unit/         (9 modules, 62 tests)
        test_materialtype_resolver.py
        test_default_profile.py
        test_legacy_migration.py
        test_external_mod.py
        test_platform_contract.py
        test_platform_registry.py
        test_preflight.py
        test_assetinfo_writer.py
        test_components_shim.py
    integration/  (4 modules, 16 tests)
        test_material_emission.py
        test_patch_worker.py
        test_orchestrator.py
        test_platform_switching.py
    ui/           (4 modules, 15 tests)
        test_engine_dropdown.py
        test_dirty_markers.py
        test_shader_mappings_dialog.py
        test_tab_gating.py
```

**Total: 17 modules, 93 tests, all green.**

## Design choices

- **No pytest dependency.** The codebase has no metadata files and no
  requirements.txt; the user runs Python scripts directly. Tests
  match that style: `assert` statements + a `run_module_tests`
  harness that emulates pytest's per-test PASS/FAIL reporting.
- **One test module per concern.** Splitting the work this way lets
  the runner filter by name (`python tests/run_all.py unit dirty`)
  and lets contributors load the right file in their editor without
  scrolling.
- **Shared fixtures, not shared setup classes.** The synthetic Unity
  tree is built by `tests.fixtures.unity_tree.build_unity_tree(root)`
  with stable GUID constants from `GUIDS`. The Qt app is a singleton
  via `tests.fixtures.qt_app.get_qt_app()`. No `unittest.TestCase`,
  no `pytest` fixtures — plain function calls.
- **Headless Qt.** `QT_QPA_PLATFORM=offscreen` + `U2O_SKIP_CLOSE_PROMPT=1`
  set by the fixtures module so UI tests don't pop windows or hang
  on close-prompt dialogs.
- **UTF-8 stdout.** The harness reconfigures stdout to UTF-8 so
  Catppuccin glyphs (↻ ✎ ★ ⚠) print under the Windows cp1252 default.

## Coverage by surface

| Surface | Tests | Source modules covered |
|---|---|---|
| Materialtype resolver (F-9.I.1) | 7 | `project_manager.resolve_materialtype_path` |
| Default shader profile (F-9.I.1b) | 10 | `project_manager.DEFAULT_SHADER_PROFILE` + `_default_stages` |
| Legacy `from_json` migrations | 4 | Pre-F-9 + pre-Phase-D shapes |
| External-modification detection (F-9.I.6b) | 6 | `project_manager.detect_externally_modified` |
| Platform contract + UnityPlatform conformance (Phase B + F-up 5/6) | 11 | `platforms.base`, `platforms.types`, `UnityPlatform` |
| Platform registry (Phase B) | 6 | `platforms.__init__` |
| Preflight (F-8) | 5 | `preflight.py` check functions + ack snapshots |
| Assetinfo writer (F-9.I.3) | 10 | `targets.o3de.assetinfo_writer` |
| Components shim (F-up 3) | 3 | Legacy `components/` re-exports |
| Material emission end-to-end (F-9.I.2/I.4) | 7 | `IntegratedAssetProcessor._process_material` |
| Patch worker (F-9.I.5) | 2 | `IntegratedAssetProcessor.patch()` |
| Pipeline orchestrator (F-8.I.3-I.5) | 3 | `main_app.PipelineOrchestrator` |
| Platform switching (Phase D) | 4 | `Project.set_active_platform` + roundtrip |
| Engine dropdown UX (Phase E) | 4 | `ProjectHeaderBanner._on_scope_changed` + toast |
| Dirty + external-mod UI markers (F-9.I.6/I.6b) | 4 | `MaterialTab._refresh_inventory` |
| Shader Mappings popout (F-6 + F-9.I.1b) | 4 | `ShaderMappingsDialog` |
| Per-platform tab gating (F-up 6) | 3 | `MainWindow._refresh_platform_tabs` + `SUPPORTED_TABS` |

## Extending for a non-Unity plugin

Per `.serena/memories/platform_abstraction/audit.md`, a third-party
plugin author shipping (e.g.) `platforms/unreal/` adds tests under
the same `tests/<layer>/` directories. Suggested mirrors:

- `tests/fixtures/unreal_project.py` — synthetic Unreal `Content/`
  tree (parallel to `unity_tree.py`).
- `tests/unit/test_unreal_platform_contract.py` — parallel to
  `test_platform_contract.py` but instantiates `UnrealPlatform`.
- `tests/integration/test_unreal_material_emission.py` — parallel to
  `test_material_emission.py` but uses the Unreal fixtures.

The shared harness + `run_all.py` picks up the new files
automatically. No code changes outside the new plugin's tests.

## When to run

- **Before every commit** that touches core code paths
  (`integrated_asset_processor.py`, `project_manager.py`,
  `preflight.py`, `main_app.py`, `platforms/*`, `targets/o3de/*`).
  Single command: `python tests/run_all.py`.
- **As a feature-development guard.** If a new feature lands a new
  surface, add a test file in the same PR.
- **As a third-party contract verifier.** External plugins should
  pass the same suite (their plugin code can extend with platform-
  specific tests but the existing ones must still pass).

## Maintenance contract

- A failing test is a signal that observable behaviour or the
  documented contract drifted. Don't delete; either fix the regression
  or update the test to match the locked design decision.
- The synthetic Unity tree (`tests/fixtures/unity_tree.py`) uses
  STABLE GUID constants (`GUIDS`). Tests address specific entries
  by these GUIDs. If the fixture grows (more materials / textures /
  shaders), the GUIDS dict grows in parallel — never replace existing
  ones.
- The harness writes ✓ / ✗ glyphs. UTF-8 stdout reconfigure is
  module-level on import; if a future Python release breaks
  `sys.stdout.reconfigure`, fall back to plain ASCII (PASS / FAIL).
