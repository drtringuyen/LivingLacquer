"""Build Blender cameras from Metashape cameras and look through them."""
import json
import os

import bpy
from mathutils import Matrix

from .parse import SENSOR_WIDTH_MM

CAMS_SHOWN = "ll_cams_shown"    # scene key: collections show_for_view turned on -> [exclude, hidden] before
SHIFT_LIMIT = 0.5               # lens shift past this (half the photo's long side) is no plausible lens
WIDTH_FIT = "ll_width_fit"      # camera key: lens and shift measured on the photo's width (0.4.5 on)


def get_collection(scene, name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        scene.collection.children.link(col)
    return col


def set_background(cd, bg_path, alpha, depth, relative=False):
    """Replace the camera's background with the photo at bg_path (none when it does not exist)."""
    cd.background_images.clear()
    if bg_path and os.path.exists(bg_path):
        cd.show_background_images = True
        bg = cd.background_images.new()
        bg.image = bpy.data.images.load(bg_path, check_existing=True)
        if relative and bpy.data.filepath:
            bg.image.filepath = bpy.path.relpath(bg_path)
        bg.frame_method = "FIT"
        bg.alpha = alpha
        bg.display_depth = depth


def lens_shift(cal, side=None):
    """(shift_x, shift_y) of a sensor: Metashape's principal point offset cx / cy in pixels over side
    (the photo's long side when None)."""
    big = side or max(cal["w"], cal["h"])
    return -cal.get("cx", 0.0) / big, cal.get("cy", 0.0) / big


def to_width_fit(ob):
    """A camera built before 0.4.5 has lens and shift measured on the photo's long side (Sensor Fit
    Vertical for a portrait photo; MultiCamProject may have switched it to Horizontal since, which
    leaves the frame 1.33x too big). Measure them on the width with Sensor Fit Horizontal, the way
    Build does now. True when it changed the camera."""
    res = ob.get("metashape_res") if ob.type == "CAMERA" else None
    if not res or ob.get(WIDTH_FIT):
        return False
    w, h = int(res[0]), int(res[1])
    k = max(w, h) / w
    cd = ob.data
    cd.sensor_fit = "HORIZONTAL"
    cd.lens *= k
    cd.shift_x *= k
    cd.shift_y *= k
    ob[WIDTH_FIT] = True
    return True


def odd_shift_warnings(sensors, cams):
    """One warning line per sensor used by cams whose lens shift is past SHIFT_LIMIT: most likely a
    calibration gone wrong in Metashape. Only a warning, the shift itself stays as solved
    (MultiCamProject projects the photos through it)."""
    count = {}
    for c in cams:
        count[c["sensor"]] = count.get(c["sensor"], 0) + 1
    out = []
    for sid, n in sorted(count.items(), key=lambda kv: str(kv[0])):
        cal = sensors[sid]
        sx, sy = lens_shift(cal)
        if max(abs(sx), abs(sy)) <= SHIFT_LIMIT:
            continue
        out.append(f"WARNING: sensor {sid} ({n} camera(s), {cal['w']}x{cal['h']}) has lens shift "
                   f"{sx:+.2f} / {sy:+.2f} (cx {cal.get('cx', 0.0):+.0f} px, cy {cal.get('cy', 0.0):+.0f} px): "
                   "check this sensor's calibration in Metashape (Tools > Camera Calibration); fix cx / cy if "
                   "they are wrong and realign. Do not zero the shift in Blender: the cameras would no longer "
                   "match their photos.")
    return out


def build_camera(cam, cal, bg_path, col, opts):
    """Create or update the camera named after the Metashape label, with its photo as background."""
    label = cam["label"]
    w, h = cal["w"], cal["h"]

    # always Horizontal on the photo's width, also for a portrait photo: MultiCamProject projects
    # through the width and switches any camera it looks through to Horizontal
    cd = bpy.data.cameras.get(label) or bpy.data.cameras.new(label)
    cd.sensor_fit = "HORIZONTAL"
    cd.sensor_width = SENSOR_WIDTH_MM
    cd.sensor_height = SENSOR_WIDTH_MM
    cd.lens = cal["f"] * SENSOR_WIDTH_MM / w
    cd.shift_x, cd.shift_y = lens_shift(cal, w)     # never zero it: MultiCamProject projects through it
    cd.clip_start = opts["clip_start"]
    cd.clip_end = opts["clip_end"]
    cd.display_size = opts["display_size"]

    set_background(cd, bg_path, opts["bg_alpha"], opts["bg_depth"], opts.get("relative", False))

    ob = bpy.data.objects.get(label)
    if ob is None or ob.type != "CAMERA":
        ob = bpy.data.objects.new(label, cd)
    else:
        ob.data = cd
    if ob.name not in col.objects:
        col.objects.link(ob)
    # Metashape camera: X right, Y down, Z forward  ->  Blender camera: X right, Y up, -Z forward
    ob.matrix_world = cam["matrix"] @ Matrix.Diagonal((1, -1, -1, 1))
    ob["metashape_res"] = [w, h]
    ob[WIDTH_FIT] = True
    ob["metashape_photo"] = (bpy.path.relpath(bg_path) if bg_path and opts.get("relative") else bg_path) or ""
    return ob


def _layer_of(view_layer, name):
    """The layer collection of the collection called name in this view layer, or None."""
    stack = [view_layer.layer_collection]
    while stack:
        lc = stack.pop()
        if lc.collection.name == name:
            return lc
        stack.extend(lc.children)
    return None


def show_for_view(context, ob):
    """A collection unticked (excluded) or hidden in the outliner takes its cameras out of the view
    layer: they cannot be selected and draw no photo. Turn ob's collections on while looking through
    it; watch_view turns them back off when no 3D view looks through a camera any more."""
    sc, vl = context.scene, context.view_layer
    shown = json.loads(sc.get(CAMS_SHOWN, "{}"))
    for col in ob.users_collection:
        lc = _layer_of(vl, col.name)
        if lc is None or not (lc.exclude or lc.hide_viewport):
            continue
        shown.setdefault(col.name, [lc.exclude, lc.hide_viewport])     # how the user had it (first time)
        lc.exclude = False
        lc.hide_viewport = False
    if shown:
        sc[CAMS_SHOWN] = json.dumps(shown)
        if not bpy.app.timers.is_registered(watch_view):
            bpy.app.timers.register(watch_view, first_interval=0.5, persistent=True)


def watch_view():
    """Timer: once no 3D view looks through a camera, put the collections show_for_view turned on back."""
    scene = bpy.context.scene
    if scene is None or CAMS_SHOWN not in scene:
        return None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D" and area.spaces.active.region_3d.view_perspective == "CAMERA":
                return 0.5
    for vl in scene.view_layers:
        for name, (exclude, hidden) in json.loads(scene[CAMS_SHOWN]).items():
            lc = _layer_of(vl, name)
            if lc is not None:
                lc.exclude = exclude
                lc.hide_viewport = hidden
    del scene[CAMS_SHOWN]
    return None


def set_view_camera(context, ob):
    """Make ob the scene camera, match its photo resolution and look through it."""
    sc = context.scene
    show_for_view(context, ob)
    sc.camera = ob
    res = ob.get("metashape_res")
    if res:
        sc.render.resolution_x, sc.render.resolution_y = int(res[0]), int(res[1])
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            space.camera = ob       # Local View keeps its own camera: it does not follow the scene's
            space.region_3d.view_perspective = "CAMERA"
