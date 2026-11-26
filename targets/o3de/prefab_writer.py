"""
=============================================================================
O3DE PREFAB JSON WRITERS  (targets.o3de.prefab_writer)
=============================================================================

Construct O3DE ``.prefab`` JSON content from parsed source data. Plus
a ``<prefab>.entitymap.json`` sidecar record stashed on the worker for
nested-instance override propagation.

Public surface (canonical entry points)::

    from targets.o3de.prefab_writer import (
        create_o3de_prefab,
        create_container_entity,
        create_nested_prefab_instance,
        create_entity_recursive,
        make_bare_entity,
        generate_component_id,
        generate_entity_id,
        quaternion_to_euler,
        convert_to_o3de_coordinates,
        write_entity_map_sidecar,
        load_entity_map_sidecar,
    )

Each function takes the worker (``IntegratedAssetProcessor``) as its
first argument. The worker carries the state the writers need —
``log``, ``coverage``, ``asset_db``, ``asset_index``,
``asset_hint_root``, ``entity_id_counter``, ``component_processors``,
``_project_prefab_records``, ``_entity_map_cache``, ``stats``,
``platform``. Functions that don't actually use the worker
(``quaternion_to_euler``) accept it anyway for signature consistency
— the parameter is documented as optional in those cases.

These bodies were previously methods on
``IntegratedAssetProcessor``; the class now carries thin wrappers
that build a context and delegate. Behaviour is byte-identical to
the pre-extraction code path.
"""

from __future__ import annotations

import json
import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from platforms.unity.components.base import ProcessingContext
from platforms.unity.types import GameObject, Transform


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------

def generate_component_id(worker) -> int:  # noqa: ARG001
    """Random O3DE component-id in the 16-digit range. The worker
    parameter is accepted for signature consistency with the rest of
    the writer family but isn't consulted."""
    return random.randint(1000000000000000, 9999999999999999)


def generate_entity_id(worker) -> str:
    """Return the next ``Entity_[N]`` id string and bump the worker's
    counter so subsequent calls are unique within a run."""
    worker.entity_id_counter += 1
    return f"Entity_[{worker.entity_id_counter}]"


# ---------------------------------------------------------------------------
# Quaternion / coordinate helpers
# ---------------------------------------------------------------------------

def quaternion_to_euler(quaternion: Tuple[float, float, float, float]) -> List[float]:
    """Convert quaternion ``[x, y, z, w]`` to the Euler angles, in degrees,
    that O3DE turns back into the same rotation. Pure function.

    O3DE builds a rotation from the ``Rotate`` field of a transform as
    ``rot = rotx * roty * rotz`` (``AZ::Quaternion::SetFromEulerRadians``).
    The angles are therefore read off the matrix ``Rx(a) * Ry(b) * Rz(c)``:

        R[0][2] =  sin(b)
        R[1][2] = -sin(a) cos(b)      R[2][2] = cos(a) cos(b)
        R[0][1] = -cos(b) sin(c)      R[0][0] = cos(b) cos(c)

    Any other order gives angles that are right for a turn about one axis
    and wrong as soon as two axes are involved."""
    x, y, z, w = quaternion

    r00 = 1 - 2 * (y * y + z * z)
    r01 = 2 * (x * y - z * w)
    r02 = 2 * (x * z + y * w)
    r12 = 2 * (y * z - x * w)
    r22 = 1 - 2 * (x * x + y * y)

    if abs(r02) < 0.999999:
        angle_x = math.atan2(-r12, r22)
        angle_y = math.asin(r02)
        angle_z = math.atan2(-r01, r00)
    else:
        # Looking straight along X: X and Z turn about the same line.
        # Put the whole of that turn on X.
        r11 = 1 - 2 * (x * x + z * z)
        r21 = 2 * (y * z + x * w)
        angle_x = math.atan2(r21, r11)
        angle_y = math.copysign(math.pi / 2, r02)
        angle_z = 0.0

    return [math.degrees(angle_x), math.degrees(angle_y), math.degrees(angle_z)]


def convert_to_o3de_coordinates(unity_transform: Transform
                                 ) -> Tuple[Transform, bool]:
    """Convert a Unity transform (Y-up, LH) to O3DE space (Z-up, RH).
    Returns ``(converted_transform, scale_was_non_uniform_flag)``.

    A Unity point ``(x, y, z)`` is the O3DE point ``(x, z, y)``. That swap
    is a mirror, and a mirror turns a rotation about an axis into the
    opposite rotation about the mirrored axis: the quaternion
    ``(x, y, z, w)`` becomes ``(-x, -z, -y, w)``. Swapping the components
    without the sign gives the inverse rotation, which is right only for
    no turn and for a half turn."""
    o3de_pos   = (unity_transform.position[0],
                  unity_transform.position[2],
                  unity_transform.position[1])
    qx, qy, qz, qw = unity_transform.rotation
    o3de_rot   = (-qx, -qz, -qy, qw)
    o3de_scale = (unity_transform.scale[0],
                  unity_transform.scale[2],
                  unity_transform.scale[1])
    converted = Transform(o3de_pos, o3de_rot, o3de_scale)
    return converted, not converted.is_uniform_scale()


def non_uniform_scale_component(component_id: int, scale) -> Dict:
    """An ``EditorNonUniformScaleComponent`` holding ``scale`` (O3DE axes).
    The engine reads the scale from ``NonUniformScale``
    (``EditorNonUniformScaleComponent::Reflect``); under any other key the
    component loads with a scale of one."""
    return {
        "$type": "EditorNonUniformScaleComponent",
        "Id": component_id,
        "NonUniformScale": [float(value) for value in scale],
    }


def gradient_gi_component(component_id: int, high, mid, low) -> Dict:
    """An ``EditorGradientGIComponent``: the level's ambient light as a
    gradient of three linear colours ``(r, g, b)`` - straight up, at the
    horizon, straight down.

    The component is the engine's "Gradient GI (IBL)"
    (``AtomLyIntegration/CommonFeatures/GradientGI``). It writes the colours
    as they are into a floating-point cubemap, so they are linear light. A
    level takes one: it shares a service with the Global Skylight (IBL)
    component and with itself, and the newest one wins."""
    def colour(rgb) -> List[float]:
        return [float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0]

    return {
        "$type": "{B2C3D4E5-F6A7-8901-BCDE-F12345678901} AZ::Render::EditorGradientGIComponent",
        "Id": component_id,
        "Controller": {
            "Configuration": {
                "HighColor": colour(high),
                "MidColor":  colour(mid),
                "LowColor":  colour(low),
            }
        },
    }


# ---------------------------------------------------------------------------
# Top-level prefab construction
# ---------------------------------------------------------------------------

def create_o3de_prefab(worker, root_go: GameObject, all_game_objects: Dict,
                       transform_map: Dict, material_mapping: Dict,
                       mesh_mapping: Dict,
                       fbx_material_labels: Dict[str, List[str]],
                       output_path: Path,
                       collider_pxmesh_mapping: Dict = None,
                       collision_config_mapping: Dict = None) -> None:
    """Write an O3DE ``.prefab`` JSON file + its
    ``.entitymap.json`` sidecar from a parsed source scene-graph
    rooted at ``root_go``."""
    # Stashed on the worker so the per-entity ProcessingContext (built deep in
    # create_entity_recursive from worker.*) can read it without threading the
    # map through every recursive signature. {(guid, fileID): .pxmesh hint}.
    worker._collider_pxmesh_mapping = collider_pxmesh_mapping or {}
    # F-Collision: {file_id: {"layer": int|None, "group": uuid|None}} stamped
    # onto each collider's ColliderConfiguration. Same stash pattern.
    worker._collision_config_mapping = collision_config_mapping or {}
    # ContainerEntity uses the root GameObject's name.
    prefab_data = {
        "ContainerEntity": create_container_entity(worker, root_go),
        "Entities": {},
        "Instances": {},
    }

    entity_id_map: Dict[str, str] = {}

    # Find the actual root GameObject (should only be one with parent_id = None).
    root_entities = [go for go in all_game_objects.values() if go.parent_id is None]

    if not root_entities:
        worker.log("  ⚠ No root GameObject found")
        return

    if len(root_entities) > 1:
        worker.log(f"  ⚠ Multiple root GameObjects found ({len(root_entities)}), using first one")

    root_entity = root_entities[0]

    # Create the root entity with ContainerEntity as parent.
    root_entity_id = create_entity_recursive(
        worker, root_entity, all_game_objects, prefab_data["Entities"],
        prefab_data["Instances"], entity_id_map, material_mapping, mesh_mapping,
        fbx_material_labels,
        parent_entity_id="ContainerEntity",
    )

    # Set child order in ContainerEntity.
    if root_entity_id:
        prefab_data["ContainerEntity"]["Components"]["EditorEntitySortComponent"]["Child Entity Order"] = [root_entity_id]

    with open(output_path, 'w') as f:
        json.dump(prefab_data, f, indent=4)

    # Write the sidecar entity map. Anything that overrides a child of
    # this prefab from a parent prefab needs to translate Unity fileIDs
    # into the O3DE entity aliases used above.
    write_entity_map_sidecar(
        worker, output_path, root_entity, all_game_objects, entity_id_map,
        fbx_material_labels,
        transform_map=transform_map,
    )


# ---------------------------------------------------------------------------
# Entity-map sidecar (per-prefab record stashed on the worker)
# ---------------------------------------------------------------------------

def write_entity_map_sidecar(worker,
                              prefab_output_path: Path,
                              root_go: GameObject,
                              all_game_objects: Dict,
                              entity_id_map: Dict[str, str],
                              fbx_material_labels: Dict[str, List[str]],
                              transform_map: Optional[Dict[str, str]] = None) -> None:
    """Build the per-prefab entity-map record and stash it on the worker.

    Two storage locations:
      1. ``worker._project_prefab_records[guid_or_stem]`` — persisted to
         the project file at end-of-run via ``to_outputs()``.
      2. ``worker._entity_map_cache[source_path]`` — used during the
         SAME run by override propagation to translate Unity fileIDs
         into O3DE entity aliases when a consumer prefab nests this one.

    Replaces the old ``<output>/.ImporterData/<stem>.entitymap.json``
    sidecar file. See the worker's earlier docstring for the schema."""
    # Recover the source Unity prefab path/guid from output_path.stem
    # (the converter writes outputs named after the source prefab's stem).
    source_path: Optional[Path] = None
    source_guid: Optional[str]  = None
    for guid, path in worker.asset_db.guid_to_path.items():
        if path.suffix == '.prefab' and path.stem == prefab_output_path.stem:
            source_path = path
            source_guid = guid
            break

    if source_guid:
        worker.asset_index["prefabs"][source_guid] = str(source_path) if source_path else ""

    material_slots = {
        go.file_id: list(go.material_guids)
        for go in all_game_objects.values()
        if go.material_guids
    }
    material_slot_labels = {
        file_id: list(labels)
        for file_id, labels in fbx_material_labels.items()
        if labels
    }
    go_names = {
        go.file_id: go.name for go in all_game_objects.values() if go.name
    }

    try:
        output_rel = str(prefab_output_path.relative_to(worker.output_root)).replace("\\", "/")
    except Exception:
        output_rel = prefab_output_path.name

    record = {
        "source_guid":          source_guid or "",
        "source_path":          str(source_path) if source_path else "",
        "output_path":          output_rel,
        "root_entity":          entity_id_map.get(root_go.file_id, ""),
        "container_alias":      "ContainerEntity",
        "entity_aliases":       dict(entity_id_map),
        # {Unity Transform file id: its GameObject's file id}. An override on
        # an object's transform names the transform, not the object.
        "transform_owners":     {str(transform_id): str(owner)
                                 for transform_id, owner in (transform_map or {}).items()
                                 if str(owner) in entity_id_map},
        "material_slots":       material_slots,
        "material_slot_labels": material_slot_labels,
        "go_names":             go_names,
        "written_at":           datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Project-outputs map keyed by GUID where available, else by stem.
    outputs_key = source_guid or f"path:{prefab_output_path.stem}"
    worker._project_prefab_records[outputs_key] = record

    # In-memory cache keyed by source path for cross-prefab reads.
    if source_path:
        worker._entity_map_cache[str(source_path)] = record

    worker.log(f"  ✓ Recorded entity map for {prefab_output_path.stem} "
                f"(guid={source_guid or 'n/a'})")


def load_entity_map_sidecar(worker, source_prefab_path: Path) -> Optional[Dict]:
    """Return the entity-map record for the given Unity source prefab,
    or None if it hasn't been processed in the current run. Reads from
    the worker's in-memory cache populated by
    ``write_entity_map_sidecar``."""
    return worker._entity_map_cache.get(str(source_prefab_path))


# ---------------------------------------------------------------------------
# Container + nested-instance + bare-entity emitters
# ---------------------------------------------------------------------------

def create_container_entity(worker, root_go: GameObject) -> Dict:
    """Build the prefab's top-level ContainerEntity dict from
    ``root_go``.

    The wrapper is emitted editor-only by default (stripped/dissolved at
    runtime); the Meshes tab's ``mesh_processor.prefab_wrapper_editor_only``
    toggle can turn that off so the container survives into the game."""
    mesh_settings = getattr(worker, "_mesh_settings", None) or {}
    editor_only = bool(mesh_settings.get("prefab_wrapper_editor_only", True))
    return {
        "Id":   "ContainerEntity",
        "Name": root_go.name,
        "Components": {
            "EditorDisabledCompositionComponent": {
                "$type": "EditorDisabledCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorEntityIconComponent": {
                "$type": "EditorEntityIconComponent",
                "Id": generate_component_id(worker),
            },
            "EditorEntitySortComponent": {
                "$type": "EditorEntitySortComponent",
                "Id": generate_component_id(worker),
                "Child Entity Order": [],
            },
            "EditorInspectorComponent": {
                "$type": "EditorInspectorComponent",
                "Id": generate_component_id(worker),
            },
            "EditorLockComponent": {
                "$type": "EditorLockComponent",
                "Id": generate_component_id(worker),
            },
            "EditorOnlyEntityComponent": {
                "$type": "EditorOnlyEntityComponent",
                "Id": generate_component_id(worker),
                "IsEditorOnly": editor_only,
            },
            "EditorPendingCompositionComponent": {
                "$type": "EditorPendingCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorPrefabComponent": {
                "$type": "EditorPrefabComponent",
                "Id": generate_component_id(worker),
            },
            "EditorVisibilityComponent": {
                "$type": "EditorVisibilityComponent",
                "Id": generate_component_id(worker),
            },
            "TransformComponent": {
                "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
                "Id": generate_component_id(worker),
                "Parent Entity": "",
            },
        },
    }


def create_nested_prefab_instance(worker, go: GameObject, prefab_path: Path,
                                   parent_entity_id: str) -> Dict:
    """Emit a nested-prefab Instance entry with JSON-patch overrides.

    Tier 1 = Transform (translate/rotate/scale on ContainerEntity).
    Tier 2 = m_IsActive (logged as unhandled — path TBD).
    Tier 3 = m_Materials.Array.data[N] (patch the assetHint inside
              the target entity's EditorMaterialComponent
              materialsByLabel entry — label key = FBX-internal
              material name at slot N).

    Source path is computed by walking up from ``prefab_path`` looking
    for the O3DE project root (``project.json``) and returning the
    file's project-relative path with original case. The pre-2026-05-31
    formula (``{asset_hint_root}/prefabs/<name>``) coupled the Source
    path to the lowercased asset-hint root, which worked on Windows by
    accident (case-insensitive FS) and broke on Linux/macOS."""
    from integrated_asset_processor import _project_relative_path
    # ``prefab_path`` is the Unity source file. The Source of an instance
    # names the CONVERTED prefab, where this run writes it. The engine wants
    # one prefab named by one string wherever it is nested, so this must be
    # the spelling the scene converter uses for the same file: its path from
    # the O3DE project root, case kept.
    converted_prefab = worker.prefabs_dir / prefab_path.name
    rel = _project_relative_path(converted_prefab)
    source_path = rel if rel else f"{worker.asset_hint_root}/prefabs/{prefab_path.name}"
    o3de_transform, _ = convert_to_o3de_coordinates(go.transform)
    euler             = quaternion_to_euler(o3de_transform.rotation)

    # PARENT RE-PARENT (always emitted).
    patches: List[Dict] = [
        {
            "op":    "replace",
            "path":  "/ContainerEntity/Components/TransformComponent/Parent Entity",
            "value": f"../{parent_entity_id}",
        }
    ]

    # TIER 1 — Transform overrides on the ContainerEntity.
    if any(abs(v) > 0.0001 for v in o3de_transform.position):
        for i, axis_val in enumerate(o3de_transform.position):
            patches.append({
                "op":    "replace",
                "path":  f"/ContainerEntity/Components/TransformComponent/Transform Data/Translate/{i}",
                "value": axis_val,
            })

    if any(abs(v) > 0.0001 for v in euler):
        for i, axis_val in enumerate(euler):
            patches.append({
                "op":    "replace",
                "path":  f"/ContainerEntity/Components/TransformComponent/Transform Data/Rotate/{i}",
                "value": axis_val,
            })

    # Scale: uniform → scalar patch on the container; non-uniform → a
    # component on the instance's root entity (below, once its alias is known).
    sx, sy, sz = o3de_transform.scale
    non_uniform = False
    if abs(sx - 1.0) > 0.0001 and abs(sx - sy) < 0.0001 and abs(sy - sz) < 0.0001:
        patches.append({
            "op":    "replace",
            "path":  "/ContainerEntity/Components/TransformComponent/Transform Data/Scale",
            "value": sx,
        })
    elif (abs(sx - 1.0) > 0.0001 or abs(sy - 1.0) > 0.0001 or abs(sz - 1.0) > 0.0001):
        non_uniform = True

    # TIER 2 + TIER 3 — walk modifications by propertyPath.
    sidecar = load_entity_map_sidecar(worker, prefab_path)
    if non_uniform:
        patches += instance_non_uniform_scale_patches(
            (sx, sy, sz), sidecar, generate_component_id(worker), go.name, worker.coverage.warn)
    entity_aliases = (sidecar or {}).get("entity_aliases", {})
    material_slot_labels = (sidecar or {}).get("material_slot_labels", {})

    if go.prefab_modifications and not sidecar:
        worker.coverage.warn(
            f"No entity-map sidecar for source prefab '{prefab_path.name}' — "
            f"non-transform overrides on nested instance '{go.name}' cannot be targeted."
        )

    # Transform overrides on objects inside the instance.
    patches += child_transform_patches(go.prefab_modifications, sidecar, go.name, worker.coverage.warn)

    # Material-slot overrides arrive as multiple property entries on the
    # same target. Collect them first to know the slot count per target.
    material_overrides: Dict[str, Dict[int, str]] = {}

    for mod in go.prefab_modifications:
        prop_path = (mod.get('propertyPath') or '').strip()
        value     = mod.get('value', None)
        objref    = mod.get('objectReference') or {}
        target    = mod.get('target') or {}
        target_id = str(target.get('fileID', ''))

        # Transform/name overrides were already projected onto go.transform / go.name
        # and emitted above. Mark them as handled in the coverage tracker.
        if prop_path == 'm_Name' or prop_path.startswith(
            ('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.')
        ):
            worker.coverage.record_modification(prop_path, handled=True, example_value=value)
            continue

        # --- Tier 2: m_IsActive (on the GameObject) ---
        if prop_path == 'm_IsActive':
            worker.coverage.record_modification(
                prop_path, handled=False, example_value=value
            )
            worker.coverage.warn(
                f"m_IsActive override on nested instance '{go.name}' (value={value}) "
                f"not emitted — O3DE disabled-entity patch path needs confirmation."
            )
            continue

        # --- Tier 3: material slot override ---
        m = re.match(r'^m_Materials\.Array\.data\[(\d+)\]$', prop_path)
        if m:
            slot_idx = int(m.group(1))
            new_guid = objref.get('guid', '') if isinstance(objref, dict) else ''
            if not new_guid:
                worker.coverage.record_modification(prop_path, handled=False,
                                                     example_value="<no guid>")
                continue
            slot_map = material_overrides.setdefault(target_id, {})
            slot_map[slot_idx] = new_guid
            continue

        # Catch-all: unhandled override.
        worker.coverage.record_modification(
            prop_path, handled=False,
            example_value=value if value not in (None, '') else objref,
        )

    # Emit material slot patches now that we have all slots per target.
    for target_id, slot_map in material_overrides.items():
        entity_alias = entity_aliases.get(target_id)
        if not entity_alias:
            worker.coverage.warn(
                f"Material override on nested instance '{go.name}' targets "
                f"fileID={target_id} which is not in the source's entity map "
                f"— renderer-component fileIDs aren't recorded yet. Skipped."
            )
            for slot_idx, mat_guid in slot_map.items():
                worker.coverage.record_modification(
                    f'm_Materials.Array.data[{slot_idx}]',
                    handled=False, example_value=mat_guid,
                )
            continue

        slot_labels = material_slot_labels.get(target_id, []) or []

        for slot_idx, mat_guid in slot_map.items():
            asset_hint = worker.asset_index["materials"].get(mat_guid)
            if not asset_hint:
                asset_hint = worker._process_material(mat_guid)
            if not asset_hint:
                worker.coverage.record_missing_material(mat_guid)
                worker.coverage.record_modification(
                    f'm_Materials.Array.data[{slot_idx}]',
                    handled=False, example_value=mat_guid,
                )
                continue

            label = (slot_labels[slot_idx]
                     if slot_idx < len(slot_labels) else '')

            if not label:
                worker.coverage.warn(
                    f"Material override on nested instance '{go.name}' "
                    f"slot {slot_idx} — no FBX-internal label recorded "
                    f"in sidecar (source prefab predates the label "
                    f"refactor, or FBX parse failed at emit time). "
                    f"Patch skipped — re-convert the source prefab to fix."
                )
                worker.coverage.record_modification(
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
            worker.coverage.record_modification(
                f'm_Materials.Array.data[{slot_idx}]',
                handled=True, example_value=asset_hint,
            )

    # Sibling fields (added / removed / added GOs) — record and skip.
    for _ in go.prefab_added_components:    worker.coverage.record_added_component()
    for _ in go.prefab_removed_components:  worker.coverage.record_removed_component()
    for _ in go.prefab_added_gameobjects:   worker.coverage.record_added_gameobject()
    if (go.prefab_added_components or go.prefab_removed_components
            or go.prefab_added_gameobjects):
        worker.coverage.warn(
            f"Nested instance '{go.name}' has added/removed components or "
            f"added GameObjects that are not yet propagated to O3DE patches."
        )

    return {
        "Source":  source_path,
        "Patches": patches,
    }


def instance_non_uniform_scale_patches(scale, sidecar: Optional[Dict], component_id: int,
                                       instance_name: str, warn) -> List[Dict]:
    """The patch that gives a nested instance a non-uniform scale (O3DE
    axes): an ``EditorNonUniformScaleComponent`` added to the instance's
    root entity.

    The container entity cannot carry it: the engine applies a non-uniform
    scale to an entity's own mesh and shapes and passes nothing down. On the
    root entity it scales what the root shows, which is the whole of a
    prefab made of one object. For a prefab with more objects the ones below
    the root keep their size and place, and that is reported."""
    root_alias = (sidecar or {}).get("root_entity")
    if not root_alias:
        warn(f"Non-uniform scale on nested instance '{instance_name}' {tuple(scale)} not emitted — "
             f"the source prefab's entity map is not known.")
        return []
    if len((sidecar or {}).get("entity_aliases") or {}) > 1:
        warn(f"Non-uniform scale on nested instance '{instance_name}' {tuple(scale)} is set on its root "
             f"only: O3DE does not pass a non-uniform scale down, so the objects below the root keep "
             f"their size and place.")
    return [{
        "op":    "add",
        "path":  f"/Entities/{root_alias}/Components/EditorNonUniformScaleComponent",
        "value": non_uniform_scale_component(component_id, scale),
    }]


def child_transform_patches(modifications: List[Dict], sidecar: Optional[Dict],
                            instance_name: str, warn) -> List[Dict]:
    """The patches for an instance's transform overrides that target an
    object *inside* it (a door moved in its frame), not the instance itself.

    ``sidecar`` is the source prefab's entity map: it says which entity was
    made of the object that owns the targeted transform. A position is
    patched one axis at a time (Unity ``x, y, z`` is O3DE ``x, z, y``); every
    entity is written with a ``Translate``, so the path exists. A rotation
    can only be set whole, so it needs all four numbers of the override; a
    scale is set when it is the same on all three axes. What cannot be
    placed is reported through ``warn``."""
    from platforms.unity.prefab import root_override_target

    root_target = root_override_target(modifications)
    if root_target is None:
        return []           # nothing tells the instance's overrides from its objects'

    values_of: Dict[str, Dict[str, float]] = {}
    for mod in modifications:
        path   = str(mod.get('propertyPath', '') or '')
        target = str((mod.get('target') or {}).get('fileID', ''))
        if target != root_target and path.startswith(('m_LocalPosition.', 'm_LocalRotation.', 'm_LocalScale.')):
            try:
                values_of.setdefault(target, {})[path] = float(mod.get('value'))
            except (TypeError, ValueError):
                continue

    owners  = (sidecar or {}).get("transform_owners", {})
    aliases = (sidecar or {}).get("entity_aliases", {})
    patches: List[Dict] = []
    for target, values in values_of.items():
        alias = aliases.get(owners.get(target, ""))
        if not alias:
            warn(f"Transform override on an object inside nested instance '{instance_name}' "
                 f"(transform fileID={target}) not emitted — the source prefab's entity map "
                 f"does not hold that object.")
            continue
        base = f"/Entities/{alias}/Components/TransformComponent/Transform Data"

        for axis, index in (("x", 0), ("y", 2), ("z", 1)):
            if f"m_LocalPosition.{axis}" in values:
                patches.append({"op": "replace", "path": f"{base}/Translate/{index}",
                                "value": values[f"m_LocalPosition.{axis}"]})

        rotation = [values.get(f"m_LocalRotation.{axis}") for axis in "xyzw"]
        if all(value is not None for value in rotation):
            converted, _ = convert_to_o3de_coordinates(Transform(rotation=tuple(rotation)))
            patches.append({"op": "add", "path": f"{base}/Rotate",
                            "value": quaternion_to_euler(converted.rotation)})
        elif any(value is not None for value in rotation):
            warn(f"Rotation override on an object inside nested instance '{instance_name}' "
                 f"holds only part of the rotation — not emitted.")

        scale = [values.get(f"m_LocalScale.{axis}") for axis in "xyz"]
        if all(value is not None for value in scale) and max(scale) - min(scale) < 0.0001:
            patches.append({"op": "add", "path": f"{base}/Scale", "value": scale[0]})
        elif any(value is not None for value in scale):
            warn(f"Scale override on an object inside nested instance '{instance_name}' "
                 f"is not one scale for all axes — not emitted.")
    return patches


def make_bare_entity(worker, entity_id: str, name: str,
                      parent_entity_id: str) -> Dict:
    """Create a minimal O3DE entity (for child collider entities)."""
    return {
        "Id":   entity_id,
        "Name": name,
        "Components": {
            "TransformComponent": {
                "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
                "Id": generate_component_id(worker),
                "Parent Entity": parent_entity_id,
            },
            "EditorDisabledCompositionComponent": {
                "$type": "EditorDisabledCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorEntityIconComponent": {
                "$type": "EditorEntityIconComponent",
                "Id": generate_component_id(worker),
            },
            "EditorInspectorComponent": {
                "$type": "EditorInspectorComponent",
                "Id": generate_component_id(worker),
            },
            "EditorLockComponent": {
                "$type": "EditorLockComponent",
                "Id": generate_component_id(worker),
            },
            "EditorOnlyEntityComponent": {
                "$type": "EditorOnlyEntityComponent",
                "Id": generate_component_id(worker),
            },
            "EditorPendingCompositionComponent": {
                "$type": "EditorPendingCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorVisibilityComponent": {
                "$type": "EditorVisibilityComponent",
                "Id": generate_component_id(worker),
            },
        },
    }


# ---------------------------------------------------------------------------
# Recursive entity walker
# ---------------------------------------------------------------------------

def create_entity_recursive(worker, go: GameObject, all_game_objects: Dict,
                             entities_dict: Dict, instances_dict: Dict,
                             entity_id_map: Dict,
                             material_mapping: Dict, mesh_mapping: Dict,
                             fbx_material_labels: Dict[str, List[str]],
                             parent_entity_id: str = None) -> str:
    """Recursively create entities or instances in JSON format."""
    # Check if this is a prefab instance.
    if go.is_prefab_instance and go.prefab_source_guid:
        instance_id = f"Instance_[{worker.entity_id_counter}]"
        worker.entity_id_counter += 1

        # Find the prefab file for this GUID.
        prefab_path = worker.asset_db.resolve_guid(go.prefab_source_guid)
        if prefab_path and prefab_path.suffix == '.prefab':
            # Create instance entry.
            instances_dict[instance_id] = create_nested_prefab_instance(
                worker, go, prefab_path, parent_entity_id,
            )
            if getattr(worker, "trace", None) is not None:
                worker.trace.record_instance(go, instance_id, prefab_path,
                                             instances_dict[instance_id])
            return f"{instance_id}/ContainerEntity"
        # If we can't find the prefab, fall through to create regular entity.

    entity_id = generate_entity_id(worker)
    entity_id_map[go.file_id] = entity_id

    o3de_transform, needs_nonuniform = convert_to_o3de_coordinates(go.transform)

    # Use provided parent_entity_id or look up from entity_id_map.
    if parent_entity_id is None:
        if go.parent_id and go.parent_id in entity_id_map:
            parent_entity_id = entity_id_map[go.parent_id]
        else:
            parent_entity_id = ""

    # Unity prefab roots carry dead transform data. See the original
    # method comment for full reasoning — when this entity is the
    # prefab's root (parent is ContainerEntity), force identity.
    is_prefab_root = (parent_entity_id == "ContainerEntity")
    transform_rule = "axis_swap"        # for the conversion trace
    if is_prefab_root and (
        any(abs(v) > 0.0001 for v in o3de_transform.position)
        or any(abs(v) > 0.0001 for v in quaternion_to_euler(o3de_transform.rotation))
        or needs_nonuniform
        or abs(o3de_transform.scale[0] - 1.0) > 0.0001
    ):
        worker.log(
            f"  [Transform] Discarding non-identity root transform on "
            f"'{go.name}' (pos={o3de_transform.position}, "
            f"scale={o3de_transform.scale}) — Unity prefab root "
            f"transforms are dead data, placement comes from the "
            f"consumer's ContainerEntity patch."
        )
        o3de_transform   = Transform((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        needs_nonuniform = False
        transform_rule   = "root_discarded"

    entity = {
        "Id":   entity_id,
        "Name": go.name,
        "Components": {
            "EditorDisabledCompositionComponent": {
                "$type": "EditorDisabledCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorEntityIconComponent": {
                "$type": "EditorEntityIconComponent",
                "Id": generate_component_id(worker),
            },
            "EditorInspectorComponent": {
                "$type": "EditorInspectorComponent",
                "Id": generate_component_id(worker),
            },
            "EditorLockComponent": {
                "$type": "EditorLockComponent",
                "Id": generate_component_id(worker),
            },
            "EditorPendingCompositionComponent": {
                "$type": "EditorPendingCompositionComponent",
                "Id": generate_component_id(worker),
            },
            "EditorVisibilityComponent": {
                "$type": "EditorVisibilityComponent",
                "Id": generate_component_id(worker),
            },
        },
    }

    # Add TransformComponent.
    transform_component = {
        "$type": "{27F1E1A1-8D9D-4C3B-BD3A-AFB9762449C0} TransformComponent",
        "Id": generate_component_id(worker),
        "Parent Entity": parent_entity_id,
    }

    # Convert quaternion to Euler for rotation check.
    euler = quaternion_to_euler(o3de_transform.rotation)

    # Add Transform Data only if entity has non-default transform.
    has_rotation    = any(abs(v) > 0.0001 for v in euler)
    has_scale       = not needs_nonuniform and abs(o3de_transform.scale[0] - 1.0) > 0.0001

    # The position is always written, also when it is zero: a prefab that
    # nests this one may move the object, and a patch can replace one axis
    # of a position only where the position exists (`child_transform_patches`).
    transform_data: Dict = {"Translate": list(o3de_transform.position)}
    if has_rotation:
        transform_data["Rotate"] = euler
    if has_scale:
        transform_data["Scale"] = o3de_transform.scale[0]
    transform_component["Transform Data"] = transform_data

    entity["Components"]["TransformComponent"] = transform_component

    if needs_nonuniform:
        entity["Components"]["EditorNonUniformScaleComponent"] = non_uniform_scale_component(
            generate_component_id(worker), o3de_transform.scale)
        # The engine applies this scale to the entity's own mesh and shapes
        # only. Unity scales everything below as well.
        if go.children_ids:
            worker.coverage.warn(
                f"'{go.name}' has a non-uniform scale {tuple(o3de_transform.scale)} and "
                f"{len(go.children_ids)} child object(s): O3DE does not pass a non-uniform "
                f"scale down, so the children keep their size and place.")

    # Component Processors — emit phase (mesh, material, physics, …).
    # Each processor runs in WEIGHT order and may add child entities.
    ctx = ProcessingContext(
        material_mapping      = material_mapping,
        mesh_mapping          = mesh_mapping,
        fbx_material_labels   = fbx_material_labels,
        collider_pxmesh_mapping = getattr(worker, "_collider_pxmesh_mapping", {}),
        collision_config      = getattr(worker, "_collision_config_mapping", {}),
        entities_dict         = entities_dict,
        entity_id_map         = entity_id_map,
        generate_component_id = (lambda: generate_component_id(worker)),
        generate_entity_id    = (lambda: generate_entity_id(worker)),
        make_bare_entity      = (lambda eid, name, parent:
                                  make_bare_entity(worker, eid, name, parent)),
        log                   = worker.log,
        stats                 = worker.stats,
    )

    # For the conversion trace: which processor added which component or
    # child entity, and whether one of them rewrote the transform.
    trace = getattr(worker, "trace", None)
    component_owner: Dict[str, str] = {}
    child_owner: Dict[str, str] = {}
    transform_modified_by = ""

    collider_child_ids: List[str] = []
    for processor in worker.component_processors:
        keys_before = set(entity["Components"])
        transform_before = json.dumps(entity["Components"]["TransformComponent"], sort_keys=True) \
            if trace is not None else ""
        child_ids = processor.emit(go, entity, ctx)
        collider_child_ids.extend(child_ids)
        if trace is not None:
            owner = type(processor).__name__
            for key in set(entity["Components"]) - keys_before:
                component_owner[key] = owner
            for child_id in child_ids:
                child_owner[child_id] = owner
            if json.dumps(entity["Components"]["TransformComponent"], sort_keys=True) != transform_before:
                transform_modified_by = owner

    if trace is not None:
        trace.record_entity(go, entity, transform_rule, component_owner, child_owner,
                            transform_modified_by)

    # Child entities: GO children + any collider sub-entities.
    child_order: List[str] = []
    for child_id in go.children_ids:
        if child_id in all_game_objects:
            child_entity_id = create_entity_recursive(
                worker, all_game_objects[child_id], all_game_objects,
                entities_dict, instances_dict, entity_id_map,
                material_mapping, mesh_mapping, fbx_material_labels,
                entity_id,
            )
            if child_entity_id:
                child_order.append(child_entity_id)

    child_order.extend(collider_child_ids)

    if child_order:
        entity["Components"]["EditorEntitySortComponent"] = {
            "$type": "EditorEntitySortComponent",
            "Id": generate_component_id(worker),
            "Child Entity Order": child_order,
        }

    entities_dict[entity_id] = entity
    return entity_id
