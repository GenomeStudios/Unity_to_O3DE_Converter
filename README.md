==USAGE VIDEO==

# Unity → O3DE Converter

A Conversion Project workspace for bringing Unity content into O3DE. The
tool itself is the surface layer; the long-term goal is to **formalize
a conversion language** — a vocabulary of stages, scopes, marks,
overrides, sync states, and patches — that other engines can mirror to
solve their own one-off conversion problems systematically.

> System co-developed with Claude LLMs. Public Domain.

---

## Vision: a conversion language, not just a converter

Cross-engine asset migrations get re-solved every time someone needs
one. The same obscure issues (mesh pivot rebake, smoothness→roughness
inversion, prefab override propagation, scene reference resolution)
get rediscovered in isolation, fixed once, and lost.

This project is a working bet that those issues have *common shapes*,
and that the right surface area looks like:

| Stage shape | What it does | Engine-specific code |
|---|---|---|
| **Scope** | Pin the walking root of a source project | Choose a folder |
| **Mark** | Pick the subset to convert from scrubbed inventories | UI checklists |
| **Preprocess** | Per-asset overrides + cross-asset mapping libraries | Mesh / material / shader rules |
| **Orchestrate** | Pre-flight check → staged execution | Generic dispatch |
| **Sync** | Track input hashes vs last-export hashes per stage | Generic state machine |
| **Patch** | Surgically re-emit only affected artifacts | Per-asset emitters |

Unity → O3DE is the first concrete implementation. If the shape is
right, an Unreal → O3DE or Unity → Godot converter should be largely
the same Conversion Project workspace with different emitters wired in.
That is the language we are trying to formalize through this project.

**Co-development with LLMs is part of the methodology**, not a side
note. Every non-trivial feature has a locked Q&A plan + living working
doc in `.serena/memories/`, so both humans and LLMs can pick up cold
and contribute without re-deriving prior decisions. The
[PID memory methodology](#pid-memory-methodology) below explains how
to read those files.

---

## Status at a glance

| Layer | Status |
|---|---|
| Conversion Project system (named projects, save/load/recent) | Shipped |
| Project header banner + custom window chrome (frameless) | Shipped |
| Dashboard with per-stage status cards | Shipped |
| Project-level `scope_root` + per-stage source override | Shipped |
| Dependency-missing startup banner | Shipped |
| Multi-scene marking + nested O3DE level output | Shipped |
| State management (sidecar-free, input-hash sync) | Shipped |
| Scrubbed prefab marking (F-4) | Pending |
| Mesh preprocessing + per-FBX overrides (F-5) | Pending |
| Material shader-mapping library (F-6) | Pending |
| Terrain heightmap extraction (F-7) | Partial — materials only |
| Staged orchestration + pre-flight (F-8) | Pending |
| Patch worker for cheap re-emit (F-9) | Foundation laid; lighter scope post-state-management |

See the [feature roadmap](#feature-roadmap) for details.

---

## Quick start

Requires Python 3.10+, PySide6, PyYAML. Pillow is optional (used for
smoothness → roughness texture re-bake).

```
pip install PySide6 PyYAML Pillow
```

**Launch the GUI:**

```
UnityToO3DE_Converter.bat        # Windows
python main_app.py               # any platform
```

CLI tab override (e.g. open straight to Scene Converter):

```
python main_app.py --tab=scene
```

Accepted values: `dashboard` (default) / `scene` / `prefab` / `terrain`.

---

## Project workflow

The Conversion Project is the unit of work. A project owns:

1. **Scope root** — the Unity assets walking root.
2. **Per-stage settings** — selected scenes, prefab directories,
   selected terrain materials, output destinations.
3. **Pipeline status** — last-run timestamps + summary counts per stage.
4. **Outputs** — entity maps, asset index, coverage reports
   (formerly `.ImporterData/` sidecars; now embedded in the project
   file).
5. **Sync state** — input-hash fingerprints per stage so the Dashboard
   can tell you when the outputs on disk no longer match the project's
   current settings.

Projects live as `.u2oproj.json` files at any path you choose. The
Dashboard's per-stage cards show readiness (what's configured) and
sync state (whether outputs match settings), with a per-card Process
button to fire that stage's worker without leaving the tab.

---

## PID memory methodology

Every non-trivial feature in this codebase has its design captured
under `.serena/memories/<feature>/`. This is intentional — the
project is co-developed with LLMs, and durable design memory is the
mechanism that lets a fresh session pick up where the last one left
off without re-deriving prior decisions.

### File pair per feature

```
.serena/memories/<feature>/
  <feature>_plan.md            Design-locked. The destination.
  working_documentation.md     Living status log. The journey.
```

### Reading order

For any feature you want to understand or extend:

1. **Skim the plan's `Goal` section** — one paragraph stating intent.
2. **Read `Resolved Decisions (Q&A history)`** — every locked design
   decision is captured with the *why* alongside the *what*. This is
   the most valuable section for understanding why the code looks the
   way it does.
3. **Skim the `Design`** — data shapes, module boundaries, contracts.
4. **Scan the `Implementation Plan`** — numbered phases (I.1 / I.2 /
   ... ) with explicit "Done when" criteria.
5. **Read the working doc's newest entry** — current shipped state +
   any open follow-ups. Newest entries are at the top.

### Writing convention

- **Plan files are design-locked.** Edits add new Resolved Decisions
  (Q&A); they don't rewrite history.
- **Working docs are living.** Newest entries on top. Older entries
  stay for context.
- **Q&A history is sacred.** When a decision changes, append a new Q
  + A that supersedes the old one. Don't delete.
- Cross-link related memories with `[[memory-slug]]`.

### Current memory clusters

| Folder | What it covers |
|---|---|
| `project_system/` | Base Conversion Project system, file format, ProjectManager |
| `project_scope/` | F-2 — project-level scope_root + per-stage source override |
| `scene_marking/` | F-3 — multi-scene checklist + nested level output |
| `dependency_banner/` | F-1 — startup dependency warning banner |
| `ui_reorganization/` | UX-1 — banner + dashboard + tab reorder + readiness summaries |
| `window_chrome/` | UX-2 — frameless window + custom title bar |
| `state_management/` | Sidecar removal + sync-state engine + Process buttons |
| `terrain/` | Terrain materials importer |
| `material_conversion/` | Material pipeline (label resolution, slot mapping) |
| `project/` | Pre-system converter notes |

Each folder's working doc is the right entry point for understanding
the current state of that subsystem.

---

## Feature roadmap

`F-1` through `F-9` are the named features in the roadmap. The
ordering reflects dependencies, not strict execution order — F-3
shipped before F-4 because they turned out to be more independent
than originally planned.

| ID | Feature | Status | Memory |
|---|---|---|---|
| F-1 | Startup dependency banner | **Shipped** | `dependency_banner/` |
| F-2 | Project-level scope path + per-stage source override | **Shipped** | `project_scope/` |
| F-3 | Multi-scene marking + nested O3DE level output | **Shipped** | `scene_marking/` |
| F-4 | Scrubbed prefab checklist (replaces "process everything in source") | Pending | (no memory yet) |
| F-5 | Mesh preprocessing — defaults + per-FBX overrides + patch primitives | Pending | (no memory yet) |
| F-6 | Material shader-mapping library + unknown-shader detection | Pending | (no memory yet) |
| F-7 | Terrain heightmap extraction (+ existing materials) | Partial — materials shipped, heightmap pending | `terrain/` |
| F-8 | Staged orchestration + pre-flight checks | Pending | (no memory yet) |
| F-9 | Output-state patching worker | Foundation laid by state-management | (no memory yet) |

Architectural / UX work that's already shipped:

| Feature | Memory |
|---|---|
| Conversion Project base (save/load/recent, dashboard) | `project_system/` |
| UI reorganization (banner + dashboard + tab order + readiness) | `ui_reorganization/` |
| Custom window chrome (frameless + title bar) | `window_chrome/` |
| State management (sidecar removal + sync state) | `state_management/` |

Future polish carried explicitly across feature boundaries:

- **`Auto-Sync changes` Config toggle** — post-F-9. Opt-in background
  patch worker that auto-re-emits when overrides change. Default off.
  Captured in `state_management/state_management_plan.md` Q10.

---

## What converts

| Unity | O3DE | Status |
|---|---|---|
| Prefab hierarchy | Entity hierarchy in `.prefab` | Working |
| Uniform transform | TransformComponent | Working |
| Non-uniform scale | EditorNonUniformScaleComponent | Working |
| MeshFilter + MeshRenderer | EditorMeshComponent | Working |
| Multi-material slots | EditorMaterialComponent `{}` default + `{0}`, `{1}`... | Working |
| FBX `.assetinfo` per-entity MeshGroups | Named, predictable `.azmodel` asset hints | Working |
| Texture maps (albedo, normal, metallic, roughness, occlusion, emissive) | StandardPBR properties | Working |
| Transparency / alpha clip | `opacity.mode = Blended` + `alphaSource = Packed` | Working |
| Metallic/roughness reconciliation (texture-aware) | Bound texture → no `metallic.factor`; `roughness.lowerBound/upperBound` from `_GlossMapScale` or `_Smoothness` | Working |
| BoxCollider | EditorBoxShapeComponent + EditorShapeColliderComponent | Working |
| SphereCollider | EditorSphereShapeComponent + EditorShapeColliderComponent | Working |
| CapsuleCollider | EditorCapsuleShapeComponent + EditorShapeColliderComponent | Working |
| MeshCollider | EditorMeshColliderComponent | Working |
| Rigidbody (dynamic) | EditorRigidBodyComponent | Working |
| No Rigidbody + collider | EditorStaticRigidBodyComponent | Working |
| Multiple colliders on one GO | Overflow → child entities `{Name}_Collider_N` | Working |
| Nested prefab instances | Nested instance references | Working |
| Prefab override — transform | Tier 1 JSON patches (`Translate/N`, `Rotate/N`, uniform `Scale`) | Working |
| Prefab override — `m_Materials.Array.data[N]` | Tier 3 `assetHint` patches via project's entity-map records | Working |
| Prefab override — `m_IsActive`, added/removed components | Logged to coverage, not emitted | Pending |
| Directional light | EditorDirectionalLightComponent (intensity, shadows) + 180° pitch correction | Working |
| Point / Spot / Area lights | EditorAreaLightComponent (Sphere / SimpleSpot / SimplePoint) | Working |
| Scene placement + rotation | Prefab instance transforms in level | Working |
| Scene → multi-output: `<output>/<SceneName>/<SceneName>.prefab` | O3DE nested level convention | Working |
| Unowned scene entities (physics + lights) | Same component pipeline as prefab processing | Working |
| Mesh pivot / coordinate rebake | — | Known issue (see below) |
| Terrain `.mat` → TerrainBaseMaterial | Per-material `.material` file emit | Working |
| Terrain heightmap extraction | — | Pending (F-7) |

---

## Architecture

```
unity_to_o3de_converter/
  main_app.py                      Unified PySide6 GUI (entry point)
  project_manager.py               Project model + ProjectManager singleton
  integrated_asset_processor.py    Stage 1 — prefab + asset processing
  unity_scene_converter_gui.py     Stage 2 — scene to level conversion
  terrain_material_processor.py    Terrain materials (TerrainBaseMaterial)
  converter_settings.json          App-level state (recent projects, config)
  Projects/                        Per-project .u2oproj.json files

  components/                      Pluggable component processor modules
    __init__.py                    Auto-discovery and dispatch table
    base.py                        ComponentProcessor ABC + ProcessingContext
    mesh.py            weight=25   MeshFilter / MeshRenderer
    material.py        weight=50   Material slot mapping
    rigidbody.py       weight=75   Rigidbody (dynamic + static)
    box_collider.py    weight=100  BoxCollider
    sphere_collider.py weight=125  SphereCollider
    capsule_collider.py weight=150 CapsuleCollider
    mesh_collider.py   weight=175  MeshCollider
    light.py           weight=510  All Unity Light types

  .serena/memories/                PID methodology — feature plans + working docs
    <feature>/<feature>_plan.md
    <feature>/working_documentation.md

  TestObjects/                     Local test fixtures (gitignored)
    TestProject.u2oproj.json       Reference testbed for feature verification
```

The Conversion Project is the data model that everything orbits.
`Project` (in `project_manager.py`) owns `scope_root`, per-stage
`stages` settings, `pipeline_status` summaries, and full `outputs`
bookkeeping. Workers read project state at start, write outputs at
finish; the Dashboard reads everything via `compute_stage_readiness`
and `compute_stage_sync_state`.

Component processors are auto-discovered: drop a new module in
`components/`, set a `WEIGHT` for ordering and a `HANDLES` list of
Unity component types, and it runs.

---

## Known issues

**Mesh coordinate system.** Unity internally rebakes mesh coordinates
in a way that does not match the raw FBX on disk. The converter
applies the Unity → O3DE axis swap — position `(x, z, y)`, rotation
`(qx, qz, qy, qw)`, scale `(sx, sz, sy)` — but cannot correct for
Unity's internal mesh pivot bake. A Blender transform-bake pass was
attempted and abandoned as ineffectual. This is the primary visual
accuracy issue on some assets.

**Material pipeline.** Texture, normal, metallic, roughness, and
opacity conversions are functional. Specular workflow, detail maps,
and some edge-case shader properties are not yet mapped. F-6 is the
formal fix.

**Smoothness alpha channel.** Unity's `_MetallicGlossMap` stores
smoothness in the alpha channel. O3DE reads roughness from the alpha
directly, so on materials using this map the shiny/dull values are
inverted. The bounds remap (`roughness.lowerBound/upperBound`) is
mathematically correct, but the texture content needs pre-inversion
at copy time to look right. Optional Pillow-backed re-bake exists
(`Config → Convert smoothness to roughness`) but is off by default.

---

## Authoring a component processor

The `components/` directory is a self-contained plugin system. Drop
a new `.py` file in and it is auto-discovered, instantiated, and
wired into the pipeline on the next run. No core changes needed.

### Minimal example

```python
from typing import Callable, Dict, List
from .base import ComponentProcessor, ProcessingContext


class LightComponentProcessor(ComponentProcessor):
    """Convert Unity Light components to O3DE EditorLightComponent."""

    WEIGHT  = 200                  # lower = runs earlier; built-ins use multiples of 25
    HANDLES = ['Light']            # Unity component types this processor parses
    EMITS   = ['EditorLightComponent']   # informational

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:
        # Called once per Unity component during parse phase.
        # Populate go.component_data (or standard fields like go.mesh_guid).
        go.component_data['light'] = {
            'intensity': float(comp_data.get('m_Intensity', 1.0)),
        }

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        # Called once per entity during the O3DE prefab generation phase.
        # Mutate entity['Components']; return child entity IDs you created.
        light = go.component_data.get('light')
        if not light:
            return []
        entity['Components']['EditorLightComponent'] = {
            '$type': 'EditorLightComponent',
            'Id':    ctx.generate_component_id(),
            'Controller': {'Configuration': {'Intensity': light['intensity']}},
        }
        ctx.log(f"  [Light] ✓ EditorLightComponent — intensity={light['intensity']}")
        return []
```

### ProcessingContext reference

| Field / method | Purpose |
|---|---|
| `ctx.material_mapping` | `dict[guid → asset_hint]` for Unity materials |
| `ctx.mesh_mapping` | `dict[guid → asset_hint]` for Unity meshes |
| `ctx.entities_dict` | All entities being built (mutate to add child entities) |
| `ctx.entity_id_map` | `dict[file_id → entity_id]` |
| `ctx.generate_component_id()` | Unique component ID string |
| `ctx.generate_entity_id()` | Unique entity ID string |
| `ctx.make_bare_entity(id, name, parent_id)` | Minimal child entity with standard boilerplate |
| `ctx.log(msg)` | Emit to the GUI console |

### Logging conventions

```
[MyComp] ✓ ...   Successful emit
[MyComp] ⚠ ...   Warning — partial result, fallback used
[MyComp] ✗ ...   Error — component skipped
```

---

## Change log (highlights)

**2026-05-27 — State management refactor**

- `.ImporterData/` directory removed. All entity maps, asset index
  records, and coverage reports now live in the `.u2oproj.json` file
  under `outputs.<stage>`. Schema version 2.
- Input-hash-driven sync state added per stage: `unconfigured /
  ready / synchronized / unsynchronized / writing / error`.
- Dashboard status cards gained a Process button + sync-state row.
- Stage 2 prefab database reads entity maps + asset index from the
  project file instead of disk sidecars.

**2026-05-26 — Project system + UX overhaul**

- Conversion Project file format (`.u2oproj.json`) + ProjectManager.
- Project header banner at the top of the window with File menu.
- Dashboard tab (renamed from Project tab) with per-stage readiness
  cards.
- Tab order reflects configuration workflow: Dashboard → Scene →
  Prefab → Terrain.
- Frameless window with custom Catppuccin-styled title bar
  (min/max/close + edge resize).
- F-1 (dependency banner), F-2 (scope path), F-3 (multi-scene)
  shipped.

**2026-05-25 — Prefab override propagation**

- Tier 1 (transform), Tier 3 (material slot) overrides emit as O3DE
  JSON patches. Tier 2 (`m_IsActive`) and Added/Removed components
  recorded as unhandled overrides in coverage.
- Per-prefab entity-map sidecars introduced (since absorbed into the
  project file as of 2026-05-27).
- Metallic/roughness texture-aware reconciliation; opacity
  `alphaSource = Packed` for Cutout + Blended materials.

**2026-03-14 — Component pipeline + scene unowned entities**

- Component processing for unowned scene entities (physics + lights
  on non-prefab scene GameObjects).
- Unified `light.py` processor handling Directional / Point / Spot /
  Area in one module. 180° pitch correction for directional lights.
- X-axis inversion removed from coordinate conversion; final swap is
  `(x, z, y)` / `(qx, qz, qy, qw)`.
- FBX `.assetinfo` per-entity MeshGroups with binary FBX parser for
  sub-objects.

**2026-03-13 — GUI consolidation**

- Unified PySide6 GUI with Catppuccin dark theme.
- Component processing refactored into auto-discovered weighted
  plugin modules.
- Full physics pipeline: Box/Sphere/Capsule/MeshCollider +
  Rigidbody / StaticRigidBody.

**2026-02-06 — Initial functionality**

- Multi-material slot conversion.
- Transparency / opacity conversion.
- Collider + Rigidbody detection.
- Mesh / model offsets identified as ongoing issue.
