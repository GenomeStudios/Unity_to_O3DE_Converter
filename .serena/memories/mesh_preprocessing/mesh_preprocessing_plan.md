---
name: mesh-preprocessing-plan
description: Design + locked decisions for F-5 — defaults + per-mesh overrides on the Mesh tab. Multi-select inventory with override markers and standard mixed-state editing semantics.
metadata:
  type: project
---

# F-5 Mesh Preprocessing — Plan

## Goal

Give the Mesh tab a real editor for per-mesh import behaviour:

- A project-wide **defaults** block that applies to every mesh by
  default (zero position on/off, default position vec3, default
  rotation vec3).
- A read-only mesh **inventory** list sourced from
  `outputs.asset_processor.meshes`. Meshes are NOT de-selectable —
  selection is for editing only. ★ markers identify meshes with
  overrides.
- A per-selection **override editor** that supports multi-select. Common
  values display normally; mixed values show `…`. Editing a field
  applies to every selected mesh.

The actual `.assetinfo` write-time application of overrides arrives in
a follow-up iteration; this F-5 phase ships the storage and editor.

## Resolved Decisions (Q&A)

**Q1 — Are meshes (and materials) de-selectable from the inventory?**
A: **No.** They're derived from Prefab Processor outputs; removing
them would break prefab and scene dependencies. The inventory list is
read-only as content but multi-selectable for editing purposes.

**Q2 — Which fields are tracked at v1?**
A: Three: `zero_position` (bool), `default_position` (vec3),
`default_rotation` (vec3). Matches the roadmap. Future fields slot
into the same shape.

**Q3 — Where do defaults vs overrides live?**
A: New `stages.mesh_processor` stage:
```json
"mesh_processor": {
  "defaults":  { "zero_position": true, "default_position": [0,0,0],
                 "default_rotation": [0,0,0] },
  "overrides": { "<mesh_guid>": { ...partial...} }
}
```
Override values can be partial — any field not present inherits the
defaults at read time.

**Q4 — How are mesh entries keyed in overrides?**
A: By **mesh GUID** (the key in `outputs.asset_processor.meshes`).
Stable across runs as long as the source mesh stays in scope.

**Q5 — Multi-edit semantics?**
A: Standard "Inspector" pattern:
- Field reads the *effective* value (override-or-default) for every
  selected mesh.
- If all match → display the value.
- If they differ → display `…` placeholder (clear text).
- On commit → apply to every selected mesh as an override entry.
- Tristate checkbox for bools so mixed state renders as
  `Qt.PartiallyChecked`.

**Q6 — How is "edited to all the same" detected?**
A: Implicit. After every field commit we recompute the common value
from current state. If everyone now agrees, the field naturally shows
that value.

**Q7 — Override marker rendering?**
A: Prefix the inventory line with `★ ` and use bold cyan font color.
Plain meshes get a 3-space indent so the columns line up. Tooltip
extends to mention the override.

**Q8 — Where does the Process button go?**
A: A disabled stub at the bottom for now ("Process (per-mesh worker —
coming)"). The override storage is functional; the worker that
applies overrides at `.assetinfo` generation time is the follow-up.

**Q9 — Do defaults edits create overrides?**
A: No. Editing the defaults block updates only `defaults`. Editing
the override block creates/updates entries in `overrides`. The two
forms are visually distinct.

**Q10 — Clearing an override?**
A: A `Clear Override for Selection` button at the bottom of the
override section. Drops every selected mesh's entry from `overrides`,
returning them to default behaviour.

## Design

### Schema

```json
"mesh_processor": {
  "defaults": {
    "zero_position":    true,
    "default_position": [0.0, 0.0, 0.0],
    "default_rotation": [0.0, 0.0, 0.0]
  },
  "overrides": {
    "<guid>": { ...partial override... }
  }
}
```

Mesh field declaration lives at module scope:

```python
_MESH_FIELDS = [
    ("zero_position",    "Zero position on import",     "bool"),
    ("default_position", "Default position (X / Y / Z)", "vec3"),
    ("default_rotation", "Default rotation (X / Y / Z)", "vec3"),
]
```

Adding a new field is a single-line edit (plus a `defaults` addition).

### `_FloatField` widget

QLineEdit subclass with:
- `QDoubleValidator` for numeric input
- `set_common(value)` — display the value
- `set_common(None)` — show `…` placeholder, blank text
- `set_disabled_blank()` — clear + disable for "no selection" state
- `committed(float)` signal on `editingFinished`, suppressed during
  programmatic updates

### `MeshTab` layout

```
+-- Default Mesh Settings -------------------------+
| [✓] Zero position on import                      |
| Default position: X[ ] Y[ ] Z[ ]                 |
| Default rotation: X[ ] Y[ ] Z[ ]                 |
+--------------------------------------------------+

+-- Mesh Inventory --------------------------------+
| ★ Alpha          (override)                      |
|    Bravo                                         |
| ★ Charlie        (override)                      |
+--------------------------------------------------+

+-- Selection Overrides (N selected) --------------+
| [✓] Zero position    (tristate when mixed)       |
| Default position: X[ ] Y[…] Z[ ]                 |
| Default rotation: X[ ] Y[ ] Z[ ]                 |
| [Clear Override for Selection]                   |
+--------------------------------------------------+
```

Override section's header reads "N mesh(es) selected · M with
override(s) · editing applies to all selected" so the user knows the
scope of their edit.

### Mixed-state for vec3 fields

Per-axis comparison. A selection where all meshes have
`default_position = [0,5,0]` shows X=0, Y=5, Z=0. If one mesh has
`[0,5,0]` and another has `[1,5,0]`, then X is mixed but Y and Z are
common.

### Suppression flag

`self._suppress_field_signals` — set True around any programmatic
field update (refresh after selection change, after edit cascade) so
the field's commit signal doesn't loop back.

## Implementation Plan

### I.1 — Schema + deep-merge handling
**Done when:** `mesh_processor` added to `_default_stages()`.
Existing testbed projects load with the field via `from_json`'s
per-stage deep merge (already in place from F-4).

### I.2 — `_FloatField` widget
**Done when:** Class exists, signal model verified by manual call.

### I.3 — Rewrite `MeshTab`
**Done when:**
- Defaults form at top, hooked to update `defaults` dict in stage.
- Multi-select inventory with override markers.
- Override form below inventory; refreshes on selection change.
- Field commits apply to all selected; defaults commits apply to
  defaults only.
- `Clear Override for Selection` clears entries for selected guids.
- Last Run Details block (per-mesh listing) matches the Prefab/Scene
  patterns.
- Process button stays disabled with a "coming soon" tooltip.

### I.4 — Verification

| ID | Proof |
|---|---|
| T-1 | mesh_processor stage carries defaults `{zero_position:True, default_position:[0,0,0], default_rotation:[0,0,0]}` after open |
| T-2 | Inventory renders correctly from `outputs.asset_processor.meshes` |
| T-3 | Pre-override selection: fields display inherited defaults; checkbox Checked; positions all 0 |
| T-4 | Editing position Y → 5.0 with 2 meshes selected creates `overrides[guid].default_position == [0, 5, 0]` for both |
| T-5 | Both meshes now show ★ marker in inventory |
| T-6 | Selecting all 3 (2 with override Y=5, 1 inheriting Y=0) → Y field shows `…` placeholder, X and Z show 0 |
| T-7 | Editing Y → 7.5 across all 3 → Y converges, placeholder clears, all 3 have override |
| T-8 | Clear Override on Charlie alone → Charlie loses override, Alpha/Bravo keep theirs |
| T-9 | Editing default zero_position → False persists into `defaults.zero_position` |

## Out of scope (deliberately)

- **Per-mesh assetinfo write-time application.** This phase ships the
  storage + editor. The worker that consumes the overrides at
  `.assetinfo` generation time arrives in the next F-5 iteration.
- **Coordinate-system overrides** (Y-up vs Z-up beyond what Stage 1
  already handles globally). Possible future override field.
- **Material-side analog.** F-6 ships the same shape for materials
  (shader-mapping library + per-material override). Same `_FloatField`
  / multi-edit infrastructure reused.
- **Mesh-mesh dependency tracking** (e.g. "which prefabs use this
  mesh"). Useful but not blocking.
- **Bulk operations** beyond "Clear Override for Selection" (e.g. copy
  override from A to B). Defer until needed.
