"""
=============================================================================
PARITY RECORDS
=============================================================================

Readers for the three records the harness compares, and the small amount of
matrix arithmetic they share.

    Truth        the Unity truth dump   (platforms/unity/bridge)
    O3deRecord   the Editor probe's record   (parity/o3de/ParityProbe)
    Trace        the converter's trace  (conversion_trace.py)

Every reader hands out plain dicts and numpy arrays. Values stay in the axes
of the engine that wrote them; only ``parity/compare.py`` maps between them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


# =============================================================================
# MATRICES
# =============================================================================

def matrix_from_rows(values) -> np.ndarray:
    """A 4x4 matrix from the twelve numbers of a 3x4, row by row."""
    matrix = np.identity(4)
    matrix[:3, :] = np.asarray(values, dtype=np.float64).reshape(3, 4)
    return matrix


def matrix_from_trs(position, rotation_xyzw, scale) -> np.ndarray:
    """T * R * S as a 4x4. ``scale`` is a number or three numbers."""
    x, y, z, w = (float(v) for v in rotation_xyzw)
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])
    scale = np.broadcast_to(np.asarray(scale, dtype=np.float64), (3,))
    matrix = np.identity(4)
    matrix[:3, :3] = rotation * scale
    matrix[:3, 3] = position
    return matrix


def transform_points(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 4x4 to an (n, 3) array of points."""
    if len(points) == 0:
        return np.zeros((0, 3))
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def read_positions(path: Path) -> np.ndarray:
    """An (n, 3) array from a file of float32 x, y, z."""
    if not Path(path).is_file():
        return np.zeros((0, 3))
    return np.fromfile(str(path), dtype="<f4").astype(np.float64).reshape(-1, 3)


def read_indices(path: Path) -> np.ndarray:
    if not Path(path).is_file():
        return np.zeros((0,), dtype=np.int64)
    return np.fromfile(str(path), dtype="<u4").astype(np.int64)


def box_corners(center, size) -> np.ndarray:
    """The eight corners of an axis-aligned box."""
    center = np.asarray(center, dtype=np.float64)
    half = np.asarray(size, dtype=np.float64) / 2.0
    signs = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float64)
    return center + signs * half


def _load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# =============================================================================
# TRUTH (Unity)
# =============================================================================

class Truth:
    """One truth dump folder. Unity axes: metres, Y up, left-handed."""

    def __init__(self, dump_dir: Path) -> None:
        self.dump_dir = Path(dump_dir)
        self.catalog = _load_json(self.dump_dir / "truth.json")
        self.done = _load_json(self.dump_dir / "done.json")
        self.meshes: Dict[str, dict] = {
            record["key"]: record for record in _load_json(self.dump_dir / "meshes.json")["meshes"]
        }
        self._hierarchies: Dict[str, dict] = {}

    def prefab_entries(self) -> List[dict]:
        return self.catalog["prefabs"]

    def scene_entries(self) -> List[dict]:
        return self.catalog["scenes"]

    def hierarchy(self, entry: dict) -> dict:
        """The prefab, model or scene of one catalog entry."""
        if entry["file"] not in self._hierarchies:
            self._hierarchies[entry["file"]] = _load_json(self.dump_dir / entry["file"])
        return self._hierarchies[entry["file"]]

    @staticmethod
    def mesh_key(reference: dict) -> str:
        return f"{reference['guid']}_{reference['fileId']}"

    def mesh_positions(self, key: str) -> np.ndarray:
        return read_positions(self.dump_dir / "meshes" / f"{key}.pos")

    def mesh_indices(self, key: str) -> np.ndarray:
        return read_indices(self.dump_dir / "meshes" / f"{key}.idx")

    def prefab_radius(self, hierarchy: dict) -> float:
        """Largest distance of any mesh box corner from the prefab's root,
        for laying prefabs out without overlap."""
        objects = hierarchy["objects"]
        if not objects:
            return 0.0
        root_position = matrix_from_rows(objects[0]["matrix"])[:3, 3]
        radius = 0.0
        for item in objects:
            if not item["hasMesh"]:
                continue
            record = self.meshes.get(self.mesh_key(item["mesh"]))
            if record is None:
                continue
            corners = transform_points(matrix_from_rows(item["matrix"]),
                                       box_corners(record["boundsCenter"], record["boundsSize"]))
            radius = max(radius, float(np.linalg.norm(corners - root_position, axis=1).max()))
        return radius


def latest_truth(truth_base: Path) -> Optional[Truth]:
    """The newest full dump under a truth folder, as ``latest.json`` names it."""
    pointer = Path(truth_base) / "latest.json"
    if not pointer.is_file():
        return None
    return Truth(Path(_load_json(pointer)["dump"]))


# =============================================================================
# O3DE RECORD (Editor probe)
# =============================================================================

class O3deRecord:
    """One probe folder. O3DE axes: metres, Z up, right-handed."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.entities: List[dict] = _load_json(self.folder / "record.json")["entities"]
        self.done = _load_json(self.folder / "probe_done.json")
        self.by_id: Dict[str, dict] = {entity["id"]: entity for entity in self.entities}

    def model_positions(self, key: str) -> np.ndarray:
        return read_positions(self.folder / "models" / f"{key}.pos")

    def model_indices(self, key: str) -> np.ndarray:
        return read_indices(self.folder / "models" / f"{key}.idx")

    def collider_positions(self, key: str) -> np.ndarray:
        return read_positions(self.folder / "colliders" / f"{key}.pos")

    def collider_indices(self, key: str) -> np.ndarray:
        return read_indices(self.folder / "colliders" / f"{key}.idx")


# =============================================================================
# TRACE (converter)
# =============================================================================

class Trace:
    """One trace folder written by ``ConversionTrace.write``."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.catalog = _load_json(self.folder / "trace.json")
        self.assetinfos: List[dict] = _load_json(self.folder / "assetinfos.json")
        self.fbx_facts: Dict[str, dict] = _load_json(self.folder / "fbx_facts.json")
        self._records: Dict[str, dict] = {}

    def prefab(self, guid: str) -> Optional[dict]:
        name = self.catalog["prefabs"].get(guid)
        if name is None:
            return None
        if name not in self._records:
            self._records[name] = _load_json(self.folder / name)
        return self._records[name]

    def scene(self, name: str) -> Optional[dict]:
        file_name = self.catalog["scenes"].get(name)
        return _load_json(self.folder / file_name) if file_name else None

    def last_assetinfo(self, fbx_name: str) -> Optional[dict]:
        """The write that is on disk for one FBX: the last one."""
        return next((w for w in reversed(self.assetinfos) if w["fbx"] == fbx_name), None)
