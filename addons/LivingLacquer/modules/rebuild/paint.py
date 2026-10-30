"""5b Brush: Blender's own Texture Paint, painting the photo into BAp_. The brush ("LL Photo", a local
brush asset) carries the photo as a Stencil texture, and a timer keeps the stencil on the camera's frame
in every 3D view that looks through the camera, so a stroke copies the photo where it lies on the mesh.
Occlude, backface culling and normal falloff are on: only what the view sees gets paint.

Solo shows only the rebuilt object (the cameras stay, they draw their photos); Lock stops the views
from rotating out of the camera."""
import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import bake, core

BRUSH = "LL Photo"
TEXTURE = "LL Photo"
SOLO_KEY = "ll_rebuild_solo"        # scene key: the objects Solo hid
INTERVAL = 0.1


def _brush():
    b = bpy.data.brushes.get(BRUSH)
    if b is None:
        b = bpy.data.brushes.new(BRUSH, mode="TEXTURE_PAINT")
    if b.asset_data is None:
        b.asset_mark()
    return b


def _texture(photo):
    tex = bpy.data.textures.get(TEXTURE)
    if tex is None or tex.type != "IMAGE":
        tex = bpy.data.textures.new(TEXTURE, "IMAGE")
    tex.image = photo
    tex.extension = "CLIP"
    return tex


def update_brush(rb):
    """The brush's photo and edge (Soft: smooth falloff, else hard)."""
    b = bpy.data.brushes.get(BRUSH)
    if b is None:
        return
    cam = core.cameras().get(rb.photo)
    photo = core.photo_image(cam)
    if photo is not None:
        b.texture = _texture(photo)
    b.texture_slot.map_mode = "STENCIL"
    b.texture_overlay_alpha = 0     # the camera shows the photo; Blender would draw this one over the photo panel
    b.color = (1.0, 1.0, 1.0)
    b.blend = "MIX"
    b.strength = 1.0
    b.curve_distance_falloff_preset = "SMOOTH" if rb.soft else "CONSTANT"


def painting(context):
    rb = context.scene.livinglacquer_rebuild
    ob = context.active_object
    return ob is not None and ob == rb.target and ob.mode == "TEXTURE_PAINT"


def start(context, rb):
    """Texture Paint on the rebuilt object: canvas BAp_ (made at BAo_'s size), uv_normal, the photo brush."""
    ob = rb.target
    bap = bake.ensure_painted(rb, ob)
    core.ensure_uv(ob)
    if rb.shading != "PAINT":
        rb.shading = "PAINT"
    for o in context.selected_objects:
        o.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if ob.mode != "TEXTURE_PAINT":
        bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
    ip = context.scene.tool_settings.image_paint
    ip.mode = "IMAGE"
    ip.canvas = bap
    ip.use_occlude = True
    ip.use_backface_culling = True
    ip.use_normal_falloff = True
    ip.normal_angle = 80
    _brush()
    update_brush(rb)
    bpy.ops.brush.asset_activate(asset_library_type="LOCAL", relative_asset_identifier=f"Brush/{BRUSH}")
    fit_all()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=INTERVAL)


def stop(context):
    if context.active_object is not None and context.active_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def _frame(scene, cam, region, rv3d):
    """The camera frame's corners in region pixels (None when the view does not show them)."""
    frame = cam.data.view_frame(scene=scene)
    pts = [view3d_utils.location_3d_to_region_2d(region, rv3d, cam.matrix_world @ v) for v in frame]
    return None if any(p is None for p in pts) else pts


def fit_all():
    """Put the brush's stencil on the camera frame of the first 3D view looking through the camera."""
    b = bpy.data.brushes.get(BRUSH)
    scene = bpy.context.scene
    cam = scene.camera
    if b is None or cam is None:
        return
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            rv3d = area.spaces.active.region_3d
            if rv3d.view_perspective != "CAMERA":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            pts = _frame(scene, cam, region, rv3d) if region else None
            if not pts:
                continue
            xs, ys = [p.x for p in pts], [p.y for p in pts]
            pos = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
            dim = Vector(((max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2))
            if (Vector(b.stencil_pos) - pos).length > 0.5 or (Vector(b.stencil_dimension) - dim).length > 0.5:
                b.stencil_pos, b.stencil_dimension = pos, dim
            return


def _tick():
    try:
        if not painting(bpy.context):
            return None             # stops; Brush starts it again
        fit_all()
    except Exception as e:          # never break painting
        print(f"[LivingLacquer] stencil fit: {e}")
    return INTERVAL


def lock_views(lock):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.lock_rotation = lock


def solo(context, rb, on):
    """Hide every other mesh / curve in the viewport (Solo on), show them again (off)."""
    scene = context.scene
    if on:
        hid = []
        for o in context.view_layer.objects:
            if o != rb.target and o.type in {"MESH", "CURVE", "SURFACE", "FONT", "EMPTY"} and not o.hide_get():
                o.hide_set(True)
                hid.append(o.name)
        scene[SOLO_KEY] = hid
    else:
        for name in scene.get(SOLO_KEY, []):
            o = bpy.data.objects.get(name)
            if o is not None and o.name in context.view_layer.objects:
                o.hide_set(False)
        if SOLO_KEY in scene:
            del scene[SOLO_KEY]


def is_solo(context):
    return SOLO_KEY in context.scene


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
