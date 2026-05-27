# Material Component By-Label Override Resolution — Working Doc

Paired with `mem:material_conversion/material_component_label_resolution_plan`.

## Update Log (newest at top)

### 2026-05-26 — Label source corrected: FBX-internal material names, not .mat stems

**Why this matters:** Confirmed via O3DE source — `ModelMaterialSlot::m_displayName`
is set from `MaterialAsset::m_name`, which SceneAPI extracts from the FBX
itself in `ModelAssetBuilderComponent.cpp:2361`. The runtime label resolver
therefore sees the FBX-internal material strings, which are completely
independent of Unity's `.mat` (and our `.azmaterial`) file names. My earlier
emission used `Path(assetHint).stem` as the label key — that string only
happens to match the FBX label if the Unity material name was authored to
mirror the FBX name, which is not a guaranteed convention.

**Structural change:** The converter now pairs *FBX-material-slot-name* ↔
*Unity-material-name* (ordinally, per Unity's MeshRenderer.materials order),
where previously it paired *Unity-mesh-slot-index* ↔ *Unity-material-name*.

**Files touched:**

- `integrated_asset_processor.py`
  - New `read_fbx_material_names(fbx_path) -> List[str]`. Scans the binary
    FBX for `\x00\x01Material` markers (mirrors the existing
    `read_fbx_mesh_node_names`). Uses a 1 MB read window because the
    Materials block in the Objects section is typically deeper than Models.
  - `_process_prefab` now calls `read_fbx_material_names` once per FBX,
    builds `fbx_material_labels: {entity_file_id: [fbx_name_0, ...]}`,
    truncates to `min(len(go.material_guids), len(fbx_mat_names))`, and
    threads it through `_create_o3de_prefab` → `_create_entity_recursive`
    → `ProcessingContext` → `MaterialComponentProcessor`.
  - **Multi-mesh FBX caveat**: uses the FBX-wide material list, not a
    per-mesh-node Connections-resolved list. Single-mesh FBX (the common
    Unity case) is correct; multi-mesh FBX with different materials per
    mesh node would need Connections parsing.

- `components/base.py` — `ProcessingContext` gained
  `fbx_material_labels: Dict[str, List[str]]`.

- `components/material.py` — `MaterialComponentProcessor.emit()` now keys
  `materialsByLabel` by `ctx.fbx_material_labels[go.file_id][idx]` instead
  of `Path(mat_path).stem`. When labels are unavailable (no FBX access,
  empty parse, or unknown entity), the by-label entry is omitted but the
  default `{}` slot is still emitted so the entity renders.

- `unity_scene_converter_gui.py` — passes `fbx_material_labels={}` into
  the scene-side `ProcessingContext` (scene converter has no FBX access).

- Sidecar (`.entitymap.json`) gained `material_slot_labels:
  {file_id: [fbx_name_0, ...]}`. Tier 3 override patches in both stages
  now look up the slot's label here rather than re-deriving from the
  assetHint stem. Sidecars from earlier converter runs lack this field,
  so overrides against legacy prefabs log a warning and skip the patch
  with a "re-convert the source prefab to fix" hint.

### 2026-05-26 — assetHint `assets/` prefix fix

All converter-emitted assetHints (and nested-prefab `Source` paths) were
missing the leading `assets/` segment that the O3DE asset catalog stores
them under. Symptom: catalog entry like
`assets/alien fantasy forest/meshes/dead _trunk_01-...azmodel` does not
match emitted hint `alien fantasy forest/meshes/Dead _trunk_01-...`,
so the hint never resolves at runtime.

Fix in `integrated_asset_processor.py`:
- New field `self.asset_hint_root = f"assets/{self.project_name}"` (next
  to the existing `self.project_name` derivation).
- Three construction sites switched from `{self.project_name}/...` to
  `{self.asset_hint_root}/...`:
    * mesh hint (`_process_prefab`, ~L934)
    * material hint (`_process_material`, ~L1380)
    * nested-prefab Source path (`_create_nested_prefab_instance`, ~L1784)
- `project_name` itself unchanged (still the bare folder basename) since
  it is also written to `asset_index.json` metadata.

Stage 2 (`unity_scene_converter_gui.py`) reads hints out of the asset
index Stage 1 writes, so it picks up the fix transitively.

**Possible parallel issue (NOT fixed, flagged for user):**
- `unity_scene_converter_gui._convert_to_assets_path` builds prefab
  `Source` paths as `{search_dir.name}/{rel_to_search}` with no
  `assets/` prefix. If `search_dir` is something other than the project
  Assets folder, the resulting Source won't match the catalog either.
- **Case mismatch** — `project_name` is lowercased but Stage 1's
  `group_name = f"{fbx_stem}-{go.name}"` preserves Unity's casing in the
  mesh subpath, and material file names also preserve case per the
  pipeline convention. The catalog normalizes paths to lowercase, so if
  O3DE's hint resolution is case-sensitive, the bind will still miss on
  any source whose file/group name has uppercase letters.

### 2026-05-25 — I.3 (converter emission) — first attempt, since superseded

Initial emission scheme keyed `materialsByLabel` by `Path(assetHint).stem`
(the Unity material name). Superseded by the FBX-name correction above —
see top entry. The default-`{}`-slot + drop-synthetic-`{N}`-keys parts
are unchanged from that attempt.

### 2026-05-25 — Implementation (I.1 + I.2) landed in o3de_sourcedev

**Files modified:**
- `Gems/AtomLyIntegration/CommonFeatures/Code/Include/AtomLyIntegration/CommonFeatures/Material/MaterialComponentConfig.h`
  - Added `m_materialsByLabel` field.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentConfig.cpp`
  - Version bumped 3 -> 4. Reflected new field as `"materialsByLabel"` in both SerializeContext and BehaviorContext.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentController.h`
  - Added private `ResolveMaterialsByLabel()` declaration.
- `Gems/AtomLyIntegration/CommonFeatures/Code/Source/Material/MaterialComponentController.cpp`
  - Inserted `ResolveMaterialsByLabel()` call inside `LoadMaterials()`, immediately after `GetDefaultMaterialMap` populates `m_defaultMaterialMap`.
  - Added method body that queries `MaterialConsumerRequestBus::GetMaterialLabels`, builds a `label -> general slot id` table for `IsSlotIdOnly()` entries, and projects unresolved by-label entries into `m_materials` (skipping any slot already explicitly populated).

**Behavior:**
- On first `Activate()`, labels return only the default-slot entry (model not loaded yet). `ResolveMaterialsByLabel()` is a no-op.
- When the mesh fires `OnMaterialAssignmentSlotsChanged`, `LoadMaterials()` runs again. Now labels are populated, by-label entries bind to real stable IDs, and the entries flow through the normal load path.
- Non-destructive: `m_materialsByLabel` is never drained, so a later mesh swap with the same slot labels rebinds.

**No version converter needed for 3 -> 4** — the new field defaults to empty for any pre-existing prefab, and the absence of the field in old serialized data is handled by AzCore reflection.

### Pending

- **Testing** — not yet run. End-to-end build + load required:
    * Convert a multi-material prefab through the new converter; verify
      the converter log prints "FBX materials found: [...]" with the
      expected list, and the resulting `.prefab` has a `materialsByLabel`
      keyed by those exact strings.
    * Open in editor with the patched AtomLyIntegration gem; verify the
      inspector shows the right materials on each slot after first mesh
      load.
    * Author a scene-level material override on the regenerated prefab;
      run Stage 2; verify the patch path uses the FBX label and resolves.
  See plan T-matrix.

## Decisions in flight
None.

## Known unknowns
- **Multi-mesh FBX**: the per-FBX material list works for single-mesh
  FBX. Multi-mesh FBX where different mesh nodes use different subsets
  of materials needs Connections-section parsing to know which materials
  go with which mesh. Currently the converter assumes the FBX-wide list
  applies to every entity sharing the FBX.
- Whether O3DE's assetHint resolution is case-sensitive. If yes, the
  converter's mixed-case mesh group names and preserved-case material
  file names won't match the lowercased catalog entries.
- JSON serialization of `AZStd::unordered_map<AZStd::string, MaterialAssignment>` is expected to use the string as the JSON object key directly (vs. the struct-string serialization used for `MaterialAssignmentId` keys). No custom serializer added — relying on auto reflection. If the field round-trips as something else (e.g. an `{Key, Value}` array form), the converter's emission shape will need to follow.
- Whether the AzCore JSON Patch `replace` op tolerates a missing intermediate path (`materialsByLabel/<label>`). The Tier 3 override emission assumes the base prefab always contains the label.

## Next actions
1. User: regenerate a multi-material prefab, confirm "FBX materials found" log shows the expected list, load in editor, confirm inspector shows correct materials on each slot.
2. User: author a scene-level material override on the regenerated prefab, run Stage 2, confirm the patch resolves.
3. README + `project/converter_working_status.md` row "Multi-material slots" needs the format note updated from `{0}, {1}, ...` to `{} default + materialsByLabel (keyed by FBX-internal material names)`.
4. Decide on Stage 2 `_convert_to_assets_path` prefix fix + case-sensitivity question.
5. Multi-mesh FBX Connections parsing if/when a test asset surfaces the limitation.
