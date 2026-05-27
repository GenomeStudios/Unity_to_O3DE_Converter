---
name: material-preprocessing-plan
description: Design + locked decisions for F-6 — shader mappings + per-material overrides on the Materials tab. Multi-select editor for target materialtype and texture rebinds.
metadata:
  type: project
---

# F-6 Material Preprocessing — Plan

## Goal

Make the Materials tab the place to:

1. Identify which Unity shaders are bound to a known O3DE materialtype
   (and which aren't, surfaced as `⚠` warnings).
2. Edit the **shader mapping table** that drives the default
   "Unity shader → O3DE materialtype" decisions.
3. Override target materialtype and texture bindings on a
   per-material basis, with multi-select bulk editing.

The actual `.material` re-emission worker arrives in a follow-up
iteration; this F-6 phase ships the **mapping table + override storage
+ editor**.

## Resolved Decisions (Q&A)

**Q1 — Are materials de-selectable from the inventory?**
A: **No.** Same answer as F-5 meshes — materials reflect what the
Prefab Processor produced; removing them would break prefab + scene
dependencies. Selection is for editing only.

**Q2 — What does the schema look like?**
A: New `stages.material_processor` with three sub-sections:
```json
"material_processor": {
  "defaults": {
    "target_materialtype": "StandardPBR.materialtype"
  },
  "shader_mappings": {
    "Standard":                       "StandardPBR.materialtype",
    "Universal Render Pipeline/Lit":  "StandardPBR.materialtype",
    ...
  },
  "overrides": {
    "<material_guid>": {
      "materialtype": "/abs/path/MyCustom.materialtype",
      "textures":     { "baseColor": "/abs/path/diff.png", ... }
    }
  }
}
```

**Q3 — Where does shader metadata come from?**
A: New `outputs.asset_processor.material_metadata` populated by
IntegratedAssetProcessor during `_process_material`. Each entry:
```
{ asset_hint, shader_name, source_path, source_stem, textures_bound }
```
Existing `outputs.asset_processor.materials` keeps its `{guid:
asset_hint_string}` shape so Stage 2's PrefabDatabase consumer keeps
working without changes.

**Q4 — Effective materialtype lookup chain?**
A: For a given material:
1. `overrides[guid].materialtype` if set
2. `shader_mappings[material's shader_name]` if mapped
3. `defaults.target_materialtype` (fallback)

The override field's "common value" surface uses this chain — two
materials that share an effective materialtype show the value;
otherwise the field renders `…`.

**Q5 — Texture rebind slots?**
A: Six standard StandardPBR slots: `baseColor`, `normal`, `metallic`,
`roughness`, `occlusion`, `emissive`. Per-slot override is independent.
Stored under `overrides[guid].textures[slot]`. Editing one slot
doesn't touch the others.

**Q6 — Inventory marker semantics?**
A: Two independent markers, both can appear:
- `★` — material has an override entry
- `⚠` — material's shader has no mapping AND isn't `(unknown)` (a
  literal unknown shader skips the `⚠` since the user can't map "I
  don't know what this is"; future iteration may add a per-material
  marker for unknown sources)
Plain materials use a 3-space indent so the columns align.

**Q7 — Bulk edit for texture rebinds?**
A: Same multi-edit semantics as F-5 floats:
- Common value across selection → field shows it
- Mixed → `…` placeholder
- Edit → applies to every selected material
- Clear per-slot — removes the slot override from each selected
  material (empties the `textures` sub-dict if it becomes empty;
  removes the override entry entirely if `textures` was the only key)

**Q8 — Override field widget?**
A: New `_PathField` — QWidget wrapping QLineEdit + Browse + Clear
buttons. Same API as `_FloatField` (`set_common(value)` /
`set_common(None)` / `set_disabled_blank()`). Browse opens a
file dialog; Clear emits `cleared` signal so callers can distinguish
"set to empty" from "remove the override".

**Q9 — What's deferred?**
A: 
- Raw `.mat` file editing (the user said "perhaps")
- Scalar property overrides (`metallic.factor`, `roughness.factor`,
  etc.) — said "ideally" — defer
- Cross-project shader-mapping library — F-6 ships per-project
  mappings; a global library lives in a future polish
- Worker integration (re-emitting `.material` files with override
  values applied) — same shape as F-5: storage ships, worker
  follows

## Design

### `_PathField` widget

```python
class _PathField(QWidget):
    committed = Signal(str)
    cleared   = Signal()

    def set_common(self, value)        # None → "…", "" → "(no path set)", str → text
    def set_disabled_blank(self)
```

Layout: `[QLineEdit] [Browse…] [Clear]`. Validators are intentionally
absent — paths can be relative, absolute, or asset hints.

### MaterialTab layout (top to bottom)

```
+-- Default Material Settings ----------------------+
| Fallback target materialtype                      |
| [...path...]              [Browse…] [Clear]       |
+---------------------------------------------------+

+-- Shader Mappings --------------------------------+
| One row per Unity shader: name + path field.      |
| Mapped shaders show name in normal color; unmapped|
| in yellow with ⚠ prefix.                          |
+---------------------------------------------------+

+-- Material Inventory -----------------------------+
| ★ Door            Standard                        |
|    Wall           Universal Render Pipeline/Lit   |
| ★ ⚠ Foliage       Custom/Foliage                  |
+---------------------------------------------------+

+-- Selection Overrides (N selected) ---------------+
| Target materialtype: [...]                        |
| Texture · baseColor: [...]                        |
| Texture · normal:    [...]                        |
| ...                                               |
| [Clear Override for Selection]                    |
+---------------------------------------------------+

+-- Last Run Details -------------------------------+
| Stem · shader=<name> · N texture slot(s)          |
+---------------------------------------------------+
```

### Cascade behavior

Changing a shader mapping → re-render the inventory (the unmapped `⚠`
marker disappears). Materials that have an override for `materialtype`
ignore the shader mapping change.

Changing the default materialtype → updates the fallback only;
materials with a shader mapping OR an override are unaffected.

Clearing an override → drops the entry from `overrides`; the material
returns to its effective-via-mapping or via-default state.

## Implementation Plan

### I.1 — Schema + outputs additions
**Done when:** `material_processor` stage added with defaults +
shader_mappings + overrides. `material_metadata` added to
`asset_processor` outputs.

### I.2 — IntegratedAssetProcessor records shader info
**Done when:** `_process_material` populates
`self._material_metadata[guid] = {asset_hint, shader_name,
source_path, source_stem, textures_bound}`. `to_outputs` includes
the new dict.

### I.3 — `_PathField` widget
**Done when:** Class exists with committed/cleared signals. Browse
opens file dialog with configurable caption + filter.

### I.4 — MaterialTab rewrite
**Done when:**
- Defaults section with editable fallback materialtype.
- Shader Mappings section rendering one row per detected/mapped
  shader. Unmapped entries get ⚠ + yellow color.
- Inventory list with shader-name column, ★ and ⚠ markers.
- Selection Overrides section: target type + six texture slot
  fields, multi-edit with common-vs-mixed semantics.
- Per-slot `Clear` button + a bottom-of-section `Clear Override for
  Selection`.
- Last Run Details mirroring the other tabs.
- Disabled `Process` button with a "coming" tooltip.

### I.5 — Tab rename
**Done when:** MainWindow registers tabs as `Dashboard / Scenes /
Prefabs / Meshes / Materials / Terrain / Config`.

### I.6 — Verification

| ID | Proof |
|---|---|
| T-1 | Schema present: defaults, shader_mappings, overrides |
| T-2 | Tab labels match the simplified set |
| T-3 | Inventory renders shader name + ★/⚠ markers correctly |
| T-4 | Two selected with same effective materialtype → field shows value |
| T-5 | Edit target materialtype on 2 selected → overrides[guid].materialtype populated for both |
| T-6 | ★ markers appear on those two |
| T-7 | Select all 3 (mixed effective materialtype) → field shows `…` placeholder |
| T-8 | Texture override on baseColor across selection → overrides[guid].textures.baseColor populated |
| T-9 | Clear Override on one selected material → entry removed; others unchanged |
| T-10 | Add mapping for previously-unmapped shader → ⚠ marker drops from inventory |

## Out of scope (deliberately)

- Raw-file editing of source `.mat` content.
- Scalar property overrides (factors / colors). Same shape will fit:
  add another section under Selection Overrides with `_FloatField`s
  per O3DE property.
- Worker integration — the override storage is live; `.material`
  re-emission consuming overrides arrives in F-6.2.
- Auto-detection of a shader-mapping suggestion ("looks like a URP
  variant, want to map it to StandardPBR?"). Future polish.
- Texture file format conversion at rebind time. The override stores
  the user's chosen file as-is.
- Cross-project shader-mapping library. Per-project only for now.
