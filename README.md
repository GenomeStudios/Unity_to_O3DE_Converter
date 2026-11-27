<img width="1349" height="1227" alt="image" src="https://github.com/user-attachments/assets/fd3482f2-499b-4397-aa31-78405fb6fae6" />

[Youtube Demo Video](https://youtu.be/amyFFLV5Dck)

# To‑O3DE Project Converter

A multi-platform Conversion Project workspace for migrating game-engine
and DCC content into **Open 3D Engine (O3DE)**. Point it at a project
folder, mark the assets you want, run a staged conversion, and get
O3DE prefabs, materials, meshes, and levels on the other side — with
a patchable state record so you can iterate on overrides without
re-running from scratch.

Unity is the production-ready reference platform that ships today.
The architecture is built around a **source-platform plugin contract**
so additional engines (Unreal, Godot, Blender, …) can plug in without
touching the core.

> System co-developed with Claude LLMs. Public Domain.

---

> [!IMPORTANT]
> **If you're an LLM picking up this project**, stop and read
> [`AGENTICS_GUIDELINES.md`](AGENTICS_GUIDELINES.md) **first**. It is
> the primary funnel point and covers the P/I/T methodology, the
> memory model under `.serena/memories/`, and how to interact with
> the developing user. Skipping it is the most common failure mode.

---

## What it does

| You give it | The converter produces |
|---|---|
| A source-engine project folder (Unity `Assets/`, etc.) | An O3DE-shaped output tree |
| A list of marked prefabs, scenes, and terrain materials | One `.prefab` per source prefab + per-scene level prefabs + `.material` files + copied textures + FBX `.assetinfo` sidecars |
| Per-mesh + per-material overrides | Overrides baked into the emitted O3DE assets |
| Subsequent edits to overrides / profiles | Patch-only re-emission via input-hash-driven dirty detection |
| Project switches mid-flight | Non-destructive per-platform state (Unity edits preserved when you switch to Unreal slot and back) |

Mission Command (the Dashboard) is the single launch surface — it
gates Run All on a pre-flight check pass and surfaces per-stage
status, sync state, and dirty markers.

---

## Status

| Layer | Status |
|---|---|
| Conversion Project system (`.u2oproj.json`, save/load/recent) | **Shipped** |
| Mission Command (preflight + Run All + Patch All) | **Shipped** |
| F-9 shader profile library + per-material overrides + patch worker | **Shipped** |
| F-9 mesh per-FBX overrides + assetinfo composition | **Shipped** |
| F-9 state index + externally-modified detection | **Shipped** |
| F-8 orchestration + per-stage cancel | **Shipped (T-8 failure routing deferred)** |
| Platform-abstraction refactor (SourcePlatform plugin contract) | **Shipped** |
| Per-platform UI tab gating (`SUPPORTED_TABS`) | **Shipped** |
| Unity source plugin | **Shipped — reference implementation** |
| Unreal / Godot / Blender source plugins | Open — see [`platforms/README.md`](platforms/README.md) |
| F-7 terrain heightmap extraction | Partial — materials shipped, heightmap pending |
| F-10 shader profile authoring editor | Pending — stub plan in `.serena/memories/profile_editor/` |

---

## Quick start

Requires **Python 3.10+**, **PySide6**, **PyYAML**. **Pillow** is
optional (smoothness → roughness alpha re-bake).

```bash
pip install PySide6 PyYAML Pillow
```

**Launch the GUI:**

```bash
python main_app.py               # any platform
UnityToO3DE_Converter.bat        # Windows shortcut
```

Open a project (or create one), pick a Source Engine + Source Root,
mark prefabs/scenes/materials on their respective tabs, then click
**Run All** in Mission Command.

CLI tab override:

```bash
python main_app.py --tab=prefab    # dashboard / scenes / prefabs / meshes / materials / terrain
```

### Without the window

```bash
python converter_cli.py describe <project.u2oproj.json>                 # settings, component processors, last coverage
python converter_cli.py run      <project.u2oproj.json>                 # the stage runs of the Process buttons
python converter_cli.py truth    <project.u2oproj.json> --out <folder>  # Unity writes what it holds after import
```

`run` takes `--stage`, `--only`, `--set stage.key=value` (for that run only), `--trace <folder>` (how every
emitted value was produced) and `--seed`. `truth` needs the Unity Editor of the project's own version: see
[`platforms/unity/bridge/README.md`](platforms/unity/bridge/README.md). No command writes to the project file.

To measure a conversion against Unity itself, see [`parity/README.md`](parity/README.md).

---

## Workflow at a glance

```
1.  Open or create a Conversion Project       (.u2oproj.json)
2.  Set Source Engine + Source Root           Dashboard banner
3.  Mark prefabs / scenes / terrain           per-tab inventories
4.  Customize per-asset overrides             Mesh / Material tabs
5.  Edit shader mappings if needed            Materials → Edit Mappings
6.  Check Mission Command pre-flight          green-light gate
7.  Run All                                    full pipeline pass
                                              OR
    Patch All                                  re-emit dirty only
8.  Review output state + state index         Dashboard cards
```

Switching the Source Engine mid-flight is non-destructive — every
platform gets its own slot for `stages` and `outputs`. Your Unity
selections + overrides survive a round-trip through Unreal and back.

---

## Architecture (high level)

```
to-o3de_project_converter/
    main_app.py                       Unified PySide6 GUI (entry point)
    project_manager.py                Project model + ProjectManager
    integrated_asset_processor.py     Worker — parse/emit orchestration
    unity_scene_converter_gui.py      Stage 2 — scene to level conversion
    terrain_material_processor.py     Terrain materials
    preflight.py                      Pre-flight check registry
    converter_cli.py                  The converter without its window (describe / run / truth)
    stage_runner.py                   Stage runs shared by the GUI and the command line
    conversion_trace.py               How every emitted value was produced (optional)
    fbx_reader.py                     What a binary FBX says: axes, unit, node tree, materials
    fbx_material_names.py             Materials of one name on one mesh, renamed in the converted copy
    matrix3.py                        The small 3x3 rotation arithmetic the converter needs
    converter_settings.json           App-level state (recent projects)
    Projects/                         Per-project .u2oproj.json files

    platforms/                        Source-engine plugins
        base.py                       SourcePlatform ABC (the contract)
        types.py                      Neutral data shapes
        unity/                        Unity reference plugin
            bridge/                   Headless Unity runs: the truth dump
            model_import.py           What Unity makes of a model file: ids, objects, materials
            builtin_meshes.py         Unity's six built-in meshes, written out
            mesh_asset.py             A mesh stored on its own in a Unity .asset, written as a model
            shader_source.py          What a shader file declares: properties, culling, alpha cut
            scale_carry.py            A scale by axis carried down to the objects below it
            scene_lighting.py         A scene's ambient colours
        README.md                     How to add a new platform

    targets/                          Output-target writers
        o3de/                         O3DE prefab + assetinfo writers
            texture_settings.py       Texture settings beside a texture whose alpha is opacity

    components/                       Legacy back-compat shim
                                      (canonical home: platforms/unity/components/)

    tests/                            Plain-Python test suite (no pytest)
        run_all.py                    Walk + dispatch every test_*.py
        unit/                         (9 modules, 62 tests)
        integration/                  (4 modules, 16 tests)
        ui/                           (4 modules, 15 tests)
        README.md

    tools/                            Standalone helper scripts
        bake_fbx_transforms.py        Blender headless companion

    parity/                           Parity harness: Unity's truth against the O3DE result
        parity.py                     One command per cycle
        README.md

    .serena/memories/                 Design memory (P/I/T methodology)
        <feature>/<feature>_plan.md
        <feature>/working_documentation.md

    AGENTICS_GUIDELINES.md            LLM co-development guide (READ FIRST if LLM)
    README.md                         This file
```

The **Conversion Project** is the data unit that everything orbits.
A project carries the source-engine selection, scope root, marked
inventories, per-platform stage settings, output state index, and
preflight acknowledgements — all in one `.u2oproj.json` file.

The **platform plugin contract** is the seam between the engine-neutral
orchestration core and the source-engine-specific parsers. See
[`platforms/README.md`](platforms/README.md) for the contract spec.

---

## What converts (Unity → O3DE)

| Unity | O3DE | Status |
|---|---|---|
| Prefab hierarchy | Entity hierarchy in `.prefab` | Working |
| Transform (uniform + non-uniform scale) | TransformComponent + EditorNonUniformScaleComponent | Working |
| MeshFilter + MeshRenderer | EditorMeshComponent | Working |
| Multi-material slots | EditorMaterialComponent (`{}` default + `materialsByLabel`) | Working |
| FBX `.assetinfo` per-entity MeshGroups | Named `.azmodel` asset hints | Working |
| Texture maps (albedo, normal, metallic, roughness, occlusion, emissive) | StandardPBR property values | Working |
| Transparency / alpha clip / cutout | `opacity.mode` + `alphaSource = Packed` | Working |
| Metallic-gloss smoothness → roughness (texture-aware) | `roughness.lowerBound/upperBound` or `roughness.factor` | Working |
| BoxCollider / SphereCollider / CapsuleCollider / MeshCollider | Editor*ShapeComponent + EditorShapeColliderComponent / EditorMeshColliderComponent | Working |
| Rigidbody dynamic + static-with-collider | EditorRigidBodyComponent / EditorStaticRigidBodyComponent | Working |
| Multiple colliders on one GO | Overflow → child entities `{Name}_Collider_N`, numbered in the order of the object's component list | Working |
| A scale by axis (or a mirror) on an object with objects below it | Carried down to each entity, as O3DE passes none of it on; a skew is reported | Working |
| A collider on a mirrored or stretched object | An entity of its own without the mirror; a second collider carries the object's scale | Working |
| Unity's built-in meshes (cube, quad, plane, cylinder, sphere, capsule), also as collision meshes | A model the converter writes (sphere and capsule on its own vertices) | Working |
| A mesh stored in a Unity `.asset` | A model the converter writes | Working |
| Several materials of one name on one FBX mesh | Renamed in the converted copy of the model, so each keeps a slot | Working |
| Nested prefab instances | Nested O3DE instance references | Working |
| Prefab override — transform | Tier 1 JSON patches | Working |
| Prefab override — material slot (`m_Materials.Array.data[N]`) | Tier 3 `assetHint` patches via project entity-map records | Working |
| Prefab override — `m_IsActive` | Entities start inactive and hidden, with everything below them | Working |
| Prefab override — another mesh (`m_Mesh`, a prefab variant) | Patch on the entity's model | Working |
| A placement stretched by axis | On the placed prefab's root; not on the objects below it | Partial |
| Prefab override — a light's range, intensity, colour, spot angles, shadows | Patches on the light's configuration | Working |
| Prefab override — added/removed components | Logged to coverage, not emitted | Pending |
| Lights — Directional / Point / Spot / Area | EditorDirectionalLightComponent / EditorAreaLightComponent (simple point, simple spot), Unity's range as an explicit radius | Working |
| Spot light direction | The light's own entity turned when it holds only the light, else a child entity (option) | Working |
| Scene → `<output>/<SceneName>/<SceneName>.prefab` | O3DE nested level convention | Working |
| Output layout | One folder per kind of asset, or the source's own folder structure (option) | Working |
| Unowned scene entities (physics + lights) | Same component pipeline as prefab processing | Working |
| Scene objects and placements added below an object of a placed prefab | The level's own, parented by path into the instance | Working |
| Terrain `.mat` → TerrainBaseMaterial | Per-material `.material` file emit | Working |
| Terrain heightmap extraction | — | Pending (F-7) |
| Terrain layers kept as `.terrainlayer` assets (Unity 2018.3 and later) | Read like the layers of an older terrain | Working |
| LOD groups | The best level kept, the others dropped | Partial |
| Skinned meshes, Animator, joints, particle systems, cameras, reflection probes | Logged to coverage, not emitted | Pending |
| Mesh pivot / coordinate rebake | — | [Known issue](#known-issues) |

---

## Adding a new source platform

The plugin contract is documented in [`platforms/README.md`](platforms/README.md).
The Unity reference is at [`platforms/unity/README.md`](platforms/unity/README.md).

Quick summary: a new plugin is `platforms/<engine>/<engine>_platform.py`
implementing the `SourcePlatform` ABC, plus a per-component-type
processor directory mirroring [`platforms/unity/components/`](platforms/unity/components/).
Estimated size: ~1500–2000 lines.

After authoring:

1. Add a `SourceEngine` enum entry in [`project_manager.py`](project_manager.py).
2. Register the platform in [`platforms/__init__.py`](platforms/__init__.py).
3. Mirror the test coverage under [`tests/`](tests/) (the shared
   harness picks up new files automatically).

Switching engines in the GUI is automatic — projects round-trip
between platform slots non-destructively.

---

## Known issues

- **Mesh coordinate / pivot rebake.** Unity internally rebakes mesh
  coordinates in a way that doesn't match the raw FBX. The converter
  applies the Unity → O3DE axis swap and composes a Y-up correction
  quaternion into every assetinfo's `CoordinateSystemRule`, but
  cannot correct for Unity's mesh-pivot bake. A Blender transform-bake
  pass exists (`tools/bake_fbx_transforms.py`) and can be invoked
  manually; integrating it into the pipeline is open.

- **Specular workflow + detail maps not yet mapped.** The default
  shader profile covers Standard, URP/Lit, URP/Simple Lit, and the
  MK4 Alien Fantasy Forest pack. Custom shaders need a per-shader
  profile entry; F-10 (Profile Editor) will surface this in the UI.

- **Smoothness alpha channel.** Unity's `_MetallicGlossMap` stores
  smoothness in the alpha channel; O3DE reads roughness directly.
  The bounds remap is mathematically correct but the texture content
  needs pre-inversion. Optional Pillow-backed re-bake exists
  (Config → Convert smoothness to roughness) but is off by default.

- **F-8 per-worker failure routing.** Stage workers throwing
  exceptions land as `processing_changed(False)` and don't propagate
  a failure signal to the orchestrator. The orchestrator stops
  dispatching on cancel; per-stage failure detection is deferred.

---

## Where the design lives

This project's design memory is captured under
[`.serena/memories/`](.serena/memories/) as **P/I/T artefacts** —
plan + working-documentation pairs per feature. The methodology is
described in [`AGENTICS_GUIDELINES.md`](AGENTICS_GUIDELINES.md) §3.

| Concern | Memory cluster |
|---|---|
| Conversion Project base | `.serena/memories/project_system/` |
| Parity harness, Unity bridge, command line, trace | `.serena/memories/parity_harness/` |
| Project scope + per-stage source override (F-2) | `.serena/memories/project_scope/` |
| Multi-scene marking + nested level output (F-3) | `.serena/memories/scene_marking/` |
| Scrubbed prefab marking (F-4) | `.serena/memories/prefab_marking/` |
| Mesh preprocessing + per-FBX overrides (F-5) | `.serena/memories/mesh_preprocessing/` |
| Material shader-mapping editor (F-6) | `.serena/memories/material_preprocessing/` |
| Orchestration + Pre-flight (F-8) | `.serena/memories/orchestration/` |
| Output propagation + state index + patch worker (F-9) | `.serena/memories/output_propagation/` |
| Platform abstraction refactor (5 phases + 7 follow-ups) | `.serena/memories/platform_abstraction/` |
| State management (sync-state engine) | `.serena/memories/state_management/` |
| UI reorganization (banner + dashboard + tab order) | `.serena/memories/ui_reorganization/` |
| Window chrome (frameless + title bar) | `.serena/memories/window_chrome/` |
| Profile editor (F-10 — stub) | `.serena/memories/profile_editor/` |

Each cluster's `working_documentation.md` is the right entry point
for understanding current state. The `<feature>_plan.md` files hold
locked design decisions with Q&A history.

---

## Co-development methodology

This codebase is co-developed with LLMs. The
[`AGENTICS_GUIDELINES.md`](AGENTICS_GUIDELINES.md) document captures
the working model:

- **P/I/T** — Plan (design-locked) / Implementation phases (with
  Done-when criteria) / Testing matrix.
- **Memory clustering** — every feature gets a folder under
  `.serena/memories/<feature>/`.
- **Verification at pivot points** — phase boundaries are stops where
  the user verifies behaviour before the next phase starts.
- **Q&A is sacred** — locked decisions append, never overwrite.

If you're an LLM, read that file first. If you're a human, it's a
useful map of how the codebase grew and where the design memory
lives.

---

## Goal: a conversion language

The long-term goal is to formalize a vocabulary that other
engine-pair converters can mirror:

| Concept | What it does | Engine-specific code |
|---|---|---|
| **Scope** | Pin the walking root of a source project | Choose a folder |
| **Mark** | Pick the subset to convert from scrubbed inventories | UI checklists |
| **Override** | Per-asset configuration knobs | Per-asset editors |
| **Profile** | Shared shader → materialtype + property remap library | Profile editor (F-10) |
| **Orchestrate** | Pre-flight check → staged execution | Mission Command |
| **Sync** | Track input hashes vs last-export per asset | State index |
| **Patch** | Surgically re-emit only affected artifacts | Patch worker |

Unity → O3DE is the first concrete implementation. The plugin
contract makes the second one (Unreal, Godot, Blender, …) a
self-contained `platforms/<engine>/` drop. The conversion language
is what survives when those plugins ship.

---

## Tests

Plain-Python assert-based test suite under [`tests/`](tests/). No
pytest dependency.

```bash
python tests/run_all.py                  # full suite (17 modules, 96 tests)
python tests/run_all.py unit             # only tests/unit/
python tests/run_all.py ui dirty         # filter by substring
python tests/unit/test_<name>.py         # single module
```

The harness sets `QT_QPA_PLATFORM=offscreen` and
`U2O_SKIP_CLOSE_PROMPT=1` so UI tests don't need a display server.
See [`tests/README.md`](tests/README.md) for the test-writing recipe.

---

## License

Public Domain. Use, fork, or strip-mine freely — the goal is a
conversion vocabulary that more developers can mirror, and license
friction would defeat that.

---

## Further reading

- [`AGENTICS_GUIDELINES.md`](AGENTICS_GUIDELINES.md) — co-development
  methodology (READ FIRST if you're an LLM).
- [`platforms/README.md`](platforms/README.md) — source-platform
  plugin contract.
- [`platforms/unity/README.md`](platforms/unity/README.md) — Unity
  reference plugin walkthrough.
- [`tests/README.md`](tests/README.md) — test suite layout + recipe.
- `.serena/memories/platform_abstraction/audit.md` — the platform-
  agnostic-core vs source-platform-surface map.
