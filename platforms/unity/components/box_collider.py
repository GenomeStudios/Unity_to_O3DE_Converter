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

def needs_own_entity(collider: Dict, stretched: bool) -> bool:
    """Whether a collider cannot sit on its object's own entity.

    Two cases, both about capsules and spheres:
      - the engine refuses a capsule or a sphere on an entity that has a
        non-uniform scale (``stretched``): the two components are declared
        incompatible and the prefab does not cook;
      - an O3DE capsule stands along its entity's Z. A Unity capsule along
        its object's X or Z has to be turned, and a shape cannot be turned
        on its own.
    In both the collider gets an entity of its own under the object
    (``own_entity_placement``)."""
    kind = collider.get('type')
    lying = kind == 'CapsuleCollider' and int(collider.get('direction', 1)) != 1
    return lying or (stretched and kind in ('CapsuleCollider', 'SphereCollider'))


def refuses_non_uniform_scale(go) -> bool:
    """Whether the entity made of ``go`` carries a capsule or a sphere
    itself, and so cannot be given a non-uniform scale afterwards (as a
    prefab that nests it would, for a stretched instance)."""
    return any(collider.get('global_index', 0) == 0
               and collider.get('type') in ('CapsuleCollider', 'SphereCollider')
               and not needs_own_entity(collider, stretched=False)
               for collider in go.colliders)


def own_entity_placement(collider: Dict, unity_scale, stretched: bool) -> Tuple[Dict, Dict]:
    """For a collider that gets an entity of its own: that entity's
    transform data, and the collider as it is written there (centred, with
    the object's non-uniform scale worked into its size).

    The entity of its own follows the object's transform but not its
    non-uniform scale, so for a ``stretched`` object the scale is applied
    here the way Unity applies it to a collider: the centre by each axis, a
    capsule's height by the scale along it and its radius by the larger of
    the two across it, a sphere's radius by the largest of the three."""
    sx, sy, sz = [abs(float(v)) for v in unity_scale] if stretched else (1.0, 1.0, 1.0)
    cx, cy, cz = collider.get('center', (0.0, 0.0, 0.0))
    transform_data: Dict = {'Translate': [cx * sx, cz * sz, cy * sy]}      # Unity (x, y, z) -> O3DE (x, z, y)
    placed = dict(collider, center=(0.0, 0.0, 0.0))

    if collider.get('type') == 'CapsuleCollider':
        direction = int(collider.get('direction', 1))                      # Unity axis: 0 X, 1 Y, 2 Z
        along = (sx, sy, sz)[direction]
        across = max(value for axis, value in enumerate((sx, sy, sz)) if axis != direction)
        placed['height'] = float(collider.get('height', 2.0)) * along
        placed['radius'] = float(collider.get('radius', 0.5)) * across
        # An O3DE capsule stands along Z. Unity's Y is O3DE's Z already.
        if direction == 0:
            transform_data['Rotate'] = [0.0, 90.0, 0.0]                    # lay it along X
        elif direction == 2:
            transform_data['Rotate'] = [90.0, 0.0, 0.0]                    # lay it along O3DE's Y
    elif collider.get('type') == 'SphereCollider':
        placed['radius'] = float(collider.get('radius', 0.5)) * max(sx, sy, sz)
    return transform_data, placed


def _resolve_target(
        global_idx: int,
        go,
        entity: Dict,
        ctx: ProcessingContext,
        own_entity: bool = False,
) -> Tuple[Dict, Optional[str]]:
    """
    Decide where to place a collider's components.

    global_idx == 0  → main entity (no child created), unless ``own_entity``.
    global_idx  > 0  → new child entity named '{go.name}_Collider_{N}',
                        pre-populated with a StaticRigidBodyComponent,
                        registered in ctx.entities_dict.

    Returns (target_components_dict, child_entity_id_or_None).
    """
    if global_idx == 0 and not own_entity:
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
