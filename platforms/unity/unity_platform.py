"""
=============================================================================
UNITY SOURCE-PLATFORM PLUGIN  (platforms.unity.unity_platform)
=============================================================================

Reference implementation of ``SourcePlatform`` for Unity-sourced projects.
Wraps the Phase-A modules — ``platforms.unity.asset_database``,
``platforms.unity.shader``, and the existing ``components/`` directory —
into a single conformant object.

The class is mostly thin glue. Heavy lifting lives in the moved
modules. Methods that require deep IAP integration (full
``parse_prefab`` returning a ``PlatformPrefab`` graph) raise
``NotImplementedError`` for now — they ship in Phase C when the worker
swaps onto the contract.

Phase B verification covers the parts that ARE implemented:
identity constants, default_profiles, default_shader_mappings,
scope_root_label, validate_scope_root, component_processors,
parse_material, resolve_shader_name, to_o3de_coordinates,
build_asset_index, scrub_* (read existing scope-walking code).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# Reusing the Phase-A moves.
from platforms.base import SourcePlatform
from platforms.types import (
    AssetIndex, PlatformMaterial, PlatformPrefab, PlatformScene,
    PlatformTransform,
)
from platforms.unity.asset_database import AssetDatabase
from platforms.unity.shader import resolve_shader_name as _resolve_shader_name


# Y-up correction quaternion. Currently mirrored from the O3DE writer
# (Phase A.3 location). Phase B keeps this duplication: the writer's
# constant is the legacy path; this constant is what `to_o3de_coordinates`
# uses. Phase C consolidates by having the writer take a correction
# quaternion parameter from the platform.
_UNITY_Y_UP_TO_O3DE_Z_UP_QUAT = [0.7071067690849304, 0.0, 0.0, 0.7071067094802856]


class UnityPlatform(SourcePlatform):
    """Unity source plugin. The reference implementation.

    Instantiate once at module import; ``platforms.__init__`` registers it.

    Dependency-injected state
    -------------------------
    The plugin holds an optional ``_asset_db`` reference set by
    ``bind_asset_db(db)``. When set, ``parse_material`` /
    ``resolve_shader_name`` route GUID resolution through the
    worker-owned ``AssetDatabase`` instead of building a fresh one
    from a heuristic scope root.

    The worker (``IntegratedAssetProcessor``) calls ``bind_asset_db``
    immediately after constructing its own ``AssetDatabase`` so the
    plugin's parse methods read from the same GUID index the worker
    uses. Standalone callers (tests, plugin validation scripts) can
    skip the bind and ``parse_material`` falls back to the
    "construct from path heuristic" path it used in Phase B.
    """

    def __init__(self):
        super().__init__()
        # Worker-supplied AssetDatabase. None until ``bind_asset_db`` is
        # called. The default fallback in ``parse_material`` /
        # ``resolve_shader_name`` builds a fresh DB scoped to the
        # material file's parent — fine for tests, sub-optimal for the
        # worker since it duplicates GUID indexing.
        self._asset_db = None

    def bind_asset_db(self, asset_db) -> None:
        """Bind a worker-owned ``AssetDatabase``. Subsequent
        ``parse_material`` / ``resolve_shader_name`` calls consult it
        instead of building a new one."""
        self._asset_db = asset_db

    def unbind_asset_db(self) -> None:
        """Clear the bound ``AssetDatabase``. Used between worker runs
        so a stale reference doesn't leak across project switches."""
        self._asset_db = None

    # ----- IDENTITY -----------------------------------------------------

    NAME        = "unity"
    DISPLAY     = "Unity"
    DESCRIPTION = ("Unity Editor projects. Parses .prefab / .unity / "
                   ".mat / .shader / .meta assets discovered under the "
                   "project's Assets/ folder.")
    FILE_EXTENSIONS = {
        "prefab":   "*.prefab",
        "scene":    "*.unity",
        "material": "*.mat",
        "shader":   ["*.shader", "*.shadergraph"],
        "mesh":     ["*.fbx", "*.obj", "*.dae", "*.blend",
                     "*.3ds", "*.max", "*.ma", "*.mb"],
        "texture":  ["*.png", "*.jpg", "*.jpeg", "*.tga", "*.tif",
                     "*.tiff", "*.bmp", "*.psd", "*.exr", "*.hdr"],
        "terrain":  "*.terrain",
        "meta":     "*.meta",
    }
    UP_AXIS    = "Y"
    HANDEDNESS = "LH"

    @property
    def correction_quat(self) -> list:
        """Source-axis correction quaternion the O3DE assetinfo writer
        composes onto every emitted CoordinateSystemRule. Unity's
        constant lives in ``platforms.unity.coordinates``."""
        from platforms.unity.coordinates import UNITY_Y_UP_TO_O3DE_Z_UP_QUAT
        return UNITY_Y_UP_TO_O3DE_Z_UP_QUAT

    # ----- DISCOVERY ----------------------------------------------------

    def scope_root_label(self) -> str:
        return "Unity project root"

    def validate_scope_root(self, path: Path):
        from preflight import PreflightItem
        out: List = []
        if not path.exists():
            out.append(PreflightItem(
                category="environment", severity="red",
                title="Unity scope root does not exist",
                detail=str(path),
                fix_hint="Re-pick the Source Root on the Dashboard.",
            ))
            return out
        if not path.is_dir():
            out.append(PreflightItem(
                category="environment", severity="red",
                title="Unity scope root is not a directory",
                detail=str(path),
            ))
            return out
        # Unity convention — the project root contains an Assets/ folder.
        # Soft warning (not fatal): some Unity sub-folders ARE valid scope
        # roots when the user wants to convert a subset.
        if not (path / "Assets").is_dir():
            out.append(PreflightItem(
                category="environment", severity="yellow",
                title="No Assets/ folder under scope root",
                detail=(f"{path} doesn't contain an Assets/ folder. The "
                        f"Unity plugin can still walk this directory but "
                        f"GUID resolution may miss assets that live "
                        f"alongside Assets/ in the standard Unity layout."),
                fix_hint="Either point the Source Root at the project root "
                          "(parent of Assets/) or Acknowledge if you're "
                          "intentionally converting a sub-folder.",
                ack_key="unity.no_assets_dir",
            ))
        return out

    def build_asset_index(self, scope_root: Path) -> AssetIndex:
        """Walk the scope and produce an asset-id index.

        Wraps Unity's GUID-from-.meta indexing (``AssetDatabase``).
        Plugin authors targeting other engines build their own index from
        whatever id scheme the engine uses (Unreal soft paths, Godot
        ``res://`` paths, Blender lib+name pairs).
        """
        db = AssetDatabase(scope_root)
        index = AssetIndex(extensions_by_kind={
            k: (v if isinstance(v, str) else v[0])
            for k, v in self.FILE_EXTENSIONS.items()
        })
        index.by_id   = dict(db.guid_to_path)
        index.by_path = {p: g for g, p in db.guid_to_path.items()}
        return index

    def scrub_prefabs(self, scope_root: Path) -> List[str]:
        return sorted(
            str(p.relative_to(scope_root)).replace("\\", "/")
            for p in scope_root.rglob("*.prefab")
        )

    def scrub_scenes(self, scope_root: Path) -> List[str]:
        return sorted(
            str(p.relative_to(scope_root)).replace("\\", "/")
            for p in scope_root.rglob("*.unity")
        )

    def scrub_terrain(self, scope_root: Path) -> List[str]:
        return sorted(
            str(p.relative_to(scope_root)).replace("\\", "/")
            for p in scope_root.rglob("*.terrain")
        )

    # ----- EXTRACTION ---------------------------------------------------

    def parse_material(self, path: Path) -> PlatformMaterial:
        """Parse a Unity ``.mat`` into a ``PlatformMaterial``.

        When a worker-supplied ``AssetDatabase`` is bound (via
        ``bind_asset_db``), reuse it. Otherwise fall back to constructing
        a one-off DB scoped to the material file's grandparent directory
        — the legacy Phase-B path, still useful for standalone tooling
        and plugin-validation scripts.
        """
        db = self._asset_db if self._asset_db is not None else self._fallback_asset_db(path)
        raw = db.parse_material(path)
        if not raw:
            return PlatformMaterial(name=path.stem)
        return PlatformMaterial(
            name=raw.get("name", path.stem),
            shader_id=raw.get("shader_guid", ""),
            shader_fileid=raw.get("shader_fileid", 0),
            raw_textures=dict(raw.get("textures", {})),
            raw_floats=dict(raw.get("properties", {})),  # legacy: post-extract
            raw_colors={},                                # see note below
            extra={"legacy_extracted": raw, "source_path": str(path)},
        )
        # NOTE: Phase A's ``parse_material`` returns POST-extraction data —
        # ``raw["textures"]`` is already keyed by O3DE slot names, and
        # ``raw["properties"]`` is already keyed by O3DE prop paths.
        # That's not what ``PlatformMaterial.raw_textures`` is supposed to
        # carry (raw, source-keyed). A future iteration reworks the parser
        # to expose both raw and post-extract views. For now the ``extra``
        # field carries the full legacy dict; consumers that need raw views
        # call ``mat.extra["legacy_extracted"]``.

    @staticmethod
    def _fallback_asset_db(path: Path):
        """Build a fresh ``AssetDatabase`` rooted at the material file's
        grandparent dir — the heuristic Phase-B path. The worker should
        ``bind_asset_db`` so this never fires in production."""
        scope = (path.parent.parent
                 if path.parent.parent.exists()
                 else path.parent)
        return AssetDatabase(scope)

    def parse_prefab(self, path: Path) -> PlatformPrefab:
        """Read a Unity ``.prefab`` into a neutral ``PlatformPrefab``.

        Builds a minimal ``UnityParseContext`` (no-op log, fresh
        CoverageTracker, the plugin's component dispatch) and routes
        through ``platforms.unity.prefab.parse_unity_prefab``. The
        resulting worker-tuple ``(game_objects, transform_map)`` is
        then converted into the neutral shape:

          - ``root`` = first GameObject whose ``parent_id is None``.
          - ``entities`` = ``{file_id: PlatformEntity(...)}``.
          - ``parent_map`` = ``{file_id: parent_file_id_or_None}``.

        Each Unity GameObject contributes a ``PlatformEntity`` whose
        ``transform`` is converted from Unity-space (Y-up, LH) to a
        neutral ``PlatformTransform`` via the
        :meth:`unity_transform_to_platform_transform` helper.

        Standalone callers that prefer the worker-tuple shape can
        still call ``platforms.unity.prefab.parse_unity_prefab(ctx, path)``
        directly. The neutral shape is documented as the contract
        return type.
        """
        from platforms.unity.prefab import UnityParseContext, parse_unity_prefab

        # Component dispatch from the plugin's processor library so the
        # parser can record handled-vs-unhandled component types into
        # coverage. Coverage is a throwaway here — standalone callers
        # don't see the report; worker-driven runs build their own.
        try:
            from platforms.unity.components import build_dispatch_table
            processors = self.component_processors()
            dispatch   = build_dispatch_table(processors)
        except Exception:
            dispatch = {}

        coverage = _PlatformCoverageStub()
        ctx = UnityParseContext(
            log=lambda _msg: None,
            coverage=coverage,
            component_dispatch=dispatch,
        )
        game_objects, _transform_map = parse_unity_prefab(ctx, path)
        return self._unity_game_objects_to_platform_prefab(game_objects)

    def parse_scene(self, path: Path) -> PlatformScene:
        """Read a Unity ``.unity`` scene into a ``PlatformScene``.

        Scene files have the same multi-document YAML shape as prefabs
        (``Transform`` / ``GameObject`` / ``PrefabInstance`` blocks +
        component blocks) so the prefab parser handles them too. This
        method delegates to :meth:`parse_prefab` — the produced
        ``PlatformPrefab`` IS a ``PlatformScene`` since the types
        currently alias.

        Plugin authors that need scene-specific metadata
        (skybox refs, render settings) can override this and emit
        an enriched return shape later — at which point
        ``PlatformScene`` becomes a distinct dataclass.
        """
        return self.parse_prefab(path)

    @staticmethod
    def unity_transform_to_platform_transform(transform):
        """Convert a Unity ``Transform`` (tuples) to a neutral
        ``PlatformTransform`` (lists). Identity-preserving — no
        coordinate-system shift; ``to_o3de_coordinates`` is the
        method that swizzles."""
        return PlatformTransform(
            translation=list(transform.position),
            rotation=list(transform.rotation),
            scale=list(transform.scale),
        )

    def _unity_game_objects_to_platform_prefab(self, game_objects: Dict
                                                ) -> PlatformPrefab:
        """Convert the worker-tuple GameObject dict to a neutral
        ``PlatformPrefab``."""
        from platforms.types import PlatformEntity

        entities: Dict[str, PlatformEntity] = {}
        parent_map: Dict[str, Any] = {}
        root: str = ""
        for file_id, go in game_objects.items():
            entities[file_id] = PlatformEntity(
                entity_id=file_id,
                name=go.name or "",
                transform=self.unity_transform_to_platform_transform(go.transform),
                mesh_id=go.mesh_guid,
                material_ids=list(go.material_guids),
                # Raw components carry the platform-specific component
                # data dicts the dispatch table consumed during parse.
                raw_components=[
                    {"type": c.type_name, "file_id": c.file_id, "data": c.data}
                    for c in go.components
                ],
            )
            parent_map[file_id] = go.parent_id
            if go.parent_id is None and not root:
                root = file_id
        # Fall back to the first entity when no obvious root exists
        # (degenerate prefabs sometimes have multiple roots; the parser
        # logs a warning for that case).
        if not root and entities:
            root = next(iter(entities))
        return PlatformPrefab(root=root, entities=entities, parent_map=parent_map)

    def resolve_shader_name(self, material: PlatformMaterial) -> str:
        """Resolve a material's shader reference to its friendly name.

        Delegates to ``platforms.unity.shader.resolve_shader_name``.
        Uses the worker-supplied ``AssetDatabase`` when bound; otherwise
        falls back to a heuristic build from the material's source path
        (carried on ``material.extra`` by ``parse_material``)."""
        if not material.shader_id and not material.shader_fileid:
            return ""
        db = self._asset_db if self._asset_db is not None \
             else self._infer_asset_db(material)
        return _resolve_shader_name(
            asset_db=db,
            shader_guid=material.shader_id,
            shader_fileid=material.shader_fileid,
        )

    @staticmethod
    def _infer_asset_db(material: PlatformMaterial):
        """Fallback asset_db builder for standalone calls. The worker
        should ``bind_asset_db`` to skip this entirely."""
        source = material.extra.get("source_path") or ""
        if not source:
            legacy = material.extra.get("legacy_extracted") or {}
            source = legacy.get("source_path") or ""
        if not source:
            raise RuntimeError(
                "UnityPlatform.resolve_shader_name was called without a "
                "bound asset_db or a source_path on the material. The "
                "worker should call bind_asset_db(...) before invoking "
                "platform methods. Standalone callers must set "
                "material.extra['source_path']."
            )
        return AssetDatabase(Path(source).parent.parent)

    # ----- PROFILE LIBRARY ----------------------------------------------

    def default_profiles(self) -> Dict[str, dict]:
        """Return the catch-all + any built-in named profiles the plugin
        ships. Currently just the F-9 default — Phase B keeps the dict
        in ``project_manager`` for backwards compatibility; Phase C/F-10
        moves authored profiles here."""
        from project_manager import (
            DEFAULT_PROFILE_NAME, DEFAULT_SHADER_PROFILE,
        )
        return {DEFAULT_PROFILE_NAME: copy.deepcopy(DEFAULT_SHADER_PROFILE)}

    def default_shader_mappings(self) -> Dict[str, str]:
        """Pre-seeded ``Unity shader name → profile name`` mappings.

        Currently mirrors the F-9 pre-seeded set in
        ``project_manager._default_stages``. Phase C consults this
        directly when constructing a new project's material_processor
        stage, so the project manager won't carry Unity-specific
        defaults anymore."""
        from project_manager import DEFAULT_PROFILE_NAME
        return {
            "Standard":                             DEFAULT_PROFILE_NAME,
            "Universal Render Pipeline/Lit":        DEFAULT_PROFILE_NAME,
            "Universal Render Pipeline/Simple Lit": DEFAULT_PROFILE_NAME,
            "MK4/Foliage Fantasy":                  DEFAULT_PROFILE_NAME,
            "MK4/Foliage Fantasy no wind":          DEFAULT_PROFILE_NAME,
            "MK4/Foliage Fantasy no trans":         DEFAULT_PROFILE_NAME,
            "MK4/Rock_cover":                       DEFAULT_PROFILE_NAME,
        }

    # ----- COMPONENT PROCESSORS -----------------------------------------

    def component_processors(self) -> List[Any]:
        """Auto-discovered Unity component processors from the canonical
        ``platforms.unity.components`` directory. The legacy
        ``components/`` shim is preserved for back-compat imports but
        no longer the source of truth."""
        from platforms.unity.components import load_component_processors
        return load_component_processors(log=None)

    # ----- COORDINATE SYSTEM --------------------------------------------

    def to_o3de_coordinates(self, transform: PlatformTransform
                            ) -> Tuple[PlatformTransform, bool]:
        """Convert Unity-space (Y-up, LH) transform to O3DE-space
        (Z-up, RH). Mirrors the existing
        ``IntegratedAssetProcessor._convert_to_o3de_coordinates``
        but operates on the neutral ``PlatformTransform`` type.

        Returns ``(converted, scale_was_non_uniform)``."""
        tx, ty, tz = transform.translation
        # Unity → O3DE: swap Y and Z, flip nothing else for translation
        # and (with the quaternion swap) for the basis vectors. This
        # matches the legacy converter's (x, z, y) swizzle.
        new_translation = [tx, tz, ty]

        qx, qy, qz, qw = transform.rotation
        new_rotation = [qx, qz, qy, qw]

        sx, sy, sz = transform.scale
        new_scale = [sx, sz, sy]
        non_uniform = not (abs(new_scale[0] - new_scale[1]) < 1e-6
                            and abs(new_scale[1] - new_scale[2]) < 1e-6)

        return (PlatformTransform(translation=new_translation,
                                   rotation=new_rotation,
                                   scale=new_scale),
                non_uniform)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PlatformCoverageStub:
    """Minimal CoverageTracker stand-in for standalone
    ``UnityPlatform.parse_prefab`` calls. Records nothing — the real
    coverage tracker lives on the worker and is consulted by
    worker-driven runs."""

    def record_component(self, unity_type, handler_name) -> None: pass
    def record_modification(self, *_a, **_kw) -> None: pass
    def record_added_component(self) -> None: pass
    def record_removed_component(self) -> None: pass
    def record_added_gameobject(self) -> None: pass
    def record_missing_texture(self, _guid) -> None: pass
    def record_missing_mesh(self, _guid) -> None: pass
    def record_missing_material(self, _guid) -> None: pass
    def record_missing_prefab(self, _guid) -> None: pass
    def record_light_type(self, _t) -> None: pass
    def warn(self, _msg: str) -> None: pass
    def to_dict(self) -> Dict[str, Any]: return {}
