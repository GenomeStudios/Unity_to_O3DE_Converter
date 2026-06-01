#!/usr/bin/env python3
"""
=============================================================================
UNITY TERRAINDATA PARSER  (platforms.unity.terrain_data)
=============================================================================

Pure source-side reader for Unity's binary ``TerrainData`` ``.asset`` file.
Knows nothing about O3DE — it only turns a Unity terrain into plain Python
data (splat layers, heightmap grid, splatmap images) that the O3DE emitter
(``targets.o3de.terrain_writer``) consumes.

A Unity terrain's real content is NOT in its ``.mat`` (the built-in
``Nature/Terrain/Standard`` shader leaves every texture slot empty). It lives
in the binary-serialized ``TerrainData`` asset:

    SplatDatabase.m_Splats[]   -> per-layer albedo/normal texture (by GUID),
                                  tiling, metallic, smoothness
    SplatDatabase.m_AlphaTextures[] -> embedded RGBA splatmaps (layer weights)
    Heightmap.{m_Heights,m_Scale,m_Width,m_Height} -> the terrain surface

Parsing is delegated to UnityPy, which reads the SerializedFile via the type
tree embedded in the asset. UnityPy is an OPTIONAL dependency: it is imported
lazily so the rest of the converter runs without it, and is only required when
a Unity terrain is actually parsed. Use ``unitypy_available()`` to flag it as a
missing component in the Unity platform's dependency check.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# =============================================================================
# OPTIONAL UNITYPY DEPENDENCY
# =============================================================================

def unitypy_available() -> bool:
    """True if UnityPy can be imported. Used by the Unity platform's
    dependency check so the requirement only surfaces for Unity sources."""
    try:
        import UnityPy  # noqa: F401
        return True
    except Exception:
        return False


def _require_unitypy():
    """Import UnityPy or raise a clear, actionable error."""
    try:
        import UnityPy
        return UnityPy
    except ImportError as exc:
        raise ImportError(
            "Unity terrain conversion requires the 'UnityPy' package. "
            "Install it with:  pip install -r requirements.txt  "
            "(or:  pip install UnityPy)."
        ) from exc


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class SplatLayer:
    """One terrain detail layer (a Unity SplatPrototype)."""
    index:        int
    albedo_guid:  Optional[str] = None   # Unity asset GUID (hex), or None
    normal_guid:  Optional[str] = None
    tile_size_x:  float = 1.0
    tile_size_y:  float = 1.0
    tile_offset_x: float = 0.0
    tile_offset_y: float = 0.0
    metallic:     float = 0.0
    smoothness:   float = 0.0


@dataclass
class HeightmapData:
    """The terrain surface grid. ``heights`` are raw Unity int16 samples in
    ``[0, HEIGHT_DIVISOR]``; world height = (raw / HEIGHT_DIVISOR) * scale_y."""
    width:    int = 0          # samples across (m_Width, e.g. 1025)
    height:   int = 0          # samples down   (m_Height)
    scale_x:  float = 1.0      # world units between samples in X
    scale_y:  float = 1.0      # full world height at normalized 1.0
    scale_z:  float = 1.0      # world units between samples in Z
    heights:  List[int] = field(default_factory=list)

    HEIGHT_DIVISOR = 32767     # Unity stores normalized height * 32767 as int16

    @property
    def world_size_x(self) -> float:
        return self.scale_x * max(self.width - 1, 1)

    @property
    def world_size_z(self) -> float:
        return self.scale_z * max(self.height - 1, 1)


@dataclass
class AlphamapData:
    """One embedded splatmap. ``image`` is an RGBA PIL.Image whose channels
    carry up to four layers' blend weights."""
    index: int
    image: object = None       # PIL.Image.Image (RGBA)


@dataclass
class TerrainData:
    """Parsed Unity terrain. ``layers`` is always populated; ``heightmap`` and
    ``alphamaps`` are only filled when requested at parse time."""
    name:       str
    source_path: Path
    layers:     List[SplatLayer]    = field(default_factory=list)
    heightmap:  Optional[HeightmapData] = None
    alphamaps:  List[AlphamapData]  = field(default_factory=list)

    def alphamap_for_layer(self, layer_index: int):
        """Return (AlphamapData, channel_index 0..3) carrying this layer's
        weight, or (None, None) if no splatmap covers it. Unity packs four
        layers per RGBA splatmap in m_Splats order."""
        tex_index = layer_index // 4
        channel   = layer_index % 4
        if 0 <= tex_index < len(self.alphamaps):
            return self.alphamaps[tex_index], channel
        return None, None


# =============================================================================
# GUID CONVERSION
# =============================================================================

def guid_bytes_to_hex(raw: bytes) -> str:
    """Convert UnityPy's raw 16-byte external GUID into the lowercase hex
    string used in ``.meta`` files. Unity swaps the two nibbles of each byte."""
    return "".join(f"{(b & 0x0F):x}{(b >> 4):x}" for b in raw)


# =============================================================================
# DETECTION
# =============================================================================

def is_terrain_data(path: Path) -> bool:
    """True if ``path`` is a Unity binary asset containing a TerrainData object
    (class id 156). Returns False (never raises) for non-terrain or unreadable
    files so it is safe to call while scanning a folder."""
    if path.suffix.lower() != ".asset":
        return False
    try:
        UnityPy = _require_unitypy()
        env = UnityPy.load(str(path))
        return any(obj.type.name == "TerrainData" for obj in env.objects)
    except Exception:
        return False


def scan_for_terrains(assets_root: Path) -> List[Path]:
    """Walk ``assets_root`` for ``*.asset`` files that contain a TerrainData
    object. Returns sorted absolute paths."""
    assets_root = Path(assets_root)
    found: List[Path] = []
    if not assets_root.is_dir():
        return found
    for candidate in assets_root.rglob("*.asset"):
        if is_terrain_data(candidate):
            found.append(candidate.resolve())
    return sorted(found)


# =============================================================================
# PARSE
# =============================================================================

def parse_terrain_data(path: Path,
                       want_heightmap: bool = True,
                       want_alphamaps: bool = True) -> TerrainData:
    """
    Parse a Unity ``TerrainData`` ``.asset``. Layers are always read (cheap);
    the heightmap grid and embedded splatmaps are only decoded when requested,
    so a materials-only run never pays for them.
    """
    UnityPy = _require_unitypy()
    path = Path(path)
    env = UnityPy.load(str(path))

    serialized = list(env.files.values())[0]
    externals = [guid_bytes_to_hex(ext.guid) for ext in serialized.externals]

    td_obj = next((o for o in env.objects if o.type.name == "TerrainData"), None)
    if td_obj is None:
        raise ValueError(f"No TerrainData object in {path.name}")
    tree = td_obj.read_typetree()

    terrain = TerrainData(name=tree.get("m_Name") or path.stem, source_path=path)

    # ── Splat layers ───────────────────────────────────────────────────────
    splat_db = tree.get("m_SplatDatabase", {})
    for i, splat in enumerate(splat_db.get("m_Splats", [])):
        spec = splat.get("specularMetallic") or {}
        terrain.layers.append(SplatLayer(
            index=i,
            albedo_guid=_pptr_guid(splat.get("texture"), externals),
            normal_guid=_pptr_guid(splat.get("normalMap"), externals),
            tile_size_x=_vec(splat.get("tileSize"), "x", 1.0),
            tile_size_y=_vec(splat.get("tileSize"), "y", 1.0),
            tile_offset_x=_vec(splat.get("tileOffset"), "x", 0.0),
            tile_offset_y=_vec(splat.get("tileOffset"), "y", 0.0),
            # Unity terrain stores metallic in specularMetallic.x.
            metallic=float(spec.get("x", 0.0)) if isinstance(spec, dict) else 0.0,
            smoothness=float(splat.get("smoothness", 0.0) or 0.0),
        ))

    # ── Heightmap ────────────────────────────────────────────────────────────
    if want_heightmap:
        hm = tree.get("m_Heightmap", {})
        scale = hm.get("m_Scale", {}) or {}
        terrain.heightmap = HeightmapData(
            width=int(hm.get("m_Width", 0) or 0),
            height=int(hm.get("m_Height", 0) or 0),
            scale_x=float(scale.get("x", 1.0)),
            scale_y=float(scale.get("y", 1.0)),
            scale_z=float(scale.get("z", 1.0)),
            heights=list(hm.get("m_Heights", []) or []),
        )

    # ── Alphamaps (embedded Texture2D splatmaps) ─────────────────────────────
    if want_alphamaps:
        alpha_ptrs = splat_db.get("m_AlphaTextures", []) or []
        for i, ptr in enumerate(alpha_ptrs):
            img = _read_local_texture(env, ptr)
            if img is not None:
                terrain.alphamaps.append(AlphamapData(index=i, image=img))

    return terrain


# =============================================================================
# PARSE HELPERS
# =============================================================================

def _pptr_guid(pptr, externals: List[str]) -> Optional[str]:
    """Resolve a PPtr dict to its external-asset GUID. ``m_FileID`` is a
    1-based index into the externals table; 0 means a local/embedded object."""
    if not isinstance(pptr, dict):
        return None
    fid = int(pptr.get("m_FileID", 0) or 0)
    if fid <= 0 or fid > len(externals):
        return None
    return externals[fid - 1]


def _read_local_texture(env, pptr):
    """Decode an embedded Texture2D referenced by a local PPtr (m_FileID == 0)
    into a PIL RGBA image, or None."""
    if not isinstance(pptr, dict):
        return None
    if int(pptr.get("m_FileID", 0) or 0) != 0:
        return None  # external splatmaps are not supported in this iteration
    path_id = pptr.get("m_PathID")
    for obj in env.objects:
        if obj.type.name == "Texture2D" and obj.path_id == path_id:
            try:
                image = obj.read().image
                return image.convert("RGBA") if image.mode != "RGBA" else image
            except Exception:
                return None
    return None


def _vec(d, key: str, default: float) -> float:
    if isinstance(d, dict):
        return float(d.get(key, default))
    return default
