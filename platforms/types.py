"""
=============================================================================
NEUTRAL DATA SHAPES  (platforms.types)
=============================================================================

The dataclasses every source-platform plugin reads from and writes into.
Defining them here decouples the converter's core orchestration from
the engine-specific parser implementations.

Reference: ``.serena/memories/platform_abstraction/audit.md`` § Part 3.2.

These shapes are deliberately small. They carry just what the
core / target-emit code needs from a parsed source:

  - ``AssetIndex``         — guid (or other id) ↔ file-path mapping.
  - ``PlatformMaterial``   — material slot bindings + raw scalar/colour
                              properties, post-source-extraction.
  - ``PlatformEntity``     — one entity in a source scene-graph.
  - ``PlatformPrefab``     — root entity + flat dict + parent map.
  - ``PlatformScene``      — alias for ``PlatformPrefab`` for now;
                              scenes are large prefab graphs.
  - ``PlatformTransform``  — neutral 3D transform (position/rotation/scale).

Phase B introduces the SHAPES. Phase C swaps the worker's existing dict
plumbing to consume them. Both pre-Phase-C tooling (returning dicts) and
post-Phase-C tooling (returning these dataclasses) coexist while the
swap is in flight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# Asset identity
# =============================================================================

@dataclass
class AssetIndex:
    """Platform-agnostic asset registry. The plugin populates this once
    per scope-root walk; the worker consults it for asset-id → file
    lookups. ``by_id`` is the canonical map; ``by_path`` is a reverse
    index when the worker needs to recover the id of a file it already
    has on disk.

    The plugin chooses the id form:
      - Unity: 32-char hex GUID from `.meta` sidecars.
      - Unreal (hypothetical): soft-object path string.
      - Godot (hypothetical): ``res://``-relative path.
      - Blender (hypothetical): library + datablock name.

    ``extensions_by_kind`` is the plugin's declared file-extension map
    (``"prefab" → "*.prefab"``, etc.). Used by the scrubbing code that
    walks the scope for selection lists. Mirrors
    ``SourcePlatform.FILE_EXTENSIONS`` for convenience.
    """
    by_id:                Dict[str, Path]   = field(default_factory=dict)
    by_path:              Dict[Path, str]   = field(default_factory=dict)
    extensions_by_kind:   Dict[str, str]    = field(default_factory=dict)


# =============================================================================
# Transform
# =============================================================================

@dataclass
class PlatformTransform:
    """Position / quaternion-rotation / scale. The convention (Y-up vs
    Z-up, RH vs LH) is declared by ``SourcePlatform.UP_AXIS`` /
    ``HANDEDNESS``. The platform's ``to_o3de_coordinates()`` converts an
    instance of this into the O3DE-space transform the writer emits.

    Rotation is stored as a quaternion ``[x, y, z, w]``. Translation /
    scale are 3-element lists. Defaults are identity."""
    translation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation:    List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    scale:       List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])


# =============================================================================
# Material
# =============================================================================

@dataclass
class PlatformMaterial:
    """Result of ``SourcePlatform.parse_material(path)``.

    The plugin populates raw fields. The worker then runs the F-9 profile
    chain over them to produce the O3DE ``.material`` content. Fields:

      ``name``          — material display name from the source file.
      ``shader_id``     — opaque platform shader identifier (Unity GUID,
                           Unreal soft path, etc.).
      ``shader_fileid`` — secondary id when the platform uses one
                           (Unity's m_FileID).
      ``raw_textures``  — source-property-name → asset-id. The profile's
                           ``texture_map`` translates these.
      ``raw_floats``    — source-property-name → float. The profile's
                           ``property_map`` translates these.
      ``raw_colors``    — source-property-name → RGBA list.
      ``extra``         — platform-specific spillover; the worker never
                           reads from this. Useful for plugin-internal
                           round-trip state (e.g. preserving Unity's
                           ``opacity.alphaSource`` flags that the legacy
                           extractor synthesised post-hoc).
    """
    name:          str       = ""
    shader_id:     str       = ""
    shader_fileid: int       = 0
    raw_textures:  Dict[str, str]       = field(default_factory=dict)
    raw_floats:    Dict[str, float]     = field(default_factory=dict)
    raw_colors:    Dict[str, List[float]] = field(default_factory=dict)
    extra:         Dict[str, Any]       = field(default_factory=dict)


# =============================================================================
# Prefab / scene-graph
# =============================================================================

@dataclass
class PlatformEntity:
    """One node in a source scene graph.

    ``entity_id``      — plugin-chosen stable id within the prefab. For
                          Unity this is the FileID anchor string.
    ``name``           — display name from the source file.
    ``transform``      — local transform.
    ``mesh_id``        — referenced mesh asset's id, or None.
    ``material_ids``   — material slot bindings, ordinal order.
    ``raw_components`` — per-component dicts the plugin's
                          ``component_processors`` translate into O3DE
                          component JSON. Each dict carries at least a
                          ``$type`` key the plugin's dispatch table
                          consults; the plugin may add other keys.
    """
    entity_id:      str
    name:           str = ""
    transform:      PlatformTransform = field(default_factory=PlatformTransform)
    mesh_id:        Optional[str] = None
    material_ids:   List[str] = field(default_factory=list)
    raw_components: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PlatformPrefab:
    """A parsed prefab. The plugin returns this from ``parse_prefab``.

    ``root``         — the root entity id.
    ``entities``     — flat dict keyed by entity_id.
    ``parent_map``   — child_id → parent_id (None for the root).
    """
    root:       str
    entities:   Dict[str, PlatformEntity] = field(default_factory=dict)
    parent_map: Dict[str, Optional[str]]  = field(default_factory=dict)


# Scenes are large prefab graphs in O3DE's mental model; the contract
# reuses ``PlatformPrefab`` to avoid a parallel type for now. If a future
# plugin needs scene-specific metadata (skybox refs, render settings),
# extend with a separate ``PlatformScene`` dataclass and the alias drops.
PlatformScene = PlatformPrefab
