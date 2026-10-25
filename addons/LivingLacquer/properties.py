import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty


def _redraw_view3d(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


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
        default="0.2.3"
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

    # scan pipeline: engine for step 4 (also written to livinglacquer.json), panel toggles
    pipe_engine: EnumProperty(
        name="Engine",
        items=[("AGISOFT", "Agisoft", "Metashape Standard does everything, Blender prepares and collects"),
               ("HYBRID", "Hybrid", "Agisoft aligns the cameras, OpenMVS builds mesh and texture"),
               ("OPENSOURCE", "Open Source", "COLMAP + OpenMVS, fully automatic")],
        default="AGISOFT"
    )
    pipe_preset: EnumProperty(
        name="Quality", description="Engine quality (Open Source / Hybrid)",
        items=[("FAST", "Fast", "Quarter-resolution depth maps, no mesh refinement"),
               ("NORMAL", "Normal", "Half-resolution depth maps, refined mesh"),
               ("HIGH", "High", "Full-resolution depth maps and texture (slow)")],
        default="NORMAL"
    )
    pipe_show_guide: BoolProperty(name="How to work in Agisoft", default=False)
    pipe_out_format: EnumProperty(
        name="Format", description="File format of converted and undistorted photos",
        items=[("JPG", "JPG", ""), ("PNG", "PNG", ""), ("TIF", "TIFF", "")],
        default="JPG"
    )
    pipe_quality: IntProperty(name="Quality", description="JPG quality", default=95, min=50, max=100)
    pipe_overwrite: BoolProperty(name="Overwrite", default=False,
                                 description="Undistort again even when the photo already exists")
    pipe_show_human: BoolProperty(
        name="1.7 m Person", default=True,
        description="Draw a 1.7 m person next to the scan in the 3D Viewport, to judge how much to scale it",
        update=lambda self, context: _redraw_view3d(context))
    pipe_show_gear: BoolProperty(name="Advanced", description="Show the advanced options", default=False)
    pipe_show_report: BoolProperty(name="Details", description="Show every line of the Check Links report",
                                   default=False)


def register():
    bpy.utils.register_class(LIVINGLACQUERProperties)
    bpy.types.Scene.livinglacquer_props = bpy.props.PointerProperty(
        type=LIVINGLACQUERProperties
    )


def unregister():
    del bpy.types.Scene.livinglacquer_props
    bpy.utils.unregister_class(LIVINGLACQUERProperties)
