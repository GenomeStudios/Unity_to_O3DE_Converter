"""
=============================================================================
O3DE TEXTURE SETTINGS  (targets.o3de.texture_settings)
=============================================================================

Writes the ``<texture>.assetinfo`` sidecar that tells O3DE's image builder
how to process one texture.

Why a converted texture needs one
---------------------------------
Left alone, the image builder picks a preset from the file's name. A base
colour texture gets the plain albedo preset, which is made for colour and
does not keep the alpha channel as opacity. A material that takes its
opacity from that alpha (a plant's cutout leaves, a pane of glass) then
shows flat planes of distorted colour. Such a texture needs the preset that
keeps colour and opacity together, at its full resolution.

The file is the engine's own serialized ``TextureSettings`` (an XML object
stream), with the fields the Texture Settings dialog writes.
"""

from __future__ import annotations

from pathlib import Path

# The image builder preset for a colour texture whose alpha is its opacity.
OPACITY_PRESET = "Decal_AlbedoWithOpacity"

_TEMPLATE = """<ObjectStream version="3">
	<Class name="TextureSettings" version="2" type="{{980132FF-C450-425D-8AE0-BD96A8486177}}">
		<Class name="AZ::Uuid" field="PresetID" value="{{00000000-0000-0000-0000-000000000000}}" type="{{E152C105-A133-4D03-BBF8-3D4B2FBA3E2A}}"/>
		<Class name="Name" field="Preset" value="{preset}" type="{{3D2B920C-9EFD-40D5-AAE0-DF131C3D4931}}"/>
		<Class name="unsigned int" field="SizeReduceLevel" value="0" type="{{43DA906B-7DEF-4CA8-9790-854106D3F983}}"/>
		<Class name="bool" field="EngineReduce" value="true" type="{{A0CA880C-AFE4-43CB-926C-59AC48496112}}"/>
		<Class name="bool" field="EnableMipmap" value="true" type="{{A0CA880C-AFE4-43CB-926C-59AC48496112}}"/>
		<Class name="unsigned int" field="MipMapGenEval" value="0" type="{{43DA906B-7DEF-4CA8-9790-854106D3F983}}"/>
		<Class name="ImageProcessingAtom::MipGenType" field="MipMapGenType" value="1" type="{{8524F650-1417-44DA-BBB0-C707A7A1A709}}"/>
		<Class name="bool" field="MaintainAlphaCoverage" value="{coverage}" type="{{A0CA880C-AFE4-43CB-926C-59AC48496112}}"/>
		<Class name="AZStd::vector&lt;unsigned int, allocator&gt;" field="MipMapAlphaAdjustments" type="{{3349AACD-BE04-50BC-9478-528BF2ACFD55}}">
{adjustments}
		</Class>
		<Class name="AZStd::map&lt;AZStd::basic_string&lt;char, AZStd::char_traits&lt;char&gt;, allocator&gt;, DataPatch, AZStd::less&lt;AZStd::basic_string&lt;char, AZStd::char_traits&lt;char&gt;, allocator&gt;&gt;, allocator&gt;" field="PlatformSpecificOverrides" type="{{74E4843B-0924-583D-8C6E-A37B09BD51FE}}"/>
		<Class name="AZStd::string" field="OverridingPlatform" value="" type="{{03AAAB3F-5C47-5A66-9EBC-D5FA4DB353C9}}"/>
		<Class name="AZStd::set&lt;AZStd::basic_string&lt;char, AZStd::char_traits&lt;char&gt;, allocator&gt;, AZStd::less&lt;AZStd::basic_string&lt;char, AZStd::char_traits&lt;char&gt;, allocator&gt;&gt;, allocator&gt;" field="Tags" type="{{166F208E-DE97-53FE-B349-BDD9FE9B8693}}"/>
	</Class>
</ObjectStream>
"""

_ADJUSTMENT = ('			<Class name="unsigned int" field="element" value="50" '
               'type="{43DA906B-7DEF-4CA8-9790-854106D3F983}"/>')


# =============================================================================
# WRITING
# =============================================================================

def write_opacity_texture_settings(texture_path: Path, cutout: bool) -> Path:
    """Write the settings for a colour texture whose alpha channel is the
    material's opacity, beside the texture, and return the sidecar's path.

    The texture is processed with ``OPACITY_PRESET`` at its full resolution
    ("EngineReduce" is the dialog's "suppress reduction"). For a ``cutout``
    material the mip levels keep the share of the texture that passes the
    cut, so leaves do not thin out with distance; a blended one has no cut
    to keep.

    An existing sidecar is replaced: the conversion owns its output."""
    sidecar = Path(str(texture_path) + ".assetinfo")
    sidecar.write_text(_TEMPLATE.format(
        preset=OPACITY_PRESET,
        coverage="true" if cutout else "false",
        adjustments="\n".join([_ADJUSTMENT] * 6),
    ), encoding="utf-8")
    return sidecar
