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

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

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

class SourceEngine(str, Enum):
    """The source engine the conversion project is reading FROM.

    Cosmetic in v1 (every project today is Unity-sourced), but the
    field exists so future iterations can select different extraction
    profile libraries / file walkers based on the engine. Adding new
    engines is a single-line addition here plus a `display_name()` row.
    """
    UNITY   = "unity"
    UNREAL  = "unreal"
    GODOT   = "godot"
    BLENDER = "blender"

    @classmethod
    def from_string(cls, value: str) -> "SourceEngine":
        # Direct match.
        for eng in cls:
            if eng.value == value:
                return eng
        # Legacy ProjectScope values (whole_game / asset_cluster / asset_set
        # / individual_action) belonged to a Unity-only world; migrate them
        # to UNITY rather than dropping them.
        return cls.UNITY

    def display_name(self) -> str:
        return {
            SourceEngine.UNITY:   "Unity",
            SourceEngine.UNREAL:  "Unreal",
            SourceEngine.GODOT:   "Godot",
            SourceEngine.BLENDER: "Blender",
        }[self]


# Legacy alias — old code paths and any third-party importers that referenced
# `ProjectScope` continue to work. New code uses `SourceEngine`.
ProjectScope = SourceEngine


# =============================================================================
# HELPERS
# =============================================================================

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# MATERIALTYPE RESOLVER (F-9)
#
# Both the UI and the worker need to know what string a user-entered
# materialtype value should resolve to inside an emitted `.material` file.
# Centralising the rules here keeps the "common value" inspector display in
# MaterialTab consistent with what IntegratedAssetProcessor actually writes.
# =============================================================================

# Bare filename → O3DE `@gemroot:...@` path. Extend as more builtin
# materialtypes become commonly mapped.
_O3DE_BUILTIN_MATERIALTYPES = {
    "StandardPBR.materialtype":
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/StandardPBR.materialtype",
    "BasePBR.materialtype":
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/BasePBR.materialtype",
    "EnhancedPBR.materialtype":
        "@gemroot:Atom_Feature_Common@/Assets/Materials/Types/EnhancedPBR.materialtype",
}

# Fallback when nothing resolves and the caller doesn't supply a default.
DEFAULT_MATERIALTYPE_PATH = _O3DE_BUILTIN_MATERIALTYPES["StandardPBR.materialtype"]


def resolve_materialtype_path(value: Optional[str]) -> str:
    """Resolve a user-entered materialtype value to the string that should
    land in the emitted `.material` file's `materialType` field.

    Resolution rules (first match wins):
    1. Empty / None → `DEFAULT_MATERIALTYPE_PATH`.
    2. Already in O3DE `@gemroot:...@` form → pass through.
    3. Absolute filesystem path (Windows drive letter, POSIX `/`) → pass
       through. Useful for project-local materialtypes.
    4. Bare filename in the builtin table → expanded.
    5. Bare filename ending `.materialtype` → returned as-written; treated
       as a project-local materialtype the asset processor will resolve.
    6. Bare name without extension → `.materialtype` appended then re-run
       through this resolver.
    """
    if not value:
        return DEFAULT_MATERIALTYPE_PATH
    s = str(value).strip()
    if not s:
        return DEFAULT_MATERIALTYPE_PATH
    # @gemroot:...@ form, or any colon-bearing alias path.
    if s.startswith("@") or ":" in s.split("/", 1)[0] or ":" in s.split("\\", 1)[0]:
        return s
    # Absolute filesystem path (POSIX or Windows).
    if s.startswith("/") or (len(s) > 2 and s[1] == ":" and s[2] in ("/", "\\")):
        return s
    if s in _O3DE_BUILTIN_MATERIALTYPES:
        return _O3DE_BUILTIN_MATERIALTYPES[s]
    if s.endswith(".materialtype"):
        return s
    return resolve_materialtype_path(s + ".materialtype")



# =============================================================================
# EXTERNALLY-MODIFIED DETECTION (F-9.I.6b)
#
# After the converter writes a `.material` / `.assetinfo` / etc., the user
# may open the file in O3DE and edit it directly (tweak property values, add
# slots, etc.). Re-running Patch would silently overwrite those edits. The
# tab UI surfaces a per-asset ✎ marker so the user knows re-emitting that
# row is destructive.
#
# Detection compares each `output_files[i]` mtime against the saved
# `last_emitted` ISO timestamp on the same state-index entry. mtime is
# best-effort (subsecond resolution differs across filesystems), so a 1.0s
# tolerance is added to absorb the write-then-record gap and FS rounding.
# =============================================================================

def _parse_iso_to_epoch(iso: str) -> Optional[float]:
    """Parse an ISO-8601 'YYYY-MM-DDTHH:MM:SSZ' string to epoch seconds.
    Returns None when the string is empty or unparsable."""
    if not iso:
        return None
    try:
        # Accept the trailing 'Z' (UTC marker) used by `_utc_now_iso`. fromisoformat
        # on Python 3.10+ accepts the suffix natively; older versions need it stripped.
        s = iso.rstrip("Z")
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def detect_externally_modified(state_index: Optional[dict],
                                tolerance_seconds: float = 1.0,
                                ) -> dict:
    """Return a dict of `{bucket_name: set(guid)}` for assets whose output
    file mtime exceeds the saved `last_emitted` timestamp by more than
    `tolerance_seconds`.

    Buckets: materials / meshes / textures / prefabs. Entries without
    `last_emitted` or `output_files` are skipped (nothing to compare).
    """
    out = {k: set() for k in ("materials", "meshes", "textures", "prefabs")}
    if not state_index:
        return out
    for bucket_name, bucket in (state_index or {}).items():
        if bucket_name not in out or not isinstance(bucket, dict):
            continue
        for guid, entry in bucket.items():
            if not isinstance(entry, dict):
                continue
            emitted_at = _parse_iso_to_epoch(entry.get("last_emitted") or "")
            if emitted_at is None:
                continue
            threshold = emitted_at + tolerance_seconds
            for p_str in (entry.get("output_files") or []):
                try:
                    mtime = Path(p_str).stat().st_mtime
                except (OSError, ValueError):
                    continue
                if mtime > threshold:
                    out[bucket_name].add(guid)
                    break
    return out


# =============================================================================
# SHADER PROFILES (F-9)
#
# A "shader profile" captures how a Unity shader's properties (textures +
# scalars/colors) map onto an O3DE materialtype. Profiles supersede the
# F-6 model where `shader_mappings` pointed at a materialtype path — that
# path lacked the property-remap context required for divergent shader
# packs. F-9 ships exactly one profile (`Default — Anything to PBR`) that
# captures the legacy hard-coded TEXTURE_MAP / PROPERTY_MAP / IGNORE_UNMAPPED
# behaviour verbatim. Profile authoring (creating new profiles, editing the
# remap tables in the GUI) is the F-10 feature.
#
# Profile fields
# --------------
#   description           — human-readable purpose
#   target_materialtype   — string fed to resolve_materialtype_path()
#   texture_map           — Unity property → {slot, transform}
#   property_map          — Unity property → {target, transform}
#   ignore_unmapped       — names that don't have a clean O3DE equivalent;
#                            silenced from the unmapped-property warnings
#   special_rules         — named flags the worker honours; F-9 only consumes
#                            `metallic_gloss_smoothness_to_roughness` to
#                            preserve the existing Standard-shader behaviour.
# =============================================================================

DEFAULT_PROFILE_NAME = "Default — Anything to PBR"

DEFAULT_SHADER_PROFILE = {
    "description": (
        "Catch-all Unity → O3DE PBR remap. Reproduces the legacy hard-coded "
        "TEXTURE_MAP / PROPERTY_MAP / IGNORE_UNMAPPED behaviour exactly. "
        "Acts as the fallback for every shader unless a project-specific "
        "profile (authored in F-10) overrides it."
    ),
    "target_materialtype": "StandardPBR.materialtype",
    # Unity property name → O3DE slot. Slots match the StandardPBR materialtype's
    # texture binding shorthand (e.g. "baseColor" → "baseColor.textureMap").
    "texture_map": {
        # baseColor — Unity Standard, URP, HDRP, and common custom-shader aliases
        "_MainTex":          {"slot": "baseColor",  "transform": "passthrough"},
        "_BaseMap":          {"slot": "baseColor",  "transform": "passthrough"},
        "_BaseColorMap":     {"slot": "baseColor",  "transform": "passthrough"},
        "_Albedo":           {"slot": "baseColor",  "transform": "passthrough"},
        "_AlbedoMap":        {"slot": "baseColor",  "transform": "passthrough"},
        "_AlbedoTex":        {"slot": "baseColor",  "transform": "passthrough"},
        "_Diffuse":          {"slot": "baseColor",  "transform": "passthrough"},
        "_DiffuseMap":       {"slot": "baseColor",  "transform": "passthrough"},
        "_DiffuseTex":       {"slot": "baseColor",  "transform": "passthrough"},
        "_ColorMap":         {"slot": "baseColor",  "transform": "passthrough"},
        # normal
        "_BumpMap":          {"slot": "normal",     "transform": "passthrough"},
        "_NormalMap":        {"slot": "normal",     "transform": "passthrough"},
        "_NormalTex":        {"slot": "normal",     "transform": "passthrough"},
        # metallic — Standard packs gloss in alpha, handled via
        # special_rules.metallic_gloss_smoothness_to_roughness
        "_MetallicGlossMap": {"slot": "metallic",   "transform": "passthrough"},
        "_MetallicMap":      {"slot": "metallic",   "transform": "passthrough"},
        "_MetallicTex":      {"slot": "metallic",   "transform": "passthrough"},
        "_Metallic_Map":     {"slot": "metallic",   "transform": "passthrough"},
        # specular workflow
        "_SpecGlossMap":     {"slot": "specular",   "transform": "passthrough"},
        "_SpecularMap":      {"slot": "specular",   "transform": "passthrough"},
        # occlusion / AO — O3DE uses occlusion.specularTextureMap; the
        # ".specular" suffix on the slot tells _process_material to expand
        # the property name.
        "_OcclusionMap":         {"slot": "occlusion.specular", "transform": "passthrough"},
        "_AOMap":                {"slot": "occlusion.specular", "transform": "passthrough"},
        "_AmbientOcclusion":     {"slot": "occlusion.specular", "transform": "passthrough"},
        "_AmbientOcclusionMap":  {"slot": "occlusion.specular", "transform": "passthrough"},
        "_AO":                   {"slot": "occlusion.specular", "transform": "passthrough"},  # MK4
        # MK4 / Alien Fantasy Forest rock shader uses prefixed names for the
        # primary surface (cover variants ignored — see ignore_unmapped).
        "_RockAlbedo":       {"slot": "baseColor",  "transform": "passthrough"},
        "_RockNormal":       {"slot": "normal",     "transform": "passthrough"},
        "_RockSpecular":     {"slot": "specular",   "transform": "passthrough"},
        # emissive
        "_EmissionMap":      {"slot": "emissive",   "transform": "passthrough"},
        "_EmissionTex":      {"slot": "emissive",   "transform": "passthrough"},
        "_EmissiveMap":      {"slot": "emissive",   "transform": "passthrough"},
        "_Emissive":         {"slot": "emissive",   "transform": "passthrough"},
        # height / parallax
        "_HeightMap":        {"slot": "height",     "transform": "passthrough"},
        "_ParallaxMap":      {"slot": "height",     "transform": "passthrough"},
        "_DisplacementMap":  {"slot": "height",     "transform": "passthrough"},
    },
    # Texture property names that are KNOWN to exist but intentionally not
    # routed — they don't have a clean 1:1 O3DE equivalent. Listed here so the
    # unmapped-property warnings don't fire for them.
    "ignore_unmapped": [
        "_DetailAlbedoMap", "_DetailMask", "_DetailNormalMap",
        "_LightTextureB0", "_VectorNoise", "_texcoord",
        # _Composite et al. are channel-packed and shader-specific.
        "_Composite", "_CompositeMap", "_MOHS", "_MaskMap",
        # MK4 / Alien Fantasy Forest detail + cover layers.
        "_Detail", "_AODetail",
        "_CoverAlbedo", "_CoverNormal", "_CoverSpecular",
    ],
    # Unity scalar / color property → O3DE materialtype property path.
    # NOTE: _Metallic, _Smoothness, _Glossiness, _GlossMapScale are handled
    # in the worker's metallic / roughness post-pass — O3DE's factor vs
    # lowerBound/upperBound semantics depend on whether a texture is bound.
    "property_map": {
        "_Color":             {"target": "baseColor.color",         "transform": "passthrough"},
        "_BaseColor":         {"target": "baseColor.color",         "transform": "passthrough"},
        "_BumpScale":         {"target": "normal.factor",           "transform": "passthrough"},
        "_OcclusionStrength": {"target": "occlusion.specularFactor", "transform": "passthrough"},
        "_EmissionColor":     {"target": "emissive.color",          "transform": "passthrough"},
    },
    "special_rules": {
        # When True, _MetallicGlossMap's alpha channel is inverted and routed
        # to the roughness slot (Unity smoothness → O3DE roughness).
        "metallic_gloss_smoothness_to_roughness": True,
    },
}


def _default_stages() -> dict:
    return {
        "asset_processor": {
            "source_path":      "",   # F-2 override (walking root for prefab scrubbing)
            "selected_prefabs": [],   # F-4 relative paths under effective_source
            "output_path":      "",
        },
        "scene_converter": {
            "source_path":     "",   # F-2 override (walking root for scene scrubbing)
            "selected_scenes": [],   # F-3 relative paths under effective_source
            "output_path":     "",
            "prefab_dirs":     [],   # legacy; supplemental dirs outside project outputs
        },
        "mesh_processor": {
            # F-5: project-wide defaults applied to every mesh unless an
            # entry exists in `overrides` for that mesh's GUID.
            "defaults": {
                "zero_position":     True,
                "default_position":  [0.0, 0.0, 0.0],
                "default_rotation":  [0.0, 0.0, 0.0],
                # When True, force-generate a whole-mesh PhysX collision
                # mesh (.pxmesh) for this FBX even if no Unity MeshCollider
                # references it. "Everything" granularity — one group over
                # all the FBX's geometry.
                "physx_mesh":        False,
                # Auto-compensation toggles (transform-truth). Default on;
                # turn off per-mesh (override) or globally (here) when the
                # auto-derived value is wrong for a specific asset.
                "auto_center":       True,   # single-mesh FBX geometry auto-center
                "auto_rotation":     True,   # Y-up→Z-up +90°X correction
            },
            # F-5: per-mesh overrides keyed by mesh GUID (from
            # outputs.asset_processor.meshes). Each value is a partial
            # dict carrying any subset of the keys above.
            "overrides": {},
            # Project-wide: emit the prefab's ContainerEntity wrapper as
            # an editor-only entity (stripped/dissolved at runtime). On by
            # default — toggled from the Meshes tab.
            "prefab_wrapper_editor_only": True,
        },
        "material_processor": {
            # F-9: defaults reference a profile name instead of a raw
            # materialtype path. The profile carries both the target
            # materialtype AND the property remap. Resolution chain at
            # emission time is:
            #   overrides[guid].profile
            #     → shader_mappings[shader_name]
            #     → defaults.profile
            # The raw-materialtype escape hatch (overrides[guid].materialtype)
            # bypasses the profile's target_materialtype after the profile
            # is selected — texture/property remap from the profile still
            # applies.
            "defaults": {
                "profile": DEFAULT_PROFILE_NAME,
            },
            # F-9 profile library. One built-in entry; F-10 will add the
            # authoring UI for custom profiles.
            "shader_profiles": {
                DEFAULT_PROFILE_NAME: copy.deepcopy(DEFAULT_SHADER_PROFILE),
            },
            # Unity shader name → profile name. Pre-seeded with common
            # Unity built-ins + the Alien Fantasy Forest pack's MK4
            # shaders, all routed through the catch-all profile.
            "shader_mappings": {
                "Standard":                             DEFAULT_PROFILE_NAME,
                "Universal Render Pipeline/Lit":        DEFAULT_PROFILE_NAME,
                "Universal Render Pipeline/Simple Lit": DEFAULT_PROFILE_NAME,
                "MK4/Foliage Fantasy":                  DEFAULT_PROFILE_NAME,
                "MK4/Foliage Fantasy no wind":          DEFAULT_PROFILE_NAME,
                "MK4/Foliage Fantasy no trans":         DEFAULT_PROFILE_NAME,
                "MK4/Rock_cover":                       DEFAULT_PROFILE_NAME,
            },
            # Per-material overrides keyed by material GUID. Each entry may
            # carry any subset of:
            #   "profile":       profile-name override (preferred)
            #   "materialtype":  raw materialtype path (escape hatch)
            #   "textures":      { slot: path, ... } per-slot texture rebinds
            "overrides": {},
        },
        "terrain_processor": {
            "source_path": "", "output_path": "",
            "selected_terrains": [],
            "outputs": ["materials", "heightmap", "splatmaps", "entity"],
        },
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
            "materials": {},   # guid → output_asset_hint (string)
            "material_metadata": {},   # guid → {shader_name, source_path, asset_hint, textures_bound}
            "meshes":    {},   # guid → output_stem (string)
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
        # F-9 per-asset state index. Each entry records the input fingerprint
        # of the most recent emission so the patch worker can detect dirty
        # assets and re-emit only those. Buckets are keyed by asset GUID;
        # each entry: { source_path, source_mtime, output_files,
        # input_hash, last_emitted }.
        "state_index": {
            "materials": {},
            "meshes":    {},
            "prefabs":   {},
            "textures":  {},
        },
    }


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge `overlay` onto `base`. Where both sides have a
    dict for the same key, recurse; otherwise `overlay` wins. Used by
    `Project.from_json` so newer schema defaults survive load even when a
    saved project file uses the same top-level key (e.g. F-6's pre-seeded
    `shader_mappings` need to fill in keys an older project's
    `shader_mappings` dict doesn't know about)."""
    out = dict(base)
    for k, v in (overlay or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


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
    source_engine:   SourceEngine
    notes:           str
    created:         str
    modified:        str
    stages:          dict
    pipeline_status: dict
    outputs:         dict = field(default_factory=_default_outputs)
    scope_root:      Optional[Path] = None
    # F-8: per-yellow-row Acknowledge state. Keys are `ack_key` strings
    # the preflight check functions emit (e.g. "material.unmapped"); each
    # value is the snapshot hash that was current when the user clicked
    # Acknowledge. The pre-flight gate re-arms whenever the snapshot drifts.
    preflight_acks:  Dict[str, str] = field(default_factory=dict)
    # Phase D — per-source-platform namespaced stages + outputs. A single
    # project preserves its Unity selections / overrides / state index
    # even when the user switches the source engine to Unreal mid-project
    # (and switches back later). The flat `stages` / `outputs` fields above
    # are live views into the active platform's slot — mutations via
    # `update_stage` / `update_outputs` pass through to the namespaced
    # storage. `__post_init__` keeps the views in sync.
    stages_by_platform:  Dict[str, dict] = field(default_factory=dict)
    outputs_by_platform: Dict[str, dict] = field(default_factory=dict)
    active_platform:     str = "unity"
    _dirty:          bool = field(default=False, repr=False)

    # -------------------------------------------------------------------------
    # Post-init — Phase D — bind `stages` / `outputs` to the active
    # platform's slot, populating from the flat fields if the caller
    # only passed those (legacy construction path) or from defaults if
    # this is a brand-new project.
    # -------------------------------------------------------------------------

    def __post_init__(self) -> None:
        active = self.active_platform or "unity"
        # If the caller didn't populate stages_by_platform, lift the flat
        # `stages` dict into the active slot. Same for outputs.
        if not self.stages_by_platform:
            self.stages_by_platform = {active: self.stages}
        elif active not in self.stages_by_platform:
            # Active platform set but no entry yet — initialise from defaults.
            self.stages_by_platform[active] = _default_stages()
        if not self.outputs_by_platform:
            self.outputs_by_platform = {active: self.outputs}
        elif active not in self.outputs_by_platform:
            self.outputs_by_platform[active] = _default_outputs()
        # Live views: same dict objects, no copies. Mutations to
        # `self.stages` propagate to `self.stages_by_platform[active]`.
        self.stages  = self.stages_by_platform[active]
        self.outputs = self.outputs_by_platform[active]
        self.active_platform = active

    # Backwards-compat alias: pre-F-9 the field was named `scope` and held a
    # ProjectScope (Whole Game / Asset Cluster / ...). Replaced by
    # `source_engine` (Unity / Unreal / Godot / Blender) but the old name
    # stays readable so any in-flight tooling keeps building.
    @property
    def scope(self) -> SourceEngine:
        return self.source_engine

    @scope.setter
    def scope(self, value: SourceEngine) -> None:
        self.source_engine = value

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_json(self) -> dict:
        """Phase D — namespaced shape. The flat `stages` / `outputs` keys
        are NOT written (the same dicts live under
        `stages_by_platform[active_platform]`). `from_json` migrates
        legacy flat-shape files on load, so a load-save round-trip is
        enough to convert a pre-Phase-D project file."""
        return {
            "schema_version":      SCHEMA_VERSION,
            "name":                self.name,
            "source_engine":       self.source_engine.value,
            "scope_root":          str(self.scope_root) if self.scope_root else "",
            "notes":               self.notes,
            "created":             self.created,
            "modified":            self.modified,
            "active_platform":     self.active_platform,
            "stages_by_platform":  self.stages_by_platform,
            "outputs_by_platform": self.outputs_by_platform,
            "pipeline_status":     self.pipeline_status,
            "preflight_acks":      dict(self.preflight_acks),
        }

    @classmethod
    def from_json(cls, data: dict, path: Optional[Path]) -> "Project":
        # Prefer the new `source_engine` key; fall back to the legacy `scope`
        # field on existing project files. `SourceEngine.from_string` already
        # maps legacy ProjectScope values (whole_game / asset_cluster /
        # asset_set / individual_action) onto UNITY, so a load-save round-trip
        # is enough to migrate a project file fully.
        engine_value    = data.get("source_engine") or data.get("scope") or "unity"
        active_platform = (data.get("active_platform") or engine_value or "unity").strip().lower()
        if not active_platform:
            active_platform = "unity"

        # Phase D migration: legacy projects carry flat `stages` /
        # `outputs`; new projects carry `stages_by_platform[name]` /
        # `outputs_by_platform[name]`. Accept either; reconcile into the
        # namespaced shape.
        raw_stages_by_plat  = data.get("stages_by_platform") or {}
        raw_outputs_by_plat = data.get("outputs_by_platform") or {}

        if not raw_stages_by_plat:
            # Legacy flat -> namespace under the active platform.
            raw_stages_by_plat = {active_platform: data.get("stages") or {}}
        if not raw_outputs_by_plat:
            raw_outputs_by_plat = {active_platform: data.get("outputs") or {}}

        # Per-platform deep-merge against `_default_stages()` so newer
        # schema defaults (shader_profiles, state_index, etc.) populate
        # missing keys without dropping user data.
        stages_by_platform: Dict[str, dict]  = {}
        outputs_by_platform: Dict[str, dict] = {}
        for plat_name, saved_stages in raw_stages_by_plat.items():
            stages = _default_stages()
            for key, saved in (saved_stages or {}).items():
                if key in stages and isinstance(saved, dict):
                    stages[key] = _deep_merge(stages[key], saved)
                else:
                    stages[key] = saved
            # F-9 one-shot normalization: material_processor switched from
            # `defaults.target_materialtype` + path-valued shader_mappings to
            # `defaults.profile` + profile-name-valued shader_mappings.
            mp = stages.get("material_processor")
            if isinstance(mp, dict):
                defaults = mp.setdefault("defaults", {})
                defaults.pop("target_materialtype", None)
                defaults.setdefault("profile", DEFAULT_PROFILE_NAME)
                profile_names = set((mp.get("shader_profiles") or {}).keys())
                mappings = mp.get("shader_mappings") or {}
                for shader, value in list(mappings.items()):
                    if value not in profile_names:
                        mappings[shader] = DEFAULT_PROFILE_NAME
            stages_by_platform[plat_name] = stages

        for plat_name, saved_outputs in raw_outputs_by_plat.items():
            outputs = _default_outputs()
            for k, v in (saved_outputs or {}).items():
                if k in outputs and isinstance(v, dict):
                    outputs[k].update(v)
                else:
                    outputs[k] = v
            outputs_by_platform[plat_name] = outputs

        # Ensure the active platform's slots exist (covers a project file
        # that listed `active_platform: unity` but no entry for unity).
        if active_platform not in stages_by_platform:
            stages_by_platform[active_platform] = _default_stages()
        if active_platform not in outputs_by_platform:
            outputs_by_platform[active_platform] = _default_outputs()

        status = _default_status()
        status.update(data.get("pipeline_status", {}))

        raw_root = (data.get("scope_root") or "").strip()
        scope_root = Path(raw_root) if raw_root else None

        # F-8 — preflight acknowledgements survive load. Missing on legacy
        # files is fine; defaults to empty so every yellow row re-arms on
        # first open under the new schema.
        preflight_acks = dict(data.get("preflight_acks") or {})

        return cls(
            path=path,
            name=data.get("name", "Untitled"),
            source_engine=SourceEngine.from_string(engine_value),
            notes=data.get("notes", ""),
            created=data.get("created",  _utc_now_iso()),
            modified=data.get("modified", _utc_now_iso()),
            stages=stages_by_platform[active_platform],
            pipeline_status=status,
            outputs=outputs_by_platform[active_platform],
            scope_root=scope_root,
            preflight_acks=preflight_acks,
            stages_by_platform=stages_by_platform,
            outputs_by_platform=outputs_by_platform,
            active_platform=active_platform,
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

    def set_source_engine(self, engine: SourceEngine) -> None:
        """Phase D — switching source engine ALSO switches the active
        platform's per-engine stages/outputs slot. Off-platform data is
        preserved untouched (the previous slot stays in
        `stages_by_platform[old]`); switching back restores it byte-for-byte.
        """
        if engine == self.source_engine and engine.value == self.active_platform:
            return
        self.source_engine = engine
        self.set_active_platform(engine.value)

    def set_active_platform(self, name: str) -> None:
        """Switch which platform's namespaced stages/outputs are the
        active view. Non-destructive: the prior platform's state stays
        in `stages_by_platform[old]` for later round-trips. The active
        platform's slot is created with `_default_stages()` /
        `_default_outputs()` on first entry."""
        name = (name or "unity").strip().lower() or "unity"
        if name == self.active_platform:
            return
        if name not in self.stages_by_platform:
            self.stages_by_platform[name] = _default_stages()
        if name not in self.outputs_by_platform:
            self.outputs_by_platform[name] = _default_outputs()
        self.active_platform = name
        # Rebind the live views.
        self.stages  = self.stages_by_platform[name]
        self.outputs = self.outputs_by_platform[name]
        self._mark_dirty()

    def set_preflight_ack(self, ack_key: str, snapshot: str) -> None:
        """F-8 — record the user's Acknowledge for a yellow preflight row.
        Storing the snapshot hash means a later condition drift (new
        unmapped shader, etc.) re-arms the row without code changes."""
        if not ack_key:
            return
        if self.preflight_acks.get(ack_key) != snapshot:
            self.preflight_acks[ack_key] = snapshot
            self._mark_dirty()

    def clear_preflight_ack(self, ack_key: str) -> None:
        if ack_key in self.preflight_acks:
            del self.preflight_acks[ack_key]
            self._mark_dirty()

    # Backwards-compat alias — see the `scope` property above. Old callers
    # that used `set_scope(...)` continue to work; new code should call
    # `set_source_engine(...)`.
    def set_scope(self, scope: SourceEngine) -> None:
        self.set_source_engine(scope)

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
        name:          str           = "Untitled Project",
        source_engine: SourceEngine  = SourceEngine.UNITY,
    ) -> Project:
        now = _utc_now_iso()
        proj = Project(
            path=None,
            name=name,
            source_engine=source_engine,
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
                source_engine=SourceEngine.UNITY,
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
        proj = pm.new_project("Smoke Test", SourceEngine.UNREAL)
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
        assert opened.source_engine == SourceEngine.UNREAL
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
        proj_root = pm.new_project("Scope Test", SourceEngine.GODOT)
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
