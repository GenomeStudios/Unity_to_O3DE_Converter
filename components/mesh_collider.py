"""
=============================================================================
MESH COLLIDER COMPONENT PROCESSOR  (WEIGHT = 175)

Handles:  MeshCollider
Emits:    EditorMeshColliderComponent

Resolution order for the .pxmesh asset hint:
  1. Collider-specific mesh GUID  (m_Mesh on the MeshCollider component)
  2. Render mesh GUID             (go.mesh_guid from MeshFilter)
  3. No hint set                  (logged as warning; collider still created)
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext
from .box_collider import _resolve_target


class MeshColliderProcessor(ComponentProcessor):
    """
    Parse phase:
      Appends a mesh collider dict to go.colliders with global_index,
      the collider mesh GUID (may differ from the render mesh), and
      the convex flag.

    Emit phase:
      global_index == 0 → component on main entity.
      global_index  > 0 → component on a new child entity.
      Resolves the physics asset hint by replacing .azmodel with .pxmesh.
    """

    WEIGHT  = 175
    HANDLES = ['MeshCollider']
    EMITS   = ['EditorMeshColliderComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        mesh_ref = comp_data.get('m_Mesh', {})

        collider = {
            'type':         'MeshCollider',
            'global_index': len(go.colliders),
            'is_trigger':   comp_data.get('m_IsTrigger', 0) == 1,
            'mesh_guid':    mesh_ref.get('guid', ''),
            'convex':       comp_data.get('m_Convex',    0) == 1,
        }
        go.colliders.append(collider)
        log(
            f"    [Physics] MeshCollider[{collider['global_index']}] → "
            f"convex={collider['convex']}, trigger={collider['is_trigger']}, "
            f"mesh_guid={collider['mesh_guid'][:8] + '...' if collider['mesh_guid'] else 'none'}"
        )

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        my_colliders = [c for c in go.colliders if c['type'] == 'MeshCollider']
        if not my_colliders:
            return []

        child_ids: List[str] = []
        for collider in my_colliders:
            global_idx = collider['global_index']
            target_comps, child_id = _resolve_target(global_idx, go, entity, ctx)
            if child_id:
                child_ids.append(child_id)

            _write_mesh_collider(target_comps, collider, go, ctx)
            ctx.log(
                f"  [Physics] ✓ MeshCollider [{global_idx}] → "
                f"{'main entity' if global_idx == 0 else 'child entity'}"
            )

        ctx.stats["Colliders"] = ctx.stats.get("Colliders", 0) + len(my_colliders)
        return child_ids


# =============================================================================
# SHAPE WRITER
# =============================================================================

def _write_mesh_collider(components: Dict, collider: Dict, go,
                         ctx: ProcessingContext) -> None:
    """Write EditorMeshColliderComponent, resolving the physics mesh asset hint."""
    is_trigger = collider.get('is_trigger', False)

    collider_cfg: Dict = {
        'MaterialSlots': {'Slots': [{'Name': 'Entire object'}]}
    }
    if is_trigger:
        collider_cfg['Trigger'] = True

    mesh_comp: Dict = {
        '$type': 'EditorMeshColliderComponent',
        'Id':    ctx.generate_component_id(),
        'ColliderConfiguration': collider_cfg,
    }

    # --- Resolve .pxmesh hint ---
    hint = None

    mesh_guid = collider.get('mesh_guid', '')
    if mesh_guid and mesh_guid in ctx.mesh_mapping:
        hint = ctx.mesh_mapping[mesh_guid].replace('.azmodel', '.pxmesh')
        ctx.log(f"  [Physics] MeshCollider using collider mesh: {hint}")

    elif go.file_id and go.file_id in ctx.mesh_mapping:
        hint = ctx.mesh_mapping[go.file_id].replace('.azmodel', '.pxmesh')
        ctx.log(f"  [Physics] MeshCollider using render mesh: {hint}")

    else:
        ctx.log(
            f"  [Physics] ⚠ MeshCollider — no mesh asset found in mapping; "
            f"collider created without physics asset hint"
        )

    if hint:
        mesh_comp['ShapeConfiguration'] = {
            'PhysicsAsset': {
                'Asset': {'assetHint': hint},
                'Configuration': {
                    'PhysicsAsset': {
                        'loadBehavior': 'QueueLoad',
                        'assetHint':    hint,
                    }
                },
            }
        }

    components['EditorMeshColliderComponent'] = mesh_comp
