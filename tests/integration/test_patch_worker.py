"""Integration test for the F-9 patch worker.

Verifies ``IntegratedAssetProcessor.patch()`` correctly detects dirty
materials (input-hash mismatch vs the saved state index) and re-emits
ONLY those, leaving clean materials untouched on disk."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.unity_tree import build_two_material_unity_tree, GUIDS

from project_manager import DEFAULT_PROFILE_NAME, DEFAULT_SHADER_PROFILE
from integrated_asset_processor import IntegratedAssetProcessor


def _initial_emission(td: Path):
    """Helper — emit both materials under the default profile.
    Returns (state_index, mat_a_mtime, mat_b_mtime, unity_root, output_root)."""
    unity = td / "unity"
    out   = td / "out"
    build_two_material_unity_tree(unity)
    out.mkdir()

    settings = {
        "defaults": {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {
            "AShader": DEFAULT_PROFILE_NAME,
            "BShader": DEFAULT_PROFILE_NAME,
        },
        "overrides": {},
    }
    proc = IntegratedAssetProcessor(unity, out, log_callback=lambda *_: None,
                                     material_settings=settings)
    proc.asset_hint_root = "assets/patch"
    proc._process_material(GUIDS["material"])     # MatA
    proc._process_material(GUIDS["material_b"])   # MatB
    state = proc.state_index()
    mat_a = out / "Materials" / "MatA.material"
    mat_b = out / "Materials" / "MatB.material"
    return state, mat_a.stat().st_mtime_ns, mat_b.stat().st_mtime_ns, unity, out


def test_patch_re_emits_only_dirty_materials():
    td = Path(tempfile.mkdtemp(prefix="u2o_patch_dirty_"))
    try:
        state, mtime_a_1, mtime_b_1, unity, out = _initial_emission(td)
        # Wait long enough for the mtime granularity to register.
        time.sleep(0.05)

        # Change the profile assignment for AShader → "Divergent"
        # but leave BShader alone. patch() should re-emit MatA only.
        custom = dict(DEFAULT_SHADER_PROFILE)
        custom["target_materialtype"] = "/abs/Custom.materialtype"
        settings2 = {
            "defaults": {"profile": DEFAULT_PROFILE_NAME},
            "shader_profiles": {
                DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE),
                "Divergent":          custom,
            },
            "shader_mappings": {
                "AShader": "Divergent",
                "BShader": DEFAULT_PROFILE_NAME,
            },
            "overrides": {},
        }
        proc2 = IntegratedAssetProcessor(unity, out, log_callback=lambda *_: None,
                                          material_settings=settings2,
                                          state_index=state)
        proc2.asset_hint_root = "assets/patch"
        summary = proc2.patch()
        assert summary["materials_dirty"]   == [GUIDS["material"]]
        assert summary["materials_emitted"] == [GUIDS["material"]]

        # On-disk verification.
        mat_a = out / "Materials" / "MatA.material"
        mat_b = out / "Materials" / "MatB.material"
        assert mat_a.stat().st_mtime_ns > mtime_a_1, \
            "MatA should be re-emitted (mtime didn't advance)"
        assert mat_b.stat().st_mtime_ns == mtime_b_1, \
            "MatB should be untouched"

        # MatA carries the new materialType; MatB still on default.
        body_a = json.loads(mat_a.read_text())
        assert body_a["materialType"] == "/abs/Custom.materialtype"
        body_b = json.loads(mat_b.read_text())
        assert "StandardPBR.materialtype" in body_b["materialType"]
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


def test_patch_with_unchanged_settings_is_noop():
    td = Path(tempfile.mkdtemp(prefix="u2o_patch_noop_"))
    try:
        state, _, _, unity, out = _initial_emission(td)
        settings_same = {
            "defaults": {"profile": DEFAULT_PROFILE_NAME},
            "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
            "shader_mappings": {
                "AShader": DEFAULT_PROFILE_NAME,
                "BShader": DEFAULT_PROFILE_NAME,
            },
            "overrides": {},
        }
        proc = IntegratedAssetProcessor(unity, out, log_callback=lambda *_: None,
                                         material_settings=settings_same,
                                         state_index=state)
        proc.asset_hint_root = "assets/patch"
        summary = proc.patch()
        assert summary["materials_dirty"] == []
        assert summary["materials_emitted"] == []
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
