"""
=============================================================================
WHAT A UNITY SHADER SAYS ABOUT ITS MATERIALS  (platforms.unity.shader_source)
=============================================================================

A Unity material file keeps every property it was ever given: change a
material's shader and the old shader's textures, numbers and switches stay
in the file beside the new one's. Which of them count is not in the material.
It is in the shader:

  - the ``Properties`` block names the properties the shader reads; the rest
    of what a material stores is left over from other shaders;
  - a pass says which faces it draws (``Cull Off``, ``Cull Back``, or
    ``Cull [_Cull]``: left to a property of the material);
  - a pass says whether it cuts by alpha at all times
    (``#define _ALPHATEST_ON 1``, or a ``clip`` against its threshold
    property) or leaves that to the material's keyword.

This module reads those from a ShaderLab file (``.shader``), which is also
what Unity's Shader Graph is saved as when a pack ships it compiled. A shader
that is no such file - one of Unity's own, a ``.shadergraph`` - gives no
facts, and the converter then goes by the material alone, as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# =============================================================================
# THE FACTS
# =============================================================================

# How a pass culls.
CULL_BACK, CULL_FRONT, CULL_OFF = "Back", "Front", "Off"


@dataclass
class ShaderFacts:
    """What one shader file says. ``properties`` maps each declared property
    to its kind as written (``2D``, ``Float``, ``Color``, ``Vector``,
    ``Range(0, 1)``, ...), in the order the shader declares them."""
    name:       str = ""
    properties: Dict[str, str] = field(default_factory=dict)
    # Each property's label, as the material inspector shows it. A pack's
    # shader often spells a packed texture's channels there
    # ("Mask Map MT(R) AO(G) SM(A)"): see ``packed_channels``.
    labels:     Dict[str, str] = field(default_factory=dict)
    # The lit pass's culling: one of the three constants above when the
    # shader fixes it, "" when it does not say.
    cull:          str = ""
    # The property the lit pass takes its culling from ("_Cull"), or "".
    cull_property: str = ""
    # True when the shader cuts by alpha whatever the material's keywords say.
    always_clips:  bool = False

    def declares(self, property_name: str) -> bool:
        return property_name in self.properties

    def textures(self) -> list:
        """The declared texture properties, in the shader's order."""
        return [name for name, kind in self.properties.items() if kind.upper().startswith("2D")]


# =============================================================================
# READING
# =============================================================================

_NAME = re.compile(r'^\s*Shader\s+"([^"]+)"', re.M)
# One declaration: optional [attributes], the name, ("label", kind) =
_PROPERTY = re.compile(r'^\s*(?:\[[^\]]*\]\s*)*(\w+)\s*\(\s*"([^"]*)"\s*,\s*([^=]+?)\s*\)\s*=', re.M)
_CULL = re.compile(r'^\s*Cull\s+(\[\s*\w+\s*\]|\w+)', re.M)
# A pass that cuts by alpha whatever the material says: the keyword defined
# outright (a compiled Shader Graph), or a ``clip`` against a threshold
# property written into the shader's own code (a surface shader).
_ALWAYS_CLIPS = re.compile(
    r'^\s*#define\s+_ALPHATEST_ON\b|\bclip\s*\([^;]*\b(?:_Cutoff|_AlphaCutoff|_AlphaClipThreshold)\b', re.M)
# The names Unity's pipelines give the pass that lights a surface.
_LIT_PASS = re.compile(r'Name\s+"(Universal Forward|ForwardLit|Forward|FORWARD|ForwardBase|ForwardOnly)"')


def read_shader_facts(shader_file: Path) -> Optional[ShaderFacts]:
    """The facts of a ShaderLab file; None for a file that is not one, that
    cannot be read, or that declares no property: such a file does not say
    which of a material's stored properties count."""
    shader_file = Path(shader_file)
    if shader_file.suffix.lower() != ".shader":
        return None
    try:
        text = shader_file.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    name = _NAME.search(text)
    if name is None:
        return None

    facts = ShaderFacts(name=name.group(1).strip())
    for declared, label, kind in _PROPERTY.findall(_properties_block(text)):
        facts.properties.setdefault(declared, kind.strip())
        facts.labels.setdefault(declared, label.strip())
    if not facts.properties:
        return None

    # Culling as the lit pass states it. A pack's shader also carries passes
    # for the editor (selection, picking) that draw both faces whatever the
    # surface does; they come after the lit pass and are not asked.
    lit_pass = _LIT_PASS.search(text)
    cull = _CULL.search(text, lit_pass.end() if lit_pass else 0)
    if cull:
        value = cull.group(1)
        if value.startswith("["):
            facts.cull_property = value.strip("[] ")
        elif value in (CULL_BACK, CULL_FRONT, CULL_OFF):
            facts.cull = value

    facts.always_clips = bool(_ALWAYS_CLIPS.search(text))
    return facts


def _properties_block(text: str) -> str:
    """The text between the braces of the shader's ``Properties`` block."""
    start = re.search(r'\bProperties\s*\{', text)
    if start is None:
        return ""
    depth, position = 1, start.end()
    while position < len(text) and depth:
        if text[position] == "{":
            depth += 1
        elif text[position] == "}":
            depth -= 1
        position += 1
    return text[start.end():position - 1]


# =============================================================================
# PACKED TEXTURES
# One texture, several surface values, each in a channel of its own.
# =============================================================================

# What a label calls a value, and the value it means.
_PACKED_VALUES = (
    (r"MT|Metal\w*",                      "metallic"),
    (r"AO|Ambient\s+Occlusion|Occlusion", "occlusion"),
    (r"SM|Smoo?th\w*",                    "smoothness"),
    (r"Rough\w*",                         "roughness"),
    (r"H|Height",                         "height"),
)
_PACKED = re.compile(
    r"(?<![A-Za-z])(" + "|".join(pattern for pattern, _ in _PACKED_VALUES) + r")\s*\(\s*([RGBA])\s*\)", re.I)

# Unity's own mask map (the HDRP Lit shader): metallic, occlusion, a detail
# mask and smoothness.
_UNITY_MASK_MAP = {"metallic": "R", "occlusion": "G", "smoothness": "A"}


def packed_channels(property_name: str, label: str) -> Dict[str, str]:
    """Which surface value sits in which channel of a packed texture, as
    ``{"metallic": "R", "occlusion": "G", "smoothness": "A"}``; empty for a
    texture that is not known to be packed.

    Read from the property's label where the shader spells it out
    ("Metalic (R) Ambient Occlusion (G) Smoothness (A)", "MT(R) AO(G) H(B)
    SM(A)", "AO (G) Sm (A)"). A property called a mask map without such a
    label is taken as Unity's own."""
    found: Dict[str, str] = {}
    for word, channel in _PACKED.findall(label or ""):
        value = next(value for pattern, value in _PACKED_VALUES if re.fullmatch(pattern, word, re.I))
        found.setdefault(value, channel.upper())
    if not found and property_name.lower().endswith("maskmap"):
        return dict(_UNITY_MASK_MAP)
    return found


# =============================================================================
# WHAT FOLLOWS FOR A MATERIAL
# =============================================================================

# The properties a material's culling may be taken from, by pipeline.
CULL_PROPERTIES = ("_Cull", "_CullMode")
# The properties that hold the alpha threshold, by pipeline. The first one a
# shader declares is the one it reads.
THRESHOLD_PROPERTIES = ("_Cutoff", "_AlphaCutoff", "_AlphaClipThreshold")
# Unity's CullMode values.
_CULL_MODE_OFF = 0


def draws_both_faces(facts: Optional[ShaderFacts], floats: Dict[str, float]) -> bool:
    """Whether a material shows both faces of its surface.

    With the shader's facts: the lit pass culls nothing, or takes its
    culling from a property the material sets to Off. Without them (one of
    Unity's own shaders): the material's ``_Cull``, which Unity's shaders
    read."""
    if facts is None:
        return int(float(floats.get("_Cull", 2))) == _CULL_MODE_OFF
    if facts.cull == CULL_OFF:
        return True
    if facts.cull_property:
        return int(float(floats.get(facts.cull_property, 2))) == _CULL_MODE_OFF
    return False


def alpha_threshold_property(facts: Optional[ShaderFacts]) -> str:
    """The property a shader reads its alpha threshold from: the first of
    the known ones it declares; Unity's own ``_Cutoff`` without facts."""
    if facts is None:
        return THRESHOLD_PROPERTIES[0]
    return next((name for name in THRESHOLD_PROPERTIES if facts.declares(name)), "")
