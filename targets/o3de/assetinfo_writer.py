"""
=============================================================================
O3DE .assetinfo WRITER  (targets.o3de.assetinfo_writer)
=============================================================================

Writes O3DE ``<fbx>.assetinfo`` sidecars — one MeshGroup per entity, with
optional PhysX MeshGroups for entities flagged as colliders. Composes a
``CoordinateSystemRule`` from the platform's coordinate-correction
quaternion (default: Unity's Y-up → O3DE Z-up) layered with the per-mesh
override transform from the project's F-9 mesh settings.

Phase A *mechanical move* from ``integrated_asset_processor`` — behaviour
is byte-identical. Re-exported from there for backwards compatibility.

Layered design (Phase B will formalise):
  - Quaternion math (`_euler_deg_to_quat`, `_quat_mul`) is pure;
    engine-pair-neutral. Lives here for now since the only consumer is
    this writer.
  - `Y_UP_ROTATION` is Unity-specific. Stays here in Phase A; Phase B
    moves it to `platforms/unity/coordinates.py` and the writer takes
    the correction quaternion as a parameter.
  - `_resolve_mesh_settings` reads the F-9 mesh-settings chain
    (defaults + per-mesh override). PAC — stays here as part of the
    writer's calling convention.
"""

import math
from pathlib import Path
from typing import Dict, Optional


# Unity Y-up → O3DE Z-up correction quaternion. The canonical home is
# now ``platforms.unity.coordinates.UNITY_Y_UP_TO_O3DE_Z_UP_QUAT``
# (follow-up: item 5). Re-exported here so callers that imported
# ``Y_UP_ROTATION`` from the writer pre-refactor keep working.
#
# The writer's ``write_fbx_assetinfo`` now accepts a per-call
# ``correction_quat`` parameter. When provided, that quaternion is used
# instead of this default — the path third-party platforms take to
# supply their own correction.
from platforms.unity.coordinates import (  # noqa: E402
    UNITY_Y_UP_TO_O3DE_Z_UP_QUAT as Y_UP_ROTATION,
)


# ---------------------------------------------------------------------------
# Quaternion math
# ---------------------------------------------------------------------------

def _euler_deg_to_quat(deg_xyz) -> list:
    """Convert Euler XYZ degrees to a quaternion [x, y, z, w] using the
    intrinsic ZYX rotation convention (same as Unity's TRS Quaternion.Euler).
    Returns the identity for an all-zero input."""
    rx = math.radians(float(deg_xyz[0] or 0.0))
    ry = math.radians(float(deg_xyz[1] or 0.0))
    rz = math.radians(float(deg_xyz[2] or 0.0))
    cr, cp, cy = math.cos(rx * 0.5), math.cos(ry * 0.5), math.cos(rz * 0.5)
    sr, sp, sy = math.sin(rx * 0.5), math.sin(ry * 0.5), math.sin(rz * 0.5)
    return [
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ]


def _quat_mul(q1, q2) -> list:
    """Hamilton-product quaternion multiplication: result = q1 ⊗ q2."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return [
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
    ]


# ---------------------------------------------------------------------------
# Per-mesh settings resolution (F-9 chain)
# ---------------------------------------------------------------------------

def _resolve_mesh_settings(mesh_settings: Optional[Dict],
                            mesh_guid: Optional[str]) -> dict:
    """F-9 mesh settings chain — `overrides[mesh_guid]` (partial) merged on
    top of `defaults`. Returns a fully-populated dict carrying the three
    knobs the assetinfo writer cares about. When no settings supplied,
    returns the conservative defaults (zero position, no rotation) so the
    legacy call path keeps writing the same assetinfo content."""
    defaults = {
        "zero_position":    True,
        "default_position": [0.0, 0.0, 0.0],
        "default_rotation": [0.0, 0.0, 0.0],
    }
    if not mesh_settings:
        return defaults
    base = dict(defaults)
    base.update(mesh_settings.get("defaults") or {})
    override = ((mesh_settings.get("overrides") or {}).get(mesh_guid)
                if mesh_guid else None)
    if isinstance(override, dict):
        base.update(override)
    return base


# ---------------------------------------------------------------------------
# .assetinfo writer
# ---------------------------------------------------------------------------

def write_fbx_assetinfo(fbx_dest_path: Path, fbx_stem: str,
                         entity_node_map: dict, log=print,
                         collider_entity_node_map: dict = None,
                         mesh_settings: Optional[Dict] = None,
                         mesh_guid: Optional[str] = None,
                         *,
                         correction_quat: Optional[list] = None) -> None:
    """Write an O3DE .assetinfo with one named MeshGroup per mesh entity.

    Group name format: "{fbx_stem}-{entity_name}"  e.g. "Closet_A-Glass_L"
    O3DE lowercases the output: closet_a-glass_l.fbx.azmodel

    Each group selects exactly its FBX node; all other mesh nodes are
    unselected. Rules mirror O3DE's auto-generated defaults:
    StaticMeshAdvancedRule (vertex color Col0), MaterialRule,
    CoordinateSystemRule (useAdvancedData=true), and LodRule.

    Rotation/translation are written **directly from mesh_settings**.
    The earlier behaviour composed the user's rotation with a Y-up→Z-up
    correction quaternion when the source FBX was Y-up; that legacy
    auto-correction has been removed (2026-05-27). With per-mesh
    defaults + overrides now part of the workflow, the user authors
    whatever rotation they need explicitly: ``default_rotation``
    [90, 0, 0] writes a 90°-X rotation, full stop. ``correction_quat``
    is retained as a parameter for plugin authors who want to opt in
    to a different default composition later but it is **not applied
    by the writer**.

    ``default_position`` is a metric translation — written into the
    CoordinateSystemRule only when ``zero_position=True`` (the
    documented "zero on import, then offset by default_position"
    behaviour). When ``zero_position=False`` no translation field is
    emitted, so the source FBX node transform passes through.

    When collider_entity_node_map is provided, one PhysX convex
    MeshGroup is also written per collider entity, targeting the parent
    node of the visual mesh node. This produces the .pxmesh file that
    EditorMeshColliderComponent references.
    """
    import json as _json
    import uuid as _uuid

    # FBX up-axis detection lives in `integrated_asset_processor` for now
    # (FBX binary parsing, format-specific not platform-specific). Imported
    # at call time to avoid a circular import during module load.
    from integrated_asset_processor import read_fbx_up_axis

    # Up-axis is logged for visibility but no longer drives an auto
    # correction. The user authors rotation explicitly via mesh_settings.
    up_axis = read_fbx_up_axis(fbx_dest_path)
    if up_axis == 1:
        log("    [Mesh] Y-up FBX detected (informational — no auto-correction "
            "is applied; set default_rotation in mesh settings if needed).")

    # F-9 — resolve the per-mesh settings chain (defaults + override).
    eff = _resolve_mesh_settings(mesh_settings, mesh_guid)
    user_rot   = list(eff.get("default_rotation") or [0.0, 0.0, 0.0])
    user_pos   = list(eff.get("default_position") or [0.0, 0.0, 0.0])
    zero_pos   = bool(eff.get("zero_position", True))
    has_user_rotation = any(abs(float(v)) > 1e-6 for v in user_rot)
    has_user_translation = any(abs(float(v)) > 1e-6 for v in user_pos)

    coordinate_rule = {"$type": "CoordinateSystemRule", "useAdvancedData": True}
    # Direct mapping: the user's Euler degrees become the rule quaternion.
    if has_user_rotation:
        coordinate_rule["rotation"] = _euler_deg_to_quat(user_rot)
    # Translation only when zero_position=True. zero_position=False explicitly
    # opts out of having the assetinfo touch position at all.
    if zero_pos and has_user_translation:
        coordinate_rule["translation"] = [float(v) for v in user_pos]

    all_node_paths = list(entity_node_map.values())
    groups = []

    # -------------------------------------------------------------------------
    # VISUAL MESH GROUPS  ({07B356B7...} MeshGroup)
    # One group per entity — produces the .azmodel render asset.
    # -------------------------------------------------------------------------
    for entity_name, node_path in entity_node_map.items():
        group_name = f"{fbx_stem}-{entity_name}"
        unselected = [p for p in all_node_paths if p != node_path]
        groups.append({
            "$type": "{07B356B7-3635-40B5-878A-FAC4EFD5AD86} MeshGroup",
            "name": group_name,
            "nodeSelectionList": {
                "selectedNodes": ["RootNode", node_path],
                "unselectedNodes": unselected
            },
            "rules": {
                "rules": [
                    {"$type": "StaticMeshAdvancedRule", "vertexColorStreamName": "Col0"},
                    {"$type": "MaterialRule"},
                    coordinate_rule,
                    {"$type": "{6E796AC8-1484-4909-860A-6D3F22A7346F} LodRule"}
                ]
            },
            "id": "{" + str(_uuid.uuid4()).upper() + "}"
        })

    # -------------------------------------------------------------------------
    # PHYSX MESH GROUPS  ({5B03C8E6...} MeshGroup)
    # One convex group per collider entity — produces the .pxmesh physics asset.
    # Targets the parent node of the visual mesh node so all geometry is captured.
    # -------------------------------------------------------------------------
    if collider_entity_node_map:
        # PhysX collider lives in the same mesh-local space as the visual
        # group, so the same composed rotation + translation applies.
        physx_coord_rule = dict(coordinate_rule)

        for entity_name, node_path in collider_entity_node_map.items():
            parts = node_path.split(".")
            parent_path   = ".".join(parts[:-1]) if len(parts) > 1 else node_path
            mesh_node_name = parts[-1]

            groups.append({
                "$type": "{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45B} MeshGroup",
                "id": "{" + str(_uuid.uuid4()).upper() + "}",
                "name": f"{fbx_stem}-{entity_name}",
                "NodeSelectionList": {
                    "selectedNodes": ["RootNode", parent_path],
                    "unselectedNodes": [{}]
                },
                "export method": 1,
                "ConvexAssetParams": {
                    "Use16bitIndices": True,
                    "CheckZeroAreaTriangles": True
                },
                "PhysicsMaterialSlots": {
                    "Slots": [{"Name": mesh_node_name}]
                },
                "rules": {
                    "rules": [physx_coord_rule]
                }
            })

        log(f"    [Mesh] Added {len(collider_entity_node_map)} PhysX MeshGroup(s)")

    sidecar = Path(str(fbx_dest_path) + ".assetinfo")
    try:
        with open(sidecar, 'w', encoding='utf-8') as f:
            _json.dump({"values": groups}, f, indent=4)
        log(f"    [Mesh] .assetinfo written — {len(groups)} group(s) ({sidecar.name})")
    except Exception as e:
        log(f"    [Mesh] WARNING: Could not write .assetinfo: {e}")
