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
      Reads go.material_guids and writes an EditorMaterialComponent containing:

        * `materials` — only the default slot ({} = IsDefault()), pointing at
          the first material in Unity's list. Survives because
          GetDefaultMaterialMapFromModelAsset unconditionally inserts
          DefaultMaterialAssignmentId at runtime.

        * `materialsByLabel` — every material keyed by its file-stem label.
          MaterialComponentController::LoadMaterials() resolves each label
          against MaterialConsumerRequestBus::GetMaterialLabels() (the FBX
          submesh material slot names) and projects resolved entries into
          m_materials. Unresolved labels stay in the by-label map so future
          mesh swaps can rebind.

      Convention: the Unity material name == the .azmaterial file stem ==
      the FBX submesh material slot's m_displayName. Mismatches break the
      bind and surface as a "label not resolved" entry that never reaches
      the inspector.

      The legacy synthetic-stable-id keys ({0}, {1}, ...) are no longer
      emitted; they never resolved at runtime under the old scheme either.
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

        from pathlib import PurePosixPath

        materials_config:        Dict = {}
        materials_by_label:      Dict = {}
        seen_labels:             set  = set()
        mapped = 0
        skipped = 0

        for idx, mat_guid in enumerate(go.material_guids):
            mat_path = ctx.material_mapping.get(mat_guid)

            if not mat_path:
                ctx.log(
                    f"  [Material] ⚠ Slot {idx} GUID {mat_guid[:8]}... "
                    f"not in material mapping — slot skipped"
                )
                skipped += 1
                continue

            slot_entry = {'MaterialAsset': {'assetHint': mat_path}}

            # Default slot keeps the first material so the entity still renders
            # something if the by-label resolution misses (e.g. label mismatch).
            if idx == 0:
                materials_config['{}'] = slot_entry

            # Label key == .azmaterial file stem. Must match the FBX submesh
            # material slot's m_displayName for runtime resolution.
            label = PurePosixPath(mat_path).stem
            if label in seen_labels:
                ctx.log(
                    f"  [Material] ⚠ Duplicate label '{label}' at slot {idx} — "
                    f"keeping first occurrence (Unity allows duplicate material "
                    f"assignments; O3DE label resolution does not)."
                )
            else:
                materials_by_label[label] = slot_entry
                seen_labels.add(label)
                ctx.log(f"  [Material] ✓ Label '{label}' → {mat_path}")
            mapped += 1

        if materials_config or materials_by_label:
            configuration: Dict = {}
            if materials_config:
                configuration['materials'] = materials_config
            if materials_by_label:
                configuration['materialsByLabel'] = materials_by_label

            entity['Components']['EditorMaterialComponent'] = {
                '$type': 'EditorMaterialComponent',
                'Id': ctx.generate_component_id(),
                'Controller': {
                    'Configuration': configuration
                }
            }
            ctx.log(
                f"  [Material] ✓ EditorMaterialComponent — "
                f"{mapped} slot(s) mapped, {skipped} skipped"
            )

        return []
