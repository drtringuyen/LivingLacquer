"""Build Blender cameras from Metashape cameras and look through them."""
import os

import bpy
from mathutils import Matrix

from .parse import SENSOR_WIDTH_MM


def get_collection(scene, name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        scene.collection.children.link(col)
    return col


def build_camera(cam, cal, bg_path, col, opts):
    """Create or update the camera named after the Metashape label, with its photo as background."""
    label = cam["label"]
    w, h = cal["w"], cal["h"]
    big = max(w, h)

    cd = bpy.data.cameras.get(label) or bpy.data.cameras.new(label)
    cd.sensor_fit = "HORIZONTAL" if w >= h else "VERTICAL"
    cd.sensor_width = SENSOR_WIDTH_MM
    cd.sensor_height = SENSOR_WIDTH_MM
    cd.lens = cal["f"] * SENSOR_WIDTH_MM / big
    cd.shift_x = -cal.get("cx", 0.0) / big
    cd.shift_y = cal.get("cy", 0.0) / big
    cd.clip_start = opts["clip_start"]
    cd.clip_end = opts["clip_end"]
    cd.display_size = opts["display_size"]

    cd.background_images.clear()
    if bg_path and os.path.exists(bg_path):
        cd.show_background_images = True
        bg = cd.background_images.new()
        bg.image = bpy.data.images.load(bg_path, check_existing=True)
        bg.frame_method = "FIT"
        bg.alpha = opts["bg_alpha"]
        bg.display_depth = opts["bg_depth"]

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
    ob["metashape_photo"] = bg_path or ""
    return ob


def set_view_camera(context, ob):
    """Make ob the scene camera, match its photo resolution and look through it."""
    sc = context.scene
    sc.camera = ob
    res = ob.get("metashape_res")
    if res:
        sc.render.resolution_x, sc.render.resolution_y = int(res[0]), int(res[1])
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            area.spaces.active.region_3d.view_perspective = "CAMERA"
