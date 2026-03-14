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
    component_data: Dict[str, Any] = field(default_factory=dict)  # processor-specific state


class AssetDatabase:
    """Central asset database for GUID resolution"""
    
    def __init__(self, unity_assets_root: Path):
        self.unity_assets_root = unity_assets_root
        self.guid_to_path: Dict[str, Path] = {}
        self.material_cache: Dict[str, Dict] = {}
        self.texture_extensions = {'.png', '.jpg', '.jpeg', '.tga', '.tiff', '.bmp', '.psd', '.exr', '.hdr'}
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
            '_MainTex': 'baseColor',
            '_BaseMap': 'baseColor',
            '_BaseColorMap': 'baseColor',
            '_BumpMap': 'normal',
            '_NormalMap': 'normal',
            '_MetallicGlossMap': 'metallic',
            '_MetallicMap': 'metallic',
            '_SpecGlossMap': 'specular',
            '_OcclusionMap': 'occlusion.specular',  # O3DE uses occlusion.specularTextureMap
            '_EmissionMap': 'emissive',
            '_HeightMap': 'height',
            '_ParallaxMap': 'height',
        }
        
        PROPERTY_MAP = {
            '_Color': 'baseColor.color',
            '_BaseColor': 'baseColor.color',
            '_Metallic': 'metallic.factor',
            '_Smoothness': 'roughness.factor',
            '_Glossiness': 'roughness.factor',
            '_BumpScale': 'normal.factor',
            '_OcclusionStrength': 'occlusion.specularFactor',  # O3DE uses occlusion.specularFactor
            '_EmissionColor': 'emissive.color',
        }
        
        extracted = {
            'name': material_data.get('m_Name', 'Material'),
            'shader': material_data.get('m_Shader', {}).get('m_Name', ''),
            'textures': {},
            'properties': {},
        }
        
        saved_properties = material_data.get('m_SavedProperties', {})
        
        # Extract textures
        tex_envs = saved_properties.get('m_TexEnvs', [])
        for tex_prop in tex_envs:
            for prop_name, tex_data in tex_prop.items():
                texture_ref = tex_data.get('m_Texture', {})
                guid = texture_ref.get('guid', '')
                
                if guid and prop_name in TEXTURE_MAP:
                    o3de_prop = TEXTURE_MAP[prop_name]
                    extracted['textures'][o3de_prop] = guid
                    
                    # Unity's _MetallicGlossMap contains metallic in RGB and smoothness in Alpha
                    # O3DE needs the same texture for both metallic and roughness
                    if prop_name == '_MetallicGlossMap':
                        extracted['textures']['roughness'] = guid
        
        # Extract float properties
        floats = saved_properties.get('m_Floats', [])
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name in PROPERTY_MAP:
                    o3de_prop = PROPERTY_MAP[prop_name]
                    if prop_name in ['_Smoothness', '_Glossiness']:
                        value = 1.0 - value
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
        # Transparency Detection
        # Unity: _Surface=1 (URP/HDRP) or _Mode>=2 (Standard) = Transparent
        #        _AlphaClip=1 or _Mode==1 (Standard) = Alpha Clipping
        #        _Cutoff = clip threshold (0..1)
        # O3DE:  opacity.mode "Blended", opacity.factor (0=clear, 1=opaque)
        # ---------------------------------------------------------------
        raw_floats = {}
        for float_prop in floats:
            for prop_name, value in float_prop.items():
                if prop_name in ('_Mode', '_Surface', '_Blend', '_AlphaClip', '_Cutoff'):
                    raw_floats[prop_name] = float(value)

        is_transparent = (raw_floats.get('_Surface', 0) == 1
                          or raw_floats.get('_Mode', 0) >= 2)
        has_alpha_clip = (raw_floats.get('_AlphaClip', 0) == 1
                          or raw_floats.get('_Mode', 0) == 1)

        if is_transparent or has_alpha_clip:
            extracted['properties']['opacity.mode'] = "Blended"
            if has_alpha_clip:
                extracted['properties']['opacity.factor'] = raw_floats.get('_Cutoff', 0.5)

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
                         entity_node_map: dict, log=print) -> None:
    """Write an O3DE .assetinfo with one named MeshGroup per mesh entity.

    Group name format: "{fbx_stem}-{entity_name}"  e.g. "Closet_A-Glass_L"
    O3DE lowercases the output: closet_a-glass_l.fbx.azmodel

    Each group selects exactly its FBX node; all other mesh nodes are unselected.
    Rules mirror O3DE's auto-generated defaults: StaticMeshAdvancedRule (vertex color Col0),
    MaterialRule, CoordinateSystemRule (useAdvancedData=true), and LodRule.
    Y-up FBX files (Maya-style, up_axis==1) get a 90° pitch rotation baked into
    the CoordinateSystemRule so the mesh imports upright without a transform workaround.
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
                 log_callback=None):
        self.unity_assets_root = unity_assets_root
        self.output_root = output_root
        self.log = log_callback or print

        self.asset_db = AssetDatabase(unity_assets_root)
        
        # Output structure
        self.prefabs_dir = output_root / "Prefabs"
        self.materials_dir = output_root / "Materials"
        self.textures_dir = output_root / "Textures"
        self.meshes_dir = output_root / "Meshes"
        
        # Create directories
        self.prefabs_dir.mkdir(parents=True, exist_ok=True)
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.textures_dir.mkdir(parents=True, exist_ok=True)
        self.meshes_dir.mkdir(parents=True, exist_ok=True)
        
        # Track processed assets
        self.processed_materials: Dict[str, str] = {}  # guid -> output_path
        self.processed_textures: Dict[str, str] = {}  # guid -> output_path
        self.processed_meshes: Dict[str, Path] = {}  # guid -> output Path
        self.processed_prefabs: Set[str] = set()  # Track processed prefab GUIDs

        # Physics stats
        self.total_colliders = 0
        self.total_rigidbodies = 0

        # Get project folder name for asset hints (lowercase)
        self.project_name = output_root.name.lower()

        self.entity_id_counter = 1000000

        # Component processor registry — auto-discovered from components/
        self.component_processors = load_component_processors(self.log)
        self.component_dispatch   = build_dispatch_table(self.component_processors)
        self.log(f"  Registered {len(self.component_processors)} component processor(s)")
    
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

                node_paths = build_fbx_node_paths(entity_list, game_objects, fbx_stem, fbx_node_names)
                entity_node_map = {
                    go.name: node_paths[go.file_id]
                    for go in entity_list if go.file_id in node_paths
                }

                write_fbx_assetinfo(fbx_path, fbx_stem, entity_node_map, self.log)

                for go in entity_list:
                    if go.file_id in node_paths:
                        group_name = f"{fbx_stem}-{go.name}".lower()
                        mesh_mapping[go.file_id] = (
                            f"{self.project_name}/meshes/{group_name}.fbx.azmodel"
                        )
            
            # Create O3DE prefab
            output_name = prefab_path.stem
            output_path = self.prefabs_dir / f"{output_name}.prefab"
            
            self._create_o3de_prefab(
                root_go, 
                game_objects, 
                transform_map,
                material_mapping,
                mesh_mapping,
                output_path
            )
            
            self.log(f"  ✓ Created O3DE prefab: {output_path.name}")
            return True
        
        except Exception as e:
            self.log(f"  ✗ Error processing prefab: {e}")
            import traceback
            traceback.print_exc()
            return False
    
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
                    # Dispatch to registered component processors
                    for known_type in self.component_dispatch:
                        if known_type in doc:
                            components_data[anchor] = {'type': known_type, 'data': doc[known_type]}
                            break
            
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
        """Parse PrefabInstance block in a Unity prefab - these represent nested prefabs"""
        # Extract source prefab GUID
        source_prefab = instance_data.get('m_SourcePrefab', {})
        prefab_guid = source_prefab.get('guid', '')
        if not prefab_guid:
            return
        
        # Extract modifications
        modification = instance_data.get('m_Modification', {})
        modifications = modification.get('m_Modifications', [])
        parent_transform = modification.get('m_TransformParent', {})
        parent_id = str(parent_transform.get('fileID', ''))
        
        # Extract name from modifications
        name = 'PrefabInstance'
        for mod in modifications:
            if mod.get('propertyPath') == 'm_Name':
                name = mod.get('value', 'PrefabInstance')
                break
        
        # Extract transform data from modifications
        position = [0.0, 0.0, 0.0]
        rotation = [0.0, 0.0, 0.0, 1.0]  # quaternion
        scale = [1.0, 1.0, 1.0]
        
        for mod in modifications:
            prop_path = mod.get('propertyPath', '')
            value = mod.get('value', 0)
            
            if 'm_LocalPosition.x' in prop_path:
                position[0] = float(value)
            elif 'm_LocalPosition.y' in prop_path:
                position[1] = float(value)
            elif 'm_LocalPosition.z' in prop_path:
                position[2] = float(value)
            elif 'm_LocalRotation.x' in prop_path:
                rotation[0] = float(value)
            elif 'm_LocalRotation.y' in prop_path:
                rotation[1] = float(value)
            elif 'm_LocalRotation.z' in prop_path:
                rotation[2] = float(value)
            elif 'm_LocalRotation.w' in prop_path:
                rotation[3] = float(value)
            elif 'm_LocalScale.x' in prop_path:
                scale[0] = float(value)
            elif 'm_LocalScale.y' in prop_path:
                scale[1] = float(value)
            elif 'm_LocalScale.z' in prop_path:
                scale[2] = float(value)
        
        # Create GameObject for this prefab instance
        transform = Transform(
            position=tuple(position),
            rotation=tuple(rotation),
            scale=tuple(scale)
        )
        
        file_id = anchor
        go = GameObject(
            file_id=file_id,
            name=name,
            transform=transform,
            is_prefab_instance=True,
            prefab_source_guid=prefab_guid
        )
        
        # Set parent - will be resolved later in _build_hierarchy
        if parent_id and parent_id != '0':
            go.parent_id = parent_id
        
        game_objects[file_id] = go
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
            return None
        
        self.log(f"    Processing material: {material_path.name}")
        
        # Parse material
        material_data = self.asset_db.parse_material(material_path)
        if not material_data:
            self.log(f"      ⚠ Failed to parse material")
            return None
        
        # Process textures
        texture_paths = {}
        for o3de_prop, texture_guid in material_data.get('textures', {}).items():
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
        
        # Write material file
        with open(output_path, 'w') as f:
            json.dump(o3de_material, f, indent=4)
        
        # Generate gem-style asset hint: projectname/materials/filename.azmaterial
        asset_hint = f"{self.project_name}/materials/{output_path.stem}.azmaterial"
        self.processed_materials[material_guid] = asset_hint
        
        self.log(f"      ✓ Created material with {len(texture_paths)} textures")
        
        return asset_hint
    
    def _process_texture(self, texture_guid: str) -> Optional[str]:
        """Process texture - copy to output directory"""
        if texture_guid in self.processed_textures:
            return self.processed_textures[texture_guid]
        
        texture_path = self.asset_db.resolve_guid(texture_guid)
        if not texture_path or texture_path.suffix.lower() not in self.asset_db.texture_extensions:
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
    
    def _process_mesh(self, mesh_guid: str) -> Optional[Path]:
        """Process mesh — copy to output directory. Returns output Path or None."""
        if mesh_guid in self.processed_meshes:
            cached = self.processed_meshes[mesh_guid]
            # Return Path if cached, or None
            return cached if isinstance(cached, Path) else None

        mesh_path = self.asset_db.resolve_guid(mesh_guid)
        if not mesh_path or mesh_path.suffix.lower() not in self.asset_db.mesh_extensions:
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
                           output_path: Path) -> None:
        """Create O3DE prefab in JSON format"""
        # ContainerEntity uses the root GameObject's name
        prefab_data = {
            "ContainerEntity": self._create_container_entity(root_go),
            "Entities": {},
            "Instances": {}
        }
        
        entity_id_map = {}
        
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
            parent_entity_id="ContainerEntity"
        )
        
        # Set child order in ContainerEntity
        if root_entity_id:
            prefab_data["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"] = [root_entity_id]
        
        with open(output_path, 'w') as f:
            json.dump(prefab_data, f, indent=4)
    
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
    
    
    def _create_nested_prefab_instance(self, go: GameObject, prefab_path: Path, parent_entity_id: str) -> Dict:
        """Create a nested prefab instance entry"""
        # Generate gem-style source path
        source_path = f"{self.project_name}/prefabs/{prefab_path.name}"
        
        o3de_transform, _ = self._convert_to_o3de_coordinates(go.transform)
        
        patches = [
            {
                "op": "replace",
                "path": "/ContainerEntity/Components/TransformComponent/Parent Entity",
                "value": f"../{parent_entity_id}"
            }
        ]
        
        # Add transform patches if non-default
        if any(abs(v) > 0.0001 for v in o3de_transform.position):
            patches.extend([
                {
                    "op": "replace",
                    "path": "/ContainerEntity/Components/TransformComponent/Transform Data/Translate/0",
                    "value": o3de_transform.position[0]
                },
                {
                    "op": "replace",
                    "path": "/ContainerEntity/Components/TransformComponent/Transform Data/Translate/1",
                    "value": o3de_transform.position[1]
                },
                {
                    "op": "replace",
                    "path": "/ContainerEntity/Components/TransformComponent/Transform Data/Translate/2",
                    "value": o3de_transform.position[2]
                }
            ])
        
        return {
            "Source": source_path,
            "Patches": patches
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
            entities_dict         = entities_dict,
            entity_id_map         = entity_id_map,
            generate_component_id = self._generate_component_id,
            generate_entity_id    = self._generate_entity_id,
            make_bare_entity      = self._make_bare_entity,
            log                   = self.log,
        )

        collider_child_ids = []
        for processor in self.component_processors:
            child_ids = processor.emit(go, entity, ctx)
            collider_child_ids.extend(child_ids)

        # Update physics stats from what processors created
        self.total_colliders   += len(go.colliders)
        self.total_rigidbodies += 1 if (go.has_rigidbody or go.colliders) else 0

        # ---------------------------------------------------------------
        # Child entities: GO children + any collider sub-entities
        # ---------------------------------------------------------------
        child_order = []
        for child_id in go.children_ids:
            if child_id in all_game_objects:
                child_entity_id = self._create_entity_recursive(
                    all_game_objects[child_id], all_game_objects,
                    entities_dict, instances_dict, entity_id_map,
                    material_mapping, mesh_mapping, entity_id
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