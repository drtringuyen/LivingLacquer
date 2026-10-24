import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty


class LIVINGLACQUERProperties(bpy.types.PropertyGroup):
    """Global properties shared across all modules"""

    debug_mode: BoolProperty(
        name="Debug Mode",
        description="Show extra-info-label and debug information",
        default=False
    )

    last_build_time: StringProperty(
        name="Last Build Time",
        description="Timestamp of last install.py run",
        default="Never"
    )

    addon_version: StringProperty(
        name="Version",
        description="Current addon version",
        default="0.0.1"
    )

    # metashape: collection the sidebar steps through, and the background photo look
    metashape_collection: StringProperty(
        name="Collection",
        description="Collection holding the imported Metashape cameras",
        default="Cameras_Metashape"
    )
    metashape_bg_alpha: FloatProperty(
        name="Opacity",
        description="Opacity of the background photo",
        default=0.6, min=0.0, max=1.0
    )
    metashape_bg_depth: EnumProperty(
        name="Depth",
        items=[("BACK", "Back", "Draw the photo behind the scene"),
               ("FRONT", "Front", "Draw the photo over the scene")],
        default="FRONT"
    )


def register():
    bpy.utils.register_class(LIVINGLACQUERProperties)
    bpy.types.Scene.livinglacquer_props = bpy.props.PointerProperty(
        type=LIVINGLACQUERProperties
    )


def unregister():
    del bpy.types.Scene.livinglacquer_props
    bpy.utils.unregister_class(LIVINGLACQUERProperties)
