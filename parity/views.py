"""
=============================================================================
PARITY VIEWS
=============================================================================

Front, top and left drawings of one prefab, made from the two records: the
geometry Unity has (drawn first, wide and pale) and the geometry O3DE has
(drawn over it, thin and dark). Where the converted prefab is right the thin
lines run inside the wide ones; where it is not, the two shapes part.

    render meshes     Unity green      O3DE red
    colliders         Unity blue       O3DE orange

Both sides are drawn by this one piece of code from measured geometry, in
the prefab frame and O3DE axes, so a difference in the picture is a
difference in the data and never one of camera, lighting or debug drawing.

The three views, as an observer standing in O3DE axes sees them:

    front   looking along +Y   right is +X, up is +Z
    top     looking down -Z    right is +X, up is +Y
    left    looking along +X   right is -Y, up is +Z
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
from PIL import Image, ImageDraw

PANEL = 520                 # pixels per view
MARGIN = 28
HEADER = 54
BACKGROUND = (24, 24, 37)
FRAME = (69, 71, 90)
TEXT = (205, 214, 244)

# (name, horizontal axis, horizontal sign, vertical axis)
VIEWS = (("front", 0, 1.0, 2), ("top", 0, 1.0, 1), ("left", 1, -1.0, 2))

# side and kind -> (colour, line width); Unity is drawn first.
STYLES = {
    ("unity", "mesh"):     ((120, 190, 130), 3),
    ("unity", "collider"): ((110, 150, 235), 3),
    ("o3de", "mesh"):      ((235, 80, 90), 1),
    ("o3de", "collider"):  ((250, 170, 80), 1),
}
ORDER = [("unity", "mesh"), ("unity", "collider"), ("o3de", "mesh"), ("o3de", "collider")]
STATUS_COLOURS = {"pass": (166, 227, 161), "fail": (243, 139, 168), "unmatched": (249, 226, 175),
                  "uncooked": (249, 226, 175), "unmeasured": (137, 220, 235)}


# =============================================================================
# GEOMETRY TO LINES
# =============================================================================

def triangle_edges(indices: np.ndarray) -> np.ndarray:
    """The distinct edges of a triangle list, as an (m, 2) array of indices."""
    triangles = np.asarray(indices, dtype=np.int64)
    triangles = triangles[: len(triangles) // 3 * 3].reshape(-1, 3)
    if len(triangles) == 0:
        return np.zeros((0, 2), dtype=np.int64)
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    return np.unique(np.sort(edges, axis=1), axis=0)


def box_edges() -> np.ndarray:
    """The twelve edges of a box whose corners are ordered as
    ``records.box_corners`` orders them (x, then y, then z, low before high)."""
    edges = []
    for a in range(8):
        for bit in (1, 2, 4):
            if not a & bit:
                edges.append((a, a | bit))
    return np.array(edges, dtype=np.int64)


def drawable(side: str, kind: str, points: np.ndarray, edges: np.ndarray) -> dict:
    return {"side": side, "kind": kind, "points": np.asarray(points, dtype=np.float64),
            "edges": np.asarray(edges, dtype=np.int64)}


# =============================================================================
# THE SHEET
# =============================================================================

def write_sheet(path: Path, title: str, status: str, summary: str, drawables: List[dict]) -> None:
    """Draw the three views of one prefab side by side and save them."""
    width, height = PANEL * len(VIEWS), PANEL + HEADER
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((12, 8), title, fill=TEXT)
    draw.text((12, 26), status.upper(), fill=STATUS_COLOURS.get(status, TEXT))
    draw.text((90, 26), summary, fill=TEXT)
    draw.text((width - 420, 8), "Unity: mesh green, collider blue (wide)", fill=STYLES[("unity", "mesh")][0])
    draw.text((width - 420, 26), "O3DE:  mesh red, collider orange (thin)", fill=STYLES[("o3de", "mesh")][0])

    with_points = [item for item in drawables if len(item["points"])]
    if with_points:
        every = np.concatenate([item["points"] for item in with_points])
        low, high = every.min(axis=0), every.max(axis=0)
    else:
        low, high = np.zeros(3), np.ones(3)
    centre = (low + high) / 2.0
    # One scale for the three views, so sizes can be compared across them.
    reach = max(float((high - low).max()), 1e-3)
    scale = (PANEL - 2 * MARGIN) / reach

    for column, (name, horizontal, sign, vertical) in enumerate(VIEWS):
        left = column * PANEL
        draw.rectangle([left, HEADER, left + PANEL - 1, height - 1], outline=FRAME)
        draw.text((left + 8, HEADER + 6), f"{name}   (frame {reach:.2f} m wide)", fill=TEXT)

        def to_pixels(points: np.ndarray) -> np.ndarray:
            x = left + PANEL / 2.0 + sign * (points[:, horizontal] - centre[horizontal]) * scale
            y = HEADER + PANEL / 2.0 - (points[:, vertical] - centre[vertical]) * scale
            return np.stack([x, y], axis=1)

        # The origin of the prefab frame.
        origin = to_pixels(np.zeros((1, 3)))[0]
        draw.line([origin[0] - 6, origin[1], origin[0] + 6, origin[1]], fill=TEXT)
        draw.line([origin[0], origin[1] - 6, origin[0], origin[1] + 6], fill=TEXT)

        for key in ORDER:
            colour, line_width = STYLES[key]
            for item in with_points:
                if (item["side"], item["kind"]) != key:
                    continue
                pixels = to_pixels(item["points"])
                if len(item["edges"]) == 0:
                    for x, y in pixels[:4000]:
                        draw.point((x, y), fill=colour)
                    continue
                for a, b in item["edges"]:
                    draw.line([tuple(pixels[a]), tuple(pixels[b])], fill=colour, width=line_width)

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
