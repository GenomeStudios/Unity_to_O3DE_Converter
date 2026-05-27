---
name: material-preprocessing-working-doc
description: Living status log for F-6 — material shader mappings + per-material overrides editor.
metadata:
  type: project
---

# F-6 Material Preprocessing — Working Documentation

Newest entries on top. Linked plan: [[material-preprocessing-plan]].

## 2026-05-27 — Shader mapping popout + section warn-state ✓

### What landed (responding to the user's "MK4 mappings aren't clearing warnings" report)

**Root-cause fix — `shader_name` resolution**
- `IntegratedAssetProcessor._extract_material_data` was reading
  `material_data.get('m_Shader', {}).get('m_Name', '')`. Unity stores
  `m_Shader` as a `{fileID, guid, type}` reference — there is no
  `m_Name` on it. shader_name was always empty, so EVERY material in
  the inventory rendered as "(unknown)" and got the ⚠ marker
  regardless of mappings.
- Fixed by recording `shader_guid` + `shader_fileid` on extraction,
  then resolving via new `_resolve_shader_name(guid, fileid)` that:
  - Looks up `_UNITY_BUILTIN_SHADERS = {4: "Standard", 46: "Standard
    (Specular setup)"}` when guid is empty (built-ins use fileIDs).
  - For guid-bearing references, reads the `.shader` file via
    `_find_asset_path` and pulls the `Shader "..."` declaration with
    a `_SHADER_NAME_RE` regex. Cached in `_shader_name_cache` keyed
    by guid.
- Verified regex extracts:
  `MK4 Foliage.shader → "MK4/Foliage Fantasy"`,
  `MK4 Foliage no wind.shader → "MK4/Foliage Fantasy no wind"`,
  `MK4 Foliage simple.shader → "MK4/Foliage Fantasy no trans"`,
  `Rock_cover.shader → "MK4/Rock_cover"`.

**Shader Mappings UI — section refactor (replaces inline rows table)**
- Old behavior: rendered union of (mapped keys ∪ detected shaders) as
  rows directly in the section. Cluttered when many shaders are
  detected; mixed mapped-but-not-detected entries into the view.
- New section composition: short info paragraph + counts summary
  (`N detected · M mapped · X unmapped`) + a colored status line
  (`✓ all mapped` green, or `⚠ Unmapped: a, b, c, +N more` yellow)
  + an `Edit Mappings…` button that opens the popout.
- `_set_section_warn(True)` adds a yellow border + yellow title color
  to the section's QGroupBox so the unmapped state is visible from
  the tab without scrolling.
- The section now shows only summary signal — the table moved into
  the dialog.

**`ShaderMappingsDialog(QDialog)` — popout editor**
- Lives in `main_app.py` above `MaterialTab`. Non-modal, 640×480.
- Rows populated from DETECTED shaders only (one entry per unique
  `shader_name` across `outputs.asset_processor.material_metadata`).
  Pre-seeded mappings that aren't detected don't render — keeps the
  list focused on what the project actually contains.
- Unmapped shaders sort to the top so the work-to-do is immediately
  visible. Each row: `[⚠ or "  "] shader_name` label + `_PathField`
  for the .materialtype path.
- Live-save: `_on_mapping_changed(shader, value)` writes the stage
  via `project_manager.update_stage`, calls `_populate(proj)` to
  reorder rows (mapped flips out of the unmapped group), and emits
  `mappings_changed`.
- Owning `MaterialTab` listens for `mappings_changed` via
  `_on_dialog_mappings_changed`, which refreshes both
  `_refresh_shader_mappings` (summary + section warn) and
  `_refresh_inventory` (clears ⚠ markers on rows whose shader is now
  mapped).
- Dialog instance is lazy-constructed on first open and reused on
  subsequent opens; `_open_mappings_dialog` always re-populates from
  the current project before showing so a prefab run that happened
  while the dialog was hidden gets picked up.

### Sanity gates passed

- `py -m py_compile main_app.py` → OK.
- Headless verification script seeded a project with two detected
  shaders (one pre-seeded mapping = `MK4/Foliage Fantasy`, one
  novel = `MK4/Unmapped Custom`) and asserted:
  - Summary reads `2 detected · 1 mapped · 1 unmapped` ✓
  - Section warn style applied (yellow border on QGroupBox) ✓
  - Inventory row for the unmapped material carries ⚠, row for the
    mapped material does not ✓
  - Popout opens, dialog summary mirrors the tab summary ✓
  - After applying a mapping through the dialog: tab summary flips
    to `0 unmapped`, section warn style clears, inventory ⚠ marker
    on the previously-unmapped row clears ✓

### Behaviour notes

- The pre-seeded `shader_mappings` (Standard, URP/Lit, URP/Simple
  Lit, MK4/Foliage Fantasy family, MK4/Rock_cover) still live in
  `project_manager._default_stages`. Existing projects pick them up
  via the `_deep_merge` schema migration. The dialog renders them
  only when they appear in the detected set.
- The orphaned `MaterialTab._on_shader_mapping_changed/_cleared`
  methods (used by the old inline rows) were removed. The dialog
  owns the only edit path now.
- Section warn-state is driven by an inline stylesheet on
  `_shader_box` (the QGroupBox). Other group boxes are unaffected
  because the stylesheet is scoped to that widget, not the app.

### Known follow-ups (unchanged from prior log)

- Worker consumption of material overrides (re-emit `.material`
  files with overrides applied).
- Scalar property override fields (metallic.factor, roughness.factor,
  emissive color) using `_FloatField`.
- Cross-project shader-mapping library (`global/shader_mappings.json`).

## 2026-05-27 — F-6 editor shipped ✓

### What landed

**Tab rename (I.5)**
- `MainWindow.__init__` registers tabs as
  `Dashboard / Scenes / Prefabs / Meshes / Materials / Terrain / Config`.
  CLI `--tab=` aliases unchanged.

**Schema additions (I.1)**
- `stages.material_processor`:
  - `defaults.target_materialtype` — fallback when no shader-specific
    mapping exists; defaults to `"StandardPBR.materialtype"`.
  - `shader_mappings` — Unity shader name → O3DE materialtype path.
    Pre-seeded with `Standard`, URP/Lit, URP/Simple Lit → StandardPBR.
  - `overrides` — keyed by material GUID. Each entry can carry
    `materialtype` and/or `textures: {slot: path}`.
- `outputs.asset_processor.material_metadata` — populated by Stage 1
  for each material:
  `{asset_hint, shader_name, source_path, source_stem, textures_bound}`.
- The legacy `outputs.asset_processor.materials` dict
  (`{guid: asset_hint}`) is preserved verbatim so Stage 2's
  PrefabDatabase consumer keeps working without changes.

**Shader metadata extraction (I.2)**
- IntegratedAssetProcessor gains `self._material_metadata: Dict[str,
  Dict]` initialized empty.
- `_process_material` writes one entry per processed material with
  shader name, source path, stem, and the sorted list of bound
  texture slots.
- `to_outputs()` now includes `material_metadata` alongside
  `materials`, `meshes`, etc.

**`_PathField` widget (I.3)**
- `QWidget` containing `[QLineEdit] [Browse…] [Clear]`.
- `committed(str)` fires when the user edits or browse-picks a path.
- `cleared()` fires when the user hits Clear — distinct from "set to
  empty string" so callers can distinguish "remove the override
  entirely" from "set the override to empty".
- `set_common(value)` / `set_common(None)` / `set_common("")` /
  `set_disabled_blank()` API matches `_FloatField` so the multi-edit
  logic is uniform.

**MaterialTab rewrite (I.4)**
- Four sections in the scroll-wrap content (plus the disabled Process
  button at the bottom):
  1. **Default Material Settings** — one `_PathField` for the fallback
     target materialtype.
  2. **Shader Mappings** — dynamic list. One row per Unity shader that
     is *either* in the project's mappings *or* detected in the
     material inventory. Unmapped detected shaders get the ⚠ prefix
     and yellow color. Each row owns a `_PathField` for the
     target materialtype. [Superseded 2026-05-27 by popout dialog;
     see top entry.]
  3. **Material Inventory** — `ExtendedSelection` QListWidget. Each
     row shows `★` (override applied) and/or `⚠` (unmapped shader)
     markers, followed by stem + shader name. Bold cyan for
     overridden, dark yellow for unmapped. Tooltip shows guid,
     shader, bound slots, and marker reasons.
  4. **Selection Overrides** — visible always but disabled when the
     selection is empty. Target materialtype row + six texture-slot
     rows (`baseColor`, `normal`, `metallic`, `roughness`,
     `occlusion`, `emissive`). Each field commits to every selected
     material; Clear removes that specific override.
- A `Clear Override for Selection` button at the bottom drops the
  whole override entry for every selected material.
- `Last Run Details` shows per-material `stem · shader=name · N
  texture slot(s)` for up to 20 entries, with `… and N more` overflow.
- Disabled `Process (re-emit materials — coming)` action button with
  tooltip pointing at the follow-up F-6 iteration.

### Sanity gates passed

- `py project_manager.py` → smoke OK.
- `py -c "import main_app"` → OK.
- F-6 E2E against testbed with seeded material_metadata for 3
  materials (Standard, URP/Lit, Custom/Foliage):
  - Tab labels match `Dashboard / Scenes / Prefabs / Meshes /
    Materials / Terrain / Config` ✓
  - material_processor stage shape verified ✓
  - Shader Mappings section renders 4 rows (3 seeded + 1 detected
    unmapped) ✓
  - Inventory renders 3 entries with shader column + ⚠ marker on
    Foliage ✓
  - 2 selected (Door + Wall, both Standard / URP/Lit → StandardPBR):
    common materialtype shown, mixed=False ✓
  - Edit target → overrides written for both, ★ markers appear ✓
  - Select all 3 (Foliage's effective type still falls back to
    default) → materialtype field flips to `…` placeholder ✓
  - Texture rebind for baseColor across all 3 → stored under each
    override's `textures.baseColor` ✓
  - Clear Override on Foliage alone → entry removed; Door/Wall keep
    their overrides ✓
  - Mapping `Custom/Foliage` → drops `⚠` marker from inventory ✓
  - Item with both override and unmapped shader renders both markers
    (`★ ⚠ Foliage`) ✓

### Behaviour notes

- The `_PathField`'s `cleared` signal is wired separately from
  committed so a user clearing baseColor doesn't accidentally set it
  to `""` — it actually removes the slot key from the override
  entry. If the override entry becomes empty after the clear, the
  entire entry is dropped from `overrides`.
- The effective-materialtype lookup uses a three-step chain:
  override → mapping → default. The "common value" check operates on
  the effective value, so two materials inherit the same default
  appear as common (correctly).
- Mapping changes cascade: editing or clearing a shader mapping
  re-renders the inventory because rows may flip between mapped and
  unmapped. Re-rendering the override editor is also needed since the
  effective materialtype may change.
- Inventory text uses a fixed-width column layout
  (`f"{stem:<32}  {shader}"`) for visual alignment. Long names
  overflow into the shader column but tooltips show full info.

### Known follow-ups

- **Worker integration.** Override storage is wired but the
  IntegratedAssetProcessor still emits `.material` files using its
  legacy logic. The worker consuming `overrides.<guid>.materialtype`
  and `overrides.<guid>.textures` is the next iteration of F-6.
- **Scalar property overrides.** `metallic.factor`, `roughness.factor`,
  emissive color, etc. Same shape would slot in below the texture
  fields using `_FloatField`. Out of scope this pass.
- **Cross-project shader library.** Mappings currently live per-
  project. A `global/shader_mappings.json` library would let common
  shaders carry over between projects. Out of scope; would slot into
  Config tab.
- **Raw `.mat` editing.** Deferred. Could be a context-menu action on
  inventory rows that opens the source file in a text editor.

## Pending / not yet shipped

- Worker consumption of material overrides.
- Scalar property override fields (factors / colors).
- "Used by N prefabs" reverse-lookup on inventory rows.
- Global shader-mapping library + project-overrides-library hybrid.
