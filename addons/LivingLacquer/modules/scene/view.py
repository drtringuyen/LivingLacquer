"""Viewport helpers for the scan: frame it after Build, and the "pivot at the world origin" toggle."""
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from . import human

PIVOT_KEYS = ("ll_prev_pivot", "ll_prev_cursor")


def scan_meshes():
    """The scan meshes under the Transform empty; files built before 0.2.2 (no Transform): the OBJ_ meshes."""
    rig = bpy.data.objects.get("Transform")
    meshes = [o for o in (rig.children if rig else []) if o.type == "MESH"]
    return meshes or [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("OBJ_")]


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


# -- pivot at the world origin: Pivot Point = 3D Cursor, cursor kept at (0, 0, 0) while the toggle is on

def apply(scene):
    """Called when the toggle changes: switch on (remember the user's pivot + cursor) or restore them."""
    ts, cur = scene.tool_settings, scene.cursor
    if scene.livinglacquer_props.pipe_pivot_origin:
        if "ll_prev_pivot" not in scene:
            scene["ll_prev_pivot"] = ts.transform_pivot_point
            scene["ll_prev_cursor"] = list(cur.location)
        _enforce(scene)
        if not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)
    else:
        if "ll_prev_pivot" in scene:
            ts.transform_pivot_point = scene["ll_prev_pivot"]
            cur.location = scene["ll_prev_cursor"]
        for k in PIVOT_KEYS:
            if k in scene:
                del scene[k]


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
