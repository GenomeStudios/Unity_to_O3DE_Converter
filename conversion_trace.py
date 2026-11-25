"""
=============================================================================
CONVERSION TRACE
=============================================================================

The converter's own account of how it produced what it wrote. A stage run
that is given a ``ConversionTrace`` records, for every value it emits, the
source values it came from and the rule that turned one into the other:

  - every entity: the Unity local transform, the emitted transform, and the
    components each processor added, beside the Unity component data;
  - every nested or scene prefab instance: the Unity transform and the
    patches emitted for it;
  - every ``.assetinfo`` write: the up axis, the effective mesh settings and
    the coordinate rule of every mesh group, with where its translation came
    from;
  - every FBX the run touched: the raw facts of the file (axes, unit scale,
    each node's local and geometric transform, each geometry's box).

Nothing here changes what the converter emits. Without a trace the hooks do
nothing.

Written by ``write`` as::

    trace.json             catalog and counts
    prefabs/<guid>.json    entities and instances of one prefab
    scenes/<name>.json     entities and instances of one scene
    assetinfos.json        every .assetinfo write, in order (the last one of
                           a file is the one on disk)
    fbx_facts.json         raw facts per FBX file
"""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# Components every entity carries; they say nothing about the conversion.
BOILERPLATE_COMPONENTS = frozenset({
    "EditorDisabledCompositionComponent", "EditorEntityIconComponent",
    "EditorInspectorComponent", "EditorLockComponent",
    "EditorPendingCompositionComponent", "EditorVisibilityComponent",
    "EditorOnlyEntityComponent", "EditorEntitySortComponent",
    "EditorPrefabComponent", "TransformComponent",
})

TRANSFORM_PATCH_PREFIX = "/ContainerEntity/Components/TransformComponent/Transform Data/"

# Node properties of an FBX Model record worth keeping, by their FBX name.
FBX_NODE_PROPERTIES = (
    "Lcl Translation", "Lcl Rotation", "Lcl Scaling",
    "PreRotation", "PostRotation", "RotationOffset", "RotationPivot",
    "ScalingOffset", "ScalingPivot", "RotationOrder", "InheritType",
    "GeometricTranslation", "GeometricRotation", "GeometricScaling",
)

FBX_GLOBAL_SETTINGS = (
    "UpAxis", "UpAxisSign", "FrontAxis", "FrontAxisSign", "CoordAxis", "CoordAxisSign",
    "OriginalUpAxis", "OriginalUpAxisSign", "UnitScaleFactor", "OriginalUnitScaleFactor",
)


# =============================================================================
# THE TRACE
# =============================================================================

class ConversionTrace:
    """Collects trace records during a stage run. See the module docstring."""

    def __init__(self) -> None:
        self.prefabs:    Dict[str, dict] = {}
        self.scenes:     Dict[str, dict] = {}
        self.assetinfos: List[dict] = []
        self.fbx_files:  Dict[str, Path] = {}       # output file name -> path
        self._current:   Optional[dict] = None      # the prefab or scene being emitted

    # -------------------------------------------------------------------------
    # Containers: one prefab or one scene at a time
    # -------------------------------------------------------------------------

    def begin_prefab(self, guid: str, source_path: Path, output_path: Path) -> None:
        self._current = {
            "kind": "prefab", "source_guid": guid,
            "source_path": str(source_path), "output_path": str(output_path),
            "entities": [], "instances": [],
        }
        self.prefabs[guid] = self._current

    def begin_scene(self, name: str, source_path: Path, output_path: Path) -> None:
        self._current = {
            "kind": "scene", "name": name,
            "source_path": str(source_path), "output_path": str(output_path),
            "entities": [], "instances": [],
        }
        self.scenes[name] = self._current

    # -------------------------------------------------------------------------
    # Entities
    # -------------------------------------------------------------------------

    def record_entity(self, go, entity: dict, rule: str,
                      component_owner: Dict[str, str],
                      child_owner: Dict[str, str],
                      transform_modified_by: str = "") -> None:
        """One emitted entity. ``entity`` is the finished entity dict, read
        after every component processor has run, so the record holds what
        was really written."""
        if self._current is None:
            return
        components = entity.get("Components", {})
        transform = components.get("TransformComponent", {})
        data = transform.get("Transform Data", {})
        nonuniform = components.get("EditorNonUniformScaleComponent", {})

        self._current["entities"].append({
            "go_file_id":       str(go.file_id),
            "entity_id":        entity.get("Id", ""),
            "name":             entity.get("Name", ""),
            "parent_entity_id": transform.get("Parent Entity", ""),
            "unity":            _unity_transform(go),
            "rule":             rule,
            "transform_modified_by": transform_modified_by,
            "emitted": {
                "translate":        _copy(data.get("Translate")),
                "rotate_euler":     _copy(data.get("Rotate")),
                "scale":            data.get("Scale"),
                "nonuniform_scale": _copy(nonuniform.get("Scale")),
            },
            "unity_components": _unity_components(go),
            "components": [
                {"key": key, "processor": component_owner.get(key, ""), "emitted": _copy(body)}
                for key, body in components.items() if key not in BOILERPLATE_COMPONENTS
            ],
            "child_entities": [
                {"entity_id": child_id, "processor": owner}
                for child_id, owner in child_owner.items()
            ],
        })

    def record_instance(self, go, instance_alias: str, prefab_path: Path,
                        instance: dict) -> None:
        """One emitted prefab instance: a nested one in a prefab, or a placed
        one in a scene. ``instance`` is the ``{"Source", "Patches"}`` dict."""
        if self._current is None:
            return
        patches = instance.get("Patches", [])
        self._current["instances"].append({
            "go_file_id":     str(go.file_id),
            # A scene gives its placed instances made-up ids; the file id of
            # the PrefabInstance itself is carried beside it.
            "unity_instance_file_id": str(go.component_data.get("unity_prefab_instance_file_id", "")
                                          or go.file_id),
            "instance_alias": instance_alias,
            "name":           go.name,
            "source_guid":    go.prefab_source_guid or "",
            "source_prefab":  str(prefab_path),
            "source":         instance.get("Source", ""),
            "unity":          _unity_transform(go),
            "rule":           "axis_swap",
            "emitted":        transform_from_patches(patches),
            "patches":        _copy(patches),
        })

    # -------------------------------------------------------------------------
    # Mesh import rules
    # -------------------------------------------------------------------------

    def record_assetinfo(self, fbx_path: Path, mesh_guid: Optional[str], up_axis: int,
                         settings: dict, rotation: Optional[list],
                         node_autocenters: dict, shared_translation: Optional[list],
                         groups: List[dict], physx_specs: Optional[list]) -> None:
        """One ``.assetinfo`` write. A file written more than once keeps every
        write here; the last is what is on disk."""
        self.fbx_files[Path(fbx_path).name] = Path(fbx_path)
        aligned = {spec.get("name"): spec.get("translation")
                   for spec in (physx_specs or []) if spec.get("translation") is not None}

        records = []
        for group in groups:
            is_physx = "NodeSelectionList" in group
            selection = group.get("NodeSelectionList") or group.get("nodeSelectionList") or {}
            nodes = [node for node in selection.get("selectedNodes", []) if node != "RootNode"]
            rule = next((r for r in (group.get("rules") or {}).get("rules", [])
                         if r.get("$type") == "CoordinateSystemRule"), {})
            leaf = nodes[0].split(".")[-1] if nodes else ""

            if "translation" not in rule:
                source = ""
            elif is_physx and group.get("name") in aligned:
                source = "collider_alignment"
            elif shared_translation is not None:
                source = "user_default_position"
            else:
                source = "auto_center"

            records.append({
                "kind":               "physx" if is_physx else "visual",
                "name":               group.get("name", ""),
                "node_paths":         nodes,
                "rotation":           _copy(rule.get("rotation")),
                "translation":        _copy(rule.get("translation")),
                "translation_source": source,
                "auto_center_of_node": _copy(node_autocenters.get(leaf)),
                "convex":             group.get("export method") == 1,
            })

        self.assetinfos.append({
            "fbx":           Path(fbx_path).name,
            "mesh_guid":     mesh_guid or "",
            "written_for":   (self._current or {}).get("source_guid", ""),
            "up_axis":       up_axis,
            "settings":      _copy(settings),
            "rotation_rule": "y_up_plus_90_x" if (up_axis == 1 and settings.get("auto_rotation", True))
                             else ("user_default_rotation" if rotation else ""),
            "groups":        records,
        })

    # -------------------------------------------------------------------------
    # Writing
    # -------------------------------------------------------------------------

    def write(self, folder: Path) -> Path:
        """Write the trace under ``folder`` and return the catalog's path."""
        folder = Path(folder)
        (folder / "prefabs").mkdir(parents=True, exist_ok=True)
        (folder / "scenes").mkdir(parents=True, exist_ok=True)

        catalog = {"prefabs": {}, "scenes": {}, "assetinfo_writes": len(self.assetinfos),
                   "fbx_files": len(self.fbx_files)}
        for guid, record in self.prefabs.items():
            name = f"prefabs/{_file_stem(guid)}.json"
            _write_json(folder / name, record)
            catalog["prefabs"][guid] = name
        for scene, record in self.scenes.items():
            name = f"scenes/{_file_stem(scene)}.json"
            _write_json(folder / name, record)
            catalog["scenes"][scene] = name

        _write_json(folder / "assetinfos.json", self.assetinfos)
        _write_json(folder / "fbx_facts.json",
                    {name: read_fbx_facts(path) for name, path in sorted(self.fbx_files.items())})
        _write_json(folder / "trace.json", catalog)
        return folder / "trace.json"


# =============================================================================
# RECORD HELPERS
# =============================================================================

def _copy(value):
    return copy.deepcopy(value)


def _file_stem(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in key)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def _unity_transform(go) -> dict:
    return {
        "position": list(go.transform.position),
        "rotation": list(go.transform.rotation),
        "scale":    list(go.transform.scale),
    }


def _unity_components(go) -> dict:
    """What the Unity parser read for this object, as the processors saw it."""
    return {
        "mesh_guid":      go.mesh_guid or "",
        "mesh_file_id":   str(go.mesh_file_id or ""),
        "material_guids": list(go.material_guids),
        "colliders":      _copy(go.colliders),
        "has_rigidbody":  bool(go.has_rigidbody),
        "rigidbody":      _copy(go.rigidbody_data),
        "component_data": sorted(go.component_data.keys()),
    }


def transform_from_patches(patches: List[dict]) -> dict:
    """The transform a patch list sets on an instance's container entity."""
    emitted = {"translate": None, "rotate_euler": None, "scale": None}
    for patch in patches:
        path = patch.get("path", "")
        if not path.startswith(TRANSFORM_PATCH_PREFIX):
            continue
        field = path[len(TRANSFORM_PATCH_PREFIX):]
        if field == "Scale":
            emitted["scale"] = patch.get("value")
            continue
        name, _, axis = field.partition("/")
        key = {"Translate": "translate", "Rotate": "rotate_euler"}.get(name)
        if key and axis.isdigit():
            if emitted[key] is None:
                emitted[key] = [0.0, 0.0, 0.0]
            emitted[key][int(axis)] = patch.get("value")
    return emitted


# =============================================================================
# COVERAGE CHECK
# Does the trace account for everything a run wrote?
# =============================================================================

def uncovered_in_prefab(prefab_file: Path, record: dict) -> List[str]:
    """Every emitted transform of one prefab (or level) file that the trace
    record does not hold with the same values. Empty means covered."""
    data = json.loads(Path(prefab_file).read_text(encoding="utf-8"))
    traced_entities = {e["entity_id"]: e for e in record.get("entities", [])}
    traced_instances = {i["instance_alias"]: i for i in record.get("instances", [])}
    problems: List[str] = []

    for entity_id, entity in data.get("Entities", {}).items():
        components = entity.get("Components", {})
        transform = components.get("TransformComponent", {}).get("Transform Data", {})
        nonuniform = components.get("EditorNonUniformScaleComponent", {}).get("Scale")
        if not transform and nonuniform is None:
            continue
        traced = traced_entities.get(entity_id)
        if traced is None:
            # Entities a processor made for an extra collider are traced under
            # the entity that owns them.
            if any(entity_id == child["entity_id"]
                   for e in traced_entities.values() for child in e["child_entities"]):
                continue
            problems.append(f"{Path(prefab_file).name}: entity {entity_id} has a transform and no trace record")
            continue
        emitted = traced["emitted"]
        if (emitted["translate"] != transform.get("Translate")
                or emitted["rotate_euler"] != transform.get("Rotate")
                or emitted["scale"] != transform.get("Scale")
                or emitted["nonuniform_scale"] != nonuniform):
            problems.append(f"{Path(prefab_file).name}: entity {entity_id} was traced with other values")

    for alias, instance in data.get("Instances", {}).items():
        traced = traced_instances.get(alias)
        if traced is None:
            problems.append(f"{Path(prefab_file).name}: instance {alias} has no trace record")
        elif traced["patches"] != instance.get("Patches", []):
            problems.append(f"{Path(prefab_file).name}: instance {alias} was traced with other patches")
    return problems


def uncovered_in_assetinfo(assetinfo_file: Path, writes: List[dict]) -> List[str]:
    """Every coordinate rule of one ``.assetinfo`` file that the last trace
    write for that file does not hold. Empty means covered."""
    fbx_name = Path(assetinfo_file).name[:-len(".assetinfo")]
    last = next((w for w in reversed(writes) if w["fbx"] == fbx_name), None)
    if last is None:
        return [f"{Path(assetinfo_file).name}: no trace record of its write"]

    traced = {group["name"]: group for group in last["groups"]}
    problems: List[str] = []
    for group in json.loads(Path(assetinfo_file).read_text(encoding="utf-8")).get("values", []):
        rule = next((r for r in (group.get("rules") or {}).get("rules", [])
                     if r.get("$type") == "CoordinateSystemRule"), {})
        record = traced.get(group.get("name"))
        if record is None:
            problems.append(f"{Path(assetinfo_file).name}: group {group.get('name')} has no trace record")
        elif record["rotation"] != rule.get("rotation") or record["translation"] != rule.get("translation"):
            problems.append(f"{Path(assetinfo_file).name}: group {group.get('name')} was traced with another rule")
    return problems


def uncovered_in_output(trace: ConversionTrace) -> List[str]:
    """Run both checks over everything the traced run wrote."""
    problems: List[str] = []
    for record in list(trace.prefabs.values()) + list(trace.scenes.values()):
        if Path(record["output_path"]).is_file():
            problems += uncovered_in_prefab(Path(record["output_path"]), record)
    for fbx_path in trace.fbx_files.values():
        assetinfo = Path(str(fbx_path) + ".assetinfo")
        if assetinfo.is_file():
            problems += uncovered_in_assetinfo(assetinfo, trace.assetinfos)
    return problems


# =============================================================================
# FBX FACTS
# What the file itself says, before any importer touches it.
# =============================================================================

def _read_fbx_records(fbx_path: Path) -> List[dict]:
    """The record tree of a binary FBX: ``[{name, props, children}, ...]``.
    Array payloads are skipped. Empty for a file that is not binary FBX."""
    try:
        data = Path(fbx_path).read_bytes()
    except OSError:
        return []
    if data[:21] != b"Kaydara FBX Binary  \x00":
        return []

    large = struct.unpack("<I", data[23:27])[0] >= 7500
    offset_format, offset_size = ("<Q", 8) if large else ("<I", 4)
    sentinel = 25 if large else 13
    scalar_formats = {"Y": ("<h", 2), "I": ("<i", 4), "F": ("<f", 4), "D": ("<d", 8), "L": ("<q", 8)}

    def read_properties(position: int, count: int):
        properties = []
        for _ in range(count):
            kind = chr(data[position]); position += 1
            if kind in scalar_formats:
                fmt, size = scalar_formats[kind]
                properties.append(struct.unpack(fmt, data[position:position + size])[0]); position += size
            elif kind == "C":
                properties.append(bool(data[position])); position += 1
            elif kind in "fdlib":
                _, _, compressed = struct.unpack("<III", data[position:position + 12])
                position += 12 + compressed
                properties.append(None)
            elif kind in "SR":
                length = struct.unpack("<I", data[position:position + 4])[0]; position += 4
                raw = data[position:position + length]; position += length
                properties.append(raw if kind == "R" else raw.decode("utf-8", "ignore"))
            else:
                raise ValueError(f"unknown FBX property type {kind!r}")
        return properties, position

    def read_record(position: int):
        end = struct.unpack(offset_format, data[position:position + offset_size])[0]; position += offset_size
        count = struct.unpack(offset_format, data[position:position + offset_size])[0]; position += offset_size
        position += offset_size
        name_length = data[position]; position += 1
        name = data[position:position + name_length].decode("utf-8", "ignore"); position += name_length
        if end == 0:
            return None, position
        properties, position = read_properties(position, count)
        children = []
        while position < end - sentinel:
            child, position = read_record(position)
            if child is None:
                break
            children.append(child)
        return {"name": name, "props": properties, "children": children}, end

    records, position = [], 27
    try:
        while position < len(data) - sentinel:
            record, position = read_record(position)
            if record is None:
                break
            records.append(record)
    except (ValueError, struct.error, IndexError):
        pass
    return records


def _properties70(record: dict, wanted) -> Dict[str, list]:
    """The numeric values of the named ``P`` entries of a record."""
    found: Dict[str, list] = {}
    for block in (c for c in record["children"] if c["name"] == "Properties70"):
        for entry in (c for c in block["children"] if c["name"] == "P"):
            if entry["props"] and entry["props"][0] in wanted:
                found[entry["props"][0]] = [
                    value for value in entry["props"][4:]
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
    return found


def _object_name(record: dict) -> str:
    label = next((p for p in record["props"] if isinstance(p, str)), "")
    return label.split("\x00\x01")[0].split("::")[0].strip()


def read_fbx_facts(fbx_path: Path) -> dict:
    """Raw facts of one binary FBX: version, global axis and unit settings,
    every Model node with its parent and transform properties (FBX units,
    Euler degrees), and every geometry's box in metres with the node it
    belongs to. ``{}`` for a file that cannot be read."""
    from integrated_asset_processor import _read_fbx_geometry_stats

    records = _read_fbx_records(fbx_path)
    if not records:
        return {}
    by_name = {record["name"]: record for record in records}
    objects = by_name.get("Objects", {"children": []})["children"]

    models = [r for r in objects if r["name"] == "Model"]
    geometries = [r for r in objects if r["name"] == "Geometry"]
    model_name = {r["props"][0]: _object_name(r) for r in models if r["props"]}

    # Connections "OO child parent": a model under a model, a geometry under a model.
    parent_of: Dict[int, int] = {}
    for link in by_name.get("Connections", {"children": []})["children"]:
        if len(link["props"]) >= 3 and link["props"][0] == "OO":
            parent_of.setdefault(link["props"][1], link["props"][2])

    nodes = {}
    for record in models:
        node_id = record["props"][0] if record["props"] else None
        nodes[_object_name(record)] = {
            "parent":     model_name.get(parent_of.get(node_id), ""),
            "properties": _properties70(record, FBX_NODE_PROPERTIES),
        }

    try:
        stats = _read_fbx_geometry_stats(Path(fbx_path))
    except Exception:
        stats = []
    geometry_facts = []
    for record, stat in zip(geometries, stats):
        geometry_id = record["props"][0] if record["props"] else None
        geometry_facts.append({
            "node": model_name.get(parent_of.get(geometry_id), ""),
            "stats_m": stat,
        })

    header = Path(fbx_path).read_bytes()[23:27]
    return {
        "version":         struct.unpack("<I", header)[0],
        "global_settings": _properties70(by_name.get("GlobalSettings", {"children": []}), FBX_GLOBAL_SETTINGS),
        "nodes":           nodes,
        "geometries":      geometry_facts,
    }
