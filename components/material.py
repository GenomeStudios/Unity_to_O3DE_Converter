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

        * `materialsByLabel` — every material keyed by the FBX-internal
          material slot name (the string SceneAPI extracts from the binary
          FBX as MaterialAsset::m_name and exposes at runtime as
          ModelMaterialSlot::m_displayName).
          MaterialComponentController::ResolveMaterialsByLabel() matches each
          label against MaterialConsumerRequestBus::GetMaterialLabels() and
          projects resolved entries into m_materials. Unresolved labels stay
          in the by-label map so future mesh swaps can rebind.

      Label source:
        ctx.fbx_material_labels[go.file_id] — a list of FBX-internal material
        names extracted by integrated_asset_processor.read_fbx_material_names
        and paired ordinally with go.material_guids in _process_prefab.
        These names are *unrelated* to Unity's .mat / .azmaterial file names.

      If no FBX labels are available (entity not in the map, FBX parse
      returned empty, or running under the scene converter which has no FBX
      access), the by-label map is omitted. The default {} slot is still
      emitted so the entity renders the first material.

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

        fbx_labels = ctx.fbx_material_labels.get(go.file_id, [])

        materials_config:   Dict = {}
        materials_by_label: Dict = {}
        seen_labels:        set  = set()
        mapped       = 0
        skipped      = 0
        no_label     = 0

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
            # something if by-label resolution misses (e.g. label mismatch).
            if idx == 0:
                materials_config['{}'] = slot_entry

            # Label key = FBX-internal material slot name at this ordinal
            # position. The FBX export order matches Unity's MeshRenderer
            # material list order, so a positional pair is the contract.
            label = fbx_labels[idx] if idx < len(fbx_labels) else ''
            if not label:
                ctx.log(
                    f"  [Material] ⚠ Slot {idx} ({mat_path}) has no FBX "
                    f"label (FBX parse returned {len(fbx_labels)} names "
                    f"for {len(go.material_guids)} slots) — by-label entry "
                    f"skipped, default slot still emitted if idx==0."
                )
                no_label += 1
                mapped += 1
                continue

            if label in seen_labels:
                ctx.log(
                    f"  [Material] ⚠ Duplicate FBX label '{label}' at "
                    f"slot {idx} — keeping first occurrence (Unity allows "
                    f"duplicate slot materials; O3DE label resolution does not)."
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
                f"{mapped} slot(s) mapped, {skipped} skipped, "
                f"{no_label} without FBX label"
            )

        return []
