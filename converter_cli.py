#!/usr/bin/env python3
"""
=============================================================================
CONVERTER CLI
=============================================================================

The converter without its window. Every command takes a conversion project
file (``.u2oproj.json``), the same file the GUI opens and saves. No command
writes to that file.

    python converter_cli.py describe <project> [--set key=value ...] [--full]
    python converter_cli.py run      <project> [--stage asset_processor|scene_converter|all]
                                               [--only <wildcard>] [--set key=value ...]
                                               [--trace <folder>] [--project-out <file>]
                                               [--seed <n>] [--log <file>] [--quiet]
    python converter_cli.py truth    <project> --out <folder> [--check] [--fresh]
                                               [--only <wildcard>] [--unity <exe>]

``describe``  prints the effective settings of every stage, the registered
              component processors and the coverage of the last run.
``run``       runs stages the way the GUI's Process buttons do, through the
              same functions (``stage_runner``).
``truth``     has the Unity Editor write the truth dump of the project's
              scope and marked scenes (``platforms/unity/bridge``).

``--set`` changes one setting for this run only, by its path under the
project's stages: ``--set mesh_processor.defaults.auto_center=false``.
The value is read as JSON when it parses, else as text.

Exit codes: 0 done, 1 failed, 2 refused (something the command needs is
missing; the message says what).
"""

from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import random
import sys
import uuid
from pathlib import Path
from typing import Callable, List, Optional

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2
SETTINGS_FILE = REPO_ROOT / "converter_settings.json"


class Refused(Exception):
    """The command cannot start; the message says what is missing."""


# =============================================================================
# PROJECT FILE AND SETTINGS
# =============================================================================

def load_project(project_file: Path):
    """Open a conversion project file the way the GUI does, defaults merged."""
    from project_manager import Project
    project_file = Path(project_file)
    return Project.from_json(json.loads(project_file.read_text(encoding="utf-8")), project_file)


def global_config() -> dict:
    """The converter-wide toggles of ``converter_settings.json``, as the
    GUI's Config tab reads them."""
    try:
        config = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("config", {}) or {}
    except (OSError, ValueError):
        config = {}
    return {"convert_smoothness_to_roughness": bool(config.get("convert_smoothness_to_roughness", False))}


def apply_overrides(project, assignments: List[str]) -> None:
    """Apply ``--set stage.key.sub=value`` assignments to the project in
    memory. The first key must be an existing stage; deeper keys are made
    when missing (a new per-asset override, for example)."""
    for assignment in assignments or []:
        path, separator, raw = assignment.partition("=")
        keys = [key for key in path.strip().split(".") if key]
        if not separator or len(keys) < 2:
            raise Refused(f"--set needs stage.key=value, got '{assignment}'.")
        if keys[0] not in project.stages:
            raise Refused(f"--set: '{keys[0]}' is not a stage "
                          f"(stages: {', '.join(sorted(project.stages))}).")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw

        target = project.stages[keys[0]]
        for key in keys[1:-1]:
            if not isinstance(target.get(key), dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value


def marked_scenes(project) -> List[Path]:
    """The scenes marked on the scene converter stage, as files."""
    root = project.effective_source("scene_converter")
    marks = project.stage_settings("scene_converter").get("selected_scenes", [])
    return [Path(root) / relative for relative in sorted(marks)] if root else []


def marked_prefabs(project, only: str = "") -> List[Path]:
    """The prefabs marked on the asset processor stage, as files. A project
    with no marks means every prefab under the stage's source. ``only`` is a
    wildcard on the file name without its extension."""
    root = project.effective_source("asset_processor")
    if not root:
        return []
    marks = project.stage_settings("asset_processor").get("selected_prefabs", [])
    if not marks:
        marks = [path.relative_to(root).as_posix() for path in Path(root).rglob("*.prefab")]
    files = [Path(root) / relative for relative in sorted(marks)]
    if only:
        files = [path for path in files if fnmatch.fnmatch(path.stem.lower(), only.lower())]
    return [path for path in files if path.is_file()]


# =============================================================================
# COMMAND: describe
# =============================================================================

def command_describe(arguments) -> int:
    project = load_project(arguments.project)
    apply_overrides(project, arguments.set)

    print(f"Project : {project.name}")
    print(f"Scope   : {project.scope_root}")
    print(f"O3DE    : {project.o3de_project_root}")
    print(f"Global  : {json.dumps(global_config())}")

    # ----- Stage settings ----------------------------------------------------
    for stage_key in sorted(project.stages):
        settings = copy.deepcopy(project.stages[stage_key])
        if not arguments.full:
            _shorten(settings)
        print(f"\n=== Stage: {stage_key} ===")
        print(json.dumps(settings, indent=2, default=str))

    # ----- Component processors ----------------------------------------------
    from platforms import get as get_platform
    platform = get_platform(project.active_platform)
    print(f"\n=== Component processors ({project.active_platform}) ===")
    print(f"{'weight':>6}  {'processor':<28} handles -> emits")
    for processor in (platform.component_processors() if platform else []):
        print(f"{processor.WEIGHT:>6}  {type(processor).__name__:<28} "
              f"{', '.join(processor.HANDLES) or '-'} -> {', '.join(processor.EMITS) or '-'}")

    # ----- Coverage of the last run ------------------------------------------
    for stage_key in ("asset_processor", "scene_converter"):
        outputs = project.outputs.get(stage_key) or {}
        coverage = outputs.get("coverage") or {}
        print(f"\n=== Coverage of the last {stage_key} run "
              f"({outputs.get('last_run') or 'never run'}) ===")
        if not coverage:
            print("  nothing recorded")
            continue
        for name, entry in sorted((coverage.get("components") or {}).items()):
            handled = "handled" if entry.get("handled") else "NOT HANDLED"
            print(f"  component {name:<28} seen {entry.get('seen', 0):>5}  {handled}")
        for path, entry in sorted((coverage.get("prefab_overrides") or {}).items()):
            handled = "handled" if entry.get("handled") else "NOT HANDLED"
            print(f"  override  {path:<28} seen {entry.get('seen', 0):>5}  {handled}")
        for kind, guids in sorted((coverage.get("missing_assets") or {}).items()):
            if guids:
                print(f"  missing   {kind:<28} {len(guids)}")
        warnings = coverage.get("warnings") or []
        print(f"  warnings: {len(warnings)}")
        for warning in warnings[: None if arguments.full else 5]:
            print(f"    {warning}")
    return EXIT_OK


def _shorten(settings: dict) -> None:
    """Replace the long tables of a stage's settings with their size."""
    for key in ("shader_profiles", "selected_prefabs", "selected_scenes", "layer_names", "group_names"):
        value = settings.get(key)
        if isinstance(value, (dict, list)) and len(value) > 8:
            settings[key] = f"<{len(value)} entries; --full shows them>"
        elif key == "shader_profiles" and isinstance(value, dict):
            settings[key] = {name: "<profile; --full shows it>" for name in value}


# =============================================================================
# COMMAND: run
# =============================================================================

def command_run(arguments) -> int:
    from stage_runner import input_hash_for, run_asset_processor, run_scene_converter, store_run

    project = load_project(arguments.project)
    apply_overrides(project, arguments.set)
    stages = ["asset_processor", "scene_converter"] if arguments.stage == "all" else [arguments.stage]

    log_file = None
    if arguments.log:
        Path(arguments.log).parent.mkdir(parents=True, exist_ok=True)
        log_file = open(arguments.log, "w", encoding="utf-8")

    def log(line) -> None:
        if log_file:
            log_file.write(str(line) + "\n")
        if not arguments.quiet:
            print(line)

    trace = None
    if arguments.trace:
        from conversion_trace import ConversionTrace
        trace = ConversionTrace()

    errors = 0
    try:
        for stage_key in stages:
            # Component ids and mesh group ids are random; a seed makes two
            # runs write the same files, so only what really changed is
            # cooked again.
            if arguments.seed is not None:
                random.seed(arguments.seed)
                uuid.uuid4 = _seeded_uuid4
            runner = _run_stage_1 if stage_key == "asset_processor" else _run_stage_2
            run = runner(project, arguments, log, trace, run_asset_processor, run_scene_converter)
            store_run(project, project, run, input_hash_for(stage_key, project))
            errors += run.errors
            print(f"[run] {stage_key}: {run.summary}")
    finally:
        if log_file:
            log_file.close()

    if trace is not None:
        from conversion_trace import uncovered_in_output
        trace.write(Path(arguments.trace))
        uncovered = uncovered_in_output(trace)
        print(f"[run] trace: {len(trace.prefabs)} prefab(s), {len(trace.scenes)} scene(s), "
              f"{len(trace.assetinfos)} assetinfo write(s), {len(uncovered)} emitted value(s) not covered")
        for problem in uncovered[:20]:
            print(f"[run]   {problem}")
        errors += len(uncovered)

    if arguments.project_out:
        out_file = Path(arguments.project_out)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(project.to_json(), indent=2), encoding="utf-8")
        print(f"[run] project with this run's bookkeeping: {out_file}")

    return EXIT_OK if errors == 0 else EXIT_FAILED


def _seeded_uuid4() -> uuid.UUID:
    """A version 4 UUID drawn from the seeded ``random`` generator."""
    return uuid.UUID(int=random.getrandbits(128), version=4)


def _run_stage_1(project, arguments, log: Callable, trace, run_asset_processor, _unused):
    settings = project.stage_settings("asset_processor")
    source = project.effective_source("asset_processor")
    output = (settings.get("output_path") or "").strip()
    if not source or not Path(source).is_dir():
        raise Refused(f"asset_processor: the source folder is not set or not found: '{source}'.")
    if not output:
        raise Refused("asset_processor: the project names no output folder.")

    prefabs = marked_prefabs(project, arguments.only)
    if not prefabs:
        raise Refused("asset_processor: no prefab to process.")
    if not settings.get("selected_prefabs"):
        log(f"[run] no prefabs are marked in the project: taking all {len(prefabs)} under the source.")

    return run_asset_processor(
        source, output, prefabs,
        material_settings=copy.deepcopy(project.stage_settings("material_processor")),
        mesh_settings=copy.deepcopy(project.stage_settings("mesh_processor")),
        collision_settings=copy.deepcopy(project.stage_settings("collision_processor")),
        strip_lods=bool(settings.get("strip_lods", True)),
        convert_smoothness_to_roughness=global_config()["convert_smoothness_to_roughness"],
        log=log, trace=trace,
    )


def _run_stage_2(project, arguments, log: Callable, trace, _unused, run_scene_converter):
    settings = project.stage_settings("scene_converter")
    output = (settings.get("output_path") or "").strip()
    scenes = [scene for scene in marked_scenes(project) if scene.is_file()]
    if not output:
        raise Refused("scene_converter: the project names no output folder.")
    if not scenes:
        raise Refused("scene_converter: no marked scene exists on disk.")

    # Converted prefabs are looked up where Stage 1 wrote them.
    prefab_dirs = []
    stage_1_output = (project.stage_settings("asset_processor").get("output_path") or "").strip()
    if stage_1_output:
        prefab_dirs.append(str(Path(stage_1_output) / "Prefabs"))
    prefab_dirs += [d for d in settings.get("prefab_dirs", []) if d and d not in prefab_dirs]

    return run_scene_converter(scenes, output, prefab_dirs,
                               project.outputs.get("asset_processor", {}), log, trace)


# =============================================================================
# COMMAND: truth
# =============================================================================

def command_truth(arguments) -> int:
    from platforms.unity.bridge import TruthRequest, run_truth_dump

    project = load_project(arguments.project)
    if project.scope_root is None:
        raise Refused("truth: the project has no scope root.")

    request = TruthRequest(
        scope_root=project.scope_root,
        out_base=Path(arguments.out),
        scenes=marked_scenes(project),
        only=arguments.only,
        mode="check" if arguments.check else "dump",
        unity_exe=Path(arguments.unity) if arguments.unity else None,
        fresh=arguments.fresh,
        timeout_s=arguments.timeout,
    )
    result = run_truth_dump(request)

    print(f"[truth] {result.status} in {result.seconds:.0f} s")
    for problem in result.problems:
        print(f"[truth]   {problem}")
    if result.dump_dir:
        print(f"[truth] dump: {result.dump_dir}")
    done = result.done
    if done:
        print(f"[truth] Unity {done.get('unityVersion', '?')}: "
              f"{done.get('prefabs', 0)} prefab(s), {done.get('models', 0)} model(s), "
              f"{done.get('scenes', 0)} scene(s), {done.get('objects', 0)} object(s), "
              f"{done.get('meshes', 0)} mesh(es), {done.get('vertices', 0)} vertices, "
              f"{done.get('matrixMismatches', 0)} matrix mismatch(es)")
        for warning in done.get("warnings", []):
            print(f"[truth]   warning: {warning}")

    if result.status == "refused":
        return EXIT_REFUSED
    return EXIT_OK if result.ok else EXIT_FAILED


# =============================================================================
# ARGUMENTS
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="converter_cli.py",
        description="The To-O3DE Project Converter without its window.")
    commands = parser.add_subparsers(dest="command", required=True)

    describe = commands.add_parser("describe", help="print settings, component processors and last coverage")
    describe.add_argument("project", help="conversion project file (.u2oproj.json)")
    describe.add_argument("--set", action="append", default=[], metavar="stage.key=value")
    describe.add_argument("--full", action="store_true", help="print the long tables too")
    describe.set_defaults(run=command_describe)

    run = commands.add_parser("run", help="run stages the way the GUI's Process buttons do")
    run.add_argument("project", help="conversion project file (.u2oproj.json)")
    run.add_argument("--stage", choices=["asset_processor", "scene_converter", "all"], default="all")
    run.add_argument("--only", default="", help="wildcard on prefab file names, e.g. Desk_*")
    run.add_argument("--set", action="append", default=[], metavar="stage.key=value",
                     help="change one setting for this run only")
    run.add_argument("--trace", default="", help="folder to write the conversion trace to")
    run.add_argument("--project-out", default="", help="file to write the project with this run's bookkeeping to")
    run.add_argument("--seed", type=int, default=None, help="seed for the random component and mesh group ids")
    run.add_argument("--log", default="", help="file to write the full log to")
    run.add_argument("--quiet", action="store_true", help="print only the summary lines")
    run.set_defaults(run=command_run)

    truth = commands.add_parser("truth", help="have Unity write the truth dump of the project's scope")
    truth.add_argument("project", help="conversion project file (.u2oproj.json)")
    truth.add_argument("--out", required=True, help="folder the dump is written under")
    truth.add_argument("--check", action="store_true",
                       help="only start Unity, compile the bridge script and count the assets")
    truth.add_argument("--fresh", action="store_true", help="ignore a cached dump")
    truth.add_argument("--only", default="", help="wildcard on asset file names, e.g. Desk_*")
    truth.add_argument("--unity", default="", help="Unity executable to use")
    truth.add_argument("--timeout", type=float, default=3600.0, help="seconds before Unity is killed")
    truth.set_defaults(run=command_truth)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return arguments.run(arguments)
    except Refused as refusal:
        print(f"[{arguments.command}] refused: {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
