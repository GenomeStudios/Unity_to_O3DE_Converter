"""
=============================================================================
O3DE COLLISION CONFIG READER  (targets.o3de.collision_config)
=============================================================================

Read-only parser for a target O3DE project's PhysX system-configuration
settings registry (``Registry/physxsystemconfiguration.setreg``). It surfaces
the project's collision **layer names** (index → name) and **group presets**
(GroupId UUID → name) so the Collisions tab can offer real names instead of
raw indices / UUIDs.

The converter NEVER writes this file — it only reads the vocabulary the user
has already authored in their O3DE project.

On-disk shape (verified against AutomatedTesting/Registry/physxsystemconfiguration.setreg):

    {"Amazon": {"Gems": {"PhysX5"|"PhysX": {"PhysXSystemConfiguration": {
        "CollisionConfig": {
            "Layers": {"LayerNames": ["Default", {}, {}, ..., "TouchBend"]},
            "Groups": {"GroupPresets": [
                {"Name": "All", "ReadOnly": true},                       # no Id → null UUID
                {"Id": {"GroupId": "{...}"}, "Name": "None",  ...},
                {"Id": {"GroupId": "{...}"}, "Name": "All_NoTouchBend", ...}
            ]}
        }}}}}}

Notes the shape forces us to handle:
  - The gem node is ``PhysX5`` (PhysX 5) OR ``PhysX`` (legacy) — try both.
  - ``LayerNames`` is a fixed 64-slot array; the array index IS the layer
    index. Empty slots serialize as ``{}`` (an object), not a string — skip
    any non-string / blank entry.
  - A preset may omit ``Id`` when its GroupId is the default (null) UUID —
    this is how the built-in ``All`` group serializes. Fall back to the null
    UUID so the name is still surfaced.
=============================================================================
"""

import json
from pathlib import Path
from typing import Dict, Optional, Tuple


# =============================================================================
# CONSTANTS
# =============================================================================

# Gem nodes to probe, in preference order (PhysX 5 first).
_GEM_KEYS = ("PhysX5", "PhysX")

# Default-constructed AZ::Uuid — the GroupId of a preset that omits "Id"
# (e.g. the built-in "All" group).
NULL_GROUP_UUID = "{00000000-0000-0000-0000-000000000000}"


# =============================================================================
# PARSER
# =============================================================================

def parse_physx_collision_config(
        setreg_path,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Read a ``physxsystemconfiguration.setreg`` and return
    ``(layer_names, group_names)``:

      - ``layer_names``: ``{ "<index>": "<name>" }`` for every named layer.
      - ``group_names``: ``{ "<group_uuid>": "<name>" }`` for every preset.

    Returns two empty dicts when the path is missing, unreadable, malformed,
    or contains no CollisionConfig — the caller treats empty vocab as "fall
    back to free-text index / UUID entry".
    """
    config = _read_collision_config(setreg_path)
    if not config:
        return {}, {}

    layer_names = _extract_layer_names(config)
    group_names = _extract_group_names(config)
    return layer_names, group_names


# =============================================================================
# INTERNALS
# =============================================================================

def _read_collision_config(setreg_path) -> Optional[dict]:
    """Load the .setreg JSON and walk to the ``CollisionConfig`` node under
    whichever PhysX gem key is present. Returns the CollisionConfig dict or
    None."""
    if not setreg_path:
        return None
    path = Path(setreg_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    gems = (((data or {}).get("Amazon") or {}).get("Gems") or {})
    for gem_key in _GEM_KEYS:
        sysconfig = (gems.get(gem_key) or {}).get("PhysXSystemConfiguration")
        if isinstance(sysconfig, dict):
            config = sysconfig.get("CollisionConfig")
            if isinstance(config, dict):
                return config
    return None


def _extract_layer_names(config: dict) -> Dict[str, str]:
    """Array index → layer name, skipping empty (``{}``) slots."""
    names = (config.get("Layers") or {}).get("LayerNames") or []
    out: Dict[str, str] = {}
    for index, entry in enumerate(names):
        if isinstance(entry, str) and entry.strip():
            out[str(index)] = entry
    return out


def _extract_group_names(config: dict) -> Dict[str, str]:
    """Group preset UUID → name. A preset with no explicit ``Id`` uses the
    null UUID (matches the built-in ``All`` group)."""
    presets = (config.get("Groups") or {}).get("GroupPresets") or []
    out: Dict[str, str] = {}
    for preset in presets:
        if not isinstance(preset, dict):
            continue
        name = preset.get("Name")
        if not name:
            continue
        group_id = ((preset.get("Id") or {}).get("GroupId")) or NULL_GROUP_UUID
        out[group_id] = name
    return out
