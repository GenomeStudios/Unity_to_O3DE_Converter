"""
=============================================================================
TOOLS  (standalone helper scripts)
=============================================================================

Scripts in this directory run **outside** the main converter pipeline.
They're invoked manually or via subprocess for one-off tasks. They
are NOT imported by `main_app.py` / `integrated_asset_processor.py`.

Contents:
    bake_fbx_transforms.py    — Blender headless companion. Bakes FBX
                                 node transforms into mesh vertex data
                                 so Unity-style centered imports work
                                 in O3DE. Invoke via:
                                   blender --background --python
                                     tools/bake_fbx_transforms.py
                                     -- <input.fbx> <output.fbx>
"""
