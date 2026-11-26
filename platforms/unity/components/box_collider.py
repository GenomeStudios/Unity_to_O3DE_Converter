"""
=============================================================================
BOX COLLIDER COMPONENT PROCESSOR  (WEIGHT = 100)

Handles:  BoxCollider
Emits:    EditorBoxShapeComponent + EditorShapeColliderComponent

Also exports _resolve_target() — a shared helper used by all collider
processors to route components to the main entity (global_index == 0) or
to an auto-generated child entity for overflow colliders (global_index > 0).
=============================================================================
"""

from typing import Callable, Dict, List, Optional, Tuple

from .base import ComponentProcessor, ProcessingContext


# =============================================================================
# SHARED HELPER — used by all collider processors
# =============================================================================

def _resolve_target(
        global_idx: int,
        go,
        entity: Dict,
        ctx: ProcessingContext,
) -> Tuple[Dict, Optional[str]]:
    """
    Decide where to place a collider's components.

    global_idx == 0  → main entity (no child created).
    global_idx  > 0  → new child entity named '{go.name}_Collider_{N}',
                        pre-populated with a StaticRigidBodyComponent,
                        registered in ctx.entities_dict.

    Returns (target_components_dict, child_entity_id_or_None).
    """
    if global_idx == 0:
        return entity['Components'], None

    child_id = ctx.generate_entity_id()
    child    = ctx.make_bare_entity(
        child_id,
        f"{go.name}_Collider_{global_idx}",
        entity['Id'],
    )
    child['Components']['EditorStaticRigidBodyComponent'] = {
        '$type': 'EditorStaticRigidBodyComponent',
        'Id':    ctx.generate_component_id(),
    }
    ctx.entities_dict[child_id] = child
    ctx.log(
        f"  [Physics] Created overflow child entity "
        f"'{go.name}_Collider_{global_idx}' (id={child_id})"
    )
    return child['Components'], child_id


def _apply_collision_config(collider_cfg: Dict, go, ctx: ProcessingContext) -> None:
    """Stamp CollisionLayer ("from") + CollisionGroupId ("to") onto a
    ColliderConfiguration from the entity's resolved collision config
    (ctx.collision_config[go.file_id]). A None layer or empty group is left
    unset so the collider keeps its O3DE engine default — shared by all four
    collider writers (box / sphere / capsule / mesh).

    Serialization (engine-verified, ColliderConfiguration v7):
      CollisionLayer   → {"Index":   <u8 0..63>}
      CollisionGroupId → {"GroupId": "<AZ::Uuid>"}
    """
    cfg = ctx.collision_config.get(str(go.file_id))
    if not cfg:
        return
    layer = cfg.get("layer")
    group = cfg.get("group")
    if layer is not None:
        collider_cfg['CollisionLayer'] = {'Index': layer}
    if group:
        collider_cfg['CollisionGroupId'] = {'GroupId': group}


# =============================================================================
# BOX COLLIDER PROCESSOR
# =============================================================================

class BoxColliderProcessor(ComponentProcessor):
    """
    Parse phase:
      Appends a box collider dict to go.colliders.  The global_index field
      records the collider's position among ALL colliders on this GameObject
      (set at parse time so emit ordering is independent of processor weight).

    Emit phase:
      global_index == 0 → shape components on main entity.
      global_index  > 0 → shape components on a new child entity.
    """

    WEIGHT  = 100
    HANDLES = ['BoxCollider']
    EMITS   = ['EditorBoxShapeComponent', 'EditorShapeColliderComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        center = comp_data.get('m_Center', {'x': 0, 'y': 0, 'z': 0})
        size   = comp_data.get('m_Size',   {'x': 1, 'y': 1, 'z': 1})

        collider = {
            'type':         'BoxCollider',
            'global_index': len(go.colliders),
            'is_trigger':   comp_data.get('m_IsTrigger', 0) == 1,
            'center': (
                float(center.get('x', 0)),
                float(center.get('y', 0)),
                float(center.get('z', 0)),
            ),
            'size': (
                float(size.get('x', 1)),
                float(size.get('y', 1)),
                float(size.get('z', 1)),
            ),
        }
        go.colliders.append(collider)
        log(
            f"    [Physics] BoxCollider[{collider['global_index']}] → "
            f"size={collider['size']}, trigger={collider['is_trigger']}"
        )

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        my_colliders = [c for c in go.colliders if c['type'] == 'BoxCollider']
        if not my_colliders:
            return []

        child_ids: List[str] = []
        for collider in my_colliders:
            global_idx = collider['global_index']
            target_comps, child_id = _resolve_target(global_idx, go, entity, ctx)
            if child_id:
                child_ids.append(child_id)

            _write_box_shape(target_comps, collider, go, ctx)
            ctx.log(
                f"  [Physics] ✓ BoxCollider [{global_idx}] → "
                f"{'main entity' if global_idx == 0 else 'child entity'}"
            )

        ctx.stats["Colliders"] = ctx.stats.get("Colliders", 0) + len(my_colliders)
        return child_ids


# =============================================================================
# SHAPE WRITER
# =============================================================================

# The thinnest box side written, in metres. PhysX takes no side of zero.
MIN_BOX_SIDE = 0.0001


def box_dimensions(size) -> List[float]:
    """The sides of a box shape for a Unity BoxCollider's ``m_Size``.

    Unity accepts a size that is negative or zero on an axis (a sheet of
    paper authored with no thickness, a box dragged through itself) and
    collides with the box of its magnitudes. PhysX in O3DE refuses such a
    box outright ("Negative or zero values are invalid for box dimensions")
    and the entity is left with no collider at all. So each side is its
    magnitude, and a side of zero becomes ``MIN_BOX_SIDE``."""
    return [max(abs(float(side)), MIN_BOX_SIDE) for side in size]

def _write_box_shape(components: Dict, collider: Dict, go,
                     ctx: ProcessingContext) -> None:
    """Write EditorBoxShapeComponent + EditorShapeColliderComponent."""
    cx, cy, cz = collider.get('center', (0, 0, 0))
    offset     = [cx, cz, cy]           # Unity (x,y,z) → O3DE (x, z, y)
    has_offset = any(abs(v) > 0.0001 for v in offset)

    sx, sy, sz = collider.get('size', (1, 1, 1))
    dims       = box_dimensions((sx, sz, sy))   # swap Y/Z axes

    box_cfg: Dict = {'IsFilled': False, 'Dimensions': dims}
    if has_offset:
        box_cfg['TranslationOffset'] = offset

    components['EditorBoxShapeComponent'] = {
        '$type':         'EditorBoxShapeComponent',
        'Id':            ctx.generate_component_id(),
        'DisplayFilled': False,
        'BoxShape':      {'Configuration': box_cfg},
    }

    collider_cfg: Dict = {
        'MaterialSlots': {'Slots': [{'Name': 'Entire object'}]}
    }
    if collider.get('is_trigger'):
        collider_cfg['Trigger'] = True
    if has_offset:
        collider_cfg['Position'] = offset
    _apply_collision_config(collider_cfg, go, ctx)

    components['EditorShapeColliderComponent'] = {
        '$type':                 'EditorShapeColliderComponent',
        'Id':                    ctx.generate_component_id(),
        'ColliderConfiguration': collider_cfg,
        'DebugDrawSettings':     {'LocallyEnabled': False},
        'ShapeConfigs':          [{'$type': 'BoxShapeConfiguration', 'Configuration': dims}],
    }
