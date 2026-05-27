"""
=============================================================================
SOURCE-PLATFORM ABC  (platforms.base)
=============================================================================

The contract a source-engine plugin implements. Subclass ``SourcePlatform``,
fill in the class-level identity fields + the required methods, and
register the instance in ``platforms.__init__.PLATFORM_REGISTRY``.

Plugins are expected to be **read-only**: they parse source assets into
the neutral data shapes from ``platforms.types`` so the engine-agnostic
core can drive emission. No writes back into the source engine, no
network calls, no live IPC.

Reference: ``.serena/memories/platform_abstraction/audit.md`` § Part 3.1.

Design choice — ABC over Protocol
---------------------------------
``SourcePlatform`` is an ABC with ``abstractmethod`` markers rather than
a ``Protocol`` because plugin authors benefit from explicit inheritance:
   - clear "this is where you slot in" signal,
   - default implementations for the optional methods,
   - one place to look up the contract.

Plugins still type-check structurally — Python doesn't enforce ABC
membership at registration time — but the ABC is the documented home.

Method categories
-----------------
1. **Identity**  — class-level constants. Loaded into the SourceEngine
   enum so the GUI dropdown and project file know about the plugin.
2. **Discovery** — given a scope-root, list the platform's prefab /
   scene / terrain candidates the user can select from.
3. **Extraction** — turn source files into neutral data shapes.
4. **Profile library** — shader profiles + shader → profile mappings.
5. **Component processors** — per-source-component-type → O3DE-JSON
   translators.
6. **Coordinate system** — convert source-space transforms to O3DE-space.
7. **Preflight hooks** — extra checks the platform contributes to the
   pre-flight panel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .types import (
    AssetIndex, PlatformMaterial, PlatformPrefab, PlatformScene,
    PlatformTransform,
)


class SourcePlatform(ABC):
    """Base class for source-engine plugins.

    Inherit, fill in the identity constants + the abstract methods,
    instantiate, then call ``platforms.register(instance)`` to make
    the plugin discoverable.
    """

    # ----- IDENTITY (class-level constants — declared on every subclass) ----

    NAME: str = ""
    """Lower-case enum-style id ("unity", "unreal", "godot", "blender").
    Matches a value in `project_manager.SourceEngine`."""

    DISPLAY: str = ""
    """Human-readable name shown in the engine dropdown ("Unity",
    "Unreal Engine 5", ...)."""

    DESCRIPTION: str = ""
    """Short tagline — appears under the engine dropdown's hover help."""

    FILE_EXTENSIONS: Dict[str, Any] = {}
    """Kind → glob pattern (or list of patterns) the plugin knows about.
    Standard kinds: ``"prefab"``, ``"scene"``, ``"material"``,
    ``"shader"``, ``"mesh"``, ``"texture"``, ``"terrain"``. A plugin
    may add others; the scrubber only consults the standard ones."""

    UP_AXIS: str = "Y"
    """Source-engine up-axis convention. ``"Y"`` or ``"Z"``."""

    HANDEDNESS: str = "LH"
    """Source-engine handedness. ``"LH"`` (left) or ``"RH"`` (right)."""

    SUPPORTED_TABS: List[str] = [
        "dashboard", "scenes", "prefabs", "meshes", "materials",
        "terrain", "config",
    ]
    """Tab keys this platform exposes in the UI. The MainWindow toggles
    tab visibility based on this list when the active platform changes.
    Defaults to the full set so the most permissive case (Unity ships
    everything) doesn't need to repeat the list.

    Plugin authors targeting engines that lack one of these concepts
    (e.g. an Unreal plugin that doesn't expose a Terrain tab) override
    this with a narrower list and the corresponding tab(s) hide
    automatically on platform switch."""

    # ----- DISCOVERY -----------------------------------------------------

    @abstractmethod
    def scope_root_label(self) -> str:
        """User-facing label for the scope-root field on the Dashboard.
        E.g. ``"Unity project root"``, ``"Unreal Content directory"``,
        ``"Godot res:// directory"``."""

    @abstractmethod
    def validate_scope_root(self, path: Path) -> List["PreflightItem"]:  # noqa: F821
        """Per-platform sanity check appended to the Environment preflight.

        Unity: the path contains an ``Assets/`` subdirectory.
        Unreal: contains ``Content/``.
        Godot: contains ``project.godot``.

        Returns a list of preflight items (see ``preflight.PreflightItem``).
        An empty list means everything's fine. Reds in the list bubble up
        to the Environment category in the preflight panel."""

    @abstractmethod
    def build_asset_index(self, scope_root: Path) -> AssetIndex:
        """Walk the scope and return the platform's asset-id index."""

    def scrub_prefabs(self, scope_root: Path) -> List[str]:
        """Return paths (relative to ``scope_root``) of prefab-like
        assets the user can mark for conversion. Default is empty —
        plugins without a prefab concept can leave it."""
        return []

    def scrub_scenes(self, scope_root: Path) -> List[str]:
        """Same as ``scrub_prefabs`` but for scene-like assets."""
        return []

    def scrub_terrain(self, scope_root: Path) -> List[str]:
        """Same as ``scrub_prefabs`` but for terrain-material-like assets."""
        return []

    # ----- EXTRACTION ----------------------------------------------------

    @abstractmethod
    def parse_material(self, path: Path) -> PlatformMaterial:
        """Read a source material file into a neutral ``PlatformMaterial``.

        The plugin populates ``shader_id``, ``raw_textures``,
        ``raw_floats``, and ``raw_colors`` from the source file's native
        format. The worker then runs the F-9 profile chain over these
        raw values to produce the O3DE-side ``.material`` content."""

    @abstractmethod
    def parse_prefab(self, path: Path) -> PlatformPrefab:
        """Read a source prefab into a neutral ``PlatformPrefab``."""

    @abstractmethod
    def parse_scene(self, path: Path) -> PlatformScene:
        """Read a source scene into a neutral ``PlatformScene``."""

    @abstractmethod
    def resolve_shader_name(self, material: PlatformMaterial) -> str:
        """Resolve a material's shader reference to its friendly name
        (the string the user sees in the Shader Mappings dialog).

        Plugins can short-circuit by reading ``material.shader_id`` if
        their format already carries the name; otherwise they consult
        a per-engine name registry (Unity reads the ``Shader "..."``
        line from a ``.shader`` file)."""

    # ----- PROFILE LIBRARY ----------------------------------------------

    @abstractmethod
    def default_profiles(self) -> Dict[str, dict]:
        """The plugin's pre-seeded shader-profile library — keyed by
        profile name, value is a profile dict (see
        ``project_manager.DEFAULT_SHADER_PROFILE`` for the shape).

        At minimum every plugin returns one catch-all profile that
        translates the engine's standard PBR shader to O3DE
        StandardPBR. Unity's catch-all is named ``"Default — Anything
        to PBR"`` and is the F-9 reference."""

    @abstractmethod
    def default_shader_mappings(self) -> Dict[str, str]:
        """Initial ``shader_name → profile_name`` mappings the plugin
        ships out of the box. Covers the engine's standard / URP / etc.
        shaders so a brand-new project doesn't have an empty mapping
        table on first open."""

    # ----- COMPONENT PROCESSORS -----------------------------------------

    @abstractmethod
    def component_processors(self) -> List[Any]:
        """Return the plugin's component processors — one per
        source-engine component type the plugin translates to O3DE
        component JSON. Each item must conform to
        ``components.base.ComponentProcessor``.

        For now the Unity plugin returns the result of
        ``components.load_component_processors()`` (the existing
        auto-discovery). Other plugins ship their own processor
        directory."""

    # ----- COORDINATE SYSTEM --------------------------------------------

    @abstractmethod
    def to_o3de_coordinates(self, transform: PlatformTransform
                            ) -> Tuple[PlatformTransform, bool]:
        """Convert a source-space transform to O3DE-space (Z-up, RH).

        Returns ``(converted_transform, scale_was_non_uniform)``. The
        boolean lets the worker surface a warning when non-uniform
        scale is lost during conversion."""

    # ----- PREFLIGHT EXTENSIONS -----------------------------------------

    def preflight_checks(self) -> List[Callable]:
        """Optional — append platform-specific check functions to
        ``preflight.CHECK_REGISTRY``. Each callable receives a
        ``project`` and returns ``List[PreflightItem]``. Default is
        no extra checks."""
        return []
