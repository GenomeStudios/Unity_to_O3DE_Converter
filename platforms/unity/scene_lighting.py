"""
=============================================================================
UNITY SCENE LIGHTING  (platforms.unity.scene_lighting)
=============================================================================

Reads the ambient light of a Unity scene from its ``RenderSettings`` block:
the three colours of the gradient - sky, equator, ground.

The colours are taken as linear
-------------------------------
They are passed on as stored. Unity's own defaults suggest the stored values
are linear light: sky ``(0.212, 0.227, 0.259)``, equator
``(0.114, 0.125, 0.133)`` and ground ``(0.047, 0.043, 0.035)`` sit, within
the three places Unity writes, on the linear values of the sRGB picks
``(127, 131, 139)``, ``(95, 99, 102)`` and ``(61, 59, 53)``. This has not
been checked against a rendered frame.

The ambient modes
-----------------
``m_AmbientMode`` says where Unity takes the ambient light from:

  1  Gradient   the three colours. Exact.
  3  Color      one colour, stored as the sky colour. Exact.
  0  Skybox     the scene's sky. The three colours are still stored (often
                Unity's defaults), but they are not what Unity lights with.
  4  Custom     an ambient probe of the user's. As for Skybox.

For the last two the stored colours are returned all the same - one gradient
per level is what the target offers - and ``exact`` is False so the caller
can say so.
"""

from __future__ import annotations

from typing import Dict, Optional

AMBIENT_MODE_NAMES = {0: "Skybox", 1: "Gradient", 3: "Color", 4: "Custom"}


def ambient_gradient(render_settings: Optional[Dict]) -> Optional[dict]:
    """The ambient gradient of a scene::

        {"sky": (r, g, b), "equator": (r, g, b), "ground": (r, g, b),
         "mode": "Gradient", "exact": True}

    Linear colours, top to bottom. None when the scene has no
    ``RenderSettings`` or they hold no ambient colour."""
    if not isinstance(render_settings, dict) or "m_AmbientSkyColor" not in render_settings:
        return None

    try:
        mode = int(render_settings.get("m_AmbientMode", 0) or 0)
    except (TypeError, ValueError):
        mode = 0
    sky = _rgb(render_settings.get("m_AmbientSkyColor"))
    if mode == 3:
        equator = ground = sky                    # one colour for the whole sphere
    else:
        equator = _rgb(render_settings.get("m_AmbientEquatorColor"), sky)
        ground = _rgb(render_settings.get("m_AmbientGroundColor"), sky)

    return {"sky": sky, "equator": equator, "ground": ground,
            "mode": AMBIENT_MODE_NAMES.get(mode, f"mode {mode}"), "exact": mode in (1, 3)}


def _rgb(colour, default=(0.0, 0.0, 0.0)) -> tuple:
    if not isinstance(colour, dict):
        return tuple(default)
    return tuple(float(colour.get(channel, 0.0) or 0.0) for channel in ("r", "g", "b"))
