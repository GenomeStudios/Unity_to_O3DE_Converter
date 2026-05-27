# Mesh Patch Worker — Plan

**Status:** Design-locked. Sequential implementation.
**Topic folder:** `mesh_patch_worker/`
**Pair file:** `mem:mesh_patch_worker/working_documentation`
**Adjacent context:** `mem:output_propagation/output_propagation_plan` (F-9 state index + Patch worker, materials only — the prior art), `mem:mesh_preprocessing/mesh_preprocessing_plan` (F-5 mesh settings schema), `mem:state_management/state_management_plan` (external-mod detection / scrub).

---

## Why this exists

The F-9 Patch worker only handles materials. The docstring at
[integrated_asset_processor.py:796-800](integrated_asset_processor.py#L796-L800)
admits the deferral verbatim:

> Scope: materials only in F-9. … Mesh-only patches need a per-FBX re-entry
> point that rebuilds entity_node_map without the prefab parse.

User-visible symptoms when this gap bites:
- Editing a mesh override (e.g. rotation correction in `mesh_settings`)
  registers no dirty count in the Patch summary.
- The mesh's per-row ↻ marker never lights.
- The on-disk `.assetinfo` keeps its stale `CoordinateSystemRule`; mesh
  imports stay rotated 90° wrong in O3DE indefinitely.
- The ✎ in-engine-edit marker fires, but the Patch action behind it is
  a no-op for meshes — the user can't "scrub" their in-engine modification.

This plan closes that gap, plus adds an override-normalisation pre-stage
so "has override" genuinely means "differs from default" before the patch
worker decides what's dirty.

---

## Design

### I.0 addition: override normalisation

Goal: edits to defaults or overrides that result in an override-dict
identical to the defaults silently delete the override and clear its
★ marker. Knock-on: "Restore Defaults" can be discovered organically —
the user just edits values back to default and the marker disappears.

Two trigger points:

1. **Override edit converges on default.** After
   `_apply_field_value(entry, key, value)`, check whether `entry` is
   now value-equal to `defaults` on every key present in `entry`. If
   yes, drop the GUID from `overrides`.
2. **Default edit makes prior overrides redundant.** After
   `_apply_field_value(defaults, key, value)`, walk every entry in
   `overrides`; drop any GUID whose entry is now value-equal to
   `defaults` on every key present in the entry.

Equality semantics:
- Scalar / bool / string → `==`.
- Vector (list of floats) → element-wise `abs(a-b) < 1e-6`.
- Missing key in `entry` is "no opinion" — not an override; never
  considered.

Implementation point: a small `_prune_redundant_overrides(overrides,
defaults)` helper in `MeshTab` called at the end of both paths inside
`_on_field_changed`. Idempotent.

### What gets cached in the mesh state-index entry (I.1)

The current entry::

```jsonc
{
  "source_path":  "...",
  "source_mtime": 0.0,
  "output_files": ["<fbx_path>", "<fbx_path>.assetinfo"],
  "input_hash":   "...",
  "last_emitted": "2026-05-27T..."
}
```

Three new serialisable fields::

```jsonc
{
  ...existing fields...,
  "fbx_stem":                  "Closet_A",
  "entity_node_map":           {"Door": "RootNode.Closet_A.Door", ...},
  "collider_entity_node_map":  {"Door": "RootNode.Closet_A.Door"}
}
```

### How the mesh patch loop works (I.2)

Mirror the existing `patch()` material loop:

1. Iterate `self._state_index_in["meshes"]` after the material loop.
2. For each saved entry:
   a. Resolve source path; skip if missing (orphan cleanup is future work).
   b. Compute current `input_hash` from
      `{source_path, source_mtime, mesh_settings_effective(guid)}`.
   c. Dirty when: hash mismatch OR any `output_files[i]` missing.
   d. **Soundness check before re-emit:** read current FBX node names via
      `read_fbx_mesh_node_names(fbx_path)`. Every value in the cached
      `entity_node_map` must reference only nodes that still exist. If
      a cached node name has disappeared, the cache is stale —
      log `[Patch] WARNING:`, mark `summary["meshes_need_reparse"]`,
      skip. Run All resolves these.
   e. Re-copy source FBX if its mtime exceeds the saved entry's
      `source_mtime`.
   f. Call `write_fbx_assetinfo(fbx_path, fbx_stem, entity_node_map,
      log, collider_entity_node_map=..., mesh_settings=self._mesh_settings,
      mesh_guid=guid, correction_quat=self.platform.correction_quat)`.
   g. Call `_record_mesh_state(...)` to update the entry's `input_hash`,
      `last_emitted`, `output_files`. Cached maps preserved.
3. Return summary keys: `meshes_dirty`, `meshes_emitted`,
   `meshes_need_reparse`.

### Scrub semantics

`detect_externally_modified` reports a `meshes:` bucket of GUIDs whose
output file mtime exceeds `last_emitted + tolerance`. The Patch action
treats every such GUID as dirty: re-emit overwrites the in-engine edit
with the converter's authoritative output. This IS the scrub.

If the user wants to KEEP an in-engine edit, they don't click Patch.

### Why we cache the resolved map vs re-derive

**Option A (chosen):** Cache the resolved `entity_node_map`. Patch path
is mechanical. Soundness check converts the rare "FBX restructured"
failure into a visible "needs reparse" notice.

**Option B (rejected):** Cache a serialised subset of the entity
hierarchy and re-derive the map per patch. Robust against renames but
doubles cache size and adds parser surface; failure mode is rare.

### Resolved decisions

**Q1: Schema migration for state-index entries that pre-date this work?**
A: An old entry without `entity_node_map` cannot be patched. Treat it
as `meshes_need_reparse` — log once and skip. Next Run All writes a
fresh entry with all three new fields. No version bump.

**Q2: Patch worker order — meshes before or after materials?**
A: After. Mesh assetinfo emit doesn't depend on materials being current.

**Q3: Should the patch worker re-copy the FBX even when only the
mesh_settings changed?**
A: No. Re-copy only when source mtime > recorded `source_mtime`.

**Q4: Per-row ↻/✎ markers on the Meshes tab?**
A: Yes. Mirror the MaterialTab pattern. Source from
`detect_externally_modified` + a `_dirty_meshes` cache populated after
each Patch summary returns.

**Q5: Per-row "Re-emit this mesh" button vs tab-level Patch?**
A: Tab-level only, mirroring `MaterialTab._patch_btn`. Per-row force is
a future refinement.

**Q6: Patch summary aggregation when both materials and meshes are
dirty?**
A: Per-tab reporting. MaterialTab reports material counts; MeshTab
reports mesh counts. They DON'T share a button.

**Q7: Does the orchestrator's "Patch All" (F-8) include meshes?**
A: Yes once I.2 lands. Orchestrator already calls `processor.patch()`;
the new mesh loop runs in the same call without orchestrator changes.

**Q8: Backwards-compat with old `.u2oproj.json` files?**
A: Anyone opening an older project file sees "needs reparse" warnings
the first time Patch runs. One Run All clears the warning. No
user-facing migration required.

**Q9: When override normalisation deletes a GUID's entry, does that
re-trigger a dirty patch?**
A: Yes — that's the right semantics. The effective mesh_settings for
that GUID has changed (override removed → falls back to defaults).
The state-index hash for that mesh changes accordingly; Patch re-emits.

**Q10: Equality tolerance for vector overrides?**
A: `1e-6` per component, matching the existing `is_uniform_scale`
tolerance pattern in `platforms/unity/types.py:Transform`.

---

## Implementation plan

Each stage ends with **`py -3.13 tests/run_all.py` green**.

### I.0 — Override normalisation in MeshTab

**Steps**
1. Add `_prune_redundant_overrides(overrides, defaults)` helper to
   `MeshTab` — returns a new overrides dict with redundant entries
   stripped.
2. In `_on_field_changed`, after `_apply_field_value(...)` runs, call
   the prune helper on `overrides` for both the `scope == "defaults"`
   and `scope == "override"` branches. Persist the pruned dict.
3. Run tests.

**Done when**
- Editing an override field back to the default value drops the GUID
  from `overrides` and clears the ★ marker.
- Editing a default field to match a prior override drops the
  redundant override and clears its ★ marker.
- `tests/run_all.py` green.

**Test alongside**
- Add `tests/ui/test_mesh_override_pruning.py` covering both
  convergence paths (override→default and default→override).

---

### I.1 — Cache the entity-node maps in the mesh state-index entry

**Steps**
1. Extend `_record_mesh_state` signature to accept `fbx_stem: str`,
   `entity_node_map: Dict[str, str]`,
   `collider_entity_node_map: Optional[Dict[str, str]]`.
2. Store those three fields alongside existing ones.
3. Update the single call site in `process_prefab` (lines 700-705)
   to pass the maps it already computes locally (lines 672-684).
4. Run tests.

**Done when**
- A fresh Run All produces state-index entries containing all three
  new fields.
- `tests/run_all.py` green.

**Test alongside**
- Add `tests/unit/test_mesh_state_index_shape.py` asserting a worker
  run produces mesh entries with all three new keys, populated correctly
  for a fixture prefab.

---

### I.2 — Mesh dirty-detect + re-emit in `patch()`

**Steps**
1. After the material loop in `patch()`, add the mesh loop per the
   design above (soundness check + scrub + stale-cache fallback).
2. Return summary keys: extend with `meshes_dirty`, `meshes_emitted`,
   `meshes_need_reparse`.
3. Update the closing log line to also report mesh counts.
4. Run tests.

**Done when**
- A mesh override change → Patch → assetinfo re-emitted reflecting
  the override.
- A touched `.assetinfo` (mimicking an in-engine edit) → Patch →
  assetinfo restored to converter authority.
- A stale state-index entry → Patch → `meshes_need_reparse` warning;
  mesh skipped.
- `tests/run_all.py` green.

**Test alongside**
- Add `tests/integration/test_mesh_patch_worker.py` exercising:
  - **A (override change):** Run All, edit a mesh override, Patch,
    assert assetinfo reflects the override.
  - **B (scrub):** Run All, `os.utime` the assetinfo past
    `last_emitted + 1s`, Patch, assert `last_emitted` advanced and
    contents are canonical.
  - **C (stale cache):** Hand-craft a state-index entry missing the
    new fields, Patch, assert the summary lists the GUID under
    `meshes_need_reparse` and the assetinfo on disk is untouched.
- Smoke assertion: Run All immediately followed by Patch reports zero
  `meshes_need_reparse`.

---

### I.3 — Meshes tab Patch button + row markers

**Steps**
1. Mirror `MaterialTab._patch_btn` on `MeshTab`: button labelled
   "Patch Dirty Meshes", handler `_patch_clicked()`.
2. `_patch_clicked()` runs the worker off the GUI thread (existing
   `_PatchWorker` pattern), surfaces a result dialog reporting
   `meshes_dirty / meshes_emitted / meshes_need_reparse`.
3. Add `_refresh_dirty_markers` to MeshTab — call
   `detect_externally_modified(state_index)` on tab activation and
   after Patch runs; mark mesh rows with ✎ when their GUID is in the
   `meshes:` bucket.
4. Add ↻ markers using the worker's reported `meshes_dirty` cache —
   a row whose GUID was dirty in the last Patch run shows ↻ briefly
   until the next refresh clears it.
5. Run tests.

**Done when**
- Meshes tab has a working Patch button.
- ✎ markers appear on mesh rows whose assetinfo was edited in-engine.
- Clicking Patch overwrites the in-engine edits and clears the marker.
- `tests/run_all.py` green.

**Test alongside**
- Extend `tests/ui/test_dirty_markers.py` with a MeshTab block —
  same shape as the existing MaterialTab tests.

---

### I.4 — Documentation + memory refresh

**Steps**
1. Update the patch-worker docstring at
   [integrated_asset_processor.py:787-805](integrated_asset_processor.py#L787-L805)
   to drop the "materials only in F-9" caveat.
2. Update `mem:project/converter_working_status` — drop the mesh-patch
   item from "Next Priority Areas".
3. Update `mem:output_propagation/working_documentation` + 
   `mem:mesh_preprocessing/working_documentation` with closing
   "mesh patch landed" entries pointing here.
4. Final pass: `mem:mesh_patch_worker/working_documentation` records
   the landed state.

**Done when**
- Cross-referenced memories accurate.
- Patch docstring no longer claims meshes are deferred.

---

## Testing matrix

| Stage | Proof |
|---|---|
| I.0 | `test_mesh_override_pruning.py`: both convergence paths drop redundant override + clear ★ marker. |
| I.1 | `test_mesh_state_index_shape.py`: mesh entries carry the 3 new keys after Run All. |
| I.2 | `test_mesh_patch_worker.py` scenarios A, B, C all pass. |
| I.3 | `test_dirty_markers.py` MeshTab block: ✎ marker on touched assetinfo, Patch clears. |
| I.4 | Docstring + cross-referenced memories accurate. |

---

## Out of scope

- Per-row "force re-emit this mesh" button.
- Orchestrator-side Patch All UI changes.
- Prefab patch worker.
- Smarter FBX node-rename handling (re-derive cached map from cached
  entity names).
- AssetDatabase wiring in Stage 2.
- F-7 terrain heightmap extraction.

---

## Risks

- **Soundness check false positives** if `read_fbx_mesh_node_names`
  ever regresses its parser tolerance. Mitigation: the post-I.2
  smoke assertion (Run All then immediate Patch must report zero
  `meshes_need_reparse`) catches parser regressions.

- **In-engine modification mtime drift** on coarse-resolution
  filesystems. Not new in this plan; flagged so I.3 dirty-markers
  test uses explicit `os.utime(...)` rather than wall-clock waits.

- **State-index size growth** ~2KB per asset pack. Negligible.
