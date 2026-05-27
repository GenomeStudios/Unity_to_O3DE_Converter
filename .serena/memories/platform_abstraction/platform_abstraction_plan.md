---
name: platform-abstraction-plan
description: Design + locked decisions for the source-platform plugin contract. References the audit; locks down the sequencing for the five-phase refactor that formalises the Unity-as-plugin boundary.
metadata:
  type: project
---

# Platform Abstraction — Plan

References: [[platform-abstraction-audit]] (the full cartography),
[[material-component-label-resolution-plan]] (the prototype plugin
system), [[output-propagation-plan]] (F-9 — already established the
shader-profile abstraction).

## Goal

Take the existing converter — a Unity-coupled tool with a few
incidentally-extensible seams (ComponentProcessor, shader profiles) —
and turn it into a platform-agnostic core with Unity as the
reference plugin. Third-party developers can then ship `platforms/<engine>/`
modules to add Unreal / Godot / Blender / etc. without touching core.

**The audit memo locks the cartography.** This plan locks the
sequencing and the open questions a future-me has to answer at each
phase boundary.

## Resolved Decisions (Q&A)

**Q1 — Does the user create non-Unity plugins?**
A: No. The user explicitly stated: "We will not be making non-Unity
tech, but we want to enable other developers to parse our work and
records to implement the other platforms." Scope is the **abstraction**
plus the Unity reference plugin. Non-Unity plugins are an external
contribution.

**Q2 — When platform switches, what survives?**
A: Per-platform `stages` and `outputs` are namespaced and preserved.
Project-global fields (name, notes, scope_root, preflight_acks) stay
shared. Implementation: `stages_by_platform[plat][stage_key]` instead
of `stages[stage_key]`. Same for `outputs_by_platform`.

**Q3 — Migration of existing (Unity-only) projects?**
A: One-shot in `Project.from_json`. Flat `stages`/`outputs` move into
`stages_by_platform["unity"]` / `outputs_by_platform["unity"]`; set
`active_platform = "unity"`. Same pattern as the F-9
`target_materialtype → profile` migration.

**Q4 — Where do platform plugins live on disk?**
A: `platforms/<engine_name>/` directory. `platforms/unity/` ships as
the reference; third-party plugins drop alongside.
- Discovery: explicit import via `register()` in
  `platforms/__init__.py`. **Not auto-discovery** — explicit imports
  make the dependency graph readable and avoid silent failures from
  plugins crashing at import time.

**Q5 — Do component processors stay global or move per-platform?**
A: **Per-platform.** The current `components/` directory is Unity-typed
(`HANDLES = ["MeshRenderer", ...]`). After the move it lives at
`platforms/unity/components/`. Each platform plugin ships its own
component set. The shared O3DE-emit side (e.g. EditorMaterialComponent
writing) lives at `targets/o3de/` since that's target-platform code,
not source-platform.

**Q6 — Does the project file format break?**
A: No. The schema migration is forward-compatible. Existing
`.u2oproj.json` files load fine; first save under the new schema rewrites
into the namespaced shape. SCHEMA_VERSION bumps from 2 to 3. The
deep-merge load layer ensures missing keys get defaults.

**Q7 — Profile library scope: project-local or platform-wide?**
A: **Platform-wide defaults, project-local overrides.** The platform
plugin ships `default_profiles()` which seeds new projects. A project
can edit / add profiles; those are stored in the project file and
override the platform defaults. F-10's profile editor operates against
this layered view.

**Q8 — Does `IntegratedAssetProcessor` get renamed?**
A: Yes — see Phase 5.1 of the audit. The class today does both the
platform-agnostic orchestration (state index, patch loop) AND the
Unity-specific parsing. After the split:
- `core/asset_pipeline.py::AssetPipeline` — the orchestration half.
  Takes a `SourcePlatform`, drives parse / extract / emit.
- `platforms/unity/asset_database.py::UnityAssetDatabase` — the GUID
  index + parsers.
- `targets/o3de/...` — the emitters.

**Q9 — Do existing tabs (PrefabProcessorTab, MaterialTab, ...) become
platform-aware?**
A: Minimal change. Tabs continue reading from
`project.stage_settings(key)` which now routes through
`stages_by_platform[active_platform]`. The tab UIs don't know they
exist in a multi-platform world unless they choose to display
platform-specific copy (which is a per-plugin opt-in via the
`SourcePlatform.tab_copy_overrides()` hook — deferred).

**Q10 — How do non-Unity developers learn the contract?**
A: Three sources:
1. `platforms/base.py::SourcePlatform` Protocol with full docstrings.
2. `platforms/unity/` reference implementation (~1500 lines after
   the move).
3. This plan + the audit memo, kept current with the contract shape.

**Q11 — Cancel / failure-routing in the new world?**
A: Same as F-8 — orchestrator-level Cancel drops queued stages;
mid-stage Cancel needs worker cooperation. Per-platform workers
inherit the same pattern. Out of scope here.

## Phase plan

Each phase is its own plan + working-doc pair to be written when the
phase begins. The five-phase outline:

### Phase A — Mechanical move (no behavior change)

`platforms/unity/` directory created; AssetDatabase + extraction +
parsers + shader resolver moved in. `targets/o3de/` directory holds
the emitters. Imports updated. **F-9 verification re-runs — must
remain green.**

### Phase B — Define the contract

`platforms/base.py::SourcePlatform` Protocol. Neutral data shapes in
`platforms/types.py`. `UnityPlatform` class wraps the moved modules
into a single conformant object. Verification: isinstance check
against the Protocol + a no-op smoke that loads UnityPlatform and
calls one method.

### Phase C — Wire the registry

`platforms/__init__.py::PLATFORM_REGISTRY` + `register()`.
`UnityPlatform` registered at module import. `AssetPipeline.__init__`
accepts a platform; current call sites route via the project's
`active_platform`. F-9 verification re-runs.

### Phase D — Project schema migration

`Project.stages_by_platform` / `Project.outputs_by_platform` /
`Project.active_platform`. `from_json` migrates legacy flat shape.
`stage_settings(key)`, `update_stage(key, ...)`, `update_outputs(key,
...)` route through the active platform.
Verification: a stash-and-switch test — load a project, switch
active_platform, switch back, assert original data intact.

### Phase E — Switch UX

Engine dropdown becomes functional. Per-tab refresh on platform
change. Toast confirming the switch.
Verification: GUI smoke — open a project, change engine via the
dropdown, confirm Material tab inventory empties (because the new
platform's outputs.asset_processor.material_metadata is empty),
switch back, confirm Material tab inventory returns.

## Testing matrix

| Phase | ID  | Proof |
|-------|-----|-------|
| A     | T-1 | All F-9 / F-8 verification scripts still green |
| A     | T-2 | `from platforms.unity import UnityPlatform` works |
| B     | T-3 | `isinstance(UnityPlatform(), SourcePlatform)` True |
| B     | T-4 | UnityPlatform.default_profiles() returns at least the catch-all |
| C     | T-5 | AssetPipeline emits the same `.material` content with platform threaded vs without |
| C     | T-6 | Component dispatch consults `platform.component_processors()` |
| D     | T-7 | Legacy flat `stages/outputs` migrate to namespaced shape on load |
| D     | T-8 | `project.stage_settings("material_processor")` reads from `stages_by_platform[active_platform]` |
| D     | T-9 | Switching active_platform preserves prior platform's data |
| E     | T-10| Dropdown switch fires `project_changed`; every tab refreshes |
| E     | T-11| Switch-back-and-forth keeps both platforms' state intact |

## Out of scope (deliberately)

- Authoring non-Unity plugins.
- Replacing O3DE as the output target. The `targets/o3de/` split is the
  prep; multi-output is a separate plan.
- Live engine bridges (Unity/Unreal IPC).
- Per-platform UI theming or copy overrides.
- A plugin marketplace / loader UI. Plugins are explicit imports.

## Notes for future iterations

- Once Phase E ships, F-7 (Terrain heightmap v1) becomes platform-aware
  trivially — it adds a `scrub_terrain(scope_root)` implementation to
  the Unity plugin without core changes.
- F-10 (Profile editor) targets the post-Phase-D schema since profiles
  live under per-platform stage settings.
- If a future plugin needs to emit non-O3DE targets, the
  `targets/<engine>/` directory is the prep work that makes that
  possible without re-architecting.
