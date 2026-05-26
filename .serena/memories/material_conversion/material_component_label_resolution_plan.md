# Material Component By-Label Override Resolution Plan

## Context / Motivation
The Unity-to-O3DE Converter generates `.prefab` files containing `EditorMaterialComponent.Controller.Configuration.materials` keyed by `MaterialAssignmentId`. Because the pipeline runs BEFORE the FBX is processed, it has no access to SceneAPI MaterialUid stable IDs and falls back to writing positional/synthetic stable IDs (`{0}`, `{1}`, ...). At runtime, `MaterialComponentController::LoadMaterials()` walks the real mesh's `m_defaultMaterialMap` (with SceneAPI-hashed StableIds) and lookups against the synthetic keys all miss. The orphaned entries persist in `m_configuration.m_materials` but never reach `m_uniqueMaterialMap`, never queue asset loads, and never display in the inspector. The Default slot (`{}` = `IsDefault()`) survives because `GetDefaultMaterialMapFromModelAsset` unconditionally inserts `DefaultMaterialAssignmentId`.

## Design (Locked)

### Data model
Add a sidecar map to `MaterialComponentConfig`:
```cpp
AZStd::unordered_map<AZStd::string, MaterialAssignment> m_materialsByLabel;
```
Key: the slot's `m_displayName` (FBX material slot name == `MaterialConsumerRequestBus::GetMaterialLabels()` value).

### Resolution semantics
- **Label-only** (no LOD form). Resolves to `MaterialAssignmentId::CreateFromStableIdOnly(stableId)`, applies to every LOD with a matching slot label.
- **Keep intact**: resolution is non-destructive. Resolved entries are *projected* into `m_configuration.m_materials`; the by-label entries stay so future mesh swaps can rebind.
- **Explicit-key precedence**: if an `m_materials` entry already exists for the resolved id, the by-label projection is skipped (explicit author intent wins).

### Where the resolution runs
Inside `MaterialComponentController::LoadMaterials()`, after `m_defaultMaterialMap` is populated and before the `m_uniqueMaterialMap` loop. The pass:
1. `MaterialConsumerRequestBus::EventResult(labels, m_entityId, &Events::GetMaterialLabels)`.
2. Build `label -> generalId` for `id.IsSlotIdOnly()` entries.
3. For each `(label, assignment)` in `m_materialsByLabel`: lookup, insert into `m_materials` if absent.

## Resolved Decisions

**Q: Label-only or LOD-aware?** A: Label-only. Unity assets are flat-list; LOD-specific overrides aren't a use case.

**Q: Drain on resolve, or keep entries?** A: Keep intact. Resolution is idempotent and survives mesh swaps.

**Q: Where does the patch live?** A: Patch `o3de_sourcedev` directly. User owns the checkout; upstream PR optional.

**Q: Does the by-label entry overwrite an explicit `m_materials` entry?** A: No. Explicit `m_materials` (whatever its key) wins. By-label is a recovery mechanism, not an authoritative source.

## Implementation Plan

### I.1 — MaterialComponentConfig data + reflection (Plan -> Code)
Files: `MaterialComponentConfig.h`, `MaterialComponentConfig.cpp`.
- Add `m_materialsByLabel` field.
- Bump `Version(3)` → `Version(4)`; reflect new field as `"materialsByLabel"`. No ConvertVersion needed for 3→4 (new field defaults to empty for old data).
- Add `BehaviorContext` property for scripting parity.
**Done when**: compiles; old prefabs deserialize without errors; new field round-trips through serialize/deserialize.

### I.2 — LoadMaterials() resolution pass
File: `MaterialComponentController.cpp`.
- After `MaterialConsumerRequestBus::EventResult(m_defaultMaterialMap, ...)` and before the unique-material loop:
  - Fetch labels via `MaterialConsumerRequestBus::Events::GetMaterialLabels`.
  - Build `unordered_map<string, MaterialAssignmentId>` for IsSlotIdOnly entries.
  - For each entry in `m_materialsByLabel`, resolve and insert into `m_materials` if absent.
**Done when**: stepping through with a prefab containing `materialsByLabel` results in `m_materials` containing the resolved entries after first mesh load.

### I.3 — Pipeline-side emission (out of engine scope, tracked here)
- Converter writes `materialsByLabel` instead of (or in addition to) `materials` for non-default slots.
- Default slot continues to use `materials: {"{}": ...}`.
**Done when**: A generated prefab loads and the editor inspector shows both default + named overrides on first activate, with no `materials.{0}` / `materials.{1}` style entries needed.

## Testing Matrix

| Test | Stage | Form | Proof |
|---|---|---|---|
| Old prefab with `materials` only still loads + applies | I.1 | Behavioral | Open existing Atom sample prefab; overrides still show. |
| New prefab with `materialsByLabel` only resolves on mesh ready | I.2 | Behavioral | Edit `W_2x_glass_A.prefab` to use new format; load; verify Door_MetalDark on Body slot, Glass on Glass slot. |
| Mesh swap rebinds labels | I.2 | Behavioral | Swap mesh to a model with same-named slots in different StableId order; verify overrides re-bind. |
| Explicit `materials` entry wins over `materialsByLabel` | I.2 | Behavioral | Author both for same slot with different assets; verify `materials` entry is used. |
| Unresolved label survives serialization | I.2 | Behavioral | Author a `materialsByLabel` entry with no matching slot; save; reload; entry still present. |

## Risks
- Label collisions across slots: if two slots share a `m_displayName`, first-write-wins on `labelToGeneralId`. Acceptable — slot display names should be unique within a model.
- Asset-hint preservation through `InitializeNotifiedMaterialAsset`'s `materialAsset = asset` replacement: orthogonal to this fix. Hints lost there are about the live asset's hint vs the saved-data hint after the asset loads. Not in scope here.
