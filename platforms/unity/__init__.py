"""
=============================================================================
UNITY SOURCE-PLATFORM PLUGIN
=============================================================================

Reference implementation of the ``SourcePlatform`` Protocol (defined in
``platforms.base`` after Phase B). The Unity plugin parses Unity asset
formats (.prefab / .unity scene / .mat / .shader) and provides the
extraction primitives the platform-agnostic worker pipeline consumes.

Submodules (lands across Phase A sub-steps):
    asset_database.py      ← AssetDatabase (GUID index, .mat parser)
    material.py            ← default profile + extraction body
    prefab.py              ← prefab / scene YAML walkers
    shader.py              ← .shader file → name resolution
    coordinates.py         ← Y-up → Z-up conversion constants
    components/            ← per-component-type processors

Phase A is mechanical-move only. The actual SourcePlatform-conformant
class lands in Phase B.
"""
