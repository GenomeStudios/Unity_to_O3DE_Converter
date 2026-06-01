---
name: mesh-preprocessing-working-doc
description: Living status log for F-5 — mesh defaults + per-mesh overrides with multi-edit semantics.
metadata:
  type: project
---

# F-5 Mesh Preprocessing — Working Documentation

Newest entries on top. Linked plan: [[mesh-preprocessing-plan]].

## 2026-05-28 — Two MeshTab additions (Editor-only wrapper + physx_mesh)

- **Prefab-wrapper Editor-only toggle.** New project-wide key
  `mesh_processor.prefab_wrapper_editor_only` (default True). MeshTab gains
  a "Prefab Output" group-box with a "Make prefab wrappers Editor-only"
  checkbox (persisted via `_on_wrapper_editor_only_changed` →
  `update_stage`, synced in `_refresh_defaults_fields`).
  `targets/o3de/prefab_writer.create_container_entity` reads it off
  `worker._mesh_settings` and emits the ContainerEntity's
  `EditorOnlyEntityComponent.IsEditorOnly` accordingly (was hardcoded True).
- **`physx_mesh` per-mesh override.** New bool in `_MESH_FIELDS` (default
  False) + `mesh_processor.defaults.physx_mesh`. When effective-True for a
  mesh, `process_prefab` adds a whole-FBX ("everything") triangle PhysX
  group named `{stem}` over all the FBX's mesh nodes, so a `.pxmesh` cooks
  even when no Unity MeshCollider referenced that mesh. Deduped against
  collider-derived specs by group name. `_resolve_mesh_settings` carries
  `physx_mesh`. See `mem:physx_mesh_collider/working_documentation`.
- Verified end-to-end: editor-only OFF→`IsEditorOnly:false`,
  default→true; `physx_mesh` override on the un-collided Moss mesh →
  whole-FBX PhysX group in its assetinfo. Tests:
  `test_prefab_wrapper_editor_only` (3), `_resolve_mesh_settings_physx_mesh`.
  Full suite 24/24 (run `QT_QPA_PLATFORM=offscreen python tests/run_all.py`).

## 2026-05-27 — F-5 editor shipped ✓

### What landed

**Schema (I.1)**
- `_default_stages()` adds `mesh_processor`:
  - `defaults`: zero_position (bool), default_position (vec3),
    default_rotation (vec3).
  - `overrides`: dict keyed by mesh GUID with partial override entries.
- Per-stage deep-merge from F-4 picks up the new field automatically
  on existing project files.

**`_FloatField` widget (I.2)**
- QLineEdit subclass with `QDoubleValidator`, fixed 70px width, right-
  aligned.
- API: `set_common(value)` / `set_common(None)` / `set_disabled_blank()`.
- Signal: `committed(float)` only fires on `editingFinished` when not
  programmatically suppressed.

**MeshTab rewrite (I.3)**
- Three sections inside a scroll wrap: Default Mesh Settings, Mesh
  Inventory, Selection Overrides — plus the standard Last Run Details
  block at the bottom and a disabled "Process (coming)" button.
- Default form widgets: tri-state-disabled checkbox + three
  `_FloatField` per vec3 row.
- Inventory: ExtendedSelection mode, ★ prefix + bold cyan for
  overridden meshes, tooltip extends accordingly.
- Selection Overrides form: same shape, but tristate-capable
  checkbox so mixed bool values render as `Qt.PartiallyChecked`.
- `_refresh_override_fields` computes per-field common values across
  the selection; for vec3, per-axis comparison so X/Y/Z mix
  independently.
- `_on_field_changed(scope, key, value)` writes back to either
  `defaults` or `overrides` (applying to every selected guid for
  overrides).
- `_clear_override_for_selection` drops entries from `overrides` for
  the selected guids.

### Sanity gates passed

- `py project_manager.py` → smoke OK.
- `py -c "import main_app"` → OK.
- F-5 E2E against testbed:
  - mesh_processor schema present with correct defaults ✓
  - Inventory renders 3 meshes (no markers initially) ✓
  - 2 selected with no overrides → header reads "2 selected · 0 with
    override(s)", checkbox Checked, positions 0 ✓
  - Edit Y → 5.0 → both selected get `default_position = [0, 5, 0]` ✓
  - ★ markers appear on the 2 with overrides ✓
  - Select all 3 → Y shows `…` placeholder (mixed), X/Z stay `0` ✓
  - Edit Y → 7.5 across all 3 → Y converges, placeholder clears ✓
  - Clear Override on Charlie alone → Charlie loses entry, Alpha/Bravo
    keep theirs ✓
  - Default zero_position → False persists into the stage ✓

### Behaviour notes

- ★ marker uses Unicode U+2605. Plain rows get a 3-space indent so
  the columns line up.
- Defaults block uses `setTristate(False)` on the checkbox (defaults
  always have a concrete value). Override block uses `setTristate(True)`
  so mixed values render as the indeterminate state.
- The override section is always visible but renders a "Select one or
  more meshes above to edit." header + disabled controls when nothing
  is selected. Avoids the section appearing/disappearing as users
  navigate.
- `Clear Override` button is only enabled when at least one selected
  mesh has an entry in `overrides`. Prevents pointless clicks.

### Known follow-ups

- **Worker integration.** The override storage is wired; the
  IntegratedAssetProcessor still emits .assetinfo using its existing
  coordinate logic. Hooking the override read at write time is the
  next iteration of F-5.
- **Materials analog.** F-6 will adopt the same pattern (defaults +
  per-material overrides) reusing `_FloatField` and the mixed-state
  rendering for any numeric properties (factors, scalars). For
  shader-mapping enums F-6 will need a similar widget for combo
  boxes — `_ComboField` with `set_common(None)` showing `(mixed)`.
- **Override → file mapping.** Currently the override key is the mesh
  GUID. If the user re-runs Stage 1 with a different mesh set, stale
  overrides linger in the dict. A future polish could prune them when
  detected.

## Pending / not yet shipped

- The .assetinfo writer doesn't yet consume `mesh_processor.overrides`.
- Material side (F-6) — currently still a `_InventoryStubTab` stub.
- "Used by N prefabs" reverse-lookup on the inventory rows.
