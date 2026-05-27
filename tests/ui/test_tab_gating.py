"""UI test for follow-up 6 — per-platform tab gating via
``SourcePlatform.SUPPORTED_TABS`` on the MainWindow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.qt_app import get_qt_app

_app = get_qt_app()

import main_app
_app.setStyleSheet(main_app.THEME_QSS)


def test_unity_shows_all_tabs():
    """Unity inherits the full SUPPORTED_TABS list → every tab
    visible (except Config which moves to the corner button)."""
    from main_app import MainWindow
    from project_manager import project_manager
    pm = project_manager()
    pm.new_project("TabGatingUnityTest")
    win = MainWindow()
    bar = win._tabs.tabBar()
    for idx, key in win._PLATFORM_TAB_KEYS.items():
        if key == "config":
            continue
        assert bar.isTabVisible(idx), f"tab '{key}' should be visible for Unity"


def test_narrow_platform_hides_tabs():
    """A subclass that narrows SUPPORTED_TABS to a subset hides
    the unsupported tabs on switch."""
    from main_app import MainWindow
    from platforms import PLATFORM_REGISTRY
    from platforms.unity.unity_platform import UnityPlatform
    from project_manager import project_manager

    class _Narrow(UnityPlatform):
        NAME = "narrow_tab_test"
        SUPPORTED_TABS = ["dashboard", "prefabs", "materials"]

    narrow = _Narrow()
    PLATFORM_REGISTRY[narrow.NAME] = narrow
    try:
        pm = project_manager()
        proj = pm.new_project("TabGatingNarrowTest")
        win = MainWindow()
        proj.set_active_platform("narrow_tab_test")
        pm.project_changed.emit(proj)
        _app.processEvents()
        bar = win._tabs.tabBar()
        hidden  = {"scenes", "meshes", "terrain"}
        visible = {"dashboard", "prefabs", "materials"}
        for idx, key in win._PLATFORM_TAB_KEYS.items():
            if key == "config":
                continue
            if key in hidden:
                assert not bar.isTabVisible(idx), \
                    f"tab '{key}' should be HIDDEN under narrow platform"
            if key in visible:
                assert bar.isTabVisible(idx), \
                    f"tab '{key}' should be VISIBLE under narrow platform"
    finally:
        PLATFORM_REGISTRY.pop("narrow_tab_test", None)


def test_switch_back_to_unity_restores_visibility():
    """After switching to a narrow platform and back to Unity, every
    tab is visible again."""
    from main_app import MainWindow
    from platforms import PLATFORM_REGISTRY
    from platforms.unity.unity_platform import UnityPlatform
    from project_manager import project_manager

    class _Narrow(UnityPlatform):
        NAME = "narrow_visible_test"
        SUPPORTED_TABS = ["dashboard", "prefabs"]

    PLATFORM_REGISTRY["narrow_visible_test"] = _Narrow()
    try:
        pm = project_manager()
        proj = pm.new_project("VisibilityRestoreTest")
        win = MainWindow()
        proj.set_active_platform("narrow_visible_test")
        pm.project_changed.emit(proj)
        _app.processEvents()
        proj.set_active_platform("unity")
        pm.project_changed.emit(proj)
        _app.processEvents()
        bar = win._tabs.tabBar()
        for idx, key in win._PLATFORM_TAB_KEYS.items():
            if key == "config":
                continue
            assert bar.isTabVisible(idx), \
                f"tab '{key}' should be visible after switch-back to Unity"
    finally:
        PLATFORM_REGISTRY.pop("narrow_visible_test", None)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
