"""Unit tests for the name a converted prefab is nested by (parity_fixes I.2,
proof T.3).

The engine wants one prefab named by one string wherever it is nested. Stage
1 names a prefab when another prefab nests it, Stage 2 when a level places
it: the two must spell it the same, as its path from the O3DE project root.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from integrated_asset_processor import CoverageTracker
from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter
from platforms.unity.types import GameObject, Transform
from targets.o3de.prefab_writer import create_nested_prefab_instance

UNITY_PREFAB = Path("U:/SomeGame/Assets/Pack/Prefabs/Props/Drawer.prefab")


def _worker(output_root: Path) -> SimpleNamespace:
    """The few things the nested-instance emitter reads from the worker."""
    (output_root / "Prefabs").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(prefabs_dir=output_root / "Prefabs", asset_hint_root="assets/art/pack",
                           prefab_output_path=lambda prefab: output_root / "Prefabs" / Path(prefab).name,
                           coverage=CoverageTracker(), _entity_map_cache={}, asset_index={"materials": {}},
                           material_hint_for=lambda guid: None)


def _nested(worker) -> dict:
    go = GameObject(file_id="77", name="Drawer", transform=Transform(), is_prefab_instance=True,
                    prefab_source_guid="0123")
    return create_nested_prefab_instance(worker, go, UNITY_PREFAB, "Entity_[1]")


def test_nested_source_is_the_converted_prefabs_project_path():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "MyProject"
        project.mkdir()
        (project / "project.json").write_text("{}", encoding="utf-8")
        instance = _nested(_worker(project / "Assets" / "Art" / "Pack"))
        assert instance["Source"] == "Assets/Art/Pack/Prefabs/Drawer.prefab", instance["Source"]


def test_stage_1_and_stage_2_spell_a_prefab_the_same():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "MyProject"
        project.mkdir()
        (project / "project.json").write_text("{}", encoding="utf-8")
        output_root = project / "Assets" / "Art" / "Pack"
        from_prefab = _nested(_worker(output_root))["Source"]

        converted = output_root / "Prefabs" / "Drawer.prefab"
        converted.write_text("{}", encoding="utf-8")
        from_level = UnitySceneConverter(PrefabDatabase(), log_callback=lambda line: None) \
            ._convert_to_assets_path(converted)
        assert from_prefab == from_level, (from_prefab, from_level)


def test_outside_a_project_the_hint_spelling_is_kept():
    with tempfile.TemporaryDirectory() as tmp:
        instance = _nested(_worker(Path(tmp) / "loose_output"))
        assert instance["Source"] == "assets/art/pack/prefabs/Drawer.prefab", instance["Source"]


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
