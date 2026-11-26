"""
=============================================================================
PARITY REPORT
=============================================================================

Joins the three records of a cycle and says, element by element, whether the
converted result is where Unity has it.

    truth dump (Unity)  --identity chain-->  trace (converter)  --alias-->  O3DE record

Elements of a prefab, each with its own verdict:

    transform   an object's transform in the prefab frame
    mesh        a render mesh: its vertices in place
    collider    a collider: its geometry in place
    materials   the materials on a renderer

A verdict is ``pass``, ``fail``, ``uncooked`` (its assets did not cook),
``unmatched`` (no O3DE entity for the Unity object), ``unmeasured`` (nothing
to measure it with) or ``lod_stripped`` (a lower level of detail the
converter drops on purpose).

A failing element carries its **residual** (the correction that would put it
right) and a **signature**; elements with one signature form a cluster.

Writes ``report.json`` (everything) and ``report.md`` (to read) into the
bed's report folder. The previous report is kept beside them for the next
run's difference.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

import compare as cmp
import level_bake
import views
from records import (O3deRecord, Trace, box_corners, latest_truth, matrix_from_rows,
                     matrix_from_trs, transform_points)

STATUS_ORDER = ["fail", "unmatched", "uncooked", "unmeasured", "lod_stripped", "pass"]
SCALE_TOLERANCE = 1e-3          # relative
MATCHED_SHARE = 0.97            # share of a mesh's vertices that must find their partner
LOST = ("fail", "uncooked", "unmatched")   # verdicts that are a loss against a pass
CONVEX_SLACK = 5.0              # a cooked hull is an approximation: this many times the tolerance


# =============================================================================
# ONE CYCLE'S RECORDS
# =============================================================================

class Cycle:
    """Everything a comparison reads, loaded once."""

    def __init__(self, bed) -> None:
        self.bed = bed
        self.truth = latest_truth(bed.truth_base)
        self.trace = Trace(bed.convert_dir / "trace")
        self.record = O3deRecord(bed.probe_dir / "o3de")
        self.recipe = level_bake.read_recipe(bed.o3de_root / "Levels" / bed.level)
        self.cook = _read_json(bed.cook_dir / "cook.json")
        self.tolerance = bed.config["tolerance"]
        self.tolerance_m = self.tolerance["geometry_mm"] / 1000.0

        # O3DE entities by (instance path below the level, alias), and children.
        self.entities: Dict[Tuple[str, str], dict] = {}
        self.children: Dict[str, List[dict]] = defaultdict(list)
        for entity in self.record.entities:
            path = "/".join(entity["prefab"]["instancePath"].split("/")[1:])
            self.entities[(path, entity["prefab"]["alias"])] = entity
            self.children[entity["parent"]].append(entity)

        self.cell_of = {Path(cell["source"]).stem: cell for cell in self.recipe.get("instances", [])}
        self.failed_sources = {Path(source).name.lower(): reasons
                               for source, reasons in (self.cook.get("failed") or {}).items()}
        self._import_cache: Dict[Tuple[str, str], dict] = {}
        # Geometry of the prefab being compared, in the prefab frame, for its
        # sheet of views. None when no sheet is wanted.
        self.drawables: Optional[List[dict]] = None

    def draw(self, side: str, kind: str, points: np.ndarray, edges: np.ndarray) -> None:
        if self.drawables is not None:
            self.drawables.append(views.drawable(side, kind, points, edges))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# =============================================================================
# THE JOIN
# From a Unity object to the O3DE entity made from it.
# =============================================================================

def resolve_entity(cycle: Cycle, top_alias: str, item: dict):
    """Follow a Unity object's identity chain through the trace. Returns
    ``(entity, trace record of that entity, "")`` or ``(None, None, why)``."""
    path = top_alias
    for link in item["identity"]:
        traced = cycle.trace.prefab(link["guid"])
        if traced is None:
            return None, None, f"the converter did not process {Path(link['assetPath']).name or link['guid']}"
        if link["instanceFileId"]:
            nested = next((i for i in traced["instances"] if i["go_file_id"] == link["instanceFileId"]), None)
            if nested is not None:
                path = f"{path}/{nested['instance_alias']}"
                continue
            # An instance of a model file has no prefab of its own: the
            # converter makes its objects entities of this prefab, under the
            # ids Unity gives them here.
            if not any(e["go_file_id"] == link["fileId"] for e in traced["entities"]):
                return None, None, "its nested instance is not in the trace"
        traced_entity = next((e for e in traced["entities"] if e["go_file_id"] == link["fileId"]), None)
        if traced_entity is None:
            return None, None, "the object is not in the trace"
        entity = cycle.entities.get((path, traced_entity["entity_id"]))
        if entity is None:
            return None, traced_entity, "the entity is not in the level"
        return entity, traced_entity, ""
    return None, None, "its identity chain ends inside an instance"


def entity_matrix(entity: dict) -> np.ndarray:
    """An entity's exact world matrix: Transform 2's when it serves one,
    else its transform with its non-uniform scale applied."""
    if entity.get("transform2World"):
        return matrix_from_rows(entity["transform2World"])
    world = matrix_from_rows(entity["world"])
    if entity.get("nonUniformScale"):
        world = world @ np.diag(list(entity["nonUniformScale"]) + [1.0])
    return world


# =============================================================================
# VERDICTS
# =============================================================================

def placement_verdict(cycle: Cycle, fit: dict, expected: np.ndarray) -> Tuple[bool, bool]:
    """Whether a fitted placement (``compare.fit_placement``) is in place:
    ``(within the tolerance plus the truth's own noise, within the tolerance
    alone)``.

    The truth's vertices are noisy, and not independently: Unity's mesh
    compression moves a whole face at once. An offset smaller than the noise
    left after the fit cannot be told from that rounding, so the noise is
    allowed on top of the position tolerance. For the turn the allowance is
    the angle that noise subtends at the reach of the points *from the axis
    of the fitted turn*: a pencil can turn about its length by a degree
    before any vertex moves a tenth of a millimetre, and its fit does."""
    if fit["matched"] < MATCHED_SHARE:
        return False, False
    reach_mm = cmp.spread_about_axis(expected, fit.get("rotation_axis")) * 1000.0
    noise_deg = float(np.degrees(np.arctan2(fit["noise_mm"], max(reach_mm, 1e-6))))
    strict = (fit["offset_mm"] <= cycle.tolerance["position_mm"]
              and fit["rotation_deg"] <= cycle.tolerance["rotation_deg"])
    allowed = (fit["offset_mm"] <= cycle.tolerance["position_mm"] + fit["noise_mm"]
               and fit["rotation_deg"] <= cycle.tolerance["rotation_deg"] + noise_deg)
    return allowed, strict


def transform_element(cycle: Cycle, expected: np.ndarray, actual: np.ndarray, traced: dict) -> dict:
    delta = cmp.transform_delta(expected, actual)
    tolerance = cycle.tolerance
    wrong = []
    if delta["position_mm"] > tolerance["position_mm"]:
        wrong.append("position")
    if delta["rotation_deg"] > tolerance["rotation_deg"]:
        wrong.append(f"rotation {delta['rotation_class']}")
    if delta["scale_error"] > SCALE_TOLERANCE:
        wrong.append("scale")
    if delta["mirror_mismatch"]:
        wrong.append("mirror")
    element = {"kind": "transform", "status": "fail" if wrong else "pass", "delta": delta,
               "rule": traced.get("rule", "")}
    if wrong:
        element["signature"] = "transform: " + " + ".join(wrong) + f" [{traced.get('rule', '')}]"
        element["residual"] = (f"position off {delta['position_mm']:.1f} mm, rotation off "
                               f"{delta['rotation_deg']:.2f} deg ({delta['rotation_class']}), "
                               f"scale {_fmt(delta['actual_scale'])} for {_fmt(delta['expected_scale'])}")
    return element


def mesh_element(cycle: Cycle, item: dict, entity: dict, traced: dict, frame_unity: np.ndarray,
                 frame_o3de: np.ndarray) -> dict:
    truth_key = cycle.truth.mesh_key(item["mesh"])
    element = {"kind": "mesh", "mesh": item["mesh"]["name"], "fbx": Path(item["mesh"]["assetPath"]).name}
    facts = _fbx_context(cycle, element["fbx"], item["mesh"]["name"])
    element["fbx_facts"] = facts

    # A file whose job failed in the Asset Processor did not cook, whatever
    # the Editor still shows for it: an older model can linger in the cache.
    cook_errors = cycle.failed_sources.get(element["fbx"].lower())
    if cook_errors is not None:
        return {**element, "status": "uncooked",
                "residual": "its FBX job failed: " + (cook_errors[0] if cook_errors else "no error line")}

    mesh = entity.get("mesh")
    if mesh is None:
        # The entity shows no model. Either the converter named none, or the
        # model it named was never produced, or it exists and is not shown.
        hints: List[str] = []
        for component in traced.get("components", []):
            _collect_hints(component.get("emitted"), hints)
        models = [hint for hint in hints if hint.lower().endswith(".azmodel")]
        if not models:
            return {**element, "status": "fail", "signature": "mesh: the converter emitted no model",
                    "residual": "the entity has no mesh component"}
        element["model"] = models[0]
        if not (cycle.bed.o3de_root / "Cache" / "pc" / models[0]).is_file():
            return {**element, "status": "uncooked",
                    "residual": f"the model the prefab names was not produced: {models[0]}",
                    "signature": "mesh: the model the prefab names was not produced"}
        return {**element, "status": "fail", "signature": "mesh: model produced and not shown",
                "residual": "the entity shows no model"}
    if not mesh["ready"]:
        return {**element, "status": "uncooked", "model": mesh["asset"]}

    unity_local = cycle.truth.mesh_positions(truth_key)
    model_local = cycle.record.model_positions(mesh["key"])
    expected = cmp.unity_points_to_o3de(transform_points(frame_unity, unity_local))
    actual = transform_points(frame_o3de, model_local)
    cycle.draw("unity", "mesh", expected, views.triangle_edges(cycle.truth.mesh_indices(truth_key)))
    cycle.draw("o3de", "mesh", actual, views.triangle_edges(cycle.record.model_indices(mesh["key"])))
    gate = cmp.noise_gate(expected, cycle.tolerance_m)
    fit = cmp.fit_placement(actual, expected, gate)
    element.update({"model": mesh["asset"], "fit": fit, "distance": cmp.two_way_distance(actual, expected),
                    "vertices": [len(unity_local), len(model_local)]})

    # Import parity: the model in its own space against Unity's mesh in its own.
    cache_key = (truth_key, mesh["key"])
    if cache_key not in cycle._import_cache:
        unity_mapped = cmp.unity_points_to_o3de(unity_local)
        residual = cmp.find_residual(model_local, unity_mapped, cmp.noise_gate(unity_mapped, cycle.tolerance_m))
        kind = cmp.residual_class(residual, cycle.tolerance_m)
        rule = _visual_rule(cycle, element["fbx"], item["mesh"]["name"])
        cycle._import_cache[cache_key] = {
            "mesh": item["mesh"]["name"], "fbx": element["fbx"], "model": mesh["asset"], "facts": facts,
            "class": kind + explain_shift(residual, rule, cycle.tolerance_m),
            "text": cmp.describe_residual(residual, cycle.tolerance_m), "residual": residual,
            "rule": rule,
        }
    imported = cycle._import_cache[cache_key]
    element["import"] = {"class": imported["class"], "text": imported["text"]}

    # The verdict is on where the mesh sits (see placement_verdict).
    allowed, strict = placement_verdict(cycle, fit, expected)
    if allowed and abs(fit["scale"] - 1.0) <= SCALE_TOLERANCE * 5:
        element["status"] = "pass"
        if not strict:
            element["within_rounding"] = True
        return element

    residual = cmp.find_residual(actual, expected, gate)
    kind = cmp.residual_class(residual, cycle.tolerance_m)
    element["status"] = "fail"
    element["residual"] = cmp.describe_residual(residual, cycle.tolerance_m)
    if kind == "none":
        # The search finds nothing to correct, yet the fit is off: the two
        # meshes are in place and are not the same set of vertices.
        kind = "different vertices"
        element["residual"] = (f"in place, but only {fit['matched'] * 100:.0f} % of the vertices have a partner; "
                               f"fit offset {fit['offset_mm']:.1f} mm, rotation {fit['rotation_deg']:.2f} deg")
    element["signature"] = f"mesh: in place {kind} | import {imported['class']} | {_facts_text(facts)}"
    return element


def _visual_rule(cycle: Cycle, fbx_name: str, mesh_name: str) -> dict:
    """The coordinate rule the converter wrote for one mesh node, from the
    last assetinfo write of its file: ``{"translation", "rotation",
    "translation_source"}``, empty when it wrote none."""
    write = cycle.trace.last_assetinfo(fbx_name) or {}
    for group in write.get("groups", []):
        if group["kind"] == "visual" and group["node_paths"] and \
                group["node_paths"][0].split(".")[-1] == mesh_name:
            return {"translation": group["translation"], "rotation": group["rotation"],
                    "translation_source": group["translation_source"]}
    return {}


def explain_shift(residual: dict, rule: dict, tolerance_m: float, slack_m: float = 0.006) -> str:
    """Relate the shift a model needs to the translation its rule carries.
    Returns text to append to the residual's class, or an empty string.

    The slack covers Unity's vertex noise and the rounding of the rule."""
    if not residual["found"] or residual["name"] != "identity":
        return ""
    shift = np.asarray(residual["shift"])
    if np.linalg.norm(shift) <= tolerance_m:
        return ""
    translation = rule.get("translation")
    if not translation:
        return " (the rule has no translation)"
    source = rule.get("translation_source") or "rule"
    if np.linalg.norm(shift + np.asarray(translation)) <= slack_m:
        return f" = minus the rule's {source} translation"
    if np.linalg.norm(shift) < 0.01:
        return f" under 1 cm (the rule's {source} translation is close)"
    return f" (differs from the rule's {source} translation)"


def _fbx_context(cycle: Cycle, fbx_name: str, mesh_name: str) -> dict:
    """What the trace knows about the file a mesh comes from."""
    facts = cycle.trace.fbx_facts.get(fbx_name) or {}
    write = cycle.trace.last_assetinfo(fbx_name) or {}
    node = (facts.get("nodes") or {}).get(mesh_name, {})
    return {
        "up_axis":    {1: "Y-up", 2: "Z-up"}.get(write.get("up_axis"), "unknown up"),
        "mesh_nodes": len(facts.get("geometries") or []),
        "node":       "sub node" if node.get("parent") else "root node",
        "writes":     sum(1 for w in cycle.trace.assetinfos if w["fbx"] == fbx_name),
    }


def _facts_text(facts: dict) -> str:
    count = "single-mesh" if facts["mesh_nodes"] <= 1 else "multi-mesh"
    return f"{facts['up_axis']}, {count} FBX, {facts['node']}"


# ----- Colliders ------------------------------------------------------------

def unity_collider_geometry(cycle: Cycle, collider: dict, frame_unity: np.ndarray) -> Optional[dict]:
    """A Unity collider in the prefab frame, O3DE axes: corner or vertex
    points for a box or a mesh, centre(s) and radius for a sphere or a
    capsule. None for a kind that is not measured."""
    kind = collider["type"]
    _, _, scale, _ = cmp.decompose(frame_unity)

    if kind == "Box":
        corners = box_corners(collider["center"], collider["size"])
        points = cmp.unity_points_to_o3de(transform_points(frame_unity, corners))
        cycle.draw("unity", "collider", points, views.box_edges())
        return {"kind": kind, "points": points}

    if kind == "Sphere":
        center = cmp.unity_points_to_o3de(transform_points(frame_unity, np.array([collider["center"]])))[0]
        return {"kind": kind, "center": center, "radius": collider["radius"] * float(scale.max())}

    if kind == "Capsule":
        axis = int(collider["direction"])
        others = [index for index in range(3) if index != axis]
        radius = collider["radius"] * float(scale[others].max())
        height = max(collider["height"] * float(scale[axis]), 2.0 * radius)
        direction = frame_unity[:3, axis] / max(float(scale[axis]), 1e-12)
        center = transform_points(frame_unity, np.array([collider["center"]]))[0]
        ends = np.array([center - direction * (height / 2.0 - radius),
                         center + direction * (height / 2.0 - radius)])
        ends = cmp.unity_points_to_o3de(ends)
        return {"kind": kind, "ends": ends, "radius": radius}

    if kind == "Mesh" and collider["hasMesh"]:
        key = cycle.truth.mesh_key(collider["mesh"])
        points = cmp.unity_points_to_o3de(transform_points(frame_unity, cycle.truth.mesh_positions(key)))
        cycle.draw("unity", "collider", points, views.triangle_edges(cycle.truth.mesh_indices(key)))
        return {"kind": "Convex" if collider["convex"] else "Mesh", "points": points}
    return None


def o3de_shapes(cycle: Cycle, entity: dict, traced: dict, container_inverse: np.ndarray) -> List[np.ndarray]:
    """The collider shapes made for one Unity object, as points in the
    prefab frame: the entity's own, then those of the collider child
    entities the converter added for it, in the order it added them."""
    owners = [entity]
    child_ids = {child["entity_id"] for child in traced.get("child_entities", [])}
    ordered = sorted((child for child in cycle.children.get(entity["id"], [])
                      if child["prefab"]["alias"] in child_ids),
                     key=lambda child: child["prefab"]["alias"])
    owners += ordered

    shapes = []
    for owner in owners:
        for shape in owner["colliders"]:
            pose = matrix_from_rows(shape["bodyWorld"]) @ matrix_from_trs(
                shape["localPosition"], shape["localRotation"], 1.0)
            points = transform_points(container_inverse @ pose, cycle.record.collider_positions(shape["key"]))
            cycle.draw("o3de", "collider", points,
                       views.triangle_edges(cycle.record.collider_indices(shape["key"])))
            shapes.append(points)
    return shapes


def collider_elements(cycle: Cycle, item: dict, entity: dict, traced: dict,
                      frame_unity: np.ndarray, container_inverse: np.ndarray) -> List[dict]:
    shapes = o3de_shapes(cycle, entity, traced, container_inverse)
    elements = []
    for index, collider in enumerate(item["colliders"]):
        element = {"kind": "collider", "collider": collider["type"], "index": index}
        geometry = unity_collider_geometry(cycle, collider, frame_unity)
        if geometry is None:
            elements.append({**element, "status": "unmeasured"})
            continue
        element["collider"] = geometry["kind"]
        if index >= len(shapes) or len(shapes[index]) == 0:
            elements.append({**element, "status": "fail", "residual": "no collider shape in O3DE",
                             "signature": f"collider {geometry['kind']}: no shape in O3DE"})
            continue

        actual = np.unique(np.round(shapes[index], 6), axis=0)
        limit = cycle.tolerance["geometry_mm"]
        if geometry["kind"] == "Sphere":
            worst = cmp.sphere_surface_distances(actual, geometry["center"], geometry["radius"]).max()
            distance = {"max_mm": float(worst * 1000.0), "measure": "surface"}
            expected = None
        elif geometry["kind"] == "Capsule":
            worst = cmp.capsule_surface_distances(actual, geometry["ends"][0], geometry["ends"][1],
                                                  geometry["radius"]).max()
            distance = {"max_mm": float(worst * 1000.0), "measure": "surface"}
            expected = None
        elif geometry["kind"] == "Convex":
            # A cooked hull moves vertices: compare the two boxes.
            expected = geometry["points"]
            worst = max(np.abs(actual.min(axis=0) - expected.min(axis=0)).max(),
                        np.abs(actual.max(axis=0) - expected.max(axis=0)).max())
            distance = {"max_mm": float(worst * 1000.0), "measure": "bounds"}
            limit *= CONVEX_SLACK
        elif geometry["kind"] == "Mesh":
            # Unity's vertices carry compression noise: judge where the mesh
            # sits, as for a render mesh (placement_verdict).
            expected = geometry["points"]
            fit = cmp.fit_placement(actual, expected, cmp.noise_gate(expected, cycle.tolerance_m))
            allowed, strict = placement_verdict(cycle, fit, expected)
            distance = {"max_mm": float(fit["offset_mm"]), "measure": "fit", "rotation_deg": fit["rotation_deg"],
                        "matched": fit["matched"], "noise_mm": fit["noise_mm"]}
            if allowed:
                elements.append({**element, "distance": distance, "status": "pass",
                                 **({} if strict else {"within_rounding": True})})
                continue
            distance["max_mm"] = max(distance["max_mm"], limit * 2)     # not in place: it must not pass below
        else:
            expected = geometry["points"]
            distance = {**cmp.two_way_distance(actual, expected), "measure": "points"}

        element["distance"] = distance
        if distance["max_mm"] <= limit:
            elements.append({**element, "status": "pass"})
            continue

        if expected is not None:
            gate = (cmp.noise_gate(expected, cycle.tolerance_m) if geometry["kind"] in ("Mesh", "Convex")
                    else cycle.tolerance_m)
            residual = cmp.find_residual(actual, expected, gate)
            text = cmp.describe_residual(residual, cycle.tolerance_m)
            kind_class = cmp.residual_class(residual, cycle.tolerance_m)
        else:
            text, kind_class = f"off the Unity surface by {distance['max_mm']:.1f} mm", "off surface"
        elements.append({**element, "status": "fail", "residual": text,
                         "signature": f"collider {geometry['kind']}: {kind_class}"})

    if len(shapes) > len(item["colliders"]):
        elements.append({"kind": "collider", "collider": "extra", "status": "fail",
                         "residual": f"{len(shapes) - len(item['colliders'])} more shape(s) in O3DE than colliders in Unity",
                         "signature": "collider: more shapes in O3DE than in Unity"})
    return elements


# ----- Materials ------------------------------------------------------------

def material_element(item: dict, traced: dict) -> dict:
    """Are the materials on the renderer the ones Unity has, by name? The
    slot each sits on is not checked.

    A material that is no asset of the project (Unity's own default, which a
    cube made in the editor carries) has nothing to be converted from; a
    renderer left without a material shows the engine's default, as Unity
    shows its own. Such materials are listed, not asked for."""
    in_project = [material for material in item["materials"]
                  if material["name"] and material.get("assetPath", "").startswith("Assets/")]
    not_assets = sorted({material["name"].lower() for material in item["materials"]
                         if material["name"] and material not in in_project})
    wanted = sorted({material["name"].lower() for material in in_project})
    hints: List[str] = []
    for component in traced.get("components", []):
        _collect_hints(component.get("emitted"), hints)
    emitted = sorted({Path(hint).name.split(".")[0].lower() for hint in hints
                      if ".azmaterial" in hint.lower() or ".material" in hint.lower()})
    element = {"kind": "materials", "unity": wanted, "o3de": emitted}
    if not_assets:
        element["unity_not_project_assets"] = not_assets
    if wanted == emitted:
        return {**element, "status": "pass"}
    missing = sorted(set(wanted) - set(emitted))
    return {**element, "status": "fail",
            "residual": f"missing in O3DE: {missing}; only in O3DE: {sorted(set(emitted) - set(wanted))}",
            "signature": "materials: " + ("none emitted" if not emitted else "set differs")}


def _collect_hints(value, hints: List[str]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "assetHint" and isinstance(inner, str):
                hints.append(inner)
            else:
                _collect_hints(inner, hints)
    elif isinstance(value, list):
        for inner in value:
            _collect_hints(inner, hints)


# =============================================================================
# ONE PREFAB
# =============================================================================

def compare_prefab(cycle: Cycle, entry: dict) -> dict:
    hierarchy = cycle.truth.hierarchy(entry)
    name = Path(entry["assetPath"]).stem
    result = {"name": name, "guid": entry["guid"], "assetPath": entry["assetPath"],
              "objects": [], "notes": []}
    objects = hierarchy["objects"]

    cook_errors = cycle.failed_sources.get(f"{name}.prefab".lower())
    if cook_errors is not None:
        result["notes"].append("its prefab job failed in the Asset Processor: " + (cook_errors[0] if cook_errors else ""))

    cell = cycle.cell_of.get(name)
    container = cycle.entities.get((cell["alias"], "ContainerEntity")) if cell else None
    if not objects or cycle.trace.prefab(entry["guid"]) is None or container is None:
        reason = ("it is empty in Unity" if not objects else
                  "the converter wrote no prefab for it" if cycle.trace.prefab(entry["guid"]) is None else
                  "its instance is not in the level")
        result.update({"status": "unmatched", "notes": result["notes"] + [reason]})
        return result

    container_inverse = np.linalg.inv(matrix_from_rows(container["world"]))
    root_matrix = matrix_from_rows(objects[0]["matrix"])
    to_prefab_frame = cmp.prefab_frame(root_matrix)
    result["root_stored"] = {"position": objects[0]["localPosition"], "rotation": objects[0]["localRotation"],
                             "scale": objects[0]["localScale"]}

    # Renderers of lower levels of detail are dropped by the converter on purpose.
    stripped = set()
    for item in objects:
        kept = set(item["lods"][0]["rendererObjects"]) if item["lods"] else set()
        for level in item["lods"][1:]:
            stripped.update(index for index in level["rendererObjects"] if index not in kept)

    matched_ids = set()
    for item in objects:
        record = {"index": item["index"], "path": item["path"], "elements": []}
        result["objects"].append(record)
        frame_unity = to_prefab_frame @ matrix_from_rows(item["matrix"])
        entity, traced, why = resolve_entity(cycle, cell["alias"], item)

        if entity is None:
            status = "lod_stripped" if item["index"] in stripped else "unmatched"
            record["elements"].append({"kind": "object", "status": status, "residual": why,
                                       "signature": f"object: {why}"})
            continue
        matched_ids.add(entity["id"])
        frame_o3de = container_inverse @ entity_matrix(entity)

        record["entity"] = entity["prefab"]["alias"]
        record["elements"].append(transform_element(cycle, cmp.unity_matrix_to_o3de(frame_unity), frame_o3de, traced))
        if item["hasMesh"] and item["hasRenderer"]:
            record["elements"].append(mesh_element(cycle, item, entity, traced, frame_unity, frame_o3de))
            record["elements"].append(material_element(item, traced))
        if item["colliders"]:
            record["elements"] += collider_elements(cycle, item, entity, traced, frame_unity, container_inverse)

    statuses = [element["status"] for record in result["objects"] for element in record["elements"]]
    result["status"] = next((status for status in STATUS_ORDER if status in statuses), "pass")
    result["counts"] = {status: statuses.count(status) for status in STATUS_ORDER if status in statuses}
    return result


# =============================================================================
# ONE SCENE
# Where each placed prefab instance stands in the converted level.
# =============================================================================

def compare_scene(cycle: Cycle, entry: dict) -> Optional[dict]:
    """Compare the world placement of every prefab instance of a Unity scene
    with its container entity in the converted level. None when the level
    was not probed."""
    name = Path(entry["assetPath"]).stem
    folder = cycle.bed.probe_dir / f"scene_{name}" / "o3de"
    traced = cycle.trace.scene(name)
    if not (folder / "record.json").is_file() or traced is None:
        return None

    record = O3deRecord(folder)
    containers = {"/".join(entity["prefab"]["instancePath"].split("/")[1:]): entity
                  for entity in record.entities if entity["prefab"]["isContainer"]}
    aliases = {instance.get("unity_instance_file_id", instance["go_file_id"]): instance["instance_alias"]
               for instance in traced["instances"]}
    objects = cycle.truth.hierarchy(entry)["objects"]

    # Objects of the scene itself (a light, a camera): by their file id.
    own = {entity["prefab"]["alias"]: entity for entity in record.entities
           if "/" not in entity["prefab"]["instancePath"] and not entity["prefab"]["isContainer"]}
    own_aliases = {entity["go_file_id"]: entity["entity_id"] for entity in traced["entities"]}

    rows = []
    for item in objects:
        link = item["identity"][0]
        if not link["instanceFileId"]:
            row = {"name": item["name"], "path": item["path"], "source": "(scene object)"}
            entity = own.get(own_aliases.get(link["fileId"], ""))
            if entity is None:
                row.update({"status": "unmatched", "signature": "scene: object not in the level",
                            "residual": "the converter made no entity for it"})
            else:
                expected = cmp.unity_matrix_to_o3de(matrix_from_rows(item["matrix"]))
                element = transform_element(cycle, expected, entity_matrix(entity), {"rule": "scene object"})
                row.update({key: element[key] for key in ("status", "delta") if key in element})
                if element["status"] == "fail":
                    row["signature"] = element["signature"].replace("transform:", "scene:")
                    row["residual"] = element["residual"]
            rows.append(row)
            continue

        parent = objects[item["parent"]] if item["parent"] >= 0 else None
        placed = item["isInstanceRoot"] and (
            parent is None or parent["identity"][0]["instanceFileId"] != link["instanceFileId"])
        if not placed:
            continue
        row = {"name": item["name"], "path": item["path"], "source": Path(item["instanceSourcePath"]).stem}
        alias = aliases.get(link["instanceFileId"])
        container = containers.get(alias) if alias else None
        if container is None:
            row.update({"status": "unmatched", "signature": "scene: instance not in the level",
                        "residual": "the converter placed no instance for it" if alias is None
                                    else "its instance is not in the level"})
        else:
            expected = cmp.unity_matrix_to_o3de(matrix_from_rows(item["matrix"]))
            element = transform_element(cycle, expected, entity_matrix(container), {"rule": "scene instance"})
            row.update({key: element[key] for key in ("status", "delta") if key in element})
            if element["status"] == "fail":
                row["signature"] = element["signature"].replace("transform:", "scene:")
                row["residual"] = element["residual"]
        rows.append(row)

    lighting = lighting_row(cycle, entry, folder)
    if lighting is not None:
        rows.append(lighting)

    statuses = [row["status"] for row in rows]
    return {"name": name, "level_probe": record.done,
            "counts": {status: statuses.count(status) for status in STATUS_ORDER if status in statuses},
            "instances": rows}


# ----- The level's ambient light ----------------------------------------------

GRADIENT_GI = "Gradient GI (IBL)"       # the component's name in the Editor
AMBIENT_COLOURS = (("High", "m_AmbientSkyColor"), ("Mid", "m_AmbientEquatorColor"), ("Low", "m_AmbientGroundColor"))
COLOUR_TOLERANCE = 0.002


def unity_ambient_colours(scene_file: Path) -> Optional[Dict[str, List[float]]]:
    """The three ambient colours a Unity scene file stores, by their Unity
    names; None when the file holds none."""
    try:
        text = Path(scene_file).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    colours = {}
    for _, key in AMBIENT_COLOURS:
        match = re.search(key + r":\s*\{r:\s*([-\d.e]+),\s*g:\s*([-\d.e]+),\s*b:\s*([-\d.e]+)", text)
        if match is None:
            return None
        colours[key] = [float(value) for value in match.groups()]
    return colours


def lighting_row(cycle: Cycle, entry: dict, folder: Path) -> Optional[dict]:
    """The level's ambient light: the three colours the Unity scene file
    stores against the ones the Editor holds in the level's Gradient GI
    component, read back by the probe session. A row like an instance's;
    None for a scene without ambient colours."""
    wanted = unity_ambient_colours(Path(cycle.truth.catalog.get("projectPath", "")) / entry["assetPath"])
    if wanted is None:
        return None
    row = {"name": "Gradient GI", "path": "(level)", "source": "(scene lighting)"}

    properties = _read_json(folder / "properties.json")
    held = [components[GRADIENT_GI] for components in properties.values() if GRADIENT_GI in components]
    if len(held) != 1:
        return {**row, "status": "fail", "signature": "scene: lighting",
                "residual": f"{len(held)} Gradient GI component(s) in the level, one wanted"}

    misses = []
    for label, key in AMBIENT_COLOURS:
        value = next((text for path, text in held[0].items() if label in path.split("|")[-1]), None)
        numbers = [float(number) for number in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?", value or "")][:3]
        if len(numbers) < 3 or max(abs(a - b) for a, b in zip(numbers, wanted[key])) > COLOUR_TOLERANCE:
            misses.append(f"{label} is {numbers or value} for Unity's {wanted[key]}")
    if misses:
        return {**row, "status": "fail", "signature": "scene: lighting", "residual": "; ".join(misses)}
    return {**row, "status": "pass", "colours": wanted}


def scene_clusters(scene: dict) -> List[dict]:
    clusters: Dict[str, dict] = {}
    for row in scene["instances"]:
        if "signature" not in row:
            continue
        cluster = clusters.setdefault(row["signature"], {"signature": row["signature"], "instances": 0,
                                                         "prefabs": set(), "example": ""})
        cluster["instances"] += 1
        cluster["prefabs"].add(row["source"])
        cluster["example"] = cluster["example"] or f"{row['name']}: {row['residual']}"
    ordered = sorted(clusters.values(), key=lambda c: -c["instances"])
    for cluster in ordered:
        cluster["prefabs"] = sorted(cluster["prefabs"])
    return ordered


# =============================================================================
# DIFFERENCE FROM THE PREVIOUS RUN
# =============================================================================

def difference(previous: dict, current: dict) -> dict:
    """What changed between two reports: clusters that closed or opened, and
    the elements that passed before and do not now (regressions: failing,
    uncooked or unmatched) or the reverse (fixed)."""
    def element_statuses(report: dict) -> Dict[str, str]:
        found = {}
        for prefab in report.get("prefabs", []):
            for record in prefab.get("objects", []):
                seen: Dict[str, int] = defaultdict(int)
                for element in record["elements"]:
                    label = element["kind"]
                    seen[label] += 1
                    # The object's index tells apart objects that share a path.
                    found[f"{prefab['name']} / {record['path']} #{record['index']} / "
                          f"{label} {seen[label]}"] = element["status"]
        return found

    before, after = element_statuses(previous), element_statuses(current)
    signatures_before = {cluster["signature"] for cluster in previous.get("clusters", [])}
    signatures_after = {cluster["signature"] for cluster in current.get("clusters", [])}
    return {
        "clusters_closed": sorted(signatures_before - signatures_after),
        "clusters_opened": sorted(signatures_after - signatures_before),
        "regressions":     sorted(key for key, status in after.items()
                                  if status in LOST and before.get(key) == "pass"),
        "fixed":           sorted(key for key, status in after.items()
                                  if status == "pass" and before.get(key) in LOST),
    }


# =============================================================================
# CLUSTERS AND SUMMARY
# =============================================================================

def build_clusters(prefabs: List[dict]) -> List[dict]:
    """Group the failing and unmatched elements by signature, largest first."""
    clusters: Dict[str, dict] = {}
    for prefab in prefabs:
        for record in prefab.get("objects", []):
            for element in record["elements"]:
                signature = element.get("signature")
                if not signature or element["status"] not in ("fail", "unmatched", "uncooked"):
                    continue
                cluster = clusters.setdefault(signature, {
                    "signature": signature, "kind": element["kind"], "elements": 0,
                    "prefabs": set(), "example": ""})
                cluster["elements"] += 1
                cluster["prefabs"].add(prefab["name"])
                if not cluster["example"]:
                    cluster["example"] = f"{prefab['name']} / {record['path']}: {element.get('residual', '')}"
    ordered = sorted(clusters.values(), key=lambda c: (-len(c["prefabs"]), -c["elements"], c["signature"]))
    for cluster in ordered:
        cluster["prefabs"] = sorted(cluster["prefabs"])
    return ordered


def summarise(prefabs: List[dict]) -> dict:
    elements = defaultdict(lambda: defaultdict(int))
    for prefab in prefabs:
        for record in prefab.get("objects", []):
            for element in record["elements"]:
                elements[element["kind"]][element["status"]] += 1
    return {
        "prefabs": {status: sum(1 for p in prefabs if p["status"] == status)
                    for status in STATUS_ORDER if any(p["status"] == status for p in prefabs)},
        "elements": {kind: dict(counts) for kind, counts in sorted(elements.items())},
        # Meshes that pass only because their offset is inside the noise of
        # Unity's own vertices (see mesh_element).
        "within_rounding": sum(1 for prefab in prefabs for record in prefab.get("objects", [])
                               for element in record["elements"] if element.get("within_rounding")),
    }


def _fmt(values) -> str:
    return "(" + ", ".join(f"{v:.3f}" for v in values) + ")"


# =============================================================================
# WRITING
# =============================================================================

def write_report(cycle: Cycle, report: dict) -> Path:
    """Write report.json and report.md. The report that was there becomes
    report_previous.json, and the new one carries its difference from it
    when both cover the same prefabs."""
    folder = cycle.bed.report_dir
    folder.mkdir(parents=True, exist_ok=True)
    current = folder / "report.json"
    if current.is_file():
        previous = _read_json(current)
        if {p["name"] for p in previous.get("prefabs", [])} == {p["name"] for p in report["prefabs"]}:
            shutil.copyfile(current, folder / "report_previous.json")
            report["difference"] = difference(previous, report)
    current.write_text(json.dumps(report, indent=1), encoding="utf-8")
    (folder / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return folder / "report.md"


def render_markdown(report: dict) -> str:
    summary, tolerance = report["summary"], report["tolerance"]
    lines = [
        f"# Parity report: {report['bed']}",
        "",
        f"Truth: Unity {report['unity_version']}, {report['truth_dump']}. "
        f"Tolerance: {tolerance['position_mm']} mm position, {tolerance['rotation_deg']} deg rotation, "
        f"{tolerance['geometry_mm']} mm geometry.",
        "",
        "## Prefabs",
        "",
        "| Status | Prefabs |",
        "|---|---|",
    ]
    lines += [f"| {status} | {count} |" for status, count in summary["prefabs"].items()]
    lines += ["", "## Elements", "", "| Kind | " + " | ".join(STATUS_ORDER) + " |",
              "|---|" + "---|" * len(STATUS_ORDER)]
    for kind, counts in summary["elements"].items():
        lines.append(f"| {kind} | " + " | ".join(str(counts.get(status, 0)) for status in STATUS_ORDER) + " |")

    lines += ["", f"Meshes passing within Unity's own vertex rounding (offset inside the noise of the fit): "
                  f"{summary.get('within_rounding', 0)}."]
    lines += ["", "## Cook", ""]
    if report["cook_failed"]:
        lines += [f"- `{Path(source).name}`: {reasons[0] if reasons else 'no error line'}"
                  for source, reasons in sorted(report["cook_failed"].items())]
    else:
        lines.append("No failed job.")

    lines += ["", "## Mesh import (model space against Unity's mesh space)", "",
              "| What the model needs to match Unity's mesh | Meshes | FBX kinds |", "|---|---|---|"]
    for row in report["import_classes"]:
        lines.append(f"| {row['class']} | {row['count']} | {row['facts']} |")

    lines += ["", "## Clusters", "",
              "| # | Prefabs | Elements | Signature | Example |", "|---|---|---|---|---|"]
    for number, cluster in enumerate(report["clusters"], 1):
        lines.append(f"| {number} | {len(cluster['prefabs'])} | {cluster['elements']} | "
                     f"{cluster['signature']} | {cluster['example']} |")

    for scene in report.get("scenes", []):
        lines += ["", f"## Scene: {scene['name']} (placement of each instance)", "",
                  ", ".join(f"{count} {status}" for status, count in scene["counts"].items()) or "no instance", "",
                  "| Instances | Prefabs | Signature | Example |", "|---|---|---|---|"]
        lines += [f"| {cluster['instances']} | {len(cluster['prefabs'])} | {cluster['signature']} | {cluster['example']} |"
                  for cluster in scene["clusters"]]

    change = report.get("difference")
    if change:
        lines += ["", "## Difference from the previous run", "",
                  f"- clusters closed: {len(change['clusters_closed'])}",
                  f"- clusters opened: {len(change['clusters_opened'])}",
                  f"- elements fixed: {len(change['fixed'])}",
                  f"- regressions: {len(change['regressions'])}"]
        lines += [f"  - regression: {key}" for key in change["regressions"][:40]]
        lines += [f"  - opened: {signature}" for signature in change["clusters_opened"][:20]]
        lines += [f"  - closed: {signature}" for signature in change["clusters_closed"][:20]]

    lines += ["", "## Prefabs, one line each", "",
              "The sheet shows front, top and left views: Unity's geometry wide and pale, O3DE's thin on top.", "",
              "| Prefab | Status | Elements | Sheet | Notes |", "|---|---|---|---|---|"]
    for prefab in report["prefabs"]:
        counts = ", ".join(f"{count} {status}" for status, count in prefab.get("counts", {}).items())
        sheet = f"[views]({prefab['sheet']})" if prefab.get("sheet") else ""
        lines.append(f"| {prefab['name']} | {prefab['status']} | {counts} | {sheet} | {'; '.join(prefab['notes'])} |")
    return "\n".join(lines) + "\n"


# =============================================================================
# ENTRY
# =============================================================================

def run_compare(bed, arguments) -> int:
    started = time.time()
    cycle = Cycle(bed)
    only = getattr(arguments, "only", "")
    entries = [entry for entry in cycle.truth.prefab_entries()
               if not only or fnmatch.fnmatch(Path(entry["assetPath"]).stem.lower(), only.lower())]

    sheets = bed.report_dir / "sheets"
    if sheets.exists() and not only:
        shutil.rmtree(sheets)
    prefabs = []
    for entry in entries:
        cycle.drawables = []
        prefab = compare_prefab(cycle, entry)
        summary = ", ".join(f"{count} {status}" for status, count in prefab.get("counts", {}).items())
        views.write_sheet(sheets / f"{prefab['name']}.png", prefab["name"], prefab["status"],
                          summary or "; ".join(prefab["notes"]), cycle.drawables)
        prefab["sheet"] = f"sheets/{prefab['name']}.png"
        prefabs.append(prefab)
    cycle.drawables = None
    prefabs.sort(key=lambda prefab: (STATUS_ORDER.index(prefab["status"]), prefab["name"]))

    import_rows: Dict[str, dict] = {}
    for imported in cycle._import_cache.values():
        row = import_rows.setdefault(imported["class"], {"class": imported["class"], "count": 0, "kinds": defaultdict(int)})
        row["count"] += 1
        row["kinds"][_facts_text(imported["facts"])] += 1
    import_classes = [{"class": row["class"], "count": row["count"],
                       "facts": "; ".join(f"{count} {kind}" for kind, count in sorted(row["kinds"].items()))}
                      for row in sorted(import_rows.values(), key=lambda row: -row["count"])]

    report = {
        "bed":            bed.config["name"],
        "unity_version":  cycle.truth.done.get("unityVersion", ""),
        "truth_dump":     cycle.truth.dump_dir.name,
        "tolerance":      cycle.tolerance,
        "summary":        summarise(prefabs),
        "cook_failed":    cycle.cook.get("failed") or {},
        "import_classes": import_classes,
        "imports":        [{**{key: value for key, value in imported.items() if key != "residual"},
                            "shift": imported["residual"]["shift"],
                            "turn": imported["residual"]["name"],
                            "turn_matrix": imported["residual"]["rotation"],
                            "scale": imported["residual"]["scale"],
                            "explained": imported["residual"]["found"]}
                           for imported in cycle._import_cache.values()],
        "clusters":       build_clusters(prefabs),
        "prefabs":        prefabs,
        "scenes":         [],
    }
    for entry in cycle.truth.scene_entries():
        scene = compare_scene(cycle, entry)
        if scene is not None:
            scene["clusters"] = scene_clusters(scene)
            report["scenes"].append(scene)
    report_file = write_report(cycle, report)

    print(f"[compare] {len(prefabs)} prefab(s) in {time.time() - started:.0f} s: "
          + ", ".join(f"{count} {status}" for status, count in report["summary"]["prefabs"].items()))
    for kind, counts in report["summary"]["elements"].items():
        print(f"[compare]   {kind:<10} " + ", ".join(f"{count} {status}" for status, count in sorted(counts.items())))
    print(f"[compare]   meshes passing within Unity's rounding: {report['summary']['within_rounding']}")
    print(f"[compare] {len(report['clusters'])} cluster(s); the largest:")
    for cluster in report["clusters"][:12]:
        print(f"[compare]   {len(cluster['prefabs']):>3} prefab(s) {cluster['elements']:>4} element(s)  {cluster['signature']}")
    for scene in report["scenes"]:
        print(f"[compare] scene {scene['name']}: "
              + ", ".join(f"{count} {status}" for status, count in scene["counts"].items()))
        for cluster in scene["clusters"][:6]:
            print(f"[compare]   {cluster['instances']:>4} instance(s)  {cluster['signature']}")
    change = report.get("difference")
    if change:
        unchanged = not any(change.values())
        print("[compare] against the previous run: " + ("no change" if unchanged else
              f"{len(change['fixed'])} fixed, {len(change['regressions'])} regression(s), "
              f"{len(change['clusters_closed'])} cluster(s) closed, {len(change['clusters_opened'])} opened"))
        for key in change["regressions"][:10]:
            print(f"[compare]   regression: {key}")
    print(f"[compare] report: {report_file}")
    return 0
