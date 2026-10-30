"""Step 5's settings, on the scene (scene.livinglacquer_rebuild)."""
import bpy
from bpy.props import (BoolProperty, BoolVectorProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, IntVectorProperty,
                       PointerProperty, StringProperty)

RESOLUTIONS = (("1024", "1K", "1024 x 1024"), ("2048", "2K", "2048 x 2048"), ("4096", "4K", "4096 x 4096"),
               ("8192", "8K", "8192 x 8192"))


def _ratio_update(self, context):
    ob = self.target
    mod = ob.modifiers.get("Decimate") if ob else None
    if mod is not None:
        mod.ratio = self.decimate_ratio


def _retopo_update(self, context):
    from . import core
    if self.retopo_object is not None:
        core.setup_target(self.retopo_object, self)


def _shading_update(self, context):
    from . import core
    if self.target is not None:
        core.set_shading(self.target, self.shading)


def _focus_update(self, context):
    from . import paint
    paint.lock_views(self.focus == "LOCK")


def _soft_update(self, context):
    from . import paint
    paint.update_brush(self)


def _mode_update(kind):
    def update(self, context):
        from . import bake
        bake.apply_mode(self, kind)
    return update


class LIVINGLACQUER_PG_RebuildName(bpy.types.PropertyGroup):
    """One camera of a photo list (the name is the camera's)."""


class LIVINGLACQUER_PG_Rebuild(bpy.types.PropertyGroup):
    mode: EnumProperty(
        name="Mode",
        items=[("REMESH", "Remesh", "Copy the scanned mesh as it is, with a Decimate modifier"),
               ("RETOPO", "Retopo", "Your own mesh: a new empty object or one you pick")],
        default="REMESH")
    decimate_ratio: FloatProperty(name="Ratio", default=0.1, min=0.0001, max=1.0, update=_ratio_update,
                                  description="Decimate ratio of the remeshed copy")
    retopo_source: EnumProperty(
        name="Retopo From",
        items=[("NEW", "New Object", "Start an empty mesh object on the scan"),
               ("OBJECT", "From Object", "Use a mesh you made")],
        default="NEW")
    retopo_object: PointerProperty(type=bpy.types.Object, name="Retopo Object", update=_retopo_update,
                                   poll=lambda self, ob: ob.type == "MESH",
                                   description="The mesh that gets the LL_ / MAT_ materials and uv_normal")
    target: PointerProperty(type=bpy.types.Object, name="Rebuilt Object",
                            description="The object step 5 works on (the remeshed copy or the retopo object)")
    shading: EnumProperty(
        name="Shading",
        items=[("PAINT", "Paint", "LL_<name>: BAo_ with BAp_ over it (BAp_'s alpha)"),
               ("FINAL", "Final", "MAT_<name>: ALB_ and NOR_")],
        default="PAINT", update=_shading_update)

    # textures: size, where they are made / loaded, the scan bake's reach
    resolution: EnumProperty(name="Resolution", items=RESOLUTIONS, default="4096",
                             description="Size of BAo_ / BAp_ / ALB_ / NOR_ (BAp_ always matches BAo_)")
    cage: FloatProperty(name="Cage", default=0.01, min=0.0, soft_max=0.2, subtype="DISTANCE", precision=3,
                        description="How far out from the rebuilt surface the scan is looked for (bake from "
                                    "the scan)")
    bake_dir: StringProperty(name="Bake Folder", default="//01.Bake/", subtype="DIR_PATH", options={"PATH_SUPPORTS_BLEND_RELATIVE"},
                             description="Where BAo_ / BAp_ / ALB_ / NOR_ are made")
    override_dir: StringProperty(name="Overrides", default="//02.Overrides/", subtype="DIR_PATH", options={"PATH_SUPPORTS_BLEND_RELATIVE"},
                                 description="Finished ALB_ / NOR_ files you made yourself (Load uses them)")
    export_dir: StringProperty(name="Export Folder", default="//Export/", subtype="DIR_PATH", options={"PATH_SUPPORTS_BLEND_RELATIVE"},
                               description="Where Lock & Export writes the FBX and its textures")
    alb_mode: EnumProperty(
        name="ALB_", items=[("BAKE", "Bake", "ALB_ is baked from BAo_ + BAp_ into the bake folder"),
                            ("LOAD", "Load", "ALB_ is your finished file in the Overrides folder")],
        default="BAKE", update=_mode_update("ALB"))
    nor_mode: EnumProperty(
        name="NOR_", items=[("BAKE", "Bake", "NOR_ is baked from the scan into the bake folder"),
                            ("LOAD", "Load", "NOR_ is your finished file in the Overrides folder")],
        default="BAKE", update=_mode_update("NOR"))
    nor_source: EnumProperty(
        name="NOR_ From",
        items=[("HIGHPASS", "High-pass", "Generated from ALB_'s brightness: fine painted relief, no scan noise"),
               ("SCAN", "Scan", "Baked from the scan's surface")],
        default="HIGHPASS")
    nor_strength: FloatProperty(name="Strength", default=2.0, min=0.0, soft_max=20.0,
                                description="Height of the relief read from ALB_")
    nor_radius: IntProperty(name="Radius", default=24, min=1, soft_max=256, subtype="PIXEL",
                            description="High-pass radius in pixels at 8K (scaled with the resolution): details "
                                        "smaller than this become relief, larger shading is ignored")
    nor_invert: BoolProperty(name="Invert", default=False, description="Dark = raised instead of dark = recessed")
    tri_budget: IntProperty(name="Budget", default=100000, min=1, soft_max=2000000,
                            description="Triangles for all the EXPORT collection's meshes, split by surface area")
    show_folders: BoolProperty(name="Folders", default=False)

    # 5b: the photos and the paint tools
    photo: StringProperty(name="Photo", description="The camera whose photo is painted from")
    favorites: CollectionProperty(type=LIVINGLACQUER_PG_RebuildName)
    edit_mesh: EnumProperty(
        name="Mesh", items=[("ORG", "ORG_", "Work on the original scan"),
                            ("FINAL", "OBJ_", "Work on the final mesh (the remeshed copy or the retopo)")],
        default="ORG", description="The mesh Poly Cut works on")
    base_segments: IntProperty(name="Segments", default=32, min=3, soft_max=256,
                               description="How many vertices the circle of From Base has")
    panel_open: BoolVectorProperty(name="Photo Panel Sections", size=5, default=(False,) * 5,
                                   description="Which of the photo panel's sections are open")
    panel_rect: IntVectorProperty(name="Photo Panel Rectangle", size=4, default=(0, 0, 0, 0),
                                  description="Left, top, width and height of the photo panel (0 width: not set)")
    show_photos: BoolProperty(name="Photo Panel", default=False,
                              description="The floating panel in the 3D viewport with Favorites, All Photos and "
                                          "the paint tools (Shift+Q)")
    focus: EnumProperty(
        name="View",
        items=[("FOCUS", "Focus", "Loading a photo looks through its camera", "VIEW_CAMERA", 0),
               ("LOCK", "Lock", "Loading a photo looks through its camera, no rotation", "LOCKED", 1),
               ("FREE", "Free", "Loading a photo keeps the view (the photo only lines up through its "
                                "camera)", "HIDE_OFF", 2)],
        default="FOCUS", update=_focus_update)
    soft: BoolProperty(name="Soft", default=True, update=_soft_update,
                       description="Soft edge for the brush and for Fill / Erase")


classes = (LIVINGLACQUER_PG_RebuildName, LIVINGLACQUER_PG_Rebuild)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.livinglacquer_rebuild = PointerProperty(type=LIVINGLACQUER_PG_Rebuild)


def unregister():
    del bpy.types.Scene.livinglacquer_rebuild
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
