"""
Blender headless script — bakes all node transforms into mesh vertex data.

This replicates Unity's FBX import behavior: meshes end up centered on their
object origin so that O3DE entities display them at the correct position.

Usage (called automatically by the asset processor):
    blender --background --python bake_fbx_transforms.py -- <input.fbx> <output.fbx>
"""

import bpy
import sys


def bake_transforms(input_path: str, output_path: str) -> None:
    """Import FBX, apply all transforms, re-export."""

    # Clear default scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Import FBX
    bpy.ops.import_scene.fbx(filepath=input_path)

    # Select every mesh object and apply transforms
    bpy.ops.object.select_all(action='SELECT')
    for obj in bpy.context.selected_objects:
        bpy.context.view_layer.objects.active = obj

    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Move all objects to world origin
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            obj.location = (0, 0, 0)

    # Export the baked FBX
    bpy.ops.export_scene.fbx(
        filepath=output_path,
        use_selection=False,
        apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_ALL',
        bake_space_transform=True,
        axis_forward='-Z',
        axis_up='Y',
    )


# ===================================================================
#  Entry point — parse args after the "--" separator
# ===================================================================

if __name__ == "__main__":
    argv = sys.argv
    separator = argv.index("--") if "--" in argv else -1

    if separator == -1 or len(argv) < separator + 3:
        print("Usage: blender --background --python bake_fbx_transforms.py "
              "-- <input.fbx> <output.fbx>")
        sys.exit(1)

    input_fbx = argv[separator + 1]
    output_fbx = argv[separator + 2]

    print(f"[FBX Bake] Input:  {input_fbx}")
    print(f"[FBX Bake] Output: {output_fbx}")

    bake_transforms(input_fbx, output_fbx)

    print("[FBX Bake] Done.")
