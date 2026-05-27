"""
=============================================================================
SOURCE-PLATFORM PLUGIN PACKAGE
=============================================================================

Source-engine plugins live in subpackages of this directory. Each plugin
implements ``SourcePlatform`` (see ``platforms.base``) and registers
itself with ``PLATFORM_REGISTRY`` via ``register(instance)``.

Layout:

    platforms/
        __init__.py            ← this file (registry + register())
        base.py                ← SourcePlatform ABC
        types.py               ← PlatformMaterial / PlatformPrefab / ...
        unity/                 ← reference Unity plugin
            __init__.py
            asset_database.py
            shader.py
            unity_platform.py  ← UnityPlatform subclass

Third-party platforms (Unreal / Godot / Blender / ...) drop alongside
``unity/``. See ``.serena/memories/platform_abstraction/`` for the
audit + plan.

Registration is explicit (no auto-discovery) — plugins import + register
in this file so a broken plugin fails loudly at startup rather than
silently from a missed scan.
"""

from typing import Dict, Optional

from .base import SourcePlatform


# =============================================================================
# REGISTRY
# =============================================================================

PLATFORM_REGISTRY: Dict[str, SourcePlatform] = {}


def register(platform: SourcePlatform) -> None:
    """Add a platform plugin to the registry.

    Raises ``ValueError`` on identity-collision so two plugins can't
    silently claim the same ``NAME``."""
    if not isinstance(platform, SourcePlatform):
        raise TypeError(
            f"register() expected a SourcePlatform subclass, "
            f"got {type(platform).__name__}"
        )
    name = (platform.NAME or "").strip().lower()
    if not name:
        raise ValueError(
            f"{type(platform).__name__}.NAME must be a non-empty string"
        )
    existing = PLATFORM_REGISTRY.get(name)
    if existing is not None and existing is not platform:
        raise ValueError(
            f"Platform '{name}' already registered "
            f"({type(existing).__name__}). Each NAME may register once."
        )
    PLATFORM_REGISTRY[name] = platform


def get(name: str) -> Optional[SourcePlatform]:
    """Look up a registered platform by name. Returns None when missing."""
    return PLATFORM_REGISTRY.get((name or "").strip().lower())


def names() -> list:
    """Sorted list of registered platform NAMEs. Used by the GUI to
    keep the engine dropdown in sync with what's actually available."""
    return sorted(PLATFORM_REGISTRY.keys())


# =============================================================================
# REGISTER BUILT-IN PLUGINS
# =============================================================================

# Unity ships as the reference implementation. The import is deferred to
# avoid module-load circularity: ``unity.unity_platform`` imports from
# ``platforms.base`` which lives in this package.
def _bootstrap_builtin_plugins() -> None:
    from platforms.unity.unity_platform import UnityPlatform
    register(UnityPlatform())


_bootstrap_builtin_plugins()
