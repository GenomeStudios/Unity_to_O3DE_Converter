#!/usr/bin/env python3
"""
Unity to O3DE Scene Converter - GUI Edition

Converts Unity scenes to O3DE levels with prefab reference support.
Searches provided directories for existing O3DE prefabs and references them.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import yaml
import json
import os
import re
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
import threading
import queue
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
class GameObject:
    """Unity GameObject representation"""
    file_id: str
    name: str
    transform: Transform
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    is_prefab_instance: bool = False
    prefab_source_guid: Optional[str] = None
    prefab_name: Optional[str] = None


class PrefabDatabase:
    """Manages index of available O3DE prefabs"""
    
    def __init__(self):
        self.prefab_paths: Dict[str, Path] = {}  # name -> full path
        self.prefab_guids: Dict[str, Path] = {}  # Unity GUID -> O3DE path
        self.search_dirs: List[Path] = []
        self.guid_to_name: Dict[str, str] = {}  # Unity GUID -> prefab name
    
    def add_search_directory(self, directory: str) -> int:
        """Add directory to search for prefabs, return count found"""
        dir_path = Path(directory)
        if not dir_path.exists():
            return 0
        
        self.search_dirs.append(dir_path)
        count = 0
        
        # Find all .prefab files
        for prefab_file in dir_path.rglob('*.prefab'):
            # Use stem (filename without extension) as key
            prefab_name = prefab_file.stem
            self.prefab_paths[prefab_name] = prefab_file
            
            # Try to find corresponding .meta file for GUID
            meta_file = Path(str(prefab_file) + '.meta')
            if meta_file.exists():
                guid = self._extract_guid_from_meta(meta_file)
                if guid:
                    self.prefab_guids[guid] = prefab_file
                    self.guid_to_name[guid] = prefab_name
            
            count += 1
        
        return count
    
    def _extract_guid_from_meta(self, meta_path: Path) -> Optional[str]:
        """Extract GUID from Unity .meta file"""
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                content = f.read()
                match = re.search(r'guid:\s*([a-f0-9]+)', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return None
    
    def add_guid_mapping(self, unity_guid: str, prefab_name: str) -> None:
        """Manually add Unity GUID -> prefab name mapping"""
        if prefab_name in self.prefab_paths:
            self.prefab_guids[unity_guid] = self.prefab_paths[prefab_name]
            self.guid_to_name[unity_guid] = prefab_name
    
    def find_prefab_by_name(self, name: str) -> Optional[Path]:
        """Find O3DE prefab by GameObject name (strips duplicate numbers)"""
        # Try exact match first
        if name in self.prefab_paths:
            return self.prefab_paths[name]
        
        # Try stripping duplicate suffix like " (1)", " (2)", etc.
        clean_name = re.sub(r'\s*\(\d+\)$', '', name)
        if clean_name in self.prefab_paths:
            return self.prefab_paths[clean_name]
        
        # Try stripping any suffix after the last space
        base_name = name.rsplit(' ', 1)[0] if ' ' in name else name
        if base_name in self.prefab_paths:
            return self.prefab_paths[base_name]
        
        return None
    
    def find_prefab_by_guid(self, guid: str) -> Optional[Path]:
        """Find O3DE prefab by Unity GUID"""
        return self.prefab_guids.get(guid)
    
    def get_relative_path(self, prefab_path: Path, base_path: Path) -> str:
        """Get relative path from base to prefab"""
        try:
            return str(prefab_path.relative_to(base_path))
        except ValueError:
            # If not relative, return absolute path
            return str(prefab_path)


class UnitySceneConverter:
    """Converts Unity scenes to O3DE levels with prefab support"""
    
    def __init__(self, prefab_db: PrefabDatabase):
        self.prefab_db = prefab_db
        self.game_objects: Dict[str, GameObject] = {}
        self.transforms: Dict[str, Transform] = {}
        self.transform_to_gameobject: Dict[str, str] = {}
        self.entity_counter = 1000000
        self.instance_counter = 1000000
        
        # Track which GameObjects will use prefab references
        self.prefab_references: Dict[str, Path] = {}  # go_id -> prefab_path
        self.missing_prefabs: Set[str] = set()  # Names of prefabs not found
        
        # Track prefab instances from scene
        self.prefab_instances: List[Dict] = []  # List of prefab instance data
    
    def parse_unity_scene(self, scene_path: str) -> None:
        """Parse Unity scene file"""
        self.game_objects.clear()
        self.transforms.clear()
        self.transform_to_gameobject.clear()
        self.prefab_references.clear()
        self.missing_prefabs.clear()
        self.prefab_instances.clear()
        
        with open(scene_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # First pass: Extract PrefabInstance blocks to get GUID mappings
        prefab_instance_guids = {}  # fileID -> GUID
        prefab_instance_pattern = r'--- !u!1001 &(\d+)\nPrefabInstance:.*?guid:\s*([a-f0-9]+)'
        for match in re.finditer(prefab_instance_pattern, content, re.DOTALL):
            instance_id = match.group(1)
            prefab_guid = match.group(2)
            prefab_instance_guids[instance_id] = prefab_guid
        
        # Parse documents with anchors
        doc_pattern = r'---\s+!u!\d+\s+&(\d+)\n(.*?)(?=---\s+!u!|\Z)'
        matches = re.findall(doc_pattern, content, re.DOTALL)
        
        for anchor, doc_content in matches:
            clean_content = re.sub(r'!u!\d+', '', doc_content)
            
            try:
                doc = yaml.safe_load(clean_content)
                if not doc:
                    continue
                
                if 'Transform' in doc:
                    self._parse_transform(doc['Transform'], anchor, prefab_instance_guids)
                elif 'GameObject' in doc:
                    self._parse_game_object(doc['GameObject'], anchor, prefab_instance_guids)
                elif 'PrefabInstance' in doc:
                    self._parse_prefab_instance(doc['PrefabInstance'])
            
            except yaml.YAMLError:
                continue
        
        self._build_hierarchy()
        self._resolve_prefab_references()
        self._process_prefab_instances()
    
    def _parse_transform(self, transform_data: Dict, transform_anchor: str, prefab_instance_guids: Dict) -> None:
        """Parse Transform component"""
        go_ref = transform_data.get('m_GameObject', {})
        go_file_id = str(go_ref.get('fileID', ''))
        
        if not go_file_id or go_file_id == '0':
            return
        
        self.transform_to_gameobject[transform_anchor] = go_file_id
        
        local_pos = transform_data.get('m_LocalPosition', {'x': 0, 'y': 0, 'z': 0})
        local_rot = transform_data.get('m_LocalRotation', {'x': 0, 'y': 0, 'z': 0, 'w': 1})
        local_scale = transform_data.get('m_LocalScale', {'x': 1, 'y': 1, 'z': 1})
        
        position = (float(local_pos.get('x', 0)), float(local_pos.get('y', 0)), float(local_pos.get('z', 0)))
        rotation = (float(local_rot.get('x', 0)), float(local_rot.get('y', 0)), 
                   float(local_rot.get('z', 0)), float(local_rot.get('w', 1)))
        scale = (float(local_scale.get('x', 1)), float(local_scale.get('y', 1)), float(local_scale.get('z', 1)))
        
        transform = Transform(position, rotation, scale)
        
        if go_file_id not in self.game_objects:
            self.game_objects[go_file_id] = GameObject(
                file_id=go_file_id,
                name="",
                transform=transform
            )
        else:
            self.game_objects[go_file_id].transform = transform
        
        parent = transform_data.get('m_Father', {})
        parent_transform_id = str(parent.get('fileID', '0'))
        if parent_transform_id != '0':
            self.game_objects[go_file_id].parent_id = parent_transform_id
        
        children = transform_data.get('m_Children', [])
        for child in children:
            if child and child.get('fileID'):
                child_transform_id = str(child['fileID'])
                self.game_objects[go_file_id].children_ids.append(child_transform_id)
    
    def _parse_game_object(self, go_data: Dict, go_anchor: str, prefab_instance_guids: Dict) -> None:
        """Parse GameObject"""
        file_id = go_anchor
        name = go_data.get('m_Name', 'GameObject')
        
        # Check if it's a prefab instance
        prefab_parent = go_data.get('m_CorrespondingSourceObject', {})
        is_prefab = prefab_parent and prefab_parent.get('fileID')
        
        # Try to get prefab GUID from multiple sources
        prefab_guid = None
        if is_prefab:
            # Method 1: Direct from m_PrefabAsset (older Unity scenes)
            prefab_asset = go_data.get('m_PrefabAsset', {})
            prefab_guid = prefab_asset.get('guid', '')
            
            # Method 2: From m_PrefabInstance reference (newer Unity scenes)
            if not prefab_guid:
                prefab_instance_ref = go_data.get('m_PrefabInstance', {})
                instance_id = str(prefab_instance_ref.get('fileID', ''))
                if instance_id and instance_id in prefab_instance_guids:
                    prefab_guid = prefab_instance_guids[instance_id]
            
            # Method 3: From m_CorrespondingSourceObject GUID
            if not prefab_guid and prefab_parent.get('guid'):
                prefab_guid = prefab_parent.get('guid', '')
        
        components = go_data.get('m_Component', [])
        transform_id = None
        for comp in components:
            comp_ref = comp.get('component', {})
            comp_file_id = str(comp_ref.get('fileID', ''))
            if comp_file_id:
                transform_id = comp_file_id
                break
        
        if transform_id and transform_id in self.transform_to_gameobject:
            old_go_id = self.transform_to_gameobject[transform_id]
            if old_go_id in self.game_objects:
                self.game_objects[file_id] = self.game_objects.pop(old_go_id)
                self.game_objects[file_id].file_id = file_id
                self.game_objects[file_id].name = name
                self.game_objects[file_id].is_prefab_instance = is_prefab
                self.game_objects[file_id].prefab_source_guid = prefab_guid if is_prefab else None
                self.game_objects[file_id].prefab_name = name if is_prefab else None
                if old_go_id in self.transforms:
                    self.transforms[file_id] = self.transforms.pop(old_go_id)
            self.transform_to_gameobject[transform_id] = file_id
        
        if file_id in self.game_objects:
            self.game_objects[file_id].name = name
            self.game_objects[file_id].is_prefab_instance = is_prefab
            self.game_objects[file_id].prefab_source_guid = prefab_guid if is_prefab else None
            self.game_objects[file_id].prefab_name = name if is_prefab else None
        else:
            transform = self.transforms.get(file_id, Transform())
            self.game_objects[file_id] = GameObject(
                file_id=file_id,
                name=name,
                transform=transform,
                is_prefab_instance=is_prefab,
                prefab_source_guid=prefab_guid if is_prefab else None,
                prefab_name=name if is_prefab else None
            )
    
    def _parse_prefab_instance(self, prefab_data: Dict) -> None:
        """Parse PrefabInstance data to create prefab reference entities"""
        # Extract GUID
        source_prefab = prefab_data.get('m_SourcePrefab', {})
        prefab_guid = source_prefab.get('guid', '')
        
        if not prefab_guid:
            return
        
        # Extract modifications
        modification = prefab_data.get('m_Modification', {})
        modifications = modification.get('m_Modifications', [])
        
        # Parse transform and name from modifications
        instance_data = {
            'guid': prefab_guid,
            'name': None,
            'position': (0, 0, 0),
            'rotation': (0, 0, 0, 1),
            'scale': (1, 1, 1),
            'parent_fileID': None
        }
        
        # Get parent
        transform_parent = modification.get('m_TransformParent', {})
        parent_id = str(transform_parent.get('fileID', '0'))
        if parent_id != '0':
            instance_data['parent_fileID'] = parent_id
        
        # Parse modifications
        pos = [0, 0, 0]
        rot = [0, 0, 0, 1]
        scale_vals = [1, 1, 1]
        
        for mod in modifications:
            property_path = mod.get('propertyPath', '')
            value = mod.get('value')
            
            if property_path == 'm_Name':
                instance_data['name'] = value
            elif property_path == 'm_LocalPosition.x':
                pos[0] = float(value) if value is not None else 0
            elif property_path == 'm_LocalPosition.y':
                pos[1] = float(value) if value is not None else 0
            elif property_path == 'm_LocalPosition.z':
                pos[2] = float(value) if value is not None else 0
            elif property_path == 'm_LocalRotation.x':
                rot[0] = float(value) if value is not None else 0
            elif property_path == 'm_LocalRotation.y':
                rot[1] = float(value) if value is not None else 0
            elif property_path == 'm_LocalRotation.z':
                rot[2] = float(value) if value is not None else 0
            elif property_path == 'm_LocalRotation.w':
                rot[3] = float(value) if value is not None else 1
            elif property_path == 'm_LocalScale.x':
                scale_vals[0] = float(value) if value is not None else 1
            elif property_path == 'm_LocalScale.y':
                scale_vals[1] = float(value) if value is not None else 1
            elif property_path == 'm_LocalScale.z':
                scale_vals[2] = float(value) if value is not None else 1
        
        instance_data['position'] = tuple(pos)
        instance_data['rotation'] = tuple(rot)
        instance_data['scale'] = tuple(scale_vals)
        
        # Add to prefab instances list
        self.prefab_instances.append(instance_data)
    
    def _build_hierarchy(self) -> None:
        """Build parent-child hierarchy"""
        for go_id, go in list(self.game_objects.items()):
            if go.parent_id and go.parent_id in self.transform_to_gameobject:
                go.parent_id = self.transform_to_gameobject[go.parent_id]
            elif go.parent_id == '0':
                go.parent_id = None
            
            resolved_children = []
            for child_transform_id in go.children_ids:
                if child_transform_id in self.transform_to_gameobject:
                    resolved_children.append(self.transform_to_gameobject[child_transform_id])
            go.children_ids = resolved_children
        
        for file_id, go in self.game_objects.items():
            for child_id in go.children_ids:
                if child_id in self.game_objects:
                    self.game_objects[child_id].parent_id = file_id
    
    def _resolve_prefab_references(self) -> None:
        """Find existing O3DE prefabs for Unity prefab instances"""
        for go_id, go in self.game_objects.items():
            if not go.is_prefab_instance:
                continue
            
            # Try to find matching O3DE prefab
            prefab_path = None
            
            # First try by GUID if available
            if go.prefab_source_guid:
                prefab_path = self.prefab_db.find_prefab_by_guid(go.prefab_source_guid)
            
            # Then try by name
            if not prefab_path and go.prefab_name:
                prefab_path = self.prefab_db.find_prefab_by_name(go.prefab_name)
            
            if prefab_path:
                self.prefab_references[go_id] = prefab_path
            else:
                # Track missing prefabs
                prefab_name = go.prefab_name or go.name or "Unknown"
                self.missing_prefabs.add(prefab_name)
    
    def _process_prefab_instances(self) -> None:
        """Convert parsed PrefabInstance data into GameObjects with prefab references"""
        for instance in self.prefab_instances:
            # Create a unique file_id for this instance
            file_id = f"prefab_instance_{self.entity_counter}"
            self.entity_counter += 1
            
            # Create Transform
            transform = Transform(
                position=instance['position'],
                rotation=instance['rotation'],
                scale=instance['scale']
            )
            
            # Determine name
            name = instance['name'] if instance['name'] else "PrefabInstance"
            
            # Create GameObject
            go = GameObject(
                file_id=file_id,
                name=name,
                transform=transform,
                is_prefab_instance=True,
                prefab_source_guid=instance['guid'],
                prefab_name=name
            )
            
            # Set parent if specified
            if instance['parent_fileID']:
                # Parent is a transform ID, need to resolve to GameObject
                parent_go_id = self.transform_to_gameobject.get(instance['parent_fileID'])
                if parent_go_id:
                    go.parent_id = parent_go_id
                    # Add this child to parent's children_ids
                    if parent_go_id in self.game_objects:
                        self.game_objects[parent_go_id].children_ids.append(file_id)
            
            # Add to game_objects
            self.game_objects[file_id] = go
            
            # Try to find matching O3DE prefab
            prefab_path = self.prefab_db.find_prefab_by_guid(instance['guid'])
            if not prefab_path:
                # Try by name as fallback
                prefab_path = self.prefab_db.find_prefab_by_name(name)
            
            if prefab_path:
                self.prefab_references[file_id] = prefab_path
            else:
                self.missing_prefabs.add(name)
    
    def convert_to_o3de_coordinates(self, unity_transform: Transform) -> Tuple[Transform, bool]:
        """Convert Unity transform to O3DE coordinate system"""
        o3de_pos = (
            -unity_transform.position[0],
            unity_transform.position[2],
            unity_transform.position[1]
        )
        
        qx, qy, qz, qw = unity_transform.rotation
        o3de_rot = (-qx, qz, qy, qw)
        
        o3de_scale = (
            unity_transform.scale[0],
            unity_transform.scale[2],
            unity_transform.scale[1]
        )
        
        converted = Transform(o3de_pos, o3de_rot, o3de_scale)
        needs_nonuniform = not converted.is_uniform_scale()
        
        return converted, needs_nonuniform
    
    def create_o3de_level(self, output_path: str, output_base: Path) -> Tuple[int, int, int]:
        """Create O3DE level file in JSON format"""
        level_data = {
            "ContainerEntity": self._create_level_container(),
            "Entities": {},
            "Instances": {}
        }
        
        entity_id_map = {}
        child_order = []
        
        prefab_ref_count = 0
        blank_entity_count = 0
        
        root_objects = [go for go in self.game_objects.values() if go.parent_id is None]
        
        for root_go in root_objects:
            if root_go.file_id in self.prefab_references:
                instance_id = f"Instance_[{self.instance_counter}]"
                self.instance_counter += 1
                
                prefab_path = self.prefab_references[root_go.file_id]
                level_data["Instances"][instance_id] = self._create_prefab_instance(
                    root_go, prefab_path, output_base, "Entity_[1000000]"
                )
                
                child_order.append(f"{instance_id}/ContainerEntity")
                prefab_ref_count += 1
            else:
                entity_id = self._create_entity_recursive(
                    root_go, self.game_objects, level_data["Entities"],
                    level_data["Instances"], entity_id_map, output_base,
                    "Entity_[1000000]"
                )
                child_order.append(entity_id)
                blank_entity_count += 1
        
        if child_order:
            level_data["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"] = child_order
        
        with open(output_path, 'w') as f:
            json.dump(level_data, f, indent=4)
        
        # Count all entities and instances created
        total_entities = len(level_data["Entities"])
        total_instances = len(level_data["Instances"])
        
        return total_entities + total_instances, total_instances, total_entities
    
    def _create_level_container(self) -> Dict:
        """Create ContainerEntity for level"""
        return {
            "Id": "Entity_[1000000]",
            "Name": "Level",
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
                    "Id": self._generate_component_id()
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
    
    def _convert_to_assets_path(self, prefab_path: Path) -> str:
        """Convert absolute prefab path to project-relative format"""
        # Find which search directory contains this prefab
        for search_dir in self.prefab_db.search_dirs:
            try:
                # Make path relative to search directory
                rel_to_search = prefab_path.relative_to(search_dir)
                # Construct path: {search_dir_name}/{relative_path}
                assets_path = f"{search_dir.name}/{rel_to_search}"
                return assets_path.replace('\\', '/')
            except ValueError:
                continue
        
        # Fallback: if not in any search directory, just use filename
        return f"Prefabs/{prefab_path.name}"
    
    def _create_prefab_instance(self, go: GameObject, prefab_path: Path, 
                                output_base: Path, parent_entity_id: str) -> Dict:
        """Create prefab instance with patches"""
        # Convert to Assets-relative path
        source_path = self._convert_to_assets_path(prefab_path)
        
        o3de_transform, _ = self.convert_to_o3de_coordinates(go.transform)
        
        patches = [
            {
                "op": "replace",
                "path": "/ContainerEntity/Components/TransformComponent/Parent Entity",
                "value": f"../{parent_entity_id}"
            }
        ]
        
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
    
    def _generate_component_id(self) -> int:
        """Generate unique component ID"""
        return random.randint(1000000000000000, 9999999999999999)
    
    def _generate_entity_id(self) -> str:
        """Generate unique entity ID"""
        self.entity_counter += 1
        return f"Entity_[{self.entity_counter}]"
    
    def _quaternion_to_euler(self, quaternion: Tuple[float, float, float, float]) -> List[float]:
        """Convert quaternion to Euler angles in degrees"""
        x, y, z, w = quaternion
        
        sinr_cosp = 2 * (w * x + y * z)
        cosr_cosp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sinr_cosp, cosr_cosp)
        
        sinp = 2 * (w * y - z * x)
        if abs(sinp) >= 1:
            pitch = math.copysign(math.pi / 2, sinp)
        else:
            pitch = math.asin(sinp)
        
        siny_cosp = 2 * (w * z + x * y)
        cosy_cosp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(siny_cosp, cosy_cosp)
        
        return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]
    
    def _create_entity_recursive(self, go: GameObject, all_game_objects: Dict,
                                 entities_dict: Dict, instances_dict: Dict,
                                 entity_id_map: Dict, output_base: Path,
                                 parent_entity_id: str) -> str:
        """Recursively create entities or instances"""
        if go.file_id in self.prefab_references:
            instance_id = f"Instance_[{self.instance_counter}]"
            self.instance_counter += 1
            prefab_path = self.prefab_references[go.file_id]
            instances_dict[instance_id] = self._create_prefab_instance(
                go, prefab_path, output_base, parent_entity_id
            )
            return f"{instance_id}/ContainerEntity"
        
        entity_id = self._generate_entity_id()
        entity_id_map[go.file_id] = entity_id
        
        o3de_transform, needs_nonuniform = self.convert_to_o3de_coordinates(go.transform)
        
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
        
        transform_component = {
            "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
            "Id": self._generate_component_id(),
            "Parent Entity": parent_entity_id
        }
        
        euler = self._quaternion_to_euler(o3de_transform.rotation)
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
        
        if go.children_ids:
            child_order = []
            for child_id in go.children_ids:
                if child_id in all_game_objects:
                    child_entity_id = self._create_entity_recursive(
                        all_game_objects[child_id], all_game_objects,
                        entities_dict, instances_dict, entity_id_map,
                        output_base, entity_id
                    )
                    if child_entity_id:
                        child_order.append(child_entity_id)
            
            if child_order:
                entity["Components"]["EditorEntitySortComponent"] = {
                    "$type": "EditorEntitySortComponent",
                    "Id": self._generate_component_id(),
                    "Child Entity Order": child_order
                }
        
        entities_dict[entity_id] = entity
        return entity_id


class SceneConverterGUI:
    """GUI for Unity to O3DE Scene Converter"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Unity to O3DE Scene Converter")
        self.root.geometry("800x700")
        
        self.prefab_db = PrefabDatabase()
        self.converter = UnitySceneConverter(self.prefab_db)
        
        self.prefab_dirs: List[str] = []
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Scene File Selection
        ttk.Label(main_frame, text="Unity Scene File:", font=('', 10, 'bold')).grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        scene_frame = ttk.Frame(main_frame)
        scene_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        self.scene_path_var = tk.StringVar()
        ttk.Entry(scene_frame, textvariable=self.scene_path_var, width=60).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(scene_frame, text="Browse...", command=self._browse_scene).grid(row=0, column=1, padx=(5, 0))
        
        scene_frame.columnconfigure(0, weight=1)
        
        # Output Destination
        ttk.Label(main_frame, text="Output Destination:", font=('', 10, 'bold')).grid(row=2, column=0, sticky=tk.W, pady=(0, 5))
        
        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        
        self.output_path_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.output_path_var, width=60).grid(row=0, column=0, sticky=(tk.W, tk.E))
        ttk.Button(output_frame, text="Browse...", command=self._browse_output).grid(row=0, column=1, padx=(5, 0))
        
        output_frame.columnconfigure(0, weight=1)
        
        # Prefab Directories
        ttk.Label(main_frame, text="O3DE Prefab Asset Directories:", font=('', 10, 'bold')).grid(row=4, column=0, sticky=tk.W, pady=(0, 5))
        
        # Listbox with scrollbar
        listbox_frame = ttk.Frame(main_frame)
        listbox_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.prefab_listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, height=8)
        self.prefab_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.prefab_listbox.yview)
        
        # Buttons for managing prefab directories
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, sticky=tk.W, pady=(0, 15))
        
        ttk.Button(button_frame, text="Add Directory", command=self._add_prefab_directory).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Remove Selected", command=self._remove_prefab_directory).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Clear All", command=self._clear_prefab_directories).pack(side=tk.LEFT)
        
        # Status area
        ttk.Label(main_frame, text="Status:", font=('', 10, 'bold')).grid(row=7, column=0, sticky=tk.W, pady=(0, 5))
        
        self.status_text = scrolledtext.ScrolledText(main_frame, height=10, width=70, state='disabled')
        self.status_text.grid(row=8, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
        
        # Convert button
        convert_frame = ttk.Frame(main_frame)
        convert_frame.grid(row=9, column=0, sticky=(tk.W, tk.E))
        
        self.convert_btn = ttk.Button(convert_frame, text="Convert Scene", command=self._convert_scene, style='Accent.TButton')
        self.convert_btn.pack(side=tk.RIGHT)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(8, weight=1)
        
        self._log("Ready. Add Unity scene file and prefab directories to begin.")
    
    def _browse_scene(self):
        """Browse for Unity scene file"""
        filename = filedialog.askopenfilename(
            title="Select Unity Scene File",
            filetypes=[("Unity Scene", "*.unity"), ("All Files", "*.*")]
        )
        if filename:
            self.scene_path_var.set(filename)
            self._log(f"Selected scene: {Path(filename).name}")
    
    def _browse_output(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(title="Select Output Directory")
        if directory:
            self.output_path_var.set(directory)
            self._log(f"Output directory: {directory}")
    
    def _add_prefab_directory(self):
        """Add prefab directory to search list"""
        directory = filedialog.askdirectory(title="Select O3DE Prefab Directory")
        if directory and directory not in self.prefab_dirs:
            self.prefab_dirs.append(directory)
            count = self.prefab_db.add_search_directory(directory)
            
            display_text = f"{Path(directory).name} ({count} prefabs)"
            self.prefab_listbox.insert(tk.END, display_text)
            self._log(f"Added directory: {directory} - Found {count} prefabs")
    
    def _remove_prefab_directory(self):
        """Remove selected prefab directory"""
        selection = self.prefab_listbox.curselection()
        if selection:
            index = selection[0]
            removed_dir = self.prefab_dirs.pop(index)
            self.prefab_listbox.delete(index)
            self._log(f"Removed directory: {removed_dir}")
            
            # Rebuild prefab database
            self.prefab_db = PrefabDatabase()
            for directory in self.prefab_dirs:
                self.prefab_db.add_search_directory(directory)
            self.converter.prefab_db = self.prefab_db
    
    def _clear_prefab_directories(self):
        """Clear all prefab directories"""
        self.prefab_dirs.clear()
        self.prefab_listbox.delete(0, tk.END)
        self.prefab_db = PrefabDatabase()
        self.converter.prefab_db = self.prefab_db
        self._log("Cleared all prefab directories")
    
    def _log(self, message: str):
        """Add message to status log"""
        self.status_text.config(state='normal')
        self.status_text.insert(tk.END, f"{message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state='disabled')
    
    def _convert_scene(self):
        """Convert Unity scene to O3DE level"""
        scene_path = self.scene_path_var.get()
        output_dir = self.output_path_var.get()
        
        # Validation
        if not scene_path:
            messagebox.showerror("Error", "Please select a Unity scene file")
            return
        
        if not output_dir:
            messagebox.showerror("Error", "Please select an output directory")
            return
        
        if not os.path.exists(scene_path):
            messagebox.showerror("Error", f"Scene file not found: {scene_path}")
            return
        
        # Disable convert button during processing
        self.convert_btn.config(state='disabled')
        
        # Run conversion in thread to keep GUI responsive
        thread = threading.Thread(target=self._do_conversion, args=(scene_path, output_dir))
        thread.daemon = True
        thread.start()
    
    def _do_conversion(self, scene_path: str, output_dir: str):
        """Perform conversion (runs in separate thread)"""
        try:
            self._log("\n" + "="*60)
            self._log("Starting conversion...")
            self._log(f"Scene: {Path(scene_path).name}")
            self._log(f"Output: {output_dir}")
            self._log(f"Prefab directories: {len(self.prefab_dirs)}")
            self._log("="*60)
            
            # Parse scene
            self._log("\nParsing Unity scene...")
            self.converter.parse_unity_scene(scene_path)
            self._log(f"Found {len(self.converter.game_objects)} GameObjects")
            
            # Report prefab status
            prefab_instances = sum(1 for go in self.converter.game_objects.values() if go.is_prefab_instance)
            self._log(f"Prefab instances in scene: {prefab_instances}")
            self._log(f"Prefabs found in directories: {len(self.converter.prefab_references)}")
            
            if self.converter.missing_prefabs:
                self._log(f"\nMissing prefabs ({len(self.converter.missing_prefabs)}):")
                for prefab_name in sorted(self.converter.missing_prefabs):
                    self._log(f"  - {prefab_name}")
            
            # Create output
            scene_name = Path(scene_path).stem
            output_path = os.path.join(output_dir, f"{scene_name}.prefab")
            
            self._log(f"\nGenerating O3DE level: {scene_name}.prefab")
            total, prefab_refs, blanks = self.converter.create_o3de_level(
                output_path, 
                Path(output_dir)
            )
            
            self._log("\n" + "="*60)
            self._log("CONVERSION COMPLETE!")
            self._log("="*60)
            self._log(f"Total entities: {total}")
            self._log(f"Prefab references: {prefab_refs}")
            self._log(f"Blank entities: {blanks}")
            self._log(f"Output: {output_path}")
            self._log("="*60)
            
            # Show success dialog
            self.root.after(0, lambda: messagebox.showinfo(
                "Success", 
                f"Scene converted successfully!\n\n"
                f"Total entities: {total}\n"
                f"Prefab references: {prefab_refs}\n"
                f"Blank entities: {blanks}\n\n"
                f"Output: {output_path}"
            ))
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            self._log(f"\nERROR: {error_msg}")
            self.root.after(0, lambda: messagebox.showerror("Error", error_msg))
        
        finally:
            # Re-enable convert button
            self.root.after(0, lambda: self.convert_btn.config(state='normal'))


def main():
    root = tk.Tk()
    app = SceneConverterGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()