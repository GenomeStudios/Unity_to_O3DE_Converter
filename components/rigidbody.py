"""
=============================================================================
RIGIDBODY COMPONENT PROCESSOR  (WEIGHT = 75)

Handles:  Rigidbody
Emits:    EditorRigidBodyComponent  /  EditorStaticRigidBodyComponent

Runs before collider processors (weight 100+) so that the rigidbody type
decision is made before shapes are added.  go.colliders is already fully
populated from the parse phase when emit() is called, so the static/dynamic
decision is always correct.
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext


class RigidbodyComponentProcessor(ComponentProcessor):
    """
    Parse phase:
      Sets go.has_rigidbody = True and stores all relevant Unity Rigidbody
      properties in go.rigidbody_data (mass, drag, angular drag, gravity,
      kinematic flag, constraint bitmask).

    Emit phase:
      Dynamic  — go.has_rigidbody is True:
                 Adds EditorRigidBodyComponent with full configuration,
                 including axis-swapped constraint lock flags.

      Static   — go.has_rigidbody is False but go.colliders is non-empty:
                 Adds EditorStaticRigidBodyComponent to the main entity.
                 Overflow collider child entities get their own
                 StaticRigidBodyComponent added by the collider processors.
    """

    WEIGHT  = 75
    HANDLES = ['Rigidbody']
    EMITS   = ['EditorRigidBodyComponent', 'EditorStaticRigidBodyComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        go.has_rigidbody = True
        go.rigidbody_data = {
            'mass':         float(comp_data.get('m_Mass',          1.0)),
            'drag':         float(comp_data.get('m_Drag',          0.0)),
            'angular_drag': float(comp_data.get('m_AngularDrag',   0.05)),
            'use_gravity':  comp_data.get('m_UseGravity',  1) == 1,
            'is_kinematic': comp_data.get('m_IsKinematic', 0) == 1,
            'constraints':  int(comp_data.get('m_Constraints',     0)),
        }
        rb = go.rigidbody_data
        log(
            f"    [Physics] Rigidbody → mass={rb['mass']}, "
            f"kinematic={rb['is_kinematic']}, gravity={rb['use_gravity']}, "
            f"constraints=0b{rb['constraints']:07b}"
        )

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        if go.has_rigidbody:
            self._emit_dynamic(go, entity, ctx)
        elif go.colliders:
            self._emit_static(entity, ctx)
        else:
            ctx.log(f"  [Physics] No rigidbody and no colliders — nothing to emit")
        return []

    # -------------------------------------------------------------------------

    def _emit_dynamic(self, go, entity: Dict, ctx: ProcessingContext) -> None:
        rb = go.rigidbody_data or {}

        config: Dict = {
            'Mass':            rb.get('mass',         1.0),
            'Linear damping':  rb.get('drag',         0.0),
            'Angular damping': rb.get('angular_drag', 0.05),
            'Gravity Enabled': rb.get('use_gravity',  True),
        }

        if rb.get('is_kinematic', False):
            config['Kinematic'] = True
            ctx.log(f"  [Physics] Kinematic mode enabled")

        # Unity constraint bitmask → O3DE lock flags
        # Unity: PosX=2  PosY=4  PosZ=8  RotX=16  RotY=32  RotZ=64
        # Axis swap: Unity Y → O3DE Z,  Unity Z → O3DE Y
        constraints = rb.get('constraints', 0)
        if constraints:
            if constraints & 2:   config['Lock Linear X']  = True
            if constraints & 4:   config['Lock Linear Z']  = True  # Y → Z
            if constraints & 8:   config['Lock Linear Y']  = True  # Z → Y
            if constraints & 16:  config['Lock Angular X'] = True
            if constraints & 32:  config['Lock Angular Z'] = True  # Y → Z
            if constraints & 64:  config['Lock Angular Y'] = True  # Z → Y
            ctx.log(f"  [Physics] Constraint locks applied from bitmask {constraints}")

        entity['Components']['EditorRigidBodyComponent'] = {
            '$type': 'EditorRigidBodyComponent',
            'Id': ctx.generate_component_id(),
            'Configuration': config,
        }
        ctx.log(
            f"  [Physics] ✓ EditorRigidBodyComponent — "
            f"mass={config['Mass']}, gravity={config['Gravity Enabled']}"
        )

    def _emit_static(self, entity: Dict, ctx: ProcessingContext) -> None:
        entity['Components']['EditorStaticRigidBodyComponent'] = {
            '$type': 'EditorStaticRigidBodyComponent',
            'Id': ctx.generate_component_id(),
        }
        ctx.log(
            f"  [Physics] ✓ EditorStaticRigidBodyComponent "
            f"(has {len(entity.get('Components', {}))} collider(s), no Rigidbody)"
        )
