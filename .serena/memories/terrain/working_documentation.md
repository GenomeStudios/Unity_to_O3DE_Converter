---
name: terrain-working-doc
description: Living status log for the Terrain importer tab. Newest entries on top. Tracks shipped pieces, regressions, decisions in flight, and pending items.
metadata:
  type: project
---

# Terrain Tab — Working Documentation

Newest entries on top. Links back to [[terrain-tab-plan]].

## 2026-05-25 — I.1 written, I.2/I.3 implementation starting
- Plan locked per user answers (see [[terrain-tab-plan]]).
- About to author `terrain_material_processor.py` and patch `main_app.py` with the new `TerrainTab` between Scene Converter and Config.
- Property-name assumption (TerrainBaseMaterial accepts StandardPBR property paths) is unverified — first user run will tell us if `baseColor.textureMap` / `normal.textureMap` etc. need remapping. Record any divergence as a follow-up entry here.

## Pending / not yet shipped
- Behaviour proofs T-3 and T-4 await user verification after the code lands.
- No prefab-scanning, no surface-tag metadata, no terrain-component emission — see plan "Out of scope" section.
