---
name: output-propagation-plan
description: Design + locked decisions for F-9 — the worker plumbing that consumes shader profiles + mesh settings, plus per-asset state index and patch detection for surgical re-emission.
metadata:
  type: project
---

# F-9 Output Propagation + Patching — Plan

Roadmap entry: `project_system/feature_roadmap` § F-9. The F-7 (Terrain
heightmap expansion) feature is deliberately delayed until after F-9
ships. F-8 (orchestration + preflight) is the sibling feature in
`orchestration/orchestration_plan`. F-10 (shader profile editor +
custom-profile authoring) is the spinoff in
`profile_editor/profile_editor_plan` — F-9 ships the profile DATA
model + the catch-all default profile; F-10 ships the UI to author
new profiles.

Linked: [[material-preprocessing-plan]] (F-6 — the profile model
supersedes the materialtype-path mapping shipped there),
[[mesh-preprocessing-plan]] (mesh override storage),
[[orchestration-plan]] (Run All + preflight that gates this),
[[profile-editor-plan]] (F-10 — defers profile authoring UI).

## Goal

Close the loop between the editors and the output. Today the F-5/F-6
editors store mesh defaults / mesh overrides / shader mappings /
material defaults / material overrides into the project file, but
`IntegratedAssetProcessor` ignores all of it — `_process_material`
hard-codes the materialtype AND the property remap, and
`write_fbx_assetinfo` hard-codes the coordinate rule. F-9 makes the
worker actually consume those settings AND records a per-asset state
index so a follow-up override change can re-emit only the affected
outputs.

## Conceptual shift — shader profiles (not materialtype paths)

The F-6 model treated `shader_mappings` as `Unity shader → O3DE
materialtype path`. That model is insufficient: actual shader
conversion needs to know the **property remap table** (Unity property
name → O3DE slot, plus per-slot transforms like alpha-invert), not
just the target materialtype. Today the remap lives hard-coded inside
`IntegratedAssetProcessor._extract_material_data` (the `TEXTURE_MAP`,
`PROPERTY_MAP`, `IGNORE_UNMAPPED` dicts) — that IS effectively a
single built-in "Anything to PBR" profile.

F-9 makes the profile concept explicit in the schema and routes
emission through it. Per-profile UI editing (the texture-map / property-map
authoring surface) is **out of scope for F-9** and lands in F-10. F-9
ships exactly ONE pre-seeded profile — `Default — Anything to PBR` —
that captures the current hard-coded logic verbatim, so existing
projects keep behaving identically while gaining a clean seam for
divergent profiles later.

## Resolved Decisions (Q&A)

**Q1 — Where does the state index live?**
A: **Inside the project file**, at `project.outputs.state_index`.
Mirrors the state-management refactor that removed `.ImporterData/`.
Schema:
```json
"outputs": {
  "state_index": {
    "materials": {
      "<material_guid>": {
        "source_path":   "/abs/Unity/.../Foo.mat",
        "source_mtime":  1234567890.1,
        "output_files":  ["/abs/output/Materials/Foo.material"],
        "input_hash":    "sha256:abcdef...",
        "last_emitted":  "2026-05-27T12:34:56Z"
      }
    },
    "meshes":   { "<mesh_guid>":   { ... } },
    "prefabs":  { "<prefab_guid>": { ... } },
    "textures": { "<texture_guid>": { ... } }
  }
}
```

**Q2 — Worker propagation split between F-8 and F-9?**
A: **Folded into F-9**. F-9 owns BOTH the state index AND the
profile-aware emission rewrite. F-8 stays pure orchestration +
preflight. Profile authoring spins off to F-10.

**Q3 — Dirty semantics?**
A: **Conservative — hash everything**. Input hash = source-file mtime
+ override-snapshot + relevant defaults + **resolved profile body**.
Editing any default, mapping, OR profile entry marks every asset
that consumes it dirty.

Hash composition per asset type:
- **Material**: `sha256(source_path + source_mtime + resolved_profile
  + overrides[guid])`. The profile body is included (not the profile
  name) so editing the profile dirties all its consumers.
- **Mesh (FBX)**: `sha256(source_path + source_mtime + mesh_defaults
  + overrides[guid])`.
- **Prefab**: `sha256(source_path + source_mtime + every dependent
  material's input_hash + every dependent mesh's input_hash)`.
- **Texture**: `sha256(source_path + source_mtime)`. No user-editable
  settings yet.

**Q4 — Settings access pattern?**
A: `IntegratedAssetProcessor.__init__` gains three new kwargs:
`material_settings: dict | None`, `mesh_settings: dict | None`,
`scope_root: Path | None`. `material_settings` carries
`{defaults, shader_profiles, shader_mappings, overrides}`. Worker
stores them and reads from them at emission time. No project
reference (keeps the worker decoupled from project_manager).

**Q5 — Material emission: what changes?**
A: `_process_material(material_guid)`:
1. **Resolve profile**: chain `overrides[guid].profile` →
   `shader_mappings[shader_name]` → `defaults.profile`.
2. **Resolve materialtype**: chain
   `overrides[guid].materialtype` (raw escape hatch) →
   `profile.target_materialtype`. Run through
   `resolve_materialtype_path()`.
3. **Run profile-driven extraction**: pass the profile's
   `texture_map`, `property_map`, `ignore_unmapped` into the
   extraction step instead of the hard-coded module dicts. The
   extraction code becomes profile-data-driven.
4. **Apply per-slot texture overrides**: `overrides[guid].textures[slot]`
   wins per-slot post-extraction.
5. **Record state_index** after write.

**Q6 — Materialtype path resolution?**
A: `resolve_materialtype_path()` shipped in F-9.I.1. Profile
`target_materialtype` strings flow through it. UI displays via the
same resolver so "common value" matches what the worker writes.

**Q7 — Mesh emission: what changes?**
A: `write_fbx_assetinfo(...)` and `_process_mesh(...)` consume the
mesh settings. Two effects:
1. **Per-mesh CoordinateSystemRule**. When `defaults.zero_position`
   OR `overrides[guid].zero_position` is true, position contribution
   to the rule is zeroed. When `default_position` / `default_rotation`
   are non-zero, they bake into the CoordinateSystemRule's
   `translation` / `rotation` fields the same way the Y-up correction
   already does.
2. **State recording**. After write, record `state_index.meshes[guid]`.

**Q8 — Patch worker?**
A: New `IntegratedAssetProcessor.patch(...)` method that:
1. Reads `state_index` from outputs.
2. For every entry, recomputes the current input hash (including the
   resolved profile body).
3. Compares against stored hash. Mismatches are dirty.
4. Walks the dirty set in dependency order (materials → meshes →
   prefabs) and re-emits each.
5. Updates state_index.

UI access: `MaterialTab` / `MeshTab` / `PrefabsTab` gain a small
"Patch" button alongside their inventory section. Project-wide
"Patch All" lives in Mission Command (added in F-8).

**Q9 — What's deferred to F-10 (profile editor feature)?**
A: ALL profile authoring UX. F-9 ships exactly one profile
(`Default — Anything to PBR`) defined in code. The user cannot edit
its texture_map / property_map / ignore_unmapped from the GUI in F-9.
F-10 owns:
- Profile editor dialog (texture-map / property-map / transform rows).
- Profile creation / duplication / deletion.
- Profile preview (which Unity properties get routed where).
- Cross-project profile library (saving a profile globally).

**Q10 — What's deferred entirely?**
A:
- **Texture file conversion at rebind time.** The override stores the
  user's chosen file; F-9 does not copy it.
- **Orphan detection.** Deferred follow-up.
- **Hash migration.** Existing projects have no state_index; first
  Patch call falls back to full re-emit and records state going
  forward.
- **Per-scene patchability.** Scenes re-emit in full.

**Q11 — UI visibility of dirty state?**
A: Inventory rows gain a `↻` marker (cyan) when the asset is dirty.
The summary line at the bottom adds a "N dirty" counter when > 0.

**Q12 — How does the shader_mappings UI shift in F-9?**
A: The popout dialog's per-shader rows switch from `_PathField`
(materialtype path) to `QComboBox` populated with profile names from
`shader_profiles`. The "Default Material Settings" section shifts
from a `_PathField` for materialtype to a `QComboBox` for profile.
The override section's "Target materialtype" `_PathField` stays as
the raw escape hatch (writes through to override.materialtype
directly, bypassing the profile chain).

## Design

### Schema additions

`material_processor` stage gains `shader_profiles`. `shader_mappings`
values shift from materialtype path → profile name.
`defaults.target_materialtype` becomes `defaults.profile`.

```json
"material_processor": {
  "defaults": {
    "profile": "Default — Anything to PBR"
  },
  "shader_profiles": {
    "Default — Anything to PBR": {
      "description": "Catch-all Unity→O3DE PBR remap. Matches the legacy hard-coded TEXTURE_MAP / PROPERTY_MAP behaviour.",
      "target_materialtype": "StandardPBR.materialtype",
      "texture_map": {
        "_MainTex":          { "slot": "baseColor",          "transform": "passthrough" },
        ...
      },
      "property_map": {
        "_Color":            { "target": "baseColor.color",  "transform": "passthrough" },
        ...
      },
      "ignore_unmapped": ["_Detail", "_AODetail", ...],
      "special_rules": {
        "metallic_gloss_smoothness_to_roughness": true
      }
    }
  },
  "shader_mappings": {
    "Standard": "Default — Anything to PBR",
    ...
  },
  "overrides": {
    "<material_guid>": {
      "profile":      "...",   # OPTIONAL — profile-name override
      "materialtype": "...",   # OPTIONAL — raw materialtype escape hatch
      "textures":     { ... }  # OPTIONAL — per-slot texture rebinds
    }
  }
}
```

`outputs.state_index` is shared across F-9 (see Q1).

### Profile data structure

```python
PROFILE_SCHEMA = {
    "description":          str,
    "target_materialtype":  str,                         # → resolve_materialtype_path
    "texture_map":          Dict[unity_prop, {slot, transform}],
    "property_map":         Dict[unity_prop, {target, transform}],
    "ignore_unmapped":      List[str],
    "special_rules":        Dict[str, bool],             # named flags
}

TRANSFORM_NAMES = {
    "passthrough",        # write value as-is
    "invert",             # scalar 1.0 - x
    "invert_alpha",       # texture: extract inverted alpha (smoothness → roughness)
    "channel_r",          # texture: extract R channel only
    "channel_g", "channel_b", "channel_a",
}
```

Transforms beyond `passthrough` and `invert` are documented but only
the ones used by the default profile have worker implementations in
F-9.

### Built-in default profile

Lives at module scope in `project_manager.py` (or a sibling
`shader_profiles.py` if it grows). The serialized form is what gets
written into `_default_stages()` for new projects, so the user sees
it in their `.u2oproj.json` and can later edit it via F-10.

### Emission seams (touch points)

| File / function | Change |
|---|---|
| `project_manager.py` | Add profile schema + default profile + resolver helpers |
| `integrated_asset_processor.py::_extract_material_data` | Accept profile data; replace module-level TEXTURE_MAP/PROPERTY_MAP/IGNORE_UNMAPPED reads with parameters |
| `integrated_asset_processor.py::_process_material` | Resolve profile chain; resolve materialtype via shared helper; thread profile into extractor |
| `integrated_asset_processor.py::write_fbx_assetinfo` | Accept mesh_settings + guid; apply override translation/rotation/zero |
| `integrated_asset_processor.py::_process_mesh` | Record state_index entry |
| `integrated_asset_processor.py::_process_texture` | Record state_index entry |
| `integrated_asset_processor.py::process_prefab` | Record state_index entry with dependency hash |
| `main_app.py::PrefabProcessorTab._start_processing` | Pass `material_settings`/`mesh_settings`/`scope_root`/`state_index` into constructor |
| `main_app.py::MaterialTab` | Replace default-materialtype `_PathField` with profile `QComboBox`; same for ShaderMappingsDialog rows |
| `main_app.py::MaterialTab` / `MeshTab` | Render ↻ on dirty rows; Patch buttons |
| `main_app.py` Mission Command | Patch All (F-8) |

## Implementation Plan

### I.1 — Schema (state_index + resolver) ✓ DONE

Shipped 2026-05-27. `outputs.state_index` buckets + `resolve_materialtype_path()`
verified against 12 test cases.

### I.1b — Shader profile schema + default profile + UI switch to profile picker

**Done when:**
- `material_processor.shader_profiles` dict added to `_default_stages`
  with one entry: `Default — Anything to PBR` containing the captured
  TEXTURE_MAP / PROPERTY_MAP / IGNORE_UNMAPPED / metallic-gloss flag.
- `shader_mappings` pre-seeded values switched from materialtype path
  → profile name (`"Default — Anything to PBR"`).
- `defaults.target_materialtype` renamed → `defaults.profile`.
- `Project.from_json` deep-merges the new shape without losing
  user-set values. Legacy `target_materialtype` carried over to
  `defaults.profile` as the catch-all profile name.
- MaterialTab's "Default Material Settings" section shows a profile
  QComboBox sourced from `shader_profiles.keys()`.
- ShaderMappingsDialog rows: per-shader `QComboBox` of profile names
  instead of `_PathField`. ⚠ marker behaviour unchanged.
- Material inventory `⚠` triggers when the resolved profile chain
  yields nothing (i.e. shader unmapped AND no default — practically
  never true since default is always set, but the code path stays
  for safety).
- The override section's "Target materialtype" `_PathField` stays as
  the raw escape hatch; documentation updated.

**Pause + verify with user.**

### I.2 — Material emission honours profile chain

**Done when:**
- `IntegratedAssetProcessor.__init__` accepts `material_settings`.
- `_extract_material_data` takes profile data as parameters (no longer
  reads module-level dicts).
- `_process_material` resolves the profile via the chain and threads
  it into extraction.
- `_process_material` honours `overrides[guid].materialtype` as the
  raw escape hatch and `overrides[guid].textures` for per-slot rebinds.
- Test: seed a custom profile pointing at `Custom.materialtype` with
  a remapped texture slot; verify the emitted `.material` reflects
  both.

**Pause + verify with user.**

### I.3 — Mesh emission honours defaults + overrides

**Done when:**
- `write_fbx_assetinfo` accepts mesh_settings + mesh_guid.
- CoordinateSystemRule absorbs override translation/rotation/zero on
  top of Y-up correction.
- Test: seed mesh override default_rotation=[0,90,0] and verify the
  `.assetinfo` reflects it.

**Pause + verify with user.**

### I.4 — State index recording

**Done when:**
- Each emission method records its asset entry. `to_outputs` includes
  the index.
- Test: emit a tiny project and verify state_index population.

### I.5 — Dirty detection + Patch worker

**Done when:**
- `patch()` method exists; recomputes hashes; re-emits only dirty
  entries in dependency order.
- Test: tweak a profile entry → patch re-emits only consuming materials.

**Pause + verify with user.**

### I.6 — UI dirty markers + per-tab Patch buttons

**Done when:**
- `_refresh_inventory` reads state_index + renders ↻.
- Patch buttons exist on Material / Mesh / Prefab tabs.

### I.7 — Verification matrix

| ID | Proof |
|---|---|
| T-1 | `outputs.state_index` initialised on new project ✓ (I.1) |
| T-2 | `_resolve_materialtype_path` resolves all 5 cases ✓ (I.1) |
| T-3 | `_default_stages` carries `shader_profiles."Default — Anything to PBR"` with full TEXTURE_MAP/PROPERTY_MAP/IGNORE_UNMAPPED captured |
| T-4 | `shader_mappings` pre-seeded values are profile names not paths |
| T-5 | `defaults.profile` (not `target_materialtype`) — migration green |
| T-6 | ShaderMappingsDialog renders QComboBox per detected shader |
| T-7 | Default Material Settings shows profile QComboBox |
| T-8 | `.material` files reflect profile.target_materialtype after run |
| T-9 | Per-material override `materialtype` wins as raw escape hatch |
| T-10 | Per-material override `textures.baseColor` wins over auto-extracted |
| T-11 | `.assetinfo` `CoordinateSystemRule.rotation` reflects mesh override |
| T-12 | After run, `state_index.materials[guid].input_hash` populated + stable |
| T-13 | Profile body change dirties consuming materials' input_hash |
| T-14 | `patch()` re-emits only affected `.material` files |
| T-15 | UI ↻ markers appear on dirty rows + clear after Patch |

## Out of scope (deliberately)

- F-7 Terrain heightmap expansion (delayed by user).
- F-10 profile editor + custom profile authoring UI.
- Texture file copy-on-rebind.
- Orphan detection / cleanup.
- Per-scene patchability.
- Scalar property overrides.
- Cross-project profile library.
