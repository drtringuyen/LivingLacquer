"""Viewport helpers for the scan: frame it after Build, and the "pivot at the world origin" toggle."""
import json

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from . import human

PIVOT_KEYS = ("ll_prev_pivot", "ll_prev_cursor", "ll_prev_active", "ll_prev_selected", "ll_prev_cams_hidden",
              "ll_solo_hidden")


def scan_meshes():
    """The scan meshes under the Transform empty; files built before 0.2.2 (no Transform): the ORG_ / OBJ_ meshes."""
    rig = bpy.data.objects.get("Transform")
    meshes = [o for o in (rig.children if rig else []) if o.type == "MESH"]
    return meshes or [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith(("ORG_", "OBJ_"))]


def frame_scan():
    """Center every 3D Viewport on the scan mesh and zoom so it fills about two thirds of the view
    (the camera ring around it is left outside on purpose). A camera view is switched to perspective."""
    meshes = scan_meshes()
    if not meshes:
        return False
    bpy.context.view_layer.update()
    lo, hi = human.world_box(meshes)
    center = Vector(((lo + hi) / 2).tolist())
    size = float(max(hi - lo))
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            r3d = area.spaces.active.region_3d
            if r3d.view_perspective == "CAMERA":
                r3d.view_perspective = "PERSP"
            r3d.view_location = center
            r3d.view_distance = size * 1.8
            area.tag_redraw()
    return True


# -- "work on the Transform" toggle: Pivot Point = 3D Cursor with the cursor kept at (0, 0, 0), the
#    Transform empty selected + active with its collection shown and the cameras hidden. Off puts the
#    pivot, cursor, camera visibility, selection and active object back and hides TRANSFORM again.

def _layer(view_layer, name):
    """The layer collection of the collection called name in this view layer, or None."""
    stack = [view_layer.layer_collection]
    while stack:
        lc = stack.pop()
        if lc.collection.name == name:
            return lc
        stack.extend(lc.children)
    return None


def apply(scene):
    """Called when the toggle changes."""
    from .build import CAMERAS, TRANSFORM, TRANSFORM_COLLECTION
    ts, cur = scene.tool_settings, scene.cursor
    vl = bpy.context.view_layer
    rig_lc, cam_lc = _layer(vl, TRANSFORM_COLLECTION), _layer(vl, CAMERAS)
    rig = bpy.data.objects.get(TRANSFORM)
    if scene.livinglacquer_props.pipe_pivot_origin:
        if "ll_prev_pivot" not in scene:            # remember what the user had (once)
            scene["ll_prev_pivot"] = ts.transform_pivot_point
            scene["ll_prev_cursor"] = list(cur.location)
            scene["ll_prev_active"] = vl.objects.active.name if vl.objects.active else ""
            scene["ll_prev_selected"] = json.dumps([o.name for o in vl.objects.selected])
            scene["ll_prev_cams_hidden"] = bool(cam_lc and cam_lc.hide_viewport)
        _enforce(scene)
        if rig_lc:
            rig_lc.exclude = False
            rig_lc.hide_viewport = False
        sync_cameras(scene)
        if rig is not None and vl.objects.get(rig.name):
            for o in vl.objects.selected:
                o.select_set(False)
            rig.hide_set(False)
            rig.select_set(True)
            vl.objects.active = rig
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)
    else:
        if "ll_prev_pivot" in scene:
            ts.transform_pivot_point = scene["ll_prev_pivot"]
            cur.location = scene["ll_prev_cursor"]
            if cam_lc:
                cam_lc.hide_viewport = bool(scene.get("ll_prev_cams_hidden", False))
            _unhide_solo(scene, vl)
            if rig is not None:
                rig.select_set(False)
            for name in json.loads(scene.get("ll_prev_selected", "[]")):
                o = vl.objects.get(name)
                if o is not None:
                    o.select_set(True)
            vl.objects.active = vl.objects.get(scene.get("ll_prev_active", "")) or None
        if rig_lc:
            rig_lc.hide_viewport = True
        for k in PIVOT_KEYS:
            if k in scene:
                del scene[k]


def looking_through(scene):
    """The scan camera a 3D view looks through (the scene camera, in CAMERAS), or None."""
    from .build import CAMERAS
    cam = scene.camera
    col = bpy.data.collections.get(CAMERAS)
    if cam is None or col is None or cam.name not in col.objects:
        return None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D" and area.spaces.active.region_3d.view_perspective == "CAMERA":
                return cam
    return None


def sync_cameras(scene):
    """While the toggle is on: the cameras are hidden, except the one a 3D view looks through - a hidden
    camera draws no photo, and the Transform is moved against that photo. Changes only what differs."""
    from .build import CAMERAS
    vl = bpy.context.view_layer
    cam_lc = _layer(vl, CAMERAS)
    if cam_lc is None:
        return
    cam = looking_through(scene)
    if cam is None:
        if not cam_lc.hide_viewport:
            cam_lc.hide_viewport = True
        _unhide_solo(scene, vl)                 # the collection hides them all again
        return
    if cam_lc.hide_viewport:
        cam_lc.hide_viewport = False
    old = scene.get("ll_solo_hidden", "[]")
    hidden = set(json.loads(old))
    for o in cam_lc.collection.objects:
        if o.type != "CAMERA" or vl.objects.get(o.name) is None:
            continue
        solo = o != cam
        if o.hide_get() != solo:
            o.hide_set(solo)
        if solo:
            hidden.add(o.name)
        else:
            hidden.discard(o.name)
    if json.dumps(sorted(hidden)) != old:
        scene["ll_solo_hidden"] = json.dumps(sorted(hidden))


def _unhide_solo(scene, vl):
    """Show the cameras sync_cameras hid one by one."""
    for name in json.loads(scene.get("ll_solo_hidden", "[]")):
        o = vl.objects.get(name)
        if o is not None and o.hide_get():
            o.hide_set(False)
    if "ll_solo_hidden" in scene:
        del scene["ll_solo_hidden"]


def _enforce(scene):
    ts, cur = scene.tool_settings, scene.cursor
    if ts.transform_pivot_point != "CURSOR":
        ts.transform_pivot_point = "CURSOR"
    if cur.location.length > 1e-9:
        cur.location = (0.0, 0.0, 0.0)


def _tick():
    """While the toggle is on: put the pivot / cursor back if something moved them."""
    scene = bpy.context.scene
    props = getattr(scene, "livinglacquer_props", None) if scene else None
    if props is None or not props.pipe_pivot_origin:
        return None
    _enforce(scene)
    sync_cameras(scene)                         # Numpad 0 / leaving the camera view while it is on
    return 0.5


@persistent
def _on_load(*_args):
    scene = bpy.context.scene
    props = getattr(scene, "livinglacquer_props", None)
    if props is not None and props.pipe_pivot_origin and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


def register():
    bpy.app.handlers.load_post.append(_on_load)
    # the context is restricted while add-ons register: let the timer look once the file is up
    bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
