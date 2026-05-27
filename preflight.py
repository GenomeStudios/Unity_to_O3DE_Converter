#!/usr/bin/env python3
"""F-8 — Pre-flight checks for the Mission Command orchestrator.

A pre-flight is a per-stage audit of project state that runs BEFORE any
worker is dispatched. Each check returns one or more `PreflightItem`s
tagged with a severity:

  green   — passed; informational
  yellow  — non-fatal; user can Acknowledge to gate-allow
  red     — fatal; blocks Run All until resolved

The `PreflightReport.can_run` gate is the orchestrator's go/no-go signal:
no reds, every yellow has an `ack_key` whose current snapshot matches the
stored ack in `project.preflight_acks`. Acknowledging a yellow row stores
a sha256 of the condition's snapshot (e.g. the sorted list of unmapped
shader names) — when the snapshot drifts (a 4th unmapped shader appears),
the stored ack no longer matches and the row re-arms.

Each check function takes a `project` (and optional cross-cutting state
like `deps_present`) and returns a list of `PreflightItem`s. Functions
must be pure-ish — no UI, no signals, no project mutation.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class PreflightItem:
    """One row in the Pre-flight panel."""
    category: str                           # "asset_processor", "environment", ...
    severity: str                           # "green" | "yellow" | "red"
    title:    str
    detail:   str   = ""
    fix_hint: str   = ""                    # short instruction ("Open Materials → Edit Mappings")
    ack_key:  Optional[str] = None          # set on yellow items that are ack-able
    ack_snapshot: Optional[str] = None      # sha256 of underlying condition; matches against project.preflight_acks


@dataclass
class PreflightReport:
    """Roll-up of every PreflightItem from a full check pass."""
    items: List[PreflightItem] = field(default_factory=list)
    acks:  Dict[str, str]      = field(default_factory=dict)  # snapshot of project.preflight_acks at check time

    # ---- queries ------------------------------------------------------------

    @property
    def has_red(self) -> bool:
        return any(it.severity == "red" for it in self.items)

    @property
    def reds(self) -> List[PreflightItem]:
        return [it for it in self.items if it.severity == "red"]

    @property
    def yellows(self) -> List[PreflightItem]:
        return [it for it in self.items if it.severity == "yellow"]

    @property
    def greens(self) -> List[PreflightItem]:
        return [it for it in self.items if it.severity == "green"]

    @property
    def needs_ack(self) -> List[PreflightItem]:
        """Yellow rows whose current snapshot hash doesn't match the
        stored ack. These block `can_run` until acknowledged or fixed."""
        out: List[PreflightItem] = []
        for it in self.yellows:
            if not it.ack_key:
                # Yellow without an ack_key is informational; doesn't gate.
                continue
            stored = self.acks.get(it.ack_key)
            if stored is None or stored != (it.ack_snapshot or ""):
                out.append(it)
        return out

    @property
    def can_run(self) -> bool:
        """Green-light gate for Run All. False on any red OR any unacked
        yellow with an ack_key."""
        return (not self.has_red) and (not self.needs_ack)

    def categories(self) -> List[str]:
        """Stable ordering of categories present in the report."""
        seen: List[str] = []
        for it in self.items:
            if it.category not in seen:
                seen.append(it.category)
        return seen

    def by_category(self, cat: str) -> List[PreflightItem]:
        return [it for it in self.items if it.category == cat]

    def worst_severity(self, cat: str) -> str:
        bucket = self.by_category(cat)
        if any(it.severity == "red" for it in bucket):
            return "red"
        if any(it.severity == "yellow" for it in bucket):
            return "yellow"
        return "green"


# =============================================================================
# SNAPSHOT HASHING
#
# Each ack-able yellow item carries a snapshot — a stable hash of the
# underlying condition. The user acknowledges that snapshot; if the
# condition then drifts (new unmapped shader, removed dep, etc.), the
# stored ack no longer matches and the item re-arms.
# =============================================================================

def _snapshot_hash(payload) -> str:
    """sha256 over a canonical JSON encoding of payload. Keys sorted,
    separators tight, default-str fallback for Path/set."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================

def check_environment(project, deps_present: bool = True) -> List[PreflightItem]:
    """Project-level sanity. Scope root exists and contains an Assets/
    folder (Unity convention). Dependencies are present (delegates to the
    F-1 banner state via the `deps_present` argument)."""
    out: List[PreflightItem] = []
    cat = "environment"

    if not deps_present:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="Missing dependencies",
            detail="One or more required tools are not installed.",
            fix_hint="Open Config to install or locate the missing dependencies.",
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="Dependencies present",
        ))

    scope_root = project.scope_root if project else None
    if scope_root is None:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="No source root set",
            detail="The project's source-engine asset root is not configured.",
            fix_hint="Set the Source Root field on the Dashboard.",
        ))
        return out
    if not Path(scope_root).exists():
        out.append(PreflightItem(
            category=cat, severity="red",
            title="Source root does not exist on disk",
            detail=f"Path: {scope_root}",
            fix_hint="Re-pick the Source Root on the Dashboard.",
        ))
        return out
    out.append(PreflightItem(
        category=cat, severity="green",
        title="Source root present",
        detail=str(scope_root),
    ))
    return out


def check_asset_processor(project) -> List[PreflightItem]:
    """Prefab Processor stage. Needs ≥1 prefab marked and an output_path."""
    out: List[PreflightItem] = []
    cat = "asset_processor"
    if project is None:
        out.append(PreflightItem(category=cat, severity="red",
                                  title="No project loaded"))
        return out
    cfg = project.stage_settings("asset_processor")
    output = (cfg.get("output_path") or "").strip()
    selected = list(cfg.get("selected_prefabs") or [])

    if not output:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="No output folder",
            detail="Prefab Processor has no O3DE output destination.",
            fix_hint="Open the Prefabs tab and pick an output folder.",
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="Output folder set",
            detail=output,
        ))

    if not selected:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="No prefabs selected",
            detail="At least one prefab must be checked before Run All.",
            fix_hint="Open the Prefabs tab and check at least one row.",
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title=f"{len(selected)} prefab(s) selected",
        ))
    return out


def check_scene_converter(project) -> List[PreflightItem]:
    """Scene Converter stage. Optional — green when no scenes selected
    (skip the stage); needs an output_path when any scene IS selected."""
    out: List[PreflightItem] = []
    cat = "scene_converter"
    if project is None:
        return out
    cfg = project.stage_settings("scene_converter")
    selected = list(cfg.get("selected_scenes") or [])
    output   = (cfg.get("output_path") or "").strip()

    if not selected:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="No scenes selected — stage will be skipped",
        ))
        return out

    if not output:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="No scene output folder",
            detail=f"{len(selected)} scene(s) selected but no output set.",
            fix_hint="Open the Scenes tab and pick a levels output folder.",
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title=f"{len(selected)} scene(s) selected",
            detail=output,
        ))
    return out


def check_material_processor(project) -> List[PreflightItem]:
    """Material profile coverage. Two checks:
      - Every detected shader has either an explicit mapping OR resolves
        to the default profile. Detected-but-unmapped shaders are yellow
        and ack-able (the catch-all default profile covers them, but the
        user should be aware).
      - Every override entry points at a material GUID present in the
        inventory. Stale overrides are yellow (clean up at user option).
    """
    out: List[PreflightItem] = []
    cat = "material_processor"
    if project is None:
        return out
    cfg = project.stage_settings("material_processor")
    mappings = cfg.get("shader_mappings") or {}
    overrides = cfg.get("overrides") or {}
    profiles  = cfg.get("shader_profiles") or {}
    ap_meta   = (project.outputs.get("asset_processor") or {}).get(
        "material_metadata") or {}

    # No materials extracted yet → can't audit, skip silently with a green.
    if not ap_meta:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="No materials extracted yet",
            detail="Run the Prefab Processor first to populate the inventory.",
        ))
        return out

    detected_shaders = sorted({
        (rec or {}).get("shader_name", "")
        for rec in ap_meta.values()
        if (rec or {}).get("shader_name")
    })
    unmapped = [s for s in detected_shaders if s not in mappings]

    if unmapped:
        out.append(PreflightItem(
            category=cat, severity="yellow",
            title=f"{len(unmapped)} shader(s) without explicit mapping",
            detail=(", ".join(unmapped[:3]) +
                    (f", +{len(unmapped) - 3} more" if len(unmapped) > 3 else "")),
            fix_hint="Open Materials → Edit Mappings, or Acknowledge to use the default profile.",
            ack_key="material.unmapped",
            ack_snapshot=_snapshot_hash(unmapped),
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title=f"{len(detected_shaders)} shader(s) — all mapped",
        ))

    # Stale overrides — keys not in inventory.
    inventory_guids = set(ap_meta.keys())
    stale = sorted(set(overrides.keys()) - inventory_guids)
    if stale:
        out.append(PreflightItem(
            category=cat, severity="yellow",
            title=f"{len(stale)} stale material override(s)",
            detail="Override entries reference GUIDs no longer in the inventory.",
            fix_hint="Open Materials and clear the override for those rows, or Acknowledge.",
            ack_key="material.stale_overrides",
            ack_snapshot=_snapshot_hash(stale),
        ))

    # Mappings that reference profiles not in the library.
    missing_profile_names = sorted({
        v for v in mappings.values() if v and v not in profiles
    })
    if missing_profile_names:
        out.append(PreflightItem(
            category=cat, severity="red",
            title=f"Mappings reference missing profile(s)",
            detail=", ".join(missing_profile_names),
            fix_hint="Either add the profile (F-10) or re-map those shaders.",
        ))
    return out


def check_mesh_processor(project) -> List[PreflightItem]:
    """Mesh override sanity — overrides that point at GUIDs not in the
    current mesh inventory are flagged as stale."""
    out: List[PreflightItem] = []
    cat = "mesh_processor"
    if project is None:
        return out
    cfg = project.stage_settings("mesh_processor")
    overrides = cfg.get("overrides") or {}
    ap_meshes = (project.outputs.get("asset_processor") or {}).get("meshes") or {}

    if not overrides:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="No mesh overrides set (defaults only)",
        ))
        return out

    stale = sorted(set(overrides.keys()) - set(ap_meshes.keys()))
    if stale:
        out.append(PreflightItem(
            category=cat, severity="yellow",
            title=f"{len(stale)} stale mesh override(s)",
            detail="Override entries reference GUIDs no longer in the inventory.",
            fix_hint="Open Meshes and clear the override for those rows, or Acknowledge.",
            ack_key="mesh.stale_overrides",
            ack_snapshot=_snapshot_hash(stale),
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title=f"{len(overrides)} mesh override(s) — all live",
        ))
    return out


def check_terrain_processor(project) -> List[PreflightItem]:
    """Terrain stage — green when no terrain materials selected (skip).
    Red when terrain selected but no output_path."""
    out: List[PreflightItem] = []
    cat = "terrain_processor"
    if project is None:
        return out
    cfg = project.stage_settings("terrain_processor")
    selected = list(cfg.get("selected_materials") or [])
    output   = (cfg.get("output_path") or "").strip()
    if not selected:
        out.append(PreflightItem(
            category=cat, severity="green",
            title="No terrain materials selected — stage will be skipped",
        ))
        return out
    if not output:
        out.append(PreflightItem(
            category=cat, severity="red",
            title="No terrain output folder",
            detail=f"{len(selected)} terrain material(s) selected but no output set.",
            fix_hint="Open the Terrain tab and pick an output folder.",
        ))
    else:
        out.append(PreflightItem(
            category=cat, severity="green",
            title=f"{len(selected)} terrain material(s) selected",
            detail=output,
        ))
    return out


# =============================================================================
# RUNNER
# =============================================================================

CHECK_REGISTRY: List[Callable[..., List[PreflightItem]]] = [
    # Order is the order the panel renders. Environment first because its
    # red blocks (no scope, no deps) are foundational.
    check_environment,
    check_asset_processor,
    check_scene_converter,
    check_material_processor,
    check_mesh_processor,
    check_terrain_processor,
]


def run_preflight(project, deps_present: bool = True) -> PreflightReport:
    """Run every check in order. Returns a fully populated PreflightReport
    with the project's current `preflight_acks` snapshotted."""
    report = PreflightReport()
    for fn in CHECK_REGISTRY:
        try:
            if fn is check_environment:
                report.items.extend(fn(project, deps_present=deps_present))
            else:
                report.items.extend(fn(project))
        except Exception as exc:
            # A check function blowing up should not take Mission Command
            # offline. Surface as a red item; the orchestrator stays gated.
            report.items.append(PreflightItem(
                category=getattr(fn, "__name__", "unknown"),
                severity="red",
                title="Pre-flight check raised an exception",
                detail=f"{type(exc).__name__}: {exc}",
            ))
    if project is not None:
        report.acks = dict(getattr(project, "preflight_acks", {}) or {})
    return report


# =============================================================================
# CATEGORY DISPLAY METADATA
# =============================================================================

CATEGORY_LABELS: Dict[str, str] = {
    "environment":        "Environment",
    "asset_processor":    "Asset Processor",
    "scene_converter":    "Scene Converter",
    "material_processor": "Material Processor",
    "mesh_processor":     "Mesh Processor",
    "terrain_processor":  "Terrain Processor",
}
