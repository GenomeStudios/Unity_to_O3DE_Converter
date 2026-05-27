---
name: profile-editor-plan
description: F-10 — profile authoring UI. Builds on F-9's profile schema by adding a texture-map / property-map editor, profile duplication / creation / deletion, and a profile preview surface.
metadata:
  type: project
---

# F-10 Shader Profile Editor — Plan (stub)

Roadmap insertion point: after F-9. Pre-empts the original F-7
(Terrain heightmap expansion v1) in priority because F-9's profile
seam is unusable for divergent shaders without an authoring surface.

Linked: [[output-propagation-plan]] (F-9 — defines the profile
schema F-10 edits), [[material-preprocessing-plan]] (F-6 — original
shader-mappings work).

## Why this exists

F-9 introduces the shader profile data structure but ships exactly
one profile (`Default — Anything to PBR`) that captures the legacy
hard-coded behavior. Users have no way to:

- Create a divergent profile (e.g. "Alien Fantasy Forest MK4")
  without hand-editing the project file's JSON.
- Inspect what the default profile actually does (texture remap +
  property remap + ignore list).
- Duplicate a profile as a starting point.
- Preview which Unity properties a profile would route where for a
  given material.

F-10 is the UI feature that closes that gap.

## Goal (high-level — full plan to be authored when picked up)

A profile editor dialog/tab. For a selected profile:

- Header: name, description, target materialtype (uses F-9's
  `resolve_materialtype_path` for display).
- Texture map table: rows of `unity_prop → o3de_slot → transform`.
  Add / remove / edit rows.
- Property map table: rows of `unity_prop → o3de_target → transform`.
- Ignore-unmapped list editor.
- Special-rules toggles (e.g. `metallic_gloss_smoothness_to_roughness`).
- Live preview: pick a material from the inventory → show which
  source properties / textures route where under this profile, which
  get ignored, which fall outside.

Profile management:
- Create new profile (blank or duplicate from existing).
- Rename, delete (with guard against deleting profiles in active
  use — must reassign affected `shader_mappings` entries first).
- Mark a profile as "built-in / read-only" so the default catch-all
  can't be edited destructively (user can duplicate it instead).

Cross-project profile library (optional, scoped to v2):
- `<repo>/shader_profiles.json` library that lives outside any
  single project. Projects import profiles from the library or
  shadow them locally.

## Open questions (to resolve at pick-up time)

- Where does the editor live — its own tab, a section under
  Materials, or a popout dialog?
- Property-map "transform" — closed enum or a small DSL? F-9 ships
  with a closed enum (`passthrough`, `invert`, `invert_alpha`,
  `channel_r/g/b/a`); a DSL widens the door but increases editor
  complexity and the worker's interpreter surface.
- Profile library: per-install global vs project-scoped only?
- How does deletion interact with `shader_mappings` entries that
  reference the deleted profile? Auto-migrate to default, or block?

## Out of scope (always)

- Authoring of new `.materialtype` files. Users supply existing ones.
- Auto-generation of profiles from shader source inspection. Future
  ML / heuristic territory.
- Profile-level dependency graphs ("profile A inherits from B").
  Inheritance complicates the worker and the editor; flat list only.

## Status

**Stub only as of 2026-05-27.** Picked up after F-9 ships and the
need for divergent profiles surfaces in real conversion work.
