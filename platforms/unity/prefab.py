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
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from platforms.unity.model_import import instance_object_id
from platforms.unity.scale_carry import carry_scales_down
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
      ``strip_lods``         — when True (default), Unity LODGroups are
                                collapsed to a single level on parse so
                                only ``lod_keep_level`` survives into
                                entity emission (see ``strip_lod_groups``).
                                O3DE selects LODs inside one model asset,
                                not via per-LOD entities, so keeping every
                                Unity LOD child renders them all at once.
      ``lod_keep_level``     — which LOD level to keep when stripping
                                (0 = LOD0, the highest detail).
      ``model_objects``      — given the guid a PrefabInstance names as its
                                source, the objects Unity makes of that model
                                file (``model_import.ModelObject`` list), or
                                None when the source is not a model. With it
                                an instance of a model becomes plain objects
                                (see ``add_model_instance``); without it such
                                an instance stays an empty object.

    The dataclass is immutable per-call — every parser invocation gets
    its own context bundle. The worker constructs one each time it
    enters its parser methods; standalone tooling can construct one
    inline."""
    log:                Callable[[str], None]
    coverage:           Any  # CoverageTracker; not type-imported to keep cycles out
    component_dispatch: Dict[str, Any]
    strip_lods:         bool = True
    lod_keep_level:     int = 0
    model_objects:      Optional[Callable[[str], Optional[list]]] = None


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
    # LOD stripping support: component fileID → owning GameObject fileID (for
    # every component, not just dispatched ones) and LODGroup fileID → its
    # per-level renderer fileID lists. LODGroup has no processor, so this is
    # the only place its data is retained.
    component_owner: Dict[str, str] = {}
    lod_groups: Dict[str, List[List[str]]] = {}
    # {component file id: its place in its object's m_Component list}.
    component_rank: Dict[str, int] = {}

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
                component_rank.update(component_ranks(doc['GameObject']))
                parse_game_object(ctx, doc['GameObject'], anchor,
                                  game_objects, transform_to_gameobject)
            elif 'PrefabInstance' in doc:
                # PrefabInstance blocks represent nested prefabs.
                parse_prefab_instance_in_prefab(ctx, doc['PrefabInstance'],
                                                anchor, game_objects,
                                                transform_to_gameobject)
            else:
                # Record component → owning-GO for LOD renderer resolution, and
                # capture LODGroup m_LODs renderer lists (LODGroup has no
                # processor, so its data would otherwise be discarded).
                for top_key, top_val in doc.items():
                    if not isinstance(top_val, dict):
                        continue
                    owner_id = str((top_val.get('m_GameObject') or {}).get('fileID', ''))
                    if owner_id:
                        component_owner[anchor] = owner_id
                    if top_key == 'LODGroup':
                        lod_groups[anchor] = _extract_lod_renderer_levels(top_val)

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

    # Build hierarchy and assign components, each object's in Unity's order.
    build_hierarchy(ctx, game_objects, transform_to_gameobject,
                    in_unity_order(components_data, component_rank))

    # Collapse Unity LODGroups so only the kept level survives into emission.
    if ctx.strip_lods and lod_groups:
        strip_lod_groups(ctx, game_objects, lod_groups, component_owner,
                         keep_level=ctx.lod_keep_level)

    # A scale that differs by axis reaches nothing below its entity in O3DE:
    # it is carried down to the objects below here (`scale_carry`).
    carry_scales_down(game_objects, getattr(ctx.coverage, "warn", None))

    return game_objects, transform_to_gameobject


# ---------------------------------------------------------------------------
# The order of an object's components
# ---------------------------------------------------------------------------

def component_ranks(go_data: Dict) -> Dict[str, int]:
    """``{component file id: its place}`` in a GameObject's ``m_Component``
    list: the order Unity shows an object's components in, and hands them
    out in. An entry is ``component: {fileID}``, or in files older than
    Unity 5.5 ``<class id>: {fileID}``."""
    ranks: Dict[str, int] = {}
    for place, entry in enumerate(go_data.get('m_Component') or []):
        reference = next(iter(entry.values()), None) if isinstance(entry, dict) else None
        if isinstance(reference, dict) and reference.get('fileID'):
            ranks[str(reference['fileID'])] = place
    return ranks


def in_unity_order(components_data: Dict, ranks: Dict[str, int]) -> Dict:
    """The parsed components, each object's in the order of its
    ``m_Component`` list.

    A file stores its documents in no order that means anything; Unity goes
    by the list. So the first collider of an object is the one Unity calls
    its first, and that decides which collider sits on the object's own
    entity and which get entities of their own. A component no list names
    (one added to an object of a nested prefab) keeps its place in the
    file, after the listed ones."""
    unlisted = len(ranks)
    return dict(sorted(components_data.items(), key=lambda item: ranks.get(item[0], unlisted)))


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
    game_objects[file_id].is_active = str(go_data.get('m_IsActive', 1)) != '0'


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

    # An instance of a model file is not an instance of a prefab: there is no
    # converted prefab to point at. It becomes the objects Unity makes of it.
    model = ctx.model_objects(prefab_guid) if ctx.model_objects else None
    if model:
        add_model_instance(ctx.log, instance_data, anchor, prefab_guid, model,
                           game_objects, transform_map)
        return

    modification         = instance_data.get('m_Modification', {})
    modifications        = modification.get('m_Modifications', []) or []
    added_components     = modification.get('m_AddedComponents', []) or []
    removed_components   = modification.get('m_RemovedComponents', []) or []
    added_gameobjects    = modification.get('m_AddedGameObjects', []) or []
    parent_transform     = modification.get('m_TransformParent', {}) or {}
    parent_id            = str(parent_transform.get('fileID', ''))

    # Project the transform overrides of the instance's own root onto a
    # Transform. Overrides that target an object inside the instance (a door
    # moved in its frame) are not the instance's: they stay in
    # modifications[] with all the others, for the emitter to handle.
    name     = 'PrefabInstance'
    position = [0.0, 0.0, 0.0]
    rotation = [0.0, 0.0, 0.0, 1.0]
    scale    = [1.0, 1.0, 1.0]
    TRANSFORM_AXIS = {'x': 0, 'y': 1, 'z': 2, 'w': 3}
    root_target = root_override_target(modifications)

    for mod in modifications:
        prop_path = mod.get('propertyPath', '') or ''
        value     = mod.get('value', 0)

        if prop_path == 'm_Name':
            name = str(value) if value else name
        elif not targets_root(mod, root_target):
            continue
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


# ---------------------------------------------------------------------------
# Which override is the instance's own
# ---------------------------------------------------------------------------

# Unity stores these seven for the root of every instance, changed or not.
_ROOT_OVERRIDES = frozenset(
    [f'm_LocalPosition.{axis}' for axis in 'xyz'] + [f'm_LocalRotation.{axis}' for axis in 'xyzw'])


def root_override_target(modifications: List[Dict]) -> Optional[str]:
    """The file id, in the source prefab, of the transform at the root of an
    instance, read off the instance's overrides.

    An override names the object it changes by that object's id in the source
    prefab. The root's position and rotation are always stored, all seven
    numbers; an object inside the instance has only what was changed. So the
    root is the target that carries all seven. Should several, the one that
    also carries ``m_RootOrder``, else the first listed. None when no target
    carries them all (then nothing tells the overrides apart)."""
    paths_of: Dict[str, set] = {}
    for mod in modifications:
        target = str((mod.get('target') or {}).get('fileID', ''))
        paths_of.setdefault(target, set()).add(str(mod.get('propertyPath', '') or ''))
    candidates = [target for target, paths in paths_of.items() if _ROOT_OVERRIDES <= paths]
    if not candidates:
        return None
    return next((target for target in candidates if 'm_RootOrder' in paths_of[target]), candidates[0])


def targets_root(mod: Dict, root_target: Optional[str]) -> bool:
    """Whether an override is on the instance's own root. With no root known
    every override counts as the root's, as before the two were told apart."""
    return root_target is None or str((mod.get('target') or {}).get('fileID', '')) == root_target


def lost_root(modifications: List[Dict], sidecar: Optional[Dict], prefab_guid: Optional[str]) -> bool:
    """Whether a placement's overrides name, as its root, a transform its
    prefab does not have: the prefab was rebuilt after the placement was
    saved. Unity drops an override that names nothing, so such a placement
    stands where the prefab's own root stands, not where its overrides say.

    ``sidecar`` is the prefab's entity map, whose ``transform_owners`` lists
    the prefab's transforms. Only a root named with the prefab's own guid is
    judged: an object the prefab takes from another file (a model, a nested
    prefab) is named by that file's guid and its id there."""
    root = root_override_target(modifications)
    known = (sidecar or {}).get("transform_owners") or {}
    if root is None or not known or root in known:
        return False
    guids = {str((mod.get('target') or {}).get('guid', '')) for mod in modifications
             if str((mod.get('target') or {}).get('fileID', '')) == root}
    return bool(prefab_guid) and guids == {prefab_guid}


def nested_prefabs_first(prefab_files: List[Path], guid_of: Callable[[Path], Optional[str]]) -> List[Path]:
    """The same prefab files, ordered so that a prefab comes after the ones
    it nests. A prefab that nests another needs the nested one's entity map
    to place its overrides, and that map exists once the nested prefab is
    converted. The given order is kept wherever nesting does not decide."""
    by_guid = {guid_of(path): path for path in prefab_files}
    nests: Dict[Path, List[Path]] = {}
    for path in prefab_files:
        try:
            text = Path(path).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            text = ''
        guids = re.findall(r'm_SourcePrefab:\s*\{fileID:\s*-?\d+,\s*guid:\s*(\w+)', text)
        nests[path] = [by_guid[guid] for guid in dict.fromkeys(guids) if guid in by_guid and by_guid[guid] != path]

    ordered: List[Path] = []
    state: Dict[Path, str] = {}

    def visit(path: Path) -> None:
        if state.get(path):
            return                      # done, or a loop back into a prefab being visited
        state[path] = 'visiting'
        for nested in nests[path]:
            visit(nested)
        state[path] = 'done'
        ordered.append(path)

    for path in prefab_files:
        visit(path)
    return ordered


# ---------------------------------------------------------------------------
# Instances of model files
# ---------------------------------------------------------------------------

_AXIS = {'x': 0, 'y': 1, 'z': 2, 'w': 3}

# Overrides every instance carries that say nothing the converter needs.
_OVERRIDES_WITHOUT_EFFECT = ('m_RootOrder', 'm_LocalEulerAnglesHint.')


def add_model_instance(log: Callable[[str], None],
                       instance_data: Dict, anchor: str, model_guid: str,
                       model: list,
                       game_objects: Dict, transform_map: Dict) -> None:
    """Add one instance of a model file (an FBX dropped into a prefab or a
    scene) as plain GameObjects: one per object Unity makes of the model,
    with the model's own transforms, meshes and materials, and the
    instance's overrides on top.

    Each object gets the id Unity gives it in the file that holds the
    instance (``instance_object_id``), so components and children the file
    adds to it attach by id like to any other object. An object whose id in
    the model is not known gets a made-up id; nothing can be added to it.

    ``model`` is what ``model_import.model_objects`` gives (root first,
    parents before children). Used by the prefab parser and by the scene
    converter alike."""
    modification = instance_data.get('m_Modification', {}) or {}
    parent_transform_id = str((modification.get('m_TransformParent') or {}).get('fileID', ''))

    # ---- One object per object of the model.
    made: List[GameObject] = []
    by_source_id: Dict[str, GameObject] = {}      # the model's own ids -> the object made
    for index, source in enumerate(model):
        file_id = (instance_object_id(anchor, source.game_object_id) if source.game_object_id
                   else f"{anchor}:{source.node or index}")
        go = GameObject(
            file_id=file_id,
            name=source.name,
            transform=Transform(tuple(source.position), tuple(source.rotation), tuple(source.scale)),
        )
        if source.mesh_file_id:
            go.mesh_guid      = model_guid
            go.mesh_file_id   = source.mesh_file_id
            go.material_guids = list(source.material_guids)
        if source.parent >= 0:
            go.parent_id = made[source.parent].file_id
            made[source.parent].model_children.append(file_id)
        elif parent_transform_id and parent_transform_id != '0':
            go.parent_id = parent_transform_id

        if source.game_object_id:
            by_source_id[source.game_object_id] = go
        if source.renderer_id:
            by_source_id[source.renderer_id] = go     # an override of its materials names the renderer
        if source.transform_id:
            by_source_id[source.transform_id] = go
            transform_map[instance_object_id(anchor, source.transform_id)] = file_id
        made.append(go)
        game_objects[file_id] = go

    # ---- The instance's overrides, each on the object it targets.
    renderers = [go for go in made if go.mesh_guid]
    modifications = modification.get('m_Modifications', []) or []
    skipped = 0
    for mod in modifications:
        target = by_source_id.get(str((mod.get('target') or {}).get('fileID', '')))
        if target is None and len(renderers) == 1 and str(mod.get('propertyPath', '')).startswith('m_Materials.'):
            target = renderers[0]     # the model's only renderer
        if target is None or not _apply_model_override(target, mod):
            skipped += 1

    log(
        f"  [ModelInstance] '{made[0].name}' src={model_guid[:8]}… "
        f"objects={len(made)}, overrides={len(modifications)} "
        f"({skipped} not applied)"
    )


def _apply_model_override(go: GameObject, mod: Dict) -> bool:
    """Apply one override of a model instance to the object it targets.
    False when the override is of a kind this does not carry over."""
    path  = str(mod.get('propertyPath', '') or '')
    value = mod.get('value', 0)
    field, _, axis = path.partition('.')

    if path == 'm_Name':
        go.name = str(value) if value else go.name
    elif field in ('m_LocalPosition', 'm_LocalRotation', 'm_LocalScale') and axis in _AXIS:
        attribute = {'m_LocalPosition': 'position', 'm_LocalRotation': 'rotation',
                     'm_LocalScale': 'scale'}[field]
        values = list(getattr(go.transform, attribute))
        if _AXIS[axis] >= len(values):
            return False
        values[_AXIS[axis]] = float(value)
        setattr(go.transform, attribute, tuple(values))
    elif path.startswith('m_Materials.Array.data['):
        slot = int(path[len('m_Materials.Array.data['):].rstrip(']'))
        guid = str((mod.get('objectReference') or {}).get('guid', '') or '')
        if not guid or slot > len(go.material_guids):
            return False
        go.material_guids[slot:slot + 1] = [guid]
    elif not path.startswith(_OVERRIDES_WITHOUT_EFFECT):
        return False
    return True


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

        # The objects of a model instance know their children by object id.
        go.children_ids += [child for child in go.model_children if child not in go.children_ids]

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
        go.component_ids[comp_type] = str(_comp_id)

        processor = ctx.component_dispatch.get(comp_type)
        if processor:
            ctx.log(f"  [Hierarchy] Parsing {comp_type} on '{go.name}'")
            processor.parse(comp_type, comp_data, go, ctx.log)
        else:
            ctx.log(f"  [Hierarchy] ⚠ No processor for component type '{comp_type}' — skipped")


# ---------------------------------------------------------------------------
# LOD stripping
# ---------------------------------------------------------------------------
# O3DE has no LODGroup component: LODs live inside a single model asset and are
# selected automatically by one MeshComponent (LodRule at import + the runtime
# LodConfiguration). Unity LODGroups instead are separate child GameObjects
# (LOD0/LOD1/…), each with its own renderer. Emitting every Unity LOD child as
# its own O3DE entity makes them all render simultaneously. Until the converter
# bakes LODs into a single model (LodRule path), the default behaviour is to
# collapse each LODGroup to a single level — see mem:lod_handling/lod_handling_plan.


def _extract_lod_renderer_levels(lod_group_data: Dict) -> List[List[str]]:
    """Return, per LOD level (LOD0 first), the renderer component FileIDs a
    Unity ``LODGroup``'s ``m_LODs`` references. Each renderer FileID points at
    a MeshRenderer component, not a GameObject — resolved to the owning GO by
    the caller via the ``component_owner`` map."""
    levels: List[List[str]] = []
    for lod in (lod_group_data.get('m_LODs') or []):
        renderer_fids: List[str] = []
        for entry in (lod.get('renderers') or []):
            fid = str((entry.get('renderer') or {}).get('fileID', ''))
            if fid and fid != '0':
                renderer_fids.append(fid)
        levels.append(renderer_fids)
    return levels


def _remove_go_subtree(game_objects: Dict[str, GameObject], go_id: str,
                       keep: set, log: Callable[[str], None]) -> int:
    """Remove ``go_id`` and all descendants from ``game_objects``, unlinking it
    from its parent's ``children_ids``. A GO in ``keep`` (a retained-LOD
    renderer GO) is never removed, so a kept entity nested under a dropped one
    survives. Returns the count of GameObjects removed."""
    go = game_objects.get(go_id)
    if go is None or go_id in keep:
        return 0

    parent = game_objects.get(go.parent_id) if go.parent_id else None
    if parent and go_id in parent.children_ids:
        parent.children_ids.remove(go_id)

    removed = 0
    for child_id in list(go.children_ids):
        removed += _remove_go_subtree(game_objects, child_id, keep, log)
    if game_objects.pop(go_id, None) is not None:
        removed += 1
    return removed


def strip_lod_groups(ctx: UnityParseContext,
                     game_objects: Dict[str, GameObject],
                     lod_groups: Dict[str, List[List[str]]],
                     component_owner: Dict[str, str],
                     keep_level: int = 0) -> None:
    """Collapse each parsed Unity LODGroup to a single LOD level, dropping the
    other levels' renderer GameObjects (and their subtrees) so they don't all
    emit as enabled O3DE entities.

    ``keep_level`` selects the surviving level (0 = LOD0, highest detail),
    clamped to the group's available levels. A renderer shared across levels is
    kept (keep wins over drop)."""
    for lod_go_id, levels in lod_groups.items():
        if not levels:
            continue
        keep_idx = max(0, min(keep_level, len(levels) - 1))

        keep_gos: set = set()
        drop_gos: set = set()
        for idx, renderer_fids in enumerate(levels):
            for rfid in renderer_fids:
                owner = component_owner.get(rfid)
                if not owner:
                    continue
                (keep_gos if idx == keep_idx else drop_gos).add(owner)
        drop_gos -= keep_gos

        removed = 0
        for go_id in drop_gos:
            removed += _remove_go_subtree(game_objects, go_id, keep_gos, ctx.log)

        ctx.log(f"  [LOD] LODGroup {lod_go_id}: kept LOD{keep_idx} "
                f"({len(keep_gos)} renderer GO), dropped {len(drop_gos)} "
                f"lower-LOD GO ({removed} entit{'y' if removed == 1 else 'ies'} "
                f"removed incl. subtrees)")


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
