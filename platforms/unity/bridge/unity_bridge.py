"""
=============================================================================
UNITY BRIDGE
=============================================================================

Runs the Unity Editor headless on a Unity project and has it write the
**truth dump**: what Unity itself holds after import - every object of every
prefab, model and scene with its transforms, meshes, materials and colliders,
and the vertices of every mesh. The converter's output is compared with it.

The bridge needs, and checks before it starts anything:

  - a Unity Editor of the project's own version, installed and licensed;
  - the project not open in Unity;
  - write access to the project's ``Assets`` folder.

What it does to the Unity project:

  - copies its Editor script into ``Assets/_U2OTruth/Editor``;
  - when the project is a git repository, lists that folder in the
    repository's local ``.git/info/exclude`` so it never shows in its status;
  - nothing else: the script saves no asset and no scene.

Nothing of Unity's is shipped with the converter. The Editor script is the
converter's own source and uses the public Editor API; whoever runs the
bridge supplies Unity and the project.

Typical use::

    result = run_truth_dump(TruthRequest(
        scope_root=Path("D:/Game/Assets/Pack"),
        scenes=[Path("D:/Game/Assets/Pack/Scenes/Showcase.unity")],
        out_base=Path("D:/work/truth"),
    ))
    if result.ok:
        print(result.dump_dir)
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# Raise when the dump's content or layout changes: it is part of the cache key.
BRIDGE_VERSION = 1

SCRIPT_DIR      = Path(__file__).parent / "Editor"
SCRIPT_FILES    = ("U2OTruthDump.cs", "U2OTruth.Editor.asmdef")
INSTALL_FOLDER  = "_U2OTruth"                       # under the project's Assets
EXECUTE_METHOD  = "U2OTruth.TruthDump.Run"
REQUEST_ARG     = "-u2oRequest"
EDITOR_ENV_VAR  = "U2O_UNITY_EDITOR"                # full path of a Unity executable

# Lines of the Editor log that explain a failed start.
LOG_TROUBLE_MARKS = (
    "error CS",
    "Scripts have compiler errors",
    "another Unity instance",
    "No valid Unity Editor license",
    "License",
    "executeMethod",
    "[U2OTruth]",
    "Aborting batchmode",
    "Exception",
)


# =============================================================================
# REQUEST AND RESULT
# =============================================================================

@dataclass
class TruthRequest:
    """One truth dump.

    ``scope_root``  the Unity asset folder to dump (inside a project's Assets).
    ``scenes``      scene files to dump as well.
    ``out_base``    folder the dump is written under, in a sub-folder named by
                    the dump's fingerprint.
    ``only``        wildcard on asset file names; empty dumps everything.
    ``mode``        ``dump``, or ``check`` to only start Unity and count.
    ``unity_exe``   a Unity executable to use instead of the discovered one.
    ``fresh``       ignore a cached dump of the same fingerprint.
    """
    scope_root: Path
    out_base:   Path
    scenes:     List[Path] = field(default_factory=list)
    only:       str = ""
    mode:       str = "dump"
    unity_exe:  Optional[Path] = None
    fresh:      bool = False
    timeout_s:  float = 3600.0


@dataclass
class TruthResult:
    """Outcome of ``run_truth_dump``.

    ``status`` is ``ok``, ``cached`` (an earlier dump of the same fingerprint
    was reused), ``refused`` (a requirement is missing, Unity was not started)
    or ``failed``. ``problems`` says why in the last two cases.
    """
    status:      str
    dump_dir:    Optional[Path] = None
    fingerprint: str = ""
    done:        Dict = field(default_factory=dict)
    problems:    List[str] = field(default_factory=list)
    seconds:     float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "cached")


# =============================================================================
# THE UNITY PROJECT
# =============================================================================

def find_unity_project_root(scope_root: Path) -> Optional[Path]:
    """The Unity project a scope folder belongs to: the nearest parent that
    holds both ``Assets`` and ``ProjectSettings/ProjectVersion.txt``."""
    scope_root = Path(scope_root)
    for candidate in [scope_root] + list(scope_root.parents):
        if (candidate / "Assets").is_dir() and \
                (candidate / "ProjectSettings" / "ProjectVersion.txt").is_file():
            return candidate
    return None


def read_editor_version(project_root: Path) -> Optional[str]:
    """The Editor version a project was last saved with, e.g. ``2021.3.14f1``."""
    version_file = Path(project_root) / "ProjectSettings" / "ProjectVersion.txt"
    try:
        for line in version_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("m_EditorVersion:"):
                return line.split(":", 1)[1].strip() or None
    except OSError:
        return None
    return None


def to_asset_path(project_root: Path, path: Path) -> str:
    """A file or folder of the project as Unity names it: ``Assets/...``."""
    return Path(path).resolve().relative_to(Path(project_root).resolve()).as_posix()


def project_is_open(project_root: Path) -> bool:
    """True while a Unity Editor has the project open. Unity holds
    ``Temp/UnityLockfile`` for as long as it runs; a file left behind by a
    crash is not held and does not count."""
    lockfile = Path(project_root) / "Temp" / "UnityLockfile"
    if not lockfile.exists():
        return False
    return _lockfile_is_held(lockfile)


def _lockfile_is_held(lockfile: Path) -> bool:
    try:
        if os.name == "nt":
            # Windows refuses to open a file another process holds exclusively.
            with open(lockfile, "a"):
                return False
        import fcntl
        with open(lockfile, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except OSError:
        return True


# =============================================================================
# THE UNITY EDITOR
# =============================================================================

def editor_executable_in(version_dir: Path) -> Path:
    """Where the Unity executable sits inside one installed version."""
    if sys.platform == "win32":
        return version_dir / "Editor" / "Unity.exe"
    if sys.platform == "darwin":
        return version_dir / "Unity.app" / "Contents" / "MacOS" / "Unity"
    return version_dir / "Editor" / "Unity"


def editor_search_roots() -> List[Path]:
    """Folders that hold one sub-folder per installed Editor version: Unity
    Hub's default location and the secondary location set in Hub."""
    roots: List[Path] = []
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        roots.append(Path(program_files) / "Unity" / "Hub" / "Editor")
        hub_settings = Path(os.environ.get("APPDATA", "")) / "UnityHub"
    elif sys.platform == "darwin":
        roots.append(Path("/Applications/Unity/Hub/Editor"))
        hub_settings = Path.home() / "Library" / "Application Support" / "UnityHub"
    else:
        roots.append(Path.home() / "Unity" / "Hub" / "Editor")
        hub_settings = Path.home() / ".config" / "UnityHub"

    try:
        secondary = json.loads((hub_settings / "secondaryInstallPath.json").read_text(encoding="utf-8"))
        if isinstance(secondary, str) and secondary.strip():
            roots.append(Path(secondary.strip()))
    except (OSError, ValueError):
        pass
    return roots


def find_unity_editor(version: str,
                      override: Optional[Path] = None,
                      search_roots: Optional[List[Path]] = None) -> Optional[Path]:
    """The Unity executable of exactly ``version``. Order: the ``override``
    argument, the ``U2O_UNITY_EDITOR`` environment variable, then the Hub
    install folders. None when it is not installed."""
    if override:
        return Path(override) if Path(override).is_file() else None

    from_environment = os.environ.get(EDITOR_ENV_VAR, "").strip()
    if from_environment and Path(from_environment).is_file():
        return Path(from_environment)

    for root in (editor_search_roots() if search_roots is None else search_roots):
        executable = editor_executable_in(Path(root) / version)
        if executable.is_file():
            return executable
    return None


# =============================================================================
# REQUIREMENTS
# =============================================================================

def check_requirements(scope_root: Path,
                       unity_override: Optional[Path] = None,
                       search_roots: Optional[List[Path]] = None) -> List[str]:
    """Everything that keeps a truth dump from starting, one sentence each.
    An empty list means Unity can be started."""
    problems: List[str] = []

    project_root = find_unity_project_root(scope_root)
    if project_root is None:
        return [f"'{scope_root}' is not inside a Unity project "
                f"(no parent folder holds Assets and ProjectSettings/ProjectVersion.txt)."]

    version = read_editor_version(project_root)
    if not version:
        problems.append(f"The Editor version of '{project_root}' could not be read "
                        f"from ProjectSettings/ProjectVersion.txt.")
    elif find_unity_editor(version, unity_override, search_roots) is None:
        problems.append(f"Unity Editor {version} is not installed. The project needs exactly this "
                        f"version: install it through Unity Hub, or name its executable with "
                        f"--unity or the {EDITOR_ENV_VAR} environment variable.")

    if project_is_open(project_root):
        problems.append(f"The project '{project_root}' is open in Unity. Close it and run again.")

    if not os.access(project_root / "Assets", os.W_OK):
        problems.append(f"No write access to '{project_root / 'Assets'}': the bridge script "
                        f"cannot be installed.")
    return problems


# =============================================================================
# INSTALLING THE BRIDGE SCRIPT
# =============================================================================

def install_bridge(project_root: Path) -> List[Path]:
    """Copy the Editor script into the project and keep it out of the
    project's git status. Returns the files written. Safe to repeat."""
    project_root = Path(project_root)
    target_dir = project_root / "Assets" / INSTALL_FOLDER / "Editor"
    target_dir.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []
    for name in SCRIPT_FILES:
        source, target = SCRIPT_DIR / name, target_dir / name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
        written.append(target)

    _exclude_from_git(project_root)
    return written


def _exclude_from_git(project_root: Path) -> None:
    """List the bridge folder and its .meta file in ``.git/info/exclude``,
    the ignore file that is local to one clone and never committed."""
    info_dir = project_root / ".git" / "info"
    if not (project_root / ".git").is_dir():
        return
    info_dir.mkdir(exist_ok=True)
    exclude_file = info_dir / "exclude"
    wanted = [f"/Assets/{INSTALL_FOLDER}/", f"/Assets/{INSTALL_FOLDER}.meta"]

    existing = exclude_file.read_text(encoding="utf-8") if exclude_file.is_file() else ""
    missing = [line for line in wanted if line not in existing.splitlines()]
    if not missing:
        return
    separator = "" if existing.endswith("\n") or not existing else "\n"
    block = "# To-O3DE Project Converter: Unity bridge script\n" + "\n".join(missing) + "\n"
    exclude_file.write_text(existing + separator + block, encoding="utf-8")


# =============================================================================
# FINGERPRINT
# What a dump depends on. Two requests with one fingerprint give one dump.
# =============================================================================

def fingerprint(request: TruthRequest, editor_version: str) -> str:
    """Hash of everything the dump is made from: every file of the scope and
    every scene (by path, size and modification time), the bridge script,
    the Editor version, and the request's ``only`` and ``mode``."""
    digest = hashlib.sha256()
    digest.update(f"bridge {BRIDGE_VERSION}|unity {editor_version}|"
                  f"only {request.only}|mode {request.mode}\n".encode("utf-8"))

    for name in SCRIPT_FILES:
        digest.update((SCRIPT_DIR / name).read_bytes())

    scope_root = Path(request.scope_root)
    files = [path for path in scope_root.rglob("*") if path.is_file()]
    files += [Path(scene) for scene in request.scenes
              if Path(scene).is_file() and scope_root not in Path(scene).parents]
    for path in sorted(files):
        stat = path.stat()
        digest.update(f"{path.as_posix()}|{stat.st_size}|{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


# =============================================================================
# RUNNING THE DUMP
# =============================================================================

def run_truth_dump(request: TruthRequest,
                   log: Callable[[str], None] = print,
                   launcher: Optional[Callable[[List[str], Path, float], int]] = None) -> TruthResult:
    """Make the truth dump of ``request``, or reuse the cached one.

    ``launcher`` starts Unity and returns its exit code; tests pass a stand-in.
    """
    started = time.time()

    # ----- Requirements ------------------------------------------------------
    problems = check_requirements(request.scope_root, request.unity_exe)
    if problems:
        return TruthResult(status="refused", problems=problems)

    project_root = find_unity_project_root(request.scope_root)
    version      = read_editor_version(project_root)
    unity_exe    = find_unity_editor(version, request.unity_exe)

    # ----- Cache -------------------------------------------------------------
    print_hash = fingerprint(request, version)
    dump_dir   = Path(request.out_base) / print_hash[:16]
    if not request.fresh:
        cached = _read_done(dump_dir)
        if cached.get("status") == "ok":
            log(f"[truth] cached dump reused: {dump_dir}")
            return TruthResult(status="cached", dump_dir=dump_dir, fingerprint=print_hash,
                               done=cached, seconds=time.time() - started)

    # ----- Request -----------------------------------------------------------
    if dump_dir.exists():
        shutil.rmtree(dump_dir)
    dump_dir.mkdir(parents=True)
    request_file = dump_dir / "request.json"
    request_file.write_text(json.dumps({
        "mode":   request.mode,
        "scope":  to_asset_path(project_root, request.scope_root),
        "outDir": dump_dir.as_posix(),
        "scenes": [to_asset_path(project_root, scene) for scene in request.scenes],
        "only":   request.only,
    }, indent=2), encoding="utf-8")

    # ----- Unity -------------------------------------------------------------
    install_bridge(project_root)
    log_file = dump_dir / "unity_editor.log"
    argv = [str(unity_exe), "-batchmode", "-nographics",
            "-projectPath", str(project_root),
            "-executeMethod", EXECUTE_METHOD,
            REQUEST_ARG, str(request_file),
            "-logFile", str(log_file),
            "-quit"]
    log(f"[truth] starting Unity {version} on {project_root}")
    log(f"[truth] log: {log_file}")
    exit_code = (launcher or _launch_unity)(argv, project_root, request.timeout_s)

    # ----- Result ------------------------------------------------------------
    done = _read_done(dump_dir)
    seconds = time.time() - started
    if exit_code == 0 and done.get("status") == "ok":
        (Path(request.out_base) / "latest.json").write_text(json.dumps({
            "dump": dump_dir.as_posix(), "fingerprint": print_hash,
        }, indent=2), encoding="utf-8")
        return TruthResult(status="ok", dump_dir=dump_dir, fingerprint=print_hash,
                           done=done, seconds=seconds)

    problems = [f"Unity left with exit code {exit_code}."]
    problems += [f"Unity: {error}" for error in done.get("errors", [])]
    if not done:
        problems.append("Unity wrote no done.json: the bridge script did not run to its end.")
    problems += [f"log: {line}" for line in read_log_trouble(log_file)]
    return TruthResult(status="failed", dump_dir=dump_dir, fingerprint=print_hash,
                       done=done, problems=problems, seconds=seconds)


def _launch_unity(argv: List[str], project_root: Path, timeout_s: float) -> int:
    """Start Unity and wait for it. A Unity that outlives the timeout is
    killed with its child processes, and -1 is returned."""
    process = subprocess.Popen(argv, cwd=str(project_root))
    try:
        return process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.kill()
        process.wait()
        return -1


def _read_done(dump_dir: Path) -> Dict:
    try:
        return json.loads((Path(dump_dir) / "done.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_log_trouble(log_file: Path, limit: int = 40) -> List[str]:
    """The lines of an Editor log that say why a run went wrong."""
    try:
        lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    trouble = [line.strip() for line in lines
               if any(mark in line for mark in LOG_TROUBLE_MARKS)]
    return trouble[-limit:]
