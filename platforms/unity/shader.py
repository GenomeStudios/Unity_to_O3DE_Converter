"""
=============================================================================
UNITY SHADER RESOLUTION  (platforms.unity.shader)
=============================================================================

Resolve a Unity material's ``m_Shader`` reference to its friendly name
(e.g. ``"MK4/Foliage Fantasy"`` or ``"Standard"``).

Unity stores shader references as ``{fileID, guid, type}``. For user
content the guid points at a ``.shader`` (or ``.shadergraph``) file
whose first ``Shader "..."`` declaration carries the friendly name.
Built-in Unity engine shaders use a reserved guid pattern that doesn't
resolve to a file in the user project — they're resolved via the
``UNITY_BUILTIN_SHADERS`` fileID lookup below.

Phase A *mechanical move* from
``IntegratedAssetProcessor._resolve_shader_name`` — the method on the
worker is now a thin wrapper that calls
``resolve_shader_name(asset_db, guid, fileid, cache)``. Behaviour is
byte-identical.
"""

import re
from typing import Dict, Optional


# Unity built-in shaders — only the ones that recur enough in user
# projects to warrant a hard-coded fallback. Extend as needed when new
# built-ins land in the inventory of converted projects.
UNITY_BUILTIN_SHADERS: Dict[int, str] = {
    4:  "Standard",
    46: "Standard (Specular setup)",
}


# First non-whitespace `Shader "Name"` line in a ShaderLab source file.
SHADER_NAME_RE = re.compile(r'\s*Shader\s+"([^"]+)"')


def resolve_shader_name(asset_db, shader_guid: str, shader_fileid: int = 0,
                         cache: Optional[Dict[str, str]] = None) -> str:
    """Resolve a Unity shader reference to its friendly name.

    Reads the first ``Shader "..."`` declaration from the .shader file
    the GUID points at. Built-in shaders use a reserved GUID pattern
    and don't have a file in the user's project — fall through to a
    small built-in fileID lookup for those. Returns empty string when
    neither path produces a name.

    ``asset_db`` is a Unity ``AssetDatabase`` (or any object exposing
    ``.resolve_guid(guid) -> Optional[Path]``). ``cache``, when
    provided, is a dict the function uses to memoise lookups across
    calls — typically the worker's ``self._shader_name_cache``.
    """
    cache_key = f"{shader_guid}:{shader_fileid}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    name = ""
    if shader_guid:
        shader_path = asset_db.resolve_guid(shader_guid)
        if shader_path and shader_path.suffix in (".shader", ".shadergraph"):
            try:
                with open(shader_path, "r", encoding="utf-8", errors="replace") as f:
                    for _ in range(80):
                        line = f.readline()
                        if not line:
                            break
                        m = SHADER_NAME_RE.match(line)
                        if m:
                            name = m.group(1).strip()
                            break
            except Exception:
                pass

    # Built-in fallback (Unity engine shaders). Only consult when the
    # GUID didn't resolve.
    if not name and shader_fileid:
        name = UNITY_BUILTIN_SHADERS.get(int(shader_fileid), "")

    if cache is not None:
        cache[cache_key] = name
    return name
