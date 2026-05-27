"""Unit tests for ``project_manager.resolve_materialtype_path``.

The resolver is platform-agnostic (every plugin targets O3DE) and
covers the bare-name / @gemroot / absolute-path / extension-fallback
cases. F-9.I.1 verification."""

# Path bootstrap so ``python tests/unit/test_*.py`` runs standalone.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from project_manager import resolve_materialtype_path, DEFAULT_MATERIALTYPE_PATH


def test_empty_input_returns_default():
    assert resolve_materialtype_path("") == DEFAULT_MATERIALTYPE_PATH
    assert resolve_materialtype_path(None) == DEFAULT_MATERIALTYPE_PATH
    assert resolve_materialtype_path("   ") == DEFAULT_MATERIALTYPE_PATH


def test_builtin_bare_filenames_expand():
    assert resolve_materialtype_path("StandardPBR.materialtype") == \
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/StandardPBR.materialtype"
    assert resolve_materialtype_path("BasePBR.materialtype") == \
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/BasePBR.materialtype"
    assert resolve_materialtype_path("EnhancedPBR.materialtype") == \
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/EnhancedPBR.materialtype"


def test_bare_name_without_extension_gets_dotmaterialtype():
    assert resolve_materialtype_path("StandardPBR") == \
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/StandardPBR.materialtype"


def test_at_gemroot_form_passes_through():
    custom = "@gemroot:My_Gem@/Assets/Materials/Types/Custom.materialtype"
    assert resolve_materialtype_path(custom) == custom


def test_posix_absolute_path_passes_through():
    p = "/abs/posix/Custom.materialtype"
    assert resolve_materialtype_path(p) == p


def test_windows_absolute_path_passes_through():
    assert resolve_materialtype_path("D:/abs/win/Custom.materialtype") == \
        "D:/abs/win/Custom.materialtype"
    assert resolve_materialtype_path("D:\\abs\\win\\Custom.materialtype") == \
        "D:\\abs\\win\\Custom.materialtype"


def test_project_local_materialtype_passes_through():
    """A bare filename ending in .materialtype that isn't a builtin
    is treated as a project-local materialtype the asset processor
    will resolve at emit time."""
    assert resolve_materialtype_path("ProjectLocal.materialtype") == \
        "ProjectLocal.materialtype"


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
