"""
=============================================================================
MATERIAL COMPONENT PROCESSOR  (WEIGHT = 50)

Handles:  (none — material GUIDs are populated by MeshComponentProcessor)
Emits:    EditorMaterialComponent
=============================================================================
"""

from typing import Dict, List

from .base import ComponentProcessor, ProcessingContext


class MaterialComponentProcessor(ComponentProcessor):
    """
    Emit-only processor.  No parse phase is needed because go.material_guids
    is already populated by MeshComponentProcessor (weight=25) when it handles
    the MeshRenderer component.

    Emit phase:
      Reads go.material_guids and writes an EditorMaterialComponent with one
      slot per material, indexed as {0}, {1}, {2}, ... to match Unity's
      MeshRenderer material list order.  Slots whose GUIDs are not found in
      ctx.material_mapping are logged as warnings and skipped gracefully.
    """

    WEIGHT  = 50
    HANDLES = []    # no parse phase
    EMITS   = ['EditorMaterialComponent']

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        if not go.material_guids:
            return []

        materials_config: Dict = {}
        mapped = 0
        skipped = 0

        for idx, mat_guid in enumerate(go.material_guids):
            mat_path = ctx.material_mapping.get(mat_guid)
            slot_id  = f'{{{idx}}}'

            if mat_path:
                slot_entry = {'MaterialAsset': {'assetHint': mat_path}}
                if idx == 0:
                    materials_config['{}'] = slot_entry
                materials_config[slot_id] = slot_entry
                ctx.log(f"  [Material] ✓ Slot {slot_id} → {mat_path}")
                mapped += 1
            else:
                ctx.log(
                    f"  [Material] ⚠ Slot {slot_id} GUID {mat_guid[:8]}... "
                    f"not in material mapping — slot skipped"
                )
                skipped += 1

        if materials_config:
            entity['Components']['EditorMaterialComponent'] = {
                '$type': 'EditorMaterialComponent',
                'Id': ctx.generate_component_id(),
                'Controller': {
                    'Configuration': {
                        'materials': materials_config
                    }
                }
            }
            ctx.log(
                f"  [Material] ✓ EditorMaterialComponent — "
                f"{mapped} slot(s) mapped, {skipped} skipped"
            )

        return []
