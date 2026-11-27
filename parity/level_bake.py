"""
=============================================================================
BAKED MEASUREMENT LEVEL
=============================================================================

Makes the level the O3DE probe measures in: one instance of every converted
prefab, each at identity rotation and scale, in a cell of its own size, far
enough apart that no two touch. The cells lie in rings around the origin, the
smallest prefabs inside (see ``lay_out``). The level is written as JSON from
the project's default level; the Editor is not needed to make it.

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
import shutil
from pathlib import Path
from typing import Dict, List

# Raise when the level's layout or content changes: it is part of the recipe.
WRITER_VERSION = 2

# The side of the smallest cell, in metres. Cells double from there.
SMALLEST_CELL = 4.0

RECIPE_FILE = "parity_bake.json"
BASE_LEVEL = "Levels/DefaultLevel/DefaultLevel.prefab"

# Entities of the default level that would stand in the pictures.
DROPPED_BASE_ENTITIES = ("Ground", "Shader Ball", "Grid")

CONTAINER_TRANSFORM = "/ContainerEntity/Components/TransformComponent"


# =============================================================================
# RECIPE
# =============================================================================

def make_recipe(project_root: Path, sources: List[str], radii: Dict[str, float]) -> dict:
    """What the level is made from.

    ``sources`` are the converted prefabs, each as the ``Source`` string
    the converter itself writes where one prefab nests another. The engine
    wants one prefab named by one string everywhere, so the level must name
    the prefabs the way they name each other. ``radii`` gives each prefab's
    reach from its root in metres, by source; it sets the size of the
    prefab's cell."""
    project_root = Path(project_root)
    # Smallest cells first (they go nearest the origin), then by name.
    sources = sorted(sources, key=lambda source: (cell_side(radii.get(source, 0.0)), source))
    centres = lay_out([cell_side(radii.get(source, 0.0)) for source in sources])

    cells = [{"alias": f"Instance_[{1000000 + index}]", "source": source, "cell": centre}
             for index, (source, centre) in enumerate(zip(sources, centres))]

    recipe = {
        "writer_version": WRITER_VERSION,
        "base_level":     BASE_LEVEL,
        "base_level_sha": _sha256((project_root / BASE_LEVEL).read_bytes()),
        # How far the farthest cell's centre lies from the origin, in metres.
        "reach":          max([max(abs(centre[0]), abs(centre[1])) for centre in centres] + [0.0]),
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


# =============================================================================
# LAYOUT
# The Editor holds positions as 32-bit numbers: a kilometre from the origin
# they are a sixteenth of a millimetre apart, thirty kilometres out two
# millimetres - more than the harness's tolerance. One spacing for all, set by
# the largest prefab, puts a pack with a few landscape-sized prefabs that far
# out. So every prefab gets a cell of its own size and the small ones, which
# are the many, stay near the origin.
# =============================================================================

def cell_side(radius: float) -> float:
    """The side of the square cell a prefab stands in, in metres: room for
    twice its reach from its root and a gap of two, rounded up to the
    smallest cell doubled as often as needed. Few sizes, so cells of one
    size tile."""
    side = SMALLEST_CELL
    while side < 2.0 * radius + 2.0:
        side *= 2.0
    return side


def lay_out(sides: List[float]) -> List[List[float]]:
    """The centre of each cell, ``[x, y, 0]``, for cell sides given smallest
    first.

    The cells of one size tile the plane, with a cell centred on the origin.
    Each size takes the free cells nearest the origin, ring by ring: the
    smallest size fills a square around the origin, the next its cells
    outside that square, and so on. A ring is closed off whole before the
    next size starts, so cells of two sizes never overlap."""
    centres: List[List[float]] = []
    taken = 0.0                         # half the side of the square already used
    index = 0
    while index < len(sides):
        side = sides[index]
        count = sides.count(side)
        ring = 0
        placed = 0
        while placed < count:
            for column, row in _ring(ring):
                inner_edge = max(abs(column), abs(row)) * side - side / 2.0
                if placed < count and (taken == 0.0 or inner_edge >= taken):
                    centres.append([column * side, row * side, 0.0])
                    placed += 1
            ring += 1
        taken = (ring - 0.5) * side
        index += count
    return centres


def _ring(ring: int) -> List[tuple]:
    """The cells at ``ring`` steps from the middle cell, in a fixed order."""
    span = range(-ring, ring + 1)
    return [(column, row) for row in span for column in span if max(abs(column), abs(row)) == ring]


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
