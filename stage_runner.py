"""
=============================================================================
STAGE RUNNER
=============================================================================

The stage runs of the converter, free of any window. The GUI tabs and the
command line (``converter_cli.py``) both call these functions, so a stage
does the same thing however it is started.

    run_asset_processor(...)   Stage 1: prefabs, materials, textures, meshes
    run_scene_converter(...)   Stage 2: scenes to levels
    store_run(...)             write a run's bookkeeping into the project
    input_hash_for(...)        fingerprint of everything a stage reads

A run returns a ``StageRun``. It does not touch the project: the caller
stores it with ``store_run``, into the live ``ProjectManager`` (the GUI) or
into a ``Project`` it holds (the command line).

This module imports no widgets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional


# =============================================================================
# RESULT OF ONE STAGE RUN
# =============================================================================

@dataclass
class StageRun:
    """What one stage run produced, for the project file and for the user.

    ``outputs``      the stage's section of ``project.outputs`` (the caller
                     adds ``last_input_hash``).
    ``status``       the stage's section of ``project.pipeline_status``.
    ``state_index``  Stage 1 only: this run's per-asset fingerprints, merged
                     onto the project's existing index by ``store_run``.
    ``totals``       Stage 2 only: the counts its tab shows after a run.
    """
    stage_key:   str
    summary:     str
    errors:      int
    outputs:     dict = field(default_factory=dict)
    status:      dict = field(default_factory=dict)
    state_index: dict = field(default_factory=dict)
    totals:      dict = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# STAGE 1 - ASSET PROCESSOR
# =============================================================================

def run_asset_processor(source_path: str, output_path: str, prefab_files: list, *,
                        material_settings: Optional[dict],
                        mesh_settings: Optional[dict],
                        collision_settings: Optional[dict],
                        strip_lods: bool,
                        convert_smoothness_to_roughness: bool,
                        log: Callable[[str], None],
                        trace=None) -> StageRun:
    """Convert the given Unity prefabs, with every material, texture and
    mesh they use, into ``output_path``. ``trace`` is an optional
    ``conversion_trace.ConversionTrace``."""
    from integrated_asset_processor import IntegratedAssetProcessor

    log("\n" + "=" * 60)
    log("STARTING ASSET PROCESSING")
    log("=" * 60)

    processor = IntegratedAssetProcessor(
        Path(source_path),
        Path(output_path),
        log_callback=log,
        convert_smoothness_to_roughness=convert_smoothness_to_roughness,
        material_settings=material_settings,
        mesh_settings=mesh_settings,
        collision_settings=collision_settings,
        strip_lods=strip_lods,
        trace=trace,
    )

    log(f"\nProcessing {len(prefab_files)} selected Unity prefab(s)")

    # A prefab is converted after the ones it nests: placing its overrides
    # needs the nested prefab's entity map.
    from platforms.unity.prefab import nested_prefabs_first
    prefab_files = nested_prefabs_first(list(prefab_files), processor.asset_db.path_to_guid)

    success_count = 0
    for i, prefab_file in enumerate(prefab_files, 1):
        log(f"\n[{i}/{len(prefab_files)}] {prefab_file.name}")
        if processor.process_prefab(prefab_file):
            success_count += 1

    processor.finalize()

    # Merge asset-level counts into stats dict (displayed first)
    asset_stats = {
        "Materials created": len(processor.processed_materials),
        "Textures copied":   len(processor.processed_textures),
        "Meshes copied":     len(processor.processed_meshes),
    }
    asset_stats.update(processor.stats)

    log("\n" + "=" * 60)
    log("PROCESSING COMPLETE!")
    log("=" * 60)
    log(f"Prefabs processed : {success_count}/{len(prefab_files)}")
    for label, count in asset_stats.items():
        log(f"{label:<20}: {count}")
    log(f"Output            : {output_path}")
    log("=" * 60)

    run_ts = _utc_now_iso()
    errors = max(0, len(prefab_files) - success_count)

    outputs = processor.to_outputs()
    outputs["last_run"]    = run_ts
    outputs["last_status"] = "warn" if errors else "ok"

    summary_parts = [f"Prefabs: {success_count}/{len(prefab_files)}"]
    summary_parts += [f"{label}: {count}" for label, count in asset_stats.items()]

    return StageRun(
        stage_key="asset_processor",
        summary="  |  ".join(summary_parts),
        errors=errors,
        outputs=outputs,
        state_index=processor.state_index(),
        status={
            "last_run":          run_ts,
            "prefabs_processed": success_count,
            "prefabs_total":     len(prefab_files),
            "materials_written": len(processor.processed_materials),
            "textures_copied":   len(processor.processed_textures),
            "meshes_copied":     len(processor.processed_meshes),
            "errors":            errors,
        },
    )


# =============================================================================
# STAGE 2 - SCENE CONVERTER
# =============================================================================

def asset_stage_arguments(project, convert_smoothness_to_roughness: bool) -> Optional[dict]:
    """What Stage 1 runs with, read off a conversion project, for
    ``run_scene_converter``: a scene's own objects have their materials and
    models converted the way a prefab's are, into the same output folder.
    None when the project names no source or no Stage 1 output."""
    import copy

    settings = project.stage_settings("asset_processor")
    source = project.effective_source("asset_processor")
    output = (settings.get("output_path") or "").strip()
    if not source or not Path(source).is_dir() or not output:
        return None
    return {
        "source_path":        source,
        "output_path":        output,
        "material_settings":  copy.deepcopy(project.stage_settings("material_processor")),
        "mesh_settings":      copy.deepcopy(project.stage_settings("mesh_processor")),
        "collision_settings": copy.deepcopy(project.stage_settings("collision_processor")),
        "strip_lods":         bool(settings.get("strip_lods", True)),
        "convert_smoothness_to_roughness": convert_smoothness_to_roughness,
        "state_index":        copy.deepcopy(project.outputs.get("state_index") or {}),
    }


def run_scene_converter(scenes: list, output_dir: str, prefab_dirs: list,
                        asset_processor_outputs: dict,
                        log: Callable[[str], None],
                        trace=None,
                        asset_stage: Optional[dict] = None) -> StageRun:
    """Serial multi-scene conversion. Each scene gets its own
    UnitySceneConverter, output goes into <output>/<SceneName>/.

    ``asset_processor_outputs`` is the project's Stage 1 outputs section: the
    per-scene converters resolve entity maps and asset hints from it.

    ``asset_stage`` is ``asset_stage_arguments(project, ...)``. With it the
    scenes' own objects (the ones that are not prefab instances) get their
    materials and models converted by one Stage 1 worker shared by the run;
    without it they are placed without them."""
    from platforms.unity.scene_converter import PrefabDatabase, UnitySceneConverter

    log("\n" + "=" * 60)
    log("STARTING MULTI-SCENE CONVERSION")
    log("=" * 60)
    log(f"Scenes : {len(scenes)}")
    log(f"Output : {output_dir}")
    log(f"Prefab search dirs: {len(prefab_dirs)}")
    log("=" * 60)

    prefab_db = PrefabDatabase()
    for d in prefab_dirs:
        prefab_db.add_search_directory(Path(d))

    ap_outputs = asset_processor_outputs or {}
    ap_prefabs = ap_outputs.get("prefabs", {})  # guid_or_stem → record
    entity_maps_by_stem: dict = {}
    for record in ap_prefabs.values():
        stem = Path(record.get("output_path", "")).stem
        if stem:
            entity_maps_by_stem[stem] = record
        # A placed prefab is found by the guid the scene names it by. The
        # name of an instance is only what the scene's author called it: a
        # renamed instance would be missed, or take another prefab's place.
        if stem and record.get("source_guid"):
            prefab_db.add_guid_mapping(record["source_guid"], stem)

    # One Stage 1 worker for the run, for what the scenes' own objects show.
    asset_processor = None
    if asset_stage:
        from integrated_asset_processor import IntegratedAssetProcessor
        asset_processor = IntegratedAssetProcessor(
            Path(asset_stage["source_path"]),
            Path(asset_stage["output_path"]),
            log_callback=log,
            convert_smoothness_to_roughness=asset_stage.get("convert_smoothness_to_roughness", False),
            material_settings=asset_stage.get("material_settings"),
            mesh_settings=asset_stage.get("mesh_settings"),
            collision_settings=asset_stage.get("collision_settings"),
            strip_lods=asset_stage.get("strip_lods", True),
            state_index=asset_stage.get("state_index"),
            trace=trace,
        )
    asset_index_for_scene = {
        "materials": dict(ap_outputs.get("materials", {})),
        "meshes":    dict(ap_outputs.get("meshes",    {})),
        "prefabs":   {g: r.get("source_path", "") for g, r in ap_prefabs.items()},
    }

    totals = {
        "scenes_converted":      0,
        "total_entities":        0,
        "total_prefab_refs":     0,
        "total_missing_prefabs": 0,
        "failures":              [],
    }
    # Per-scene records accumulated into project.outputs.scene_converter.
    scene_records: dict = {}
    # Coverage from the last scene that converted (Stage 2's coverage
    # is global to the run rather than per-scene; this is one source).
    last_coverage: dict = {}

    for i, scene_path in enumerate(scenes, 1):
        scene_stem    = scene_path.stem
        scene_out_dir = Path(output_dir) / scene_stem
        scene_out_dir.mkdir(parents=True, exist_ok=True)
        level_prefab  = scene_out_dir / f"{scene_stem}.prefab"

        log(f"\n[{i}/{len(scenes)}] {scene_path.name}  →  {scene_out_dir.name}/")
        try:
            conv = UnitySceneConverter(
                prefab_db, log_callback=log,
                entity_maps_by_stem=entity_maps_by_stem,
                asset_index=asset_index_for_scene,
                trace=trace,
                asset_processor=asset_processor,
            )
            conv.parse_unity_scene(str(scene_path))
            log(f"  Parsed {len(conv.game_objects)} GameObject(s)")
            prefab_instances = sum(
                1 for go in conv.game_objects.values() if go.is_prefab_instance
            )
            log(f"  Prefab instances: {prefab_instances}, "
                f"resolved: {len(conv.prefab_references)}, "
                f"missing: {len(conv.missing_prefabs)}")

            total, refs, blanks = conv.create_o3de_level(
                str(level_prefab), scene_out_dir
            )
            conv.finalize(scene_out_dir)

            # Record this scene's outputs for the project file.
            try:
                output_rel = str(level_prefab.relative_to(Path(output_dir)))
            except Exception:
                output_rel = level_prefab.name
            scene_records[scene_path.name] = {
                "output_path":       output_rel.replace("\\", "/"),
                "entities":          total,
                "prefab_references": refs,
                "blanks":            blanks,
                "missing_prefabs":   sorted(conv.missing_prefabs),
                "written_at":        _utc_now_iso(),
            }
            last_coverage = conv.to_coverage()

            totals["scenes_converted"]      += 1
            totals["total_entities"]        += total
            totals["total_prefab_refs"]     += refs
            totals["total_missing_prefabs"] += len(conv.missing_prefabs)
            log(f"  ✓ Wrote {level_prefab.name}")
        except Exception as exc:
            log(f"  ✗ Scene failed: {exc}")
            totals["failures"].append(scene_path.name)

    log("\n" + "=" * 60)
    log("CONVERSION COMPLETE!")
    log("=" * 60)
    log(f"Scenes converted   : {totals['scenes_converted']}/{len(scenes)}")
    log(f"Total entities     : {totals['total_entities']}")
    log(f"Total prefab refs  : {totals['total_prefab_refs']}")
    log(f"Total missing refs : {totals['total_missing_prefabs']}")
    if totals["failures"]:
        log(f"Failures           : {', '.join(totals['failures'])}")
    log("=" * 60)

    run_ts = _utc_now_iso()
    had_errors = (totals["total_missing_prefabs"] > 0
                  or len(totals["failures"]) > 0)

    return StageRun(
        stage_key="scene_converter",
        summary=(
            f"Scenes: {totals['scenes_converted']}/{len(scenes)}  |  "
            f"Entities: {totals['total_entities']}  |  "
            f"Prefab refs: {totals['total_prefab_refs']}  |  "
            f"Missing: {totals['total_missing_prefabs']}"
        ),
        errors=len(totals["failures"]),
        outputs={
            "last_run":    run_ts,
            "last_status": "warn" if had_errors else "ok",
            "scenes":      scene_records,
            "coverage":    last_coverage,
        },
        status={
            "last_run":                run_ts,
            "scenes_converted":        totals["scenes_converted"],
            "scenes_total":            len(scenes),
            "total_entities":          totals["total_entities"],
            "total_prefab_references": totals["total_prefab_refs"],
            "total_missing_prefabs":   totals["total_missing_prefabs"],
        },
        # The models and materials the scenes' own objects brought in: merged
        # onto the project's index, so a later run keeps their mesh groups.
        state_index=asset_processor.state_index() if asset_processor is not None else {},
        totals=totals,
    )


# =============================================================================
# BOOKKEEPING
# =============================================================================

def store_run(sink, project, run: StageRun, input_hash: str) -> None:
    """Write a run's bookkeeping into the project.

    ``sink`` is what receives it: the ``ProjectManager`` in the GUI (which
    announces the change to the tabs) or the ``Project`` itself on the
    command line. Both offer ``update_outputs`` and ``update_status``.
    ``project`` is the project the existing state index is read from."""
    outputs = dict(run.outputs)
    outputs["last_input_hash"] = input_hash
    sink.update_outputs(run.stage_key, outputs)

    # Merge this run's state index onto the existing one, so assets the run
    # did not touch keep their fingerprints for the patch worker.
    if run.state_index and project is not None:
        existing = dict(project.outputs.get("state_index") or {})
        for bucket_name, bucket in run.state_index.items():
            merged = dict(existing.get(bucket_name) or {})
            merged.update(bucket)
            existing[bucket_name] = merged
        sink.update_outputs("state_index", existing)

    sink.update_status(run.stage_key, run.status)


# =============================================================================
# INPUT FINGERPRINT
# =============================================================================

def _fingerprint_file(p) -> int:
    try:
        return int(Path(p).stat().st_mtime)
    except Exception:
        return 0


def input_hash_for(stage_key: str, project) -> str:
    """Stable 16-char SHA-256 prefix over every input that affects this
    stage's output. Recomputing for the same inputs returns the same hash;
    changing any path / selection / file mtime changes the hash."""
    if project is None:
        return ""

    cfg     = project.stage_settings(stage_key)
    source  = project.effective_source(stage_key)
    payload = {
        "scope_root":       str(project.scope_root) if project.scope_root else "",
        "effective_source": source,
        "output_path":      (cfg.get("output_path") or "").strip(),
    }

    if stage_key == "asset_processor":
        selected = sorted(cfg.get("selected_prefabs", []) or [])
        payload["selected_prefabs"] = selected
        if source:
            payload["files"] = {
                rel: _fingerprint_file(Path(source) / rel) for rel in selected
            }
        else:
            payload["files"] = {}

    elif stage_key == "scene_converter":
        selected = sorted(cfg.get("selected_scenes", []) or [])
        payload["selected_scenes"] = selected
        payload["prefab_dirs"]     = sorted(cfg.get("prefab_dirs", []) or [])
        if source:
            payload["files"] = {
                rel: _fingerprint_file(Path(source) / rel)
                for rel in selected
            }
        else:
            payload["files"] = {}

    elif stage_key == "terrain_processor":
        selected = sorted(cfg.get("selected_terrains", []) or [])
        payload["selected_terrains"] = selected
        payload["outputs"] = sorted(cfg.get("outputs", []) or [])
        payload["files"] = {t: _fingerprint_file(t) for t in selected}

    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
