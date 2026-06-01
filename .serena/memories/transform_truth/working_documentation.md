---
name: transform-truth-working-doc
description: Living status for the transform-truth diagnostic work. Plan: [[transform-truth-plan]].
metadata:
  type: project
---

# Transform Truth — Working Documentation

Newest on top.

## 2026-05-28 (latest) — Single-mesh auto-center SHIPPED

`integrated_asset_processor.py`: `read_fbx_geometry_centroids` (Geometry
Vertices→centroid m, zlib-aware) + `compute_single_mesh_autocenter` → returns
`(centroid_X, node_Y, -node_Z)` for SINGLE-mesh FBX, None for multi-mesh.
Wired into `write_fbx_assetinfo`: when user authored NO position, a single-mesh
FBX auto-centres (override wins; gated by zero_position; self-limiting).
Verified: drawer A emits `translation=[-0.5982,-0.4516,-0.7577]` (≈ user fix,
5-8mm); desk frame + cabinet (multi-mesh) get none. Also shipped earlier today:
per-FBX UpAxis rotation (Y-up→+90°X), Cabinet material cutout-precedence,
diagnostics (FBX node/geometry readers, reconciliation report). Suite 28 green.
Caveat: single-mesh `_COL` FBX also auto-centres (Desk_metal_COL −8mm) — harmless
(one coord rule shifts azmodel+pxmesh together, stays aligned).

**Flags + toggles SHIPPED (user request):** per-mesh `auto_center` +
`auto_rotation` toggles (default True; schema in `_default_stages` +
`_resolve_mesh_settings`; `write_fbx_assetinfo` gates both on them; in
`_MESH_FIELDS` so they appear in the MeshTab defaults + override forms).
`_record_mesh_state` records `auto_flags={auto_center:[x,y,z]|None, y_up:bool}`
on the state-index entry; the MeshTab inventory shows a **⚙** marker + tooltip
for auto-flagged meshes. Tests: `test_assetinfo_writer` toggle-gating ×2.
Suite 28 green. Verified: drawer A flags auto_center value; Cabinet flags y_up.

**User test feedback (drawers/cabinet re-cook):** drawers A/B land in place ✓.
Drawer C NOT fixed (it's a sub-mesh of the desk FBX, not single-mesh).
Cabinet doors DO need compensation (user corrected earlier statement) — "offset
the same way as the drawers." So both drawer C + cabinet doors are the
multi-mesh PER-SUBMESH case.

**Per-submesh translation SHIPPED (cook-test pending).** `write_fbx_assetinfo`
restructured: rotation stays shared per-FBX; translation is now PER-NODE via a
`rule_for(node_path)` helper — each visual + physx group gets its own
CoordinateSystemRule. `compute_node_autocenters(fbx)` generalises the
single-mesh helper: `{node_name: (centroid_X, node_Y, -node_Z)}`, Model↔Geometry
paired by file order (empty if counts mismatch). User override applies to all
nodes (shared); auto-center is per-node; toggles still gate. Flag recording +
MeshTab ⚙ now use the per-node dict. Verified emission: desk drawer_C
T=[0.0105,0.808,-0.450] (was none), cabinet doors symmetric T=[±0.203,1.25,
-0.222]+90°rot, frames ~0. Tests: `compute_node_autocenters` multi-mesh,
toggle-gating updated. Suite 28 green.
**COOK RESULT (user):** per-node translation BROKE the Y-up cabinet doors —
offset doubled + wrong direction ("forward by a large amount; high and to the
outward sides"). The Z-up formula does NOT transfer to Y-up FBXs: the 90°
up-correction reorients the translation (door HEIGHT node_Y=1.25 landed in
O3DE's forward axis) and the sign adds instead of cancels.

**FIX SHIPPED — gate per-node translation to Z-up (up_axis != 1).** Y-up FBXs
get rotation-only (stand up, original offset — NOT doubled); Z-up keeps the
validated auto-center (drawers + drawer_C). `write_fbx_assetinfo`:
`auto_translate_ok = zero_pos and auto_center and up_axis != 1`. Verified:
desk drawer_C T=[0.0105,0.808,-0.450] kept; cabinet all T=None rot=True.
Suite 28 green.

**O3DE source confirms the mechanism:** with `useAdvancedData=true`,
`DetermineWorldTransform` = `CreateFromQuaternionAndTranslation(R, T)` →
world_vertex = R·local + T (T in WORLD frame, after R). So a Y-up FBX (R=90°X)
needs T in the post-rotation O3DE frame, not the FBX frame. Empirical Z-up
formula `(centroid_X, node_Y, -node_Z)` ≠ `-R·centroid`, so the Y-up form can't
be cleanly derived from source — needs a calibration point like the drawers had.

**Y-up formula SOLVED + SHIPPED.** User calibration: door_L needs
(-0.625,-0.222,-1.25); door_L node Lcl = (-0.625, 1.25, 0.222). ⇒ Y-up comp =
**(node_X, -node_Z, -node_Y)** (offset in the ORIGINAL pre-rotation axes, Y/Z
swapped+negated because the +90°X up-correction rotates the mesh — user:
"offset is based on original, not rotated axies"). `compute_node_autocenters`
now up-axis-aware: Z-up `(X, node_Y, -node_Z)`, Y-up `(X, -node_Z, -node_Y)`;
X = node_X for Y-up sub-nodes (|node_X|≤5m), else geometry centroid_X (Z-up, or
Y-up junk-X root). Y-up gate removed from the writer. Verified emission matches
the user's door values; Z-up drawers/drawer_C unchanged. Suite 28 green.

**Collider→render alignment SHIPPED.** User measured desk COL needs +0.875 Z;
the BBOX-CENTER delta (render frame bbox-Z +0.450 vs COL bbox-Z -0.418 = 0.868)
matched — centroid delta (0.597) would have been wrong (box vs detailed mesh).
New: `_read_fbx_geometry_stats` (centroid+min+max, shared),
`read_fbx_geometry_bbox_centers`, `compute_node_bbox_centers`,
`compute_collider_alignment(col_fbx,col_node,render_fbx,render_node)` =
`render_bbox + render_autocenter - col_bbox`. Producer: `collider_refs` now
carry the colliding entity's render mesh (guid/name/fileID); when a DEDICATED
_COL FBX (render_guid != collision_guid) collides for a render mesh, the physx
spec gets an explicit `translation` = the alignment; the writer applies it over
the collider's own auto-center. Same-FBX collision (collision IS a render
sub-mesh) → no shift. Verified: desk COL pxmesh translation
[-0.0002,0.0012,0.8695] (≈ user +0.875). Tests: bbox-center vs centroid. Suite
28 green.

**NEXT:** (1) desk COL alignment (measurement or render-coupled pass);
(2) cabinet door L/R mirror — cook-test whether doors land on correct sides.

**(superseded) earlier pending notes:**
1. **Per-submesh translation** (drawer C + cabinet doors). KEY INSIGHT: for a
   SUB-node the FBX node's LOCAL translation X is REAL (drawer_C Lcl X=0.014,
   door_R Lcl X=0.624) — only the ROOT node's X is the 24-50m scene junk. So
   the per-submesh formula can use the node Lcl transform directly
   (≈ `(node_X, node_Y, -node_Z)`), no geometry-centroid pairing needed for
   sub-nodes. Needs: per-ENTITY/per-group CoordinateSystemRule translation in
   `write_fbx_assetinfo` (today one shared rule per FBX) + root-vs-sub
   detection (root: |Lcl X|>~5m → use centroid_X like single-mesh; sub: use
   Lcl X). Cook-test (no ground truth yet).
2. Cabinet door L/R mirror (`bake-vs-world-sign-flip`) — revisit after #1.
3. I.3 expose suggested_offset/UpAxis/tags in report.

## 2026-05-28 — I.1 + I.2 shipped (diagnostic instruments)

**I.1 — `read_fbx_node_transforms`** (in `integrated_asset_processor.py`,
beside the other FBX readers). Recursive binary-FBX parser → `{node_name:
{translation(cm), rotation(deg), scaling}}`, handles v<7500/≥7500.
`tools/fbx_node_transforms.py` is now a thin CLI over it. Tests:
`tests/unit/test_fbx_node_transforms.py` (4, synthetic FBX builder — portable,
no pack dependency).

**I.2 — `tools/transform_report.py`** reconciliation report. Pure helpers
`classify_bake` / `compose_world_pos` / `UNITY_TO_M` (unit-tested,
`test_transform_report.py`, 7). Per render-mesh + collider it lays out the
FBX node bake (m), node rotation, `zero_position` state, Unity-composed
world pos, and pattern tags. Run:
`QT_QPA_PLATFORM=offscreen python tools/transform_report.py <src_root> <prefab>`.

**Patterns the report exposed (Desk_metal, Cabinet_A/B):**
- `large-scene-offset` + `axis-90-bake` on EVERY root frame node: Desk X=25m,
  Cabinet_A X=49.4m, Cabinet_B X=51.5m, all R=[90,0,0]. Scene-layout bake
  Unity drops.
- **`bake-vs-world-sign-flip` on EVERY door/drawer**: the FBX node bake X is
  the *negative* of the Unity-authored world X (door_R bake +0.62 → world
  −0.62; door_L mirror; drawer_C bake +0.014 → world −0.014). This is the
  mirror/scatter signal — Unity placed GOs to position node-LOCAL meshes;
  baking node-WORLD in O3DE flips/doubles them. Door L/R naming vs ±X also
  flips between Cabinet_A and Cabinet_B.
- `collider-vs-render-bake`: Desk render FBX baked +25m X, `Desk_metal_COL.FBX`
  at origin → 25m divergence (mesh vs collider).
- **Hash-scheme mesh fileIDs**: Desk frame/drawer_C use Unity hash fileIDs
  (8474…/7295…), NOT the 4300000 linear scheme. Node attribution must
  NAME-match (as `build_fbx_node_paths` does); `resolve_collision_node`'s
  linear decode falls back to node[0] and would mis-resolve a multi-mesh
  hash-fileID FBX — a latent gap in the collider path too (single-mesh
  `_COL` FBXs dodge it; flag if a multi-mesh `_COL` with hash fileIDs appears).

**Truer-state takeaway:** Unity FBX import = node-LOCAL vertices (drops the
scene-layout offset, the sign-flip proves authors positioned via GO not node).
O3DE SceneAPI bakes node-WORLD via our MeshGroup → the scatter. Compensation
(Phase 2, gated on the user's in-engine cook) = cancel the node scene-offset
so the GO/instance transform alone places the mesh (reproducing Unity), and
reconcile the collider FBX's differing bake.

**Suite:** 26 modules green (`QT_QPA_PLATFORM=offscreen python tests/run_all.py`).

## 2026-05-28 (cont.) — User test results + geometry-centroid confirmation

**User confirmed in-engine:** drawer ENTITIES + box COLLIDERS now land
correctly (instance Translate patches + collider centers are right). The
RESIDUAL is purely the **mesh/azmodel internal offset**: each drawer model's
geometry is modeled off-origin, and our `zero_position` strips the offset it
needs. User's manual fix: set the model's mesh `default_position` to
−(its home-instance placement) — fixes ALL instances of that model (instance
Translate handles left/right; the model just needs centering).

**Geometry-centroid probe** (`tools/fbx_geometry_bounds.py` — reads Geometry
Vertices arrays, zlib-aware, cm→m): confirms the meshes are modeled off-origin
and the centroid ≈ the user's fix magnitudes:
- drawer A centroid (−0.598, −0.384, +0.761); B (−0.598, −0.384, +0.536);
  desk geom[1]=drawer_C (+0.011, −0.343, +0.809 — Z matches Unity Y 0.808).
- Calibration vs user's known-good drawer-A fix (O3DE default_position
  −0.603,−0.448,−0.76): the **node transform** (after −90°X) nails Y/Z
  (0.758, 0.452 ≈ 0.76, 0.448) but X is the 25m junk; the **geometry
  centroid** nails X (−0.598≈0.6) but Z is ~0.06 off. ⇒ neither source alone
  is exact; a calibrated combo (node Y/Z + centroid X) or centroid + a
  fine-tune knob reproduces Unity.
- Cabinet_A geom: frame centered; two doors symmetric at centroid X=±0.203,
  Z=1.202 (the L/R doors).

**Compensation candidate (Phase 2):** auto-derive each model's mesh
`default_position` to cancel where O3DE bakes the geometry, reproducing
Unity's node-local. Source = node transform (Y/Z) + geometry centroid (X),
calibrated against the user's A/B fixes; expose the derived value in the
report; allow per-mesh override fine-tune. Awaiting user direction on
approach + acceptable precision (auto-approx vs auto+manual-tune).

**Separate issues surfaced (not transform):**
- Cabinet_A renders fully transparent → material needs cutout/alpha-blend
  (material pipeline, see `mem:project/converter_working_status` material
  section). And Cabinet_A needs the 90° rotation applied (its frame node
  R=90° is being dropped/mishandled for some assets but not others).

## 2026-05-28 (cont.) — Calibration validated + the 90° discriminator (UpAxis)

**Decisions (user):** compensation = calibrated node+centroid; auto-detect 90°
from FBX; user will COOK A TEST before I generalize.

**Translation formula VALIDATED** (Z-up FBXs). For a node:
`default_position_o3de = (centroid_X, node_Y, -node_Z)` (metres; node = Lcl
Translation·0.01, centroid = geometry vertex centroid). Predicts the user's
known-good drawer fixes within 5–8 mm:
- Drawer A predicted (-0.598,-0.452,-0.758) vs user (-0.603,-0.448,-0.76).
- Drawer B predicted (-0.598,-0.452,-0.587) vs user (-0.593,-0.444,-0.586).
(Residual = geometry centroid ≠ true pivot; a fine-tune knob covers it.)

**The 90° discriminator = FBX GlobalSettings UpAxis** (`read_fbx_up_axis`,
already in code; 1=Y-up, 2=Z-up):
- Desk_metal + drawers: **UpAxis=2 (Z-up)** → matches O3DE → oriented fine,
  NO rotation needed. (User: "metal desk is properly oriented.")
- Cabinet_A/_B: **UpAxis=1 (Y-up)** → need Y-up→Z-up 90°X → currently lying
  on their face. (User: "Cabinet_A WAS 90 degrees rotated wrong… laying on
  their face.")
The converter READS up_axis but applies NO correction (global auto-correct
was removed earlier for overcompensating). Correct rule is PER-FBX:
`UpAxis=1 → apply 90°X; UpAxis=2 → none`. This also explains why the old
GLOBAL 90° default helped Y-up assets and broke Z-up ones.
Geometry-extent corroborates: Cabinet tallest extent in Z=2.39m (height),
Desk tallest in X=1.82m (width).

**Open for the cook test:** O3DE's CoordinateSystemRule uses
`useAdvancedData=true`; this may suppress O3DE's own UpAxis auto-convert, so
Y-up FBXs need the 90° supplied explicitly (default_rotation) OR
useAdvancedData dropped. The cook decides exact sign (+90 vs -90) and whether
the Y-up case also shifts the translation mapping (translation validated only
for Z-up desk so far). Cabinet door L/R can't be judged until it stands up.

**Translation calibration uses `tools/fbx_geometry_bounds.py` centroid +
`read_fbx_node_transforms`.**

## 2026-05-28 (cont.) — Cook confirmed; UpAxis rotation SHIPPED

**Cook results (user):** Cabinet_A needs **+90° X** (positive) to stand up.
Cabinet doors render correctly at entity 0,0,0 with NO translation comp —
they're sub-meshes of a MULTI-mesh FBX, so Unity/O3DE keep their FBX-relative
position. Drawers (SINGLE-mesh FBX) DO need translation (instance double-counts
the centered mesh). Structural rule confirmed:
- **Rotation = per-FBX UpAxis** (1→+90°X, 2→none). SHIPPED in
  `write_fbx_assetinfo`: composes a +90°X quat under the user's
  default_rotation when up_axis==1. Verified: Cabinet rule rotation
  [.707,0,0,.707]; Desk none. Tests updated (the old "Y-up does NOT correct"
  tests now assert the per-FBX correction; added Z-up no-correct guard).
  Suite 28 modules green.
- **Translation = single-mesh-FBX only.** Single-mesh FBX (drawer A/B) → Unity
  centers it → cancel the bake via calibrated `(centroid_X, node_Y, -node_Z)`
  (validated 5-8mm). Multi-mesh sub-mesh (cabinet doors) → keep bake, entity
  places it (0,0,0). **Edge: multi-mesh sub-mesh WITH a non-zero GO offset
  (drawer C, GO at 0.808) double-counts** → fix = drop the redundant GO
  transform (entity-side, like "Prefab Root Discarded" but for sub-mesh
  children). NOT yet built.

**Why the user's manual fix "reset":** it was applied in-engine, not emitted by
the converter — a re-cook wipes it. Compensation must be EMITTED (the converter
writes default_position into the CoordinateSystemRule).

**User's "anchor to another mesh's center" idea** = the relational version of
the same compensation; the validated node+centroid formula already derives it
per-mesh automatically, so no manual mesh-pairing is needed.

### Pending (translation auto-comp — awaiting user go-ahead)
1. Single-mesh FBX → auto-emit `default_position = (centroid_X, node_Y,
   -node_Z)` (computed in producer/writer; user override still wins). Needs
   geometry-centroid read on the hot path (single-mesh only, so cheap-ish).
   Calibrated on Z-up desk; Y-up single-mesh axis mapping unverified.
2. Multi-mesh sub-mesh with GO offset (drawer C) → drop the redundant entity
   transform. Entity-side, riskier — confirm approach with user.
I.3 (expose suggested_offset/UpAxis/tags in report) still pending.

## 2026-05-28 — P-stage: Desk_metal dissected, root cause found, instrument prototyped

- Full dissection of `OfficeAndPoliceStation/.../Desk_metal.prefab` + its
  nested drawer prefabs (A/B) + the desk/drawer/cabinet FBXs. See plan
  `mem:transform_truth/transform_truth_plan` for the evidence table.
- **Root cause:** converter is blind to FBX node `Lcl Translation/Rotation`.
  Pack bakes scattered scene offsets (Desk frame 2500cm X, Cabinets
  4943/5151, drawers ~2440) + a 90° X axis bake into FBX root nodes;
  `_COL` FBXs sit at origin (diverging from render). Unity importer uses
  node-LOCAL vertices (drops scene offset, bakes axis); O3DE SceneAPI bakes
  node WORLD transform via our MeshGroup → scatter. Door L/R ordering flips
  between Cabinet_A/B → the mirroring symptom.
- **Not the bug:** nested-instance placement — converter already emits
  correct `(x,z,y)` Translate patches for the 4 drawers.
- **Prototype:** `tools/fbx_node_transforms.py` — recursive binary-FBX
  reader extracting Model-node Lcl T/R/S (cm). Validated on Desk/Cabinet/
  drawer FBXs (v7200). This is the keystone instrument for I.1.
- Env note: full pipeline now runs locally (PySide6 installed); tests via
  `QT_QPA_PLATFORM=offscreen python tests/run_all.py` (24 modules green).

### Pending — P-stage Q&A (awaiting user)
Scope of first deliverable (diagnostic-only vs +compensation); whether to
reconcile against actually-cooked azmodel bounds or emitted intent;
whether to empirically confirm the "Unity node-local" hypothesis by
cooking one FBX in-engine before building compensation. Then I.1+.
