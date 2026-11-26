#!/usr/bin/env python3
"""
=============================================================================
PARITY HARNESS
=============================================================================

Compares what the converter makes with what Unity holds. See README.md.

    python parity/parity.py setup   <config>              register the probe gem in the O3DE project
    python parity/parity.py truth   <config> [--fresh]    Unity truth dump (cached)
    python parity/parity.py convert <config> [--only W] [--set k=v ...]
    python parity/parity.py bake    <config> [--fresh]    the measurement level
    python parity/parity.py cook    <config>              Asset Processor, batch
    python parity/parity.py probe   <config>              Editor session on the baked level
    python parity/parity.py compare <config>              truth against the O3DE record
    python parity/parity.py cycle   <config> [--only W] [--set k=v ...]   all of the above, in order

A config (``parity/configs/office.json``) names a conversion project file,
the baked level, the seed and the tolerances. Everything a run writes goes to
``<O3DE project>/user/Parity``; nothing derived from the source assets is
written into this repository.

Close the Editor and the Asset Processor before ``cook``, ``probe`` and
``cycle``; close the Unity project before ``truth``.

Exit codes: 0 done, 1 failed, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for path in (str(REPO_ROOT), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

import converter_cli                      # noqa: E402
import level_bake                         # noqa: E402
import o3de_run                           # noqa: E402
from records import latest_truth          # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2
PROBE_GEM = HERE / "o3de" / "ParityProbe"


class Refused(Exception):
    """The command cannot start; the message says what is missing."""


# =============================================================================
# CONFIG AND FOLDERS
# =============================================================================

class Bed:
    """One test bed: the config, its conversion project, and where runs go."""

    def __init__(self, config_file: Path) -> None:
        self.config_file = Path(config_file).resolve()
        self.config = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.project_file = (self.config_file.parent / self.config["project"]).resolve()
        self.project = converter_cli.load_project(self.project_file)
        if self.project.o3de_project_root is None or not self.project.o3de_project_root.is_dir():
            raise Refused(f"The conversion project names no O3DE project root that exists: "
                          f"{self.project.o3de_project_root}")
        self.o3de_root: Path = self.project.o3de_project_root
        # Each bed keeps its runs in a folder of its own under the project's
        # user folder: "work" in the config, "Parity" when it names none. Two
        # beds on one O3DE project must not write over each other's truth,
        # trace and report.
        self.work: Path = self.o3de_root / "user" / self.config.get("work", "Parity")
        self.level: str = self.config["level"]
        self.output: Path = Path(self.project.stage_settings("asset_processor")["output_path"])

    # ----- Folders of the latest run of each step ------------------------------
    @property
    def truth_base(self) -> Path:    return self.work / "truth"
    @property
    def convert_dir(self) -> Path:   return self.work / "convert"
    @property
    def cook_dir(self) -> Path:      return self.work / "cook"
    @property
    def probe_dir(self) -> Path:     return self.work / "probe"
    @property
    def report_dir(self) -> Path:    return self.work / "report"

    def converted_prefabs(self) -> List[Path]:
        return sorted((self.output / "Prefabs").glob("*.prefab"))

    def recipe(self) -> dict:
        """The recipe the measurement level must have for the current state."""
        truth = latest_truth(self.truth_base)
        if truth is None:
            raise Refused("There is no truth dump yet: run 'truth' first.")
        prefabs = self.converted_prefabs()
        if not prefabs:
            raise Refused("There are no converted prefabs yet: run 'convert' first.")
        radii = {Path(entry["assetPath"]).stem: truth.prefab_radius(truth.hierarchy(entry))
                 for entry in truth.prefab_entries()}
        return level_bake.make_recipe(self.o3de_root, prefabs, radii,
                                      level_bake.nested_source_folder(prefabs))


def run_python(script: Path, *arguments: str) -> int:
    """Run one of the converter's own commands as a separate process."""
    return subprocess.run([sys.executable, str(script), *arguments], cwd=str(REPO_ROOT)).returncode


# =============================================================================
# STEPS
# =============================================================================

def step_setup(bed: Bed, arguments) -> int:
    """Register and enable the probe gem in the O3DE project. It is built
    with the project (target ParityProbe.Editor) after a configure."""
    project_json = bed.o3de_root / "project.json"
    project = json.loads(project_json.read_text(encoding="utf-8"))
    gem_path = PROBE_GEM.as_posix()
    changed = False
    if gem_path not in project.setdefault("external_subdirectories", []):
        project["external_subdirectories"].append(gem_path)
        changed = True
    if "ParityProbe" not in project.setdefault("gem_names", []):
        project["gem_names"].append("ParityProbe")
        changed = True
    if changed:
        project_json.write_text(json.dumps(project, indent=4) + "\n", encoding="utf-8")
    built = (bed.o3de_root / "build" / "windows" / "bin" / "profile" / "ParityProbe.Editor.dll").is_file()
    print(f"[setup] ParityProbe {'registered' if changed else 'already registered'} in {project_json}")
    print(f"[setup] module built: {'yes' if built else 'NO - configure the project and build target ParityProbe.Editor'}")
    return EXIT_OK if built else EXIT_FAILED


def step_truth(bed: Bed, arguments) -> int:
    extra = ["--fresh"] if getattr(arguments, "fresh", False) else []
    return run_python(REPO_ROOT / "converter_cli.py", "truth", str(bed.project_file),
                      "--out", str(bed.truth_base), *extra)


def step_convert(bed: Bed, arguments) -> int:
    extra: List[str] = []
    if getattr(arguments, "only", ""):
        extra += ["--only", arguments.only]
    for assignment in getattr(arguments, "set", []) or []:
        extra += ["--set", assignment]
    return run_python(REPO_ROOT / "converter_cli.py", "run", str(bed.project_file),
                      "--seed", str(bed.config.get("seed", 1234)), "--quiet",
                      "--log", str(bed.convert_dir / "run.log"),
                      "--trace", str(bed.convert_dir / "trace"),
                      "--project-out", str(bed.convert_dir / "project.u2oproj.json"), *extra)


def step_bake(bed: Bed, arguments) -> int:
    recipe = bed.recipe()
    level_dir = bed.o3de_root / "Levels" / bed.level
    problem = level_bake.recipe_problem(level_dir, recipe)
    if not problem and not getattr(arguments, "fresh", False):
        print(f"[bake] {bed.level} matches its recipe ({len(recipe['instances'])} instances): kept")
        return EXIT_OK
    level_file = level_bake.bake_level(bed.o3de_root, bed.level, recipe)
    print(f"[bake] wrote {level_file} ({len(recipe['instances'])} instances, "
          f"{recipe['spacing']:.0f} m apart, recipe {recipe['hash'][:12]})")
    return EXIT_OK


def step_cook(bed: Bed, arguments) -> int:
    print("[cook] Asset Processor batch run; the first one on a project takes long")
    result = o3de_run.cook(bed.o3de_root, bed.cook_dir / "ap_batch.log")
    if result["status"] == "refused":
        raise Refused(result["problem"])
    (bed.cook_dir / "cook.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"[cook] {result['status']} in {result['seconds']:.0f} s, exit code {result['exit_code']}, "
          f"{len(result['failed'])} failed job(s)")
    for source, reasons in sorted(result["failed"].items()):
        print(f"[cook]   {Path(source).name}: {reasons[0] if reasons else 'no error line'}")
    # Failed jobs are findings, not a failed step: the report carries them.
    return EXIT_OK if result["status"] in ("ok", "failed_jobs") else EXIT_FAILED


def step_probe(bed: Bed, arguments) -> int:
    problem = level_bake.recipe_problem(bed.o3de_root / "Levels" / bed.level, bed.recipe())
    if problem:
        raise Refused(f"{problem}. Bake it: python parity/parity.py bake <config>")

    run_dir = bed.probe_dir
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)
    result = o3de_run.editor_session(bed.o3de_root, run_dir, {
        "level": bed.level,
        "out":   (run_dir / "o3de").as_posix(),
        "scrub": not getattr(arguments, "no_scrub", False),
    })
    if result["status"] == "refused":
        raise Refused(result["problem"])
    _print_session("probe", result)
    if result["status"] != "ok":
        return EXIT_FAILED

    # The levels the scene converter made, for the placement of their instances.
    for scene in converter_cli.marked_scenes(bed.project):
        level = scene.stem
        if not (bed.o3de_root / "Levels" / level / f"{level}.prefab").is_file():
            continue
        scene_dir = run_dir / f"scene_{level}"
        # Of a converted level only its lighting is read back, not every component.
        result = o3de_run.editor_session(bed.o3de_root, scene_dir, {
            "level": level, "out": (scene_dir / "o3de").as_posix(),
            "scrub": True, "scrub_components": ["Gradient GI (IBL)"],
        })
        _print_session(f"probe {level}", result)
    return EXIT_OK


def _print_session(label: str, result: dict) -> None:
    session = result.get("result", {})
    print(f"[{label}] {result['status']} in {result.get('seconds', 0):.0f} s, exit code {result.get('exit_code')}")
    print(f"[{label}] steps: {json.dumps(session.get('steps', {}))}")
    for error in session.get("errors", []):
        print(f"[{label}]   {error.strip().splitlines()[-1]}")


def step_compare(bed: Bed, arguments) -> int:
    import report
    return report.run_compare(bed, arguments)


def step_cycle(bed: Bed, arguments) -> int:
    """Every step in order. A step that fails stops the cycle."""
    started = time.time()
    for name, step in (("truth", step_truth), ("convert", step_convert), ("bake", step_bake),
                       ("cook", step_cook), ("probe", step_probe), ("compare", step_compare)):
        print(f"\n===== {name} =====", flush=True)
        code = step(bed, arguments)
        if code != EXIT_OK and not (name == "convert" and code == EXIT_FAILED):
            # A convert run with failed prefabs still leaves output worth measuring.
            print(f"[cycle] stopped at '{name}' (exit code {code})")
            return code
    print(f"\n[cycle] done in {time.time() - started:.0f} s")
    return EXIT_OK


# =============================================================================
# ARGUMENTS
# =============================================================================

STEPS = {
    "setup": step_setup, "truth": step_truth, "convert": step_convert, "bake": step_bake,
    "cook": step_cook, "probe": step_probe, "compare": step_compare, "cycle": step_cycle,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parity.py", description="Unity-truth parity harness.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in STEPS:
        command = commands.add_parser(name)
        command.add_argument("config", help="test bed config, e.g. parity/configs/office.json")
        if name in ("truth", "bake", "cycle"):
            command.add_argument("--fresh", action="store_true", help="ignore what is cached or baked")
        if name in ("convert", "compare", "cycle"):
            command.add_argument("--only", default="", help="wildcard on prefab names, e.g. Desk_*")
        if name in ("convert", "cycle"):
            command.add_argument("--set", action="append", default=[], metavar="stage.key=value")
        if name in ("probe", "cycle"):
            command.add_argument("--no-scrub", action="store_true", help="skip reading component properties")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return STEPS[arguments.command](Bed(Path(arguments.config)), arguments)
    except (Refused, converter_cli.Refused) as refusal:
        print(f"[{arguments.command}] refused: {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
