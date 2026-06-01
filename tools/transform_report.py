"""Transform reconciliation report — exposes the "truer state" of a Unity
prefab's placement so we can SEE why conversions scatter.

For each renderable + collider it lays out, side by side:
  - the FBX-baked node transform (the offset/axis Unity drops but O3DE bakes),
  - the per-mesh `zero_position` state (our centralization default),
  - the Unity-composed world position (hierarchy + nested-instance placement),
  - pattern tags (large-scene-offset, axis-90-bake, collider-vs-render-bake
    divergence, sub-node real-offset).

Read-only. Pure helpers (`compose_world_pos`, `classify_bake`,
`UNITY_TO_M`) are unit-tested in tests/unit/test_transform_report.py.
See `mem:transform_truth/transform_truth_plan`.

  python tools/transform_report.py <source_root> <prefab.prefab> [--json]
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Pure helpers (engine-free, unit-tested)
# ---------------------------------------------------------------------------

UNITY_TO_M = 0.01   # FBX stores cm; Unity imports FBX at scale 0.01 → metres.

# Above this (metres) an FBX node translation is a scene-layout/turntable
# bake Unity drops (Office roots sit 25-50m off in X); below it, it's
# furniture-scale authored placement (door height ~1.25m, drawer ~0.45m).
LARGE_OFFSET_M = 5.0


def compose_world_pos(go, gos) -> tuple:
    """Sum local positions up the parent chain → Unity-space world position.
    Translation only (the dominant scatter axis); rotation is reported raw."""
    x = y = z = 0.0
    seen = set()
    cur = go
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        p = cur.transform.position if cur.transform else None
        if p:
            x += float(p[0]); y += float(p[1]); z += float(p[2])
        cur = gos.get(cur.parent_id) if cur.parent_id else None
    return (round(x, 4), round(y, 4), round(z, 4))


def classify_bake(translation_cm, rotation_deg) -> dict:
    """Tag an FBX node's baked transform. Returns translation in metres +
    a list of pattern tags."""
    tm = [round(v * UNITY_TO_M, 4) for v in (translation_cm or [0, 0, 0])]
    rot = rotation_deg or [0, 0, 0]
    tags = []
    if any(abs(v) > LARGE_OFFSET_M for v in tm):
        tags.append("large-scene-offset")
    elif any(abs(v) > 1e-4 for v in tm):
        tags.append("sub-node-offset")
    if any(abs(abs(v) - 90.0) < 1.0 or abs(abs(v) - 270.0) < 1.0 for v in rot):
        tags.append("axis-90-bake")
    return {"translation_m": tm, "tags": tags}


# ---------------------------------------------------------------------------
# Report builder (uses the converter's parser + FBX readers)
# ---------------------------------------------------------------------------

def build_report(source_root: Path, prefab_path: Path) -> dict:
    from integrated_asset_processor import (
        IntegratedAssetProcessor, read_fbx_mesh_node_names,
        read_fbx_node_transforms, resolve_collision_node,
    )

    out = Path(tempfile.mkdtemp(prefix="u2o_report_"))
    proc = IntegratedAssetProcessor(source_root, out, log_callback=lambda *_: None)
    mesh_settings = proc._mesh_settings
    from targets.o3de.assetinfo_writer import _resolve_mesh_settings

    gos, _ = proc._parse_unity_prefab(prefab_path)

    # Cache: mesh_guid -> (fbx_path, node_names, node_transforms)
    fbx_cache = {}

    def fbx_for(guid):
        if guid in fbx_cache:
            return fbx_cache[guid]
        src = proc.asset_db.resolve_guid(guid) if guid else None
        if not src:
            fbx_cache[guid] = (None, [], {})
        else:
            fbx_cache[guid] = (src, read_fbx_mesh_node_names(src),
                               read_fbx_node_transforms(src))
        return fbx_cache[guid]

    def pick_leaf(go_name, file_id, names):
        """Attribute a GO to its FBX node. Exact name-match first (mirrors
        build_fbx_node_paths; required for hash-scheme mesh fileIDs like the
        desk's 8474…/7295…), then the (fileID)→node decode as fallback."""
        if go_name in names:
            return go_name
        node = resolve_collision_node(file_id or "", names)
        return node.split(".")[-1] if node else None

    meshes, colliders = [], []
    for fid, go in gos.items():
        world = compose_world_pos(go, gos)

        if go.mesh_guid:
            src, names, node_tf = fbx_for(go.mesh_guid)
            leaf = pick_leaf(go.name, go.mesh_file_id, names)
            bake = node_tf.get(leaf, {}) if leaf else {}
            cls = classify_bake(bake.get("translation"), bake.get("rotation"))
            eff = _resolve_mesh_settings(mesh_settings, go.mesh_guid)
            # The mirror/scatter signal: FBX node bake and Unity-authored
            # world placement disagree in sign on an axis (door_R baked +X
            # but placed at -X). Unity drops the bake; baking node-world in
            # O3DE flips/doubles the element.
            bm = cls["translation_m"]
            if any(abs(bm[i]) > 0.05 and abs(world[i]) > 0.05
                   and (bm[i] > 0) != (world[i] > 0) for i in range(3)):
                cls["tags"].append("bake-vs-world-sign-flip")
            meshes.append({
                "entity": go.name,
                "fbx": src.name if src else "(unresolved)",
                "node": leaf,
                "node_bake_m": cls["translation_m"],
                "node_rot_deg": [round(v, 2) for v in (bake.get("rotation") or [0, 0, 0])],
                "zero_position": bool(eff.get("zero_position", True)),
                "unity_world_pos": world,
                "is_instance": go.is_prefab_instance,
                "tags": cls["tags"],
            })

        for c in go.colliders:
            if c.get("type") == "MeshCollider":
                cg = c.get("mesh_guid") or go.mesh_guid
                csrc, cnames, cnode_tf = fbx_for(cg)
                cnode = resolve_collision_node(c.get("mesh_file_id") or "", cnames)
                cleaf = cnode.split(".")[-1] if cnode else None
                cbake = classify_bake((cnode_tf.get(cleaf, {}) or {}).get("translation"),
                                      (cnode_tf.get(cleaf, {}) or {}).get("rotation"))
                # Divergence vs the render mesh's bake on the same GO.
                rsrc, rnames, rnode_tf = fbx_for(go.mesh_guid) if go.mesh_guid else (None, [], {})
                rleaf = pick_leaf(go.name, go.mesh_file_id, rnames) if go.mesh_guid else None
                rbake_m = classify_bake((rnode_tf.get(rleaf, {}) or {}).get("translation"), None)["translation_m"]
                diverge = [round(cbake["translation_m"][i] - rbake_m[i], 4) for i in range(3)]
                tags = list(cbake["tags"])
                if any(abs(d) > 1e-3 for d in diverge):
                    tags.append("collider-vs-render-bake")
                colliders.append({
                    "entity": go.name, "type": "MeshCollider",
                    "collision_fbx": csrc.name if csrc else "(unresolved)",
                    "node_bake_m": cbake["translation_m"],
                    "diverge_from_render_m": diverge, "tags": tags,
                })
            else:
                colliders.append({
                    "entity": go.name, "type": c.get("type"),
                    "center": c.get("center"), "size": c.get("size"),
                    "tags": ["box-center-relative-to-GO"],
                })

    import shutil; shutil.rmtree(out, ignore_errors=True)
    return {"prefab": prefab_path.name, "meshes": meshes, "colliders": colliders}


def _print(report: dict) -> None:
    print(f"\n===== TRANSFORM RECONCILIATION: {report['prefab']} =====")
    print("\n-- RENDER MESHES --")
    print(f"  {'entity':24} {'fbx':24} {'node_bake(m)':24} {'rot':14} zero unity_world           tags")
    for m in report["meshes"]:
        print(f"  {m['entity'][:24]:24} {m['fbx'][:24]:24} "
              f"{str(m['node_bake_m']):24} {str(m['node_rot_deg']):14} "
              f"{str(m['zero_position'])[0]}   {str(m['unity_world_pos']):22} {','.join(m['tags'])}")
    print("\n-- COLLIDERS --")
    for c in report["colliders"]:
        if c["type"] == "MeshCollider":
            print(f"  {c['entity'][:24]:24} MeshCollider fbx={c['collision_fbx'][:24]:24} "
                  f"bake={c['node_bake_m']} diverge={c['diverge_from_render_m']} {','.join(c['tags'])}")
        else:
            print(f"  {c['entity'][:24]:24} {c['type']:14} center={c.get('center')} size={c.get('size')} {','.join(c['tags'])}")
    # Pattern summary
    all_tags = [t for m in report["meshes"] for t in m["tags"]] + \
               [t for c in report["colliders"] for t in c["tags"]]
    from collections import Counter
    print("\n-- PATTERN SUMMARY --")
    for tag, n in Counter(all_tags).most_common():
        print(f"  {n:3}  {tag}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if len(args) < 2:
        print(__doc__); raise SystemExit(2)
    rep = build_report(Path(args[0]), Path(args[1]))
    if as_json:
        print(json.dumps(rep, indent=2))
    else:
        _print(rep)
