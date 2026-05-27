"""
=============================================================================
UNITY SOURCE-DATA TYPES  (platforms.unity.types)
=============================================================================

Dataclasses the Unity parsers populate during ``_parse_unity_prefab``.
Promoted from ``integrated_asset_processor`` so third-party plugin
authors targeting Unity-like engines (Unreal? Roblox? Maya scenes?)
can reuse them without depending on the worker module.

Re-exported from ``integrated_asset_processor`` for backwards
compatibility.

Contents:
    Transform        — 3D transform with quaternion rotation +
                        ``is_uniform_scale`` test.
    UnityComponent   — One parsed component (type_name + file_id +
                        raw data dict).
    GameObject       — A node in a Unity scene-graph. Carries
                        transform, components, hierarchy refs, and
                        the prefab-instance override capture lists.

These are SOURCE-SPECIFIC types — they mirror Unity's data model.
The platform-agnostic neutral equivalents live in
``platforms.types`` (``PlatformTransform``, ``PlatformEntity``,
``PlatformPrefab``). The worker translates between these as it
walks the parse → emit pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Transform:
    """Unity transform data — position + quaternion rotation + scale.

    Stored as plain tuples for cheap copying. The
    :meth:`is_uniform_scale` test underpins the converter's
    non-uniform-scale warning path."""
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale:    Tuple[float, float, float] = (1.0, 1.0, 1.0)

    def is_uniform_scale(self, tolerance: float = 0.0001) -> bool:
        return (abs(self.scale[0] - self.scale[1]) < tolerance
                and abs(self.scale[1] - self.scale[2]) < tolerance)


@dataclass
class UnityComponent:
    """One Unity component as parsed from a prefab/scene YAML.

    ``type_name`` is the component class string (``"MeshRenderer"``,
    ``"BoxCollider"``, …). ``file_id`` is the anchor inside the
    source file. ``data`` is the raw YAML dict — the dispatch
    table's component processors read from it."""
    type_name: str
    file_id:   str
    data:      Dict = field(default_factory=dict)


@dataclass
class GameObject:
    """Unity GameObject representation — a node in a scene-graph.

    Populated by ``_parse_unity_prefab`` / ``_parse_game_object``
    and consumed by ``_create_entity_recursive`` /
    ``_create_o3de_prefab``. Carries the component list, hierarchy
    refs, mesh/material asset GUIDs, and the prefab-instance
    override capture lists.
    """
    file_id:       str
    name:          str
    transform:     Transform
    components:    List[UnityComponent] = field(default_factory=list)
    parent_id:     Optional[str] = None
    children_ids:  List[str] = field(default_factory=list)
    mesh_guid:     Optional[str] = None
    material_guids: List[str] = field(default_factory=list)
    has_rigidbody: bool = False
    rigidbody_data: Optional[Dict] = None
    colliders:     List[Dict] = field(default_factory=list)
    is_prefab_instance:  bool = False
    prefab_source_guid:  Optional[str] = None
    prefab_name:         Optional[str] = None
    component_data:      Dict[str, Any] = field(default_factory=dict)

    # =========================================================================
    # Prefab-instance override capture (populated only when is_prefab_instance=True)
    # =========================================================================
    # Raw ``m_Modification.m_Modifications`` entries kept verbatim. Each entry
    # is a dict with keys like ``{target: {fileID, guid, type}, propertyPath,
    # value, objectReference}``. The override emitter walks this list and
    # dispatches by propertyPath. Transform overrides are also reflected in
    # ``self.transform`` for convenience, but the raw entries remain here so
    # the coverage tracker can account for everything.
    prefab_modifications:      List[Dict] = field(default_factory=list)
    prefab_added_components:   List[Dict] = field(default_factory=list)
    prefab_removed_components: List[Dict] = field(default_factory=list)
    prefab_added_gameobjects:  List[Dict] = field(default_factory=list)
