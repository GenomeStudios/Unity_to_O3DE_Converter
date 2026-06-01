---
name: transform-truth-plan
description: P/I/T plan for the transform-truth diagnostic — exposing FBX-baked node offsets + full Unity-vs-O3DE world-placement reconciliation, to explain & compensate the scatter seen on Office/Police furniture (Desk_metal et al).
metadata:
  type: project
---

# Transform Truth — Plan

## Problem

Author-curated Unity prefabs (esp. `OfficeAndPoliceStation` furniture)
look correct in Unity but **scatter/explode after conversion**: meshes,
colliders, drawers, doors land at wrong offsets, some need a 90° fix and
some don't, doors mirror to the wrong side. The core tenet: **Unity is
ground truth — the pack is correctly arranged there.** The converter
loses the nuance of how placement is composed.

## Root cause (evidenced on Desk_metal, 2026-05-28)

The converter is **blind to FBX node transforms** — `read_fbx_mesh_node_names`
reads only names. But the asset pack bakes scene placement into FBX node
`Lcl Translation/Rotation`, and authors did it inconsistently:

- `Desk_metal.FBX` → `Desk_metal::Model` **T=[2500,0,-0.134]cm R=[90,0,0]**;
  `Desk_metal_drawer_C::Model` T=[1.4,80.8,45.0] R=0.
- `Desk_metal_COL.FBX` → T=[0,0,0] R=[90,0,0] (collider at origin — does
  NOT share the 2500 offset of the render frame).
- `Cabinet_A.FBX` root T=[4943,…]; `Cabinet_B.FBX` root T=[5151,…];
  drawer A/B roots T≈2440. All R=[90,0,0].
- Sub-nodes carry the *real* small placements: `Cabinet_A_door_R` X=+62.4,
  `door_L` X=−62.4; `Cabinet_B_door_L` X=−55.2, `door_R` X=+54.6 — note
  the L/R **ordering flips between cabinets** (the door-mirroring symptom).

Unity's FBX importer effectively uses **node-LOCAL vertices** (drops the
node's scene-position offset, applies the Z-up→Y-up 90° axis bake into
vertices), so an author GO at (0,0,0) renders correctly. O3DE SceneAPI,
with our current `MeshGroup` + `CoordinateSystemRule(useAdvancedData)`,
bakes the node's **world** transform → the 2500cm offset and/or the 90°
reappear, differently per FBX. Colliders diverge because the `_COL` FBX
has a different (often zero) baked offset than the render FBX. Box-collider
centers are authored relative to the GO and so land wrong once the mesh
itself is mis-baked.

The nested-instance placement is NOT the bug: the converter already emits
correct `(x,z,y)`-swapped Translate patches for the 4 drawer instances
(verified: Drawer A L=[-0.602,0.448,0.76], R=[0.603,…], etc.).

## Locked facts
- FBX is binary (v7200/7300); units cm, Unity import scale 0.01 → m.
- FBX node parser prototype exists: `tools/fbx_node_transforms.py`
  (recursive binary-FBX reader → Model nodes' Lcl T/R/S). Validated on
  Desk/Cabinet/drawer FBXs.
- Converter coordinate map (positions) `(x,z,y)`, no X negation, is correct
  for explicit transforms (`mem:project/converter_working_status`).
- The 90° X on root nodes is the 3ds-Max Z-up→Y-up export bake.

## Open questions (resolve before I-phases)
- Q1 Scope of first deliverable: read-only **diagnostic report** that
  exposes the truer state (recommended), vs jumping to auto-compensation.
- Q2 Reconciliation target: do we validate Unity-composed world placement
  against the **actually-cooked** O3DE azmodel/pxmesh bounds (needs an AP
  cook + .azmodel reader), or against the **emitted assetinfo intent**
  (static, no engine)?
- Q3 Compensation mechanism (Phase 2): when an FBX node has a scene-offset
  Unity zeroed, do we (a) emit a CoordinateSystemRule translation that
  cancels it, (b) set an Origin/`use mesh origin` rule, or (c) bake a
  per-mesh override? Needs an O3DE SceneAPI capability check
  (`o3de_sourcedev` CoordinateSystemRule / OriginRule).
- Q4 Pattern taxonomy to detect & flag: {giant-scene-offset bake, 90°
  axis bake, collider-FBX-vs-render-FBX offset delta, door/drawer L↔R
  mirror, sub-node real-offset}. Which to auto-classify first.

## Implementation Plan (staged; P done, I/T pending Q&A)

### P — understanding + instrument prototype  ✅ (this session)
Desk_metal fully dissected; `tools/fbx_node_transforms.py` reads node
T/R/S; root-offset + 90° + collider-divergence + door-mirror patterns
identified and evidenced.

### I.1 — Productionize the FBX node-transform reader
Move the parser into the codebase (e.g. `formats/fbx/node_transforms.py`
or alongside the existing FBX readers), unit-tested against the Office
FBXs. Surfaces `{node_name: {translation, rotation, scaling}}` in cm and
in Unity-meters. **Done when** the reader returns the Desk/Cabinet values
above and has tests.

### I.2 — Transform reconciliation report (read-only diagnostic)
For a given Unity prefab, compose the **Unity true world transform** of
every renderable + collider: GO-hierarchy locals × nested-instance
placements × FBX node bake (node-local convention) × collider center.
Emit a table: per element, Unity-world vs the converter's emitted O3DE
placement, with a divergence delta and a pattern tag. Output as
structured JSON + a readable log. **Done when** Desk_metal's report names
the 2500cm frame bake and the collider divergence with numbers.

### I.3 — Pattern detectors + contingency flags
Classify each divergence (Q4 taxonomy). For each, propose a concrete
compensation the converter could apply. Wire detectable ones into the
coverage/preflight surface so the user gets a punch list per prefab.

### I.4 — Compensation (separate, gated on Q3)
Apply the highest-confidence contingency (likely: cancel the FBX node
scene-offset so mesh sits at the GO origin like Unity; reconcile collider
FBX bake). Re-run Desk_metal end-to-end; verify in-engine.

## Testing matrix
| ID | Proof |
|---|---|
| T-1 | node reader returns Desk_metal frame T=[2500,0,-0.134] R=[90,0,0]; drawer_C T≈[1.4,80.8,45.0] |
| T-2 | reader handles v7200 + v7300; non-binary → empty |
| T-3 | reconciliation report flags the frame's 25m X bake vs emitted placement |
| T-4 | report flags collider(_COL origin) vs render(2500) divergence |
| T-5 | door L/R mirror detector fires on Cabinet_A vs Cabinet_B ordering |
| T-6 (I.4) | compensated Desk_metal: frame+drawers+colliders within tolerance of Unity world placement, verified in O3DE |

## Out of scope (for now)
- Non-FBX mesh formats. Animation/skin. Material placement.
- Auto-fixing every pattern — start with the dominant scene-offset bake.
