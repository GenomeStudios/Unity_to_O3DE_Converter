"""
=============================================================================
COMPONENT PROCESSOR BASE

Base classes for the pluggable Unity → O3DE component processor system.

  ComponentProcessor  — ABC that every component module must subclass.
  ProcessingContext   — Shared state + helper callbacks passed to emit().
=============================================================================
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, List, Any

if TYPE_CHECKING:
    from integrated_asset_processor import GameObject


# =============================================================================
# PROCESSING CONTEXT
# Carries all shared state and helper callbacks into every emit() call.
# =============================================================================

@dataclass
class ProcessingContext:
    """All shared resources needed by component processors during the emit phase."""

    material_mapping:       Dict[str, str]          # unity guid  -> o3de asset hint
    mesh_mapping:           Dict[str, str]          # unity guid  -> o3de asset hint
    entities_dict:          Dict[str, Dict]         # entity_id   -> entity dict (mutated in place)
    entity_id_map:          Dict[str, str]          # go.file_id  -> entity_id

    generate_component_id:  Callable[[], str]
    generate_entity_id:     Callable[[], str]
    make_bare_entity:       Callable[[str, str, str], Dict]  # (id, name, parent_id) -> entity dict

    log:                    Callable[[str], None]


# =============================================================================
# COMPONENT PROCESSOR ABC
# Drop a new subclass into components/ and it is auto-discovered and wired in.
# =============================================================================

class ComponentProcessor(ABC):
    """
    Base class for all Unity component processors.

    WEIGHT   — Execution order. Lower weight runs first. Ties are broken by
               file discovery order (Python sort is stable). Default spacing
               is 25 between built-in processors, leaving room to insert new
               processors at any position.

    HANDLES  — List of Unity component type names this processor handles
               during the parse phase. An empty list means emit-only.

    EMITS    — Informational list of O3DE component types this processor writes.
               Not used at runtime; useful for documentation and debugging.
    """

    WEIGHT:  int       = 100
    HANDLES: List[str] = []
    EMITS:   List[str] = []

    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go: 'GameObject', log: Callable[[str], None]) -> None:
        """
        Parse phase — called once per detected Unity component during
        _build_hierarchy. Populate fields on `go` such as mesh_guid,
        material_guids, colliders, has_rigidbody, or go.component_data
        for processor-specific state.

        Default implementation does nothing; override when HANDLES is non-empty.
        """

    @abstractmethod
    def emit(self, go: 'GameObject', entity: Dict,
             ctx: ProcessingContext) -> List[str]:
        """
        Emit phase — called once per entity during _create_entity_recursive,
        after the TransformComponent has already been added.

        Mutate entity['Components'] to add O3DE component JSON blocks.
        Return a list of child entity_ids created (e.g. overflow collider
        entities). Return an empty list when no children are created.
        """
        return []
