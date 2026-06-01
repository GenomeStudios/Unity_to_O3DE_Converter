"""Unit test for `_derive_asset_hint_root`.

Regression guard for the 2026-05-28 bug where output deeper than
`<proj>/Assets/<leaf>` (e.g. `<proj>/Assets/Art/<leaf>`) produced an
assetHint root that dropped the intermediate folders, leaving every
mesh / material reference unresolved in O3DE.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests

from integrated_asset_processor import (
    _derive_asset_hint_root,
    _find_project_root,
    _project_relative_path,
)


def test_relative_to_project_root_keeps_intermediate_folders():
    """The real-world failure: output nested under Assets/Art/. The hint
    root must include `art/`, derived from the path relative to the dir
    holding project.json."""
    td = Path(tempfile.mkdtemp(prefix="u2o_hint_proj_"))
    try:
        (td / "project.json").write_text("{}", encoding="utf-8")
        out = td / "Assets" / "Art" / "Alien Fantasy Forest"
        out.mkdir(parents=True)
        assert _derive_asset_hint_root(out) == "assets/art/alien fantasy forest"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_direct_in_assets_under_project_root():
    """Output directly inside Assets/ → single segment after assets/."""
    td = Path(tempfile.mkdtemp(prefix="u2o_hint_direct_"))
    try:
        (td / "project.json").write_text("{}", encoding="utf-8")
        out = td / "Assets" / "MyPack"
        out.mkdir(parents=True)
        assert _derive_asset_hint_root(out) == "assets/mypack"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_assets_segment_fallback_without_project_json():
    """No project.json above the output (not built yet) → fall back to
    the first `assets` path segment and keep everything below it."""
    td = Path(tempfile.mkdtemp(prefix="u2o_hint_seg_"))
    try:
        out = td / "Assets" / "Art" / "ForestPack"
        out.mkdir(parents=True)
        # No project.json anywhere above.
        assert _derive_asset_hint_root(out) == "assets/art/forestpack"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_leaf_only_last_resort():
    """No project.json and no `assets` segment → legacy leaf behaviour."""
    td = Path(tempfile.mkdtemp(prefix="u2o_hint_leaf_"))
    try:
        out = td / "RandomOutput"
        out.mkdir(parents=True)
        assert _derive_asset_hint_root(out) == "assets/randomoutput"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_project_root_wins_over_assets_segment():
    """When BOTH a project.json and an `assets` segment exist, the
    project-relative path is authoritative — even if the project root
    itself sits below a folder literally named 'assets'."""
    td = Path(tempfile.mkdtemp(prefix="u2o_hint_both_"))
    try:
        # Pathological: an 'assets' dir ABOVE the project root.
        proj = td / "assets" / "MyProj"
        proj.mkdir(parents=True)
        (proj / "project.json").write_text("{}", encoding="utf-8")
        out = proj / "Assets" / "Art" / "Pack"
        out.mkdir(parents=True)
        # Relative to project root, not to the outer 'assets' dir.
        assert _derive_asset_hint_root(out) == "assets/art/pack"
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


# =============================================================================
# `_project_relative_path` — the case-preserving sibling used by the
# nested-prefab `Source` field. Regression guard for the 2026-05-31
# bug where scene-level nested prefab instances pointed at
# `Prefabs/<name>.prefab` instead of the real `Assets/Art/.../Prefabs/<name>.prefab`.
# =============================================================================

def test_project_relative_path_preserves_case():
    td = Path(tempfile.mkdtemp(prefix="u2o_relpath_case_"))
    try:
        (td / "project.json").write_text("{}", encoding="utf-8")
        prefab = td / "Assets" / "Art" / "Alien Fantasy Forest" / "Prefabs" / "Watersprinklerpipe_R.prefab"
        prefab.parent.mkdir(parents=True)
        prefab.write_text("{}", encoding="utf-8")
        assert _project_relative_path(prefab) == (
            "Assets/Art/Alien Fantasy Forest/Prefabs/Watersprinklerpipe_R.prefab"
        )
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_project_relative_path_returns_none_outside_project():
    td = Path(tempfile.mkdtemp(prefix="u2o_relpath_none_"))
    try:
        prefab = td / "loose" / "Pack" / "Prefabs" / "Foo.prefab"
        prefab.parent.mkdir(parents=True)
        prefab.write_text("{}", encoding="utf-8")
        # No project.json anywhere → callers fall back to legacy logic.
        assert _project_relative_path(prefab) is None
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


def test_find_project_root_returns_dir_with_project_json():
    td = Path(tempfile.mkdtemp(prefix="u2o_findroot_"))
    try:
        (td / "project.json").write_text("{}", encoding="utf-8")
        nested = td / "Assets" / "X" / "Y"
        nested.mkdir(parents=True)
        assert _find_project_root(nested) == td
        assert _find_project_root(td) == td
    finally:
        import shutil; shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
