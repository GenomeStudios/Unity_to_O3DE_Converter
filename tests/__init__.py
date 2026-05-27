"""
=============================================================================
TESTS PACKAGE
=============================================================================

End-to-end + integration + unit verifications for the converter.

Layout::

    tests/
        __init__.py
        run_all.py                 ← walk every test_*.py and report
        README.md                  ← how to add tests + extend for new platforms
        fixtures/                  ← shared test fixtures
            __init__.py
            unity_tree.py          ← synthetic Unity asset tree builder
            qt_app.py              ← headless QApplication helper
        unit/                      ← single-module assertions
            test_*.py
        integration/               ← full-worker, end-to-end emission
            test_*.py
        ui/                        ← MainWindow / tab / banner widgets
            test_*.py

Tests are PLAIN PYTHON SCRIPTS (no pytest dependency). Each
``test_<name>.py`` defines test functions and ends with::

    if __name__ == "__main__":
        raise SystemExit(_run_all())

where ``_run_all`` iterates the module's ``test_*`` functions and
prints OK/FAIL. The repo-level runner (``tests/run_all.py``) walks
all three subdirectories and invokes each module.

Run a single module::

    python tests/unit/test_materialtype_resolver.py

Run everything::

    python tests/run_all.py
"""
