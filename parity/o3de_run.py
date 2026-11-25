"""
=============================================================================
O3DE RUNS
=============================================================================

Starts the two O3DE programs the harness needs, unattended:

    cook(...)            AssetProcessorBatch on the project: every asset is
                         processed, and every failed job is listed by its
                         source asset with the builder's own error lines.
    editor_session(...)  the Editor on a session script (parity/o3de/session.py)
                         with a run folder; watched, and killed when it stops.

The Editor is started the way ``gs_play/Tools/PerformerSmoke`` starts it. It
brings up its own Asset Processor; the one it started is closed afterwards,
and only that one.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

SESSION_SCRIPT = Path(__file__).parent / "o3de" / "session.py"

STARTUP_GRACE_S = 900.0     # no progress file yet: the Editor is still starting
STALL_S         = 900.0     # the progress file has stopped changing
TIMEOUT_S       = 5400.0    # the whole session

FAILED_LINE = re.compile(r"^AssetProcessor: Failed (.+?), \(\w+\)")


# =============================================================================
# THE ENGINE OF A PROJECT
# =============================================================================

def find_engine(project_root: Path) -> Optional[Path]:
    """The engine a project builds against: the path its ``user/project.json``
    records, else the registered engine its ``project.json`` names."""
    project_root = Path(project_root)
    user = _read_json(project_root / "user" / "project.json")
    if user.get("engine_path") and Path(user["engine_path"]).is_dir():
        return Path(user["engine_path"])

    wanted = _read_json(project_root / "project.json").get("engine", "")
    manifest = _read_json(Path.home() / ".o3de" / "o3de_manifest.json")
    for engine_path in manifest.get("engines", []):
        if _read_json(Path(engine_path) / "engine.json").get("engine_name") == wanted:
            return Path(engine_path)
    return None


def engine_program(project_root: Path, name: str) -> Optional[Path]:
    """An engine program (``Editor``, ``AssetProcessorBatch``): the project's
    own build of it when there is one, else the installed engine's."""
    own = Path(project_root) / "build" / "windows" / "bin" / "profile" / f"{name}.exe"
    if own.is_file():
        return own
    engine = find_engine(project_root)
    if engine is None:
        return None
    installed = engine / "bin" / "Windows" / "profile" / "Default" / f"{name}.exe"
    return installed if installed.is_file() else None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


# =============================================================================
# COOK
# =============================================================================

def cook(project_root: Path, log_file: Path, timeout_s: float = 7200.0) -> dict:
    """Run AssetProcessorBatch on the project. Returns ``{"status",
    "exit_code", "seconds", "failed": {source path: [error lines]}}``.
    ``status`` is ``ok``, ``failed_jobs``, ``timeout`` or ``refused``."""
    program = engine_program(project_root, "AssetProcessorBatch")
    if program is None:
        return {"status": "refused", "problem": "AssetProcessorBatch.exe was not found for this project.",
                "failed": {}}
    if processes_for_project("AssetProcessor.exe", project_root) or \
            processes_for_project("Editor.exe", project_root):
        return {"status": "refused", "failed": {},
                "problem": "The Editor or the Asset Processor is running on this project. Close it and run again."}

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with open(log_file, "w", encoding="utf-8", errors="replace") as out:
        process = subprocess.Popen([str(program), f"--project-path={project_root}"],
                                   cwd=str(project_root), stdout=out, stderr=subprocess.STDOUT)
        try:
            exit_code = process.wait(timeout=timeout_s)
            status = "ok"
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            exit_code, status = process.wait(), "timeout"

    failed = read_failed_jobs(log_file)
    if status == "ok" and failed:
        status = "failed_jobs"
    return {"status": status, "exit_code": exit_code, "seconds": time.time() - started, "failed": failed}


def read_failed_jobs(log_file: Path) -> Dict[str, List[str]]:
    """Every failed job of an Asset Processor batch log: the source asset,
    with the error lines the builder printed for it."""
    failed: Dict[str, List[str]] = {}
    current: Optional[str] = None
    try:
        lines = Path(log_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return failed
    for line in lines:
        match = FAILED_LINE.match(line)
        if match:
            current = match.group(1).replace("\\", "/")
            failed.setdefault(current, [])
        elif line.startswith("AssetProcessor: Process"):
            current = None
        elif current is not None and "| ERROR |" in line:
            reason = line.split("|")[-1].strip()
            if reason and reason not in failed[current]:
                failed[current].append(reason)
    return failed


# =============================================================================
# PROCESSES OF A PROJECT
# =============================================================================

def processes_for_project(image: str, project_root: Path) -> List[int]:
    """Process ids of ``image`` whose command line names this project."""
    query = (f"Get-CimInstance Win32_Process -Filter \"name='{image}'\" | "
             f"ForEach-Object {{ \"$($_.ProcessId)|$($_.CommandLine)\" }}")
    try:
        output = subprocess.run(["powershell", "-NoProfile", "-Command", query],
                                capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    needle = str(project_root).replace("\\", "/").lower()
    found = []
    for line in output.splitlines():
        process_id, _, command_line = line.partition("|")
        if process_id.strip().isdigit() and needle in command_line.replace("\\", "/").lower():
            found.append(int(process_id))
    return found


def _kill(process_ids: List[int]) -> None:
    for process_id in process_ids:
        subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"], capture_output=True)


# =============================================================================
# EDITOR SESSION
# =============================================================================

def editor_session(project_root: Path, run_dir: Path, session: dict,
                   log: Callable[[str], None] = print) -> dict:
    """Run the session script in the Editor with ``session`` as its config.
    Returns ``{"status", "exit_code", "seconds", "result"}``; ``status`` is
    ``ok``, ``failed``, ``timeout``, ``hung``, ``hung_at_startup`` or
    ``refused``. Logs are kept in the run folder."""
    project_root, run_dir = Path(project_root), Path(run_dir)
    editor = engine_program(project_root, "Editor")
    if editor is None:
        return {"status": "refused", "problem": "Editor.exe was not found for this project."}
    # The Editor splits --runpythonargs at spaces.
    if " " in str(run_dir):
        return {"status": "refused", "problem": f"The run folder must not contain spaces: {run_dir}"}
    if processes_for_project("Editor.exe", project_root):
        return {"status": "refused", "problem": "The Editor is running on this project. Close it and run again."}

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "session.json").write_text(json.dumps(session, indent=1), encoding="utf-8")
    asset_processors_before = set(processes_for_project("AssetProcessor.exe", project_root))

    argv = [str(editor), "--project-path", str(project_root), "--autotest_mode",
            "--runpython", str(SESSION_SCRIPT), "--runpythonargs", str(run_dir)]
    started = time.monotonic()
    status = "ok"
    with open(run_dir / "editor_stdout.log", "w", encoding="utf-8", errors="replace") as out:
        process = subprocess.Popen(argv, cwd=str(project_root), stdout=out, stderr=subprocess.STDOUT)
        last_text, last_change, seen = None, started, False
        while process.poll() is None:
            time.sleep(2.0)
            now = time.monotonic()
            progress = _read_json(run_dir / "progress.json")
            text = json.dumps(progress, sort_keys=True) if progress else None
            if text != last_text:
                last_text, last_change, seen = text, now, seen or bool(progress)
                log(f"[probe] {now - started:5.0f} s  {progress.get('phase', '') if progress else ''}")
            if now - started > TIMEOUT_S:
                status = "timeout"
            elif not seen and now - started > STARTUP_GRACE_S:
                status = "hung_at_startup"
            elif seen and now - last_change > STALL_S:
                status = "hung"
            if status != "ok":
                log(f"[probe] {status}: killing the Editor")
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                break
        exit_code = process.wait()

    # Close the Asset Processor this Editor brought up, and no other.
    time.sleep(2.0)
    _kill([pid for pid in processes_for_project("AssetProcessor.exe", project_root)
           if pid not in asset_processors_before])
    _keep_editor_log(project_root, run_dir)

    result = _read_json(run_dir / "result.json")
    if status == "ok" and result.get("status") != "ok":
        status = "failed"
    return {"status": status, "exit_code": exit_code, "seconds": time.monotonic() - started, "result": result}


def _keep_editor_log(project_root: Path, run_dir: Path) -> None:
    source = Path(project_root) / "user" / "log" / "Editor.log"
    try:
        (Path(run_dir) / "Editor.log").write_bytes(source.read_bytes())
    except OSError:
        pass
