import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty


def _apply_backgrounds(props):
    """Opacity / depth straight onto every camera of the cameras collection (no Apply button)."""
    col = bpy.data.collections.get(props.metashape_collection)
    for o in col.all_objects if col else []:
        if o.type == "CAMERA":
            for bg in o.data.background_images:
                bg.alpha = props.metashape_bg_alpha
                bg.display_depth = props.metashape_bg_depth


def _redraw_view3d(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _pivot_update(self, context):
    try:
        from .modules.scene import view
    except ImportError:
        return
    view.apply(context.scene)


def _guide_ontop(props):
    try:
        from .modules.engines import guide
    except ImportError:
        return
    guide.set_topmost(props.pipe_guide_ontop)


def _guide_update(context):
    try:
        from .modules.engines import guide
    except ImportError:
        return
    if bpy.data.texts.get(guide.TEXT):
        guide.write_text(context)


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
        default="0.4.2"
    )

    # metashape: collection the sidebar steps through, and the background photo look
    metashape_collection: StringProperty(
        name="Collection",
        description="Collection holding the imported Metashape cameras",
        default="Cameras_Metashape"
    )
    metashape_bg_alpha: FloatProperty(
        name="Opacity",
        description="Opacity of the cameras' background photos (all scan cameras at once)",
        default=0.6, min=0.0, max=1.0, update=lambda self, context: _apply_backgrounds(self)
    )
    metashape_bg_depth: EnumProperty(
        name="Depth",
        items=[("BACK", "Back", "Draw the photo behind the scene"),
               ("FRONT", "Front", "Draw the photo over the scene")],
        default="FRONT", update=lambda self, context: _apply_backgrounds(self)
    )

    # scan pipeline: engine for step 4 (also written to livinglacquer.json), panel toggles
    pipe_engine: EnumProperty(
        name="Engine",
        items=[("AGISOFT", "Agisoft", "Metashape Standard does everything, Blender prepares and collects"),
               ("HYBRID", "Hybrid", "Agisoft aligns the cameras, OpenMVS builds mesh and texture"),
               ("OPENSOURCE", "Open Source", "COLMAP + OpenMVS, fully automatic")],
        default="OPENSOURCE"
    )
    pipe_preset: EnumProperty(
        name="Quality", description="Engine quality (Open Source / Hybrid)",
        items=[("FAST", "Fast", "Quarter-resolution depth maps, no mesh refinement"),
               ("NORMAL", "Normal", "Half-resolution depth maps, refined mesh"),
               ("HIGH", "High", "Full-resolution depth maps and texture (slow)")],
        default="NORMAL"
    )
    pipe_show_guide: BoolProperty(name="How to work in Agisoft", default=False)
    pipe_guide_all: BoolProperty(
        name="Show All Steps", default=False, update=lambda self, context: _guide_update(context),
        description="Also list the Agisoft steps already done (marked [done]); off shows only what is left")
    pipe_guide_ontop: BoolProperty(
        name="Keep on Top", default=True, update=lambda self, context: _guide_ontop(self),
        description="Keep the Agisoft guide window above Metashape (Windows); off lets it go behind again")
    pipe_guide_paths: BoolProperty(
        name="Show Paths", default=False, update=lambda self, context: _guide_update(context),
        description="Write the full folder / file paths into the Agisoft guide text (the copy buttons work "
                    "either way)")
    pipe_mask_method: EnumProperty(
        name="Mask Method",
        items=[("AI", "AI cut-out", "Find the object with an AI model (U^2-Net, 176 MB download once); works on any "
                                    "background"),
               ("COLOR", "Colour key", "Ignore everything close to the background colour (no download); needs a "
                                       "plain background")],
        default="AI")
    pipe_colmap_masks: BoolProperty(
        name="Use masks: object only in the mesh", default=False,
        description="Leave the masked background (table, floor) out of the mesh. The photos still align on the "
                    "whole picture, so the background keeps helping to place the cameras")
    pipe_mask_grow: IntProperty(name="Grow Edge", default=12, min=0, max=80,
                                description="Widen the kept area by this many pixels, so the object's edge is never cut")
    pipe_mask_tolerance: FloatProperty(name="Colour Tolerance", default=0.12, min=0.02, max=0.5,
                                       description="How far from the background colour a pixel may be and still be "
                                                   "ignored (Colour key)")
    pipe_out_format: EnumProperty(
        name="Format", description="File format of converted and undistorted photos",
        items=[("JPG", "JPG", ""), ("PNG", "PNG", ""), ("TIF", "TIFF", "")],
        default="JPG"
    )
    pipe_quality: IntProperty(name="Quality", description="JPG quality", default=95, min=50, max=100)
    pipe_show_human: BoolProperty(
        name="Size References", default=True,
        description="Draw a 1.7 m person, a 0.75 m table and a 0.30 m cat on the floor next to the scan, to judge how much to scale it",
        update=lambda self, context: _redraw_view3d(context))
    pipe_pivot_origin: BoolProperty(
        name="Work on the Transform", default=False, update=_pivot_update,
        description="On: select the Transform empty, show TRANSFORM, hide the cameras, Pivot Point = 3D Cursor "
                    "held at the world origin (scale / rotate the scan about the center of the world). Off: hides "
                    "TRANSFORM, gives back the cameras, your pivot, cursor, selection and active object")
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
