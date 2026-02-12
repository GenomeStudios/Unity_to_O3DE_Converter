#!/usr/bin/env python3
"""
Integrated Unity Prefab + Material Asset Processor

Reads Unity prefabs, finds referenced materials, generates O3DE materials with textures,
and copies everything to a homogenized folder structure.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import yaml
import json
import os
import re
import shutil
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
import threading
import random


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


# ===================================================================
#  Blender Integration — FBX Transform Baking
# ===================================================================

# Common Blender install locations (Windows)
_BLENDER_SEARCH_PATHS = [
    Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Blender Foundation",
    Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Blender Foundation",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Blender Foundation",
]

# Path to the bake script shipped alongside this file
_BAKE_SCRIPT = Path(__file__).parent / "bake_fbx_transforms.py"


def find_blender() -> Optional[Path]:
    """Auto-detect a Blender installation on this machine.

    Checks PATH first, then common install directories.
    Returns the full path to blender.exe or None.
    """
    # 1. Check PATH
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        candidate = Path(d) / "blender.exe"
        if candidate.is_file():
            return candidate

    # 2. Search common install folders (pick newest version)
    candidates: list[Path] = []
    for search_root in _BLENDER_SEARCH_PATHS:
        if not search_root.is_dir():
            continue
        for version_dir in search_root.iterdir():
            exe = version_dir / "blender.exe"
            if exe.is_file():
                candidates.append(exe)

    if candidates:
        candidates.sort(key=lambda p: p.parent.name, reverse=True)
        return candidates[0]

    return None


def validate_blender(blender_path: Optional[str]) -> Optional[Path]:
    """Return a valid Path to blender.exe, or None."""
    if not blender_path:
        return None
    p = Path(blender_path)
    if p.is_file() and p.name.lower() in ("blender.exe", "blender"):
        return p
    return None


def bake_fbx_with_blender(blender_exe: Path, input_fbx: Path,
                           output_fbx: Path, log=print) -> bool:
    """Run the Blender bake script on a single FBX file.

    Returns True on success.
    """
    cmd = [
        str(blender_exe),
        "--background",
        "--python", str(_BAKE_SCRIPT),
        "--",
        str(input_fbx),
        str(output_fbx),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            log(f"      [Blender] stderr: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log("      [Blender] Timed out after 120 s")
        return False
    except FileNotFoundError:
        log(f"      [Blender] Executable not found: {blender_exe}")
        return False


class IntegratedAssetProcessor:
    """Processes Unity prefabs with materials to O3DE format"""
    
    def __init__(self, unity_assets_root: Path, output_root: Path,
                 log_callback=None, blender_path: Optional[Path] = None):
        self.unity_assets_root = unity_assets_root
        self.output_root = output_root
        self.log = log_callback or print
        self.blender_path = blender_path

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
        self.processed_meshes: Dict[str, str] = {}  # guid -> output_path
        self.processed_prefabs: Set[str] = set()  # Track processed prefab GUIDs

        # Physics stats
        self.total_colliders = 0
        self.total_rigidbodies = 0
        
        # Get project folder name for asset hints (lowercase)
        self.project_name = output_root.name.lower()
        
        self.entity_id_counter = 1000000
    
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
            
            mesh_mapping = {}
            for mesh_guid in all_mesh_guids:
                if mesh_guid:
                    o3de_mesh_path = self._process_mesh(mesh_guid)
                    if o3de_mesh_path:
                        mesh_mapping[mesh_guid] = o3de_mesh_path
            
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
                    # In Unity prefabs, PrefabInstance blocks represent nested prefabs
                    # We need to create a GameObject for each one
                    self._parse_prefab_instance_in_prefab(doc['PrefabInstance'], anchor, game_objects, transform_to_gameobject)
                elif 'MeshFilter' in doc:
                    components_data[anchor] = {'type': 'MeshFilter', 'data': doc['MeshFilter']}
                elif 'MeshRenderer' in doc:
                    components_data[anchor] = {'type': 'MeshRenderer', 'data': doc['MeshRenderer']}
                elif 'Rigidbody' in doc:
                    components_data[anchor] = {'type': 'Rigidbody', 'data': doc['Rigidbody']}
                elif 'BoxCollider' in doc:
                    components_data[anchor] = {'type': 'BoxCollider', 'data': doc['BoxCollider']}
                elif 'SphereCollider' in doc:
                    components_data[anchor] = {'type': 'SphereCollider', 'data': doc['SphereCollider']}
                elif 'CapsuleCollider' in doc:
                    components_data[anchor] = {'type': 'CapsuleCollider', 'data': doc['CapsuleCollider']}
                elif 'MeshCollider' in doc:
                    components_data[anchor] = {'type': 'MeshCollider', 'data': doc['MeshCollider']}
            
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
        
        # Assign component data (simplified - looking for material GUIDs)
        for comp_id, comp_info in components_data.items():
            comp_type = comp_info.get('type')
            comp_data = comp_info.get('data', {})
            
            # Find which GameObject this component belongs to
            go_ref = comp_data.get('m_GameObject', {})
            go_id = str(go_ref.get('fileID', ''))
            
            if go_id in game_objects:
                go = game_objects[go_id]
                
                if comp_type == 'MeshRenderer':
                    materials = comp_data.get('m_Materials', [])
                    for mat_ref in materials:
                        guid = mat_ref.get('guid', '')
                        if guid:
                            go.material_guids.append(guid)
                
                elif comp_type == 'MeshFilter':
                    mesh_ref = comp_data.get('m_Mesh', {})
                    guid = mesh_ref.get('guid', '')
                    if guid:
                        go.mesh_guid = guid
                
                elif comp_type == 'Rigidbody':
                    go.has_rigidbody = True
                    go.rigidbody_data = {
                        'mass': comp_data.get('m_Mass', 1.0),
                        'drag': comp_data.get('m_Drag', 0.0),
                        'angular_drag': comp_data.get('m_AngularDrag', 0.05),
                        'use_gravity': comp_data.get('m_UseGravity', 1) == 1,
                        'is_kinematic': comp_data.get('m_IsKinematic', 0) == 1,
                        'constraints': comp_data.get('m_Constraints', 0),
                    }
                
                elif comp_type in ['BoxCollider', 'SphereCollider', 'CapsuleCollider', 'MeshCollider']:
                    collider_info = {'type': comp_type}
                    collider_info.update(self._parse_collider_data(comp_data, comp_type))
                    go.colliders.append(collider_info)
    
    def _parse_collider_data(self, comp_data: Dict, comp_type: str) -> Dict:
        """Parse collider component data"""
        result = {'is_trigger': comp_data.get('m_IsTrigger', 0) == 1}
        
        center = comp_data.get('m_Center', {'x': 0, 'y': 0, 'z': 0})
        result['center'] = (float(center.get('x', 0)), float(center.get('y', 0)), float(center.get('z', 0)))
        
        if comp_type == 'BoxCollider':
            size = comp_data.get('m_Size', {'x': 1, 'y': 1, 'z': 1})
            result['size'] = (float(size.get('x', 1)), float(size.get('y', 1)), float(size.get('z', 1)))
        
        elif comp_type == 'SphereCollider':
            result['radius'] = float(comp_data.get('m_Radius', 0.5))
        
        elif comp_type == 'CapsuleCollider':
            result['radius'] = float(comp_data.get('m_Radius', 0.5))
            result['height'] = float(comp_data.get('m_Height', 2.0))
            result['direction'] = int(comp_data.get('m_Direction', 1))
        
        elif comp_type == 'MeshCollider':
            mesh_ref = comp_data.get('m_Mesh', {})
            result['mesh_guid'] = mesh_ref.get('guid', '')
            result['convex'] = comp_data.get('m_Convex', 0) == 1
        
        return result
    
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
    
    def _process_mesh(self, mesh_guid: str) -> Optional[str]:
        """Process mesh — copy to output, optionally bake transforms via Blender."""
        if mesh_guid in self.processed_meshes:
            return self.processed_meshes[mesh_guid]

        mesh_path = self.asset_db.resolve_guid(mesh_guid)
        if not mesh_path or mesh_path.suffix.lower() not in self.asset_db.mesh_extensions:
            return None

        self.log(f"    Processing mesh: {mesh_path.name}")

        output_path = self.meshes_dir / mesh_path.name

        try:
            if not output_path.exists():
                # Blender bake: import → apply transforms → re-export
                if (self.blender_path
                        and mesh_path.suffix.lower() == '.fbx'):
                    self.log(f"      Baking transforms via Blender...")
                    ok = bake_fbx_with_blender(
                        self.blender_path, mesh_path, output_path, self.log
                    )
                    if ok:
                        self.log(f"      ✓ Baked and exported mesh")
                    else:
                        # Fallback: raw copy so the pipeline continues
                        shutil.copy2(mesh_path, output_path)
                        self.log(f"      ⚠ Bake failed — raw copy used")
                else:
                    shutil.copy2(mesh_path, output_path)
                    self.log(f"      ✓ Copied mesh file")
            else:
                self.log(f"      → Mesh already exists")

            asset_hint = f"{self.project_name}/meshes/{output_path.name}.azmodel"
            self.processed_meshes[mesh_guid] = asset_hint
            return asset_hint

        except Exception as e:
            self.log(f"      ⚠ Failed to process mesh {mesh_path.name}: {e}")
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
        o3de_pos = (-unity_transform.position[0], unity_transform.position[2], unity_transform.position[1])
        qx, qy, qz, qw = unity_transform.rotation
        o3de_rot = (-qx, qz, qy, qw)
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
    #  PhysX Component Generation
    # ===================================================================

    def _create_physx_components(self, go: GameObject, entity: Dict,
                                 mesh_mapping: Dict,
                                 entities_dict: Dict) -> List[str]:
        """Add PhysX collider and rigidbody components to an entity.

        O3DE allows only ONE collider per entity. When a Unity GO has
        multiple colliders, extras become child entities named
        '{ParentName}_Collider_{N}'.

        Mapping:
          BoxCollider    -> EditorBoxShapeComponent     + EditorShapeColliderComponent
          SphereCollider -> EditorSphereShapeComponent   + EditorShapeColliderComponent
          CapsuleCollider-> EditorCapsuleShapeComponent  + EditorShapeColliderComponent
          MeshCollider   -> EditorMeshColliderComponent
          Rigidbody      -> EditorRigidBodyComponent     (dynamic)
          No Rigidbody   -> EditorStaticRigidBodyComponent (static companion)

        Returns list of child entity IDs created for multi-collider setups.
        """
        if not go.colliders and not go.has_rigidbody:
            return []

        components = entity["Components"]
        child_entity_ids = []

        # ---------------------------------------------------------------
        #  Colliders — first on main entity, extras as child entities
        # ---------------------------------------------------------------
        for idx, collider in enumerate(go.colliders):

            if idx == 0:
                target = components
            else:
                child_id = self._generate_entity_id()
                child = self._make_bare_entity(
                    child_id,
                    f"{go.name}_Collider_{idx}",
                    entity["Id"]
                )
                child["Components"]["EditorStaticRigidBodyComponent"] = {
                    "$type": "EditorStaticRigidBodyComponent",
                    "Id": self._generate_component_id()
                }
                entities_dict[child_id] = child
                child_entity_ids.append(child_id)
                target = child["Components"]

            col_type = collider['type']
            cx, cy, cz = collider.get('center', (0, 0, 0))
            offset = [-cx, cz, cy]  # Unity (x,y,z) -> O3DE (-x,z,y)
            is_trigger = collider.get('is_trigger', False)

            if col_type == 'MeshCollider':
                self._add_mesh_collider(target, collider, is_trigger,
                                        mesh_mapping, go)
            else:
                self._add_shape_collider(target, collider, col_type,
                                         offset, is_trigger)
            self.total_colliders += 1

        # ---------------------------------------------------------------
        #  Rigid Body
        # ---------------------------------------------------------------
        if go.has_rigidbody:
            rb = go.rigidbody_data or {}
            config = {
                "Mass": float(rb.get('mass', 1.0)),
                "Linear damping": float(rb.get('drag', 0.0)),
                "Angular damping": float(rb.get('angular_drag', 0.05)),
                "Gravity Enabled": rb.get('use_gravity', True),
            }
            if rb.get('is_kinematic', False):
                config["Kinematic"] = True

            # Unity constraint bitmask -> O3DE lock flags
            # Unity: PosX=2 PosY=4 PosZ=8 RotX=16 RotY=32 RotZ=64
            # Axis swap: Unity Y -> O3DE Z, Unity Z -> O3DE Y
            constraints = rb.get('constraints', 0)
            if constraints:
                if constraints & 2:  config["Lock Linear X"] = True
                if constraints & 4:  config["Lock Linear Z"] = True   # Y->Z
                if constraints & 8:  config["Lock Linear Y"] = True   # Z->Y
                if constraints & 16: config["Lock Angular X"] = True
                if constraints & 32: config["Lock Angular Z"] = True  # Y->Z
                if constraints & 64: config["Lock Angular Y"] = True  # Z->Y

            components["EditorRigidBodyComponent"] = {
                "$type": "EditorRigidBodyComponent",
                "Id": self._generate_component_id(),
                "Configuration": config
            }
            self.total_rigidbodies += 1

        elif go.colliders:
            components["EditorStaticRigidBodyComponent"] = {
                "$type": "EditorStaticRigidBodyComponent",
                "Id": self._generate_component_id()
            }
            self.total_rigidbodies += 1

        return child_entity_ids

    # ===================================================================
    #  Collider Helpers
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

    def _add_mesh_collider(self, components: Dict, collider: Dict,
                           is_trigger: bool, mesh_mapping: Dict,
                           go: GameObject) -> None:
        """Add an EditorMeshColliderComponent to *components*."""
        collider_cfg = {
            "MaterialSlots": {
                "Slots": [{"Name": "Entire object"}]
            }
        }
        if is_trigger:
            collider_cfg["Trigger"] = True

        mesh_comp = {
            "$type": "EditorMeshColliderComponent",
            "Id": self._generate_component_id(),
            "ColliderConfiguration": collider_cfg
        }

        # Resolve .pxmesh asset hint from collider mesh or render mesh
        hint = None
        mesh_guid = collider.get('mesh_guid', '')
        if mesh_guid and mesh_guid in mesh_mapping:
            hint = mesh_mapping[mesh_guid].replace('.azmodel', '.pxmesh')
        elif go.mesh_guid and go.mesh_guid in mesh_mapping:
            hint = mesh_mapping[go.mesh_guid].replace('.azmodel', '.pxmesh')

        if hint:
            mesh_comp["ShapeConfiguration"] = {
                "PhysicsAsset": {
                    "Asset": {
                        "assetHint": hint
                    },
                    "Configuration": {
                        "PhysicsAsset": {
                            "loadBehavior": "QueueLoad",
                            "assetHint": hint
                        }
                    }
                }
            }

        components["EditorMeshColliderComponent"] = mesh_comp

    def _add_shape_collider(self, components: Dict, collider: Dict,
                            col_type: str, offset: List[float],
                            is_trigger: bool) -> None:
        """Add Editor{Shape}ShapeComponent + EditorShapeColliderComponent."""
        has_offset = any(abs(v) > 0.0001 for v in offset)
        shape_config = {}  # entry for ShapeConfigs array

        # ----- Box -----
        if col_type == 'BoxCollider':
            sx, sy, sz = collider.get('size', (1, 1, 1))
            dims = [sx, sz, sy]  # swap Y/Z
            shape_config = {"$type": "BoxShapeConfiguration", "Configuration": dims}

            box_cfg = {"Dimensions": dims}
            if has_offset:
                box_cfg["TranslationOffset"] = offset
            components["EditorBoxShapeComponent"] = {
                "$type": "EditorBoxShapeComponent",
                "Id": self._generate_component_id(),
                "BoxShape": {"Configuration": box_cfg}
            }

        # ----- Sphere -----
        elif col_type == 'SphereCollider':
            radius = collider.get('radius', 0.5)
            shape_config = {"$type": "SphereShapeConfiguration", "Radius": radius}

            sphere_cfg = {"Radius": radius}
            if has_offset:
                sphere_cfg["TranslationOffset"] = offset
            components["EditorSphereShapeComponent"] = {
                "$type": "EditorSphereShapeComponent",
                "Id": self._generate_component_id(),
                "SphereShape": {"Configuration": sphere_cfg}
            }

        # ----- Capsule -----
        elif col_type == 'CapsuleCollider':
            height = collider.get('height', 2.0)
            radius = collider.get('radius', 0.5)
            shape_config = {
                "$type": "CapsuleShapeConfiguration",
                "Height": height, "Radius": radius
            }

            capsule_cfg = {"Height": height, "Radius": radius}
            if has_offset:
                capsule_cfg["TranslationOffset"] = offset
            components["EditorCapsuleShapeComponent"] = {
                "$type": "EditorCapsuleShapeComponent",
                "Id": self._generate_component_id(),
                "CapsuleShape": {"Configuration": capsule_cfg}
            }

        # Paired EditorShapeColliderComponent
        collider_cfg = {
            "MaterialSlots": {
                "Slots": [{"Name": "Entire object"}]
            }
        }
        if is_trigger:
            collider_cfg["Trigger"] = True
        if has_offset:
            collider_cfg["Position"] = offset

        components["EditorShapeColliderComponent"] = {
            "$type": "EditorShapeColliderComponent",
            "Id": self._generate_component_id(),
            "ColliderConfiguration": collider_cfg,
            "ShapeConfigs": [shape_config]
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
        
        if go.mesh_guid:
            mesh_path = mesh_mapping.get(go.mesh_guid)
            if mesh_path:
                entity["Components"]["AZ::Render::EditorMeshComponent"] = {
                    "$type": "AZ::Render::EditorMeshComponent",
                    "Id": self._generate_component_id(),
                    "Controller": {
                        "Configuration": {
                            "ModelAsset": {
                                "assetHint": mesh_path
                            }
                        }
                    }
                }
        
        # ---------------------------------------------------------------
        # Material Component - map each Unity material to an O3DE slot
        # Slot "{0}" = mesh material index 0, "{1}" = index 1, etc.
        # ---------------------------------------------------------------
        if go.material_guids:
            materials_config = {}
            for idx, mat_guid in enumerate(go.material_guids):
                mat_path = material_mapping.get(mat_guid)
                if mat_path:
                    slot_id = f"{{{idx}}}"
                    materials_config[slot_id] = {
                        "MaterialAsset": {
                            "assetHint": mat_path
                        }
                    }

            if materials_config:
                entity["Components"]["EditorMaterialComponent"] = {
                    "$type": "EditorMaterialComponent",
                    "Id": self._generate_component_id(),
                    "Controller": {
                        "Configuration": {
                            "materials": materials_config
                        }
                    }
                }

        # ---------------------------------------------------------------
        # PhysX Colliders + Rigid Bodies
        # ---------------------------------------------------------------
        collider_child_ids = self._create_physx_components(
            go, entity, mesh_mapping, entities_dict
        )

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


class IntegratedProcessorGUI:
    """GUI for integrated Unity asset processing"""

    def __init__(self, root):
        self.root = root
        self.root.title("Unity to O3DE Integrated Asset Processor")
        self.root.geometry("700x650")

        self._create_widgets()
        self._load_settings()
        self._check_blender_on_startup()
    
    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="Unity to O3DE Asset Processor", 
                               font=('', 12, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 15))
        
        # Source path
        ttk.Label(main_frame, text="Unity Assets Folder:", font=('', 10, 'bold')).grid(
            row=1, column=0, sticky=tk.W, pady=(0, 5))
        
        source_frame = ttk.Frame(main_frame)
        source_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        self.source_path_var = tk.StringVar()
        ttk.Entry(source_frame, textvariable=self.source_path_var, width=50).grid(
            row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(source_frame, text="Browse...", command=self._browse_source).grid(
            row=0, column=1, padx=(5, 0))
        
        source_frame.columnconfigure(0, weight=1)
        
        # Output path
        ttk.Label(main_frame, text="O3DE Output Folder:", font=('', 10, 'bold')).grid(
            row=3, column=0, sticky=tk.W, pady=(0, 5))
        
        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.output_path_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.output_path_var, width=50).grid(
            row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(output_frame, text="Browse...", command=self._browse_output).grid(
            row=0, column=1, padx=(5, 0))
        
        output_frame.columnconfigure(0, weight=1)

        # Blender path (for FBX transform baking)
        ttk.Label(main_frame, text="Blender Path (optional):",
                  font=('', 10, 'bold')).grid(
            row=5, column=0, sticky=tk.W, pady=(0, 5))

        blender_frame = ttk.Frame(main_frame)
        blender_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

        self.blender_path_var = tk.StringVar()
        ttk.Entry(blender_frame, textvariable=self.blender_path_var,
                  width=50).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(blender_frame, text="Browse...",
                   command=self._browse_blender).grid(row=0, column=1, padx=(5, 0))
        ttk.Button(blender_frame, text="Auto-detect",
                   command=self._autodetect_blender).grid(row=0, column=2, padx=(5, 0))
        blender_frame.columnconfigure(0, weight=1)

        self.blender_status_var = tk.StringVar(value="")
        self.blender_status_label = ttk.Label(
            main_frame, textvariable=self.blender_status_var,
            foreground="gray")
        self.blender_status_label.grid(row=7, column=0, sticky=tk.W, pady=(0, 10))

        # Info frame
        info_frame = ttk.LabelFrame(main_frame, text="Output Structure", padding="10")
        info_frame.grid(row=8, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        info_text = """This will create:
  • Prefabs/    - O3DE prefabs with correct material references
  • Materials/  - O3DE PBR materials with textures
  • Textures/   - All textures in one location
  • Meshes/     - FBX models (baked via Blender when available)"""

        ttk.Label(info_frame, text=info_text, justify=tk.LEFT).pack()

        # Status log
        ttk.Label(main_frame, text="Processing Log:", font=('', 10, 'bold')).grid(
            row=9, column=0, sticky=tk.W, pady=(0, 5))

        self.status_text = scrolledtext.ScrolledText(main_frame, height=15, width=70,
                                                     state='disabled')
        self.status_text.grid(row=10, column=0, sticky=(tk.W, tk.E, tk.N, tk.S),
                              pady=(0, 15))

        # Process button
        process_frame = ttk.Frame(main_frame)
        process_frame.grid(row=11, column=0, sticky=(tk.W, tk.E))

        self.process_btn = ttk.Button(process_frame, text="Process Assets",
                                      command=self._process_assets)
        self.process_btn.pack(side=tk.RIGHT)

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(10, weight=1)

        self._log("Ready. Select Unity assets folder and O3DE output folder to begin.")
    
    # ---------------------------------------------------------------
    #  Settings persistence
    # ---------------------------------------------------------------

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                cfg = data.get("asset_processor", {})
                if cfg.get("source_path"):
                    self.source_path_var.set(cfg["source_path"])
                if cfg.get("output_path"):
                    self.output_path_var.set(cfg["output_path"])
                if cfg.get("blender_path"):
                    self.blender_path_var.set(cfg["blender_path"])
                    self._update_blender_status()
        except Exception:
            pass

    def _save_settings(self):
        try:
            data = {}
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
            data["asset_processor"] = {
                "source_path": self.source_path_var.get(),
                "output_path": self.output_path_var.get(),
                "blender_path": self.blender_path_var.get(),
            }
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    # ---------------------------------------------------------------
    #  Blender path helpers
    # ---------------------------------------------------------------

    def _update_blender_status(self):
        """Refresh the status label under the Blender path field."""
        path = validate_blender(self.blender_path_var.get())
        if path:
            self.blender_status_var.set(f"Blender found: {path.parent.name}")
            self.blender_status_label.config(foreground="green")
        elif self.blender_path_var.get():
            self.blender_status_var.set("Invalid path — blender.exe not found")
            self.blender_status_label.config(foreground="red")
        else:
            self.blender_status_var.set(
                "Not set — FBX meshes will be copied without transform baking")
            self.blender_status_label.config(foreground="gray")

    def _browse_blender(self):
        path = filedialog.askopenfilename(
            title="Select blender.exe",
            filetypes=[("Blender", "blender.exe"), ("All files", "*.*")])
        if path:
            self.blender_path_var.set(path)
            self._update_blender_status()
            self._save_settings()

    def _autodetect_blender(self):
        found = find_blender()
        if found:
            self.blender_path_var.set(str(found))
            self._update_blender_status()
            self._save_settings()
            self._log(f"Blender auto-detected: {found}")
        else:
            self._update_blender_status()
            messagebox.showwarning(
                "Blender Not Found",
                "Could not find a Blender installation.\n\n"
                "FBX meshes will still be copied, but mesh pivot points\n"
                "may appear offset in O3DE.\n\n"
                "To fix this, install Blender (free) from:\n"
                "https://www.blender.org/download/\n\n"
                "After installing, click Auto-detect or Browse to set the path.")

    def _check_blender_on_startup(self):
        """On first launch, auto-detect Blender. Prompt if missing."""
        if self.blender_path_var.get():
            self._update_blender_status()
            return

        found = find_blender()
        if found:
            self.blender_path_var.set(str(found))
            self._update_blender_status()
            self._save_settings()
            self._log(f"Blender auto-detected: {found}")
        else:
            self._update_blender_status()
            self._log(
                "Blender not found. FBX meshes will be copied without "
                "transform baking. Install Blender from "
                "https://www.blender.org/download/ for proper mesh pivots.")

    # ---------------------------------------------------------------

    def _browse_source(self):
        directory = filedialog.askdirectory(title="Select Unity Assets Folder")
        if directory:
            self.source_path_var.set(directory)
            self._log(f"Source: {directory}")
            self._save_settings()

    def _browse_output(self):
        directory = filedialog.askdirectory(title="Select O3DE Output Folder")
        if directory:
            self.output_path_var.set(directory)
            self._log(f"Output: {directory}")
            self._save_settings()
    
    def _log(self, message: str):
        self.status_text.config(state='normal')
        self.status_text.insert(tk.END, f"{message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state='disabled')
        self.root.update_idletasks()
    
    def _process_assets(self):
        source_path = self.source_path_var.get()
        output_path = self.output_path_var.get()
        
        if not source_path or not output_path:
            messagebox.showerror("Error", "Please select both source and output folders")
            return
        
        if not os.path.exists(source_path):
            messagebox.showerror("Error", f"Source folder not found: {source_path}")
            return
        
        self.process_btn.config(state='disabled')
        
        thread = threading.Thread(target=self._do_processing, args=(source_path, output_path))
        thread.daemon = True
        thread.start()
    
    def _do_processing(self, source_path: str, output_path: str):
        try:
            blender = validate_blender(self.blender_path_var.get())
            processor = IntegratedAssetProcessor(
                Path(source_path),
                Path(output_path),
                log_callback=self._log,
                blender_path=blender,
            )
            
            self._log("\n" + "="*60)
            self._log("STARTING ASSET PROCESSING")
            self._log("="*60)
            
            # Find all prefab files
            prefab_files = list(Path(source_path).rglob('*.prefab'))
            self._log(f"\nFound {len(prefab_files)} Unity prefabs to process")
            
            success_count = 0
            for i, prefab_file in enumerate(prefab_files, 1):
                self._log(f"\n[{i}/{len(prefab_files)}] {prefab_file.name}")
                if processor.process_prefab(prefab_file):
                    success_count += 1
            
            self._log("\n" + "="*60)
            self._log("PROCESSING COMPLETE!")
            self._log("="*60)
            self._log(f"Prefabs processed: {success_count}/{len(prefab_files)}")
            self._log(f"Materials created: {len(processor.processed_materials)}")
            self._log(f"Textures copied: {len(processor.processed_textures)}")
            mesh_verb = "baked" if blender else "copied"
            self._log(f"Meshes {mesh_verb}: {len(processor.processed_meshes)}")
            self._log(f"Colliders created: {processor.total_colliders}")
            self._log(f"Rigid bodies created: {processor.total_rigidbodies}")
            self._log(f"\nOutput location: {output_path}")
            self._log("="*60)

            self.root.after(0, lambda: messagebox.showinfo(
                "Success",
                f"Processing complete!\n\n"
                f"Prefabs: {success_count}/{len(prefab_files)}\n"
                f"Materials: {len(processor.processed_materials)}\n"
                f"Textures: {len(processor.processed_textures)}\n"
                f"Meshes: {len(processor.processed_meshes)}\n"
                f"Colliders: {processor.total_colliders}\n"
                f"Rigid bodies: {processor.total_rigidbodies}"
            ))
        
        except Exception as e:
            error_msg = f"Processing failed: {str(e)}"
            self._log(f"\nERROR: {error_msg}")
            import traceback
            self._log(traceback.format_exc())
            self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        finally:
            self.root.after(0, lambda: self.process_btn.config(state='normal'))


def main():
    root = tk.Tk()
    app = IntegratedProcessorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()