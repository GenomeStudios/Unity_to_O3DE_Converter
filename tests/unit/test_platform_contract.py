"""Unit tests for the SourcePlatform contract and UnityPlatform's
conformance to it. Phase B verification + follow-up 5 (asset_db
binding) + follow-up 6 (SUPPORTED_TABS)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from tests.fixtures.unity_tree import build_unity_tree, GUIDS


def test_source_platform_is_abstract():
    """SourcePlatform must not be directly instantiable."""
    from platforms.base import SourcePlatform
    try:
        SourcePlatform()
    except TypeError as e:
        assert "abstract" in str(e).lower()
        return
    raise AssertionError("SourcePlatform should not be directly instantiable")


def test_neutral_types_carry_sane_defaults():
    from platforms.types import (
        AssetIndex, PlatformMaterial, PlatformEntity, PlatformPrefab,
        PlatformScene, PlatformTransform,
    )
    t = PlatformTransform()
    assert t.translation == [0.0, 0.0, 0.0]
    assert t.rotation    == [0.0, 0.0, 0.0, 1.0]
    assert t.scale       == [1.0, 1.0, 1.0]
    # PlatformScene is presently an alias for PlatformPrefab.
    assert PlatformScene is PlatformPrefab
    m = PlatformMaterial()
    assert m.name == "" and m.raw_textures == {} and m.extra == {}
    idx = AssetIndex()
    assert idx.by_id == {}


def test_unity_platform_conforms():
    from platforms.base import SourcePlatform
    from platforms.unity.unity_platform import UnityPlatform
    plat = UnityPlatform()
    assert isinstance(plat, SourcePlatform)
    assert plat.NAME == "unity"
    assert plat.DISPLAY == "Unity"
    assert plat.UP_AXIS == "Y"
    assert plat.HANDEDNESS == "LH"
    assert plat.FILE_EXTENSIONS.get("prefab") == "*.prefab"
    assert plat.FILE_EXTENSIONS.get("material") == "*.mat"


def test_unity_platform_default_profiles_carry_catchall():
    from platforms.unity.unity_platform import UnityPlatform
    plat = UnityPlatform()
    profiles = plat.default_profiles()
    assert "Default — Anything to PBR" in profiles, \
        f"catch-all profile missing: {list(profiles.keys())}"
    mappings = plat.default_shader_mappings()
    assert "Standard" in mappings
    assert mappings["Standard"] == "Default — Anything to PBR"


def test_unity_platform_loads_component_processors():
    from platforms.unity.unity_platform import UnityPlatform
    plat = UnityPlatform()
    procs = plat.component_processors()
    assert procs and isinstance(procs, list)
    proc_names = [type(p).__name__ for p in procs]
    # A handful of must-have processors.
    for expected in ("MeshComponentProcessor", "MaterialComponentProcessor"):
        assert expected in proc_names, \
            f"{expected} missing from component_processors: {proc_names}"


def test_to_o3de_coordinates_swizzles_y_z():
    from platforms.unity.unity_platform import UnityPlatform
    from platforms.types import PlatformTransform
    plat = UnityPlatform()
    t = PlatformTransform(translation=[1, 2, 3],
                          rotation=[0.1, 0.2, 0.3, 0.4],
                          scale=[1, 2, 3])
    converted, non_uniform = plat.to_o3de_coordinates(t)
    assert converted.translation == [1, 3, 2]
    assert converted.rotation    == [0.1, 0.3, 0.2, 0.4]
    assert converted.scale       == [1, 3, 2]
    assert non_uniform


def test_validate_scope_root_red_on_missing():
    from platforms.unity.unity_platform import UnityPlatform
    plat = UnityPlatform()
    items = plat.validate_scope_root(Path("/__this/does/not/exist__"))
    assert any(it.severity == "red" for it in items)


def test_validate_scope_root_yellow_on_missing_assets_dir():
    from platforms.unity.unity_platform import UnityPlatform
    plat = UnityPlatform()
    with tempfile.TemporaryDirectory() as td:
        items = plat.validate_scope_root(Path(td))
        yellow = [it for it in items if it.severity == "yellow"]
        assert yellow and yellow[0].ack_key == "unity.no_assets_dir"


def test_bind_asset_db_threads_worker_db_into_platform():
    """Follow-up 5 — `bind_asset_db` lets the worker share its GUID
    index with the platform plugin, avoiding redundant rebuilds."""
    from platforms.unity.unity_platform import UnityPlatform
    from platforms.unity.asset_database import AssetDatabase
    with tempfile.TemporaryDirectory() as td:
        unity = Path(td) / "unity"
        build_unity_tree(unity)
        plat = UnityPlatform()
        assert plat._asset_db is None

        db = AssetDatabase(unity)
        plat.bind_asset_db(db)
        assert plat._asset_db is db

        # parse_material uses bound DB.
        mat = plat.parse_material(unity / "Materials" / "TestMat.mat")
        assert mat.shader_id == GUIDS["shader"]

        name = plat.resolve_shader_name(mat)
        assert name == "CustomPack/Foo"

        plat.unbind_asset_db()
        assert plat._asset_db is None


def test_supported_tabs_default_is_full_set():
    """Follow-up 6 — every plugin defaults to the full tab set;
    subclasses narrow it to declare which tabs the platform exposes."""
    from platforms.base import SourcePlatform
    from platforms.unity.unity_platform import UnityPlatform
    full = {"dashboard", "scenes", "prefabs", "meshes", "materials",
            "terrain", "config"}
    assert set(SourcePlatform.SUPPORTED_TABS) == full
    assert set(UnityPlatform.SUPPORTED_TABS) == full


def test_supported_tabs_can_be_narrowed():
    from platforms.unity.unity_platform import UnityPlatform

    class NarrowPlatform(UnityPlatform):
        NAME = "narrow"
        SUPPORTED_TABS = ["dashboard", "prefabs", "materials"]

    n = NarrowPlatform()
    assert "terrain" not in n.SUPPORTED_TABS
    assert "scenes"  not in n.SUPPORTED_TABS


def test_correction_quat_is_unity_y_up():
    """Follow-up 5 — UnityPlatform supplies the Y-up→Z-up quaternion
    that the O3DE assetinfo writer composes onto every emitted
    CoordinateSystemRule."""
    from platforms.unity.unity_platform import UnityPlatform
    from platforms.unity.coordinates import UNITY_Y_UP_TO_O3DE_Z_UP_QUAT
    plat = UnityPlatform()
    assert plat.correction_quat == UNITY_Y_UP_TO_O3DE_Z_UP_QUAT


def test_parse_prefab_returns_platform_prefab():
    """Follow-up 2 — `UnityPlatform.parse_prefab(path)` now returns a
    populated PlatformPrefab (not NotImplementedError). Builds a
    minimal synthetic prefab on disk to exercise the converter."""
    import tempfile
    from platforms.unity.unity_platform import UnityPlatform
    from platforms.types import PlatformPrefab, PlatformEntity

    UNITY_PREFAB = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
    - component: {fileID: 4100}
  m_Name: RootGO
--- !u!4 &4100
Transform:
  m_GameObject: {fileID: 100}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Father: {fileID: 0}
  m_Children: []
"""
    with tempfile.TemporaryDirectory() as td:
        prefab_path = Path(td) / "Foo.prefab"
        prefab_path.write_text(UNITY_PREFAB, encoding="utf-8")
        plat = UnityPlatform()
        result = plat.parse_prefab(prefab_path)
        assert isinstance(result, PlatformPrefab)
        assert result.root, f"root should be populated: {result}"
        assert len(result.entities) >= 1
        entity = result.entities[result.root]
        assert isinstance(entity, PlatformEntity)
        assert entity.name == "RootGO"


def test_parse_scene_delegates_to_parse_prefab():
    """Follow-up 3 — `parse_scene` delegates to `parse_prefab` (Unity
    scene + prefab files share the same YAML format)."""
    import tempfile
    from platforms.unity.unity_platform import UnityPlatform

    UNITY_SCENE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &200
GameObject:
  m_Component:
    - component: {fileID: 4200}
  m_Name: SceneRoot
--- !u!4 &4200
Transform:
  m_GameObject: {fileID: 200}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Father: {fileID: 0}
  m_Children: []
"""
    with tempfile.TemporaryDirectory() as td:
        scene_path = Path(td) / "Bar.unity"
        scene_path.write_text(UNITY_SCENE, encoding="utf-8")
        plat = UnityPlatform()
        result = plat.parse_scene(scene_path)
        assert result.entities[result.root].name == "SceneRoot"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
