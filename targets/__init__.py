"""
=============================================================================
OUTPUT-TARGET PLUGIN PACKAGE
=============================================================================

Output-target plugins live in subpackages of this directory. The
converter ships with the O3DE target as a reference. A future iteration
could add additional target engines without rewriting the source-side
plugins.

Layout:
    targets/
        __init__.py            ← this file
        o3de/                  ← reference O3DE target
            __init__.py
            material_writer.py
            prefab_writer.py
            assetinfo_writer.py
            materialtype_resolver.py

For now there is only one target. The scaffolding exists so a
multi-target refactor (separate from the source-platform refactor)
slots in cleanly later.
"""
