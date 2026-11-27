"""
=============================================================================
LIGHT COMPONENT PROCESSOR  (WEIGHT = 510)

Handles all Unity Light types and maps them to the closest O3DE equivalent.
This processor supersedes DirectionalLightComponentProcessor (weight 500)
in the parse dispatch — the old module's emit() is harmless (returns []).

Unity m_Type mapping:
    0 = Spot        → AZ::Render::EditorAreaLightComponent  (LightType 7 = SimpleSpot)
    1 = Directional → AZ::Render::EditorDirectionalLightComponent
    2 = Point       → AZ::Render::EditorAreaLightComponent  (LightType 6 = SimplePoint)
    3 = Area/Rect   → AZ::Render::EditorAreaLightComponent  (LightType 6 = SimplePoint)
                      (Unity area lights are baked-only; this is a runtime approximation)

O3DE LightType enum (EditorAreaLightComponent):
    6 = SimplePoint  — Point emitter, no shape needed
    7 = SimpleSpot   — Spot emitter with shutters, no shape needed

O3DE IntensityMode enum:
    1 = Lumen    (used for Point / Area)
    2 = Candela  (used for Spot)
=============================================================================
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import ComponentProcessor, ProcessingContext


# =============================================================================
# UNITY LIGHT TYPE CONSTANTS
# =============================================================================

UNITY_SPOT        = 0
UNITY_DIRECTIONAL = 1
UNITY_POINT       = 2
UNITY_AREA        = 3

# O3DE EditorAreaLightComponent LightType values
O3DE_SIMPLE_POINT = 6   # Simple point (no physical emitter size)
O3DE_SIMPLE_SPOT  = 7   # Simple spot  (no physical emitter size)

# O3DE IntensityMode values
INTENSITY_LUMEN   = 1
INTENSITY_CANDELA = 2

# O3DE LightAttenuationRadiusMode: 0 = Explicit (the radius given), 1 = Automatic
ATTENUATION_EXPLICIT = 0

# The component keys the lights are written under.
AREA_LIGHT        = 'AZ::Render::EditorAreaLightComponent'
DIRECTIONAL_LIGHT = 'AZ::Render::EditorDirectionalLightComponent'


# =============================================================================
# WHERE A SPOT LIGHT SITS
# An O3DE spot shines along its entity's +Z; the converted Unity object
# points its light along +Y. Something has to make the quarter turn about X
# between the two: the object's own entity, or a child entity made for the
# light. The stage option "spot_light_placement" says which.
# =============================================================================

# The object's own entity is turned where that changes nothing else: the
# object holds only the light. Any other spot goes on a child entity.
PLACEMENT_TURN  = "turn_entity"
# Every spot goes on a child entity, and every object keeps Unity's transform.
PLACEMENT_CHILD = "child_entity"
PLACEMENT_OPTION  = "spot_light_placement"
PLACEMENT_DEFAULT = PLACEMENT_TURN

# The quarter turn as the child's ``Rotate``, and as a matrix (Rx(-90)): it
# carries +Z onto +Y.
SPOT_CHILD_ROTATION = [-90.0, 0.0, 0.0]
SPOT_TURN_MATRIX    = [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]


def holds_only_a_light(go) -> bool:
    """Whether turning the object's entity changes nothing but its light:
    it shows no mesh, carries no collider or body, and nothing hangs below
    it."""
    return not (go.children_ids or go.model_children or go.mesh_guid or go.colliders
                or go.has_rigidbody or go.is_prefab_instance)


def turns_its_entity(go, placement: str) -> bool:
    """Whether a spot light is written on its object's own entity, turned
    (see ``targets.o3de.prefab_writer.with_light_turn``), instead of on a
    child entity."""
    light = go.component_data.get('unity_light') or {}
    return (placement == PLACEMENT_TURN and light.get('type') == UNITY_SPOT
            and holds_only_a_light(go))


# =============================================================================
# OVERRIDES
# What a placed prefab changes on a light inside it. Unity names the Light's
# properties; each sets one value of the O3DE light's configuration.
# =============================================================================

def light_record(go) -> Optional[Dict[str, Any]]:
    """What the entity map keeps of an object's light, for the overrides a
    prefab that nests this one may hold: the entity and component the light
    was written on, its kind, and the colour an override of one channel
    starts from. None when the object has no light written."""
    placed = go.component_data.get('light_entity')
    light = go.component_data.get('unity_light')
    if not placed or not light:
        return None
    return {"entity": placed["entity"], "component": placed["component"],
            "type": light["type"], "color": list(light["color"])}


def override_configuration(record: Dict[str, Any],
                           properties: Dict[str, Any]) -> Tuple[Dict[str, Any], set]:
    """The configuration values a set of Unity overrides gives a light, and
    the property paths that were used.

    ``record`` is the light's ``light_record``; ``properties`` is
    ``{Unity propertyPath: value}``. A Unity spot angle is the whole cone,
    an O3DE shutter angle half of it. A directional light has no range and
    no shutters. What is not listed here is left unused (bounce intensity
    and lightmapping belong to baked lighting)."""
    directional = record.get("type") == UNITY_DIRECTIONAL
    spot = record.get("type") == UNITY_SPOT
    values: Dict[str, Any] = {}
    used = set()

    def number(path: str) -> Optional[float]:
        try:
            return float(properties[path])
        except (KeyError, TypeError, ValueError):
            return None

    def take(path: str, key: str, convert=lambda value: value) -> None:
        value = number(path)
        if value is not None:
            values[key] = convert(value)
            used.add(path)

    take('m_Intensity', 'Intensity')
    take('m_Shadows.m_Type', 'Shadow Enabled' if directional else 'Enable Shadow', lambda value: value != 0)
    if not directional:
        take('m_Range', 'AttenuationRadius')
    if spot:
        take('m_SpotAngle', 'OuterShutterAngleDegrees', lambda value: value / 2.0)
        take('m_InnerSpotAngle', 'InnerShutterAngleDegrees', lambda value: value / 2.0)

    # A colour is written whole: the channels not overridden keep the light's own.
    color = list(record.get("color") or [1.0, 1.0, 1.0])
    for index, channel in enumerate(('r', 'g', 'b')):
        value = number(f'm_Color.{channel}')
        if value is not None and not directional:
            color[index] = value
            values['Color'] = color
            used.add(f'm_Color.{channel}')
    return values, used


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
        Dispatches to one of four private helpers based on light type, and
        notes where the light was written in
        go.component_data['light_entity'] (see ``light_record``).

    Which way a light shines
        A Unity light shines along its object's local +Z, which the
        transform conversion carries onto the entity's local +Y. An O3DE
        directional light shines along +Y, so it needs nothing more. An
        O3DE spot light shines along its entity's +Z
        (``SimpleSpotLightFeatureProcessor``), a quarter turn about X away.
        Where the object holds only the light, the writer has turned the
        object's own entity and the spot is written on it; otherwise, or
        when the stage option asks for it, the spot is put on a child
        entity that makes the turn, and the object's entity keeps Unity's
        transform for whatever else it carries.

    How far a light reaches
        Unity's Range is where the light ends. O3DE works a radius out
        from the intensity unless told otherwise, so every light is written
        with the attenuation radius mode Explicit and Unity's range.

    A point light
        Unity's point light has no size. It is written as a simple point
        light: the sphere light it was written as before needs a sphere
        shape beside it, drawn in the Editor over the light's range.
    """

    WEIGHT  = 510
    HANDLES = ['Light']
    EMITS   = [DIRECTIONAL_LIGHT, AREA_LIGHT]

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
            '$type': AREA_LIGHT,
            'Id':    ctx.generate_component_id(),
            'Controller': {'Configuration': config},
        }

    @staticmethod
    def _note_placement(go, entity_id: str, component: str) -> None:
        """Where the light was written, for the entity map."""
        go.component_data['light_entity'] = {"entity": entity_id, "component": component}

    # -------------------------------------------------------------------------
    # EMIT — per-type helpers
    # -------------------------------------------------------------------------

    def _emit_directional(self, data: Dict, entity: Dict, go,
                           ctx: ProcessingContext) -> None:
        """Emit EditorDirectionalLightComponent. The entity's transform is
        left as the writer made it: a Unity light shines along its local +Z,
        an O3DE light along its local +Y, and the axis swap of the transform
        conversion carries one onto the other."""
        entity['Components'][DIRECTIONAL_LIGHT] = {
            '$type': DIRECTIONAL_LIGHT,
            'Id':    ctx.generate_component_id(),
            'Controller': {
                'Configuration': {
                    'Intensity':      data['intensity'],
                    'CameraEntityId': '',
                    'Shadow Enabled': data['shadows'],
                }
            },
        }
        self._note_placement(go, entity['Id'], DIRECTIONAL_LIGHT)
        ctx.log(
            f"  [Light] ✓ DirectionalLight — "
            f"intensity={data['intensity']}, shadows={data['shadows']}"
        )

    def _emit_point(self, data: Dict, entity: Dict, go,
                    ctx: ProcessingContext) -> None:
        """Emit EditorAreaLightComponent (SimplePoint)."""
        entity['Components'][AREA_LIGHT] = self._area_light_component({
            'LightType':         O3DE_SIMPLE_POINT,
            'AttenuationRadiusMode': ATTENUATION_EXPLICIT,
            'Color':             data['color'],
            'IntensityMode':     INTENSITY_LUMEN,
            'Intensity':         data['intensity'],
            'AttenuationRadius': data['range'],
            'Enable Shadow':     data['shadows'],
        }, ctx)
        self._note_placement(go, entity['Id'], AREA_LIGHT)
        ctx.log(
            f"  [Light] ✓ PointLight (SimplePoint) — "
            f"intensity={data['intensity']} lm, range={data['range']}"
        )

    def _emit_spot(self, data: Dict, entity: Dict, go,
                   ctx: ProcessingContext) -> str:
        """Emit EditorAreaLightComponent (SimpleSpot) with shutter angles so
        the spot shines where Unity's does: on the object's own entity when
        the writer has turned it (``light_turns_entity``), otherwise on a
        child entity that makes the turn. Returns the child's id, or ""."""
        component = self._area_light_component({
            'LightType':                O3DE_SIMPLE_SPOT,
            'AttenuationRadiusMode':    ATTENUATION_EXPLICIT,
            'Color':                    data['color'],
            'IntensityMode':            INTENSITY_CANDELA,
            'Intensity':                data['intensity'],
            'AttenuationRadius':        data['range'],
            'EnableShutters':           True,
            'InnerShutterAngleDegrees': data['spot_inner'],
            'OuterShutterAngleDegrees': data['spot_outer'],
            'Enable Shadow':            data['shadows'],
        }, ctx)

        child_id = ""
        if go.component_data.get('light_turns_entity'):
            entity['Components'][AREA_LIGHT] = component
            self._note_placement(go, entity['Id'], AREA_LIGHT)
        else:
            child_id = ctx.generate_entity_id()
            child = ctx.make_bare_entity(child_id, f"{go.name}_Light", entity['Id'])
            child['Components']['TransformComponent']['Transform Data'] = {
                'Translate': [0.0, 0.0, 0.0], 'Rotate': list(SPOT_CHILD_ROTATION)}
            child['Components'][AREA_LIGHT] = component
            ctx.entities_dict[child_id] = child
            self._note_placement(go, child_id, AREA_LIGHT)
        ctx.log(
            f"  [Light] ✓ SpotLight (SimpleSpot, {'own entity turned' if not child_id else 'child entity'}) — "
            f"intensity={data['intensity']} cd, range={data['range']}, "
            f"outer={data['spot_outer']:.1f}°, inner={data['spot_inner']:.1f}°"
        )
        return child_id

    def _emit_area(self, data: Dict, entity: Dict, go,
                   ctx: ProcessingContext) -> None:
        """
        Emit EditorAreaLightComponent (SimplePoint) as a runtime approximation.
        Unity area lights are baked-only and have no direct real-time equivalent;
        SimplePoint preserves position, color, and approximate intensity.
        """
        entity['Components'][AREA_LIGHT] = self._area_light_component({
            'LightType':         O3DE_SIMPLE_POINT,
            'AttenuationRadiusMode': ATTENUATION_EXPLICIT,
            'Color':             data['color'],
            'IntensityMode':     INTENSITY_LUMEN,
            'Intensity':         data['intensity'],
            'AttenuationRadius': data['range'],
            'Affects GI':        True,
            'Affects GI Factor': 1.0,
        }, ctx)
        self._note_placement(go, entity['Id'], AREA_LIGHT)
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
        child_ids: List[str] = []
        if handler:
            child_id = handler(data, entity, go, ctx)
            if child_id:
                child_ids.append(child_id)
            ctx.stats["Lights"] = ctx.stats.get("Lights", 0) + 1

        return child_ids
