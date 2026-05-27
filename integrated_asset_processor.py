#!/usr/bin/env python3
"""
Integrated Unity Prefab + Material Asset Processor

Reads Unity prefabs, finds referenced materials, generates O3DE materials
with textures, and copies everything to a homogenised folder structure.

Component processing is handled by auto-discovered modules in components/.
Add or remove processors by dropping files into that directory.
"""

import yaml
import json
import os
import re
import shutil
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

from components import load_component_processors, build_dispatch_table
from components.base import ProcessingContext

# Pillow is a soft dependency, only required when the user enables
# "Convert Smoothness Textures to Roughness" in the Config tab. The plain
# copy path used everywhere else does not need it.
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    Image = None        # type: ignore
    PIL_AVAILABLE = False


@dataclass
class Transform:
    """Unity transform data"""
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    
    def is_uniform_scale(self, tolerance: float = 0.0001) -> bool:
        return abs(self.scale[0] - self.scale[1]) < tolerance and \
               abs(self.scale[1] - self.scale[2]) < tolerance


@dataclass
class UnityComponent:
    """Unity component reference"""
    type_name: str
    file_id: str
    data: Dict = field(default_factory=dict)


@dataclass
class GameObject:
    """Unity GameObject representation"""
    file_id: str
    name: str
    transform: Transform
    components: List[UnityComponent] = field(default_factory=list)
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    mesh_guid: Optional[str] = None
    material_guids: List[str] = field(default_factory=list)
    has_rigidbody: bool = False
    rigidbody_data: Optional[Dict] = None
    colliders: List[Dict] = field(default_factory=list)
    is_prefab_instance: bool = False
    prefab_source_guid: Optional[str] = None
    component_data: Dict[str, Any] = field(default_factory=dict)

    # =============================================================================
    # Prefab-instance override capture (populated only when is_prefab_instance=True)
    # =============================================================================
    # Raw `m_Modification.m_Modifications` entries kept verbatim. Each entry is a
    # dict with keys like {target: {fileID, guid, type}, propertyPath, value,
    # objectReference}. The override emitter walks this list and dispatches by
    # propertyPath. Transform overrides are also reflected in self.transform for
    # convenience, but the raw entries remain here so the coverage tracker can
    # account for everything.
    prefab_modifications: List[Dict] = field(default_factory=list)
    prefab_added_components: List[Dict] = field(default_factory=list)
    prefab_removed_components: List[Dict] = field(default_factory=list)
    prefab_added_gameobjects: List[Dict] = field(default_factory=list)  # processor-specific state


class CoverageTracker:
    """
    =============================================================================
    Records what the converter saw vs. what it actually emitted.

    Every Unity construct that crosses the converter — component types, prefab
    override propertyPaths, missing GUIDs, unsupported shaders — gets logged
    here so the end-of-run coverage.json gives the user an honest accounting of
    coverage and a punch list of what was lost.

    Intentionally append-only and cheap: no policy lives here, only counting.
    =============================================================================
    """

    def __init__(self):
        # Component types observed during parse, with handler resolution.
        # {unity_type: {"seen": int, "handled": bool, "emitted_handler": str|None}}
        self.components: Dict[str, Dict[str, Any]] = {}

        # Prefab override propertyPaths observed on PrefabInstance blocks.
        # {propertyPath_pattern: {"seen": int, "handled": int, "examples": [..]}}
        # The pattern strips Array.data[N] indices to "Array.data[*]" so a single
        # key collects all material-slot overrides regardless of slot number.
        self.prefab_overrides: Dict[str, Dict[str, Any]] = {}

        # Other prefab-instance override categories.
        self.added_components: int = 0
        self.removed_components: int = 0
        self.added_gameobjects: int = 0

        # Missing-asset reports, deduped.
        self.missing_textures: Set[str] = set()
        self.missing_meshes:   Set[str] = set()
        self.missing_materials: Set[str] = set()
        self.missing_prefabs:  Set[str] = set()

        # Light types seen, with counts (one bucket per Unity m_Type).
        self.light_types: Dict[int, int] = {}

        # Free-form notes the user should know about.
        self.warnings: List[str] = []

    # -------------------------------------------------------------------------
    # COMPONENT TYPES (observed during prefab/scene parse)
    # -------------------------------------------------------------------------

    def record_component(self, unity_type: str, handler_name: Optional[str]) -> None:
        bucket = self.components.setdefault(
            unity_type,
            {"seen": 0, "handled": handler_name is not None, "emitted_handler": handler_name},
        )
        bucket["seen"] += 1
        if handler_name and not bucket["handled"]:
            bucket["handled"] = True
            bucket["emitted_handler"] = handler_name

    # -------------------------------------------------------------------------
    # PREFAB OVERRIDES (m_Modifications + sibling fields)
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_property_path(prop_path: str) -> str:
        """
        Collapse indexed array entries into a single bucket so the report
        doesn't list 30 separate `m_Materials.Array.data[0..29]` lines.
        """
        return re.sub(r'\[\d+\]', '[*]', prop_path or '')

    def record_modification(self, prop_path: str, handled: bool,
                            example_value: Any = None) -> None:
        key    = self._normalize_property_path(prop_path)
        bucket = self.prefab_overrides.setdefault(
            key, {"seen": 0, "handled": 0, "examples": []}
        )
        bucket["seen"] += 1
        if handled:
            bucket["handled"] += 1
        if example_value is not None and len(bucket["examples"]) < 3:
            bucket["examples"].append(str(example_value)[:80])

    def record_added_component(self) -> None:
        self.added_components += 1

    def record_removed_component(self) -> None:
        self.removed_components += 1

    def record_added_gameobject(self) -> None:
        self.added_gameobjects += 1

    # -------------------------------------------------------------------------
    # ASSET RESOLUTION (missing GUIDs)
    # -------------------------------------------------------------------------

    def record_missing_texture(self, guid: str) -> None:
        if guid: self.missing_textures.add(guid)

    def record_missing_mesh(self, guid: str) -> None:
        if guid: self.missing_meshes.add(guid)

    def record_missing_material(self, guid: str) -> None:
        if guid: self.missing_materials.add(guid)

    def record_missing_prefab(self, guid: str) -> None:
        if guid: self.missing_prefabs.add(guid)

    # -------------------------------------------------------------------------
    # LIGHTS
    # -------------------------------------------------------------------------

    def record_light_type(self, unity_type: int) -> None:
        self.light_types[unity_type] = self.light_types.get(unity_type, 0) + 1

    # -------------------------------------------------------------------------
    # WARNINGS
    # -------------------------------------------------------------------------

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # -------------------------------------------------------------------------
    # SERIALIZE
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        unhandled_components = sorted(
            t for t, info in self.components.items() if not info["handled"]
        )
        unhandled_overrides = sorted(
            p for p, info in self.prefab_overrides.items() if info["handled"] == 0
        )
        return {
            "components": dict(sorted(self.components.items())),
            "unhandled_component_types": unhandled_components,
            "prefab_overrides":          dict(sorted(self.prefab_overrides.items())),
            "unhandled_override_paths":  unhandled_overrides,
            "prefab_added_components":   self.added_components,
            "prefab_removed_components": self.removed_components,
            "prefab_added_gameobjects":  self.added_gameobjects,
            "missing_assets": {
                "textures":  sorted(self.missing_textures),
                "meshes":    sorted(self.missing_meshes),
                "materials": sorted(self.missing_materials),
                "prefabs":   sorted(self.missing_prefabs),
            },
            "light_types_seen": {
                {0: "Spot", 1: "Directional", 2: "Point", 3: "Area"}.get(t, f"unknown({t})"):
                count for t, count in sorted(self.light_types.items())
            },
            "warnings": self.warnings,
        }


class AssetDatabase:
    """Central asset database for GUID resolution"""
    
    def __init__(self, unity_assets_root: Path):
        self.unity_assets_root = unity_assets_root
        self.guid_to_path: Dict[str, Path] = {}
        self.material_cache: Dict[str, Dict] = {}
        self.texture_extensions = {'.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff', '.bmp', '.psd', '.exr', '.hdr'}
        self.mesh_extensions = {'.fbx', '.obj', '.dae', '.blend', '.3ds', '.max', '.ma', '.mb'}
        
        print("Building asset GUID index...")
        self._build_guid_index()
        print(f"Indexed {len(self.guid_to_path)} assets")
    
    def _build_guid_index(self) -> None:
        """Build GUID -> file path index from .meta files"""
        for meta_file in self.unity_assets_root.rglob('*.meta'):
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                guid_match = re.search(r'guid:\s*([a-f0-9]+)', content)
                if guid_match:
                    guid = guid_match.group(1)
                    asset_file = Path(str(meta_file)[:-5])  # Remove .meta
                    if asset_file.exists():
                        self.guid_to_path[guid] = asset_file
            except Exception:
                continue
    
    def resolve_guid(self, guid: str) -> Optional[Path]:
        """Resolve GUID to file path"""
        return self.guid_to_path.get(guid)

    def path_to_guid(self, asset_path: Path) -> Optional[str]:
        """Reverse lookup: file path → Unity GUID (by reading the .meta sidecar)."""
        meta = asset_path.parent / (asset_path.name + '.meta')
        if not meta.exists():
            return None
        try:
            with open(meta, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('guid:'):
                        return line.split(':', 1)[1].strip()
        except Exception:
            return None
        return None
    
    def parse_material(self, material_path: Path) -> Optional[Dict]:
        """Parse Unity material file"""
        if str(material_path) in self.material_cache:
            return self.material_cache[str(material_path)]
        
        if not material_path.exists() or material_path.suffix != '.mat':
            return None
        
        try:
            with open(material_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            doc_pattern = r'---\s+!u!\d+\s+&(\d+)\n(.*?)(?=---\s+!u!|\Z)'
            matches = re.findall(doc_pattern, content, re.DOTALL)
            
            for anchor, doc_content in matches:
                clean_content = re.sub(r'!u!\d+', '', doc_content)
                
                try:
                    doc = yaml.safe_load(clean_content)
                    if doc and 'Material' in doc:
                        material_data = self._extract_material_data(doc['Material'])
                        self.material_cache[str(material_path)] = material_data
                        return material_data
                except yaml.YAMLError:
                    continue
            
            return None
        
        except Exception as e:
            print(f"Error parsing material {material_path}: {e}")
            return None
    
    def _extract_material_data(self, material_data: Dict) -> Dict:
        """Extract material properties and texture references"""
        TEXTURE_MAP = {
            # baseColor — Unity Standard, URP, HDRP, and common custom-shader aliases
            '_MainTex':          'baseColor',
            '_BaseMap':          'baseColor',
            '_BaseColorMap':     'baseColor',
            '_Albedo':           'baseColor',
            '_AlbedoMap':        'baseColor',
            '_AlbedoTex':        'baseColor',
            '_Diffuse':          'baseColor',
            '_DiffuseMap':       'baseColor',
            '_DiffuseTex':       'baseColor',
            '_ColorMap':         'baseColor',
            # normal
            '_BumpMap':          'normal',
            '_NormalMap':        'normal',
            '_NormalTex':        'normal',
            # metallic — Standard packs gloss in alpha, treated below
            '_MetallicGlossMap': 'metallic',
            '_MetallicMap':      'metallic',
            '_MetallicTex':      'metallic',
            '_Metallic_Map':     'metallic',
            # specular workflow
            '_SpecGlossMap':     'specular',
            '_SpecularMap':      'specular',
            # occlusion / AO
            '_OcclusionMap':     'occlusion.specular',  # O3DE uses occlusion.specularTextureMap
            '_AOMap':            'occlusion.specular',
            '_AmbientOcclusion': 'occlusion.specular',
            '_AmbientOcclusionMap': 'occlusion.specular',
            # emissive
            '_EmissionMap':      'emissive',
            '_EmissionTex':      'emissive',
            '_EmissiveMap':      'emissive',
            '_Emissive':         'emissive',
            # height / parallax
            '_HeightMap':        'height',
            '_ParallaxMap':      'height',
            '_DisplacementMap':  'height',
        }

        # Texture property names that are KNOWN to exist but intentionally not
        # mapped — they don't have a clean 1:1 O3DE equivalent and silently
        # mapping them would inject the wrong data. Listed here so the unmapped-
        # property warning below doesn't yell about them on every material.
        IGNORE_UNMAPPED = {
            '_DetailAlbedoMap', '_DetailMask', '_DetailNormalMap',
            '_LightTextureB0', '_VectorNoise', '_texcoord',
            # _Composite is channel-packed and shader-specific (metallic/AO/rough
            # in different channels per shader); needs a per-shader rule.
            '_Composite', '_CompositeMap', '_MOHS', '_MaskMap',
        }
        
        # NOTE: _Metallic, _Smoothness, _Glossiness, _GlossMapScale are handled
        # in the dedicated metallic/roughness post-pass below — O3DE's factor
        # vs lowerBound/upperBound semantics depend on whether a texture is bound.
        PROPERTY_MAP = {
            '_Color': 'baseColor.color',
            '_BaseColor': 'baseColor.color',
            '_BumpScale': 'normal.factor',
            '_OcclusionStrength': 'occlusion.specularFactor',  # O3DE uses occlusion.specularFactor
            '_EmissionColor': 'emissive.color',
        }
        
        extracted = {
            'name': material_data.get('m_Name', 'Material'),
            'shader': material_data.get('m_Shader', {}).get('m_Name', ''),
            'textures': {},
            'properties': {},
            # GUIDs that came from Unity's _MetallicGlossMap. _process_material
            # uses this set to decide whether the roughness slot should sample
            # from an alpha-inverted re-bake rather than the raw Unity texture.
            'metallic_gloss_source_guids': set(),
        }

        saved_properties = material_data.get('m_SavedProperties', {})

        # Extract textures
        tex_envs = saved_properties.get('m_TexEnvs', [])
        unmapped_with_texture: List[str] = []
        for tex_prop in tex_envs:
            for prop_name, tex_data in tex_prop.items():
                texture_ref = tex_data.get('m_Texture', {})
                guid = texture_ref.get('guid', '')

                if not guid:
                    continue

                if prop_name in TEXTURE_MAP:
                    o3de_prop = TEXTURE_MAP[prop_name]
                    # Don't let a later alias clobber an already-resolved slot
                    # (e.g. _BumpMap and _NormalMap both → 'normal'; keep first).
                    if o3de_prop not in extracted['textures']:
                        extracted['textures'][o3de_prop] = guid

                    # Unity's _MetallicGlossMap contains metallic in RGB and smoothness in Alpha
                    # O3DE needs the same texture for both metallic and roughness
                    if prop_name == '_MetallicGlossMap':
                        if 'roughness' not in extracted['textures']:
                            extracted['textures']['roughness'] = guid
                        extracted['metallic_gloss_source_guids'].add(guid)
                elif prop_name not in IGNORE_UNMAPPED:
                    unmapped_with_texture.append(prop_name)

        if unmapped_with_texture:
            # Record on the extracted dict so _process_material can surface a
            # single concise warning per material (with the material name and
            # shader path for context).
            extracted['unmapped_texture_props'] = unmapped_with_texture
        
        # Extract float properties
        floats = saved_properties.get('m_Floats', [])
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name in PROPERTY_MAP:
                    o3de_prop = PROPERTY_MAP[prop_name]
                    extracted['properties'][o3de_prop] = value
        
        # Extract colors
        colors = saved_properties.get('m_Colors', [])
        for color_prop in colors:
            for prop_name, color_data in color_prop.items():
                if prop_name in PROPERTY_MAP:
                    o3de_prop = PROPERTY_MAP[prop_name]
                    r = color_data.get('r', 1.0)
                    g = color_data.get('g', 1.0)
                    b = color_data.get('b', 1.0)
                    a = color_data.get('a', 1.0)
                    extracted['properties'][o3de_prop] = [r, g, b, a]

        # ---------------------------------------------------------------
        # Metallic / Roughness reconciliation
        #
        # O3DE StandardPBR exposes these properties with TEXTURE-AWARE semantics:
        #
        #   metallic
        #     - texture bound    → no factor dial; the texture is the value.
        #     - no texture       → metallic.factor ∈ [0, 1].
        #
        #   roughness
        #     - texture bound    → no factor; instead roughness.lowerBound /
        #                          roughness.upperBound remap the sampled range.
        #                          (0 = shiny, 1 = rough.)
        #     - no texture       → roughness.factor ∈ [0, 1]. (0 = shiny, 1 = rough.)
        #
        # Unity stores SMOOTHNESS (= 1 − roughness):
        #
        #   No map:  _Smoothness (URP) or _Glossiness (Standard) is the scalar.
        #   Map:     sampled smoothness is multiplied by _GlossMapScale (Standard)
        #            or _Smoothness (URP, which reuses the scalar in both roles).
        #
        # Mapping when a texture is bound:
        #   multiplier `s`  ⇒  final smoothness ∈ [0, s]
        #                  ⇒  final roughness  ∈ [1 − s, 1]
        #                  ⇒  O3DE lowerBound = 1 − s, upperBound = 1.0
        #
        # Note: Unity's _MetallicGlossMap stores smoothness in the alpha channel.
        # O3DE samples the bound texture directly as roughness, so the alpha would
        # have to be pre-inverted at copy time for the texture branch to look
        # correct. That texture-channel fix is a separate concern from the
        # factor / bound semantics handled here.
        # ---------------------------------------------------------------
        raw_metallic        = None
        raw_smoothness      = None
        raw_smoothness_mult = None
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name == '_Metallic':
                    raw_metallic = float(value)
                elif prop_name in ('_Smoothness', '_Glossiness'):
                    raw_smoothness = float(value)
                elif prop_name == '_GlossMapScale':
                    raw_smoothness_mult = float(value)

        has_metallic_tex  = 'metallic'  in extracted['textures']
        has_roughness_tex = 'roughness' in extracted['textures']

        # Metallic: factor is only meaningful without a texture.
        if not has_metallic_tex and raw_metallic is not None:
            extracted['properties']['metallic.factor'] = raw_metallic

        # Roughness: pick factor vs bounds based on whether a texture is bound.
        if has_roughness_tex:
            # Standard's _GlossMapScale takes precedence over _Smoothness/_Glossiness
            # when a gloss map is present (URP collapses both into _Smoothness).
            multiplier = (raw_smoothness_mult
                          if raw_smoothness_mult is not None
                          else raw_smoothness)
            if multiplier is not None:
                lower = max(0.0, min(1.0, 1.0 - float(multiplier)))
                extracted['properties']['roughness.lowerBound'] = lower
                extracted['properties']['roughness.upperBound'] = 1.0
        elif raw_smoothness is not None:
            extracted['properties']['roughness.factor'] = max(
                0.0, min(1.0, 1.0 - raw_smoothness)
            )

        # ---------------------------------------------------------------
        # Transparency / Cutout Detection
        # Unity URP/HDRP:
        #   _Surface=0  = Opaque
        #   _Surface=1  = Transparent (blended)
        #   _AlphaClip=1 on an opaque surface (_Surface=0) = Cutout
        # Unity Standard shader:
        #   _Mode=0 = Opaque, _Mode=1 = Cutout, _Mode>=2 = Transparent
        #   _Cutoff = alpha clip threshold (0..1)
        #
        # O3DE opacity modes:
        #   "Opaque"  — no transparency
        #   "Cutout"  — opaque with alpha-tested mask, uses opacity.alphaSource + factor
        #   "Blended" — true alpha blending
        # ---------------------------------------------------------------
        raw_floats = {}
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name in ('_Mode', '_Surface', '_Blend', '_AlphaClip', '_Cutoff'):
                    raw_floats[prop_name] = float(value)

        is_transparent = (raw_floats.get('_Surface', 0) == 1
                          or raw_floats.get('_Mode', 0) >= 2)
        is_cutout      = (not is_transparent
                          and (raw_floats.get('_AlphaClip', 0) == 1
                               or raw_floats.get('_Mode', 0) == 1))

        # Unity stores alpha in the baseColor texture's alpha channel for both
        # cutout and transparent surfaces. O3DE StandardPBR requires alphaSource
        # to be set explicitly, otherwise the mask/blend is ignored and the
        # material renders as fully opaque regardless of opacity.mode.
        if is_transparent:
            extracted['properties']['opacity.mode']        = "Blended"
            extracted['properties']['opacity.alphaSource'] = "Packed"
        elif is_cutout:
            extracted['properties']['opacity.mode']        = "Cutout"
            extracted['properties']['opacity.alphaSource'] = "Packed"
            extracted['properties']['opacity.factor']      = raw_floats.get('_Cutoff', 0.5)

        return extracted



# ---------------------------------------------------------------------------
# FBX UTILITIES  (axis detection + mesh node name extraction)
# ---------------------------------------------------------------------------

def read_fbx_mesh_node_names(fbx_path: Path) -> List[str]:
    """Extract mesh node names from a binary FBX file.

    In binary FBX, each scene object is stored as a Model property string
    with the format  "NodeName\\x00\\x01Model".  Scanning backwards from
    that separator gives the node name.

    Returns a list of unique node names found, in file order.
    Returns [] for non-binary or unreadable FBX files.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(262144)   # 256 KB covers node table for all common FBX files
    except Exception:
        return []

    if data[:20] != b'Kaydara FBX Binary  ':
        return []

    names: List[str] = []
    marker = b'\x00\x01Model'
    pos = 0
    while True:
        idx = data.find(marker, pos)
        if idx < 0:
            break
        # Walk backwards collecting printable ASCII bytes — that's the node name
        end = idx
        start = end
        while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
            start -= 1
        name = data[start:end].decode('ascii', errors='ignore').strip()
        if len(name) >= 2 and name not in names:
            names.append(name)
        pos = idx + len(marker)

    return names


def read_fbx_material_names(fbx_path: Path) -> List[str]:
    """Extract material names from a binary FBX file, in file order.

    Binary FBX stores each scene object as `<Name>\\x00\\x01<Class>`. The
    Material class marker is `\\x00\\x01Material`. Scanning backwards from
    that separator gives the material name as the FBX engine sees it —
    which is what SceneAPI's ModelAssetBuilderComponent later exposes as
    `MaterialAsset::m_name` / `ModelMaterialSlot::m_displayName`. That is
    the exact string the O3DE MaterialComponent label resolver matches
    against, so it is the only correct key for `materialsByLabel`.

    Returns [] for non-binary or unreadable FBX files. Uses a larger read
    window than `read_fbx_mesh_node_names` because the Materials block in
    the Objects section is typically further into the file than Models.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(1048576)   # 1 MB covers the Material block on common assets
    except Exception:
        return []

    if data[:20] != b'Kaydara FBX Binary  ':
        return []

    names: List[str] = []
    marker = b'\x00\x01Material'
    pos = 0
    while True:
        idx = data.find(marker, pos)
        if idx < 0:
            break
        end = idx
        start = end
        while start > 0 and 0x20 <= data[start - 1] <= 0x7E:
            start -= 1
        name = data[start:end].decode('ascii', errors='ignore').strip()
        if len(name) >= 1 and name not in names:
            names.append(name)
        pos = idx + len(marker)

    return names


def read_fbx_up_axis(fbx_path: Path) -> int:
    """Read UpAxis from an FBX binary file's GlobalSettings block.

    FBX binary encodes: \x06\x00\x00\x00UpAxis ... I <int32 value>
    Value 1 = Y-up (Maya-style), 2 = Z-up (Blender-style), -1 = unknown.

    O3DE is Z-up.  Y-up FBX files need a coordinate correction sidecar so
    that O3DE's asset processor imports them in the correct orientation.
    """
    try:
        with open(fbx_path, 'rb') as f:
            data = f.read(65536)  # GlobalSettings appears near the top

        gs_pos = data.find(b'GlobalSettings')
        if gs_pos < 0:
            return -1

        # Binary FBX stores string "UpAxis" as: uint32-length(6) + "UpAxis"
        up_pos = data.find(b'\x06\x00\x00\x00UpAxis', gs_pos)
        if up_pos < 0:
            return -1

        # After the 10-byte prefix, the P-record continues:
        #   S + uint32(3) + "int" + S + uint32(7) + "Integer" + S + uint32(0)
        # then type marker 'I' (0x49) + int32 little-endian value.
        # Scan the next 60 bytes for: 0x49 + [0-2] + 0x00 0x00 0x00
        chunk = data[up_pos + 10 : up_pos + 70]
        for i in range(len(chunk) - 4):
            if (chunk[i] == 0x49
                    and chunk[i + 2] == 0
                    and chunk[i + 3] == 0
                    and chunk[i + 4] == 0):
                val = chunk[i + 1]
                if 0 <= val <= 2:
                    return val
        return -1

    except Exception:
        return -1


def build_fbx_node_paths(mesh_entities: list, all_game_objects: dict,
                          fbx_stem: str, fbx_node_names: List[str]) -> dict:
    """Derive FBX node paths from the Unity prefab hierarchy.

    Uses actual FBX node names (read from the binary FBX) for the path
    segments, not GO names — GO names can differ from FBX node names.

    Matching strategy per entity:
      1. Exact name match between go.name and a known FBX node name.
      2. Single-entity + single-node fallback: use the one available node.
      3. No match: fall back to go.name with a warning (may not resolve in O3DE).

    Returns {entity_file_id: "RootNode.ActualFBXNodeName[.Child...]"}.
    """
    mesh_ids = {go.file_id for go in mesh_entities}
    fbx_node_set = set(fbx_node_names)

    # Root of this FBX group = entity whose parent is not in the group
    root_go = next(
        (go for go in mesh_entities if go.parent_id not in mesh_ids),
        mesh_entities[0]
    )

    result = {}

    def resolve_node_name(go_name: str) -> str:
        """Map a GO name to the best available FBX node name."""
        if go_name in fbx_node_set:
            return go_name
        # Single entity, single FBX node — unambiguous fallback
        if len(mesh_entities) == 1 and len(fbx_node_names) == 1:
            return fbx_node_names[0]
        return go_name   # best-effort; O3DE may not find it

    def recurse(go, parent_path):
        node_name = resolve_node_name(go.name)
        node_path = f"{parent_path}.{node_name}"
        result[go.file_id] = node_path
        for child_id in go.children_ids:
            child = all_game_objects.get(child_id)
            if child and child.file_id in mesh_ids:
                recurse(child, node_path)

    recurse(root_go, "RootNode")
    return result


def write_fbx_assetinfo(fbx_dest_path: Path, fbx_stem: str,
                         entity_node_map: dict, log=print,
                         collider_entity_node_map: dict = None) -> None:
    """Write an O3DE .assetinfo with one named MeshGroup per mesh entity.

    Group name format: "{fbx_stem}-{entity_name}"  e.g. "Closet_A-Glass_L"
    O3DE lowercases the output: closet_a-glass_l.fbx.azmodel

    Each group selects exactly its FBX node; all other mesh nodes are unselected.
    Rules mirror O3DE's auto-generated defaults: StaticMeshAdvancedRule (vertex color Col0),
    MaterialRule, CoordinateSystemRule (useAdvancedData=true), and LodRule.
    Y-up FBX files (Maya-style, up_axis==1) get a 90° pitch rotation baked into
    the CoordinateSystemRule so the mesh imports upright without a transform workaround.

    When collider_entity_node_map is provided, one PhysX convex MeshGroup is also
    written per collider entity, targeting the parent node of the visual mesh node.
    This produces the .pxmesh file that EditorMeshColliderComponent references.
    """
    import json as _json
    import uuid as _uuid

    # Detect Y-up FBX — up_axis==1 means Y-up (Maya), 2 means Z-up (matches O3DE)
    up_axis = read_fbx_up_axis(fbx_dest_path)
    is_y_up = (up_axis == 1)
    if is_y_up:
        log(f"    [Mesh] Y-up detected — adding 90° pitch to CoordinateSystemRule")

    # Quaternion for 90° rotation around X axis (Y-up → Z-up correction)
    Y_UP_ROTATION = [0.7071067690849304, 0.0, 0.0, 0.7071067094802856]

    coordinate_rule = {"$type": "CoordinateSystemRule", "useAdvancedData": True}
    if is_y_up:
        coordinate_rule["rotation"] = Y_UP_ROTATION

    all_node_paths = list(entity_node_map.values())
    groups = []

    # -------------------------------------------------------------------------
    # VISUAL MESH GROUPS  ({07B356B7...} MeshGroup)
    # One group per entity — produces the .azmodel render asset.
    # -------------------------------------------------------------------------
    for entity_name, node_path in entity_node_map.items():
        group_name = f"{fbx_stem}-{entity_name}"
        unselected = [p for p in all_node_paths if p != node_path]
        groups.append({
            "$type": "{07B356B7-3635-40B5-878A-FAC4EFD5AD86} MeshGroup",
            "name": group_name,
            "nodeSelectionList": {
                "selectedNodes": ["RootNode", node_path],
                "unselectedNodes": unselected
            },
            "rules": {
                "rules": [
                    {"$type": "StaticMeshAdvancedRule", "vertexColorStreamName": "Col0"},
                    {"$type": "MaterialRule"},
                    coordinate_rule,
                    {"$type": "{6E796AC8-1484-4909-860A-6D3F22A7346F} LodRule"}
                ]
            },
            "id": "{" + str(_uuid.uuid4()).upper() + "}"
        })

    # -------------------------------------------------------------------------
    # PHYSX MESH GROUPS  ({5B03C8E6...} MeshGroup)
    # One convex group per collider entity — produces the .pxmesh physics asset.
    # Targets the parent node of the visual mesh node so all geometry is captured.
    # -------------------------------------------------------------------------
    if collider_entity_node_map:
        physx_coord_rule = {"$type": "CoordinateSystemRule", "useAdvancedData": True}
        if is_y_up:
            physx_coord_rule["rotation"] = Y_UP_ROTATION

        for entity_name, node_path in collider_entity_node_map.items():
            parts = node_path.split(".")
            parent_path   = ".".join(parts[:-1]) if len(parts) > 1 else node_path
            mesh_node_name = parts[-1]

            groups.append({
                "$type": "{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45B} MeshGroup",
                "id": "{" + str(_uuid.uuid4()).upper() + "}",
                "name": f"{fbx_stem}-{entity_name}",
                "NodeSelectionList": {
                    "selectedNodes": ["RootNode", parent_path],
                    "unselectedNodes": [{}]
                },
                "export method": 1,
                "ConvexAssetParams": {
                    "Use16bitIndices": True,
                    "CheckZeroAreaTriangles": True
                },
                "PhysicsMaterialSlots": {
                    "Slots": [{"Name": mesh_node_name}]
                },
                "rules": {
                    "rules": [physx_coord_rule]
                }
            })

        log(f"    [Mesh] Added {len(collider_entity_node_map)} PhysX MeshGroup(s)")

    sidecar = Path(str(fbx_dest_path) + ".assetinfo")
    try:
        with open(sidecar, 'w', encoding='utf-8') as f:
            _json.dump({"values": groups}, f, indent=4)
        log(f"    [Mesh] .assetinfo written — {len(groups)} group(s) ({sidecar.name})")
    except Exception as e:
        log(f"    [Mesh] WARNING: Could not write .assetinfo: {e}")


class IntegratedAssetProcessor:
    """Processes Unity prefabs with materials to O3DE format"""
    
    def __init__(self, unity_assets_root: Path, output_root: Path,
                 log_callback=None,
                 convert_smoothness_to_roughness: bool = False):
        self.unity_assets_root = unity_assets_root
        self.output_root = output_root
        self.log = log_callback or print

        # Per-run config flags
        self.convert_smoothness_to_roughness = convert_smoothness_to_roughness

        self.asset_db = AssetDatabase(unity_assets_root)
        
        # Output structure
        self.prefabs_dir = output_root / "Prefabs"
        self.materials_dir = output_root / "Materials"
        self.textures_dir = output_root / "Textures"
        self.meshes_dir = output_root / "Meshes"
        # Internal converter bookkeeping that O3DE does not consume:
        # per-prefab .entitymap.json sidecars, asset_index.json, coverage.json.
        # Kept out of Prefabs/ so the O3DE Asset Processor never scans them.
        self.importer_data_dir = output_root / ".ImporterData"

        # Create directories
        self.prefabs_dir.mkdir(parents=True, exist_ok=True)
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.textures_dir.mkdir(parents=True, exist_ok=True)
        self.meshes_dir.mkdir(parents=True, exist_ok=True)
        self.importer_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Track processed assets
        self.processed_materials: Dict[str, str] = {}  # guid -> output_path
        self.processed_textures: Dict[str, str] = {}  # guid -> output_path
        # GUIDs whose Unity _MetallicGlossMap has been re-baked with an inverted
        # alpha channel for use as an O3DE roughness texture. Keyed by source
        # texture GUID; value is the output relative path (Textures/Foo_Roughness.png).
        self.processed_inverted_textures: Dict[str, str] = {}
        self.processed_meshes: Dict[str, Path] = {}  # guid -> output Path
        self.processed_prefabs: Set[str] = set()  # Track processed prefab GUIDs

        # Component processing stats — accumulated by processors via ctx.stats
        self.stats: Dict[str, int] = {}

        # =====================================================================
        # Coverage tracker — populated incrementally; written by finalize()
        # =====================================================================
        self.coverage = CoverageTracker()

        # =====================================================================
        # Cross-prefab asset index. Populated as materials/meshes/prefabs are
        # processed so nested-instance override emission can resolve a GUID to
        # an O3DE assetHint. Written by finalize() as <output_root>/asset_index.json.
        # =====================================================================
        self.asset_index: Dict[str, Dict[str, Any]] = {
            "materials": {},   # {unity_mat_guid: o3de_material_assetHint}
            "meshes":    {},   # {unity_mesh_guid: fbx_output_stem}
            "prefabs":   {},   # {unity_prefab_guid: source_path_in_assets}
        }

        # In-memory cache of source-prefab entity-map sidecars, keyed by the
        # source prefab's resolved path. Avoids re-reading the same sidecar
        # when a prefab is referenced from multiple consumers.
        self._entity_map_cache: Dict[str, Optional[Dict]] = {}

        # Get project folder name for asset hints (lowercase). This is the
        # output root's basename — the folder that will sit inside the O3DE
        # project's Assets/ directory.
        self.project_name = output_root.name.lower()

        # Root prefix every assetHint must carry. O3DE's asset catalog stores
        # paths rooted at the project's Assets/ scan folder, lowercased, with
        # `assets/` as the leading segment (e.g.
        # `assets/<project>/materials/foo.azmaterial`). Hints without the
        # `assets/` prefix do not resolve at runtime.
        self.asset_hint_root = f"assets/{self.project_name}"

        self.entity_id_counter = 1000000

        # Component processor registry — auto-discovered from components/
        self.component_processors = load_component_processors(self.log)
        self.component_dispatch   = build_dispatch_table(self.component_processors)
        self.log(f"  Registered {len(self.component_processors)} component processor(s)")

        # Surface the smoothness→roughness conversion mode at run start so
        # the log makes it obvious which texture pipeline is active.
        if self.convert_smoothness_to_roughness:
            if PIL_AVAILABLE:
                self.log("  [Config] Smoothness→Roughness texture conversion: ENABLED")
            else:
                self.log("  [Config] Smoothness→Roughness texture conversion REQUESTED "
                         "but Pillow is not installed. Install with: pip install Pillow")
    
    def process_prefab(self, prefab_path: Path) -> bool:
        """Process a single Unity prefab"""
        self.log(f"\n{'='*60}")
        self.log(f"Processing prefab: {prefab_path.name}")
        self.log(f"{'='*60}")
        
        try:
            # Parse Unity prefab
            game_objects, transform_map = self._parse_unity_prefab(prefab_path)
            
            if not game_objects:
                self.log("  ⚠ No GameObjects found in prefab")
                return False
            
            # Find root GameObject
            root_go = None
            for go in game_objects.values():
                if go.parent_id is None:
                    root_go = go
                    break
            
            if not root_go:
                self.log("  ⚠ No root GameObject found")
                return False
            
            self.log(f"  Found {len(game_objects)} GameObjects")
            
            # Process materials referenced by this prefab
            all_material_guids = set()
            all_mesh_guids = set()
            for go in game_objects.values():
                all_material_guids.update(go.material_guids)
                if go.mesh_guid:
                    all_mesh_guids.add(go.mesh_guid)
            
            # Count colliders and rigidbodies in this prefab
            prefab_collider_count = sum(len(go.colliders) for go in game_objects.values())
            prefab_rigidbody_count = sum(1 for go in game_objects.values() if go.has_rigidbody)

            self.log(f"  Found {len(all_material_guids)} unique material references")
            self.log(f"  Found {len(all_mesh_guids)} unique mesh references")
            self.log(f"  Found {prefab_collider_count} colliders, {prefab_rigidbody_count} rigidbodies")
            
            material_mapping = {}
            for mat_guid in all_material_guids:
                if mat_guid:
                    o3de_mat_path = self._process_material(mat_guid)
                    if o3de_mat_path:
                        material_mapping[mat_guid] = o3de_mat_path
            
            # --- Copy FBX files to output ---
            fbx_output_paths = {}   # {mesh_guid: Path}
            for mesh_guid in all_mesh_guids:
                if mesh_guid:
                    out_path = self._process_mesh(mesh_guid)
                    if out_path:
                        fbx_output_paths[mesh_guid] = out_path

            # --- Build per-entity mesh hints + write .assetinfo ---
            # mesh_mapping keyed by entity file_id (not guid) so each entity
            # gets its own named sub-mesh rather than the combined FBX model.
            mesh_mapping = {}   # {entity_file_id: assetHint}

            # FBX-internal material names per entity, in submesh order.
            # SceneAPI extracts these from the FBX as MaterialAsset::m_name,
            # and ModelMaterialSlot::m_displayName is set from that. The
            # O3DE MaterialComponent label resolver matches against exactly
            # these strings — they are the only valid keys for the
            # `materialsByLabel` map. Pair ordinally with go.material_guids.
            fbx_material_labels = {}   # {entity_file_id: [fbx_name_0, ...]}

            from collections import defaultdict
            entities_by_guid = defaultdict(list)
            for go in game_objects.values():
                if go.mesh_guid and go.mesh_guid in fbx_output_paths:
                    entities_by_guid[go.mesh_guid].append(go)

            for mesh_guid, entity_list in entities_by_guid.items():
                fbx_path = fbx_output_paths[mesh_guid]
                fbx_stem = fbx_path.name.rsplit('.', 1)[0]  # "Closet_A.FBX" → "Closet_A"

                # Read actual mesh node names from the FBX binary
                fbx_node_names = read_fbx_mesh_node_names(fbx_path)
                self.log(f"    [Mesh] FBX nodes found: {fbx_node_names}")

                # Read FBX-internal material names (Material class objects in
                # the binary FBX), in file order. This is what SceneAPI will
                # expose as ModelMaterialSlot::m_displayName at runtime.
                fbx_mat_names = read_fbx_material_names(fbx_path)
                if fbx_mat_names:
                    self.log(f"    [Mesh] FBX materials found: {fbx_mat_names}")
                else:
                    self.log(f"    [Mesh] ⚠ No FBX-internal material names "
                             f"read from {fbx_path.name} — materialsByLabel "
                             f"will be empty for entities using this mesh.")

                node_paths = build_fbx_node_paths(entity_list, game_objects, fbx_stem, fbx_node_names)
                entity_node_map = {
                    go.name: node_paths[go.file_id]
                    for go in entity_list if go.file_id in node_paths
                }

                # Entities with a MeshCollider also need a PhysX MeshGroup
                collider_entity_node_map = {
                    go.name: node_paths[go.file_id]
                    for go in entity_list
                    if go.file_id in node_paths
                    and any(c['type'] == 'MeshCollider' for c in go.colliders)
                }

                write_fbx_assetinfo(fbx_path, fbx_stem, entity_node_map, self.log,
                                    collider_entity_node_map=collider_entity_node_map or None)

                for go in entity_list:
                    if go.file_id in node_paths:
                        group_name = f"{fbx_stem}-{go.name}"
                        mesh_mapping[go.file_id] = (
                            f"{self.asset_hint_root}/meshes/{group_name}.fbx.azmodel"
                        )
                    # Per-entity material label list. Pair ordinally with the
                    # Unity MeshRenderer slot order; truncate to whichever is
                    # shorter so we never index past either array. Multi-mesh
                    # FBX caveat: this uses the FBX-wide material list, not a
                    # per-submesh Connections-resolved list. For single-mesh
                    # FBX (the common Unity case) this matches; for multi-mesh
                    # FBX with different materials per mesh node, a Connections
                    # parse would be needed.
                    if go.material_guids and fbx_mat_names:
                        slot_count = min(len(go.material_guids), len(fbx_mat_names))
                        fbx_material_labels[go.file_id] = list(fbx_mat_names[:slot_count])
            
            # Create O3DE prefab
            output_name = prefab_path.stem
            output_path = self.prefabs_dir / f"{output_name}.prefab"
            
            self._create_o3de_prefab(
                root_go,
                game_objects,
                transform_map,
                material_mapping,
                mesh_mapping,
                fbx_material_labels,
                output_path
            )
            
            self.log(f"  ✓ Created O3DE prefab: {output_path.name}")
            return True
        
        except Exception as e:
            self.log(f"  ✗ Error processing prefab: {e}")
            import traceback
            traceback.print_exc()
            return False

    # =========================================================================
    # FINALIZE — write coverage and asset-index reports
    # =========================================================================

    def finalize(self) -> None:
        """
        Write the run's coverage.json and asset_index.json into <output_root>.

        Call this exactly once, after every process_prefab() invocation in this
        run has completed. The coverage report enumerates every Unity component
        type seen, every prefab override propertyPath seen, every missing GUID,
        and every warning the converter wanted to surface. The asset index lets
        a follow-up Stage 2 scene conversion (or a re-run) resolve material /
        mesh / prefab GUIDs to O3DE asset hints without re-walking everything.
        """
        # Roll up Unity-light counts from the in-memory GameObject coverage
        # (the light processor stashes m_Type into go.component_data).
        # No-op when no prefab was processed.
        self._write_asset_index()
        self._write_coverage_report()

    def _write_asset_index(self) -> None:
        path = self.importer_data_dir / "asset_index.json"
        payload = {
            "project_name": self.project_name,
            "materials":    self.asset_index["materials"],
            "meshes":       self.asset_index["meshes"],
            "prefabs":      self.asset_index["prefabs"],
            "counts": {
                "materials": len(self.asset_index["materials"]),
                "meshes":    len(self.asset_index["meshes"]),
                "prefabs":   len(self.asset_index["prefabs"]),
            },
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
            self.log(f"\n  ✓ Wrote asset index: .ImporterData/{path.name} "
                     f"({payload['counts']['materials']} mats, "
                     f"{payload['counts']['meshes']} meshes, "
                     f"{payload['counts']['prefabs']} prefabs)")
        except Exception as exc:
            self.log(f"  ⚠ Failed to write asset_index.json: {exc}")

    def _write_coverage_report(self) -> None:
        path = self.importer_data_dir / "coverage.json"
        payload = self.coverage.to_dict()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
            unh_comp = len(payload['unhandled_component_types'])
            unh_over = len(payload['unhandled_override_paths'])
            self.log(f"  ✓ Wrote coverage report: .ImporterData/{path.name} "
                     f"({unh_comp} unhandled component type(s), "
                     f"{unh_over} unhandled override path(s), "
                     f"{len(payload['warnings'])} warning(s))")
        except Exception as exc:
            self.log(f"  ⚠ Failed to write coverage.json: {exc}")
    
    def _parse_unity_prefab(self, prefab_path: Path) -> Tuple[Dict[str, GameObject], Dict[str, str]]:
        """Parse Unity prefab and extract GameObjects"""
        game_objects = {}
        components_data = {}
        transform_to_gameobject = {}
        
        with open(prefab_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        doc_pattern = r'---\s+!u!\d+\s+&(\d+)\n(.*?)(?=---\s+!u!|\Z)'
        matches = re.findall(doc_pattern, content, re.DOTALL)
        
        for anchor, doc_content in matches:
            clean_content = re.sub(r'!u!\d+', '', doc_content)
            
            try:
                doc = yaml.safe_load(clean_content)
                if not doc:
                    continue
                
                if 'Transform' in doc:
                    self._parse_transform(doc['Transform'], anchor, game_objects, transform_to_gameobject)
                elif 'GameObject' in doc:
                    self._parse_game_object(doc['GameObject'], anchor, game_objects, transform_to_gameobject)
                elif 'PrefabInstance' in doc:
                    # PrefabInstance blocks represent nested prefabs
                    self._parse_prefab_instance_in_prefab(doc['PrefabInstance'], anchor, game_objects, transform_to_gameobject)
                else:
                    # Dispatch to registered component processors and record
                    # every top-level key into coverage so the end-of-run report
                    # shows both handled and unhandled component types.
                    handled = False
                    for known_type in self.component_dispatch:
                        if known_type in doc:
                            components_data[anchor] = {'type': known_type, 'data': doc[known_type]}
                            self.coverage.record_component(
                                known_type,
                                type(self.component_dispatch[known_type]).__name__,
                            )
                            handled = True
                            break
                    if not handled:
                        for top_key in doc:
                            self.coverage.record_component(top_key, None)
            
            except yaml.YAMLError:
                continue
        
        # Build hierarchy and assign components
        self._build_hierarchy(game_objects, transform_to_gameobject, components_data)
        
        return game_objects, transform_to_gameobject
    
    def _parse_transform(self, transform_data: Dict, anchor: str, 
                        game_objects: Dict, transform_map: Dict) -> None:
        """Parse Transform component"""
        go_ref = transform_data.get('m_GameObject', {})
        go_file_id = str(go_ref.get('fileID', ''))
        
        if not go_file_id or go_file_id == '0':
            return
        
        transform_map[anchor] = go_file_id
        
        local_pos = transform_data.get('m_LocalPosition', {'x': 0, 'y': 0, 'z': 0})
        local_rot = transform_data.get('m_LocalRotation', {'x': 0, 'y': 0, 'z': 0, 'w': 1})
        local_scale = transform_data.get('m_LocalScale', {'x': 1, 'y': 1, 'z': 1})
        
        position = (float(local_pos.get('x', 0)), float(local_pos.get('y', 0)), float(local_pos.get('z', 0)))
        rotation = (float(local_rot.get('x', 0)), float(local_rot.get('y', 0)),
                   float(local_rot.get('z', 0)), float(local_rot.get('w', 1)))
        scale = (float(local_scale.get('x', 1)), float(local_scale.get('y', 1)), float(local_scale.get('z', 1)))
        
        transform = Transform(position, rotation, scale)
        
        if go_file_id not in game_objects:
            game_objects[go_file_id] = GameObject(
                file_id=go_file_id,
                name="",
                transform=transform
            )
        else:
            game_objects[go_file_id].transform = transform
        
        parent = transform_data.get('m_Father', {})
        parent_transform_id = str(parent.get('fileID', '0'))
        if parent_transform_id != '0':
            game_objects[go_file_id].parent_id = parent_transform_id
        
        children = transform_data.get('m_Children', [])
        for child in children:
            if child and child.get('fileID'):
                child_transform_id = str(child['fileID'])
                game_objects[go_file_id].children_ids.append(child_transform_id)
    
    def _parse_game_object(self, go_data: Dict, anchor: str, 
                          game_objects: Dict, transform_map: Dict) -> None:
        """Parse GameObject"""
        file_id = anchor
        name = go_data.get('m_Name', 'GameObject')
        
        components = go_data.get('m_Component', [])
        transform_id = None
        for comp in components:
            comp_ref = comp.get('component', {})
            comp_file_id = str(comp_ref.get('fileID', ''))
            if comp_file_id:
                transform_id = comp_file_id
                break
        
        if transform_id and transform_id in transform_map:
            old_go_id = transform_map[transform_id]
            if old_go_id in game_objects:
                game_objects[file_id] = game_objects.pop(old_go_id)
                game_objects[file_id].file_id = file_id
                game_objects[file_id].name = name
            transform_map[transform_id] = file_id
        
        if file_id in game_objects:
            game_objects[file_id].name = name
        else:
            game_objects[file_id] = GameObject(
                file_id=file_id,
                name=name,
                transform=Transform()
            )
    
    def _parse_prefab_instance_in_prefab(self, instance_data: Dict, anchor: str,
                                        game_objects: Dict, transform_map: Dict) -> None:
        """
        Parse a PrefabInstance block (a nested prefab reference inside a Unity prefab).

        Captures the FULL m_Modifications array verbatim onto the GameObject so
        downstream emission can dispatch overrides by propertyPath. Also extracts
        m_AddedComponents, m_RemovedComponents, m_AddedGameObjects from the
        m_Modification block — these live alongside m_Modifications, not inside it.

        The transform-related modifications are additionally projected onto a
        Transform so that the converter's existing position/rotation/scale plumbing
        keeps working. All other overrides are left for _create_nested_prefab_instance
        to translate into O3DE JSON patches.
        """
        source_prefab = instance_data.get('m_SourcePrefab', {})
        prefab_guid   = source_prefab.get('guid', '')
        if not prefab_guid:
            return

        modification         = instance_data.get('m_Modification', {})
        modifications        = modification.get('m_Modifications', []) or []
        added_components     = modification.get('m_AddedComponents', []) or []
        removed_components   = modification.get('m_RemovedComponents', []) or []
        added_gameobjects    = modification.get('m_AddedGameObjects', []) or []
        parent_transform     = modification.get('m_TransformParent', {}) or {}
        parent_id            = str(parent_transform.get('fileID', ''))

        # --- Project transform-related overrides onto a Transform ---
        # All other overrides stay in modifications[] for the emitter to handle.
        name     = 'PrefabInstance'
        position = [0.0, 0.0, 0.0]
        rotation = [0.0, 0.0, 0.0, 1.0]
        scale    = [1.0, 1.0, 1.0]
        TRANSFORM_AXIS = {'x': 0, 'y': 1, 'z': 2, 'w': 3}

        for mod in modifications:
            prop_path = mod.get('propertyPath', '') or ''
            value     = mod.get('value', 0)

            if prop_path == 'm_Name':
                name = str(value) if value else name
            elif prop_path.startswith('m_LocalPosition.'):
                axis = prop_path.rsplit('.', 1)[-1]
                if axis in TRANSFORM_AXIS and TRANSFORM_AXIS[axis] < 3:
                    position[TRANSFORM_AXIS[axis]] = float(value)
            elif prop_path.startswith('m_LocalRotation.'):
                axis = prop_path.rsplit('.', 1)[-1]
                if axis in TRANSFORM_AXIS:
                    rotation[TRANSFORM_AXIS[axis]] = float(value)
            elif prop_path.startswith('m_LocalScale.'):
                axis = prop_path.rsplit('.', 1)[-1]
                if axis in TRANSFORM_AXIS and TRANSFORM_AXIS[axis] < 3:
                    scale[TRANSFORM_AXIS[axis]] = float(value)

        transform = Transform(
            position=tuple(position),
            rotation=tuple(rotation),
            scale=tuple(scale),
        )

        file_id = anchor
        go = GameObject(
            file_id=file_id,
            name=name,
            transform=transform,
            is_prefab_instance=True,
            prefab_source_guid=prefab_guid,
        )

        # Keep every override entry around for the emitter and the coverage tracker.
        go.prefab_modifications      = list(modifications)
        go.prefab_added_components   = list(added_components)
        go.prefab_removed_components = list(removed_components)
        go.prefab_added_gameobjects  = list(added_gameobjects)

        if parent_id and parent_id != '0':
            go.parent_id = parent_id

        game_objects[file_id] = go

        # Log a one-line override summary for visibility during conversion.
        other_count = sum(
            1 for m in modifications
            if not (m.get('propertyPath', '') or '').startswith(
                ('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.', 'm_Name')
            )
        )
        self.log(
            f"  [PrefabInstance] '{name}' src={prefab_guid[:8]}… "
            f"mods={len(modifications)} (transform+name handled, "
            f"{other_count} other), added_comp={len(added_components)}, "
            f"removed_comp={len(removed_components)}, "
            f"added_go={len(added_gameobjects)}"
        )
        # Don't add to transform_map since PrefabInstance doesn't have a separate Transform component
    
    def _build_hierarchy(self, game_objects: Dict, transform_map: Dict, components_data: Dict) -> None:
        """Build hierarchy and assign component data"""
        # Resolve transform IDs to GameObject IDs
        for go_id, go in list(game_objects.items()):
            if go.parent_id and go.parent_id in transform_map:
                go.parent_id = transform_map[go.parent_id]
            elif go.parent_id == '0':
                go.parent_id = None
            
            resolved_children = []
            for child_transform_id in go.children_ids:
                if child_transform_id in transform_map:
                    resolved_children.append(transform_map[child_transform_id])
            go.children_ids = resolved_children
        
        # Ensure parent-child relationships (bidirectional)
        for file_id, go in game_objects.items():
            # Forward: parent -> children
            for child_id in go.children_ids:
                if child_id in game_objects:
                    game_objects[child_id].parent_id = file_id
            
            # Reverse: child -> parent (add child to parent's children_ids if not already there)
            if go.parent_id and go.parent_id in game_objects:
                parent_go = game_objects[go.parent_id]
                if file_id not in parent_go.children_ids:
                    parent_go.children_ids.append(file_id)
        
        # Dispatch each component to its registered processor's parse() method
        for comp_id, comp_info in components_data.items():
            comp_type = comp_info.get('type')
            comp_data = comp_info.get('data', {})

            go_ref = comp_data.get('m_GameObject', {})
            go_id  = str(go_ref.get('fileID', ''))

            if go_id not in game_objects:
                self.log(f"  [Hierarchy] ⚠ Component '{comp_type}' references unknown GO id={go_id}")
                continue

            go = game_objects[go_id]

            processor = self.component_dispatch.get(comp_type)
            if processor:
                self.log(f"  [Hierarchy] Parsing {comp_type} on '{go.name}'")
                processor.parse(comp_type, comp_data, go, self.log)
            else:
                self.log(f"  [Hierarchy] ⚠ No processor for component type '{comp_type}' — skipped")
    
    
    def _process_material(self, material_guid: str) -> Optional[str]:
        """Process Unity material and create O3DE material"""
        # Check if already processed
        if material_guid in self.processed_materials:
            return self.processed_materials[material_guid]
        
        # Find material file
        material_path = self.asset_db.resolve_guid(material_guid)
        if not material_path:
            self.log(f"    ⚠ Material GUID not found: {material_guid}")
            self.coverage.record_missing_material(material_guid)
            return None
        
        self.log(f"    Processing material: {material_path.name}")
        
        # Parse material
        material_data = self.asset_db.parse_material(material_path)
        if not material_data:
            self.log(f"      ⚠ Failed to parse material")
            return None
        
        # Warn about texture-bound property names the extractor doesn't know
        # how to route. Almost always indicates a custom / asset-store shader
        # that uses non-standard slot names (e.g. _Albedo, _Composite). Add
        # the aliases to TEXTURE_MAP (or IGNORE_UNMAPPED) in
        # _extract_material_data when one of these recurs across a pack.
        unmapped = material_data.get('unmapped_texture_props', [])
        if unmapped:
            shader_path = material_data.get('shader') or '<unknown shader>'
            self.log(
                f"      ⚠ '{material_path.stem}' has bound textures on "
                f"unrecognized property names {unmapped} "
                f"(shader: {shader_path}). Those textures will be skipped — "
                f"add the names to TEXTURE_MAP in _extract_material_data to "
                f"route them, or to IGNORE_UNMAPPED to silence this warning."
            )

        # Process textures
        texture_paths = {}
        mg_source_guids = material_data.get('metallic_gloss_source_guids', set())
        for o3de_prop, texture_guid in material_data.get('textures', {}).items():
            # The roughness slot wants an INVERTED alpha when the source came
            # from Unity's _MetallicGlossMap (alpha=smoothness, not roughness).
            # The metallic slot still uses the raw texture — its RGB is correct.
            if (o3de_prop == 'roughness'
                    and self.convert_smoothness_to_roughness
                    and texture_guid in mg_source_guids):
                texture_output = self._process_metallic_gloss_as_roughness(texture_guid)
            else:
                texture_output = self._process_texture(texture_guid)
            if texture_output:
                texture_paths[o3de_prop] = texture_output
        
        # Create O3DE material
        output_name = material_path.stem
        output_path = self.materials_dir / f"{output_name}.material"
        
        o3de_material = {
            "materialType": "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/StandardPBR.materialtype",
            "materialTypeVersion": 5,
            "propertyValues": {}
        }
        
        # Add texture properties with RELATIVE paths (../Textures/filename)
        for o3de_prop, texture_rel_path in texture_paths.items():
            # Convert "Textures/filename" to "../Textures/filename" for relative path from Materials/ folder
            if texture_rel_path.startswith("Textures/"):
                relative_texture_path = f"../{texture_rel_path}"
            else:
                relative_texture_path = texture_rel_path
            
            # Handle special property naming
            # For "occlusion.specular", it becomes "occlusion.specularTextureMap"
            if o3de_prop == 'occlusion.specular':
                property_name = 'occlusion.specularTextureMap'
            else:
                property_name = f"{o3de_prop}.textureMap"
            
            o3de_material["propertyValues"][property_name] = relative_texture_path
        
        # Add scalar/color/enum properties
        for o3de_prop, value in material_data.get('properties', {}).items():
            if isinstance(value, list):
                # Color property - ensure 4 components
                color = value[:3] if len(value) >= 3 else [1.0, 1.0, 1.0]
                alpha = value[3] if len(value) >= 4 else 1.0
                o3de_material["propertyValues"][o3de_prop] = [
                    float(color[0]),
                    float(color[1]),
                    float(color[2]),
                    float(alpha)
                ]
            elif isinstance(value, str):
                # Enum property (e.g. opacity.mode = "Blended")
                o3de_material["propertyValues"][o3de_prop] = value
            else:
                # Scalar property
                o3de_material["propertyValues"][o3de_prop] = float(value)
        
        # ---------------------------------------------------------------
        # Opacity sanity pass.
        # `opacity.alphaSource = "Packed"` tells O3DE to read alpha from the
        # bound baseColor texture. With no baseColor texture in the final
        # material, that sample returns 0 → a Cutout material renders fully
        # invisible and a Blended material renders fully transparent.
        # Strip the opacity flags in that case so the material falls back to
        # the (correct) Opaque default and at least shows the constant
        # baseColor.color. The most common cause is a Unity material whose
        # _MainTex/_BaseMap GUID does not resolve in the project being
        # converted (missing texture, package-only texture, etc.).
        # ---------------------------------------------------------------
        prop_values = o3de_material["propertyValues"]
        opacity_mode = prop_values.get('opacity.mode')
        if opacity_mode in ('Cutout', 'Blended') and 'baseColor.textureMap' not in prop_values:
            prop_values.pop('opacity.mode', None)
            prop_values.pop('opacity.alphaSource', None)
            prop_values.pop('opacity.factor', None)
            self.log(
                f"      ⚠ '{output_name}' source declared opacity.mode="
                f"{opacity_mode} but no baseColor texture survived "
                f"resolution — opacity flags dropped to avoid an invisible "
                f"material. Check that the Unity material's _MainTex / "
                f"_BaseMap GUID is resolvable in this project."
            )

        # Write material file
        with open(output_path, 'w') as f:
            json.dump(o3de_material, f, indent=4)

        # Generate gem-style asset hint: assets/projectname/materials/filename.azmaterial
        asset_hint = f"{self.asset_hint_root}/materials/{output_path.stem}.azmaterial"
        self.processed_materials[material_guid] = asset_hint
        self.asset_index["materials"][material_guid] = asset_hint

        self.log(f"      ✓ Created material with {len(texture_paths)} textures")

        return asset_hint
    
    def _process_texture(self, texture_guid: str) -> Optional[str]:
        """Process texture - copy to output directory"""
        if texture_guid in self.processed_textures:
            return self.processed_textures[texture_guid]
        
        texture_path = self.asset_db.resolve_guid(texture_guid)
        if not texture_path or texture_path.suffix.lower() not in self.asset_db.texture_extensions:
            self.coverage.record_missing_texture(texture_guid)
            return None
        
        # Copy texture to output
        output_path = self.textures_dir / texture_path.name
        
        try:
            if not output_path.exists():
                shutil.copy2(texture_path, output_path)

            relative_path = f"Textures/{output_path.name}"
            self.processed_textures[texture_guid] = relative_path

            return relative_path

        except Exception as e:
            self.log(f"      ⚠ Failed to copy texture {texture_path.name}: {e}")
            return None

    # =========================================================================
    # SMOOTHNESS → ROUGHNESS  (alpha-channel re-bake)
    # =========================================================================

    def _process_metallic_gloss_as_roughness(self, texture_guid: str) -> Optional[str]:
        """
        Re-bake a Unity `_MetallicGlossMap` texture for use as an O3DE roughness map.

        Unity packs smoothness into the alpha channel of the metallic-gloss map.
        O3DE samples the roughness texture directly — it has no built-in
        smoothness-to-roughness inversion. To make the texture sample correctly
        as roughness we invert the alpha channel (alpha = 1 − alpha) and write
        the result as `<stem>_Roughness.png` into the Textures/ folder.

        The RGB channels are left untouched: the metallic slot still references
        the original texture and reads metallic from RGB exactly as Unity wrote
        it. Only the roughness slot routes through this method.

        Returns None if Pillow isn't installed, the source can't be loaded, or
        the file lacks an alpha channel (in which case the caller falls back to
        plain copy via _process_texture and the user gets a coverage warning).
        """
        if texture_guid in self.processed_inverted_textures:
            return self.processed_inverted_textures[texture_guid]

        if not PIL_AVAILABLE:
            self.log("      ⚠ Smoothness→roughness conversion requested but Pillow is "
                     "not installed; falling back to raw texture copy.")
            self.coverage.warn(
                "Smoothness→Roughness conversion enabled but Pillow is missing. "
                "Install with: pip install Pillow"
            )
            return self._process_texture(texture_guid)

        texture_path = self.asset_db.resolve_guid(texture_guid)
        if not texture_path or texture_path.suffix.lower() not in self.asset_db.texture_extensions:
            self.coverage.record_missing_texture(texture_guid)
            return None

        # Re-baked file lives next to the originals but always as PNG, because
        # PNG preserves alpha losslessly and O3DE's image processor accepts it.
        output_name = f"{texture_path.stem}_Roughness.png"
        output_path = self.textures_dir / output_name
        relative_path = f"Textures/{output_name}"

        try:
            if not output_path.exists():
                with Image.open(texture_path) as img:
                    # Force RGBA so we always have an alpha channel to invert,
                    # even when the source was RGB-only (in which case the
                    # synthetic alpha is fully opaque → inverted is fully
                    # transparent → roughness=0, which is correct for a
                    # "fully smooth" interpretation of a missing smoothness map).
                    rgba = img.convert('RGBA')
                    r, g, b, a = rgba.split()
                    # Pillow's `Image.eval` runs `1 − x` on the 8-bit channel.
                    inverted_a = a.point(lambda v: 255 - v)
                    out = Image.merge('RGBA', (r, g, b, inverted_a))
                    out.save(output_path, format='PNG')
                self.log(f"      ✓ Wrote inverted-alpha roughness map: {output_name}")
            else:
                self.log(f"      Inverted-alpha roughness map already exists: {output_name}")

            self.processed_inverted_textures[texture_guid] = relative_path
            return relative_path

        except Exception as e:
            self.log(f"      ⚠ Failed to invert alpha for {texture_path.name}: {e}")
            self.coverage.warn(
                f"Failed to re-bake smoothness→roughness for {texture_path.name}: {e}"
            )
            # Fall back to the plain copy so the slot still has SOMETHING bound.
            return self._process_texture(texture_guid)

    def _process_mesh(self, mesh_guid: str) -> Optional[Path]:
        """Process mesh — copy to output directory. Returns output Path or None."""
        if mesh_guid in self.processed_meshes:
            cached = self.processed_meshes[mesh_guid]
            # Return Path if cached, or None
            return cached if isinstance(cached, Path) else None

        mesh_path = self.asset_db.resolve_guid(mesh_guid)
        if not mesh_path or mesh_path.suffix.lower() not in self.asset_db.mesh_extensions:
            self.coverage.record_missing_mesh(mesh_guid)
            return None

        self.log(f"    Processing mesh: {mesh_path.name}")
        output_path = self.meshes_dir / mesh_path.name

        try:
            if not output_path.exists():
                shutil.copy2(mesh_path, output_path)
                self.log(f"      Copied mesh file")
            else:
                self.log(f"      Mesh already exists")

            self.processed_meshes[mesh_guid] = output_path
            # Record the FBX stem; per-entity sub-mesh hints are computed
            # later (see process_prefab() FBX assetinfo block).
            self.asset_index["meshes"][mesh_guid] = output_path.stem
            return output_path

        except Exception as e:
            self.log(f"      Failed to process mesh {mesh_path.name}: {e}")
            return None
    
    
    def _generate_component_id(self) -> int:
        """Generate unique component ID"""
        return random.randint(1000000000000000, 9999999999999999)
    
    def _generate_entity_id(self) -> str:
        """Generate unique entity ID in O3DE format"""
        self.entity_id_counter += 1
        return f"Entity_[{self.entity_id_counter}]"
    
    def _quaternion_to_euler(self, quaternion: Tuple[float, float, float, float]) -> List[float]:
        """Convert quaternion to Euler angles in degrees (XYZ order)"""
        x, y, z, w = quaternion
        
        # Roll (x-axis rotation)
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        
        # Pitch (y-axis rotation)
        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)
        
        # Yaw (z-axis rotation)
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        # Convert to degrees
        return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]
    
    def _convert_to_o3de_coordinates(self, unity_transform: Transform) -> Tuple[Transform, bool]:
        """Convert Unity transform to O3DE coordinate system"""
        o3de_pos = (unity_transform.position[0], unity_transform.position[2], unity_transform.position[1])
        qx, qy, qz, qw = unity_transform.rotation
        o3de_rot = (qx, qz, qy, qw)
        o3de_scale = (unity_transform.scale[0], unity_transform.scale[2], unity_transform.scale[1])
        converted = Transform(o3de_pos, o3de_rot, o3de_scale)
        return converted, not converted.is_uniform_scale()
    
    def _create_o3de_prefab(self, root_go: GameObject, all_game_objects: Dict,
                           transform_map: Dict, material_mapping: Dict, mesh_mapping: Dict,
                           fbx_material_labels: Dict[str, List[str]],
                           output_path: Path) -> None:
        """Create O3DE prefab in JSON format, plus a `.entitymap.json` sidecar
        that records the fileID→entity_alias mapping so nested-instance override
        propagation can target the right entity in this prefab from a consumer.
        """
        # ContainerEntity uses the root GameObject's name
        prefab_data = {
            "ContainerEntity": self._create_container_entity(root_go),
            "Entities": {},
            "Instances": {}
        }

        entity_id_map: Dict[str, str] = {}

        # Find the actual root GameObject (should only be one with parent_id = None)
        root_entities = [go for go in all_game_objects.values() if go.parent_id is None]

        if not root_entities:
            self.log("  ⚠ No root GameObject found")
            return

        if len(root_entities) > 1:
            self.log(f"  ⚠ Multiple root GameObjects found ({len(root_entities)}), using first one")

        root_entity = root_entities[0]

        # Create the root entity with ContainerEntity as parent
        root_entity_id = self._create_entity_recursive(
            root_entity, all_game_objects, prefab_data["Entities"],
            prefab_data["Instances"], entity_id_map, material_mapping, mesh_mapping,
            fbx_material_labels,
            parent_entity_id="ContainerEntity"
        )

        # Set child order in ContainerEntity
        if root_entity_id:
            prefab_data["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"] = [root_entity_id]

        with open(output_path, 'w') as f:
            json.dump(prefab_data, f, indent=4)

        # ---------------------------------------------------------------
        # Write the sidecar entity map. Anything that overrides a child of
        # this prefab from a parent prefab needs to translate Unity fileIDs
        # into the O3DE entity aliases used above.
        # ---------------------------------------------------------------
        self._write_entity_map_sidecar(
            output_path, root_entity, all_game_objects, entity_id_map,
            fbx_material_labels,
        )

    # =========================================================================
    # ENTITY-MAP SIDECAR  (per-prefab, written next to the .prefab output)
    # =========================================================================

    def _write_entity_map_sidecar(self, prefab_output_path: Path,
                                  root_go: GameObject,
                                  all_game_objects: Dict,
                                  entity_id_map: Dict[str, str],
                                  fbx_material_labels: Dict[str, List[str]]) -> None:
        """
        Persist the fileID→entity_alias map and per-entity material slot list
        into <output>/.ImporterData/<prefab_stem>.entitymap.json so the O3DE
        Asset Processor never scans these (they are converter bookkeeping, not
        O3DE-consumed). Sidecar format:

            {
              "source_guid":     "<unity_prefab_guid>",
              "source_path":     "Assets/Foo.prefab",   (best-effort)
              "root_entity":     "Entity_[1000001]",
              "container_alias": "ContainerEntity",
              "entity_aliases":     {"<unity_file_id>": "Entity_[N]", ...},
              "material_slots":     {"<unity_file_id>": ["<mat_guid_0>", ...]},
              "material_slot_labels": {"<unity_file_id>": ["<fbx_name_0>", ...]},
              "go_names":           {"<unity_file_id>": "Cube_001", ...}
            }

        `material_slot_labels` holds the FBX-internal material names (one per
        Unity MeshRenderer slot, ordinally paired). It is the only valid key
        source for the runtime `materialsByLabel` map, so any Tier 3 override
        emission needs to look up the slot's label here rather than guessing
        from the assetHint stem.
        """
        # The root in entity_id_map keys was indexed by Unity file_id, which is
        # exactly what nested-instance overrides target. ContainerEntity is the
        # outer shell — overrides on the prefab instance's own root go to
        # ContainerEntity at the consumer side, while overrides on internal
        # children go to /Entities/<alias>/...

        # Recover the source Unity prefab path/guid from output_path.stem (the
        # converter writes outputs named after the source prefab's stem).
        source_path: Optional[Path] = None
        source_guid: Optional[str]  = None
        for guid, path in self.asset_db.guid_to_path.items():
            if path.suffix == '.prefab' and path.stem == prefab_output_path.stem:
                source_path = path
                source_guid = guid
                break

        if source_guid:
            self.asset_index["prefabs"][source_guid] = str(source_path) if source_path else ""

        material_slots = {
            go.file_id: list(go.material_guids)
            for go in all_game_objects.values()
            if go.material_guids
        }
        material_slot_labels = {
            file_id: list(labels)
            for file_id, labels in fbx_material_labels.items()
            if labels
        }
        go_names = {
            go.file_id: go.name for go in all_game_objects.values() if go.name
        }

        sidecar = {
            "source_guid":         source_guid or "",
            "source_path":         str(source_path) if source_path else "",
            "root_entity":         entity_id_map.get(root_go.file_id, ""),
            "container_alias":     "ContainerEntity",
            "entity_aliases":      dict(entity_id_map),
            "material_slots":      material_slots,
            "material_slot_labels": material_slot_labels,
            "go_names":            go_names,
        }

        sidecar_path = self.importer_data_dir / f"{prefab_output_path.stem}.entitymap.json"
        try:
            with open(sidecar_path, 'w', encoding='utf-8') as f:
                json.dump(sidecar, f, indent=2)
            self.log(f"  ✓ Wrote entity map sidecar: .ImporterData/{sidecar_path.name}")
        except Exception as exc:
            self.log(f"  ⚠ Failed to write entity map sidecar: {exc}")

    def _load_entity_map_sidecar(self, source_prefab_path: Path) -> Optional[Dict]:
        """Load the converted-side sidecar for a Unity source prefab path.

        Sidecars now live in <output>/.ImporterData/<stem>.entitymap.json.
        Returns None when the source prefab hasn't been converted yet (or the
        sidecar is missing for some other reason). Cached after first load.
        """
        key = str(source_prefab_path)
        if key in self._entity_map_cache:
            return self._entity_map_cache[key]

        candidate = self.importer_data_dir / f"{source_prefab_path.stem}.entitymap.json"
        if not candidate.exists():
            self._entity_map_cache[key] = None
            return None

        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._entity_map_cache[key] = data
            return data
        except Exception as exc:
            self.log(f"  ⚠ Failed to load entity map sidecar {candidate.name}: {exc}")
            self._entity_map_cache[key] = None
            return None
    
    def _create_container_entity(self, root_go: GameObject) -> Dict:
        """Create ContainerEntity for prefab"""
        return {
            "Id": "ContainerEntity",
            "Name": root_go.name,
            "Components": {
                "EditorDisabledCompositionComponent": {
                    "$type": "EditorDisabledCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorEntityIconComponent": {
                    "$type": "EditorEntityIconComponent",
                    "Id": self._generate_component_id()
                },
                "EditorEntitySortComponent": {
                    "$type": "EditorEntitySortComponent",
                    "Id": self._generate_component_id(),
                    "Child Entity Order": []
                },
                "EditorInspectorComponent": {
                    "$type": "EditorInspectorComponent",
                    "Id": self._generate_component_id()
                },
                "EditorLockComponent": {
                    "$type": "EditorLockComponent",
                    "Id": self._generate_component_id()
                },
                "EditorOnlyEntityComponent": {
                    "$type": "EditorOnlyEntityComponent",
                    "Id": self._generate_component_id(),
                    "IsEditorOnly": True
                },
                "EditorPendingCompositionComponent": {
                    "$type": "EditorPendingCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorPrefabComponent": {
                    "$type": "EditorPrefabComponent",
                    "Id": self._generate_component_id()
                },
                "EditorVisibilityComponent": {
                    "$type": "EditorVisibilityComponent",
                    "Id": self._generate_component_id()
                },
                "TransformComponent": {
                    "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
                    "Id": self._generate_component_id(),
                    "Parent Entity": ""
                }
            }
        }
    
    
    def _create_nested_prefab_instance(self, go: GameObject, prefab_path: Path,
                                       parent_entity_id: str) -> Dict:
        """Emit a nested-prefab Instance entry with JSON-patch overrides.

        Patch tiers handled here (anything else is logged to the coverage
        tracker as 'unhandled' so the end-of-run coverage.json shows what
        was lost):

          Tier 1  Transform — translate, rotate, scale on the ContainerEntity
          Tier 2  m_IsActive on the prefab root → container visibility patch
          Tier 3  m_Materials.Array.data[N] → patch the assetHint inside the
                  target entity's EditorMaterialComponent materialsByLabel
                  entry. Label key = FBX-internal material name at slot N
                  (read from the source prefab's sidecar
                  `material_slot_labels`, which mirrors what SceneAPI exposes
                  as ModelMaterialSlot::m_displayName at runtime).

        Patch path conventions (all are valid JSON Pointer fragments rooted at
        the nested instance):
          /ContainerEntity/...                — affects the instance shell
          /Entities/<entity_alias>/...        — affects a child of the source
        """
        source_path = f"{self.asset_hint_root}/prefabs/{prefab_path.name}"
        o3de_transform, _ = self._convert_to_o3de_coordinates(go.transform)
        euler             = self._quaternion_to_euler(o3de_transform.rotation)

        # ---------------------------------------------------------------
        # PARENT RE-PARENT (always emitted)
        # ---------------------------------------------------------------
        patches: List[Dict] = [
            {
                "op":    "replace",
                "path":  "/ContainerEntity/Components/TransformComponent/Parent Entity",
                "value": f"../{parent_entity_id}",
            }
        ]

        # ---------------------------------------------------------------
        # TIER 1 — Transform overrides on the ContainerEntity
        # ---------------------------------------------------------------
        if any(abs(v) > 0.0001 for v in o3de_transform.position):
            for i, axis_val in enumerate(o3de_transform.position):
                patches.append({
                    "op":    "replace",
                    "path":  f"/ContainerEntity/Components/TransformComponent/Transform Data/Translate/{i}",
                    "value": axis_val,
                })

        if any(abs(v) > 0.0001 for v in euler):
            for i, axis_val in enumerate(euler):
                patches.append({
                    "op":    "replace",
                    "path":  f"/ContainerEntity/Components/TransformComponent/Transform Data/Rotate/{i}",
                    "value": axis_val,
                })

        # Scale only when non-unit. Uniform scale collapses to scalar in the
        # source prefab; non-uniform scale becomes EditorNonUniformScaleComponent.
        # For the instance shell we keep it simple and emit a scalar scale patch
        # when the captured local scale is uniform-ish and non-1.
        sx, sy, sz = o3de_transform.scale
        if abs(sx - 1.0) > 0.0001 and abs(sx - sy) < 0.0001 and abs(sy - sz) < 0.0001:
            patches.append({
                "op":    "replace",
                "path":  "/ContainerEntity/Components/TransformComponent/Transform Data/Scale",
                "value": sx,
            })
        elif (abs(sx - 1.0) > 0.0001 or abs(sy - 1.0) > 0.0001 or abs(sz - 1.0) > 0.0001):
            # Non-uniform — would require an EditorNonUniformScaleComponent
            # patch path that may or may not already exist in the source prefab.
            # Log to coverage and skip for now.
            self.coverage.warn(
                f"Non-uniform scale override on nested instance '{go.name}' "
                f"({sx}, {sy}, {sz}) not emitted — needs EditorNonUniformScaleComponent."
            )

        # ---------------------------------------------------------------
        # TIER 2 + TIER 3 — walk modifications by propertyPath
        # ---------------------------------------------------------------
        sidecar = self._load_entity_map_sidecar(prefab_path)
        entity_aliases = (sidecar or {}).get("entity_aliases", {})
        material_slot_labels = (sidecar or {}).get("material_slot_labels", {})

        if go.prefab_modifications and not sidecar:
            self.coverage.warn(
                f"No entity-map sidecar for source prefab '{prefab_path.name}' — "
                f"non-transform overrides on nested instance '{go.name}' cannot be targeted."
            )

        # Material-slot overrides arrive as multiple property entries on the
        # same target (the renderer component fileID, not the GO). We collect
        # them first so we know the slot count per target before patching.
        # Structure: {target_fileID: {slot_index: new_mat_guid}}
        material_overrides: Dict[str, Dict[int, str]] = {}

        for mod in go.prefab_modifications:
            prop_path = (mod.get('propertyPath') or '').strip()
            value     = mod.get('value', None)
            objref    = mod.get('objectReference') or {}
            target    = mod.get('target') or {}
            target_id = str(target.get('fileID', ''))

            # Transform/name overrides were already projected onto go.transform / go.name
            # and emitted above. Mark them as handled in the coverage tracker.
            if prop_path == 'm_Name' or prop_path.startswith(
                ('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.')
            ):
                self.coverage.record_modification(prop_path, handled=True, example_value=value)
                continue

            # --- Tier 2: m_IsActive (on the GameObject) ---
            if prop_path == 'm_IsActive':
                # O3DE entity-disabled state isn't fully reverse-engineered yet;
                # log a warning and record as unhandled. Container-side
                # patching can be added once the exact schema is confirmed.
                self.coverage.record_modification(
                    prop_path, handled=False, example_value=value
                )
                self.coverage.warn(
                    f"m_IsActive override on nested instance '{go.name}' (value={value}) "
                    f"not emitted — O3DE disabled-entity patch path needs confirmation."
                )
                continue

            # --- Tier 3: material slot override ---
            # propertyPath is `m_Materials.Array.data[N]` and the new material
            # GUID lives on `objectReference.guid` (not `value`).
            m = re.match(r'^m_Materials\.Array\.data\[(\d+)\]$', prop_path)
            if m:
                slot_idx = int(m.group(1))
                new_guid = objref.get('guid', '') if isinstance(objref, dict) else ''
                if not new_guid:
                    self.coverage.record_modification(prop_path, handled=False,
                                                     example_value="<no guid>")
                    continue
                # The target.fileID for material overrides is the MeshRenderer's
                # fileID inside the source prefab — NOT the GameObject. The
                # sidecar's material_slots map is keyed by GameObject fileID,
                # so we resolve via the renderer-to-GO link the sidecar omits
                # today. Until that's added, we fall back to "target.fileID is
                # the renderer's owner GO" which is true when the override was
                # authored at the GO level (most common).
                slot_map = material_overrides.setdefault(target_id, {})
                slot_map[slot_idx] = new_guid
                continue

            # --- Catch-all: unhandled override ---
            self.coverage.record_modification(
                prop_path, handled=False,
                example_value=value if value not in (None, '') else objref,
            )

        # Emit material slot patches now that we have all slots per target.
        for target_id, slot_map in material_overrides.items():
            entity_alias = entity_aliases.get(target_id)
            if not entity_alias:
                # The override targets a component fileID, not a GO. Search
                # go_names for a GO whose ID is close — for now, just log.
                self.coverage.warn(
                    f"Material override on nested instance '{go.name}' targets "
                    f"fileID={target_id} which is not in the source's entity map "
                    f"— renderer-component fileIDs aren't recorded yet. Skipped."
                )
                for slot_idx, mat_guid in slot_map.items():
                    self.coverage.record_modification(
                        f'm_Materials.Array.data[{slot_idx}]',
                        handled=False, example_value=mat_guid,
                    )
                continue

            # FBX-internal material names per slot index for this target.
            # Recorded by the source prefab's converter run as the truth
            # source for label keys in the base prefab's materialsByLabel.
            slot_labels = material_slot_labels.get(target_id, []) or []

            for slot_idx, mat_guid in slot_map.items():
                asset_hint = self.asset_index["materials"].get(mat_guid)
                if not asset_hint:
                    # Try to process the material now (covers consumer-only refs).
                    asset_hint = self._process_material(mat_guid)
                if not asset_hint:
                    self.coverage.record_missing_material(mat_guid)
                    self.coverage.record_modification(
                        f'm_Materials.Array.data[{slot_idx}]',
                        handled=False, example_value=mat_guid,
                    )
                    continue

                # Resolve the slot's label = FBX-internal material name at
                # this ordinal position (as SceneAPI saw it when the base
                # prefab was emitted). This is the only key that will match
                # the base prefab's materialsByLabel entry at runtime.
                label = (slot_labels[slot_idx]
                         if slot_idx < len(slot_labels) else '')

                if not label:
                    self.coverage.warn(
                        f"Material override on nested instance '{go.name}' "
                        f"slot {slot_idx} — no FBX-internal label recorded "
                        f"in sidecar (source prefab predates the label "
                        f"refactor, or FBX parse failed at emit time). "
                        f"Patch skipped — re-convert the source prefab to fix."
                    )
                    self.coverage.record_modification(
                        f'm_Materials.Array.data[{slot_idx}]',
                        handled=False, example_value=mat_guid,
                    )
                    continue

                patches.append({
                    "op":   "replace",
                    "path": (f"/Entities/{entity_alias}/Components/EditorMaterialComponent/"
                             f"Controller/Configuration/materialsByLabel/{label}/"
                             f"MaterialAsset/assetHint"),
                    "value": asset_hint,
                })
                self.coverage.record_modification(
                    f'm_Materials.Array.data[{slot_idx}]',
                    handled=True, example_value=asset_hint,
                )

        # ---------------------------------------------------------------
        # Sibling fields (added / removed / added GOs) — record and skip
        # ---------------------------------------------------------------
        for _ in go.prefab_added_components:    self.coverage.record_added_component()
        for _ in go.prefab_removed_components:  self.coverage.record_removed_component()
        for _ in go.prefab_added_gameobjects:   self.coverage.record_added_gameobject()
        if (go.prefab_added_components or go.prefab_removed_components
                or go.prefab_added_gameobjects):
            self.coverage.warn(
                f"Nested instance '{go.name}' has added/removed components or "
                f"added GameObjects that are not yet propagated to O3DE patches."
            )

        return {
            "Source":  source_path,
            "Patches": patches,
        }
    
    # ===================================================================
    #  Entity Helpers
    # ===================================================================

    def _make_bare_entity(self, entity_id: str, name: str,
                          parent_entity_id: str) -> Dict:
        """Create a minimal O3DE entity (for child collider entities)."""
        return {
            "Id": entity_id,
            "Name": name,
            "Components": {
                "TransformComponent": {
                    "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
                    "Id": self._generate_component_id(),
                    "Parent Entity": parent_entity_id
                },
                "EditorDisabledCompositionComponent": {
                    "$type": "EditorDisabledCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorEntityIconComponent": {
                    "$type": "EditorEntityIconComponent",
                    "Id": self._generate_component_id()
                },
                "EditorInspectorComponent": {
                    "$type": "EditorInspectorComponent",
                    "Id": self._generate_component_id()
                },
                "EditorLockComponent": {
                    "$type": "EditorLockComponent",
                    "Id": self._generate_component_id()
                },
                "EditorOnlyEntityComponent": {
                    "$type": "EditorOnlyEntityComponent",
                    "Id": self._generate_component_id()
                },
                "EditorPendingCompositionComponent": {
                    "$type": "EditorPendingCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorVisibilityComponent": {
                    "$type": "EditorVisibilityComponent",
                    "Id": self._generate_component_id()
                }
            }
        }

    # ===================================================================

    def _create_entity_recursive(self, go: GameObject, all_game_objects: Dict,
                                 entities_dict: Dict, instances_dict: Dict,
                                 entity_id_map: Dict,
                                 material_mapping: Dict, mesh_mapping: Dict,
                                 fbx_material_labels: Dict[str, List[str]],
                                 parent_entity_id: str = None) -> str:
        """Recursively create entities or instances in JSON format"""
        # Check if this is a prefab instance
        if go.is_prefab_instance and go.prefab_source_guid:
            instance_id = f"Instance_[{self.entity_id_counter}]"
            self.entity_id_counter += 1
            
            # Find the prefab file for this GUID
            prefab_path = self.asset_db.resolve_guid(go.prefab_source_guid)
            if prefab_path and prefab_path.suffix == '.prefab':
                # Create instance entry
                instances_dict[instance_id] = self._create_nested_prefab_instance(
                    go, prefab_path, parent_entity_id
                )
                return f"{instance_id}/ContainerEntity"
            # If we can't find the prefab, fall through to create regular entity
        
        entity_id = self._generate_entity_id()
        entity_id_map[go.file_id] = entity_id
        
        o3de_transform, needs_nonuniform = self._convert_to_o3de_coordinates(go.transform)

        # Use provided parent_entity_id or look up from entity_id_map
        if parent_entity_id is None:
            if go.parent_id and go.parent_id in entity_id_map:
                parent_entity_id = entity_id_map[go.parent_id]
            else:
                parent_entity_id = ""

        # Unity prefabs are always rooted at a single GameObject whose stored
        # transform is just whatever the prefab happened to sit at when last
        # saved. Unity treats that root transform as DEAD DATA at instance
        # time: every PrefabInstance modification records the FINAL
        # m_LocalPosition / m_LocalRotation / m_LocalScale, not a delta on
        # top of the prefab root. So preserving the Unity root GO's
        # transform on the converted prefab's inner root entity causes a
        # double-offset — the consumer's instance patch positions the
        # ContainerEntity at the world placement, and then the inner root
        # entity adds its own bake on top.
        #
        # Fix: when this entity is the prefab's root (parent_entity_id is
        # the ContainerEntity), force identity. World placement is supplied
        # entirely by the consumer's patches on the ContainerEntity.
        is_prefab_root = (parent_entity_id == "ContainerEntity")
        if is_prefab_root and (
            any(abs(v) > 0.0001 for v in o3de_transform.position)
            or any(abs(v) > 0.0001 for v in self._quaternion_to_euler(o3de_transform.rotation))
            or needs_nonuniform
            or abs(o3de_transform.scale[0] - 1.0) > 0.0001
        ):
            self.log(
                f"  [Transform] Discarding non-identity root transform on "
                f"'{go.name}' (pos={o3de_transform.position}, "
                f"scale={o3de_transform.scale}) — Unity prefab root "
                f"transforms are dead data, placement comes from the "
                f"consumer's ContainerEntity patch."
            )
            o3de_transform   = Transform((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
            needs_nonuniform = False
        
        entity = {
            "Id": entity_id,
            "Name": go.name,
            "Components": {
                "EditorDisabledCompositionComponent": {
                    "$type": "EditorDisabledCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorEntityIconComponent": {
                    "$type": "EditorEntityIconComponent",
                    "Id": self._generate_component_id()
                },
                "EditorInspectorComponent": {
                    "$type": "EditorInspectorComponent",
                    "Id": self._generate_component_id()
                },
                "EditorLockComponent": {
                    "$type": "EditorLockComponent",
                    "Id": self._generate_component_id()
                },
                "EditorPendingCompositionComponent": {
                    "$type": "EditorPendingCompositionComponent",
                    "Id": self._generate_component_id()
                },
                "EditorVisibilityComponent": {
                    "$type": "EditorVisibilityComponent",
                    "Id": self._generate_component_id()
                }
            }
        }
        
        # Add TransformComponent
        transform_component = {
            "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
            "Id": self._generate_component_id(),
            "Parent Entity": parent_entity_id
        }
        
        # Convert quaternion to Euler for rotation check
        euler = self._quaternion_to_euler(o3de_transform.rotation)
        
        # Add Transform Data only if entity has non-default transform
        has_translation = any(abs(v) > 0.0001 for v in o3de_transform.position)
        has_rotation = any(abs(v) > 0.0001 for v in euler)
        has_scale = not needs_nonuniform and abs(o3de_transform.scale[0] - 1.0) > 0.0001
        
        if has_translation or has_rotation or has_scale:
            transform_data = {}
            
            if has_translation:
                transform_data["Translate"] = list(o3de_transform.position)
            
            if has_rotation:
                transform_data["Rotate"] = euler
            
            if has_scale:
                transform_data["Scale"] = o3de_transform.scale[0]
            
            transform_component["Transform Data"] = transform_data
        
        entity["Components"]["TransformComponent"] = transform_component
        
        if needs_nonuniform:
            entity["Components"]["EditorNonUniformScaleComponent"] = {
                "$type": "EditorNonUniformScaleComponent",
                "Id": self._generate_component_id(),
                "Scale": list(o3de_transform.scale)
            }
        
        # ---------------------------------------------------------------
        # Component Processors — emit phase (mesh, material, physics, ...)
        # Each processor runs in WEIGHT order and may add child entities.
        # ---------------------------------------------------------------
        ctx = ProcessingContext(
            material_mapping      = material_mapping,
            mesh_mapping          = mesh_mapping,
            fbx_material_labels   = fbx_material_labels,
            entities_dict         = entities_dict,
            entity_id_map         = entity_id_map,
            generate_component_id = self._generate_component_id,
            generate_entity_id    = self._generate_entity_id,
            make_bare_entity      = self._make_bare_entity,
            log                   = self.log,
            stats                 = self.stats,
        )

        collider_child_ids = []
        for processor in self.component_processors:
            child_ids = processor.emit(go, entity, ctx)
            collider_child_ids.extend(child_ids)

        # ---------------------------------------------------------------
        # Child entities: GO children + any collider sub-entities
        # ---------------------------------------------------------------
        child_order = []
        for child_id in go.children_ids:
            if child_id in all_game_objects:
                child_entity_id = self._create_entity_recursive(
                    all_game_objects[child_id], all_game_objects,
                    entities_dict, instances_dict, entity_id_map,
                    material_mapping, mesh_mapping, fbx_material_labels,
                    entity_id
                )
                if child_entity_id:
                    child_order.append(child_entity_id)

        child_order.extend(collider_child_ids)

        if child_order:
            entity["Components"]["EditorEntitySortComponent"] = {
                "$type": "EditorEntitySortComponent",
                "Id": self._generate_component_id(),
                "Child Entity Order": child_order
            }

        entities_dict[entity_id] = entity
        return entity_id


SETTINGS_FILE = Path(__file__).parent / "converter_settings.json"


def main():
    """Launch the unified PySide6 GUI, opening directly on the Prefab tab."""
    import sys
    from main_app import main as app_main
    sys.argv.append('--tab=prefab')
    app_main()


if __name__ == '__main__':
    main()