#!/usr/bin/env python3
"""
Conversion Project system — data model + manager.

A Conversion Project is a named, savable bundle of:
  - per-stage converter settings (asset_processor, scene_converter, terrain_processor)
  - pipeline status (last-run timestamps + summary counts per stage)
  - metadata (name, scope, notes, created/modified timestamps)

Stored as a JSON file (extension ".u2oproj.json") at a user-chosen path.

The global "converter_settings.json" is repurposed as app-level state only:
    {
      "config":   { ... global toggles ... },
      "projects": {
        "current":      "<abs path of last-opened project>",
        "recent":       [ "<abs path>", ... ],
        "recent_limit": 10
      }
    }

Tabs subscribe to ProjectManager.project_changed and use apply_project /
collect_into_project to round-trip their fields with the active project.

Module is import-safe without a QApplication; signals only fire when a Qt
event loop is running, but plain method calls work in any context (incl.
the __main__ smoke test at the bottom of this file).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


# =============================================================================
# CONSTANTS
# =============================================================================

PROJECT_FILE_EXT     = ".u2oproj.json"
SCHEMA_VERSION       = 2
DEFAULT_RECENT_LIMIT = 10

REPO_ROOT            = Path(__file__).parent
DEFAULT_SETTINGS     = REPO_ROOT / "converter_settings.json"
PROJECTS_DIR         = REPO_ROOT / "Projects"
LEGACY_PROJECT_NAME  = "Legacy.u2oproj.json"

STAGE_KEYS = ("asset_processor", "scene_converter", "terrain_processor")


# =============================================================================
# PROJECT SCOPE
# =============================================================================

class ProjectScope(str, Enum):
    WHOLE_GAME        = "whole_game"
    ASSET_CLUSTER     = "asset_cluster"
    ASSET_SET         = "asset_set"
    INDIVIDUAL_ACTION = "individual_action"

    @classmethod
    def from_string(cls, value: str) -> "ProjectScope":
        for scope in cls:
            if scope.value == value:
                return scope
        return cls.WHOLE_GAME

    def display_name(self) -> str:
        return {
            ProjectScope.WHOLE_GAME:        "Whole Game",
            ProjectScope.ASSET_CLUSTER:     "Asset Cluster",
            ProjectScope.ASSET_SET:         "Asset Set",
            ProjectScope.INDIVIDUAL_ACTION: "Individual Action",
        }[self]


# =============================================================================
# HELPERS
# =============================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_stages() -> dict:
    return {
        "asset_processor":   {"source_path": "", "output_path": ""},
        "scene_converter":   {
            "source_path":     "",   # F-2 override (walking root for scene scrubbing)
            "selected_scenes": [],   # F-3 relative paths under effective_source
            "output_path":     "",
            "prefab_dirs":     [],
        },
        "terrain_processor": {"source_path": "", "output_path": "", "selected_materials": []},
    }


def _default_status() -> dict:
    return {key: {"last_run": None} for key in STAGE_KEYS}


def _default_outputs() -> dict:
    """Per-stage outputs bookkeeping — replaces the old `.ImporterData/`
    sidecar files. Each stage records the input-hash + last-run metadata
    plus the per-asset records (entity maps, asset index entries, etc.)
    that downstream consumers used to read from sidecars."""
    return {
        "asset_processor": {
            "last_run":        None,
            "last_input_hash": None,
            "last_status":     None,
            "prefabs":   {},   # guid → {source_path, output_path, container_alias,
                               #         entity_aliases, material_slots, go_names, written_at}
            "materials": {},   # guid → {output_path, written_at}
            "meshes":    {},   # guid → {output_path, written_at}
            "coverage":  {},
        },
        "scene_converter": {
            "last_run":        None,
            "last_input_hash": None,
            "last_status":     None,
            "scenes":   {},    # rel_path → {output_path, entities, prefab_references,
                               #             missing_prefabs, written_at}
            "coverage": {},
        },
        "terrain_processor": {
            "last_run":        None,
            "last_input_hash": None,
            "last_status":     None,
            "materials": {},   # source_abs_path → {output_path, textures, written_at}
            "coverage":  {},
        },
    }


def _normalize_project_path(path: Path) -> Path:
    """Force a user-chosen save path to end with .u2oproj.json."""
    if path.name.endswith(PROJECT_FILE_EXT):
        return path
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    return path.with_name(stem + PROJECT_FILE_EXT)


# =============================================================================
# PROJECT DATACLASS
# =============================================================================

@dataclass
class Project:
    path:            Optional[Path]
    name:            str
    scope:           ProjectScope
    notes:           str
    created:         str
    modified:        str
    stages:          dict
    pipeline_status: dict
    outputs:         dict = field(default_factory=_default_outputs)
    scope_root:      Optional[Path] = None
    _dirty:          bool = field(default=False, repr=False)

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "schema_version":  SCHEMA_VERSION,
            "name":            self.name,
            "scope":           self.scope.value,
            "scope_root":      str(self.scope_root) if self.scope_root else "",
            "notes":           self.notes,
            "created":         self.created,
            "modified":        self.modified,
            "stages":          self.stages,
            "pipeline_status": self.pipeline_status,
            "outputs":         self.outputs,
        }

    @classmethod
    def from_json(cls, data: dict, path: Optional[Path]) -> "Project":
        stages = _default_stages()
        stages.update(data.get("stages", {}))
        status = _default_status()
        status.update(data.get("pipeline_status", {}))
        outputs = _default_outputs()
        # Deep merge: keep new defaults for missing stages but copy any
        # existing data over.
        for k, v in (data.get("outputs", {}) or {}).items():
            if k in outputs and isinstance(v, dict):
                outputs[k].update(v)
            else:
                outputs[k] = v

        raw_root = (data.get("scope_root") or "").strip()
        scope_root = Path(raw_root) if raw_root else None

        return cls(
            path=path,
            name=data.get("name", "Untitled"),
            scope=ProjectScope.from_string(data.get("scope", "whole_game")),
            notes=data.get("notes", ""),
            created=data.get("created",  _utc_now_iso()),
            modified=data.get("modified", _utc_now_iso()),
            stages=stages,
            pipeline_status=status,
            outputs=outputs,
            scope_root=scope_root,
        )

    # -------------------------------------------------------------------------
    # Accessors / mutation
    # -------------------------------------------------------------------------

    def stage_settings(self, key: str) -> dict:
        return self.stages.setdefault(key, {})

    def update_stage(self, key: str, settings: dict) -> None:
        self.stages[key] = dict(settings)
        self._mark_dirty()

    def update_status(self, key: str, status: dict) -> None:
        self.pipeline_status[key] = dict(status)
        self._mark_dirty()

    def update_outputs(self, key: str, outputs: dict) -> None:
        """Replace the stage's outputs record. The outputs dict carries the
        bookkeeping that used to live in `.ImporterData/` sidecars."""
        self.outputs[key] = dict(outputs)
        self._mark_dirty()

    def set_name(self, name: str) -> None:
        if name != self.name:
            self.name = name
            self._mark_dirty()

    def set_scope(self, scope: ProjectScope) -> None:
        if scope != self.scope:
            self.scope = scope
            self._mark_dirty()

    def set_notes(self, notes: str) -> None:
        if notes != self.notes:
            self.notes = notes
            self._mark_dirty()

    def set_scope_root(self, path: Optional[Path]) -> None:
        """Set the project's Unity scope-root walking directory, or None
        to clear. Per-stage source paths fall back to this when blank."""
        new_value: Optional[Path] = Path(path) if path else None
        if new_value != self.scope_root:
            self.scope_root = new_value
            self._mark_dirty()

    def effective_source(self, stage_key: str) -> str:
        """Resolve the walking root a stage should actually use:
          - The stage's own `source_path` override if non-empty,
          - else the project's `scope_root` if set,
          - else "" (caller decides what to do with an empty result).

        Returned as a string for direct use with Path(...)/QFileDialog
        plumbing. Callers should treat "" as "no source configured"."""
        stage = self.stage_settings(stage_key)
        override = (stage.get("source_path") or "").strip()
        if override:
            return override
        return str(self.scope_root) if self.scope_root else ""

    def is_dirty(self) -> bool:
        return self._dirty

    def _mark_dirty(self) -> None:
        self.modified = _utc_now_iso()
        self._dirty   = True

    def _mark_clean(self) -> None:
        self._dirty = False


# =============================================================================
# PROJECT MANAGER (Qt-aware)
# =============================================================================

class ProjectManager(QObject):
    """Singleton-style manager. Holds the currently active Project and brokers
    persistence between the project file and the global settings file.

    Construct directly with a custom `settings_path` for tests. In the app,
    use `project_manager()` to obtain the process-wide instance.
    """

    project_changed     = Signal(object)        # emits Project or None
    status_changed      = Signal(str)           # stage key whose status updated
    processing_changed  = Signal(str, bool)     # stage key, is-currently-writing

    def __init__(self, settings_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self._settings_path: Path           = settings_path or DEFAULT_SETTINGS
        self._current:       Optional[Project] = None
        self._migrated:      bool           = False

    # -------------------------------------------------------------------------
    # Bootstrap
    # -------------------------------------------------------------------------

    def bootstrap(self) -> None:
        """One-shot startup: migrate legacy settings, then auto-load the last
        opened project (if any). Emits project_changed in all cases."""
        self._migrate_legacy_settings()
        cfg = self._read_settings()
        recent_path = cfg.get("projects", {}).get("current")
        if recent_path and Path(recent_path).exists():
            try:
                self.open(Path(recent_path))
                return
            except Exception:
                # Corrupt/unreadable; fall through to no-project state.
                pass
        self.project_changed.emit(None)

    # -------------------------------------------------------------------------
    # Project lifecycle
    # -------------------------------------------------------------------------

    def current(self) -> Optional[Project]:
        return self._current

    def new_project(
        self,
        name:  str          = "Untitled Project",
        scope: ProjectScope = ProjectScope.WHOLE_GAME,
    ) -> Project:
        now = _utc_now_iso()
        proj = Project(
            path=None,
            name=name,
            scope=scope,
            notes="",
            created=now,
            modified=now,
            stages=_default_stages(),
            pipeline_status=_default_status(),
        )
        proj._mark_dirty()
        self._current = proj
        self.project_changed.emit(proj)
        return proj

    def open(self, path: Path) -> Project:
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        proj = Project.from_json(data, path)
        proj._mark_clean()
        self._current = proj
        self.push_recent(path)
        self._write_settings_field(("projects", "current"), str(path))
        self.project_changed.emit(proj)
        return proj

    def save(self) -> None:
        if self._current is None:
            return
        if self._current.path is None:
            raise ValueError("Project has no path; use save_as(path) first")
        self._write_project(self._current, self._current.path)
        self._current._mark_clean()
        self.push_recent(self._current.path)
        self._write_settings_field(("projects", "current"), str(self._current.path))

    def save_as(self, path: Path) -> None:
        if self._current is None:
            return
        self._current.path = _normalize_project_path(Path(path))
        self.save()

    def close(self) -> None:
        self._current = None
        self._write_settings_field(("projects", "current"), None)
        self.project_changed.emit(None)

    # -------------------------------------------------------------------------
    # Recent list
    # -------------------------------------------------------------------------

    def recent(self) -> list:
        cfg = self._read_settings()
        paths = cfg.get("projects", {}).get("recent", [])
        return [Path(p) for p in paths if Path(p).exists()]

    def push_recent(self, path: Path) -> None:
        path = Path(path)
        cfg = self._read_settings()
        projects = cfg.setdefault("projects", {})
        recent = projects.get("recent", [])
        # De-dupe + push to front
        recent = [str(path)] + [p for p in recent if Path(p) != path]
        limit = projects.get("recent_limit", DEFAULT_RECENT_LIMIT)
        projects["recent"] = recent[:limit]
        self._write_settings(cfg)

    # -------------------------------------------------------------------------
    # Stage / status updates (called by tabs + workers)
    # -------------------------------------------------------------------------

    def update_stage(self, stage_key: str, settings: dict) -> None:
        """Tab call: replace the stage's settings, save if persisted."""
        if self._current is None:
            return
        self._current.update_stage(stage_key, settings)
        if self._current.path is not None:
            self.save()

    def update_status(self, stage_key: str, status: dict) -> None:
        """Worker call: record last run result, save if persisted."""
        if self._current is None:
            return
        self._current.update_status(stage_key, status)
        if self._current.path is not None:
            self.save()
        self.status_changed.emit(stage_key)

    def update_outputs(self, stage_key: str, outputs: dict) -> None:
        """Worker call: persist the stage's outputs bookkeeping (entity
        maps, asset index, coverage, etc.) into the project file.
        Replaces the old `.ImporterData/` sidecar pattern."""
        if self._current is None:
            return
        self._current.update_outputs(stage_key, outputs)
        if self._current.path is not None:
            self.save()
        # Reuse status_changed since dashboard cards refresh on either.
        self.status_changed.emit(stage_key)

    def set_processing(self, stage_key: str, writing: bool) -> None:
        """Worker call at start/end of a run. Drives the dashboard card's
        `writing` sync-state badge."""
        self.processing_changed.emit(stage_key, writing)

    def commit_metadata(self) -> None:
        """Persist + re-emit project_changed after the caller has mutated the
        current project's metadata fields (name / scope / notes) directly via
        the Project.set_* methods. Used by the Project tab when the user edits
        the header so the window title and any other listeners refresh."""
        if self._current is None:
            return
        if self._current.path is not None:
            self.save()
        self.project_changed.emit(self._current)

    # -------------------------------------------------------------------------
    # Settings file I/O (the global file)
    # -------------------------------------------------------------------------

    def _read_settings(self) -> dict:
        try:
            if self._settings_path.exists():
                with self._settings_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_settings(self, data: dict) -> None:
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self._settings_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def _write_settings_field(self, key_path: tuple, value) -> None:
        cfg = self._read_settings()
        cursor = cfg
        for k in key_path[:-1]:
            cursor = cursor.setdefault(k, {})
        if value is None:
            cursor.pop(key_path[-1], None)
        else:
            cursor[key_path[-1]] = value
        self._write_settings(cfg)

    # -------------------------------------------------------------------------
    # Project file I/O
    # -------------------------------------------------------------------------

    @staticmethod
    def _write_project(project: Project, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(project.to_json(), f, indent=4)

    # -------------------------------------------------------------------------
    # Legacy migration (one-shot, idempotent)
    # -------------------------------------------------------------------------

    def _migrate_legacy_settings(self) -> None:
        """Sweep `asset_processor` / `scene_converter` / `terrain_processor`
        keys from the legacy global settings file into a per-project file,
        and rewrite the global file to point at it. Idempotent."""
        if self._migrated:
            return
        cfg = self._read_settings()
        legacy_stages = {k: cfg[k] for k in STAGE_KEYS if k in cfg}
        if not legacy_stages:
            self._migrated = True
            return

        # Resolve target Projects dir alongside the settings file so tests can
        # redirect both with a single settings_path swap.
        projects_dir = self._settings_path.parent / "Projects"
        projects_dir.mkdir(parents=True, exist_ok=True)
        legacy_path = projects_dir / LEGACY_PROJECT_NAME

        if not legacy_path.exists():
            now = _utc_now_iso()
            stages = _default_stages()
            stages.update(legacy_stages)
            proj = Project(
                path=legacy_path,
                name="Legacy (auto-migrated)",
                scope=ProjectScope.WHOLE_GAME,
                notes="Auto-migrated from converter_settings.json on first launch of the project system.",
                created=now,
                modified=now,
                stages=stages,
                pipeline_status=_default_status(),
            )
            self._write_project(proj, legacy_path)

        projects_section = cfg.setdefault("projects", {})
        projects_section["current"] = str(legacy_path)
        recent = projects_section.get("recent", [])
        if str(legacy_path) not in recent:
            recent.insert(0, str(legacy_path))
            projects_section["recent"] = recent[:DEFAULT_RECENT_LIMIT]

        for k in STAGE_KEYS:
            cfg.pop(k, None)

        self._write_settings(cfg)
        self._migrated = True


# =============================================================================
# SINGLETON ACCESSOR
# =============================================================================

_singleton: Optional[ProjectManager] = None


def project_manager() -> ProjectManager:
    """Return the process-wide ProjectManager. Caller is responsible for
    invoking .bootstrap() once after QApplication is constructed."""
    global _singleton
    if _singleton is None:
        _singleton = ProjectManager()
    return _singleton


# =============================================================================
# GLOBAL-SETTINGS HELPERS (non-project state shared across the install)
#
# These read/write the same converter_settings.json the ProjectManager owns,
# but for sections unrelated to any specific project. Keeping them on the
# manager keeps a single file-I/O entrypoint.
# =============================================================================

def get_dismissed_dependency_signature() -> Optional[str]:
    """Return the missing-deps signature the user has dismissed, or None
    if no dismissal is recorded."""
    pm = project_manager()
    cfg = pm._read_settings()
    return cfg.get("dependencies", {}).get("dismissed_signature")


def set_dismissed_dependency_signature(signature: Optional[str]) -> None:
    """Persist (or clear) the dismissed-dependency signature.

    Passing None clears the key so the banner re-arms on the next missing
    set, regardless of contents. Passing a string records the user's
    "don't bother me about this exact set again" choice.
    """
    pm = project_manager()
    cfg = pm._read_settings()
    deps_section = cfg.setdefault("dependencies", {})
    if signature is None:
        deps_section.pop("dismissed_signature", None)
        if not deps_section:
            cfg.pop("dependencies", None)
    else:
        deps_section["dismissed_signature"] = signature
    pm._write_settings(cfg)


# =============================================================================
# SMOKE TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    import shutil
    import tempfile
    from PySide6.QtCore import QCoreApplication

    _ = QCoreApplication.instance() or QCoreApplication(sys.argv)

    tmp = Path(tempfile.mkdtemp(prefix="u2oproj_smoke_"))
    try:
        # Use a temp settings path so we never touch the real converter_settings.json
        settings_path = tmp / "converter_settings.json"
        pm = ProjectManager(settings_path=settings_path)

        # 1. New project + save_as
        proj = pm.new_project("Smoke Test", ProjectScope.ASSET_SET)
        proj.set_notes("smoke notes")
        proj.stages["asset_processor"]["source_path"] = "C:/fake/source"
        proj_path = tmp / "smoke.u2oproj.json"
        pm.save_as(proj_path)
        assert proj_path.exists(), "save_as did not write project file"

        # 2. Close + reopen, fields preserved
        pm.close()
        assert pm.current() is None
        opened = pm.open(proj_path)
        assert opened.name == "Smoke Test"
        assert opened.scope == ProjectScope.ASSET_SET
        assert opened.notes == "smoke notes"
        assert opened.stages["asset_processor"]["source_path"] == "C:/fake/source"

        # 3. Mutate via update_stage, re-open, persistence holds
        pm.update_stage("scene_converter", {
            "scene_path":  "C:/fake/scene.unity",
            "output_path": "C:/fake/output",
            "prefab_dirs": ["C:/fake/prefabs"],
        })
        pm.close()
        reopened = pm.open(proj_path)
        assert reopened.stages["scene_converter"]["scene_path"] == "C:/fake/scene.unity"
        assert reopened.stages["scene_converter"]["prefab_dirs"] == ["C:/fake/prefabs"]

        # 4. update_status round-trips
        pm.update_status("asset_processor", {
            "last_run":        _utc_now_iso(),
            "prefabs_written": 42,
            "errors":          0,
        })
        pm.close()
        again = pm.open(proj_path)
        assert again.pipeline_status["asset_processor"]["prefabs_written"] == 42

        # 5. Recent list contains the project
        recent_paths = [str(p) for p in pm.recent()]
        assert str(proj_path) in recent_paths, f"recent missing project: {recent_paths}"

        # 6. Path normalization on save_as
        pm.close()
        proj2 = pm.new_project("Norm Test")
        pm.save_as(tmp / "no_extension")
        assert proj2.path is not None and proj2.path.name == "no_extension.u2oproj.json"

        # 7. Migration: legacy keys swept into a per-project file
        legacy_settings = tmp / "legacy_settings.json"
        legacy_settings.write_text(json.dumps({
            "asset_processor":   {"source_path": "C:/legacy/src", "output_path": "C:/legacy/out"},
            "scene_converter":   {"scene_path":  "C:/legacy/s.unity",
                                  "output_path": "C:/legacy/lvl",
                                  "prefab_dirs": []},
            "terrain_processor": {"source_path": "C:/legacy/t",
                                  "output_path": "C:/legacy/tout",
                                  "selected_materials": []},
            "config":            {"convert_smoothness_to_roughness": True},
        }, indent=4))
        pm_mig = ProjectManager(settings_path=legacy_settings)
        pm_mig.bootstrap()
        assert pm_mig.current() is not None, "bootstrap did not auto-load migrated project"
        cur = pm_mig.current()
        assert cur.name == "Legacy (auto-migrated)"
        assert cur.stages["asset_processor"]["source_path"] == "C:/legacy/src"
        rewritten = json.loads(legacy_settings.read_text())
        for legacy_key in STAGE_KEYS:
            assert legacy_key not in rewritten, f"{legacy_key} not removed from global settings"
        assert rewritten["projects"]["current"].endswith("Legacy.u2oproj.json")
        assert rewritten["config"]["convert_smoothness_to_roughness"] is True

        # 8. Migration is idempotent on second run
        pm_mig2 = ProjectManager(settings_path=legacy_settings)
        pm_mig2.bootstrap()
        assert pm_mig2.current() is not None
        rewritten2 = json.loads(legacy_settings.read_text())
        assert rewritten == rewritten2, "second migration mutated global settings"

        # 9. scope_root + effective_source round-trips.
        import os
        def _norm(p): return os.path.normpath(p) if p else p
        pm.close()
        proj_root = pm.new_project("Scope Test", ProjectScope.ASSET_SET)
        proj_root_path = tmp / "scoped.u2oproj.json"
        # Initially no scope_root, no override → effective_source is ""
        assert proj_root.effective_source("asset_processor") == ""
        # Set scope_root → effective is the scope_root
        proj_root.set_scope_root(Path("C:/fake/scope"))
        assert _norm(proj_root.effective_source("asset_processor")) == _norm("C:/fake/scope")
        # Set per-stage override → effective is the override
        proj_root.update_stage("asset_processor", {
            "source_path": "C:/fake/override",
            "output_path": "C:/fake/out",
        })
        assert _norm(proj_root.effective_source("asset_processor")) == _norm("C:/fake/override")
        # Save + reload preserves both
        pm.save_as(proj_root_path)
        pm.close()
        reopened_root = pm.open(proj_root_path)
        assert reopened_root.scope_root == Path("C:/fake/scope")
        assert _norm(reopened_root.effective_source("asset_processor")) == _norm("C:/fake/override")
        # Clearing override falls back to scope_root again
        reopened_root.update_stage("asset_processor", {
            "source_path": "",
            "output_path": "C:/fake/out",
        })
        assert _norm(reopened_root.effective_source("asset_processor")) == _norm("C:/fake/scope")
        # Clearing scope_root + no override → empty
        reopened_root.set_scope_root(None)
        assert reopened_root.effective_source("asset_processor") == ""

        # 9b. Loading a project file with no scope_root key (old format) works.
        old_format = tmp / "no_scope_root.u2oproj.json"
        old_format.write_text(json.dumps({
            "schema_version": 1,
            "name": "Old",
            "scope": "whole_game",
            "notes": "",
            "created":  _utc_now_iso(),
            "modified": _utc_now_iso(),
            "stages":          _default_stages(),
            "pipeline_status": _default_status(),
        }, indent=4))
        pm.close()
        old_proj = pm.open(old_format)
        assert old_proj.scope_root is None
        assert old_proj.effective_source("asset_processor") == ""

        # 10. outputs round-trip (replaces .ImporterData/ sidecars).
        pm.close()
        proj_out = pm.new_project("Outputs Test")
        outputs_path = tmp / "outputs.u2oproj.json"
        sample_outputs = {
            "last_run":        _utc_now_iso(),
            "last_input_hash": "abc123",
            "last_status":     "ok",
            "prefabs": {
                "guid-1": {
                    "source_path":     "C:/u/foo.prefab",
                    "output_path":     "Prefabs/foo.prefab",
                    "container_alias": "container",
                    "entity_aliases":  {"100000": "Entity_[1]"},
                    "material_slots":  {"200000": ["mat-guid-1"]},
                    "go_names":        {"Entity_[1]": "Foo"},
                    "written_at":      _utc_now_iso(),
                },
            },
            "materials": {},
            "meshes":    {},
            "coverage":  {"warnings": ["nothing to report"]},
        }
        pm.update_outputs("asset_processor", sample_outputs)
        pm.save_as(outputs_path)
        pm.close()
        reopened_out = pm.open(outputs_path)
        ap = reopened_out.outputs["asset_processor"]
        assert ap["last_input_hash"] == "abc123"
        assert ap["last_status"] == "ok"
        assert ap["prefabs"]["guid-1"]["container_alias"] == "container"
        assert ap["prefabs"]["guid-1"]["entity_aliases"]["100000"] == "Entity_[1]"
        assert ap["coverage"]["warnings"] == ["nothing to report"]
        # An old-format project file with no `outputs` key still loads.
        no_outputs = tmp / "no_outputs.u2oproj.json"
        no_outputs.write_text(json.dumps({
            "name": "Old", "scope": "whole_game", "notes": "",
            "created": _utc_now_iso(), "modified": _utc_now_iso(),
            "stages":          _default_stages(),
            "pipeline_status": _default_status(),
        }, indent=4))
        pm.close()
        old_no_out = pm.open(no_outputs)
        assert "asset_processor" in old_no_out.outputs
        assert old_no_out.outputs["asset_processor"]["prefabs"] == {}

        # 11. Dismissed-dependency-signature round-trip (uses singleton).
        # Temporarily swap the singleton to point at the same temp settings
        # the migration test created so we don't write to the real file.
        import project_manager as _pm_mod  # noqa: F401 (self-import for swap)
        saved_singleton = _pm_mod._singleton
        _pm_mod._singleton = pm_mig  # bound to legacy_settings
        try:
            assert get_dismissed_dependency_signature() is None
            set_dismissed_dependency_signature("Pillow")
            assert get_dismissed_dependency_signature() == "Pillow"
            set_dismissed_dependency_signature("PyYAML,Pillow")
            assert get_dismissed_dependency_signature() == "PyYAML,Pillow"
            set_dismissed_dependency_signature(None)
            assert get_dismissed_dependency_signature() is None
            # ...and the dependencies section is fully cleared, not left empty
            rewritten3 = json.loads(legacy_settings.read_text())
            assert "dependencies" not in rewritten3
        finally:
            _pm_mod._singleton = saved_singleton

        print("project_manager smoke test: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
