"""
=============================================================================
UNITY PREFAB / SCENE PARSERS  (platforms.unity.prefab)
=============================================================================

Parse Unity ``.prefab`` and ``.unity`` files into the worker's source
scene-graph representation: a flat dict of ``GameObject`` instances
keyed by FileID anchor, plus a transform → GameObject id map for
hierarchy resolution.

This module holds the REAL implementations as free functions
accepting a ``UnityParseContext`` dataclass. The worker
(``IntegratedAssetProcessor``) keeps thin wrapper methods that build
a context and delegate, so existing call sites keep working.

Public surface (canonical entry points)::

    from platforms.unity.prefab import (
        UnityParseContext,
        parse_unity_prefab,
        parse_transform,
        parse_game_object,
        parse_prefab_instance_in_prefab,
        build_hierarchy,
        parse_unity_scene,
    )

Each free function takes the context as its first parameter. The
context bundles the worker-side state these parsers need
(``log``, ``coverage``, ``component_dispatch``); plugin authors
wiring custom parse paths construct their own context to call into
this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import yaml

from platforms.unity.types import GameObject, Transform


# ---------------------------------------------------------------------------
# Parse context
# ---------------------------------------------------------------------------

@dataclass
class UnityParseContext:
    """The shared state the Unity prefab parsers consume.

    Bundles the three pieces of state the parsers historically read
    from the worker via ``self.``:

      ``log``                — callback for one-line progress notes.
      ``coverage``           — CoverageTracker recording which component
                                types were seen (handled + unhandled).
      ``component_dispatch`` — ``{unity_type_name: ComponentProcessor}``
                                from the active platform plugin.

    The dataclass is immutable per-call — every parser invocation gets
    its own context bundle. The worker constructs one each time it
    enters its parser methods; standalone tooling can construct one
    inline."""
    log:                Callable[[str], None]
    coverage:           Any  # CoverageTracker; not type-imported to keep cycles out
    component_dispatch: Dict[str, Any]


# ---------------------------------------------------------------------------
# Top-level prefab walker
# ---------------------------------------------------------------------------

def parse_unity_prefab(ctx: UnityParseContext,
                      prefab_path: Path
                      ) -> Tuple[Dict[str, GameObject], Dict[str, str]]:
    """Parse a Unity ``.prefab`` file and return
    ``(game_objects, transform_to_gameobject_map)``.

    ``game_objects`` is keyed by GameObject FileID anchor.
    ``transform_to_gameobject_map`` resolves Transform FileIDs back
    to their owning GameObject's FileID — used by hierarchy
    resolution. Component data is stashed during the walk and
    dispatched through ``ctx.component_dispatch`` in the final
    ``build_hierarchy`` pass."""
    game_objects: Dict[str, GameObject] = {}
    components_data: Dict[str, Dict] = {}
    transform_to_gameobject: Dict[str, str] = {}

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
                parse_transform(ctx, doc['Transform'], anchor,
                                game_objects, transform_to_gameobject)
            elif 'GameObject' in doc:
                parse_game_object(ctx, doc['GameObject'], anchor,
                                  game_objects, transform_to_gameobject)
            elif 'PrefabInstance' in doc:
                # PrefabInstance blocks represent nested prefabs.
                parse_prefab_instance_in_prefab(ctx, doc['PrefabInstance'],
                                                anchor, game_objects,
                                                transform_to_gameobject)
            else:
                # Dispatch to registered component processors and record every
                # top-level key into coverage so the end-of-run report shows
                # both handled and unhandled component types.
                handled = False
                for known_type in ctx.component_dispatch:
                    if known_type in doc:
                        components_data[anchor] = {
                            'type': known_type,
                            'data': doc[known_type],
                        }
                        ctx.coverage.record_component(
                            known_type,
                            type(ctx.component_dispatch[known_type]).__name__,
                        )
                        handled = True
                        break
                if not handled:
                    for top_key in doc:
                        ctx.coverage.record_component(top_key, None)

        except yaml.YAMLError:
            continue

    # Build hierarchy and assign components.
    build_hierarchy(ctx, game_objects, transform_to_gameobject, components_data)

    return game_objects, transform_to_gameobject


# ---------------------------------------------------------------------------
# Per-document parsers
# ---------------------------------------------------------------------------

def parse_transform(ctx: UnityParseContext,
                    transform_data: Dict, anchor: str,
                    game_objects: Dict,
                    transform_map: Dict) -> None:
    """Parse a Unity Transform document. Pulls translation /
    rotation / scale + parent FileID, then stashes them onto the
    GameObject identified by ``m_GameObject.fileID``."""
    go_ref = transform_data.get('m_GameObject', {})
    go_file_id = str(go_ref.get('fileID', ''))

    if not go_file_id or go_file_id == '0':
        return

    transform_map[anchor] = go_file_id

    local_pos   = transform_data.get('m_LocalPosition', {'x': 0, 'y': 0, 'z': 0})
    local_rot   = transform_data.get('m_LocalRotation', {'x': 0, 'y': 0, 'z': 0, 'w': 1})
    local_scale = transform_data.get('m_LocalScale', {'x': 1, 'y': 1, 'z': 1})

    position = (float(local_pos.get('x', 0)),
                float(local_pos.get('y', 0)),
                float(local_pos.get('z', 0)))
    rotation = (float(local_rot.get('x', 0)),
                float(local_rot.get('y', 0)),
                float(local_rot.get('z', 0)),
                float(local_rot.get('w', 1)))
    scale    = (float(local_scale.get('x', 1)),
                float(local_scale.get('y', 1)),
                float(local_scale.get('z', 1)))

    transform = Transform(position, rotation, scale)

    if go_file_id not in game_objects:
        game_objects[go_file_id] = GameObject(
            file_id=go_file_id,
            name="",
            transform=transform,
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


def parse_game_object(ctx: UnityParseContext,
                     go_data: Dict, anchor: str,
                     game_objects: Dict,
                     transform_map: Dict) -> None:
    """Parse a Unity GameObject document. Re-keys the entity in
    ``game_objects`` from its Transform-derived placeholder id to the
    real GameObject FileID anchor."""
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
            transform=Transform(),
        )


def parse_prefab_instance_in_prefab(ctx: UnityParseContext,
                                    instance_data: Dict, anchor: str,
                                    game_objects: Dict,
                                    transform_map: Dict) -> None:
    """Parse a PrefabInstance block (a nested prefab reference inside
    a Unity prefab).

    Captures the FULL ``m_Modifications`` array verbatim onto the
    GameObject so downstream emission can dispatch overrides by
    ``propertyPath``. Also extracts ``m_AddedComponents``,
    ``m_RemovedComponents``, ``m_AddedGameObjects`` from the
    ``m_Modification`` block — these live alongside
    ``m_Modifications``, not inside it.

    Transform-related modifications are additionally projected onto
    a Transform so the converter's position/rotation/scale plumbing
    keeps working. All other overrides are left for
    ``_create_nested_prefab_instance`` to translate into O3DE JSON
    patches."""
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

    # Project transform-related overrides onto a Transform. All other
    # overrides stay in modifications[] for the emitter to handle.
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

    # Keep every override entry around for the emitter and the coverage
    # tracker.
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
    ctx.log(
        f"  [PrefabInstance] '{name}' src={prefab_guid[:8]}… "
        f"mods={len(modifications)} (transform+name handled, "
        f"{other_count} other), added_comp={len(added_components)}, "
        f"removed_comp={len(removed_components)}, "
        f"added_go={len(added_gameobjects)}"
    )
    # Don't add to transform_map since PrefabInstance doesn't have a
    # separate Transform component.


def build_hierarchy(ctx: UnityParseContext,
                   game_objects: Dict,
                   transform_map: Dict,
                   components_data: Dict) -> None:
    """Resolve parent-child relationships across the parsed
    GameObject dict, dispatch parsed components through
    ``ctx.component_dispatch``, and surface unhandled component types
    to ``ctx.coverage``."""
    # Resolve transform IDs to GameObject IDs.
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

    # Ensure parent-child relationships (bidirectional).
    for file_id, go in game_objects.items():
        # Forward: parent -> children.
        for child_id in go.children_ids:
            if child_id in game_objects:
                game_objects[child_id].parent_id = file_id

        # Reverse: child -> parent (add child to parent's children_ids
        # if not already there).
        if go.parent_id and go.parent_id in game_objects:
            parent_go = game_objects[go.parent_id]
            if file_id not in parent_go.children_ids:
                parent_go.children_ids.append(file_id)

    # Dispatch each component to its registered processor's parse() method.
    for _comp_id, comp_info in components_data.items():
        comp_type = comp_info.get('type')
        comp_data = comp_info.get('data', {})

        go_ref = comp_data.get('m_GameObject', {})
        go_id  = str(go_ref.get('fileID', ''))

        if go_id not in game_objects:
            ctx.log(f"  [Hierarchy] ⚠ Component '{comp_type}' references unknown GO id={go_id}")
            continue

        go = game_objects[go_id]

        processor = ctx.component_dispatch.get(comp_type)
        if processor:
            ctx.log(f"  [Hierarchy] Parsing {comp_type} on '{go.name}'")
            processor.parse(comp_type, comp_data, go, ctx.log)
        else:
            ctx.log(f"  [Hierarchy] ⚠ No processor for component type '{comp_type}' — skipped")


# ---------------------------------------------------------------------------
# Scene parsing (placeholder — see item 3 in the follow-ups)
# ---------------------------------------------------------------------------

def parse_unity_scene(ctx: UnityParseContext, scene_path: Path
                      ) -> Tuple[Dict[str, GameObject], Dict[str, str]]:
    """Parse a Unity ``.unity`` scene file into the same scene-graph
    shape ``parse_unity_prefab`` produces.

    Unity scene files use the same multi-document YAML format as
    prefabs — ``Transform`` / ``GameObject`` / ``PrefabInstance``
    documents followed by component blocks. ``parse_unity_prefab``
    handles all those document kinds, so the scene walker IS the
    prefab walker.

    Semantic note: ``platforms.unity.scene_converter.UnitySceneConverter``
    deliberately keeps its own parser for Stage-2 level emission
    because scene-level ``PrefabInstance`` blocks have different
    semantics from prefab-nested ones. In a prefab, a PrefabInstance
    is a nested prefab reference and becomes a regular GameObject
    in ``game_objects``. In a scene, a PrefabInstance is a top-level
    placement and goes into a separate ``prefab_instances`` list that
    drives the level's ``Instances`` map directly. The two emission
    paths diverge; the parsers consequently do too. This function is
    the canonical scene parser for new code reaching for the platform
    plugin contract (which treats both PrefabInstance flavours
    uniformly as nested references)."""
    return parse_unity_prefab(ctx, scene_path)
