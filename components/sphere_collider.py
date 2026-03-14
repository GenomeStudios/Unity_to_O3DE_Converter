"""
=============================================================================
SPHERE COLLIDER COMPONENT PROCESSOR  (WEIGHT = 125)

Handles:  SphereCollider
Emits:    EditorSphereShapeComponent + EditorShapeColliderComponent
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext
from .box_collider import _resolve_target


class SphereColliderProcessor(ComponentProcessor):
    """
    Parse phase:
      Appends a sphere collider dict to go.colliders with a global_index
      set at parse time (position among ALL colliders on this GameObject).

    Emit phase:
      global_index == 0 → shape components on main entity.
      global_index  > 0 → shape components on a new child entity.
    """

    WEIGHT  = 125
    HANDLES = ['SphereCollider']
    EMITS   = ['EditorSphereShapeComponent', 'EditorShapeColliderComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        center = comp_data.get('m_Center', {'x': 0, 'y': 0, 'z': 0})

        collider = {
            'type':         'SphereCollider',
            'global_index': len(go.colliders),
            'is_trigger':   comp_data.get('m_IsTrigger', 0) == 1,
            'center': (
                float(center.get('x', 0)),
                float(center.get('y', 0)),
                float(center.get('z', 0)),
            ),
            'radius': float(comp_data.get('m_Radius', 0.5)),
        }
        go.colliders.append(collider)
        log(
            f"    [Physics] SphereCollider[{collider['global_index']}] → "
            f"radius={collider['radius']}, trigger={collider['is_trigger']}"
        )

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        my_colliders = [c for c in go.colliders if c['type'] == 'SphereCollider']
        if not my_colliders:
            return []

        child_ids: List[str] = []
        for collider in my_colliders:
            global_idx = collider['global_index']
            target_comps, child_id = _resolve_target(global_idx, go, entity, ctx)
            if child_id:
                child_ids.append(child_id)

            _write_sphere_shape(target_comps, collider, ctx)
            ctx.log(
                f"  [Physics] ✓ SphereCollider [{global_idx}] → "
                f"{'main entity' if global_idx == 0 else 'child entity'}"
            )

        return child_ids


# =============================================================================
# SHAPE WRITER
# =============================================================================

def _write_sphere_shape(components: Dict, collider: Dict,
                        ctx: ProcessingContext) -> None:
    """Write EditorSphereShapeComponent + EditorShapeColliderComponent."""
    cx, cy, cz = collider.get('center', (0, 0, 0))
    offset     = [cx, cz, cy]
    has_offset = any(abs(v) > 0.0001 for v in offset)

    radius = collider.get('radius', 0.5)

    sphere_cfg: Dict = {'Radius': radius}
    if has_offset:
        sphere_cfg['TranslationOffset'] = offset

    components['EditorSphereShapeComponent'] = {
        '$type':         'EditorSphereShapeComponent',
        'Id':            ctx.generate_component_id(),
        'DisplayFilled': False,
        'SphereShape':   {'Configuration': sphere_cfg},
    }

    collider_cfg: Dict = {
        'MaterialSlots': {'Slots': [{'Name': 'Entire object'}]}
    }
    if collider.get('is_trigger'):
        collider_cfg['Trigger'] = True
    if has_offset:
        collider_cfg['Position'] = offset

    components['EditorShapeColliderComponent'] = {
        '$type':                 'EditorShapeColliderComponent',
        'Id':                    ctx.generate_component_id(),
        'ColliderConfiguration': collider_cfg,
        'DebugDrawSettings':     {'LocallyEnabled': False},
        'ShapeConfigs': [{'$type': 'SphereShapeConfiguration', 'Radius': radius}],
    }
