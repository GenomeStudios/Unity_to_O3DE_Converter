"""
=============================================================================
DIRECTIONAL LIGHT COMPONENT PROCESSOR  (WEIGHT = 60)

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

    WEIGHT  = 60
    HANDLES = ['Light']
    EMITS   = ['AZ::Render::EditorDirectionalLightComponent']

    UNITY_TYPE_DIRECTIONAL = 1

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    def parse(self, comp_type: str, comp_data: Dict,
              go, log: Callable[[str], None]) -> None:

        light_type = int(comp_data.get('m_Type', -1))

        if light_type != self.UNITY_TYPE_DIRECTIONAL:
            log(f"    [Light] Skipping non-directional light (m_Type={light_type}) on '{go.name}'")
            return

        intensity      = float(comp_data.get('m_Intensity', 1.0))
        shadows_on     = int(comp_data.get('m_Shadows', 0)) != 0

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
        return []
