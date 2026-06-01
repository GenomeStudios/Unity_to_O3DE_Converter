"""
=============================================================================
MESH COMPONENT PROCESSOR  (WEIGHT = 25)

Handles:  MeshFilter, MeshRenderer
Emits:    AZ::Render::EditorMeshComponent
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext


class MeshComponentProcessor(ComponentProcessor):
    """
    Parse phase:
      MeshFilter   → go.mesh_guid             (the FBX / model asset GUID)
      MeshRenderer → go.material_guids list   (ordered material slot GUIDs)

    Emit phase:
      Writes EditorMeshComponent using the resolved mesh asset hint from
      ctx.mesh_mapping.  Skips silently when the mesh GUID is not mapped
      (e.g. built-in Unity primitives with no external asset).
    """

    WEIGHT  = 25
    HANDLES = ['MeshFilter', 'MeshRenderer']
    EMITS   = ['AZ::Render::EditorMeshComponent']

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:

        if comp_type == 'MeshFilter':
            mesh_ref = comp_data.get('m_Mesh', {})
            guid = mesh_ref.get('guid', '')
            if guid:
                go.mesh_guid = guid
                # fileID identifies which sub-mesh within the FBX this GO
                # renders. Captured so a MeshCollider that references the
                # same (guid, fileID) can be correlated to this node.
                go.mesh_file_id = str(mesh_ref.get('fileID', '') or '')
                log(f"    [Mesh] MeshFilter   → guid={guid[:8]}...")
            else:
                log(f"    [Mesh] ⚠ MeshFilter has no mesh GUID (built-in primitive?)")

        elif comp_type == 'MeshRenderer':
            materials = comp_data.get('m_Materials', [])
            count = 0
            for mat_ref in materials:
                guid = mat_ref.get('guid', '')
                if guid:
                    go.material_guids.append(guid)
                    count += 1
            log(f"    [Mesh] MeshRenderer → {count} material slot(s)")

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        if not go.mesh_guid:
            return []

        mesh_path = ctx.mesh_mapping.get(go.file_id)
        if not mesh_path:
            ctx.log(
                f"  [Mesh] No sub-mesh hint for '{go.name}' (file_id={go.file_id}) "
                f"— EditorMeshComponent skipped"
            )
            return []

        entity['Components']['AZ::Render::EditorMeshComponent'] = {
            '$type': 'AZ::Render::EditorMeshComponent',
            'Id': ctx.generate_component_id(),
            'Controller': {
                'Configuration': {
                    'ModelAsset': {
                        'assetHint': mesh_path
                    }
                }
            }
        }
        ctx.log(f"  [Mesh] ✓ EditorMeshComponent → {mesh_path}")
        ctx.stats["Mesh components"] = ctx.stats.get("Mesh components", 0) + 1
        return []
