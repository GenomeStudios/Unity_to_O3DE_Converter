# Mesh Patch Worker — Working Documentation

Newest entries at top.

Pair plan: `mem:mesh_patch_worker/mesh_patch_worker_plan`.

---

## 2026-05-27 — Plan written; user reported the gap

**Trigger:** user observed that mesh override changes don't dirty-mark
in the Patch UI, and FBX assets in O3DE stay rotated 90° wrong with no
way to scrub the in-engine state back to converter authority.

**Root cause confirmed in code:** F-9.I.5 patch worker at
[integrated_asset_processor.py:787-866](integrated_asset_processor.py#L787-L866)
iterates `self._state_index_in["materials"]` only. The docstring at
lines 796-800 spells out the deferral and the required fix
("per-FBX re-entry point that rebuilds entity_node_map without the prefab
parse … the patch worker could call write_fbx_assetinfo directly if the
entity map were cached per-mesh in state_index").

**Workaround for the user's current blocker:** Run All re-emits FBX
assetinfo correctly. For a single offending mesh, unmark every prefab
that doesn't reference it in the Prefabs tab and Run All — touches
only the affected set.

**Plan landed:** `mem:mesh_patch_worker/mesh_patch_worker_plan`.

4 implementation stages:
- I.1 — Cache `fbx_stem` + `entity_node_map` + `collider_entity_node_map`
  in the mesh state-index entry.
- I.2 — Mesh dirty-detect + re-emit loop in `patch()`. Closes the
  override-change, scrub, and stale-cache cases.
- I.3 — Meshes tab Patch button + ✎/↻ row markers, mirroring MaterialTab.
- I.4 — Docstring + cross-reference memory refresh.

Soundness fallback: a soundness check at patch time validates the cached
`entity_node_map` against current FBX node names. If a cached node name
no longer exists in the FBX, the patch worker emits a "needs reparse"
warning and skips that mesh — Run All resolves it. This converts a
silent failure mode into a visible one without expanding the cache to
full hierarchy serialisation.

---

## Pre-plan state of the world (for archeology)

- `_record_mesh_state` records `{source_path, source_mtime, output_files,
  input_hash, last_emitted}` per mesh GUID. No cached entity-node map.
- `write_fbx_assetinfo` needs `entity_node_map`,
  `collider_entity_node_map`, `fbx_stem`, plus the platform's
  `correction_quat` and the project's `mesh_settings`. The first three
  are computed during prefab parse and discarded after emit.
- `detect_externally_modified` returns a `meshes:` bucket already
  (state_management/state_management_plan landed this). The ✎ marker
  fires correctly; the Patch action behind it is the missing piece.
- MaterialTab has a fully-working Patch button and ↻/✎ markers; the
  MeshTab does not.
