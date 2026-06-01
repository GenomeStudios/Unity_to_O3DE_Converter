"""Unit test for the prefab-wrapper Editor-only toggle.

`create_container_entity` emits the prefab's ContainerEntity as an
editor-only entity by default; the Meshes tab's
`mesh_processor.prefab_wrapper_editor_only` flag (threaded via the
worker's `_mesh_settings`) can turn that off.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests

from targets.o3de.prefab_writer import create_container_entity


class _StubWorker:
    def __init__(self, mesh_settings):
        self._mesh_settings = mesh_settings


class _StubGO:
    name = "Foo"


def _is_editor_only(mesh_settings) -> bool:
    c = create_container_entity(_StubWorker(mesh_settings), _StubGO())
    return c["Components"]["EditorOnlyEntityComponent"]["IsEditorOnly"]


def test_default_is_editor_only():
    """Absent flag → editor-only (preserves prior hardcoded behaviour)."""
    assert _is_editor_only({}) is True
    assert _is_editor_only({"prefab_wrapper_editor_only": True}) is True


def test_toggle_off_keeps_wrapper_at_runtime():
    assert _is_editor_only({"prefab_wrapper_editor_only": False}) is False


def test_missing_mesh_settings_defaults_editor_only():
    """A worker with no _mesh_settings attribute still defaults on."""
    class _Bare:
        pass
    c = create_container_entity(_Bare(), _StubGO())
    assert c["Components"]["EditorOnlyEntityComponent"]["IsEditorOnly"] is True


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
