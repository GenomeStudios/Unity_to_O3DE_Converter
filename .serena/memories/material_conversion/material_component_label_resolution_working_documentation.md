# Material Component By-Label Override Resolution — Working Doc

Paired with `mem:material_conversion/material_component_label_resolution_plan`.

## Update Log (newest at top)

### 2026-05-25 — I.3 (converter emission) landed

**Primary emission (`components/material.py`)**
`MaterialComponentProcessor.emit()` rewritten:
- `materials` now contains only the default `{}` slot (= first Unity material).
  Retained because `GetDefaultMaterialMapFromModelAsset` always inserts
  `DefaultMaterialAssignmentId` and therefore the default slot still routes
  through the legacy `m_materials` path.
- All materials are also written into `materialsByLabel`, keyed by
  `Path(assetHint).stem` (e.g. `Door_MetalDark`). At runtime,
  `ResolveMaterialsByLabel()` matches each label against
  `MaterialConsumerRequestBus::GetMaterialLabels()` (the FBX submesh slot's
  `m_displayName`) and projects resolved entries into `m_materials`.
  Unresolved labels stay in the by-label map.
- Synthetic `{N}` keys (`{0}`, `{1}`, …) are no longer emitted — they
  never resolved at runtime under the old scheme either.
- Duplicate labels emit a warning and keep first occurrence (Unity allows
  the same material on multiple slots; O3DE label resolution does not).

**Tier 3 nested-prefab + scene-instance overrides**
Both override sites rewritten to patch `materialsByLabel/<label>` instead
of the dead `materials/{N}` path:
- `integrated_asset_processor.py` `_create_nested_prefab_instance` —
  label = stem of the ORIGINAL material at slot N in the source prefab,
  looked up via the sidecar's `material_slots[target_id][slot_idx]` →
  `asset_index["materials"]` → `Path(hint).stem`.
- `unity_scene_converter_gui.py` `_create_prefab_instance` — same lookup,
  via `_get_asset_index(prefab_path)`. Sidecar `material_slots` is now
  loaded in this method (previously only Stage 1 loaded it).
- Slots with no recorded original material (sidecar missing the entry)
  log a coverage warning and skip the patch.

**Invariant the whole pipeline now depends on**: the Unity material name
(= .azmaterial file stem we emit) must equal the FBX submesh material
slot's `m_displayName`. Mismatches surface as a "label not resolved"
entry that never reaches the inspector.

### 2026-05-25 — Implementation (I.1 + I.2) landed in o3de_sourcedev

**Files modified:**
- `Gems/AtomLyIntegration/CommonFeatures/Code/Include/AtomLyIntegration/CommonFeatures/Material/MaterialComponentConfig.h`
  - Added `m_materialsByLabel` field.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentConfig.cpp`
  - Version bumped 3 -> 4. Reflected new field as `"materialsByLabel"` in both SerializeContext and BehaviorContext.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentController.h`
  - Added private `ResolveMaterialsByLabel()` declaration.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentController.cpp`
  - Inserted `ResolveMaterialsByLabel()` call inside `LoadMaterials()`, immediately after `GetDefaultMaterialMap` populates `m_defaultMaterialMap`.
  - Added method body that queries `MaterialConsumerRequestBus::GetMaterialLabels`, builds a `label -> general slot id` table for `IsSlotIdOnly()` entries, and projects unresolved by-label entries into `m_materials` (skipping any slot already explicitly populated).

**Behavior:**
- On first `Activate()`, labels return only the default-slot entry (model not loaded yet). `ResolveMaterialsByLabel()` is a no-op.
- When the mesh fires `OnMaterialAssignmentSlotsChanged`, `LoadMaterials()` runs again. Now labels are populated, by-label entries bind to real stable IDs, and the entries flow through the normal load path.
- Non-destructive: `m_materialsByLabel` is never drained, so a later mesh swap with the same slot labels rebinds.

**No version converter needed for 3 -> 4** — the new field defaults to empty for any pre-existing prefab, and the absence of the field in old serialized data is handled by AzCore reflection.

### Pending

- **Testing** — not yet run. End-to-end build + load required:
    * Convert `W_2x_glass_A.prefab` through the new converter.
    * Open in editor with the patched AtomLyIntegration gem.
    * Verify Door_MetalDark + Glass slots bind on first mesh load.
    * Verify a scene-level material override on the same prefab also
      lands via the new `materialsByLabel/<label>` patch path.
  See plan T-matrix.

## Decisions in flight
None.

## Known unknowns
- Does the Unity material name always equal the FBX submesh material slot's `m_displayName` for converted assets? The pipeline now hard-depends on this. Verify on the W_2x_glass_A test asset first. If false: need a name-mapping pass in the converter to rewrite either the .azmaterial file names or the by-label keys to match the FBX slot names.
- JSON serialization of `AZStd::unordered_map<AZStd::string, MaterialAssignment>` is expected to use the string as the JSON object key directly (vs. the struct-string serialization used for `MaterialAssignmentId` keys). No custom serializer added — relying on auto reflection. If the field round-trips as something else (e.g. an `{Key, Value}` array form), the converter's emission shape will need to follow.
- Whether the AzCore JSON Patch `replace` op tolerates a missing intermediate path (`materialsByLabel/<label>`). The Tier 3 override emission assumes the base prefab always contains the label (which is true under the new emission scheme, since every original material is also written to materialsByLabel). Legacy prefabs converted before this change won't have it — those need re-conversion to benefit.

## Next actions
1. User: regenerate a multi-material prefab (W_2x_glass_A), load in editor, confirm inspector shows both Door_MetalDark and Glass after first mesh load.
2. User: author a scene-level material override on the regenerated prefab, run Stage 2, confirm the patch resolves.
3. README + `project/converter_working_status.md` row "Multi-material slots" needs the format note updated from `{0}, {1}, ...` to `{} default + materialsByLabel`.
