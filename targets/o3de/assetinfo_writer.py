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
# Small matrix arithmetic: lives in ``matrix3``. The names below are the ones
# this module and its tests have always used.
# ---------------------------------------------------------------------------

from matrix3 import (  # noqa: E402
    IDENTITY as _IDENTITY,
    euler_xyz_matrix as _euler_xyz_matrix,
    is_identity as _is_identity,
    mat_mul as _mat_mul,
    mat_vec as _mat_vec,
    matrix_to_quat as _matrix_to_quat,
    quat_to_matrix as _quat_to_matrix,
)


# ---------------------------------------------------------------------------
# The import rule a mesh node needs to match the source engine's import
# ---------------------------------------------------------------------------

# Unity negates X when it imports an FBX; a Unity point (x, y, z) is the O3DE
# point (x, z, y). The two together are one turn: (x, y, z) -> (-x, z, y).
_UNITY_MESH_TO_O3DE = [[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]]

# How the file's raw vertices relate to the vertices O3DE's scene pipeline
# holds before any rule, by the file's up axis (raw = turn * pipeline).
# Measured on the Office pack, 255 meshes; see mem:parity_fixes/plan D.12.
_RAW_FROM_PIPELINE = {
    1: _UNITY_MESH_TO_O3DE,                                         # Y-up file
    2: [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]],        # Z-up file: half turn about Z
}


def source_import_rule(facts: dict, node_name: str, *,
                       axis_rule: bool = True, geometric_offset: bool = True):
    """The rotation (3x3) and translation (metres) of the coordinate rule
    that makes O3DE's model of one mesh node equal the mesh Unity imports
    from the same node.

    Unity's mesh is the node's own geometry with the node's **geometric
    transform** baked in and X negated. O3DE's scene pipeline, given an
    advanced coordinate rule, applies only that rule to the node's vertices
    (``SceneAPI::Utilities::DetermineWorldTransform``): neither the node's
    place in the file nor its geometric transform enters. So the rule is

        rule = U * G * K

    with ``G`` the geometric transform, ``U`` the turn from Unity's mesh
    space to O3DE's, and ``K`` the turn from the pipeline's vertices back to
    the file's raw ones, which depends only on the file's up axis.

    ``facts`` comes from ``fbx_reader.read_import_facts``. With an up axis
    the table does not know, or a node the file does not have, the rule is
    the identity. ``axis_rule`` and ``geometric_offset`` switch the rotation
    and the translation off separately."""
    node = (facts.get("nodes") or {}).get(node_name)
    raw_from_pipeline = _RAW_FROM_PIPELINE.get(facts.get("up_axis"))
    if node is None or raw_from_pipeline is None:
        return _IDENTITY, [0.0, 0.0, 0.0]

    rotation = _IDENTITY
    if axis_rule:
        geometric_rotation = _euler_xyz_matrix(node["geometric_rotation"])
        rotation = _mat_mul(_mat_mul(_UNITY_MESH_TO_O3DE, geometric_rotation), raw_from_pipeline)

    translation = [0.0, 0.0, 0.0]
    if geometric_offset:
        unit = float(facts.get("unit_to_metres") or 0.01)
        translation = _mat_vec(_UNITY_MESH_TO_O3DE, [value * unit for value in node["geometric_translation"]])
    return rotation, translation


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
        # The import rule read from the file (see `source_import_rule`). The
        # two keys keep their names so saved projects load unchanged.
        "auto_center":      True,   # the node's geometric offset, as the rule's translation
        "auto_rotation":    True,   # the axis and geometric turn, as the rule's rotation
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
                         correction_quat: Optional[list] = None,
                         trace=None) -> None:
    """Write an O3DE .assetinfo with one named MeshGroup per mesh node shown.

    ``entity_node_map`` is ``{name: node path}``; the converter keys it by
    the node's own name, so a group is the same whichever prefab asks for it.
    Group name format: "{fbx_stem}-{name}"  e.g. "Closet_A-Glass_L"
    O3DE lowercases the output: closet_a-glass_l.fbx.azmodel

    Each group selects exactly its FBX node and unselects every other mesh
    node of the file. A node that a selection does not name follows its
    parent, so the ones no group shows have to be unselected too.
    Rules mirror O3DE's auto-generated defaults:
    StaticMeshAdvancedRule (vertex color Col0), MaterialRule,
    CoordinateSystemRule (useAdvancedData=true), and LodRule.

    Each group's CoordinateSystemRule is the rule its node needs to match
    the source engine's import (``source_import_rule``: the axis turn and
    the node's geometric transform, read from the file), with the user's
    ``default_rotation`` and ``default_position`` applied after it.
    ``auto_rotation`` and ``auto_center`` switch the file-derived rotation
    and translation off; ``default_position`` is applied when
    ``zero_position`` is set.

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

    from fbx_reader import mesh_node_names, read_import_facts

    # What the file says: its up axis, its unit, each node's geometric transform.
    facts = read_import_facts(fbx_dest_path)
    up_axis = facts["up_axis"]

    # F-9 — resolve the per-mesh settings chain (defaults + override).
    eff = _resolve_mesh_settings(mesh_settings, mesh_guid)
    user_rot   = list(eff.get("default_rotation") or [0.0, 0.0, 0.0])
    user_pos   = list(eff.get("default_position") or [0.0, 0.0, 0.0])
    zero_pos   = bool(eff.get("zero_position", True))
    has_user_rotation = any(abs(float(v)) > 1e-6 for v in user_rot)
    has_user_translation = zero_pos and any(abs(float(v)) > 1e-6 for v in user_pos)

    axis_rule        = bool(eff.get("auto_rotation", True))
    geometric_offset = bool(eff.get("auto_center", True))

    # The user's own rotation and position come after the file's rule.
    user_matrix = _quat_to_matrix(_euler_deg_to_quat(user_rot)) if has_user_rotation else _IDENTITY
    user_translation = [float(v) for v in user_pos] if has_user_translation else [0.0, 0.0, 0.0]

    # For the conversion trace: the file-derived translation of each node.
    node_translations: Dict[str, list] = {}

    def rule_for(node_path: str) -> dict:
        """Build this node's CoordinateSystemRule: the file's rule for the
        node, then the user's rotation and position."""
        leaf = node_path.split(".")[-1]
        rotation, translation = source_import_rule(
            facts, leaf, axis_rule=axis_rule, geometric_offset=geometric_offset)
        if any(abs(v) > 1e-6 for v in translation):
            node_translations[leaf] = [round(v, 6) for v in translation]

        rotation = _mat_mul(user_matrix, rotation)
        translation = [a + b for a, b in zip(_mat_vec(user_matrix, translation), user_translation)]

        rule = {"$type": "CoordinateSystemRule", "useAdvancedData": True}
        if not _is_identity(rotation):
            rule["rotation"] = _matrix_to_quat(rotation)
        if any(abs(v) > 1e-6 for v in translation):
            rule["translation"] = [round(float(v), 6) for v in translation]
        return rule

    if up_axis not in _RAW_FROM_PIPELINE and (axis_rule or geometric_offset):
        log(f"    [Mesh] up axis {up_axis} of {fbx_dest_path.name} is not known to the import rule: "
            f"no rule written for it.")

    # Every mesh node of the file, and whatever else a group names (a file
    # this reader cannot read has no nodes of its own to offer).
    all_node_paths = list(dict.fromkeys(
        [facts["nodes"][name]["path"] for name in mesh_node_names(facts)] + list(entity_node_map.values())))
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
                # The top of the graph, then the node itself. The top is
                # "RootNode" in an FBX; an OBJ's is named after the file.
                "selectedNodes": list(dict.fromkeys([node_path.split(".")[0], node_path])),
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
            # A collision mesh is imported like a render mesh: its own node's
            # rule. Unity places it by the object's transform, as the entity's
            # transform does here. The rule is written also when it turns and
            # moves nothing: a group without an advanced rule gets the node's
            # place in the file baked into its vertices, and a collision file
            # keeps its node wherever the artist left it (20 m off, in the
            # Office pack).
            group["rules"] = {"rules": [rule_for(node_paths[0])]}

            groups.append(group)

        log(f"    [Mesh] Added {len(physx_specs)} PhysX MeshGroup(s)")

    sidecar = Path(str(fbx_dest_path) + ".assetinfo")
    try:
        with open(sidecar, 'w', encoding='utf-8') as f:
            _json.dump({"values": groups}, f, indent=4)
        log(f"    [Mesh] .assetinfo written — {len(groups)} group(s) ({sidecar.name})")
    except Exception as e:
        log(f"    [Mesh] WARNING: Could not write .assetinfo: {e}")

    # Conversion trace: which rule each group got, and from what.
    if trace is not None:
        trace.record_assetinfo(
            fbx_dest_path, mesh_guid, up_axis, eff,
            node_translations, user_translation if has_user_translation else None, groups,
        )
