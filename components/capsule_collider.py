"""
=============================================================================
CAPSULE COLLIDER COMPONENT PROCESSOR  (WEIGHT = 150)

Handles:  CapsuleCollider
Emits:    EditorCapsuleShapeComponent + EditorShapeColliderComponent
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext
from .box_collider import _resolve_target


class CapsuleColliderProcessor(ComponentProcessor):
    """
    Parse phase:
      Appends a capsule collider dict to go.colliders with a global_index
      set at parse time (position among ALL colliders on this GameObject).
      Records radius, height, and Unity direction axis (0=X, 1=Y, 2=Z).

    Emit phase:
      global_index == 0 → shape components on main entity.
      global_index  > 0 → shape components on a new child entity.

    Note: Unity 'direction' axis is recorded but O3DE CapsuleShape always
    aligns along the Z axis; axis remapping can be added here when needed.
    """

    WEIGHT  = 150
    HANDLES = ['CapsuleCollider']
    EMITS   = ['EditorCapsuleShapeComponent', 'EditorShapeColliderComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        center = comp_data.get('m_Center', {'x': 0, 'y': 0, 'z': 0})

        collider = {
            'type':         'CapsuleCollider',
            'global_index': len(go.colliders),
            'is_trigger':   comp_data.get('m_IsTrigger', 0) == 1,
            'center': (
                float(center.get('x', 0)),
                float(center.get('y', 0)),
                float(center.get('z', 0)),
            ),
            'radius':    float(comp_data.get('m_Radius',    0.5)),
            'height':    float(comp_data.get('m_Height',    2.0)),
            'direction': int(comp_data.get('m_Direction', 1)),    # 0=X 1=Y 2=Z
        }
        go.colliders.append(collider)
        log(
            f"    [Physics] CapsuleCollider[{collider['global_index']}] → "
            f"r={collider['radius']}, h={collider['height']}, "
            f"dir={collider['direction']}, trigger={collider['is_trigger']}"
        )

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        my_colliders = [c for c in go.colliders if c['type'] == 'CapsuleCollider']
        if not my_colliders:
            return []

        child_ids: List[str] = []
        for collider in my_colliders:
            global_idx = collider['global_index']
            target_comps, child_id = _resolve_target(global_idx, go, entity, ctx)
            if child_id:
                child_ids.append(child_id)

            _write_capsule_shape(target_comps, collider, ctx)
            ctx.log(
                f"  [Physics] ✓ CapsuleCollider [{global_idx}] → "
                f"{'main entity' if global_idx == 0 else 'child entity'}"
            )

        return child_ids


# =============================================================================
# SHAPE WRITER
# =============================================================================

def _write_capsule_shape(components: Dict, collider: Dict,
                         ctx: ProcessingContext) -> None:
    """Write EditorCapsuleShapeComponent + EditorShapeColliderComponent."""
    cx, cy, cz = collider.get('center', (0, 0, 0))
    offset     = [cx, cz, cy]
    has_offset = any(abs(v) > 0.0001 for v in offset)

    height = collider.get('height', 2.0)
    radius = collider.get('radius', 0.5)

    capsule_cfg: Dict = {'Height': height, 'Radius': radius}
    if has_offset:
        capsule_cfg['TranslationOffset'] = offset

    components['EditorCapsuleShapeComponent'] = {
        '$type':         'EditorCapsuleShapeComponent',
        'Id':            ctx.generate_component_id(),
        'DisplayFilled': False,
        'CapsuleShape':  {'Configuration': capsule_cfg},
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
        'ShapeConfigs': [{
            '$type':  'CapsuleShapeConfiguration',
            'Height': height,
            'Radius': radius,
        }],
    }
