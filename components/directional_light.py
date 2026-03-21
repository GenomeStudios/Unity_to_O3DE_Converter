"""
=============================================================================
DIRECTIONAL LIGHT COMPONENT PROCESSOR  (WEIGHT = 500)

Handles:  Light  (Unity type 1 = Directional)
Emits:    AZ::Render::EditorDirectionalLightComponent
=============================================================================
"""

from typing import Callable, Dict, List

from .base import ComponentProcessor, ProcessingContext


class DirectionalLightComponentProcessor(ComponentProcessor):
    """
    Parse phase:
      Unity Light component with m_Type == 1 (Directional).
      Reads intensity and shadow settings into go.component_data['directional_light'].
      Non-directional light types are ignored (logged and skipped).

    Emit phase:
      Writes EditorDirectionalLightComponent with intensity and shadow enabled flag.
      Intensity is passed through directly from Unity (lux).
    """

    WEIGHT  = 500
    HANDLES = ['Light']
    EMITS   = ['AZ::Render::EditorDirectionalLightComponent']

    UNITY_TYPE_DIRECTIONAL = 1

    @staticmethod
    def _to_int(value) -> int:
        """Safely convert a value to int — handles Unity scene dicts (e.g. m_Shadows struct)."""
        if isinstance(value, dict):
            return int(value.get('m_Type', value.get('value', 0)))
        return int(value)

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:

        light_type = self._to_int(comp_data.get('m_Type', -1))

        if light_type != self.UNITY_TYPE_DIRECTIONAL:
            log(f"    [Light] Skipping non-directional light (m_Type={light_type}) on '{go.name}'")
            return

        intensity  = float(comp_data.get('m_Intensity', 1.0))
        shadows_on = self._to_int(comp_data.get('m_Shadows', 0)) != 0

        go.component_data['directional_light'] = {
            'intensity':  intensity,
            'shadows_on': shadows_on,
        }
        log(f"    [Light] DirectionalLight → intensity={intensity}, shadows={shadows_on}")

    # -------------------------------------------------------------------------
    # EMIT
    # -------------------------------------------------------------------------

    def emit(self, go, entity: Dict, ctx: ProcessingContext) -> List[str]:
        light_data = go.component_data.get('directional_light')
        if not light_data:
            return []

        # Invert the light direction — Unity and O3DE directional lights face
        # opposite directions after coordinate conversion, so apply a 180° pitch flip.
        tc = entity['Components'].get('TransformComponent', {})
        td = tc.setdefault('Transform Data', {})
        rotate = list(td.get('Rotate', [0.0, 0.0, 0.0]))
        rotate[0] = ((rotate[0] + 180.0 + 180.0) % 360.0) - 180.0  # add 180°, normalize to [-180, 180]
        td['Rotate'] = rotate
        ctx.log(f"  [Light] Inverted pitch to {rotate[0]:.2f}° for directional light on '{go.name}'")

        entity['Components']['AZ::Render::EditorDirectionalLightComponent'] = {
            '$type': 'AZ::Render::EditorDirectionalLightComponent',
            'Id': ctx.generate_component_id(),
            'Controller': {
                'Configuration': {
                    'Intensity':       light_data['intensity'],
                    'CameraEntityId':  '',
                    'Shadow Enabled':  light_data['shadows_on'],
                }
            }
        }
        ctx.log(
            f"  [Light] ✓ EditorDirectionalLightComponent — "
            f"intensity={light_data['intensity']}, shadows={light_data['shadows_on']}"
        )
        ctx.stats["Directional lights"] = ctx.stats.get("Directional lights", 0) + 1
        return []
