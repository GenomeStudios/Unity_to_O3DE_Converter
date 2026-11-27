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
from platforms.unity.prefab import (
    add_model_instance, component_ranks, in_unity_order, lost_root, root_override_target, targets_root,
)
from platforms.unity.types import Transform, GameObject
from targets.o3de.prefab_writer import UNIFORM_SCALE


# =============================================================================
# STRIPPED TRANSFORMS
# =============================================================================

# A transform of a placed prefab that the scene itself refers to, as the
# parent of something added below the placement. The scene keeps only what
# it is a copy of and which placement it belongs to. The two are spelled
# m_CorrespondingSourceObject and m_PrefabInstance since Unity 2018.3,
# m_PrefabParentObject and m_PrefabInternal before.
STRIPPED_TRANSFORM = re.compile(r'--- !u!4 &(\d+) stripped\nTransform:\n(.*?)(?=--- !u!|\Z)', re.DOTALL)
STRIPPED_SOURCE = re.compile(r'm_(?:CorrespondingSourceObject|PrefabParentObject): \{fileID: (\d+)')
STRIPPED_PLACEMENT = re.compile(r'm_(?:PrefabInstance|PrefabInternal): \{fileID: (\d+)')


def stripped_transforms(scene_text: str) -> Dict[str, Tuple[str, str]]:
    """``{file id of a stripped transform: (file id of the placement it
    belongs to, file id of the transform in the source prefab)}``."""
    found: Dict[str, Tuple[str, str]] = {}
    for anchor, body in STRIPPED_TRANSFORM.findall(scene_text):
        source, placement = STRIPPED_SOURCE.search(body), STRIPPED_PLACEMENT.search(body)
        if source and placement and placement.group(1) != '0':
            found[anchor] = (placement.group(1), source.group(1))
    return found


def prefab_key(converted_prefab: Path) -> str:
    """One spelling of a converted prefab's path, to look things up by."""
    return os.path.normcase(os.path.abspath(str(converted_prefab)))


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
    
    def add_converted_prefab(self, unity_guid: str, converted_prefab: Path) -> None:
        """A Unity prefab's converted file, where Stage 1 wrote it. Two
        prefabs of one name in different folders are kept apart this way;
        by name the second would take the first one's place."""
        self.prefab_guids[unity_guid] = Path(converted_prefab)
        self.guid_to_name[unity_guid] = Path(converted_prefab).stem

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
                 entity_maps_by_path: Optional[Dict[str, Dict]] = None,
                 asset_index: Optional[Dict] = None,
                 trace=None,
                 asset_processor=None):
        """
        `asset_processor` is the Stage 1 worker (an
        `IntegratedAssetProcessor` on the same output folder). With it a
        scene's own objects - the ones that are not prefab instances - get
        what they show converted like the objects of a prefab: materials,
        models, collision meshes, and a model file instanced straight in the
        scene becomes entities. Without it such objects are placed with
        their transforms, lights and primitive colliders only.

        `entity_maps_by_path` holds each converted prefab's entity map
        under `prefab_key(<converted file>)`; `entity_maps_by_stem` the same
        maps under the file's name, for a caller that knows no more.

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
        self.asset_processor = asset_processor
        # What the scene's own objects show, converted (see
        # `IntegratedAssetProcessor.convert_assets_of`). Filled per level.
        self._scene_assets: Dict[str, Any] = {}
        # The scene's objects that Unity has switched off, or that sit below
        # one that is. Filled per level.
        self._inactive_ids: set = set()
        # Optional `conversion_trace.ConversionTrace`; None changes nothing.
        self.trace = trace
        self.scene_path = ""
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
        # {component file id: its place in its object's m_Component list}
        self.component_rank: Dict[str, int] = {}
        # The scene's stripped transforms (`stripped_transforms`).
        self.stripped_transforms: Dict[str, Tuple[str, str]] = {}

        # The scene's RenderSettings block: its ambient light (see
        # `platforms.unity.scene_lighting`). None until a scene is parsed.
        self.render_settings: Optional[Dict] = None

        # =====================================================================
        # Coverage tracker — populated incrementally; reported via to_coverage()
        # =====================================================================
        self.coverage = CoverageTracker()

        # Project-supplied lookups (formerly sidecar reads). Keyed by the
        # output prefab stem (e.g. "Foo") so the lookup matches a Stage 2
        # prefab reference like `<output>/Prefabs/Foo.prefab`.
        self._entity_maps_by_stem: Dict[str, Dict] = dict(entity_maps_by_stem or {})
        self._entity_maps_by_path: Dict[str, Dict] = dict(entity_maps_by_path or {})
        # Asset index shape: {materials: {guid: hint}, meshes: {guid: stem},
        # prefabs: {guid: source_path}}.
        self._asset_index: Dict = dict(asset_index or {})
    
    def parse_unity_scene(self, scene_path: str) -> None:
        """Parse Unity scene file"""
        self.scene_path = str(scene_path)
        self.game_objects.clear()
        self.transforms.clear()
        self.transform_to_gameobject.clear()
        self.prefab_references.clear()
        self.missing_prefabs.clear()
        self.prefab_instances.clear()
        self.components_data.clear()
        self.component_rank.clear()
        self.render_settings = None
        
        with open(scene_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.stripped_transforms = stripped_transforms(content)
        
        # First pass: Extract PrefabInstance blocks to get GUID mappings.
        # The doc body key is `PrefabInstance:` in the modern (Unity 2018.3+)
        # prefab system and `Prefab:` in the legacy (pre-2018.3) one; both are
        # !u!1001. The first guid encountered in the body is the source-prefab
        # guid in either format (modification targets reference it by guid).
        prefab_instance_guids = {}  # fileID -> GUID
        prefab_instance_pattern = r'--- !u!1001 &(\d+)\n(?:PrefabInstance|Prefab):.*?guid:\s*([a-f0-9]+)'
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
                    self.component_rank.update(component_ranks(doc['GameObject']))
                    self._parse_game_object(doc['GameObject'], anchor, prefab_instance_guids)
                elif 'PrefabInstance' in doc:
                    self._parse_prefab_instance(doc['PrefabInstance'], anchor)
                elif 'Prefab' in doc and isinstance(doc['Prefab'], dict):
                    # Legacy (pre-2018.3) prefab instance: doc key is `Prefab:`,
                    # source ref is `m_ParentPrefab:`. m_IsPrefabParent == 1 marks
                    # a prefab-asset reference rather than a scene instance — skip
                    # those; only m_IsPrefabParent == 0 docs are real placements.
                    if int(doc['Prefab'].get('m_IsPrefabParent', 0) or 0) == 0:
                        self._parse_prefab_instance(doc['Prefab'], anchor)
                elif 'RenderSettings' in doc and isinstance(doc['RenderSettings'], dict):
                    self.render_settings = doc['RenderSettings']
                    self.coverage.record_component('RenderSettings', 'SceneLighting')
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
        self._hang_below_placements()
        # A scale that differs by axis reaches nothing below its entity in
        # O3DE: it is carried down to the objects below here.
        from platforms.unity.scale_carry import carry_scales_down
        carry_scales_down(self.game_objects, self.coverage.warn)
    
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
        self.game_objects[file_id].is_active = str(go_data.get('m_IsActive', 1)) != '0'

    def _parse_prefab_instance(self, prefab_data: Dict, anchor: str = "") -> None:
        """
        Parse PrefabInstance data — capture transform overrides for the existing
        prefab_instances pipeline, AND capture the full m_Modifications array +
        sibling override fields (added/removed components, added GameObjects)
        so _create_prefab_instance can emit non-transform patches.
        """
        # `m_SourcePrefab` is the modern (2018.3+) field; `m_ParentPrefab` is the
        # legacy (pre-2018.3) equivalent. The m_Modification block is identical
        # across both formats, so everything below is format-agnostic.
        source_prefab = prefab_data.get('m_SourcePrefab') or prefab_data.get('m_ParentPrefab') or {}
        prefab_guid   = source_prefab.get('guid', '')
        if not prefab_guid:
            return

        # An instance of a model file has no converted prefab to point at:
        # it becomes the objects Unity makes of the model, as in a prefab.
        model = self.asset_processor.model_objects_for(prefab_guid) if self.asset_processor else None
        if model:
            add_model_instance(self.log, prefab_data, anchor, prefab_guid, model,
                               self.game_objects, self.transform_to_gameobject)
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

        # Project the transform modifications of the instance's own root
        # onto position/rotation/scale. Those on an object inside the
        # instance are emitted as patches on that object.
        pos        = [0, 0, 0]
        rot        = [0, 0, 0, 1]
        scale_vals = [1, 1, 1]
        AXIS = {'x': 0, 'y': 1, 'z': 2, 'w': 3}
        root_target = root_override_target(modifications)

        for mod in modifications:
            property_path = (mod.get('propertyPath') or '').strip()
            value         = mod.get('value')
            if property_path == 'm_Name':
                instance_data['name'] = value
            elif not targets_root(mod, root_target):
                continue
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

        # The PrefabInstance's file id in the scene: its identity for the
        # conversion trace. Not used for emission.
        instance_data['unity_file_id'] = str(anchor)
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
            # The objects of a model instance know their children by object id.
            go.children_ids += [child for child in go.model_children if child not in go.children_ids]
            for child_id in go.children_ids:
                if child_id in self.game_objects:
                    self.game_objects[child_id].parent_id = file_id

        # An object that names a parent which does not list it: the root of
        # a model file placed below another object of the scene. The parent
        # lists the placement by a transform id of the scene's own, which
        # names no object here. Without this the object is neither a root
        # nor anyone's child, and is never written.
        for file_id, go in self.game_objects.items():
            parent = self.game_objects.get(go.parent_id) if go.parent_id else None
            if parent is not None and file_id not in parent.children_ids:
                parent.children_ids.append(file_id)

    def _dispatch_component_processors(self) -> None:
        """Dispatch collected component blocks to processor parse() methods,
        each object's in Unity's order (``prefab.in_unity_order``)."""
        for comp_id, comp_info in in_unity_order(self.components_data, self.component_rank).items():
            comp_type = comp_info['type']
            comp_data = comp_info['data']

            go_ref = comp_data.get('m_GameObject', {})
            go_id  = str(go_ref.get('fileID', ''))

            if go_id not in self.game_objects:
                continue

            go = self.game_objects[go_id]
            go.component_ids[comp_type] = str(comp_id)
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
            go.component_data['unity_prefab_instance_file_id'] = instance.get('unity_file_id', '')
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
                elif instance['parent_fileID'] in self.stripped_transforms:
                    # Placed below an object of another placement
                    # (`_hang_below_placements` finds it).
                    go.parent_id = instance['parent_fileID']

            self.game_objects[file_id] = go

            prefab_path = self.prefab_db.find_prefab_by_guid(instance['guid'])
            if not prefab_path:
                prefab_path = self.prefab_db.find_prefab_by_name(name)

            if prefab_path:
                self.prefab_references[file_id] = prefab_path
            else:
                self.missing_prefabs.add(name)
                self.coverage.record_missing_prefab(instance['guid'])
    
    # -------------------------------------------------------------------------
    # WHAT A SCENE ADDS BELOW A PLACED PREFAB
    # A rock dropped under a placed rock, a lamp hung on a placed wall: the
    # scene's own object, parented to an object inside the placement. Unity
    # names that parent by a stripped transform.
    # -------------------------------------------------------------------------

    def _hang_below_placements(self) -> None:
        """Give every object and placement that hangs below an object of a
        placed prefab its parent: the placement, with the transform it hangs
        under inside it noted as ``component_data["parent_in_placement"]``
        (that transform's file id in the source prefab). Before this they
        named a parent the scene has no object for, and were never written."""
        placement_of = {go.component_data.get('unity_prefab_instance_file_id'): go
                        for go in self.game_objects.values() if go.is_prefab_instance}
        for go in list(self.game_objects.values()):
            stripped = self.stripped_transforms.get(str(go.parent_id or ''))
            if stripped is None:
                continue
            placement = placement_of.get(stripped[0])
            if placement is None:
                self.coverage.warn(f"'{go.name}' hangs below a placed prefab the scene does not hold; "
                                   f"it is written at the top of the level.")
                go.parent_id = None
                continue
            go.parent_id = placement.file_id
            go.component_data["parent_in_placement"] = stripped[1]
            if go.file_id not in placement.children_ids:
                placement.children_ids.append(go.file_id)

    def _create_objects_below_placement(self, placement: GameObject, instance_id: str,
                                        all_game_objects: Dict, entities_dict: Dict, instances_dict: Dict,
                                        entity_id_map: Dict, output_base: Path) -> None:
        """Write what the scene hangs below an object of this placed prefab.

        Each is the level's own entity (or placement) and names its parent
        inside the placement by path, ``Instance_[n]/Entity_[m]``: the engine
        reads an entity reference relative to the prefab that holds it
        (``InstanceEntityIdMapper::MapJsonToId``). An object whose parent
        has no entity in the converted prefab hangs under the prefab's root."""
        sidecar = self._load_entity_map_sidecar(self.prefab_references[placement.file_id]) or {}
        for child_id in placement.children_ids:
            child = all_game_objects.get(child_id)
            if child is None or "parent_in_placement" not in child.component_data:
                continue
            owner = (sidecar.get("transform_owners") or {}).get(str(child.component_data["parent_in_placement"]))
            alias = (sidecar.get("entity_aliases") or {}).get(owner)
            if not alias:
                alias = sidecar.get("root_entity") or "ContainerEntity"
                self.coverage.warn(f"'{child.name}' hangs below an object of '{placement.name}' that has no "
                                   f"entity of its own; it is put under the prefab's root.")
            self._create_entity_recursive(child, all_game_objects, entities_dict, instances_dict,
                                          entity_id_map, output_base, f"{instance_id}/{alias}")

    def convert_to_o3de_coordinates(self, unity_transform: Transform) -> Tuple[Transform, bool]:
        """Delegate to the canonical O3DE-target coordinate converter."""
        from targets.o3de.prefab_writer import convert_to_o3de_coordinates
        return convert_to_o3de_coordinates(unity_transform)
    
    def create_o3de_level(self, output_path: str, output_base: Path,
                          level_name: Optional[str] = None) -> Tuple[int, int, int]:
        """Create O3DE level file in JSON format. ``level_name`` is what the
        level is known by (``stage_runner.level_name_for``): the file's name
        when it is not given."""
        if self.trace is not None:
            self.trace.begin_scene(level_name or Path(output_path).stem,
                                   Path(self.scene_path), Path(output_path))
        level_data = {
            "ContainerEntity": self._create_level_container(),
            "Entities": {},
            "Instances": {}
        }
        
        entity_id_map = {}
        child_order = []
        
        # What the scene's own objects show: their materials, models and
        # collision meshes, converted beside the prefabs' ones.
        self._scene_assets = {}
        if self.asset_processor is not None:
            own_objects = {file_id: go for file_id, go in self.game_objects.items()
                           if not go.is_prefab_instance}
            self._scene_assets = self.asset_processor.convert_assets_of(
                own_objects, Path(self.scene_path).name)

        from targets.o3de.prefab_writer import inactive_objects
        self._inactive_ids = inactive_objects(self.game_objects)

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
                if self.trace is not None:
                    self.trace.record_instance(root_go, instance_id, prefab_path,
                                               level_data["Instances"][instance_id])
                self._create_objects_below_placement(
                    root_go, instance_id, self.game_objects, level_data["Entities"],
                    level_data["Instances"], entity_id_map, output_base)
                
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
        
        lighting_entity_id = self._add_ambient_light(level_data["Entities"], "Entity_[1000000]")
        if lighting_entity_id:
            child_order.append(lighting_entity_id)
            blank_entity_count += 1

        if child_order:
            level_data["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"] = child_order
        
        with open(output_path, 'w') as f:
            json.dump(level_data, f, indent=4)
        
        # Count all entities and instances created
        total_entities = len(level_data["Entities"])
        total_instances = len(level_data["Instances"])
        
        return total_entities + total_instances, total_instances, total_entities
    
    def _material_hint(self, asset_index: Optional[Dict], material_guid: str) -> Optional[str]:
        """The hint of a converted material: from Stage 1's index, else
        converted now by the stage's own worker. A material that only a
        scene's overrides use (a carpet laid over a common floor) is in no
        prefab, so Stage 1 never met it."""
        hint = ((asset_index or {}).get('materials') or {}).get(material_guid)
        if not hint and self.asset_processor is not None:
            hint = self.asset_processor.material_hint_for(material_guid)
        return hint

    # -------------------------------------------------------------------------
    # SCENE LIGHTING
    # -------------------------------------------------------------------------

    def _add_ambient_light(self, entities: Dict, parent_entity_id: str) -> Optional[str]:
        """Add the level's one ambient light: an entity with a Gradient GI
        component that carries the Unity scene's three ambient colours.
        Returns the entity's id, or None for a scene without ambient
        colours."""
        from platforms.unity.scene_lighting import ambient_gradient
        from targets.o3de.prefab_writer import gradient_gi_component

        ambient = ambient_gradient(self.render_settings)
        if ambient is None:
            return None

        entity_id = self._generate_entity_id()
        entity = self._make_bare_entity(entity_id, "Gradient GI", parent_entity_id)
        entity["Components"]["EditorGradientGIComponent"] = gradient_gi_component(
            self._generate_component_id(), ambient["sky"], ambient["equator"], ambient["ground"])
        entities[entity_id] = entity

        self.log(f"  [Lighting] Gradient GI: sky {ambient['sky']}, equator {ambient['equator']}, "
                 f"ground {ambient['ground']} (Unity ambient source: {ambient['mode']})")
        if not ambient["exact"]:
            self.coverage.warn(
                f"The scene takes its ambient light from its {ambient['mode'].lower()}, not from "
                f"its three ambient colours. The level's Gradient GI carries the three colours "
                f"the scene stores, so its ambient tone will differ from Unity's.")
        return entity_id

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
    
    def _drop_lost_root_overrides(self, go: GameObject, sidecar: Optional[Dict]) -> None:
        """Put a placement whose overrides name a root its prefab no longer
        has (``prefab.lost_root``) where Unity puts it: where the prefab's
        own root stands, with those overrides dropped."""
        if not lost_root(go.prefab_modifications, sidecar, go.prefab_source_guid):
            return
        root = root_override_target(go.prefab_modifications)
        go.prefab_modifications = [mod for mod in go.prefab_modifications if not targets_root(mod, root)]
        go.transform = Transform(tuple(sidecar.get("root_position") or (0.0, 0.0, 0.0)),
                                 tuple(sidecar.get("root_rotation") or (0.0, 0.0, 0.0, 1.0)),
                                 (1.0, 1.0, 1.0))
        self.coverage.warn(
            f"The placement '{go.name}' was saved against an earlier form of its prefab: its position "
            f"and rotation name an object the prefab no longer has. Unity drops them and so does the "
            f"converter; it stands where the prefab's own root stands.")

    def _convert_to_assets_path(self, prefab_path: Path) -> str:
        """Return the O3DE prefab Source path for ``prefab_path``.

        O3DE's PrefabLoader resolves the ``Source`` field as a path
        relative to the project root (the directory containing
        ``project.json``), preserving original case. The pre-2026-05-31
        behaviour used the prefab search-dir's leaf folder name (or just
        the filename) which produced paths like ``Prefabs/Foo.prefab``
        that the loader resolved to ``<proj>/Prefabs/Foo.prefab`` —
        always failing when the real file lives under ``Assets/.../``.

        Walks up from the prefab looking for ``project.json``. Falls
        back to the legacy search-dir / filename path only when the
        prefab isn't inside an O3DE project (rare; useful for tests)."""
        from integrated_asset_processor import _project_relative_path
        rel = _project_relative_path(prefab_path)
        if rel:
            return rel

        # Legacy fallback path — used only when no project.json sits
        # above the prefab (typically a synthetic test fixture). The
        # leaf-folder construction here is broken for real projects;
        # the `_project_relative_path` branch above is the correct one.
        for search_dir in self.prefab_db.search_dirs:
            try:
                rel_to_search = prefab_path.relative_to(search_dir)
                return f"{search_dir.name}/{rel_to_search}".replace("\\", "/")
            except ValueError:
                continue
        return f"Prefabs/{prefab_path.name}"
    
    def _create_prefab_instance(self, go: GameObject, prefab_path: Path,
                                output_base: Path, parent_entity_id: str) -> Dict:
        """Emit a prefab Instance entry with JSON-patch overrides.

        Same tiered scheme as Stage 1's nested-instance emitter:
          Tier 1  Transform — translate, rotate, scale on the ContainerEntity
          Tier 2  m_IsActive — the object and everything below it switched
                  off or on (`prefab_writer.active_state_patches`)
          Tier 3  m_Materials.Array.data[N] — the slot's entry added on the
                  entity of the renderer the override targets
                  (`prefab_writer.material_override_patches`). Label key =
                  FBX-internal material name at slot N (read from the
                  source prefab's sidecar `material_slot_labels`).
        Unhandled propertyPaths are recorded into self.coverage.
        """
        source_path = self._convert_to_assets_path(prefab_path)
        sidecar = self._load_entity_map_sidecar(prefab_path)
        self._drop_lost_root_overrides(go, sidecar)
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

        # Scale: what the placement sets, on the instance's root entity.
        from targets.o3de.prefab_writer import instance_scale_patches
        patches += instance_scale_patches(go, sidecar, self._generate_component_id(), self.coverage.warn)

        # ---- Tier 2 + 3: walk modifications by propertyPath ----
        entity_aliases       = (sidecar or {}).get("entity_aliases", {})
        material_slot_labels = (sidecar or {}).get("material_slot_labels", {})

        if go.prefab_modifications and not sidecar:
            self.coverage.warn(
                f"No entity-map sidecar for prefab '{prefab_path.name}' — "
                f"non-transform overrides on scene instance '{go.name}' cannot be targeted."
            )

        # An instance below a switched-off object of the scene: all of it off.
        if go.file_id in self._inactive_ids:
            from targets.o3de.prefab_writer import active_state_patches
            patches += active_state_patches("", False, sidecar)

        # Transform overrides on objects inside the instance.
        from targets.o3de.prefab_writer import (
            child_transform_patches, light_override_patches, mesh_override_patches, overrides_a_light)
        patches += child_transform_patches(go.prefab_modifications, sidecar, go.name, self.coverage.warn)

        # Overrides of the lights inside the instance.
        patches += light_override_patches(go.prefab_modifications, sidecar, self.coverage)

        # Overrides of the meshes inside the instance.
        patches += mesh_override_patches(go.prefab_modifications, sidecar,
                                         getattr(self.asset_processor, "model_hint_for", None),
                                         go.name, self.coverage)

        material_overrides: Dict[str, Dict[int, str]] = {}

        for mod in go.prefab_modifications:
            prop_path = (mod.get('propertyPath') or '').strip()
            value     = mod.get('value', None)
            objref    = mod.get('objectReference') or {}
            target    = mod.get('target') or {}
            target_id = str(target.get('fileID', ''))

            if overrides_a_light(mod, sidecar) or prop_path == 'm_Mesh':
                continue

            if prop_path == 'm_Name' or prop_path.startswith(
                ('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.')
            ):
                self.coverage.record_modification(prop_path, handled=True, example_value=value)
                continue

            if prop_path == 'm_IsActive':
                from targets.o3de.prefab_writer import active_state_patches
                state_patches = active_state_patches(target_id, str(value) != '0', sidecar)
                patches.extend(state_patches)
                self.coverage.record_modification(prop_path, handled=bool(state_patches), example_value=value)
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

        # Emit material slot patches: each override onto the renderer it
        # targets, its material converted now if no prefab brought it in.
        from targets.o3de.prefab_writer import material_override_patches
        asset_index = self._get_asset_index(prefab_path)
        patches += material_override_patches(
            material_overrides, sidecar, lambda guid: self._material_hint(asset_index, guid),
            go.name, self.coverage)

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
        hasn't processed the prefab in the active project).

        The map is looked up by the converted file itself first: two
        prefabs of one name in different folders have different maps."""
        return (self._entity_maps_by_path.get(prefab_key(prefab_path))
                or self._entity_maps_by_stem.get(prefab_path.stem))

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
        """Convert quaternion to the Euler angles O3DE reads back as the
        same rotation. One implementation, the prefab writer's."""
        from targets.o3de.prefab_writer import quaternion_to_euler
        return quaternion_to_euler(quaternion)

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
            if self.trace is not None:
                self.trace.record_instance(go, instance_id, prefab_path,
                                           instances_dict[instance_id])
            self._create_objects_below_placement(go, instance_id, all_game_objects, entities_dict,
                                                 instances_dict, entity_id_map, output_base)
            return f"{instance_id}/ContainerEntity"
        
        entity_id = self._generate_entity_id()
        entity_id_map[go.file_id] = entity_id
        
        o3de_transform, needs_nonuniform = self.convert_to_o3de_coordinates(go.transform)
        from targets.o3de.prefab_writer import with_light_turn, with_mesh_stretch
        o3de_transform, needs_nonuniform = with_mesh_stretch(go, o3de_transform, needs_nonuniform)
        o3de_transform = with_light_turn(go, o3de_transform, needs_nonuniform,
                                         getattr(self.asset_processor, "options", None))
        
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
                transform_data[UNIFORM_SCALE] = o3de_transform.scale[0]
            transform_component["Transform Data"] = transform_data
        
        entity["Components"]["TransformComponent"] = transform_component
        
        if needs_nonuniform:
            from targets.o3de.prefab_writer import non_uniform_scale_component
            entity["Components"]["EditorNonUniformScaleComponent"] = non_uniform_scale_component(
                self._generate_component_id(), o3de_transform.scale)

        # ---------------------------------------------------------------
        # Component Processors — emit phase (physics, mesh, material, ...)
        # ---------------------------------------------------------------
        ctx = ProcessingContext(
            material_mapping      = self._scene_assets.get("materials", {}),
            mesh_mapping          = self._scene_assets.get("meshes", {}),
            fbx_material_labels   = self._scene_assets.get("material_labels", {}),
            collider_pxmesh_mapping = self._scene_assets.get("collision_meshes", {}),
            entities_dict         = entities_dict,
            entity_id_map         = entity_id_map,
            generate_component_id = self._generate_component_id,
            generate_entity_id    = self._generate_entity_id,
            make_bare_entity      = self._make_bare_entity,
            log                   = self.log,
            stats                 = self.stats,
        )
        # For the conversion trace: which processor added which component or
        # child entity, and whether one of them rewrote the transform.
        component_owner: Dict[str, str] = {}
        child_owner: Dict[str, str] = {}
        transform_modified_by = ""

        collider_child_ids: List[str] = []
        for processor in self.component_processors:
            keys_before = set(entity["Components"])
            transform_before = json.dumps(entity["Components"]["TransformComponent"], sort_keys=True)                 if self.trace is not None else ""
            child_ids = processor.emit(go, entity, ctx)
            collider_child_ids.extend(child_ids)
            if self.trace is not None:
                owner = type(processor).__name__
                for key in set(entity["Components"]) - keys_before:
                    component_owner[key] = owner
                for child_id in child_ids:
                    child_owner[child_id] = owner
                if json.dumps(entity["Components"]["TransformComponent"], sort_keys=True) != transform_before:
                    transform_modified_by = owner

        if self.trace is not None:
            self.trace.record_entity(go, entity, "axis_swap", component_owner, child_owner,
                                     transform_modified_by)

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

        # An object Unity has switched off: its entity and the ones made
        # beside it start inactive and hidden.
        if go.file_id in self._inactive_ids:
            from targets.o3de.prefab_writer import mark_inactive
            mark_inactive(entity)
            for child_id in collider_child_ids:
                mark_inactive(entities_dict[child_id])

        if child_order:
            entity["Components"]["EditorEntitySortComponent"] = {
                "$type": "EditorEntitySortComponent",
                "Id": self._generate_component_id(),
                "Child Entity Order": child_order
            }

        entities_dict[entity_id] = entity
        return entity_id

