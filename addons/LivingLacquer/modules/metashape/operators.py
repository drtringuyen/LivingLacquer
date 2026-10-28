import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .cameras import (CAMS_SHOWN, build_camera, get_collection, odd_shift_warnings, set_view_camera,
                      show_for_view, to_width_fit, watch_view)
from .parse import parse_metashape_xml
from .photos import guess_image_dir, index_images, read_image_size, size_matches, undistort_image


def _working_on_transform(context):
    return getattr(context.scene.livinglacquer_props, "pipe_pivot_origin", False)


def _look_through(context, ob):
    """Look through ob. With "Work on the Transform" on it stays on (the Transform stays selected for
    G / R / S): the other cameras are hidden, ob is shown, since a hidden camera draws no photo."""
    set_view_camera(context, ob)
    if _working_on_transform(context):
        from ..scene.view import sync_cameras
        sync_cameras(context.scene)


class LIVINGLACQUER_OT_MetashapeImport(bpy.types.Operator, ImportHelper):
    """Import Agisoft Metashape XML cameras with undistorted background photos"""
    bl_idname = "livinglacquer.metashape_import"
    bl_label = "Import Metashape Cameras"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".xml"
    filter_glob: StringProperty(default="*.xml", options={"HIDDEN"})

    image_dir: StringProperty(name="Photo Folder", subtype="DIR_PATH",
                              description="Folder with the original photos (empty = auto-detect next to the XML)")
    output_dir: StringProperty(name="Undistorted Folder", subtype="DIR_PATH",
                               description="Where undistorted photos go (empty = '<photo folder>_undistorted')")
    undistort: BoolProperty(name="Undistort Photos", default=True)
    overwrite: BoolProperty(name="Overwrite Existing", default=False,
                            description="Re-undistort photos that already exist in the output folder")
    out_format: EnumProperty(name="Format", items=[("JPG", "JPEG", ""), ("PNG", "PNG", ""), ("TIF", "TIFF", "")],
                             default="JPG")
    quality: IntProperty(name="JPEG Quality", default=95, min=50, max=100)
    collection_name: StringProperty(name="Collection", default="Cameras_Metashape")
    skip_odd_size: BoolProperty(name="Skip Mismatched Photos", default=True,
                                description="Skip cameras whose photo does not fit their own sensor "
                                            "(each lens is checked separately, so mixed lenses are kept)")
    set_resolution: BoolProperty(name="Set Render Resolution", default=True)
    bg_alpha: FloatProperty(name="Background Opacity", default=0.6, min=0, max=1)
    bg_depth: EnumProperty(name="Background Depth", items=[("BACK", "Back", ""), ("FRONT", "Front", "")],
                           default="FRONT")
    display_size: FloatProperty(name="Camera Display Size", default=0.2, min=0.001)
    clip_start: FloatProperty(name="Clip Start", default=0.01, min=0.0001)
    clip_end: FloatProperty(name="Clip End", default=1000.0)
    limit: IntProperty(name="Limit", default=0, min=0, description="Only import this many cameras (0 = all)")
    run_modal: BoolProperty(name="Run in Background", default=True, options={"HIDDEN"},
                            description="Process one camera per tick with a progress bar (Esc cancels)")

    _timer = None

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "image_dir")
        lay.prop(self, "output_dir")
        box = lay.box()
        box.prop(self, "undistort")
        if self.undistort:
            box.prop(self, "overwrite")
            row = box.row()
            row.prop(self, "out_format", text="")
            if self.out_format == "JPG":
                row.prop(self, "quality")
        lay.prop(self, "collection_name")
        lay.prop(self, "skip_odd_size")
        lay.prop(self, "set_resolution")
        lay.prop(self, "bg_alpha")
        lay.prop(self, "bg_depth")
        lay.prop(self, "display_size")
        row = lay.row(align=True)
        row.prop(self, "clip_start")
        row.prop(self, "clip_end")
        lay.prop(self, "limit")

    # -- setup shared by modal and blocking runs
    def _prepare(self, context):
        xml_path = bpy.path.abspath(self.filepath)
        self.sensors, cams = parse_metashape_xml(xml_path)
        self.cams = cams
        labels = [c["label"] for c in cams]
        img_dir = bpy.path.abspath(self.image_dir) if self.image_dir else guess_image_dir(xml_path, labels)
        self.images = index_images(img_dir)
        if self.output_dir:
            out_dir = bpy.path.abspath(self.output_dir)
        elif os.path.basename(os.path.dirname(xml_path)) == "01.CAM_Photos":
            out_dir = os.path.dirname(xml_path)     # scan folder: undistorted photos sit next to the XML
        else:
            out_dir = img_dir.rstrip("\\/") + "_undistorted"
        self.out_dir = out_dir

        sizes = {}
        for c in cams:
            cal = self.sensors[c["sensor"]]
            key = (cal["w"], cal["h"])
            sizes[key] = sizes.get(key, 0) + 1
        self.main_size = max(sizes, key=sizes.get) if sizes else None

        self.queue, self.skipped = [], []
        for c in cams:
            cal = self.sensors[c["sensor"]]
            if c["label"] not in self.images:
                self.skipped.append(c["label"] + " (photo not found)")
            elif self.skip_odd_size and not size_matches(read_image_size(self.images[c["label"]]), cal):
                self.skipped.append(c["label"] + " (photo size does not fit its sensor)")
            else:
                self.queue.append(c)
        if self.limit:
            self.queue = self.queue[:self.limit]
        self.total = len(self.queue)
        self.done = []
        self.col = get_collection(context.scene, self.collection_name)
        self.opts = {"bg_alpha": self.bg_alpha, "bg_depth": self.bg_depth, "display_size": self.display_size,
                     "clip_start": self.clip_start, "clip_end": self.clip_end}
        if self.undistort and self.queue:
            os.makedirs(out_dir, exist_ok=True)
        if self.set_resolution and self.main_size:
            context.scene.render.resolution_x, context.scene.render.resolution_y = self.main_size
        # the sidebar steps through this collection from now on
        context.scene.livinglacquer_props.metashape_collection = self.col.name
        return img_dir

    def _step(self):
        cam = self.queue.pop(0)
        cal = self.sensors[cam["sensor"]]
        src = self.images[cam["label"]]
        if self.undistort:
            ext = {"JPG": ".jpg", "PNG": ".png", "TIF": ".tif"}[self.out_format]
            bg = os.path.join(self.out_dir, cam["label"] + ext)
            if self.overwrite or not os.path.exists(bg):
                undistort_image(src, bg, cal, self.quality)
        else:
            bg = src
        build_camera(cam, cal, bg, self.col, self.opts)
        self.done.append(cam["label"])

    def _finish(self, context):
        msg = f"Metashape: imported {len(self.done)} cameras into '{self.collection_name}'"
        if self.skipped:
            msg += f", skipped {len(self.skipped)}: " + ", ".join(self.skipped[:5])
        self.report({"INFO"}, msg)
        built = set(self.done)
        for line in odd_shift_warnings(self.sensors, [c for c in self.cams if c["label"] in built]):
            print("LivingLacquer Metashape import:", line)
            self.report({"WARNING"}, line)
        if self.done:
            ob = bpy.data.objects.get(self.done[0])
            if ob:
                set_view_camera(context, ob)

    def execute(self, context):
        try:
            self._prepare(context)
        except Exception as e:
            self.report({"ERROR"}, f"Could not read Metashape XML: {e}")
            return {"CANCELLED"}
        if not self.queue:
            self.report({"WARNING"}, "No cameras to import (check the photo folder)")
            return {"CANCELLED"}

        if self.run_modal and context.window:
            wm = context.window_manager
            self._timer = wm.event_timer_add(0.01, window=context.window)
            wm.progress_begin(0, self.total)
            wm.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        while self.queue:
            self._step()
        self._finish(context)
        return {"FINISHED"}

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == "ESC":
            self.queue.clear()
        if event.type != "TIMER" and event.type != "ESC":
            return {"PASS_THROUGH"}
        if self.queue:
            self._step()
            n = len(self.done)
            wm.progress_update(n)
            if context.area:
                context.area.header_text_set(f"Metashape cameras: {n}/{self.total}  (Esc to stop)")
            return {"RUNNING_MODAL"}
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        if context.area:
            context.area.header_text_set(None)
        self._finish(context)
        return {"FINISHED"}


def _camera(context):
    """The active camera; while working on the Transform (it is the active one) the scene camera."""
    ob = context.active_object
    if ob is not None and ob.type == "CAMERA":
        return ob
    cam = context.scene.camera
    return cam if _working_on_transform(context) and cam is not None and cam.type == "CAMERA" else None


class LIVINGLACQUER_OT_MetashapeLookThrough(bpy.types.Operator):
    """Make the active camera the scene camera, match its photo resolution and look through it"""
    bl_idname = "livinglacquer.metashape_look_through"
    bl_label = "Look Through Camera"

    @classmethod
    def poll(cls, context):
        return _camera(context) is not None

    def execute(self, context):
        _look_through(context, _camera(context))
        return {"FINISHED"}


class LIVINGLACQUER_OT_MetashapeStepCamera(bpy.types.Operator):
    """Look through the next / previous camera in the collection"""
    bl_idname = "livinglacquer.metashape_step_camera"
    bl_label = "Step Camera"
    direction: IntProperty(default=1)

    def execute(self, context):
        sc = context.scene
        col = bpy.data.collections.get(sc.livinglacquer_props.metashape_collection)
        cams = sorted([o for o in col.objects if o.type == "CAMERA"], key=lambda o: o.name) if col else []
        if not cams:
            self.report({"WARNING"}, "No cameras in the collection")
            return {"CANCELLED"}
        i = cams.index(sc.camera) if sc.camera in cams else -1
        ob = cams[(i + self.direction) % len(cams)]
        if not _working_on_transform(context):      # else the Transform stays selected for G / R / S
            show_for_view(context, ob)             # an unticked CAMERAS: ob is not selectable before this
            for o in context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
        _look_through(context, ob)
        return {"FINISHED"}


class LIVINGLACQUER_OT_MetashapeBgSettings(bpy.types.Operator):
    """Apply opacity / depth to the background photo of every camera in the collection"""
    bl_idname = "livinglacquer.metashape_bg_settings"
    bl_label = "Apply to All Cameras"

    def execute(self, context):
        props = context.scene.livinglacquer_props
        col = bpy.data.collections.get(props.metashape_collection)
        if not col:
            return {"CANCELLED"}
        for o in col.objects:
            if o.type == "CAMERA":
                for bg in o.data.background_images:
                    bg.alpha = props.metashape_bg_alpha
                    bg.display_depth = props.metashape_bg_depth
        return {"FINISHED"}


def menu_import(self, context):
    self.layout.operator(LIVINGLACQUER_OT_MetashapeImport.bl_idname, text="Agisoft Metashape Cameras (.xml)")


classes = (
    LIVINGLACQUER_OT_MetashapeImport,
    LIVINGLACQUER_OT_MetashapeLookThrough,
    LIVINGLACQUER_OT_MetashapeStepCamera,
    LIVINGLACQUER_OT_MetashapeBgSettings,
)


def width_fit_all():
    """Every camera built before 0.4.5 measured on the photo's width (to_width_fit). Returns how many."""
    return sum(to_width_fit(ob) for ob in bpy.data.objects
               if ob.type == "CAMERA" and not ob.library and not ob.data.library)


def _width_fit_timer():
    n = width_fit_all()
    if n:
        print(f"[LivingLacquer] {n} camera(s) now measured on the photo width (Sensor Fit Horizontal)")
    return None


@persistent
def _on_load(*_args):
    """Saved while looking through a camera: keep watching, so the collections still go back off.
    Cameras built before 0.4.5 get Sensor Fit Horizontal on the photo's width."""
    _width_fit_timer()
    scene = bpy.context.scene
    if scene is not None and CAMS_SHOWN in scene and not bpy.app.timers.is_registered(watch_view):
        bpy.app.timers.register(watch_view, first_interval=0.5, persistent=True)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_width_fit_timer, first_interval=0.2)     # the file open while installing


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(watch_view):
        bpy.app.timers.unregister(watch_view)
    if bpy.app.timers.is_registered(_width_fit_timer):
        bpy.app.timers.unregister(_width_fit_timer)
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
