"""
=============================================================================
SYNTHETIC UNITY ASSET TREE FIXTURE
=============================================================================

Builds a small but realistic Unity-style directory tree for end-to-end
tests. The tree contains one ``.mat`` referencing one ``.shader``
referencing one texture; each asset has its companion ``.meta`` file
with a stable GUID. The GUIDs are well-known constants so test
assertions can address specific entries.

Used by every integration test that exercises the worker
(``IntegratedAssetProcessor``) or the platform plugin
(``UnityPlatform``) end-to-end.

Usage::

    from tests.fixtures.unity_tree import build_unity_tree, GUIDS
    from pathlib import Path

    unity_root = Path(tmp_dir) / "unity"
    build_unity_tree(unity_root)

    proc = IntegratedAssetProcessor(unity_root, output_root, ...)
    proc._process_material(GUIDS["material"])
"""

from pathlib import Path
from typing import Dict


# ---------------------------------------------------------------------------
# Stable test GUIDs. Address specific assets in test assertions.
# ---------------------------------------------------------------------------

GUIDS: Dict[str, str] = {
    "material":   "deadbeefcafebabe000000000000eeee",
    "shader":     "deadbeefcafebabe000000000000aaaa",
    "texture":    "deadbeefcafebabe000000000000bbbb",
    # Secondary material/shader used for tests that need two of each
    # (e.g. patch worker testing "only one of two materials is dirty").
    "material_b": "11111111111111111111111111111111",
    "shader_b":   "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "texture_b":  "cccccccccccccccccccccccccccccccc",
}


# ---------------------------------------------------------------------------
# File body templates. Multi-doc Unity YAML with one Material doc.
# ---------------------------------------------------------------------------

_UNITY_MAT_TEMPLATE = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!21 &2100000
Material:
  serializedVersion: 6
  m_Name: {name}
  m_Shader: {{fileID: 4800000, guid: {shader_guid}, type: 3}}
  m_SavedProperties:
    serializedVersion: 3
    m_TexEnvs:
    - _MainTex:
        m_Texture: {{fileID: 2800000, guid: {texture_guid}, type: 3}}
    m_Floats:
    - _BumpScale: 1.5
    m_Colors:
    - _Color: {{r: 0.5, g: 0.6, b: 0.7, a: 1.0}}
"""

_META_TEMPLATE = "fileFormatVersion: 2\nguid: {guid}\n"

_SHADER_TEMPLATE = 'Shader "{shader_name}"\n{{\n}}\n'

# Smallest legal PNG: 1×1, fully transparent. Enough for texture-copy
# code paths that just `shutil.copy2` the bytes through.
_PNG_BYTES = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_unity_tree(root: Path,
                      *,
                      material_name: str = "TestMat",
                      shader_name:   str = "CustomPack/Foo") -> None:
    """Create the synthetic tree under ``root``. Idempotent — calling
    twice with the same root rewrites the same files.

    The tree::

        <root>/
            Materials/
                <material_name>.mat
                <material_name>.mat.meta
            Shaders/
                Foo.shader
                Foo.shader.meta
            Textures/
                test.png
                test.png.meta
    """
    (root / "Materials").mkdir(parents=True, exist_ok=True)
    (root / "Shaders").mkdir(parents=True, exist_ok=True)
    (root / "Textures").mkdir(parents=True, exist_ok=True)

    (root / "Materials" / f"{material_name}.mat").write_text(
        _UNITY_MAT_TEMPLATE.format(
            name=material_name,
            shader_guid=GUIDS["shader"],
            texture_guid=GUIDS["texture"],
        ),
        encoding="utf-8",
    )
    (root / "Materials" / f"{material_name}.mat.meta").write_text(
        _META_TEMPLATE.format(guid=GUIDS["material"]),
        encoding="utf-8",
    )
    (root / "Shaders" / "Foo.shader").write_text(
        _SHADER_TEMPLATE.format(shader_name=shader_name),
        encoding="utf-8",
    )
    (root / "Shaders" / "Foo.shader.meta").write_text(
        _META_TEMPLATE.format(guid=GUIDS["shader"]),
        encoding="utf-8",
    )
    (root / "Textures" / "test.png").write_bytes(_PNG_BYTES)
    (root / "Textures" / "test.png.meta").write_text(
        _META_TEMPLATE.format(guid=GUIDS["texture"]),
        encoding="utf-8",
    )


def build_two_material_unity_tree(root: Path) -> None:
    """Variant that produces two materials, two shaders, one shared
    texture. Used by patch-worker tests that need to verify
    "only the dirty material re-emits"."""
    build_unity_tree(root, material_name="MatA",
                       shader_name="AShader")
    # Override the meta for material A's shader so its meta GUID matches
    # the canonical primary one (otherwise both shaders would map to
    # the same GUID via the secondary path).
    # No further override needed — build_unity_tree already used GUIDS["shader"]
    # for the first one.

    (root / "Materials" / "MatB.mat").write_text(
        _UNITY_MAT_TEMPLATE.format(
            name="MatB",
            shader_guid=GUIDS["shader_b"],
            texture_guid=GUIDS["texture"],
        ),
        encoding="utf-8",
    )
    (root / "Materials" / "MatB.mat.meta").write_text(
        _META_TEMPLATE.format(guid=GUIDS["material_b"]),
        encoding="utf-8",
    )
    (root / "Shaders" / "BShader.shader").write_text(
        _SHADER_TEMPLATE.format(shader_name="BShader"),
        encoding="utf-8",
    )
    (root / "Shaders" / "BShader.shader.meta").write_text(
        _META_TEMPLATE.format(guid=GUIDS["shader_b"]),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fake FBX (just enough to satisfy `read_fbx_up_axis`).
# ---------------------------------------------------------------------------

def write_fake_fbx(path: Path) -> None:
    """Write a minimal placeholder file at ``path``.

    The real ``read_fbx_up_axis`` returns -1 on unparseable binary,
    which the assetinfo writer treats as Z-up (no Y-up correction).
    That's the behavior tests want when they're isolating the user
    transform from the platform's Y-up adjustment.
    """
    path.write_bytes(b"FBX-stub\x00\x00")
