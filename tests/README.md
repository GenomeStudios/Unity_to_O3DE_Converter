# Converter Test Suite

End-to-end + integration + unit verifications for the Unity → O3DE
Converter. Plain-Python assert-based tests (no pytest dependency) that
match the existing codebase style.

## Running

```bash
python tests/run_all.py                  # everything
python tests/run_all.py unit             # only tests/unit/
python tests/run_all.py ui dirty         # any path containing 'ui' OR 'dirty'
python tests/run_all.py --quiet          # short summary

# Or run individual modules:
python tests/unit/test_materialtype_resolver.py
python tests/integration/test_material_emission.py
python tests/ui/test_engine_dropdown.py
```

Exit code is 0 when every test passed, 1 otherwise. Failures are
collected end-to-end — one broken test doesn't stop the rest.

The runner sets `QT_QPA_PLATFORM=offscreen` and
`U2O_SKIP_CLOSE_PROMPT=1` so UI tests don't need a display server
or generate close-prompt dialogs.

## Layout

```
tests/
    __init__.py
    harness.py                    # run_module_tests() + path bootstrap + UTF-8 stdout
    run_all.py                    # walk + dispatch every test_*.py
    README.md                     # this file
    fixtures/                     # shared test fixtures
        __init__.py
        unity_tree.py             # synthetic Unity asset tree + stable GUIDs
        qt_app.py                 # headless QApplication helper
    unit/                         # single-module assertions
        test_materialtype_resolver.py
        test_default_profile.py
        test_legacy_migration.py
        test_external_mod.py
        test_platform_contract.py
        test_platform_registry.py
        test_preflight.py
        test_assetinfo_writer.py
        test_components_shim.py
    integration/                  # full-worker, end-to-end emission
        test_material_emission.py
        test_patch_worker.py
        test_orchestrator.py
        test_platform_switching.py
    ui/                           # PySide6 widget tests (offscreen)
        test_engine_dropdown.py
        test_dirty_markers.py
        test_shader_mappings_dialog.py
        test_tab_gating.py
```

## Test layer guidelines

- **`tests/unit/`** — single-module assertions, no end-to-end emission,
  no Qt widgets. Each test should be < 10 lines of logic. If a test
  needs to construct a worker or a window, it belongs in
  integration/ or ui/.
- **`tests/integration/`** — full `IntegratedAssetProcessor` runs
  against the synthetic Unity tree. Each test typically spins up a
  tempfs tree, runs `_process_material` / `patch()` / etc., and
  asserts on the emitted `.material` / `.assetinfo` files.
- **`tests/ui/`** — PySide6 widgets under the off-screen Qt platform.
  Each test imports `tests.fixtures.qt_app.get_qt_app()` for the
  shared `QApplication`.

## Writing a new test

1. Pick the right layer (unit / integration / ui).
2. Copy the prelude from an existing test:

   ```python
   """One-line module purpose."""

   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

   from tests.harness import run_module_tests
   # plus any tests.fixtures.* imports you need
   ```

3. Define `def test_<descriptive_name>():` functions with `assert`
   statements. No setup/teardown classes — use `tempfile.TemporaryDirectory()`
   or per-test cleanup.

4. End the file with:

   ```python
   if __name__ == "__main__":
       raise SystemExit(run_module_tests(globals()))
   ```

5. Smoke-run it standalone: `python tests/<layer>/test_<name>.py`.
6. Re-run the full suite: `python tests/run_all.py`.

## Adding tests for a new source-engine plugin

When a third-party developer ships a non-Unity plugin (per
`.serena/memories/platform_abstraction/`), they should add tests
mirroring the Unity coverage. Suggested per-plugin structure:

```
tests/
    fixtures/
        unreal_project.py            # synthetic Unreal Content/ tree
        # or godot_project.py, blender_project.py — whatever the
        # plugin's `validate_scope_root` expects.
    unit/
        test_unreal_platform_contract.py     # mirrors test_platform_contract.py
        test_unreal_default_profile.py       # mirrors test_default_profile.py
        # one file per engine-specific concern
    integration/
        test_unreal_material_emission.py     # mirrors test_material_emission.py
        test_unreal_patch_worker.py
```

The shared fixtures + harness work for any plugin — only the synthetic
asset tree fixture is engine-specific. The `run_all.py` runner picks
up new test files automatically.

## Coverage as of 2026-05-27

| Layer        | Modules | Tests | Surfaces |
|--------------|---------|-------|----------|
| unit         | 9       | 62    | F-9 resolver, default profile, legacy migration, external-mod, platform contract, registry, preflight, assetinfo writer, components shim |
| integration  | 4       | 16    | F-9 emission, patch worker, F-8 orchestrator, Phase-D switching |
| ui           | 4       | 15    | Phase-E dropdown, F-9.I.6 markers, F-6 shader dialog, follow-up-6 tab gating |
| **total**    | **17**  | **93** | |

## Maintenance contract

- Tests are **artefacts of the codebase**. If a feature changes its
  observable behaviour, the relevant test SHOULD break — that's the
  signal the doc / contract drifted.
- Don't delete a failing test to fix CI. Either fix the regression
  or update the test to match the new contract (after a design
  decision is locked).
- New PRs that touch a covered surface should also touch the
  matching test file.
