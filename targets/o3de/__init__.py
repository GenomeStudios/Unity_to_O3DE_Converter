"""
=============================================================================
O3DE OUTPUT TARGET
=============================================================================

The converter's reference output target. All code that knows about O3DE's
file formats (.prefab JSON, .material JSON, .assetinfo sidecars,
``@gemroot:`` paths, etc.) lives here.

Current submodules:
    prefab_writer.py       ← O3DE prefab JSON builders + coordinate swap
    assetinfo_writer.py    ← `.assetinfo` writer + Y-up correction

Future submodules (slot in when a second target engine is added):
    material_writer.py     ← `.material` emission helpers (currently
                              inline inside ``IntegratedAssetProcessor``)
    materialtype_resolver.py ← `resolve_materialtype_path` (currently
                                in ``project_manager.py``)
"""
