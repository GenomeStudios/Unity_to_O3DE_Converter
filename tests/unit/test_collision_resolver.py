"""Unit tests for the collision sub-mesh resolver — the heart of the
per-sub-mesh PhysX model. Maps a Unity MeshCollider's
``m_Mesh = {guid, fileID}`` to the FBX node that holds its collision
geometry, and derives the deterministic PhysX group / .pxmesh name.

Covers the topologies catalogued in `mem:asset_packs/import_catalogue`:
  T1/T2/T3 — render-correlation (collision sub-mesh is also rendered).
  T4       — dedicated multi-submesh _COL FBX, never rendered, resolved
             by the linear fileID scheme.
See `mem:physx_mesh_collider/physx_mesh_collider_plan`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests

from integrated_asset_processor import resolve_collision_node, physx_group_name


# ---- resolve_collision_node ---------------------------------------------

def test_render_correlation_wins_when_node_is_real():
    """When a render entity uses the same (guid, fileID) and its node path
    points at a real FBX node, reuse it verbatim (covers hash/negative
    fileIDs that can't be decoded arithmetically)."""
    node = resolve_collision_node(
        "-99", ["A", "B", "C"], render_node="RootNode.Deep.B")
    assert node == "RootNode.Deep.B"


def test_render_correlation_ignored_when_node_not_in_fbx():
    """A correlated node that isn't a real FBX node (build_fbx_node_paths
    fell back to the GO name — NatureManufacture LOD2 vs FBX LOD02) is
    NOT trusted; linear decode wins. Regression for the LOD-naming bug."""
    nodes = ["SM_LOD02", "SM_LOD1", "SM_LOD0"]
    node = resolve_collision_node(
        "4300000", nodes, render_node="RootNode.SM_LOD2")  # LOD2 ∉ nodes
    assert node == "RootNode.SM_LOD02"  # linear decode, index 0


def test_single_mesh_fbx_always_node_zero():
    """A single-mesh FBX resolves to its one node regardless of fileID
    (covers Desk/Cell _COL and negative-hash fileIDs)."""
    assert resolve_collision_node("4300000", ["Only"]) == "RootNode.Only"
    assert resolve_collision_node("-7011492303168654833", ["Only"]) == "RootNode.Only"
    assert resolve_collision_node("", ["Only"]) == "RootNode.Only"


def test_linear_fileid_scheme_multi_mesh():
    """T4 StairsMod_COL: file-order nodes, fileID = 4300000 + 2*index."""
    nodes = ["Ground_Collision", "RailInside_Collision", "RailOutside_Collision"]
    assert resolve_collision_node("4300000", nodes) == "RootNode.Ground_Collision"
    assert resolve_collision_node("4300002", nodes) == "RootNode.RailInside_Collision"
    assert resolve_collision_node("4300004", nodes) == "RootNode.RailOutside_Collision"


def test_out_of_range_or_hash_falls_back_to_first():
    """Negative/hash or out-of-range fileIDs in a multi-mesh FBX fall back
    to the first node (best-effort whole-FBX)."""
    nodes = ["A", "B", "C"]
    assert resolve_collision_node("-123", nodes) == "RootNode.A"
    assert resolve_collision_node("4300099", nodes) == "RootNode.A"  # idx 49 > len
    assert resolve_collision_node("not-an-int", nodes) == "RootNode.A"


def test_no_nodes_returns_none():
    assert resolve_collision_node("4300000", []) is None


# ---- physx_group_name ----------------------------------------------------

def test_group_name_single_mesh_is_bare_stem():
    """Single-mesh FBX → bare stem (matches the Mushroom reference:
    mushroom_big1.fbx.pxmesh)."""
    assert physx_group_name("Mushroom_Big1", "RootNode.Group47215", ["Group47215"]) \
        == "Mushroom_Big1"


def test_group_name_multi_mesh_suffixes_node_leaf():
    """Multi-mesh FBX → stem-nodeleaf so each sub-mesh yields a distinct
    .pxmesh product."""
    nodes = ["Ground_Collision", "RailInside_Collision", "RailOutside_Collision"]
    assert physx_group_name("StairsMod_Ground_COL",
                            "RootNode.RailInside_Collision", nodes) \
        == "StairsMod_Ground_COL-RailInside_Collision"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
