"""
=============================================================================
UNITY ASSET DATABASE  (platforms.unity.asset_database)
=============================================================================

GUID-based asset resolution for Unity projects. Builds a guid → file-path
index by walking ``*.meta`` sidecars under the project's assets root, then
exposes lookup primitives and a Unity ``.mat`` parser.

This module is a Phase-A *mechanical move* from
``integrated_asset_processor.AssetDatabase`` — behaviour is byte-identical
to the original. The class is re-exported from
``integrated_asset_processor`` so existing callers (``IntegratedAssetProcessor``,
``terrain_material_processor``) keep working unchanged.

After Phase B / C, ``AssetDatabase`` becomes the parsing half of the
Unity ``SourcePlatform`` plugin. The class itself is engine-coupled
(``.meta`` sidecars are Unity-specific) and lives here permanently.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class AssetDatabase:
    """Central asset database for GUID resolution"""

    def __init__(self, unity_assets_root: Path):
        self.unity_assets_root = unity_assets_root
        self.guid_to_path: Dict[str, Path] = {}
        # Raw parsed YAML body keyed by str(path). Separated from the
        # profile-applied extraction cache so a re-parse under a different
        # profile reuses the expensive YAML parse.
        self.material_yaml_cache: Dict[str, Dict] = {}
        # Profile-applied extraction. Key: (str(path), profile_id). The
        # legacy "no profile" call sites (e.g. terrain_material_processor)
        # use profile_id=0; F-9 worker calls pass profile_id=id(profile_dict).
        self.material_cache: Dict[tuple, Dict] = {}
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

    def parse_material(self, material_path: Path,
                       profile: Optional[Dict] = None) -> Optional[Dict]:
        """Parse Unity material file and run the Unity → O3DE remap.

        ``profile`` is an F-9 shader profile dict (see
        ``project_manager.DEFAULT_SHADER_PROFILE``). When ``None``, falls back
        to the legacy hard-coded TEXTURE_MAP / PROPERTY_MAP / IGNORE_UNMAPPED
        + ``metallic_gloss_smoothness_to_roughness=True`` behaviour so
        existing callers (terrain_material_processor, tests) keep working.
        """
        profile_id = id(profile) if profile is not None else 0
        cache_key  = (str(material_path), profile_id)
        if cache_key in self.material_cache:
            return self.material_cache[cache_key]

        raw_material = self.material_yaml_cache.get(str(material_path))
        if raw_material is None:
            if not material_path.exists() or material_path.suffix != '.mat':
                return None
            try:
                with open(material_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                doc_pattern = r'---\s+!u!\d+\s+&(\d+)\n(.*?)(?=---\s+!u!|\Z)'
                matches = re.findall(doc_pattern, content, re.DOTALL)
                for _anchor, doc_content in matches:
                    clean_content = re.sub(r'!u!\d+', '', doc_content)
                    try:
                        doc = yaml.safe_load(clean_content)
                    except yaml.YAMLError:
                        continue
                    if doc and 'Material' in doc:
                        raw_material = doc['Material']
                        self.material_yaml_cache[str(material_path)] = raw_material
                        break
            except Exception as e:
                print(f"Error parsing material {material_path}: {e}")
                return None

        if raw_material is None:
            return None

        extracted = self._extract_material_data(raw_material, profile=profile)
        self.material_cache[cache_key] = extracted
        return extracted

    def _extract_material_data(self, material_data: Dict,
                                profile: Optional[Dict] = None) -> Dict:
        """Extract material properties and texture references.

        When ``profile`` is provided, the texture remap, property remap,
        ignore list, and the metallic-gloss → roughness special rule come
        from the profile data (see ``project_manager.DEFAULT_SHADER_PROFILE``).
        When ``profile`` is ``None``, fall back to the legacy hard-coded
        dicts so callers that don't know about profiles (e.g.
        ``terrain_material_processor``) keep working.

        Note: the legacy fallback dicts mirror the
        ``Default — Anything to PBR`` profile byte-for-byte. They live here
        AS WELL AS in ``project_manager`` so a tool import that doesn't pull
        ``project_manager`` (e.g. a standalone CLI) can still run.
        """
        if profile is not None:
            # Profile-driven mode (F-9). Flatten the {slot, transform}
            # entries: F-9 only consumes the slot field — transforms beyond
            # "passthrough" land in F-10 with the editor.
            TEXTURE_MAP = {
                unity_prop: entry["slot"]
                for unity_prop, entry in (profile.get("texture_map") or {}).items()
                if isinstance(entry, dict) and entry.get("slot")
            }
            IGNORE_UNMAPPED = set(profile.get("ignore_unmapped") or [])
            PROPERTY_MAP = {
                unity_prop: entry["target"]
                for unity_prop, entry in (profile.get("property_map") or {}).items()
                if isinstance(entry, dict) and entry.get("target")
            }
            special_rules        = profile.get("special_rules") or {}
            smoothness_to_rough  = bool(special_rules.get(
                "metallic_gloss_smoothness_to_roughness", True))
        else:
            # Legacy hard-coded behaviour. Kept verbatim so the no-profile
            # call path is byte-identical to pre-F-9.
            TEXTURE_MAP = {
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
                '_BumpMap':          'normal',
                '_NormalMap':        'normal',
                '_NormalTex':        'normal',
                '_MetallicGlossMap': 'metallic',
                '_MetallicMap':      'metallic',
                '_MetallicTex':      'metallic',
                '_Metallic_Map':     'metallic',
                '_SpecGlossMap':     'specular',
                '_SpecularMap':      'specular',
                '_OcclusionMap':         'occlusion.specular',
                '_AOMap':                'occlusion.specular',
                '_AmbientOcclusion':     'occlusion.specular',
                '_AmbientOcclusionMap':  'occlusion.specular',
                '_AO':                   'occlusion.specular',
                '_RockAlbedo':       'baseColor',
                '_RockNormal':       'normal',
                '_RockSpecular':     'specular',
                '_EmissionMap':      'emissive',
                '_EmissionTex':      'emissive',
                '_EmissiveMap':      'emissive',
                '_Emissive':         'emissive',
                '_HeightMap':        'height',
                '_ParallaxMap':      'height',
                '_DisplacementMap':  'height',
            }
            IGNORE_UNMAPPED = {
                '_DetailAlbedoMap', '_DetailMask', '_DetailNormalMap',
                '_LightTextureB0', '_VectorNoise', '_texcoord',
                '_Composite', '_CompositeMap', '_MOHS', '_MaskMap',
                '_Detail', '_AODetail',
                '_CoverAlbedo', '_CoverNormal', '_CoverSpecular',
            }
            PROPERTY_MAP = {
                '_Color':             'baseColor.color',
                '_BaseColor':         'baseColor.color',
                '_BumpScale':         'normal.factor',
                '_OcclusionStrength': 'occlusion.specularFactor',
                '_EmissionColor':     'emissive.color',
            }
            smoothness_to_rough = True

        # Unity materials store m_Shader as a reference, not a name. Record
        # the guid + fileID so _process_material can resolve the friendly
        # "Shader \"Name\"" string via the .shader file (or a built-in
        # lookup table).
        shader_ref = material_data.get('m_Shader') or {}
        if not isinstance(shader_ref, dict):
            shader_ref = {}
        extracted = {
            'name':         material_data.get('m_Name', 'Material'),
            'shader':       '',  # filled by _process_material via _resolve_shader_name
            'shader_guid':  shader_ref.get('guid', '') or '',
            'shader_fileid': shader_ref.get('fileID', 0) or 0,
            'textures':    {},
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

                    # Unity's _MetallicGlossMap contains metallic in RGB and smoothness in Alpha.
                    # O3DE needs the same texture for both metallic and roughness, but only
                    # when the profile's smoothness_to_roughness rule is enabled.
                    if prop_name == '_MetallicGlossMap' and smoothness_to_rough:
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
        # The inversion below assumes Unity stored smoothness — profiles whose
        # source shader already speaks roughness can flip
        # `metallic_gloss_smoothness_to_roughness` off so the value passes
        # through untouched.
        if has_roughness_tex and smoothness_to_rough:
            # Standard's _GlossMapScale takes precedence over _Smoothness/_Glossiness
            # when a gloss map is present (URP collapses both into _Smoothness).
            multiplier = (raw_smoothness_mult
                          if raw_smoothness_mult is not None
                          else raw_smoothness)
            if multiplier is not None:
                lower = max(0.0, min(1.0, 1.0 - float(multiplier)))
                extracted['properties']['roughness.lowerBound'] = lower
                extracted['properties']['roughness.upperBound'] = 1.0
        elif raw_smoothness is not None and smoothness_to_rough:
            extracted['properties']['roughness.factor'] = max(
                0.0, min(1.0, 1.0 - raw_smoothness)
            )
        elif raw_smoothness is not None and not smoothness_to_rough:
            # Profile says the source is already roughness, not smoothness.
            extracted['properties']['roughness.factor'] = max(
                0.0, min(1.0, raw_smoothness)
            )

        # ---------------------------------------------------------------
        # Transparency / Cutout Detection
        # Unity URP/HDRP:
        #   _Surface=0  = Opaque
        #   _Surface=1  = Transparent (blended)
        #   _AlphaClip=1 = alpha-tested mask (Cutout)
        # Unity Standard shader:
        #   _Mode=0 = Opaque, _Mode=1 = Cutout, _Mode>=2 = Transparent
        #   _Cutoff = alpha clip threshold (0..1)
        #
        # O3DE opacity modes:
        #   "Opaque"  — no transparency
        #   "Cutout"  — opaque with alpha-tested mask, uses opacity.alphaSource + factor
        #   "Blended" — true alpha blending
        #
        # CUTOUT TAKES PRECEDENCE over Blended. Materials in the wild set both
        # signals (Office's MetalShelf: _AlphaClip=1 + _Mode=1 AND _Surface=1)
        # — an alpha-tested metal authored on a transparent-surface shader.
        # Reading _Surface first made it Blended → fully invisible in O3DE.
        # Alpha-clip wins because it fails safe (hard edges, still visible)
        # whereas a wrong Blended fails worst (the whole mesh vanishes). True
        # glass (Surface=1, AlphaClip=0, Mode>=2) still resolves to Blended.
        # ---------------------------------------------------------------
        raw_floats = {}
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name in ('_Mode', '_Surface', '_Blend', '_AlphaClip', '_Cutoff'):
                    raw_floats[prop_name] = float(value)

        is_cutout      = (raw_floats.get('_AlphaClip', 0) == 1
                          or raw_floats.get('_Mode', 0) == 1)
        is_transparent = (not is_cutout
                          and (raw_floats.get('_Surface', 0) == 1
                               or raw_floats.get('_Mode', 0) >= 2))

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
