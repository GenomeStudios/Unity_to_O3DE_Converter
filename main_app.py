#!/usr/bin/env python3
"""
Unity → O3DE Converter — Unified PySide6 Application

Two-tab interface:
  Tab 1 — Prefab Processor  (integrated_asset_processor.py)
  Tab 2 — Scene Converter   (unity_scene_converter_gui.py)

Run:
    python main_app.py
    python main_app.py --tab=prefab
    python main_app.py --tab=scene
"""

import json
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore    import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui     import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QGroupBox, QListWidget, QListWidgetItem,
    QMessageBox, QSizePolicy, QCheckBox,
)


# =============================================================================
# SETTINGS
# =============================================================================

SETTINGS_FILE = Path(__file__).parent / "converter_settings.json"


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(data: dict) -> None:
    try:
        existing = load_settings()
        existing.update(data)
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(existing, f, indent=4)
    except Exception:
        pass


# =============================================================================
# DARK THEME  (Catppuccin Mocha palette)
# =============================================================================

THEME_QSS = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 10pt;
}

QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px;
}
QTabBar::tab {
    background: #313244;
    color: #cdd6f4;
    padding: 8px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #45475a;
}

QLineEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
    padding: 5px 8px;
    selection-background-color: #89b4fa;
}
QLineEdit:focus {
    border: 1px solid #89b4fa;
}

QPushButton {
    background: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
    min-width: 70px;
}
QPushButton:hover {
    background: #585b70;
}
QPushButton:pressed {
    background: #313244;
}
QPushButton#primary {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
}
QPushButton#primary:hover {
    background: #b4d0ff;
}
QPushButton#primary:disabled {
    background: #45475a;
    color: #6c7086;
}

QTextEdit {
    background: #11111b;
    color: #a6e3a1;
    font-family: Consolas, Courier New, monospace;
    font-size: 9pt;
    border: 1px solid #313244;
    border-radius: 4px;
}

QListWidget {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    color: #cdd6f4;
}
QListWidget::item:selected {
    background: #89b4fa;
    color: #1e1e2e;
}
QListWidget::item:hover {
    background: #45475a;
}

QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    color: #89b4fa;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
}

QCheckBox {
    color: #cdd6f4;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #45475a;
    border-radius: 3px;
    background: #313244;
}
QCheckBox::indicator:hover {
    border: 1px solid #89b4fa;
}
QCheckBox::indicator:checked {
    background: #89b4fa;
    border: 1px solid #89b4fa;
}

QLabel#section {
    color: #89b4fa;
    font-weight: bold;
}
QLabel#status_ok {
    color: #a6e3a1;
    font-size: 9pt;
}
QLabel#status_warn {
    color: #f9e2af;
    font-size: 9pt;
}
QLabel#status_err {
    color: #f38ba8;
    font-size: 9pt;
}

QScrollBar:vertical {
    background: #1e1e2e;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #89b4fa;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# =============================================================================
# THREAD WORKER  — runs blocking processing functions off the main thread
# =============================================================================

class LogEmitter(QObject):
    message = Signal(str)


class WorkerThread(QThread):
    """Generic background worker. Emits log messages and a finished signal."""
    finished = Signal(bool, str)   # success, summary_text

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn    = fn
        self._args  = args
        self._kwargs = kwargs
        self.emitter = LogEmitter()

    def _log(self, msg: str) -> None:
        self.emitter.message.emit(msg)

    def run(self) -> None:
        try:
            result = self._fn(*self._args, log=self._log, **self._kwargs)
            summary = result if isinstance(result, str) else "Done."
            self.finished.emit(True, summary)
        except Exception as exc:
            self.emitter.message.emit(f"\n✗ EXCEPTION: {exc}")
            self.emitter.message.emit(traceback.format_exc())
            self.finished.emit(False, str(exc))


# =============================================================================
# SHARED WIDGETS
# =============================================================================

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def _path_row(placeholder: str) -> tuple:
    """Returns (QLineEdit, browse_QPushButton) arranged in an HBoxLayout."""
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    btn  = QPushButton("Browse…")
    return edit, btn


def _log_widget() -> QTextEdit:
    log = QTextEdit()
    log.setReadOnly(True)
    log.setLineWrapMode(QTextEdit.NoWrap)
    log.setMinimumHeight(220)
    return log


# =============================================================================
# TAB 1 — PREFAB PROCESSOR
# =============================================================================

class PrefabProcessorTab(QWidget):
    """
    Drives IntegratedAssetProcessor.  Mirrors the fields from the old
    IntegratedProcessorGUI (tkinter), loading/saving under the key
    "asset_processor" in converter_settings.json.
    """

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread = None
        self._build_ui()
        self._load_settings()

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Source folder ---
        root.addWidget(_section_label("Unity Assets Folder"))
        self._source_edit, src_btn = _path_row("Select Unity project Assets folder…")
        src_btn.clicked.connect(self._browse_source)
        row = QHBoxLayout()
        row.addWidget(self._source_edit)
        row.addWidget(src_btn)
        root.addLayout(row)

        # --- Output folder ---
        root.addWidget(_section_label("O3DE Output Folder"))
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        row.addWidget(out_btn)
        root.addLayout(row)

        # --- Output structure info ---
        info = QGroupBox("Output Structure")
        info_layout = QVBoxLayout(info)
        info_layout.addWidget(QLabel(
            "  Prefabs/    — O3DE prefabs with material references\n"
            "  Materials/  — O3DE PBR materials (.material)\n"
            "  Textures/   — All textures consolidated\n"
            "  Meshes/     — FBX models with .assetinfo sub-mesh definitions"
        ))
        root.addWidget(info)

        # --- Log ---
        root.addWidget(_section_label("Processing Log"))
        self._log_edit = _log_widget()
        root.addWidget(self._log_edit, stretch=1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        btn_row.addWidget(save_log_btn)
        btn_row.addStretch()
        self._process_btn = QPushButton("Process Assets")
        self._process_btn.setObjectName("primary")
        self._process_btn.clicked.connect(self._start_processing)
        btn_row.addWidget(self._process_btn)
        root.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    def _load_settings(self) -> None:
        cfg = load_settings().get("asset_processor", {})
        if cfg.get("source_path"):  self._source_edit.setText(cfg["source_path"])
        if cfg.get("output_path"):  self._output_edit.setText(cfg["output_path"])

    def _save_settings(self) -> None:
        save_settings({"asset_processor": {
            "source_path": self._source_edit.text(),
            "output_path": self._output_edit.text(),
        }})

    # -------------------------------------------------------------------------
    # BROWSE HELPERS
    # -------------------------------------------------------------------------

    def _browse_source(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Unity Assets Folder")
        if d:
            self._source_edit.setText(d)
            self._log(f"Source: {d}")
            self._save_settings()

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select O3DE Output Folder")
        if d:
            self._output_edit.setText(d)
            self._log(f"Output: {d}")
            self._save_settings()

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_edit.append(msg)
        self._log_edit.moveCursor(QTextCursor.End)

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Processing Log", "prefab_processor_log.txt",
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._log_edit.toPlainText())

    # -------------------------------------------------------------------------
    # PROCESSING
    # -------------------------------------------------------------------------

    def _start_processing(self) -> None:
        source = self._source_edit.text().strip()
        output = self._output_edit.text().strip()

        if not source or not output:
            QMessageBox.critical(self, "Error", "Please select both source and output folders.")
            return
        if not os.path.exists(source):
            QMessageBox.critical(self, "Error", f"Source folder not found:\n{source}")
            return

        self._save_settings()
        self._process_btn.setEnabled(False)
        self._log_edit.clear()

        self._worker = WorkerThread(self._do_processing, source, output)
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_processing(self, source_path: str, output_path: str, log) -> str:
        from integrated_asset_processor import IntegratedAssetProcessor

        log("\n" + "=" * 60)
        log("STARTING ASSET PROCESSING")
        log("=" * 60)

        cfg = get_config()
        processor = IntegratedAssetProcessor(
            Path(source_path),
            Path(output_path),
            log_callback=log,
            convert_smoothness_to_roughness=cfg["convert_smoothness_to_roughness"],
        )

        prefab_files = list(Path(source_path).rglob('*.prefab'))
        log(f"\nFound {len(prefab_files)} Unity prefab(s) to process")

        success_count = 0
        for i, prefab_file in enumerate(prefab_files, 1):
            log(f"\n[{i}/{len(prefab_files)}] {prefab_file.name}")
            if processor.process_prefab(prefab_file):
                success_count += 1

        # Write coverage.json and asset_index.json into the output root.
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

        summary_parts = [f"Prefabs: {success_count}/{len(prefab_files)}"]
        summary_parts += [f"{label}: {count}" for label, count in asset_stats.items()]
        return "  |  ".join(summary_parts)

    def _on_finished(self, success: bool, summary: str) -> None:
        self._process_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Processing Complete", summary)
        else:
            QMessageBox.critical(self, "Processing Failed", summary)


# =============================================================================
# TAB 2 — SCENE CONVERTER
# =============================================================================

class SceneConverterTab(QWidget):
    """
    Drives UnitySceneConverter.  Mirrors the fields from the old
    SceneConverterGUI (tkinter), loading/saving under the key
    "scene_converter" in converter_settings.json.
    """

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread = None
        self._prefab_dirs: list = []
        self._build_ui()
        self._load_settings()

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Scene file ---
        root.addWidget(_section_label("Unity Scene File (.unity)"))
        self._scene_edit, scene_btn = _path_row("Select Unity .unity scene file…")
        scene_btn.clicked.connect(self._browse_scene)
        row = QHBoxLayout()
        row.addWidget(self._scene_edit)
        row.addWidget(scene_btn)
        root.addLayout(row)

        # --- Output folder ---
        root.addWidget(_section_label("Output Destination"))
        self._output_edit, out_btn = _path_row("Select O3DE output destination folder…")
        out_btn.clicked.connect(self._browse_output)
        row = QHBoxLayout()
        row.addWidget(self._output_edit)
        row.addWidget(out_btn)
        root.addLayout(row)

        # --- Prefab directories ---
        root.addWidget(_section_label("O3DE Prefab Asset Directories"))
        self._prefab_list = QListWidget()
        self._prefab_list.setMinimumHeight(100)
        self._prefab_list.setMaximumHeight(160)
        root.addWidget(self._prefab_list)

        dir_btn_row = QHBoxLayout()
        add_btn    = QPushButton("Add Directory")
        remove_btn = QPushButton("Remove Selected")
        clear_btn  = QPushButton("Clear All")
        add_btn.clicked.connect(self._add_prefab_directory)
        remove_btn.clicked.connect(self._remove_prefab_directory)
        clear_btn.clicked.connect(self._clear_prefab_directories)
        dir_btn_row.addWidget(add_btn)
        dir_btn_row.addWidget(remove_btn)
        dir_btn_row.addWidget(clear_btn)
        dir_btn_row.addStretch()
        root.addLayout(dir_btn_row)

        # --- Log ---
        root.addWidget(_section_label("Conversion Log"))
        self._log_edit = _log_widget()
        root.addWidget(self._log_edit, stretch=1)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        save_log_btn = QPushButton("Save Log…")
        save_log_btn.clicked.connect(self._save_log)
        btn_row.addWidget(save_log_btn)
        btn_row.addStretch()
        self._convert_btn = QPushButton("Convert Scene")
        self._convert_btn.setObjectName("primary")
        self._convert_btn.clicked.connect(self._start_conversion)
        btn_row.addWidget(self._convert_btn)
        root.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    def _load_settings(self) -> None:
        cfg = load_settings().get("scene_converter", {})
        if cfg.get("scene_path"):  self._scene_edit.setText(cfg["scene_path"])
        if cfg.get("output_path"): self._output_edit.setText(cfg["output_path"])
        for d in cfg.get("prefab_dirs", []):
            self._add_dir_to_list(d)

    def _save_settings(self) -> None:
        save_settings({"scene_converter": {
            "scene_path":  self._scene_edit.text(),
            "output_path": self._output_edit.text(),
            "prefab_dirs": self._prefab_dirs,
        }})

    # -------------------------------------------------------------------------
    # BROWSE HELPERS
    # -------------------------------------------------------------------------

    def _browse_scene(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "Select Unity Scene File", "",
            "Unity Scene (*.unity);;All files (*.*)"
        )
        if f:
            self._scene_edit.setText(f)
            self._save_settings()

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select Output Destination")
        if d:
            self._output_edit.setText(d)
            self._save_settings()

    # -------------------------------------------------------------------------
    # PREFAB DIRECTORY LIST
    # -------------------------------------------------------------------------

    def _add_prefab_directory(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select O3DE Prefab Directory")
        if d and d not in self._prefab_dirs:
            self._add_dir_to_list(d)
            self._save_settings()

    def _add_dir_to_list(self, path: str) -> None:
        self._prefab_dirs.append(path)
        self._prefab_list.addItem(QListWidgetItem(path))

    def _remove_prefab_directory(self) -> None:
        for item in self._prefab_list.selectedItems():
            row = self._prefab_list.row(item)
            self._prefab_list.takeItem(row)
            self._prefab_dirs.pop(row)
        self._save_settings()

    def _clear_prefab_directories(self) -> None:
        self._prefab_list.clear()
        self._prefab_dirs.clear()
        self._save_settings()

    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self._log_edit.append(msg)
        self._log_edit.moveCursor(QTextCursor.End)

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Conversion Log", "scene_converter_log.txt",
            "Text files (*.txt);;All files (*.*)"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._log_edit.toPlainText())

    # -------------------------------------------------------------------------
    # CONVERSION
    # -------------------------------------------------------------------------

    def _start_conversion(self) -> None:
        scene  = self._scene_edit.text().strip()
        output = self._output_edit.text().strip()

        if not scene or not output:
            QMessageBox.critical(self, "Error", "Please select a scene file and output folder.")
            return
        if not os.path.exists(scene):
            QMessageBox.critical(self, "Error", f"Scene file not found:\n{scene}")
            return
        if not self._prefab_dirs:
            QMessageBox.warning(self, "Warning",
                "No prefab directories added. Prefabs will not be resolved.")

        self._save_settings()
        self._convert_btn.setEnabled(False)
        self._log_edit.clear()

        self._worker = WorkerThread(
            self._do_conversion, scene, output, self._prefab_dirs[:]
        )
        self._worker.emitter.message.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _do_conversion(self, scene_path: str, output_dir: str,
                       prefab_dirs: list, log) -> str:
        from unity_scene_converter_gui import PrefabDatabase, UnitySceneConverter

        log("\n" + "=" * 60)
        log("STARTING SCENE CONVERSION")
        log("=" * 60)
        log(f"Scene  : {Path(scene_path).name}")
        log(f"Output : {output_dir}")
        log(f"Prefab directories: {len(prefab_dirs)}")

        prefab_db = PrefabDatabase()
        for d in prefab_dirs:
            prefab_db.add_search_directory(Path(d))

        converter = UnitySceneConverter(prefab_db, log_callback=log)

        log("\nParsing Unity scene…")
        converter.parse_unity_scene(scene_path)
        log(f"Found {len(converter.game_objects)} GameObject(s)")

        prefab_instances = sum(
            1 for go in converter.game_objects.values() if go.is_prefab_instance
        )
        log(f"Prefab instances in scene : {prefab_instances}")
        log(f"Prefabs resolved          : {len(converter.prefab_references)}")

        if converter.missing_prefabs:
            log(f"\nMissing prefabs ({len(converter.missing_prefabs)}):")
            for name in sorted(converter.missing_prefabs):
                log(f"  ⚠ {name}")

        scene_name  = Path(scene_path).stem
        output_path = os.path.join(output_dir, f"{scene_name}.prefab")

        log(f"\nGenerating O3DE level: {scene_name}.prefab")
        total, prefab_refs, blanks = converter.create_o3de_level(
            output_path, Path(output_dir)
        )

        # Write coverage.json next to the level output.
        converter.finalize(Path(output_dir))

        log("\n" + "=" * 60)
        log("CONVERSION COMPLETE!")
        log("=" * 60)
        log(f"Total entities     : {total}")
        log(f"Prefab references  : {prefab_refs}")
        log(f"Blank entities     : {blanks}")
        log(f"Output             : {output_path}")
        log("=" * 60)

        return f"Entities: {total}  |  Prefab refs: {prefab_refs}  |  Blanks: {blanks}"

    def _on_finished(self, success: bool, summary: str) -> None:
        self._convert_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Conversion Complete", summary)
        else:
            QMessageBox.critical(self, "Conversion Failed", summary)


# =============================================================================
# TAB 3 — CONFIG
# =============================================================================

def get_config() -> dict:
    """Return the persisted `config` section, with defaults filled in."""
    cfg = load_settings().get("config", {}) or {}
    return {
        "convert_smoothness_to_roughness":
            bool(cfg.get("convert_smoothness_to_roughness", False)),
    }


# =============================================================================
# DEPENDENCY PROBE
#
# The converter has three pip-installable dependencies. The Config tab probes
# each one at startup (and on refresh) and renders a platform-specific install
# command bound to this Python interpreter's `sys.executable`.  Using the full
# interpreter path defeats the "pip is from a different python than the one
# running the GUI" failure mode — `python -m pip` vs `pip` mismatches are the
# single most common install issue on Windows machines with multiple Pythons.
# =============================================================================

# (import_name, pypi_name, role_text, is_hard_dep)
DEPENDENCIES = [
    ("PySide6", "PySide6", "GUI framework",                              True),
    ("yaml",    "PyYAML",  "Unity prefab / scene YAML parser",           True),
    ("PIL",     "Pillow",  "Smoothness→Roughness texture re-bake",       False),
]


def _probe_dependency(import_name: str, pypi_name: str):
    """Return (installed: bool, version: Optional[str])."""
    import importlib.util
    spec = importlib.util.find_spec(import_name)
    if spec is None:
        return (False, None)
    try:
        import importlib.metadata as md
        return (True, md.version(pypi_name))
    except Exception:
        return (True, None)


def _platform_label() -> str:
    if sys.platform.startswith("win"):  return "Windows"
    if sys.platform == "darwin":        return "macOS"
    return "Linux"


def _install_command(pypi_names: list) -> str:
    """Build a pip-install command bound to the running interpreter.

    Quoting `sys.executable` is important — Windows user-install paths usually
    contain spaces (AppData\\Local\\Programs\\...).  Single quotes on POSIX
    are safe against shells that treat double quotes specially.
    """
    pkgs = " ".join(pypi_names) if pypi_names else " ".join(d[1] for d in DEPENDENCIES)
    exe  = sys.executable
    if sys.platform.startswith("win"):
        return f'"{exe}" -m pip install {pkgs}'
    return f"'{exe}' -m pip install {pkgs}"


class ConfigTab(QWidget):
    """
    Per-run conversion options. Settings are persisted on toggle to
    `converter_settings.json` under the `config` key and read back by the
    Prefab Processor when a run is launched.
    """

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_settings()

    # -------------------------------------------------------------------------
    # UI CONSTRUCTION
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        # --- Material conversion group ---
        mat_group = QGroupBox("Material Conversion")
        ml        = QVBoxLayout(mat_group)

        self._cb_smooth_to_rough = QCheckBox("Convert Smoothness Textures to Roughness")
        self._cb_smooth_to_rough.setToolTip(
            "When enabled, any Unity '_MetallicGlossMap' bound as the roughness "
            "slot is re-baked with an inverted alpha channel and written as "
            "<name>_Roughness.png in Textures/. O3DE samples roughness directly "
            "from the bound texture, so without this step Unity smoothness maps "
            "appear inverted (smooth surfaces look rough). Requires Pillow."
        )
        self._cb_smooth_to_rough.toggled.connect(self._save_settings)
        ml.addWidget(self._cb_smooth_to_rough)
        root.addWidget(mat_group)

        # --- Dependencies group (platform-specific install commands) ---
        dep_group = QGroupBox(f"Dependencies — {_platform_label()}")
        dl        = QVBoxLayout(dep_group)

        # Show the interpreter path so the user can confirm which Python is
        # the install target. This is the single piece of info that explains
        # "pip installed it but the app can't see it" failures.
        dl.addWidget(QLabel("Python interpreter:"))
        py_edit = QLineEdit(sys.executable)
        py_edit.setReadOnly(True)
        py_edit.setStyleSheet("font-family: Consolas, monospace;")
        dl.addWidget(py_edit)

        # Per-dependency status, refreshed by _refresh_dep_status().
        self._dep_status_labels: dict = {}
        for import_name, pypi_name, role, is_hard in DEPENDENCIES:
            lbl = QLabel("")
            lbl.setWordWrap(True)
            self._dep_status_labels[pypi_name] = lbl
            dl.addWidget(lbl)

        dl.addSpacing(6)
        dl.addWidget(QLabel("Install command (binds to the interpreter above):"))
        self._install_cmd_edit = QLineEdit("")
        self._install_cmd_edit.setReadOnly(True)
        self._install_cmd_edit.setStyleSheet(
            "font-family: Consolas, monospace; color: #a6e3a1;"
        )
        dl.addWidget(self._install_cmd_edit)

        # Linux's system Python is usually PEP 668 externally-managed; warn
        # there specifically so users don't bang their head against pip refusing
        # to install. macOS Homebrew is similar but typical desktop users will
        # have used the Python installer from python.org so we skip the macOS warn.
        if sys.platform.startswith("linux"):
            hint = QLabel(
                "Note: on modern Linux distributions, the system Python may refuse "
                "this install (PEP 668). If you see 'externally-managed-environment', "
                "either add  --user  to the command, or create a venv first:  "
                "python3 -m venv .venv && source .venv/bin/activate"
            )
            hint.setObjectName("status_warn")
            hint.setWordWrap(True)
            dl.addWidget(hint)

        btn_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copy command")
        self._copy_btn.clicked.connect(self._copy_install_cmd)
        btn_row.addWidget(self._copy_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setToolTip("Re-probe installed packages")
        self._refresh_btn.clicked.connect(self._refresh_dep_status)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch(1)
        dl.addLayout(btn_row)

        root.addWidget(dep_group)
        root.addStretch(1)

        # Populate the dep section now.
        self._refresh_dep_status()

    # -------------------------------------------------------------------------
    # SETTINGS
    # -------------------------------------------------------------------------

    def _load_settings(self) -> None:
        cfg = get_config()
        self._cb_smooth_to_rough.setChecked(cfg["convert_smoothness_to_roughness"])

    def _save_settings(self) -> None:
        save_settings({"config": {
            "convert_smoothness_to_roughness": self._cb_smooth_to_rough.isChecked(),
        }})

    # -------------------------------------------------------------------------
    # DEPENDENCY STATUS
    # -------------------------------------------------------------------------

    def _refresh_dep_status(self) -> None:
        """Re-probe each dependency, update labels, rebuild install command.

        The install command lists only the missing packages by default; when
        nothing is missing it falls back to the "install all" form so a fresh
        clone can copy a single line to bootstrap everything.

        Flushes Python's import caches first so a package installed via
        `pip install` AFTER the app started can be detected without an app
        restart. Without this, `find_spec` can return stale negative results.
        """
        import importlib
        importlib.invalidate_caches()

        missing: list = []
        for import_name, pypi_name, role, is_hard in DEPENDENCIES:
            installed, version = _probe_dependency(import_name, pypi_name)
            lbl = self._dep_status_labels[pypi_name]
            if installed:
                ver = version or "version unknown"
                lbl.setText(f"  ✓  {pypi_name} {ver} — {role}")
                lbl.setStyleSheet("color: #a6e3a1;")  # green
            else:
                tag = "required" if is_hard else "optional"
                lbl.setText(f"  ✗  {pypi_name} — {role}  ({tag}, not installed)")
                lbl.setStyleSheet("color: #f9e2af;")  # warn yellow
                missing.append(pypi_name)

        # Empty `missing` list → _install_command emits the full install line.
        self._install_cmd_edit.setText(_install_command(missing))

    def _copy_install_cmd(self) -> None:
        QApplication.clipboard().setText(self._install_cmd_edit.text())
        # Brief visual confirmation on the button.
        self._copy_btn.setText("Copied ✓")
        QTimer.singleShot(1200, lambda: self._copy_btn.setText("Copy command"))


# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, start_tab: int = 0):
        super().__init__()
        self.setWindowTitle("Unity → O3DE Converter")
        self.resize(820, 760)

        tabs = QTabWidget()
        tabs.addTab(PrefabProcessorTab(), "Prefab Processor")
        tabs.addTab(SceneConverterTab(),  "Scene Converter")
        tabs.addTab(ConfigTab(),          "Config")
        tabs.setCurrentIndex(start_tab)

        self.setCentralWidget(tabs)


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    # Determine which tab to open from --tab= argument
    start_tab = 0
    for arg in sys.argv[1:]:
        if arg.startswith('--tab='):
            val = arg.split('=', 1)[1].lower()
            start_tab = 1 if val == 'scene' else 0

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(THEME_QSS)

    window = MainWindow(start_tab=start_tab)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
