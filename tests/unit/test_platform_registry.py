"""Unit tests for the platform registry — register / get / names /
collision detection. Phase B verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests


def test_unity_pre_registered():
    """The package's bootstrap registers Unity at import time."""
    from platforms import PLATFORM_REGISTRY, get
    assert "unity" in PLATFORM_REGISTRY
    plat = get("unity")
    assert plat is not None and plat.NAME == "unity"


def test_case_insensitive_lookup():
    from platforms import get
    plat = get("unity")
    assert get("UNITY") is plat
    assert get("Unity") is plat


def test_names_returns_sorted_list():
    from platforms import names
    n = names()
    assert isinstance(n, list)
    assert "unity" in n
    assert n == sorted(n)


def test_double_register_same_instance_is_noop():
    from platforms import register, get
    plat = get("unity")
    register(plat)  # same instance — no exception, no duplication
    assert get("unity") is plat


def test_double_register_different_instance_raises():
    from platforms import register
    from platforms.unity.unity_platform import UnityPlatform

    class DupeUnity(UnityPlatform):
        pass

    try:
        register(DupeUnity())
    except ValueError as e:
        assert "already registered" in str(e).lower()
        return
    raise AssertionError("registry should have rejected the duplicate NAME")


def test_register_non_platform_raises():
    from platforms import register

    class NotAPlatform:
        NAME = "fake"

    try:
        register(NotAPlatform())  # type: ignore[arg-type]
    except TypeError as e:
        assert "SourcePlatform" in str(e)
        return
    raise AssertionError("registry should have rejected non-SourcePlatform input")


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
