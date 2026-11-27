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

That is the form of a terrain saved before Unity 2018.3. Since then (and in
every terrain a later Unity has opened and upgraded):

    SplatDatabase.m_TerrainLayers[] -> each layer is a ``TerrainLayer`` asset
                                  of its own, a ``.terrainlayer`` file, which
                                  holds the textures, tiling, metallic and
                                  smoothness. Unity writes the upgraded ones
                                  into ``Assets/_TerrainAutoUpgrade``.
    Heightmap.m_Resolution     -> one number for both sides of the grid

Both forms are read.

Parsing is delegated to UnityPy, which reads the SerializedFile via the type
tree embedded in the asset. UnityPy is an OPTIONAL dependency: it is imported
lazily so the rest of the converter runs without it, and is only required when
a Unity terrain is actually parsed. Use ``unitypy_available()`` to flag it as a
missing component in the Unity platform's dependency check.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


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
                       want_alphamaps: bool = True,
                       find_asset: Optional[Callable[[str], Optional[Path]]] = None) -> TerrainData:
    """
    Parse a Unity ``TerrainData`` ``.asset``. Layers are always read (cheap);
    the heightmap grid and embedded splatmaps are only decoded when requested,
    so a materials-only run never pays for them.

    ``find_asset`` gives the file of an asset by its guid, for a terrain
    whose layers are assets of their own. A layer it does not find is looked
    for among the ``.terrainlayer`` files of the Unity project the terrain
    lies in (``terrain_layer_files``).
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
    # Since Unity 2018.3: each layer an asset of its own.
    for i, reference in enumerate(splat_db.get("m_TerrainLayers") or []):
        guid = _pptr_guid(reference, externals)
        layer_file = (find_asset(guid) if find_asset and guid else None) or \
            (terrain_layer_files(path).get(guid) if guid else None)
        terrain.layers.append(read_terrain_layer(i, layer_file))
    # Before: the layers inside the terrain itself.
    for i, splat in enumerate(splat_db.get("m_Splats") or []):
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
        # One resolution for both sides since Unity 2019.3.
        resolution = int(hm.get("m_Resolution", 0) or 0)
        terrain.heightmap = HeightmapData(
            width=int(hm.get("m_Width", 0) or 0) or resolution,
            height=int(hm.get("m_Height", 0) or 0) or resolution,
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
# TERRAIN LAYERS  (a layer as an asset of its own)
# =============================================================================

# {a Unity project's Assets folder: {guid: its .terrainlayer file}}
_layer_files_of: Dict[Path, Dict[str, Path]] = {}


def terrain_layer_files(terrain_asset: Path) -> Dict[str, Path]:
    """``{guid: file}`` of every ``.terrainlayer`` file in the Unity project
    a terrain lies in: the nearest folder called ``Assets`` above it, searched
    once. Empty when the terrain lies in no such folder.

    A terrain's layers need not lie beside it: the ones Unity makes when it
    upgrades an older terrain go to ``Assets/_TerrainAutoUpgrade``, outside
    any pack's own folder."""
    assets = next((folder for folder in Path(terrain_asset).resolve().parents if folder.name == "Assets"), None)
    if assets is None:
        return {}
    if assets not in _layer_files_of:
        found: Dict[str, Path] = {}
        for meta in assets.rglob("*.terrainlayer.meta"):
            guid = re.search(r"^guid: ([0-9a-f]{32})", meta.read_text(encoding="utf-8", errors="ignore"), re.M)
            if guid:
                found[guid.group(1)] = meta.with_suffix("")
        _layer_files_of[assets] = found
    return _layer_files_of[assets]


def read_terrain_layer(index: int, layer_file: Optional[Path]) -> SplatLayer:
    """The layer a ``.terrainlayer`` file holds, read from its text form. A
    file that is missing, or is not text, gives a layer without textures."""
    try:
        text = Path(layer_file).read_text(encoding="utf-8") if layer_file else ""
    except (OSError, UnicodeDecodeError):
        text = ""

    def guid_of(key: str) -> Optional[str]:
        found = re.search(rf"^\s*{key}: \{{fileID: \d+, guid: ([0-9a-f]{{32}})", text, re.M)
        return found.group(1) if found else None

    def number(key: str, default: float) -> float:
        found = re.search(rf"^\s*{key}: (-?[\d.eE+-]+)\s*$", text, re.M)
        return float(found.group(1)) if found else default

    def pair(key: str, default: float) -> tuple:
        found = re.search(rf"^\s*{key}: \{{x: (-?[\d.eE+-]+), y: (-?[\d.eE+-]+)\}}", text, re.M)
        return (float(found.group(1)), float(found.group(2))) if found else (default, default)

    tile_size, tile_offset = pair("m_TileSize", 1.0), pair("m_TileOffset", 0.0)
    return SplatLayer(
        index=index,
        albedo_guid=guid_of("m_DiffuseTexture"),
        normal_guid=guid_of("m_NormalMapTexture"),
        tile_size_x=tile_size[0], tile_size_y=tile_size[1],
        tile_offset_x=tile_offset[0], tile_offset_y=tile_offset[1],
        metallic=number("m_Metallic", 0.0),
        smoothness=number("m_Smoothness", 0.0),
    )


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
