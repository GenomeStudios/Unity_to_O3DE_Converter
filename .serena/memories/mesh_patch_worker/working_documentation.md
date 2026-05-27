# Mesh Patch Worker — Working Documentation

Newest entries at top.

Pair plan: `mem:mesh_patch_worker/mesh_patch_worker_plan`.

---

## 2026-05-27 — Landed in one session (I.0–I.4 + 3 in-flight follow-ups)

The mesh patch worker shipped. Tests green at 19/19 modules under `py -3.13`.

### What landed (canonical stages)

**I.0 — Override normalisation in MeshTab.**
`MeshTab._on_field_changed` now calls `_prune_redundant_overrides`
after each field commit. An override whose every present key is
value-equal to the project defaults is dropped automatically; the
★ marker clears. Symmetric on both convergence paths (override edited
back to default, default edited to match a prior override). Equality
tolerance: `1e-6` per vec3 component. Test:
`tests/ui/test_mesh_override_pruning.py` (6 cases).

**I.1 — Cached entity-node maps in mesh state-index.**
`_record_mesh_state` now accepts and stores `fbx_stem`,
`entity_node_map`, `collider_entity_node_map`. The single producer
call site in `process_prefab` passes the maps it computes locally
during prefab parse. Pre-I.1 entries land with empty maps and the
patch loop treats them as "needs reparse". Test:
`tests/unit/test_mesh_state_index_shape.py` (2 cases).

**I.2 — Mesh dirty-detect + re-emit loop in `patch()`.**
After the material loop, `_patch_meshes(summary)` iterates
`state_index_in["meshes"]`:
- Hash diff on `{source_path, source_mtime, mesh_settings_effective}`.
- Missing-output check (covers the in-engine-edit scrub path: user
  deletes the assetinfo, Patch restores).
- Soundness gate: `read_fbx_mesh_node_names(fbx)` ∩ cached map. Stale
  node names → `meshes_need_reparse` (skip, log warning, recommend
  Run All).
- Re-copy source FBX when mtime advanced.
- Re-emit via `write_fbx_assetinfo` with current `mesh_settings` +
  platform `correction_quat`.
- `_record_mesh_state(...)` refreshes the entry preserving cached maps.
Returns extended summary: `meshes_dirty / meshes_emitted /
meshes_need_reparse` alongside the material counts. Tests:
`tests/integration/test_mesh_patch_worker.py` (4 scenarios — override
change, scrub, stale cache, clean-patch smoke).

**I.3 — Meshes tab Patch button + ↻/✎ row markers.**
`MeshTab` now mirrors MaterialTab's Patch pattern:
- "Patch Dirty Meshes" button + `_dirty_summary` band.
- `showEvent` re-runs `apply_project` on tab activation so external-mod
  markers refresh.
- `_refresh_inventory` reads `state_index["meshes"]` for ↻ (missing
  outputs / never emitted) and `detect_externally_modified` for ✎
  (in-engine edits since last_emitted).
- Foreground colour ladder: external-mod (orange) > override (cyan
  bold) > plain.
- Click handler runs `IntegratedAssetProcessor.patch()` off the GUI
  thread (`WorkerThread` pattern) and merges the resulting state-index
  back into the project. Result dialog reports counts and lists meshes
  that need full Run All.
Tests: `tests/ui/test_dirty_markers.py` MeshTab block (3 new cases).

**I.4 — Docstring + memory refresh (this entry + below).**

### In-flight follow-ups landed in the same session

The user surfaced three issues mid-implementation while testing
behaviour. All three landed alongside the mesh patch worker so the
mesh re-emission story is fully usable on first commit:

**FU1 — Y-up auto-correction removed from `write_fbx_assetinfo`.**
The previous behaviour detected Y-up FBX (`up_axis == 1`) and
multiplied the user's authored rotation against the platform's
`Y_UP_ROTATION` quaternion. Once `mesh_settings.default_rotation`
became user-authorable, the auto-correction overcompensated — typing
"90 X" produced an effective 180° because the auto-correction was
already baked in. Removed. The user's Euler is converted directly to
a quaternion and written into the `CoordinateSystemRule` with no
composition. Y-up detection is retained for an informational log line
only. `correction_quat` is still accepted as a parameter for plugin
authors who may want to opt into a different default later, but the
writer no longer applies it. Test:
`tests/unit/test_assetinfo_writer.py:test_y_up_does_not_auto_correct_rotation`
+ `test_zero_user_rotation_on_y_up_writes_no_rotation`. The prior
`test_y_up_correction_composes_with_user_rotation` was inverted to
guard against accidental re-introduction.

**FU2 — Direct mesh-settings → assetinfo mapping confirmed.**
Same change as FU1 from a different angle. The user wanted "90 on X
in the override → 90 on X in the rule, nothing fancy." The
auto-correction removal IS the direct-mapping landing.

**FU3 — Material provenance in state-index + MaterialTab tooltip.**
Added a sibling resolver `_resolve_profile_name_for_material` that
returns `(profile_name, profile_dict)`. The original
`_resolve_profile_for_material` is now a thin wrapper. Extended
`_record_material_state` to accept `profile_name` + `shader_name`
kwargs and store them on the state-index material entry. Call site in
`_process_material` now passes both. The MaterialTab's row tooltip
surfaces one of three states per material:
- "Last emitted by profile: X (shader recorded as: Y) … 2026-05-27T…"
  — the F-9 chain emitted this file.
- "Last emitted via legacy hardcoded path (no F-9 profile recorded —
  re-emit to capture provenance)." — emitted before profile_name was
  recorded, or via the legacy `material_settings=None` path.
- "Never emitted by this converter — output on disk (if any) is from
  a prior tool or hand-authored." — no state-index entry exists.
Tests: `tests/integration/test_material_emission.py:test_state_index_records_profile_provenance`
+ `test_state_index_provenance_blank_in_legacy_fallback`.

### Test count delta

Pre-session: 17 modules / 96 tests after Pass-2 consolidation.
Post-session: 19 modules / ~108 tests.
- +1 module: `tests/ui/test_mesh_override_pruning.py` (6 cases)
- +1 module: `tests/unit/test_mesh_state_index_shape.py` (2 cases)
- +1 module: `tests/integration/test_mesh_patch_worker.py` (4 cases)
- +3 cases in `tests/ui/test_dirty_markers.py` (MeshTab block)
- +1 case (inverted) in `tests/unit/test_assetinfo_writer.py`
- +1 case (zero-rotation-on-Y-up) in `tests/unit/test_assetinfo_writer.py`
- +2 cases in `tests/integration/test_material_emission.py` (provenance)

### What's still NOT done (separate plans needed when picked up)

- Per-row "force re-emit this mesh" button — tab-level Patch suffices
  for now.
- Prefab patch worker — still goes through Run All.
- Smarter FBX node-rename handling (re-derive cached map from cached
  entity names rather than failing to "needs reparse").
- AssetDatabase wiring in Stage 2 — Scene tab still emits nothing for
  unowned-entity meshes/materials.
- F-7 terrain heightmap extraction.
- F-10 profile editor UI for filling out the shader-profile library.
- `targets/o3de/material_writer.py` extraction.
- Stage-1 worker migration into `platforms/unity/`.

### Risks resolved during implementation

- The soundness check's smoke assertion (Run All → immediate Patch
  reports zero `meshes_need_reparse`) is captured in
  `test_clean_patch_reports_zero_need_reparse`. Guards against
  `read_fbx_mesh_node_names` regressions silently flagging every mesh
  as stale.

- Per-emit `_uuid.uuid4()` in MeshGroup `id` fields would have broken
  byte-equal scrub assertions. Resolved by adding `_strip_volatile`
  to the integration test that compares structural equality.

---

## 2026-05-27 — Plan written; user reported the gap (earlier the same day)

Trigger and design notes — see earlier entry. The plan landed; all
five stages plus the three in-flight follow-ups shipped in one
session because each piece was small once the plan locked the design.
