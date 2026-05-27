"""Integration test for F-9 material emission through
``IntegratedAssetProcessor._process_material``.

Verifies the full chain:
  - Profile resolution (override → mapping → default).
  - Materialtype escape hatch.
  - Per-slot texture overrides.
  - state_index recording.

Uses the synthetic Unity tree fixture so the asset_db actually has
data to walk.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.unity_tree import build_unity_tree, GUIDS

from project_manager import DEFAULT_PROFILE_NAME, DEFAULT_SHADER_PROFILE
from integrated_asset_processor import IntegratedAssetProcessor


def _emit_with_settings(material_settings):
    """Helper — build a Unity tree, run _process_material, return
    the emitted .material body dict + the worker."""
    td = tempfile.mkdtemp(prefix="u2o_emit_")
    try:
        unity = Path(td) / "unity"
        out   = Path(td) / "out"
        build_unity_tree(unity)
        out.mkdir()
        proc = IntegratedAssetProcessor(
            unity, out, log_callback=lambda *_: None,
            material_settings=material_settings,
        )
        proc.asset_hint_root = "assets/test"
        proc._process_material(GUIDS["material"])
        body = json.loads((out / "Materials" / "TestMat.material").read_text())
        return body, proc, td
    except Exception:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
        raise


def _cleanup(td):
    import shutil
    shutil.rmtree(td, ignore_errors=True)


def test_default_profile_emits_standardpbr():
    """No explicit mapping for the synthetic CustomPack/Foo shader →
    falls through to the default profile → emits StandardPBR."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {},
        "overrides":       {},
    }
    body, _, td = _emit_with_settings(settings)
    try:
        assert "StandardPBR.materialtype" in body["materialType"]
        assert body["propertyValues"].get("baseColor.textureMap"), \
            f"texture routing broke: {body['propertyValues']}"
    finally:
        _cleanup(td)


def test_state_index_records_profile_provenance():
    """The state-index entry for an emitted material carries
    `profile_name` and `shader_name` so the MaterialTab tooltip can
    surface which F-9 profile produced this .material on disk."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {"CustomPack/Foo": DEFAULT_PROFILE_NAME},
        "overrides":       {},
    }
    _body, proc, td = _emit_with_settings(settings)
    try:
        entry = proc.state_index()["materials"][GUIDS["material"]]
        assert entry["profile_name"] == DEFAULT_PROFILE_NAME, entry
        assert entry["shader_name"]  == "CustomPack/Foo", entry
    finally:
        _cleanup(td)


def test_state_index_provenance_blank_in_legacy_fallback():
    """No `material_settings` supplied → legacy hardcoded extraction
    path → the state-index entry's provenance fields are blank,
    so the MaterialTab tooltip can show "Last emitted via legacy
    hardcoded path"."""
    td = tempfile.mkdtemp(prefix="u2o_legacy_prov_")
    try:
        unity = Path(td) / "unity"
        out   = Path(td) / "out"
        build_unity_tree(unity)
        out.mkdir()
        proc = IntegratedAssetProcessor(
            unity, out, log_callback=lambda *_: None,
            # No material_settings — legacy mode.
        )
        proc.asset_hint_root = "assets/test"
        proc._process_material(GUIDS["material"])
        entry = proc.state_index()["materials"][GUIDS["material"]]
        assert entry["profile_name"] == "", entry
        assert entry["shader_name"]  == "CustomPack/Foo", entry
    finally:
        _cleanup(td)


def test_divergent_profile_via_shader_mapping():
    """An explicit mapping for the shader routes the material through
    a divergent profile with a custom target_materialtype."""
    custom = dict(DEFAULT_SHADER_PROFILE)
    custom["target_materialtype"] = "/abs/path/CustomTest.materialtype"
    settings = {
        "defaults": {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {
            DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE),
            "Divergent":          custom,
        },
        "shader_mappings": {"CustomPack/Foo": "Divergent"},
        "overrides": {},
    }
    body, _, td = _emit_with_settings(settings)
    try:
        assert body["materialType"] == "/abs/path/CustomTest.materialtype"
    finally:
        _cleanup(td)


def test_per_material_materialtype_escape_hatch():
    """``overrides[guid].materialtype`` bypasses the profile chain."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {},
        "overrides": {
            GUIDS["material"]: {
                "materialtype": "@gemroot:My_Gem@/Materials/Types/Escape.materialtype",
            },
        },
    }
    body, _, td = _emit_with_settings(settings)
    try:
        assert body["materialType"] == \
            "@gemroot:My_Gem@/Materials/Types/Escape.materialtype"
    finally:
        _cleanup(td)


def test_per_slot_texture_override_wins():
    """``overrides[guid].textures.<slot>`` overrides the auto-extracted
    texture for that slot."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {},
        "overrides": {
            GUIDS["material"]: {
                "textures": {"baseColor": "../Textures/UserPickedAlt.png"},
            },
        },
    }
    body, _, td = _emit_with_settings(settings)
    try:
        assert body["propertyValues"]["baseColor.textureMap"] == \
            "../Textures/UserPickedAlt.png"
    finally:
        _cleanup(td)


def test_legacy_no_settings_emits_hardcoded_standardpbr():
    """No material_settings → legacy path → hard-coded StandardPBR
    @gemroot. Keeps terrain_material_processor + standalone tooling
    working post-refactor."""
    td = tempfile.mkdtemp(prefix="u2o_legacy_")
    try:
        unity = Path(td) / "unity"
        out   = Path(td) / "out"
        build_unity_tree(unity)
        out.mkdir()
        proc = IntegratedAssetProcessor(unity, out, log_callback=lambda *_: None)
        proc.asset_hint_root = "assets/legacy"
        proc._process_material(GUIDS["material"])
        body = json.loads((out / "Materials" / "TestMat.material").read_text())
        assert body["materialType"] == \
            "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/StandardPBR.materialtype"
    finally:
        _cleanup(td)


def test_state_index_records_material_after_emission():
    """F-9.I.4 — after emission, state_index.materials[guid] carries
    an input_hash + output_files + last_emitted."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {},
        "overrides":       {},
    }
    _, proc, td = _emit_with_settings(settings)
    try:
        si = proc.state_index()
        entry = si["materials"].get(GUIDS["material"])
        assert entry is not None, f"state_index missing entry: {si['materials']}"
        assert entry["input_hash"].startswith("sha256:")
        assert entry["output_files"]
        assert entry["last_emitted"]
        assert entry["source_mtime"] > 0
    finally:
        _cleanup(td)


def test_worker_binds_asset_db_to_platform():
    """Follow-up 5 — the worker shares its AssetDatabase with the
    platform plugin so platform methods don't rebuild a redundant DB."""
    settings = {
        "defaults":        {"profile": DEFAULT_PROFILE_NAME},
        "shader_profiles": {DEFAULT_PROFILE_NAME: dict(DEFAULT_SHADER_PROFILE)},
        "shader_mappings": {},
        "overrides":       {},
    }
    _, proc, td = _emit_with_settings(settings)
    try:
        assert proc.platform._asset_db is proc.asset_db, \
            "worker did not bind asset_db onto platform"
    finally:
        _cleanup(td)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
