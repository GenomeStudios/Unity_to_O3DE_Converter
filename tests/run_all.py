"""
=============================================================================
TEST RUNNER  (tests/run_all.py)
=============================================================================

Walks every ``test_*.py`` under ``tests/unit/``, ``tests/integration/``,
and ``tests/ui/``, imports each, and runs its ``test_*`` functions
through ``tests.harness.run_module_tests``.

Usage::

    python tests/run_all.py            # everything
    python tests/run_all.py unit       # only unit/
    python tests/run_all.py ui dirty   # any file whose path contains 'ui'
                                       # OR 'dirty'
    python tests/run_all.py --quiet    # one-line summary only

Exit code: 0 on full pass, 1 if any test failed. Failures are
collected end-to-end — one broken test doesn't stop the rest.
"""

import importlib.util
import sys
from pathlib import Path


# Make the repo importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Reconfigure stdout to UTF-8 so summary glyphs print cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


from tests.harness import run_module_tests


_TESTS_ROOT = Path(__file__).resolve().parent
_DIRS = ("unit", "integration", "ui")


def _discover() -> list:
    """Return ``[(path, label), ...]`` for every test_*.py under the
    test subdirectories. ``label`` is the path relative to tests/
    for use in headers."""
    tests = []
    for sub in _DIRS:
        d = _TESTS_ROOT / sub
        if not d.is_dir():
            continue
        for path in sorted(d.glob("test_*.py")):
            label = f"{sub}/{path.name}"
            tests.append((path, label))
    return tests


def _filter(tests: list, terms: list) -> list:
    if not terms:
        return tests
    out = []
    for path, label in tests:
        if any(t in label for t in terms):
            out.append((path, label))
    return out


def _load_module(path: Path):
    """Load ``path`` as a fresh module so each test file gets a clean
    global namespace."""
    spec = importlib.util.spec_from_file_location(
        f"_runner_{path.stem}", path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv: list) -> int:
    quiet = "--quiet" in argv
    terms = [a for a in argv if not a.startswith("--")]
    tests = _filter(_discover(), terms)
    if not tests:
        print("No test files matched.")
        return 0

    print(f"\n{'=' * 70}")
    print(f"Converter test suite — {len(tests)} module(s)")
    if terms:
        print(f"Filter: {', '.join(terms)}")
    print(f"{'=' * 70}")

    failures: list = []
    for path, label in tests:
        try:
            mod = _load_module(path)
        except Exception as exc:
            print(f"\n✗ {label}: import failed — {type(exc).__name__}: {exc}")
            failures.append(label)
            continue
        rc = run_module_tests(mod.__dict__, header=label)
        if rc != 0:
            failures.append(label)

    print(f"\n{'=' * 70}")
    if failures:
        print(f"FAILED — {len(failures)}/{len(tests)} module(s) had failures:")
        for label in failures:
            print(f"  ✗ {label}")
        return 1
    print(f"PASSED — {len(tests)}/{len(tests)} module(s) green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
