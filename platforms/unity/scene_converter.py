#!/usr/bin/env python3
"""
=============================================================================
UNITY SCENE CONVERTER  (platforms.unity.scene_converter)
=============================================================================

Stage-2 worker: converts a Unity ``.unity`` scene into an O3DE level
prefab, with prefab-reference resolution against an O3DE prefab search
index (``PrefabDatabase``).

Imported by ``main_app.py``'s SceneConverterTab. Pure worker — no UI.

Uses the canonical Unity source-data dataclasses from
``platforms.unity.types`` (``Transform``, ``GameObject``). The previous
local copies have been deleted; this module is the only Stage-2 home.

Pass-2 I.4 will route the scene parser through
``platforms.unity.prefab.parse_unity_scene`` so the local
``parse_unity_scene`` + ``_parse_*`` private parsers can be deleted
and the duplicate-parser path collapsed.
"""

import yaml
import json
import os
import re
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, Set

from platforms.unity.components import load_component_processors, build_dispatch_table
from platforms.unity.components.base import ProcessingContext
from integrated_asset_processor import CoverageTracker
from platforms.unity.types import Transform, GameObject


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

    def __init__(self, prefab_db: PrefabDatabase, log_callback=None, *,
                 entity_maps_by_stem: Optional[Dict[str, Dict]] = None,
                 asset_index: Optional[Dict] = None):
        """
        `entity_maps_by_stem` and `asset_index` are sourced from the
        project file's `outputs.asset_processor` section by the tab
        worker. They replace the old sidecar files
        (`<output>/.ImporterData/<stem>.entitymap.json` and
        `<output>/.ImporterData/asset_index.json`). Both default to {}
        for callers that don't have project state available (e.g.
        ad-hoc scripts).
        """
        self.prefab_db = prefab_db
        self.log = log_callback or print
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

        # Component processor pipeline — auto-discovered from components/
        self.component_processors = load_component_processors()
        self.component_dispatch   = build_dispatch_table(self.component_processors)

        # Component processing stats — accumulated by processors via ctx.stats
        self.stats: Dict[str, int] = {}

        # Collected component blocks from the scene (anchor -> {type, data})
        self.components_data: Dict[str, Dict] = {}

        # =====================================================================
        # Coverage tracker — populated incrementally; reported via to_coverage()
        # =====================================================================
        self.coverage = CoverageTracker()

        # Project-supplied lookups (formerly sidecar reads). Keyed by the
        # output prefab stem (e.g. "Foo") so the lookup matches a Stage 2
        # prefab reference like `<output>/Prefabs/Foo.prefab`.
        self._entity_maps_by_stem: Dict[str, Dict] = dict(entity_maps_by_stem or {})
        # Asset index shape: {materials: {guid: hint}, meshes: {guid: stem},
        # prefabs: {guid: source_path}}.
        self._asset_index: Dict = dict(asset_index or {})
    
    def parse_unity_scene(self, scene_path: str) -> None:
        """Parse Unity scene file"""
        self.game_objects.clear()
        self.transforms.clear()
        self.transform_to_gameobject.clear()
        self.prefab_references.clear()
        self.missing_prefabs.clear()
        self.prefab_instances.clear()
        self.components_data.clear()
        
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
                else:
                    # Collect component blocks for the processor pipeline,
                    # and record every top-level key into coverage so the
                    # end-of-run report shows handled + unhandled types.
                    handled = False
                    for known_type in self.component_dispatch:
                        if known_type in doc:
                            self.components_data[anchor] = {
                                'type': known_type,
                                'data': doc[known_type],
                            }
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
        
        self._build_hierarchy()
        self._dispatch_component_processors()
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
        """
        Parse PrefabInstance data — capture transform overrides for the existing
        prefab_instances pipeline, AND capture the full m_Modifications array +
        sibling override fields (added/removed components, added GameObjects)
        so _create_prefab_instance can emit non-transform patches.
        """
        source_prefab = prefab_data.get('m_SourcePrefab', {})
        prefab_guid   = source_prefab.get('guid', '')
        if not prefab_guid:
            return

        modification          = prefab_data.get('m_Modification', {}) or {}
        modifications         = modification.get('m_Modifications', []) or []
        added_components      = modification.get('m_AddedComponents', []) or []
        removed_components    = modification.get('m_RemovedComponents', []) or []
        added_gameobjects     = modification.get('m_AddedGameObjects', []) or []

        instance_data: Dict[str, Any] = {
            'guid':              prefab_guid,
            'name':              None,
            'position':          (0, 0, 0),
            'rotation':          (0, 0, 0, 1),
            'scale':             (1, 1, 1),
            'parent_fileID':     None,
            'modifications':     list(modifications),
            'added_components':  list(added_components),
            'removed_components': list(removed_components),
            'added_gameobjects': list(added_gameobjects),
        }

        # Parent
        transform_parent = modification.get('m_TransformParent', {}) or {}
        parent_id = str(transform_parent.get('fileID', '0'))
        if parent_id != '0':
            instance_data['parent_fileID'] = parent_id

        # Project transform modifications onto position/rotation/scale.
        pos        = [0, 0, 0]
        rot        = [0, 0, 0, 1]
        scale_vals = [1, 1, 1]
        AXIS = {'x': 0, 'y': 1, 'z': 2, 'w': 3}

        for mod in modifications:
            property_path = (mod.get('propertyPath') or '').strip()
            value         = mod.get('value')
            if property_path == 'm_Name':
                instance_data['name'] = value
            elif property_path.startswith('m_LocalPosition.'):
                a = property_path.rsplit('.', 1)[-1]
                if a in AXIS and AXIS[a] < 3 and value is not None:
                    pos[AXIS[a]] = float(value)
            elif property_path.startswith('m_LocalRotation.'):
                a = property_path.rsplit('.', 1)[-1]
                if a in AXIS and value is not None:
                    rot[AXIS[a]] = float(value)
            elif property_path.startswith('m_LocalScale.'):
                a = property_path.rsplit('.', 1)[-1]
                if a in AXIS and AXIS[a] < 3 and value is not None:
                    scale_vals[AXIS[a]] = float(value)

        instance_data['position'] = tuple(pos)
        instance_data['rotation'] = tuple(rot)
        instance_data['scale']    = tuple(scale_vals)

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
    
    def _dispatch_component_processors(self) -> None:
        """Dispatch collected component blocks to processor parse() methods."""
        for comp_info in self.components_data.values():
            comp_type = comp_info['type']
            comp_data = comp_info['data']

            go_ref = comp_data.get('m_GameObject', {})
            go_id  = str(go_ref.get('fileID', ''))

            if go_id not in self.game_objects:
                continue

            go = self.game_objects[go_id]
            processor = self.component_dispatch.get(comp_type)
            if processor:
                processor.parse(comp_type, comp_data, go, self.log)

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
        """Convert parsed PrefabInstance data into GameObjects with prefab references."""
        for instance in self.prefab_instances:
            file_id = f"prefab_instance_{self.entity_counter}"
            self.entity_counter += 1

            transform = Transform(
                position=instance['position'],
                rotation=instance['rotation'],
                scale=instance['scale'],
            )

            name = instance['name'] if instance['name'] else "PrefabInstance"

            go = GameObject(
                file_id=file_id,
                name=name,
                transform=transform,
                is_prefab_instance=True,
                prefab_source_guid=instance['guid'],
                prefab_name=name,
            )
            # Carry the full override payload so _create_prefab_instance can emit
            # non-transform JSON patches and record unhandled paths into coverage.
            go.prefab_modifications      = instance.get('modifications', []) or []
            go.prefab_added_components   = instance.get('added_components', []) or []
            go.prefab_removed_components = instance.get('removed_components', []) or []
            go.prefab_added_gameobjects  = instance.get('added_gameobjects', []) or []

            if instance['parent_fileID']:
                parent_go_id = self.transform_to_gameobject.get(instance['parent_fileID'])
                if parent_go_id:
                    go.parent_id = parent_go_id
                    if parent_go_id in self.game_objects:
                        self.game_objects[parent_go_id].children_ids.append(file_id)

            self.game_objects[file_id] = go

            prefab_path = self.prefab_db.find_prefab_by_guid(instance['guid'])
            if not prefab_path:
                prefab_path = self.prefab_db.find_prefab_by_name(name)

            if prefab_path:
                self.prefab_references[file_id] = prefab_path
            else:
                self.missing_prefabs.add(name)
                self.coverage.record_missing_prefab(instance['guid'])
    
    def convert_to_o3de_coordinates(self, unity_transform: Transform) -> Tuple[Transform, bool]:
        """Delegate to the canonical O3DE-target coordinate converter."""
        from targets.o3de.prefab_writer import convert_to_o3de_coordinates
        return convert_to_o3de_coordinates(unity_transform)
    
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
        """Emit a prefab Instance entry with JSON-patch overrides.

        Same tiered scheme as Stage 1's nested-instance emitter:
          Tier 1  Transform — translate, rotate, scale on the ContainerEntity
          Tier 2  m_IsActive — logged to coverage (schema TBD)
          Tier 3  m_Materials.Array.data[N] — patch the assetHint in the
                  target entity's EditorMaterialComponent materialsByLabel
                  entry. Label key = FBX-internal material name at slot N
                  (read from the source prefab's sidecar
                  `material_slot_labels`).
        Unhandled propertyPaths are recorded into self.coverage.
        """
        source_path = self._convert_to_assets_path(prefab_path)
        o3de_transform, _ = self.convert_to_o3de_coordinates(go.transform)
        euler             = self._quaternion_to_euler(o3de_transform.rotation)

        patches: List[Dict] = [
            {
                "op":    "replace",
                "path":  "/ContainerEntity/Components/TransformComponent/Parent Entity",
                "value": f"../{parent_entity_id}",
            }
        ]

        # ---- Tier 1: transform overrides on the ContainerEntity ----
        if any(abs(v) > 0.0001 for v in o3de_transform.position):
            for i, axis_val in enumerate(o3de_transform.position):
                patches.append({
                    "op":   "replace",
                    "path": f"/ContainerEntity/Components/TransformComponent/Transform Data/Translate/{i}",
                    "value": axis_val,
                })

        if any(abs(v) > 0.0001 for v in euler):
            for i, axis_val in enumerate(euler):
                patches.append({
                    "op":   "replace",
                    "path": f"/ContainerEntity/Components/TransformComponent/Transform Data/Rotate/{i}",
                    "value": axis_val,
                })

        sx, sy, sz = o3de_transform.scale
        if abs(sx - 1.0) > 0.0001 and abs(sx - sy) < 0.0001 and abs(sy - sz) < 0.0001:
            patches.append({
                "op":   "replace",
                "path": "/ContainerEntity/Components/TransformComponent/Transform Data/Scale",
                "value": sx,
            })
        elif (abs(sx - 1.0) > 0.0001 or abs(sy - 1.0) > 0.0001 or abs(sz - 1.0) > 0.0001):
            self.coverage.warn(
                f"Non-uniform scale override on scene prefab instance '{go.name}' "
                f"({sx}, {sy}, {sz}) not emitted — needs EditorNonUniformScaleComponent."
            )

        # ---- Tier 2 + 3: walk modifications by propertyPath ----
        sidecar = self._load_entity_map_sidecar(prefab_path)
        entity_aliases       = (sidecar or {}).get("entity_aliases", {})
        material_slot_labels = (sidecar or {}).get("material_slot_labels", {})

        if go.prefab_modifications and not sidecar:
            self.coverage.warn(
                f"No entity-map sidecar for prefab '{prefab_path.name}' — "
                f"non-transform overrides on scene instance '{go.name}' cannot be targeted."
            )

        material_overrides: Dict[str, Dict[int, str]] = {}

        for mod in go.prefab_modifications:
            prop_path = (mod.get('propertyPath') or '').strip()
            value     = mod.get('value', None)
            objref    = mod.get('objectReference') or {}
            target    = mod.get('target') or {}
            target_id = str(target.get('fileID', ''))

            if prop_path == 'm_Name' or prop_path.startswith(
                ('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.')
            ):
                self.coverage.record_modification(prop_path, handled=True, example_value=value)
                continue

            if prop_path == 'm_IsActive':
                self.coverage.record_modification(prop_path, handled=False, example_value=value)
                self.coverage.warn(
                    f"m_IsActive override on scene instance '{go.name}' (value={value}) "
                    f"not emitted — O3DE disabled-entity patch path needs confirmation."
                )
                continue

            m = re.match(r'^m_Materials\.Array\.data\[(\d+)\]$', prop_path)
            if m:
                slot_idx = int(m.group(1))
                new_guid = objref.get('guid', '') if isinstance(objref, dict) else ''
                if not new_guid:
                    self.coverage.record_modification(prop_path, handled=False,
                                                     example_value="<no guid>")
                    continue
                slot_map = material_overrides.setdefault(target_id, {})
                slot_map[slot_idx] = new_guid
                continue

            self.coverage.record_modification(
                prop_path, handled=False,
                example_value=value if value not in (None, '') else objref,
            )

        # Emit material slot patches.
        asset_index = self._get_asset_index(prefab_path)
        for target_id, slot_map in material_overrides.items():
            entity_alias = entity_aliases.get(target_id)
            if not entity_alias:
                self.coverage.warn(
                    f"Material override on scene instance '{go.name}' targets "
                    f"fileID={target_id} not in source's entity map — skipped."
                )
                for slot_idx, mat_guid in slot_map.items():
                    self.coverage.record_modification(
                        f'm_Materials.Array.data[{slot_idx}]',
                        handled=False, example_value=mat_guid,
                    )
                continue

            # FBX-internal material names per slot index for this target,
            # recorded by the source prefab's converter run. Only valid keys
            # for the base prefab's materialsByLabel.
            slot_labels = material_slot_labels.get(target_id, []) or []

            for slot_idx, mat_guid in slot_map.items():
                asset_hint = (asset_index or {}).get('materials', {}).get(mat_guid)
                if not asset_hint:
                    self.coverage.record_missing_material(mat_guid)
                    self.coverage.record_modification(
                        f'm_Materials.Array.data[{slot_idx}]',
                        handled=False, example_value=mat_guid,
                    )
                    continue

                # Label = FBX-internal material name at this ordinal position
                # (the only key that matches the base prefab's
                # materialsByLabel entry at runtime).
                label = (slot_labels[slot_idx]
                         if slot_idx < len(slot_labels) else '')

                if not label:
                    self.coverage.warn(
                        f"Material override on scene instance '{go.name}' "
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

        # Sibling-field accounting.
        for _ in go.prefab_added_components:    self.coverage.record_added_component()
        for _ in go.prefab_removed_components:  self.coverage.record_removed_component()
        for _ in go.prefab_added_gameobjects:   self.coverage.record_added_gameobject()
        if (go.prefab_added_components or go.prefab_removed_components
                or go.prefab_added_gameobjects):
            self.coverage.warn(
                f"Scene instance '{go.name}' has added/removed components or "
                f"added GameObjects that are not yet propagated to O3DE patches."
            )

        return {
            "Source":  source_path,
            "Patches": patches,
        }

    # =========================================================================
    # SIDECAR + ASSET INDEX LOOKUP
    # =========================================================================

    def _load_entity_map_sidecar(self, prefab_path: Path) -> Optional[Dict]:
        """Return the entity-map record for the given output prefab path.

        Reads from `self._entity_maps_by_stem` which the tab worker
        populates from `project.outputs.asset_processor.prefabs` at
        construction time. Replaces the old
        `<output>/.ImporterData/<stem>.entitymap.json` sidecar read.
        Returns None when no record exists for that stem (i.e. Stage 1
        hasn't processed the prefab in the active project)."""
        return self._entity_maps_by_stem.get(prefab_path.stem)

    def _get_asset_index(self, hint_path: Path) -> Dict:
        """Return the project's asset index (materials / meshes / prefabs
        sub-dicts). Populated by the tab worker from
        `project.outputs.asset_processor` at construction time. Replaces
        the old `<output>/.ImporterData/asset_index.json` read.
        `hint_path` retained for API compatibility; ignored."""
        return self._asset_index

    # =========================================================================
    # FINALIZE — write the scene-side coverage report
    # =========================================================================

    def finalize(self, output_dir: Path = None) -> None:
        """End-of-run hook. No disk writes — the tab worker reads
        `to_coverage()` and persists into the project file's
        `outputs.scene_converter.coverage`. `output_dir` accepted for
        backwards-API compatibility with callers that still pass it; the
        parameter is ignored."""
        cov = self.coverage.to_dict()
        unh_comp = len(cov.get('unhandled_component_types', {}))
        unh_over = len(cov.get('unhandled_override_paths', {}))
        self.log(f"  ✓ Coverage recorded: "
                 f"{unh_comp} unhandled component type(s), "
                 f"{unh_over} unhandled override path(s), "
                 f"{len(cov.get('warnings', []))} warning(s)")

    def to_coverage(self) -> dict:
        """Return the scene's coverage report dict. Stored by the tab
        worker into `project.outputs.scene_converter.coverage`."""
        return self.coverage.to_dict()
    
    def _generate_component_id(self) -> int:
        """Generate unique component ID"""
        return random.randint(1000000000000000, 9999999999999999)

    def _generate_entity_id(self) -> str:
        """Generate unique entity ID"""
        self.entity_counter += 1
        return f"Entity_[{self.entity_counter}]"

    def _make_bare_entity(self, entity_id: str, name: str, parent_entity_id: str) -> Dict:
        """Create a minimal O3DE entity (used by collider processors for overflow child entities)."""
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

        # ---------------------------------------------------------------
        # Component Processors — emit phase (physics, mesh, material, ...)
        # ---------------------------------------------------------------
        ctx = ProcessingContext(
            material_mapping      = {},
            mesh_mapping          = {},
            fbx_material_labels   = {},   # scene converter has no FBX access; material emit gracefully degrades
            entities_dict         = entities_dict,
            entity_id_map         = entity_id_map,
            generate_component_id = self._generate_component_id,
            generate_entity_id    = self._generate_entity_id,
            make_bare_entity      = self._make_bare_entity,
            log                   = self.log,
            stats                 = self.stats,
        )
        collider_child_ids: List[str] = []
        for processor in self.component_processors:
            child_ids = processor.emit(go, entity, ctx)
            collider_child_ids.extend(child_ids)

        # ---------------------------------------------------------------
        # Child entities: GO children + any collider overflow sub-entities
        # ---------------------------------------------------------------
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

        child_order.extend(collider_child_ids)

        if child_order:
            entity["Components"]["EditorEntitySortComponent"] = {
                "$type": "EditorEntitySortComponent",
                "Id": self._generate_component_id(),
                "Child Entity Order": child_order
            }

        entities_dict[entity_id] = entity
        return entity_id

