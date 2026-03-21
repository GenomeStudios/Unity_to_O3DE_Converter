"""
=============================================================================
LIGHT COMPONENT PROCESSOR  (WEIGHT = 510)

Handles all Unity Light types and maps them to the closest O3DE equivalent.
This processor supersedes DirectionalLightComponentProcessor (weight 500)
in the parse dispatch — the old module's emit() is harmless (returns []).

Unity m_Type mapping:
    0 = Spot        → AZ::Render::EditorAreaLightComponent  (LightType 7 = SimpleSpot)
    1 = Directional → AZ::Render::EditorDirectionalLightComponent
    2 = Point       → AZ::Render::EditorAreaLightComponent  (LightType 1 = Sphere)
                      + EditorSphereShapeComponent
    3 = Area/Rect   → AZ::Render::EditorAreaLightComponent  (LightType 6 = SimplePoint)
                      (Unity area lights are baked-only; this is a runtime approximation)

O3DE LightType enum (EditorAreaLightComponent):
    1 = Sphere       — Physical sphere emitter, needs EditorSphereShapeComponent
    6 = SimplePoint  — Point emitter, no shape needed
    7 = SimpleSpot   — Spot emitter with shutters, no shape needed

O3DE IntensityMode enum:
    1 = Lumen    (used for Point / Area)
    2 = Candela  (used for Spot)
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext


# =============================================================================
# UNITY LIGHT TYPE CONSTANTS
# =============================================================================

UNITY_SPOT        = 0
UNITY_DIRECTIONAL = 1
UNITY_POINT       = 2
UNITY_AREA        = 3

# O3DE EditorAreaLightComponent LightType values
O3DE_SPHERE       = 1   # Physical sphere point light
O3DE_SIMPLE_POINT = 6   # Simple point (no physical emitter size)
O3DE_SIMPLE_SPOT  = 7   # Simple spot  (no physical emitter size)

# O3DE IntensityMode values
INTENSITY_LUMEN   = 1
INTENSITY_CANDELA = 2

# Default physical size for sphere lights (Unity has no emitter-area concept)
DEFAULT_SPHERE_RADIUS = 0.05


# =============================================================================
# PROCESSOR
# =============================================================================

class LightComponentProcessor(ComponentProcessor):
    """
    Parse phase:
        Reads all Unity Light fields — type, color, intensity, range,
        spot angles, shadow toggle — and stores them in
        go.component_data['unity_light'].

    Emit phase:
        Dispatches to one of four private helpers based on light type.
        Directional lights also flip the pitch 180° to match O3DE's
        opposite-facing convention.
    """

    WEIGHT  = 510
    HANDLES = ['Light']
    EMITS   = [
        'AZ::Render::EditorDirectionalLightComponent',
        'AZ::Render::EditorAreaLightComponent',
        'EditorSphereShapeComponent',
    ]

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    @staticmethod
    def _to_int(value) -> int:
        """Safely coerce a Unity value to int (handles m_Shadows dicts)."""
        if isinstance(value, dict):
            return int(value.get('m_Type', value.get('value', 0)))
        return int(value)

    @staticmethod
    def _extract_color(m_color) -> List[float]:
        """Convert Unity m_Color (dict or RGBA list) to an O3DE [r, g, b] list."""
        if isinstance(m_color, dict):
            return [
                float(m_color.get('r', 1.0)),
                float(m_color.get('g', 1.0)),
                float(m_color.get('b', 1.0)),
            ]
        if isinstance(m_color, (list, tuple)) and len(m_color) >= 3:
            return [float(m_color[0]), float(m_color[1]), float(m_color[2])]
        return [1.0, 1.0, 1.0]

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:

        light_type = self._to_int(comp_data.get('m_Type', -1))

        if light_type not in (UNITY_SPOT, UNITY_DIRECTIONAL, UNITY_POINT, UNITY_AREA):
            log(f"    [Light] Unknown Unity light type {light_type} on '{go.name}' — skipping")
            return

        # Spot angle: Unity stores the *full* cone angle; O3DE uses half-angles.
        # m_InnerSpotAngle was added in Unity 2020+; fall back to half of outer.
        outer_full = float(comp_data.get('m_SpotAngle', 30.0))
        inner_full = float(comp_data.get('m_InnerSpotAngle', outer_full * 0.5))

        go.component_data['unity_light'] = {
            'type':       light_type,
            'color':      self._extract_color(comp_data.get('m_Color', {})),
            'intensity':  float(comp_data.get('m_Intensity', 1.0)),
            'range':      float(comp_data.get('m_Range', 10.0)),
            'shadows':    self._to_int(comp_data.get('m_Shadows', 0)) != 0,
            'spot_outer': outer_full / 2.0,   # half-angle for O3DE
            'spot_inner': inner_full / 2.0,   # half-angle for O3DE
        }

        type_name = {
            UNITY_SPOT: 'Spot', UNITY_DIRECTIONAL: 'Directional',
            UNITY_POINT: 'Point', UNITY_AREA: 'Area',
        }.get(light_type, '?')
        log(
            f"    [Light] {type_name} → "
            f"intensity={go.component_data['unity_light']['intensity']}, "
            f"range={go.component_data['unity_light']['range']}, "
            f"shadows={go.component_data['unity_light']['shadows']}"
        )

    # -------------------------------------------------------------------------
    # EMIT — shared builders
    # -------------------------------------------------------------------------

    def _area_light_component(self, config: Dict, ctx: ProcessingContext) -> Dict:
        return {
            '$type': 'AZ::Render::EditorAreaLightComponent',
            'Id':    ctx.generate_component_id(),
            'Controller': {'Configuration': config},
        }

    def _sphere_shape_component(self, color: List[float], radius: float,
                                 ctx: ProcessingContext) -> Dict:
        return {
            '$type':      'EditorSphereShapeComponent',
            'Id':         ctx.generate_component_id(),
            'ShapeColor': [color[0], color[1], color[2], 1.0],
            'SphereShape': {'Configuration': {'Radius': radius}},
        }

    # -------------------------------------------------------------------------
    # EMIT — per-type helpers
    # -------------------------------------------------------------------------

    def _emit_directional(self, data: Dict, entity: Dict, go,
                           ctx: ProcessingContext) -> None:
        """Emit EditorDirectionalLightComponent with a 180° pitch flip."""
        tc  = entity['Components'].get('TransformComponent', {})
        td  = tc.setdefault('Transform Data', {})
        rot = list(td.get('Rotate', [0.0, 0.0, 0.0]))
        rot[0] = ((rot[0] + 180.0 + 180.0) % 360.0) - 180.0   # add 180°, normalize to [-180, 180]
        td['Rotate'] = rot

        entity['Components']['AZ::Render::EditorDirectionalLightComponent'] = {
            '$type': 'AZ::Render::EditorDirectionalLightComponent',
            'Id':    ctx.generate_component_id(),
            'Controller': {
                'Configuration': {
                    'Intensity':      data['intensity'],
                    'CameraEntityId': '',
                    'Shadow Enabled': data['shadows'],
                }
            },
        }
        ctx.log(
            f"  [Light] ✓ DirectionalLight — "
            f"intensity={data['intensity']}, shadows={data['shadows']}, "
            f"pitch flipped to {rot[0]:.2f}°"
        )

    def _emit_point(self, data: Dict, entity: Dict, go,
                    ctx: ProcessingContext) -> None:
        """Emit EditorAreaLightComponent (Sphere) + EditorSphereShapeComponent."""
        color = data['color']
        entity['Components']['AZ::Render::EditorAreaLightComponent'] = self._area_light_component({
            'LightType':         O3DE_SPHERE,
            'Color':             color,
            'IntensityMode':     INTENSITY_LUMEN,
            'Intensity':         data['intensity'],
            'AttenuationRadius': data['range'],
            'Enable Shadow':     data['shadows'],
        }, ctx)
        entity['Components']['EditorSphereShapeComponent'] = self._sphere_shape_component(
            color, DEFAULT_SPHERE_RADIUS, ctx
        )
        ctx.log(
            f"  [Light] ✓ PointLight (Sphere) — "
            f"intensity={data['intensity']} lm, range={data['range']}"
        )

    def _emit_spot(self, data: Dict, entity: Dict, go,
                   ctx: ProcessingContext) -> None:
        """Emit EditorAreaLightComponent (SimpleSpot) with shutter angles."""
        entity['Components']['AZ::Render::EditorAreaLightComponent'] = self._area_light_component({
            'LightType':                O3DE_SIMPLE_SPOT,
            'Color':                    data['color'],
            'IntensityMode':            INTENSITY_CANDELA,
            'Intensity':                data['intensity'],
            'AttenuationRadius':        data['range'],
            'EnableShutters':           True,
            'InnerShutterAngleDegrees': data['spot_inner'],
            'OuterShutterAngleDegrees': data['spot_outer'],
            'Enable Shadow':            data['shadows'],
        }, ctx)
        ctx.log(
            f"  [Light] ✓ SpotLight (SimpleSpot) — "
            f"intensity={data['intensity']} cd, range={data['range']}, "
            f"outer={data['spot_outer']:.1f}°, inner={data['spot_inner']:.1f}°"
        )

    def _emit_area(self, data: Dict, entity: Dict, go,
                   ctx: ProcessingContext) -> None:
        """
        Emit EditorAreaLightComponent (SimplePoint) as a runtime approximation.
        Unity area lights are baked-only and have no direct real-time equivalent;
        SimplePoint preserves position, color, and approximate intensity.
        """
        entity['Components']['AZ::Render::EditorAreaLightComponent'] = self._area_light_component({
            'LightType':         O3DE_SIMPLE_POINT,
            'Color':             data['color'],
            'IntensityMode':     INTENSITY_LUMEN,
            'Intensity':         data['intensity'],
            'AttenuationRadius': data['range'],
            'Affects GI':        True,
            'Affects GI Factor': 1.0,
        }, ctx)
        ctx.log(
            f"  [Light] ✓ AreaLight → SimplePoint (approx) — "
            f"intensity={data['intensity']} lm, range={data['range']}"
        )

    # -------------------------------------------------------------------------
    # EMIT — main entry point
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        data = go.component_data.get('unity_light')
        if not data:
            return []

        dispatch = {
            UNITY_DIRECTIONAL: self._emit_directional,
            UNITY_POINT:       self._emit_point,
            UNITY_SPOT:        self._emit_spot,
            UNITY_AREA:        self._emit_area,
        }
        handler = dispatch.get(data['type'])
        if handler:
            handler(data, entity, go, ctx)
            ctx.stats["Lights"] = ctx.stats.get("Lights", 0) + 1

        return []
