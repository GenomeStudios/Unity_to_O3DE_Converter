"""Unit test for the cached fields on mesh state-index entries.

I.1 of the mesh-patch-worker plan adds ``fbx_stem``,
``entity_node_map``, and ``collider_entity_node_map`` to every entry
written by ``_record_mesh_state``. These are the cached subset of
prefab-parse state the Patch worker replays at re-emit time so it can
call ``write_fbx_assetinfo`` without re-parsing every consumer prefab.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests

from integrated_asset_processor import IntegratedAssetProcessor


def _make_processor(td: Path) -> IntegratedAssetProcessor:
    unity = td / "unity"
    out   = td / "out"
    unity.mkdir()
    out.mkdir()
    proc = IntegratedAssetProcessor(unity, out, log_callback=lambda *_: None)
    return proc


def test_record_mesh_state_caches_node_maps():
    td = Path(tempfile.mkdtemp(prefix="u2o_mesh_state_shape_"))
    try:
        proc = _make_processor(td)
        # Fake a source FBX + an output FBX (no assetinfo on disk for now)
        src_fbx = td / "unity" / "Mesh.fbx"
        src_fbx.write_bytes(b"FBX-stub\x00\x00")
        out_fbx = td / "out" / "Meshes" / "Mesh.fbx"
        out_fbx.parent.mkdir(parents=True, exist_ok=True)
        out_fbx.write_bytes(b"FBX-stub\x00\x00")

        guid = "deadbeefcafebabe000000000000ffff"
        entity_node_map = {"Door":  "RootNode.Mesh.Door",
                           "Handle": "RootNode.Mesh.Door.Handle"}
        physx_specs = [{"name": "Mesh-Door", "node_paths": ["RootNode.Mesh.Door"],
                        "convex": False}]
        proc._record_mesh_state(
            guid, src_fbx, out_fbx,
            fbx_stem="Mesh",
            entity_node_map=entity_node_map,
            physx_specs=physx_specs,
        )

        entry = proc.state_index()["meshes"][guid]
        assert entry["fbx_stem"] == "Mesh"
        assert entry["entity_node_map"] == entity_node_map
        assert entry["physx_specs"] == physx_specs
        # Pre-existing fields still present.
        for key in ("source_path", "source_mtime", "output_files",
                    "input_hash", "last_emitted"):
            assert key in entry, f"missing {key}"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_record_mesh_state_defaults_to_empty_maps():
    """Backwards-compat: calls that omit the new kwargs land empty
    dicts on the entry rather than missing keys (so the Patch worker's
    "needs reparse" check has a stable shape to read against)."""
    td = Path(tempfile.mkdtemp(prefix="u2o_mesh_state_default_"))
    try:
        proc = _make_processor(td)
        src_fbx = td / "unity" / "M.fbx"
        src_fbx.write_bytes(b"FBX-stub\x00\x00")
        out_fbx = td / "out" / "Meshes" / "M.fbx"
        out_fbx.parent.mkdir(parents=True, exist_ok=True)
        out_fbx.write_bytes(b"FBX-stub\x00\x00")

        guid = "deadbeefcafebabe000000000000aaaa"
        proc._record_mesh_state(guid, src_fbx, out_fbx)

        entry = proc.state_index()["meshes"][guid]
        assert entry["fbx_stem"] == ""
        assert entry["entity_node_map"] == {}
        assert entry["physx_specs"] == []
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
