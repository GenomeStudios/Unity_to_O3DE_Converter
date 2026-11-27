"""Unit tests for the Unity bridge (parity_harness I.1).

Everything here runs without Unity: the project, the Editor install and the
Unity start are stand-ins built in a temporary folder.

Covers:
  - finding the Unity project of a scope folder and its Editor version;
  - finding the Editor of exactly that version;
  - each refusal message (not a project, Editor missing, project open);
  - installing the bridge script and keeping it out of git status;
  - the fingerprint: stable, and changed by a changed file;
  - the cache: a finished dump of the same fingerprint is reused, Unity is
    not started; ``fresh`` starts it;
  - a failed Unity start is reported with the reason from its log.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.harness import run_module_tests
from platforms.unity.bridge import unity_bridge as bridge
from platforms.unity.bridge.unity_bridge import TruthRequest


# =============================================================================
# FIXTURES
# =============================================================================

VERSION = "2021.3.14f1"


def _make_project(root: Path, version: str = VERSION, with_git: bool = False) -> Path:
    """A Unity project on disk: Assets/Pack with two files, and the version file."""
    scope = root / "Game" / "Assets" / "Pack"
    scope.mkdir(parents=True)
    (scope / "Chair.prefab").write_text("chair", encoding="utf-8")
    (scope / "Chair.fbx").write_bytes(b"\x00\x01\x02")
    settings = root / "Game" / "ProjectSettings"
    settings.mkdir()
    (settings / "ProjectVersion.txt").write_text(
        f"m_EditorVersion: {version}\nm_EditorVersionWithRevision: {version} (abc)\n", encoding="utf-8")
    if with_git:
        (root / "Game" / ".git" / "info").mkdir(parents=True)
        (root / "Game" / ".git" / "info" / "exclude").write_text("# local ignores\n", encoding="utf-8")
    return scope


def _make_editor(root: Path, version: str = VERSION) -> Path:
    """An installed Editor of one version; returns the search root."""
    search_root = root / "Hub" / "Editor"
    executable = bridge.editor_executable_in(search_root / version)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    return search_root


class _Patched:
    """Swap module attributes of the bridge for the length of a ``with`` block."""

    def __init__(self, **replacements):
        self._replacements = replacements
        self._saved = {}

    def __enter__(self):
        for name, value in self._replacements.items():
            self._saved[name] = getattr(bridge, name)
            setattr(bridge, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(bridge, name, value)


# =============================================================================
# PROJECT AND EDITOR DISCOVERY
# =============================================================================

def test_project_root_is_found_from_a_scope_folder():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        assert bridge.find_unity_project_root(scope) == Path(tmp) / "Game"
        assert bridge.find_unity_project_root(scope / "Chair.prefab") == Path(tmp) / "Game"
        assert bridge.find_unity_project_root(Path(tmp)) is None


def test_editor_version_is_read_from_the_project():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp), version="6000.0.32f1")
        assert bridge.read_editor_version(bridge.find_unity_project_root(scope)) == "6000.0.32f1"
        assert bridge.read_editor_version(Path(tmp) / "nowhere") is None


def test_editor_is_found_only_for_the_exact_version():
    with tempfile.TemporaryDirectory() as tmp:
        search_root = _make_editor(Path(tmp))
        with _Patched(EDITOR_ENV_VAR="U2O_TEST_NO_SUCH_VARIABLE"):
            found = bridge.find_unity_editor(VERSION, search_roots=[search_root])
            assert found == bridge.editor_executable_in(search_root / VERSION)
            assert bridge.find_unity_editor("2022.3.34f1", search_roots=[search_root]) is None


def test_editor_override_wins_and_must_exist():
    with tempfile.TemporaryDirectory() as tmp:
        search_root = _make_editor(Path(tmp))
        own = Path(tmp) / "MyUnity.exe"
        own.write_bytes(b"")
        assert bridge.find_unity_editor(VERSION, override=own, search_roots=[search_root]) == own
        assert bridge.find_unity_editor(VERSION, override=Path(tmp) / "missing.exe",
                                        search_roots=[search_root]) is None


def test_asset_path_is_relative_to_the_project():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        project_root = bridge.find_unity_project_root(scope)
        assert bridge.to_asset_path(project_root, scope) == "Assets/Pack"
        assert bridge.to_asset_path(project_root, scope / "Chair.prefab") == "Assets/Pack/Chair.prefab"


# =============================================================================
# REFUSALS
# =============================================================================

def test_refuses_a_folder_outside_any_project():
    with tempfile.TemporaryDirectory() as tmp:
        problems = bridge.check_requirements(Path(tmp))
        assert len(problems) == 1 and "not inside a Unity project" in problems[0], problems


def test_refuses_when_the_editor_version_is_not_installed():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        with _Patched(EDITOR_ENV_VAR="U2O_TEST_NO_SUCH_VARIABLE"):
            problems = bridge.check_requirements(scope, search_roots=[Path(tmp) / "empty"])
        assert len(problems) == 1, problems
        assert f"Unity Editor {VERSION} is not installed" in problems[0], problems


def test_refuses_while_the_project_is_open():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        search_root = _make_editor(Path(tmp))
        lockfile = Path(tmp) / "Game" / "Temp" / "UnityLockfile"
        lockfile.parent.mkdir()
        lockfile.write_bytes(b"")

        # A lock file nobody holds is what a crash leaves behind: not open.
        assert bridge.check_requirements(scope, search_roots=[search_root]) == []

        with _Patched(_lockfile_is_held=lambda path: True):
            problems = bridge.check_requirements(scope, search_roots=[search_root])
        assert len(problems) == 1 and "is open in Unity" in problems[0], problems


def test_no_problems_when_everything_is_in_place():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        search_root = _make_editor(Path(tmp))
        assert bridge.check_requirements(scope, search_roots=[search_root]) == []


# =============================================================================
# INSTALLING THE SCRIPT
# =============================================================================

def test_install_copies_the_script_and_excludes_it_from_git():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp), with_git=True)
        project_root = bridge.find_unity_project_root(scope)

        written = bridge.install_bridge(project_root)
        assert [path.name for path in written] == list(bridge.SCRIPT_FILES)
        for path in written:
            assert path.read_bytes() == (bridge.SCRIPT_DIR / path.name).read_bytes()
            assert path.parent == project_root / "Assets" / "_U2OTruth" / "Editor"

        exclude = (project_root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        assert "/Assets/_U2OTruth/" in exclude.splitlines()
        assert "/Assets/_U2OTruth.meta" in exclude.splitlines()
        assert exclude.startswith("# local ignores\n"), "existing lines must be kept"

        # A second install adds nothing.
        bridge.install_bridge(project_root)
        again = (project_root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        assert again == exclude


def test_install_works_without_a_git_repository():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        project_root = bridge.find_unity_project_root(scope)
        bridge.install_bridge(project_root)
        assert not (project_root / ".git").exists()


# =============================================================================
# FINGERPRINT
# =============================================================================

def test_fingerprint_is_stable_and_follows_the_files():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        request = TruthRequest(scope_root=scope, out_base=Path(tmp) / "out")
        first = bridge.fingerprint(request, VERSION)
        assert first == bridge.fingerprint(request, VERSION)

        (scope / "Chair.prefab").write_text("a different chair", encoding="utf-8")
        assert bridge.fingerprint(request, VERSION) != first


def test_fingerprint_follows_version_only_and_mode():
    with tempfile.TemporaryDirectory() as tmp:
        scope = _make_project(Path(tmp))
        base = bridge.fingerprint(TruthRequest(scope_root=scope, out_base=Path(tmp)), VERSION)
        assert bridge.fingerprint(TruthRequest(scope_root=scope, out_base=Path(tmp)), "2022.3.34f1") != base
        assert bridge.fingerprint(TruthRequest(scope_root=scope, out_base=Path(tmp), only="Desk*"), VERSION) != base
        assert bridge.fingerprint(TruthRequest(scope_root=scope, out_base=Path(tmp), mode="check"), VERSION) != base


# =============================================================================
# RUNNING: CACHE, SUCCESS AND FAILURE (Unity is a stand-in)
# =============================================================================

def _fake_unity(status: str = "ok", exit_code: int = 0, log_text: str = ""):
    """A launcher that plays Unity: reads the request, writes done.json."""
    calls = []

    def launcher(argv, project_root, timeout_s):
        calls.append(argv)
        request = json.loads(Path(argv[argv.index(bridge.REQUEST_ARG) + 1]).read_text(encoding="utf-8"))
        out_dir = Path(request["outDir"])
        Path(argv[argv.index("-logFile") + 1]).write_text(log_text, encoding="utf-8")
        if status:
            (out_dir / "done.json").write_text(json.dumps({
                "status": status, "prefabs": 1, "scope": request["scope"],
                "errors": [] if status == "ok" else ["it broke"],
            }), encoding="utf-8")
        return exit_code

    launcher.calls = calls
    return launcher


def _run(tmp: Path, launcher, **request_fields):
    scope = _make_project(tmp) if not (tmp / "Game").exists() else tmp / "Game" / "Assets" / "Pack"
    search_root = _make_editor(tmp) if not (tmp / "Hub").exists() else tmp / "Hub" / "Editor"
    request = TruthRequest(scope_root=scope, out_base=tmp / "out", **request_fields)
    with _Patched(editor_search_roots=lambda: [search_root],
                  EDITOR_ENV_VAR="U2O_TEST_NO_SUCH_VARIABLE"):
        return bridge.run_truth_dump(request, log=lambda line: None, launcher=launcher)


def test_run_writes_the_request_and_reports_ok():
    with tempfile.TemporaryDirectory() as tmp:
        launcher = _fake_unity()
        result = _run(Path(tmp), launcher)
        assert result.status == "ok", result.problems
        assert result.dump_dir.name == result.fingerprint[:16]

        request = json.loads((result.dump_dir / "request.json").read_text(encoding="utf-8"))
        assert request["scope"] == "Assets/Pack"
        assert request["mode"] == "dump"

        argv = launcher.calls[0]
        assert "-batchmode" in argv and "-quit" in argv
        assert argv[argv.index("-executeMethod") + 1] == bridge.EXECUTE_METHOD

        latest = json.loads((Path(tmp) / "out" / "latest.json").read_text(encoding="utf-8"))
        assert latest["fingerprint"] == result.fingerprint


def test_second_run_is_answered_from_the_cache():
    with tempfile.TemporaryDirectory() as tmp:
        launcher = _fake_unity()
        first = _run(Path(tmp), launcher)
        second = _run(Path(tmp), launcher)
        assert first.status == "ok" and second.status == "cached"
        assert second.dump_dir == first.dump_dir
        assert len(launcher.calls) == 1, "Unity must not be started for a cached dump"


def test_fresh_ignores_the_cache():
    with tempfile.TemporaryDirectory() as tmp:
        launcher = _fake_unity()
        _run(Path(tmp), launcher)
        again = _run(Path(tmp), launcher, fresh=True)
        assert again.status == "ok"
        assert len(launcher.calls) == 2


def test_changed_file_misses_the_cache():
    with tempfile.TemporaryDirectory() as tmp:
        launcher = _fake_unity()
        first = _run(Path(tmp), launcher)
        (Path(tmp) / "Game" / "Assets" / "Pack" / "Chair.prefab").write_text("moved", encoding="utf-8")
        second = _run(Path(tmp), launcher)
        assert second.status == "ok" and second.dump_dir != first.dump_dir


def test_files_unity_changed_during_the_dump_are_named():
    """Unity upgrades what an older version saved and writes it back (two
    materials of the Alchemist House pack, on the first dump). The result
    names such files, and the dump is found again without a second start."""
    with tempfile.TemporaryDirectory() as tmp:
        plays_unity = _fake_unity()

        def launcher(argv, project_root, timeout_s):
            (Path(project_root) / "Assets" / "Pack" / "Chair.prefab").write_text("upgraded by Unity", encoding="utf-8")
            return plays_unity(argv, project_root, timeout_s)

        lines = []
        scope = _make_project(Path(tmp))
        search_root = _make_editor(Path(tmp))
        request = TruthRequest(scope_root=scope, out_base=Path(tmp) / "out")
        with _Patched(editor_search_roots=lambda: [search_root], EDITOR_ENV_VAR="U2O_TEST_NO_SUCH_VARIABLE"):
            first = bridge.run_truth_dump(request, log=lines.append, launcher=launcher)
            second = bridge.run_truth_dump(request, log=lines.append, launcher=launcher)

        assert first.status == "ok" and first.changed_files == ["Assets/Pack/Chair.prefab"]
        assert any("Unity changed 1 file(s)" in line for line in lines)
        assert first.dump_dir.is_dir() and first.dump_dir.name == first.fingerprint[:16]
        assert second.status == "cached" and second.dump_dir == first.dump_dir
        assert len(plays_unity.calls) == 1, "the dump is filed under the project as Unity left it"


def test_a_dump_that_changes_nothing_names_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        assert _run(Path(tmp), _fake_unity()).changed_files == []


def test_failed_unity_start_names_the_reason():
    with tempfile.TemporaryDirectory() as tmp:
        log_text = "Assets/Other/Broken.cs(4,1): error CS1002: ; expected\nScripts have compiler errors.\n"
        result = _run(Path(tmp), _fake_unity(status="", exit_code=1, log_text=log_text))
        assert result.status == "failed" and not result.ok
        joined = "\n".join(result.problems)
        assert "exit code 1" in joined
        assert "no done.json" in joined
        assert "error CS1002" in joined


def test_a_dump_unity_marked_failed_is_not_cached():
    with tempfile.TemporaryDirectory() as tmp:
        failing = _fake_unity(status="failed", exit_code=1)
        result = _run(Path(tmp), failing)
        assert result.status == "failed"
        assert any("it broke" in problem for problem in result.problems)

        working = _fake_unity()
        assert _run(Path(tmp), working).status == "ok"
        assert len(working.calls) == 1


def test_refusal_starts_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        launcher = _fake_unity()
        request = TruthRequest(scope_root=Path(tmp), out_base=Path(tmp) / "out")
        result = bridge.run_truth_dump(request, log=lambda line: None, launcher=launcher)
        assert result.status == "refused" and result.problems
        assert launcher.calls == []
        assert not (Path(tmp) / "out").exists()


if __name__ == "__main__":
    raise SystemExit(run_module_tests(globals()))
