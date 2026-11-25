"""
=============================================================================
BAKED MEASUREMENT LEVEL
=============================================================================

Makes the level the O3DE probe measures in: one instance of every converted
prefab on a grid, each at identity rotation and scale, far enough apart that
no two touch. The level is written as JSON from the project's default level;
the Editor is not needed to make it.

The level is a product of its **recipe**: the prefabs, their grid cells, the
base level and the version of this writer. The recipe sits beside the level
(``parity_bake.json``) with its hash. A probe refuses a level whose recipe is
not the one the current state would give - bake again then. A level folder
without a recipe file was not made here and is never touched.

The converted prefabs change from cycle to cycle; the level only names them,
so it stays valid until the list of prefabs or the layout changes.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Dict, List

# Raise when the level's layout or content changes: it is part of the recipe.
WRITER_VERSION = 1

RECIPE_FILE = "parity_bake.json"
BASE_LEVEL = "Levels/DefaultLevel/DefaultLevel.prefab"

# Entities of the default level that would stand in the pictures.
DROPPED_BASE_ENTITIES = ("Ground", "Shader Ball", "Grid")

CONTAINER_TRANSFORM = "/ContainerEntity/Components/TransformComponent"


# =============================================================================
# RECIPE
# =============================================================================

def make_recipe(project_root: Path, prefab_files: List[Path], radii: Dict[str, float],
                source_folder: str = "") -> dict:
    """What the level is made from. ``radii`` gives each prefab's reach from
    its root in metres, by file stem; the largest sets the grid spacing.

    ``source_folder`` is the folder part of each instance's ``Source``. The
    engine wants one prefab named by one string everywhere it is nested, so
    the level must name the prefabs the way they name each other (see
    ``nested_source_folder``). Empty means the project-relative path."""
    project_root = Path(project_root)
    if source_folder:
        sources = sorted(f"{source_folder}/{Path(path).name}" for path in prefab_files)
    else:
        sources = sorted(Path(path).resolve().relative_to(project_root.resolve()).as_posix()
                         for path in prefab_files)
    largest = max([radii.get(Path(source).stem, 0.0) for source in sources] + [1.0])
    spacing = float(math.ceil(2.0 * largest + 2.0))
    columns = max(1, math.ceil(math.sqrt(len(sources))))
    rows = max(1, math.ceil(len(sources) / columns))

    cells = []
    for index, source in enumerate(sources):
        column, row = index % columns, index // columns
        cells.append({
            "alias":  f"Instance_[{1000000 + index}]",
            "source": source,
            # Centred on the origin, to keep coordinates small.
            "cell":   [(column - (columns - 1) / 2.0) * spacing,
                       (row - (rows - 1) / 2.0) * spacing,
                       0.0],
        })

    recipe = {
        "writer_version": WRITER_VERSION,
        "base_level":     BASE_LEVEL,
        "base_level_sha": _sha256((project_root / BASE_LEVEL).read_bytes()),
        "spacing":        spacing,
        "columns":        columns,
        "instances":      cells,
    }
    recipe["hash"] = _sha256(json.dumps(recipe, sort_keys=True).encode("utf-8"))
    return recipe


def nested_source_folder(prefab_files: List[Path]) -> str:
    """The folder part of the ``Source`` strings converted prefabs use for
    the prefabs nested in them; empty when none nests another."""
    for path in prefab_files:
        try:
            instances = json.loads(Path(path).read_text(encoding="utf-8")).get("Instances", {})
        except (OSError, ValueError):
            continue
        for instance in instances.values():
            source = instance.get("Source", "")
            if "/" in source:
                return source.rsplit("/", 1)[0]
    return ""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_recipe(level_dir: Path) -> dict:
    """The recipe a level was baked from; ``{}`` when it has none."""
    try:
        return json.loads((Path(level_dir) / RECIPE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def recipe_problem(level_dir: Path, recipe: dict) -> str:
    """Why a baked level cannot be used for ``recipe``; empty when it can."""
    level_dir = Path(level_dir)
    baked = read_recipe(level_dir)
    if not level_dir.is_dir():
        return f"the level '{level_dir.name}' has not been baked"
    if not baked:
        return f"the level '{level_dir.name}' has no {RECIPE_FILE}: it was not made by this tool"
    if baked.get("hash") != recipe["hash"]:
        return (f"the level '{level_dir.name}' no longer matches its recipe "
                f"(prefab list, layout, base level or writer changed)")
    if not (level_dir / f"{level_dir.name}.prefab").is_file():
        return f"the level file of '{level_dir.name}' is missing"
    return ""


# =============================================================================
# BAKING
# =============================================================================

def bake_level(project_root: Path, level_name: str, recipe: dict) -> Path:
    """Write the level and its recipe. Refuses to replace a level folder
    that carries no recipe file. Returns the level file."""
    project_root = Path(project_root)
    level_dir = project_root / "Levels" / level_name
    if level_dir.exists() and not read_recipe(level_dir):
        raise RuntimeError(f"'{level_dir}' exists and has no {RECIPE_FILE}: "
                           f"it was not made by this tool and is left alone.")
    if level_dir.exists():
        shutil.rmtree(level_dir)
    level_dir.mkdir(parents=True)

    level = json.loads((project_root / recipe["base_level"]).read_text(encoding="utf-8"))
    _drop_base_entities(level)

    container_id = level["ContainerEntity"]["Id"]
    level["Instances"] = {
        cell["alias"]: {
            "Source":  cell["source"],
            "Patches": _placement_patches(container_id, cell["cell"]),
        }
        for cell in recipe["instances"]
    }

    level_file = level_dir / f"{level_name}.prefab"
    level_file.write_text(json.dumps(level, indent=4), encoding="utf-8")
    (level_dir / RECIPE_FILE).write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    return level_file


def _drop_base_entities(level: dict) -> None:
    """Remove the default level's props, and their mention in child orders."""
    dropped = [alias for alias, entity in level["Entities"].items()
               if entity.get("Name") in DROPPED_BASE_ENTITIES]
    for alias in dropped:
        del level["Entities"][alias]
    holders = [level["ContainerEntity"]] + list(level["Entities"].values())
    for entity in holders:
        for component in entity.get("Components", {}).values():
            order = component.get("Child Entity Order")
            if isinstance(order, list):
                component["Child Entity Order"] = [alias for alias in order if alias not in dropped]


def _placement_patches(container_id: str, cell: List[float]) -> List[dict]:
    """Parent the instance to the level and move it to its cell: the same
    patches the converter writes for a placed prefab."""
    patches = [{"op": "replace", "path": f"{CONTAINER_TRANSFORM}/Parent Entity",
                "value": f"../{container_id}"}]
    for axis, value in enumerate(cell):
        patches.append({"op": "replace",
                        "path": f"{CONTAINER_TRANSFORM}/Transform Data/Translate/{axis}",
                        "value": float(value)})
    return patches
