---
name: output-propagation-working-doc
description: Living status log for F-9 — output propagation + per-asset state index + patch detection.
metadata:
  type: project
---

# F-9 Output Propagation + Patching — Working Documentation

Newest entries on top. Linked plan: [[output-propagation-plan]].
Sibling features: [[orchestration-plan]] (F-8 — pre-flight + Run All
that drives F-9's worker), [[profile-editor-plan]] (F-10 — defers the
profile authoring UI; F-9 ships only the data model + one catch-all
profile).

## 2026-05-27 — F-9.I.6b shipped ✓ (in-engine modification detection)

### What landed

**`project_manager.detect_externally_modified(state_index, tolerance=1.0)`**

Returns `{materials: set(guid), meshes: set, textures: set, prefabs: set}`
for assets whose `output_files[i].mtime` exceeds the saved
`last_emitted` timestamp + tolerance. Tolerance absorbs the
write-then-record gap and FS subsecond rounding (default 1.0s).
Entries without `last_emitted` are skipped — can't compare. Entries
whose output file is unstat-able (deleted) are also skipped because
the existing dirty-detection path catches that case via
`output_files` existence.

Helper `_parse_iso_to_epoch(iso)` lives next to it — accepts the
trailing `'Z'` form `_utc_now_iso` produces. Both helpers are
import-safe (no Qt dependency).

**MaterialTab — `✎` marker + summary**

- `_refresh_inventory` runs `detect_externally_modified(state_index)`
  on every refresh and renders a `✎` glyph in the row prefix for
  flagged materials.
- Foreground colour priority: external-mod (orange `#fab387`, bold) >
  override (cyan, bold) > unmapped (yellow). External-mod takes
  precedence because the user-visible risk is destructive — re-emitting
  *overwrites* the in-engine edit, while dirty just means stale.
- Tooltip extends with: "✎ Output edited in-engine since last emit —
  re-patching will OVERWRITE those changes."
- Summary line appends `N edited externally` when count > 0.
- The `_dirty_summary` band re-prioritises: external-mod wins over
  generic dirty when both are present, so the user sees the
  destructive warning first.

**Tab activation — `showEvent`**

`MaterialTab.showEvent` re-runs `apply_project(current)` so opening
the tab triggers a fresh stat pass. The user's explicit ask: open the
tab → see what changed in-engine since last patch. Without this, the
detection would only fire on `project_changed` / `status_changed`
events, missing the "I tabbed away, edited a material in O3DE, came
back" workflow.

### Verification (T-16a → T-16f)

- ✓ Helper returns empty set when all output mtimes precede
  `last_emitted`.
- ✓ Helper flags only files whose mtime > `last_emitted` + 1s
  tolerance.
- ✓ Inventory marks A (clean), B (✎ external), C (↻ dirty + output
  deleted) correctly — markers are mutually exclusive.
- ✓ Summary reports `N edited externally` count.
- ✓ Dirty summary band copy explicitly warns about destructive
  re-patch behaviour.
- ✓ `showEvent` re-runs the stat pass — bumping a file's mtime to
  the future while the tab is hidden causes the `✎` marker to appear
  after the next `show()`.

### Marker legend (final)

```
★    Override applied        (bold cyan)
⚠    Shader unmapped         (yellow)
↻    Dirty / stale output    (added by source/settings change)
✎    Edited in-engine        (bold orange — re-patch is destructive)
```

`★` and `✎` are not mutually exclusive — a material can carry both
markers. Tooltip lines describe each independently.

### Scope notes

- Detection runs against materials only in this slice. Mesh and prefab
  buckets are populated by the helper but the UI surface for them
  lives in MeshTab / PrefabsTab, which haven't been retrofitted yet.
  Same pattern would extend trivially when those tabs gain a parallel
  Patch action.
- mtime-based detection is best-effort. Hash-based verification
  (computing a digest of the emitted file at write time + comparing
  on read) is more accurate but heavier and currently unnecessary —
  mtime + a 1-second tolerance covers the common edit-in-O3DE case
  without false positives.

## 2026-05-27 — F-9 phase complete ✓ (I.3 → I.6)

[Prior entry — see git history for I.3 / I.4 / I.5 / I.6 details.]

## F-9 Phase Status

- [x] I.1   — Schema + materialtype resolver
- [x] I.1b  — Shader profile schema + default profile + UI picker switch
- [x] I.2   — Material emission honours profile chain
- [x] I.3   — Mesh emission honours defaults + overrides
- [x] I.4   — State index recording
- [x] I.5   — Dirty detection + Patch worker
- [x] I.6   — UI dirty markers + per-tab Patch button
- [x] I.6b  — External-modification detection (this entry)
- [x] I.7   — Verification matrix

## What this unlocks

- F-6 / F-5 settings actually propagate to the emitted O3DE assets.
- F-8's "Run All" orchestrator has the worker plumbing it needs.
- F-8's "Patch All" can call the same `patch()` method.
- F-9's `detect_externally_modified` is general — mesh, prefab,
  texture tabs reuse the same helper when they get a Patch action.
- F-10's profile editor will edit `shader_profiles` entries that F-9's
  worker already consumes.

## Deferred to follow-ups (still aligned with the plan)

- Extending `✎` markers to MeshTab + PrefabsTab inventory rows.
- Per-asset hash verification (cryptographic vs mtime-only) for paranoid
  detection.
- "Refresh from disk" button that re-fingerprints in-engine edits
  back into the state_index so the user can adopt their O3DE-side
  changes as the new baseline.
- Orphan detection / cleanup.
- Texture copy-on-rebind for override paths outside the project's
  `Textures/` folder.
- F-10's profile authoring UI.

## Next session

Move into F-8 — Mission Command pre-flight + Run All orchestrator
on top of F-9's worker. See [[orchestration-plan]].
