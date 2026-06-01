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
        "physx_mesh":       False,
        "auto_center":      True,   # single-mesh FBX auto-center (toggle off to disable)
        "auto_rotation":    True,   # Y-up→Z-up +90°X auto-correction (toggle off to disable)
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
                         physx_specs: Optional[list] = None,
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

    When ``physx_specs`` is provided, one PhysX MeshGroup is written per
    spec into the same ``values[]`` array (the engine supports many PhysX
    groups in one assetinfo, exactly like the visual groups). Each spec is
    ``{"name": str, "node_paths": [str, ...], "convex": bool}`` and produces
    one ``.pxmesh`` product named after ``name``. This is the per-sub-mesh
    model (`mem:physx_mesh_collider/physx_mesh_collider_plan`): one FBX can
    yield several pxmesh products (T3 multi-LOD, T4 multi-submesh ``_COL``),
    and the assetinfo may carry only PhysX groups (a dedicated collider FBX
    with no visual entities). Convex specs emit ``"export method": 1``; the
    default is a triangle mesh.
    """
    import json as _json
    import uuid as _uuid

    # FBX up-axis detection lives in `integrated_asset_processor` for now
    # (FBX binary parsing, format-specific not platform-specific). Imported
    # at call time to avoid a circular import during module load.
    from integrated_asset_processor import (
        read_fbx_up_axis, compute_node_autocenters,
    )

    # Per-FBX up-axis drives the Y-up→Z-up rotation correction. FBX
    # GlobalSettings UpAxis: 1 = Y-up, 2 = Z-up. O3DE is Z-up, so a Y-up FBX
    # needs a +90° X correction (confirmed in-engine on the Office Cabinet:
    # Z-up desk imports upright, Y-up cabinet lands on its face without it).
    # This is the PER-FBX successor to the old GLOBAL auto-correction that
    # was removed for overcompensating — Z-up FBX (up_axis=2) gets nothing.
    up_axis = read_fbx_up_axis(fbx_dest_path)

    # F-9 — resolve the per-mesh settings chain (defaults + override).
    eff = _resolve_mesh_settings(mesh_settings, mesh_guid)
    user_rot   = list(eff.get("default_rotation") or [0.0, 0.0, 0.0])
    user_pos   = list(eff.get("default_position") or [0.0, 0.0, 0.0])
    zero_pos   = bool(eff.get("zero_position", True))
    has_user_rotation = any(abs(float(v)) > 1e-6 for v in user_rot)
    has_user_translation = any(abs(float(v)) > 1e-6 for v in user_pos)

    auto_rotation = bool(eff.get("auto_rotation", True))
    auto_center   = bool(eff.get("auto_center", True))

    # --- Shared rotation (per-FBX) ---
    # User's Euler degrees → quaternion, composed UNDER the Y-up correction.
    rot_quat = _euler_deg_to_quat(user_rot) if has_user_rotation else None
    if up_axis == 1 and auto_rotation:
        yup_corr = _euler_deg_to_quat([90.0, 0.0, 0.0])
        rot_quat = _quat_mul(rot_quat, yup_corr) if rot_quat else yup_corr
        log("    [Mesh] Y-up FBX → +90° X auto-correction applied.")

    # --- Translation (per-node auto-center) ---
    # Each mesh node is centred independently so its entity/instance transform
    # places it — reproducing Unity's node-local import. A single-mesh FBX gets
    # one center; a multi-mesh FBX (cabinet doors, drawer_C) gets one PER
    # sub-mesh. A user-authored default_position overrides ALL nodes (shared).
    # Gated by zero_position + auto_center toggle. Self-limiting: an
    # already-centred node yields ~0. See `mem:transform_truth/*`.
    shared_translation = ([float(v) for v in user_pos]
                          if (zero_pos and has_user_translation) else None)
    # Per-node auto-center, calibrated for BOTH up-axes (compute_node_autocenters
    # applies the Z-up / Y-up formula). A user-authored default_position
    # overrides all nodes (shared). Gated by zero_position + the auto_center
    # toggle. See `mem:transform_truth/*`.
    node_autocenters = ({} if (shared_translation is not None
                               or not (zero_pos and auto_center))
                        else compute_node_autocenters(fbx_dest_path))
    if node_autocenters:
        log(f"    [Mesh] per-node auto-center → {node_autocenters}")

    def rule_for(node_path: str) -> dict:
        """Build this node's CoordinateSystemRule: shared rotation + the node's
        own auto-center translation (or the shared user override)."""
        rule = {"$type": "CoordinateSystemRule", "useAdvancedData": True}
        if rot_quat is not None:
            rule["rotation"] = rot_quat
        leaf = node_path.split(".")[-1]
        tr = (shared_translation if shared_translation is not None
              else node_autocenters.get(leaf))
        if tr and any(abs(float(v)) > 1e-6 for v in tr):
            rule["translation"] = [float(v) for v in tr]
        return rule

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
                    rule_for(node_path),
                    {"$type": "{6E796AC8-1484-4909-860A-6D3F22A7346F} LodRule"}
                ]
            },
            "id": "{" + str(_uuid.uuid4()).upper() + "}"
        })

    # -------------------------------------------------------------------------
    # PHYSX MESH GROUPS  ({5B03C8E6...} MeshGroup)
    # One group per spec — produces a .pxmesh physics asset whose product name
    # is "{group name}.fbx.pxmesh" (O3DE names the product after the group, so
    # distinct per-sub-mesh names keep products distinct and the
    # EditorMeshColliderComponent hint resolves). Many groups may share one
    # assetinfo (multi-LOD / multi-submesh _COL FBX).
    #
    # "export method" enum: 0=TriMesh, 1=Convex, 2=Primitive. Omitting it
    # defaults to TriMesh (a concave/static collision mesh) — matches a Unity
    # MeshCollider with m_Convex=0 and O3DE's own minimal serialization of a
    # default triangle group. Convex colliders (m_Convex=1) carry
    # "export method": 1; asset params are left at engine defaults in both
    # cases. See `mem:physx_mesh_collider/physx_mesh_collider_plan` for the
    # engine-source verification of all of this.
    # -------------------------------------------------------------------------
    if physx_specs:
        for spec in physx_specs:
            node_paths = [p for p in (spec.get("node_paths") or []) if p]
            if not node_paths:
                continue
            is_convex = bool(spec.get("convex", False))
            name = spec.get("name") or fbx_stem
            unselected = [p for p in all_node_paths if p not in node_paths]
            unselected.append("RootNode")

            group = {
                "$type": "{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45B} MeshGroup",
                "id": "{" + str(_uuid.uuid4()).upper() + "}",
                "name": name,
                "NodeSelectionList": {
                    "selectedNodes": node_paths,
                    "unselectedNodes": unselected
                },
                "PhysicsMaterialSlots": {
                    "Slots": [{"Name": node_paths[0].split(".")[-1]}]
                },
            }
            if is_convex:
                group["export method"] = 1  # MeshExportMethod::Convex
            # The collision mesh gets the per-node rotation; its translation is
            # the explicit render-alignment when the producer supplied one
            # (dedicated _COL FBX), else the node's own auto-center. Identity
            # rule omitted.
            phys_rule = rule_for(node_paths[0])
            spec_tr = spec.get("translation")
            if spec_tr is not None:
                if any(abs(float(v)) > 1e-6 for v in spec_tr):
                    phys_rule["translation"] = [float(v) for v in spec_tr]
                else:
                    phys_rule.pop("translation", None)
            if "rotation" in phys_rule or "translation" in phys_rule:
                group["rules"] = {"rules": [phys_rule]}

            groups.append(group)

        log(f"    [Mesh] Added {len(physx_specs)} PhysX MeshGroup(s)")

    sidecar = Path(str(fbx_dest_path) + ".assetinfo")
    try:
        with open(sidecar, 'w', encoding='utf-8') as f:
            _json.dump({"values": groups}, f, indent=4)
        log(f"    [Mesh] .assetinfo written — {len(groups)} group(s) ({sidecar.name})")
    except Exception as e:
        log(f"    [Mesh] WARNING: Could not write .assetinfo: {e}")
