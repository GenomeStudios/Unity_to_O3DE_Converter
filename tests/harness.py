"""
=============================================================================
TEST MODULE HARNESS
=============================================================================

Each ``test_*.py`` module defines test functions and ends with::

    if __name__ == "__main__":
        raise SystemExit(run_module_tests(globals()))

``run_module_tests`` walks the module's globals, picks out every
function named ``test_*``, runs them in source order, and reports
PASS/FAIL counts. Failures don't stop the run — the harness collects
every failure so a single broken test doesn't mask others.

The repo-level runner (``tests/run_all.py``) reuses this harness by
importing each test module and calling ``run_module_tests`` on its
globals.
"""

import inspect
import sys
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


# Make the repo root importable so test modules can do
# ``from project_manager import ...`` regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Reconfigure stdout to UTF-8 so the ✓ / ✗ glyphs print under the
# Windows cp1252 console default. Idempotent — repeat calls are a no-op.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def _list_tests(module_globals: Dict) -> List[Tuple[str, Callable]]:
    """Return ``[(name, fn), ...]`` for every ``test_*`` function in
    ``module_globals``, ordered by source line number."""
    tests: List[Tuple[str, Callable, int]] = []
    for name, obj in module_globals.items():
        if not name.startswith("test_"):
            continue
        if not callable(obj):
            continue
        try:
            line = inspect.getsourcelines(obj)[1]
        except (OSError, TypeError):
            line = 0
        tests.append((name, obj, line))
    tests.sort(key=lambda t: t[2])
    return [(n, fn) for n, fn, _ in tests]


def run_module_tests(module_globals: Dict, *,
                     header: Optional[str] = None) -> int:
    """Run every ``test_*`` function in ``module_globals``. Returns 0
    when every test passed, 1 otherwise. Stdout shows per-test
    status; failures include the traceback so the user can jump to
    the offending line."""
    name = module_globals.get("__name__", "<test module>")
    if header is None:
        header = name
    tests = _list_tests(module_globals)
    if not tests:
        print(f"[{header}] no tests found")
        return 0

    print(f"\n=== {header}  ({len(tests)} test(s)) ===")
    failures: List[Tuple[str, str]] = []
    passed = 0
    for fn_name, fn in tests:
        try:
            fn()
            print(f"  ✓ {fn_name}")
            passed += 1
        except AssertionError as exc:
            failures.append((fn_name, traceback.format_exc()))
            print(f"  ✗ {fn_name}  — assertion failed: {exc}")
        except Exception as exc:
            failures.append((fn_name, traceback.format_exc()))
            print(f"  ✗ {fn_name}  — {type(exc).__name__}: {exc}")

    if failures:
        print(f"\n  {passed}/{len(tests)} passed, {len(failures)} FAILED:")
        for fn_name, tb in failures:
            print(f"\n  ── {fn_name} ──")
            for line in tb.splitlines():
                print(f"    {line}")
        return 1
    print(f"\n  {passed}/{len(tests)} passed.")
    return 0
