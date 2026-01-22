#!/usr/bin/env python3
"""
Unity Prefab to O3DE Converter

Converts Unity prefab assets to O3DE prefabs with components and materials.

Usage:
    python unity_prefab_to_o3de.py <unity_assets_folder> <output_folder>
"""

import yaml
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import os
import sys
import re
import json
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field


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
    mesh_path: Optional[str] = None
    material_paths: List[str] = field(default_factory=list)


@dataclass
class UnityMaterial:
    """Unity material data"""
    name: str
    shader: str
    textures: Dict[str, str] = field(default_factory=dict)  # property -> texture path
    properties: Dict[str, any] = field(default_factory=dict)


class UnityPrefabConverter:
    """Converts Unity prefabs to O3DE prefabs with components"""
    
    def __init__(self, unity_assets_root: str, output_root: str):
        self.unity_assets_root = Path(unity_assets_root)
        self.output_root = Path(output_root)
        
        self.game_objects: Dict[str, GameObject] = {}
        self.components_data: Dict[str, Dict] = {}
        self.materials_cache: Dict[str, UnityMaterial] = {}
        self.transform_to_gameobject: Dict[str, str] = {}
        
        self.entity_counter = 1000000
        self.material_counter = 0
        
        # Output directories
        self.prefabs_dir = self.output_root / "Prefabs"
        self.materials_dir = self.output_root / "Materials"
        self.meshes_dir = self.output_root / "Meshes"
        
        # Create output structure
        self.prefabs_dir.mkdir(parents=True, exist_ok=True)
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.meshes_dir.mkdir(parents=True, exist_ok=True)
    
    def parse_unity_prefab(self, prefab_path: str) -> Optional[str]:
        """
        Parse Unity prefab file and return root GameObject ID
        """
        print(f"Parsing prefab: {prefab_path}")
        
        # Reset state
        self.game_objects.clear()
        self.components_data.clear()
        self.transform_to_gameobject.clear()
        
        with open(prefab_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse documents with anchors
        doc_pattern = r'---\s+!u!\d+\s+&(\d+)\n(.*?)(?=---\s+!u!|\Z)'
        matches = re.findall(doc_pattern, content, re.DOTALL)
        
        for anchor, doc_content in matches:
            clean_content = re.sub(r'!u!\d+', '', doc_content)
            
            try:
                doc = yaml.safe_load(clean_content)
                if not doc:
                    continue
                
                # Parse different component types
                if 'Transform' in doc:
                    self._parse_transform(doc['Transform'], anchor)
                elif 'GameObject' in doc:
                    self._parse_game_object(doc['GameObject'], anchor)
                elif 'MeshFilter' in doc:
                    self._parse_mesh_filter(doc['MeshFilter'], anchor)
                elif 'MeshRenderer' in doc:
                    self._parse_mesh_renderer(doc['MeshRenderer'], anchor)
                else:
                    # Store other component data for reference
                    for key in doc.keys():
                        if key not in ['Transform', 'GameObject']:
                            self.components_data[anchor] = {key: doc[key]}
            
            except yaml.YAMLError as e:
                print(f"Warning: Failed to parse document {anchor}: {e}")
                continue
        
        # Build hierarchy
        self._build_hierarchy()
        
        # Find root GameObject (one without parent)
        root_go = None
        for go in self.game_objects.values():
            if go.parent_id is None:
                root_go = go.file_id
                break
        
        print(f"Parsed {len(self.game_objects)} GameObjects")
        return root_go
    
    def _parse_transform(self, transform_data: Dict, transform_anchor: str) -> None:
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
        
        # Create or update GameObject
        if go_file_id not in self.game_objects:
            self.game_objects[go_file_id] = GameObject(
                file_id=go_file_id,
                name="",
                transform=transform
            )
        else:
            self.game_objects[go_file_id].transform = transform
        
        # Store parent/children references
        parent = transform_data.get('m_Father', {})
        parent_transform_id = str(parent.get('fileID', '0'))
        if parent_transform_id != '0':
            self.game_objects[go_file_id].parent_id = parent_transform_id
        
        children = transform_data.get('m_Children', [])
        for child in children:
            if child and child.get('fileID'):
                child_transform_id = str(child['fileID'])
                self.game_objects[go_file_id].children_ids.append(child_transform_id)
    
    def _parse_game_object(self, go_data: Dict, go_anchor: str) -> None:
        """Parse GameObject"""
        file_id = go_anchor
        name = go_data.get('m_Name', 'GameObject')
        
        # Get component references
        components_list = go_data.get('m_Component', [])
        unity_components = []
        
        for comp in components_list:
            comp_ref = comp.get('component', {})
            comp_file_id = str(comp_ref.get('fileID', ''))
            if comp_file_id:
                # We'll determine component type when we parse the component data
                unity_components.append(UnityComponent(
                    type_name="Unknown",
                    file_id=comp_file_id
                ))
        
        # Update or create GameObject
        if file_id in self.game_objects:
            self.game_objects[file_id].name = name
            self.game_objects[file_id].components = unity_components
        else:
            self.game_objects[file_id] = GameObject(
                file_id=file_id,
                name=name,
                transform=Transform(),
                components=unity_components
            )
    
    def _parse_mesh_filter(self, mesh_filter_data: Dict, anchor: str) -> None:
        """Parse MeshFilter component"""
        mesh_ref = mesh_filter_data.get('m_Mesh', {})
        
        # Try to get mesh GUID
        guid = mesh_ref.get('guid', '')
        if guid:
            # Store mesh reference
            # We'll need to find the actual mesh file path from the GUID
            # For now, store the GUID
            self.components_data[anchor] = {
                'type': 'MeshFilter',
                'mesh_guid': guid
            }
    
    def _parse_mesh_renderer(self, mesh_renderer_data: Dict, anchor: str) -> None:
        """Parse MeshRenderer component"""
        materials = mesh_renderer_data.get('m_Materials', [])
        
        material_guids = []
        for mat_ref in materials:
            guid = mat_ref.get('guid', '')
            if guid:
                material_guids.append(guid)
        
        self.components_data[anchor] = {
            'type': 'MeshRenderer',
            'material_guids': material_guids
        }
    
    def _build_hierarchy(self) -> None:
        """Build parent-child hierarchy and resolve component references"""
        # Resolve transform IDs to GameObject IDs
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
        
        # Resolve component references
        for go in self.game_objects.values():
            for component in go.components:
                if component.file_id in self.components_data:
                    comp_data = self.components_data[component.file_id]
                    component.data = comp_data
                    component.type_name = comp_data.get('type', 'Unknown')
                    
                    # Extract mesh/material paths
                    if comp_data.get('type') == 'MeshFilter':
                        go.mesh_path = comp_data.get('mesh_guid', '')
                    elif comp_data.get('type') == 'MeshRenderer':
                        go.material_paths = comp_data.get('material_guids', [])
    
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
    
    def create_o3de_entity(self, go: GameObject, parent_element: ET.Element, 
                          unity_to_o3de_id: Dict[str, int]) -> ET.Element:
        """Create O3DE entity XML element with components"""
        entity = ET.SubElement(parent_element, 'Class')
        entity.set('name', 'Entity')
        entity.set('type', '{75651658-8663-478D-9090-2432DFCAFA44}')
        
        # Entity ID
        o3de_id = self.entity_counter
        unity_to_o3de_id[go.file_id] = o3de_id
        self.entity_counter += 1
        
        entity_id = ET.SubElement(entity, 'Class')
        entity_id.set('name', 'Id')
        entity_id.set('field', 'Id')
        entity_id.set('value', str(o3de_id))
        entity_id.set('type', '{6383F1D3-BB27-4E6B-A49A-6409B2059EAA}')
        
        # Entity Name
        name_elem = ET.SubElement(entity, 'Class')
        name_elem.set('name', 'AZStd::string')
        name_elem.set('field', 'Name')
        name_elem.set('value', go.name)
        name_elem.set('type', '{03AAAB3F-5C47-5A66-9EBC-D5FA4DB353C9}')
        
        # Components container
        components = ET.SubElement(entity, 'Class')
        components.set('name', 'AZStd::vector')
        components.set('field', 'Components')
        components.set('type', '{13D58FF9-1088-5C69-9A1F-C2A144B57B78}')
        
        # Add Transform component
        self._add_transform_component(components, go)
        
        # Add NonUniformScale component if needed
        o3de_transform, needs_nonuniform = self.convert_to_o3de_coordinates(go.transform)
        if needs_nonuniform:
            self._add_nonuniform_scale_component(components, o3de_transform)
        
        # Add Mesh component if mesh reference exists
        if go.mesh_path:
            self._add_mesh_component(components, go)
        
        # Add Material component if material references exist
        if go.material_paths:
            self._add_material_component(components, go)
        
        return entity
    
    def _add_transform_component(self, parent: ET.Element, go: GameObject) -> None:
        """Add EditorTransformComponent"""
        component = ET.SubElement(parent, 'Class')
        component.set('name', 'EditorTransformComponent')
        component.set('type', '{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0}')
        
        o3de_transform, _ = self.convert_to_o3de_coordinates(go.transform)
        
        # Parent Entity (will be fixed later)
        parent_entity = ET.SubElement(component, 'Class')
        parent_entity.set('name', 'EntityId')
        parent_entity.set('field', 'Parent Entity')
        parent_entity.set('value', '4294967295')
        parent_entity.set('type', '{6383F1D3-BB27-4E6B-A49A-6409B2059EAA}')
        
        # Transform data
        transform_data = ET.SubElement(component, 'Class')
        transform_data.set('name', 'Transform')
        transform_data.set('field', 'Transform Data')
        transform_data.set('type', '{5D9958E9-9F1E-4985-B532-FFFDE75FEDFD}')
        
        # Translation
        translation = ET.SubElement(transform_data, 'Class')
        translation.set('name', 'Vector3')
        translation.set('field', 'Translate')
        translation.set('value', f"{o3de_transform.position[0]} {o3de_transform.position[1]} {o3de_transform.position[2]}")
        translation.set('type', '{8379EB7D-01FA-4538-B64B-A6543B4BE73D}')
        
        # Rotation
        rotation = ET.SubElement(transform_data, 'Class')
        rotation.set('name', 'Quaternion')
        rotation.set('field', 'Rotation')
        rotation.set('value', f"{o3de_transform.rotation[0]} {o3de_transform.rotation[1]} {o3de_transform.rotation[2]} {o3de_transform.rotation[3]}")
        rotation.set('type', '{73103120-3DD3-4873-BAB3-9713FA2804FB}')
        
        # Scale
        uniform_scale = sum(o3de_transform.scale) / 3.0
        scale = ET.SubElement(transform_data, 'Class')
        scale.set('name', 'float')
        scale.set('field', 'Scale')
        scale.set('value', str(uniform_scale))
        scale.set('type', '{EA2C3E90-AFBE-44D4-A90D-FAAF79BAF93D}')
    
    def _add_nonuniform_scale_component(self, parent: ET.Element, transform: Transform) -> None:
        """Add EditorNonUniformScaleComponent"""
        component = ET.SubElement(parent, 'Class')
        component.set('name', 'EditorNonUniformScaleComponent')
        component.set('type', '{3B80F423-2AB7-4D2A-9962-7D9AFD18AE0C}')
        
        scale = ET.SubElement(component, 'Class')
        scale.set('name', 'Vector3')
        scale.set('field', 'Scale')
        scale.set('value', f"{transform.scale[0]} {transform.scale[1]} {transform.scale[2]}")
        scale.set('type', '{8379EB7D-01FA-4538-B64B-A6543B4BE73D}')
    
    def _add_mesh_component(self, parent: ET.Element, go: GameObject) -> None:
        """Add EditorMeshComponent with mesh reference"""
        component = ET.SubElement(parent, 'Class')
        component.set('name', 'EditorMeshComponent')
        component.set('type', '{FC315B86-3280-4D03-B4F0-5553D7D08432}')
        
        # Model Asset reference
        # This would need to be resolved to actual .azmodel path
        model_asset = ET.SubElement(component, 'Class')
        model_asset.set('name', 'Asset')
        model_asset.set('field', 'Model Asset')
        model_asset.set('value', f"meshes/{go.mesh_path}.azmodel")
        model_asset.set('type', '{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45D}')
    
    def _add_material_component(self, parent: ET.Element, go: GameObject) -> None:
        """Add EditorMaterialComponent with material references"""
        component = ET.SubElement(parent, 'Class')
        component.set('name', 'EditorMaterialComponent')
        component.set('type', '{0174263D-F8AF-4C26-A11D-B39B8F66D86D}')
        
        # Materials container
        materials_container = ET.SubElement(component, 'Class')
        materials_container.set('name', 'AZStd::vector')
        materials_container.set('field', 'Materials')
        materials_container.set('type', '{0A15B3DE-3129-5474-BCAD-27C74F8E39E5}')
        
        # Add each material reference
        for material_guid in go.material_paths:
            material_ref = ET.SubElement(materials_container, 'Class')
            material_ref.set('name', 'MaterialAssignment')
            material_ref.set('type', '{1DD447F3-5A7B-4F14-96AD-2E7DC115E47A}')
            
            # Material asset
            mat_asset = ET.SubElement(material_ref, 'Class')
            mat_asset.set('name', 'Asset')
            mat_asset.set('field', 'Material Asset')
            mat_asset.set('value', f"materials/{material_guid}.material")
            mat_asset.set('type', '{5B03C8E6-8CEE-4DA0-A7FA-CD88689DD45D}')
    
    def create_o3de_prefab(self, root_go_id: str, output_name: str) -> str:
        """Create O3DE prefab file from GameObject hierarchy"""
        if root_go_id not in self.game_objects:
            print(f"Error: Root GameObject {root_go_id} not found")
            return None
        
        root_go = self.game_objects[root_go_id]
        output_path = self.prefabs_dir / f"{output_name}.prefab"
        
        print(f"Creating prefab: {output_path}")
        
        unity_to_o3de_id = {}
        
        # Create root structure
        root = ET.Element('ObjectStream')
        root.set('version', '3')
        
        prefab = ET.SubElement(root, 'Class')
        prefab.set('name', 'Prefab')
        prefab.set('version', '1')
        prefab.set('type', '{8C7EA5A7-EF1C-45D4-B45C-57DADC60E870}')
        
        entities_container = ET.SubElement(prefab, 'Class')
        entities_container.set('name', 'PrefabDom::Entities')
        entities_container.set('field', 'Entities')
        entities_container.set('type', '{C8DF58A9-71F9-5572-AA60-823CEF62CDDC}')
        
        # Add entities recursively
        self._add_entity_hierarchy_with_mapping(root_go, entities_container, unity_to_o3de_id)
        
        # Fix parent entity IDs
        self._fix_parent_entity_ids(entities_container, unity_to_o3de_id)
        
        # Write to file
        self._write_xml(root, str(output_path))
        
        return str(output_path)
    
    def _add_entity_hierarchy_with_mapping(self, go: GameObject, parent_element: ET.Element,
                                            unity_to_o3de_id: Dict[str, int]) -> None:
        """Recursively add entity and children"""
        self.create_o3de_entity(go, parent_element, unity_to_o3de_id)
        
        for child_id in go.children_ids:
            if child_id in self.game_objects:
                self._add_entity_hierarchy_with_mapping(
                    self.game_objects[child_id], 
                    parent_element, 
                    unity_to_o3de_id
                )
    
    def _fix_parent_entity_ids(self, entities_container: ET.Element,
                                unity_to_o3de_id: Dict[str, int]) -> None:
        """Fix parent entity IDs in all entities"""
        for entity in entities_container.findall('.//Class[@name="Entity"]'):
            entity_id_elem = entity.find('.//Class[@name="Id"][@field="Id"]')
            if entity_id_elem is None:
                continue
            
            entity_id = int(entity_id_elem.get('value', '0'))
            
            unity_go_id = None
            for u_id, o_id in unity_to_o3de_id.items():
                if o_id == entity_id:
                    unity_go_id = u_id
                    break
            
            if not unity_go_id or unity_go_id not in self.game_objects:
                continue
            
            unity_go = self.game_objects[unity_go_id]
            
            if unity_go.parent_id and unity_go.parent_id in unity_to_o3de_id:
                parent_o3de_id = unity_to_o3de_id[unity_go.parent_id]
                
                parent_id_elem = entity.find('.//Class[@name="EditorTransformComponent"]//Class[@name="EntityId"][@field="Parent Entity"]')
                if parent_id_elem is not None:
                    parent_id_elem.set('value', str(parent_o3de_id))
    
    def _write_xml(self, root: ET.Element, output_path: str) -> None:
        """Write XML to file with pretty formatting"""
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        pretty_xml = dom.toprettyxml(indent='    ')
        lines = [line for line in pretty_xml.split('\n') if line.strip()]
        pretty_xml = '\n'.join(lines)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
    
    def process_prefab_folder(self, prefab_folder: Path) -> List[str]:
        """Process all prefabs in a folder"""
        converted_prefabs = []
        
        for prefab_file in prefab_folder.rglob('*.prefab'):
            # Skip meta files and already processed files
            if prefab_file.name.endswith('.meta'):
                continue
            
            try:
                root_go_id = self.parse_unity_prefab(str(prefab_file))
                if root_go_id:
                    output_name = prefab_file.stem
                    output_path = self.create_o3de_prefab(root_go_id, output_name)
                    if output_path:
                        converted_prefabs.append(output_path)
                        print(f"✓ Converted: {prefab_file.name} -> {output_name}.prefab")
            except Exception as e:
                print(f"✗ Failed to convert {prefab_file.name}: {e}")
        
        return converted_prefabs


def main():
    if len(sys.argv) < 3:
        print("Usage: python unity_prefab_to_o3de.py <unity_assets_folder> <output_folder>")
        sys.exit(1)
    
    unity_assets_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    if not os.path.exists(unity_assets_folder):
        print(f"Error: Unity assets folder not found: {unity_assets_folder}")
        sys.exit(1)
    
    converter = UnityPrefabConverter(unity_assets_folder, output_folder)
    
    print(f"\n=== Unity Prefab to O3DE Converter ===")
    print(f"Unity Assets: {unity_assets_folder}")
    print(f"Output: {output_folder}\n")
    
    # Process all prefabs
    converted = converter.process_prefab_folder(Path(unity_assets_folder))
    
    print(f"\n=== Conversion Complete ===")
    print(f"Converted {len(converted)} prefabs")
    print(f"Output directory: {output_folder}")
    print(f"  Prefabs: {converter.prefabs_dir}")
    print(f"  Materials: {converter.materials_dir}")
    print(f"  Meshes: {converter.meshes_dir}")


if __name__ == '__main__':
    main()
