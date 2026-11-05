"""5b Brush: Blender's own Texture Paint, painting the photo into BAp_. The brush ("LL Photo", a local
brush asset) carries the photo as a Stencil texture, and a timer keeps the stencil on the camera's frame
in every 3D view that looks through the camera, so a stroke copies the photo where it lies on the mesh.
Occlude, backface culling and normal falloff are on: only what the view sees gets paint.

Solo shows only the rebuilt object (the cameras stay, they draw their photos); Lock stops the views
from rotating out of the camera. Free: the stencil leaves the camera and stays where it is on the screen,
drawn by the photo panel's module, while the view moves under it: a stamp of the photo on any part.
Blender's own stencil keys place it.

While the Brush is on the timeline stands still and the GN- modifiers are off (Mesh Build's playback shows an older
stage, whose UVs may lie elsewhere): paint lands on the last version of the mesh, on uv_normal. Flat turns them off once,
so what shows is that paint; turned back on while only Flat is on (Preview ON, Play Build) they stay on. What the Brush or
Flat turned off comes back when both end, however they end: GN_OFF_KEY on the object remembers it across a reload or a
saved file.

A stroke paints only BAp_, and Blender gives no event for it: the timer waits for the stroke to end and compares BAp_
under MSKp_'s pixels with the last look (sync_stroke), and what changed turns MSKp_ white. LL_ does not read BAp_'s alpha,
so it holds marks: 0 under MSKp_'s pixels that are not white, which any stroke raises, even one painting the same colours.
Erase paints MSKp_ itself: the canvas is MSKp_ and the "LL Mask" brush paints black.

Pin: a photo whose camera does not help (the object was turned over for it, so the camera solved on the table) keeps
the view and the stencil as the user lined them up, on its camera (PIN_KEY, saved with the file). Loading it goes there."""
import json
import math

import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector

from . import bake, core

STROKE_OP = "PAINT_OT_image_paint"
STROKE_GAIN = 8.0                   # a stroke's change in BAp_ to how far MSKp_ goes white
_look = {"name": "", "px": None, "stroking": False}      # BAp_ under MSKp_'s pixels, as last seen
BRUSH = "LL Photo"
MASK_BRUSH = "LL Mask"
TEXTURE = "LL Photo"
SOLO_KEY = "ll_rebuild_solo"        # scene key: the objects Solo hid
GN_OFF_KEY = "ll_paint_gn_off"      # object key: the GN- modifiers the Brush turned off
PIN_KEY = "ll_pin"                  # camera key: the pinned view and stencil (JSON)
INTERVAL = 0.1
STENCIL_DEFAULT_POS = (256, 256)    # Blender's, on a brush nobody placed yet
STAMP_HEIGHT = 0.7                  # of the view, the photo's first size in Free


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
    m = bpy.data.brushes.get(MASK_BRUSH)
    if m is not None:
        m.curve_distance_falloff_preset = "SMOOTH" if rb.soft else "CONSTANT"
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


def _set_color(context, color):
    context.scene.tool_settings.image_paint.unified_paint_settings.color = color


def masking(context):
    """Erase is on: Texture Paint with MSKp_ as the canvas."""
    canvas = context.scene.tool_settings.image_paint.canvas
    return painting(context) and canvas is not None and canvas.name.startswith(core.MASK)


def start_mask(context, rb):
    """Texture Paint as start() does, on MSKp_: a stroke paints it black, BAo_ shows under it."""
    start(context, rb)
    b = bpy.data.brushes.get(MASK_BRUSH)
    if b is None:
        b = bpy.data.brushes.new(MASK_BRUSH, mode="TEXTURE_PAINT")
    if b.asset_data is None:
        b.asset_mark()
    b.color = (0.0, 0.0, 0.0)
    b.blend = "MIX"
    b.strength = 1.0
    b.curve_distance_falloff_preset = "SMOOTH" if rb.soft else "CONSTANT"
    context.scene.tool_settings.image_paint.canvas = core.image(core.MASK, rb.target)
    bpy.ops.brush.asset_activate(asset_library_type="LOCAL", relative_asset_identifier=f"Brush/{MASK_BRUSH}")
    _set_color(context, (0.0, 0.0, 0.0))


def painting(context):
    rb = context.scene.livinglacquer_rebuild
    ob = context.active_object
    return ob is not None and ob == rb.target and ob.mode == "TEXTURE_PAINT"


def _stop_timeline():
    for win in bpy.context.window_manager.windows:
        if win.screen.is_animation_playing:
            with bpy.context.temp_override(window=win, screen=win.screen):
                bpy.ops.screen.animation_cancel(restore_frame=False)


def _final_mesh_on(ob):
    """ob's GN- modifiers off in the view, also one pressed back on while painting."""
    names = [m.name for m in ob.modifiers if bake.is_gn(m) and m.show_viewport]
    if names:
        for name in names:
            ob.modifiers[name].show_viewport = False
        ob[GN_OFF_KEY] = sorted(set(ob.get(GN_OFF_KEY, [])) | set(names))
        ob.update_tag()


def has_pin(cam):
    return cam is not None and PIN_KEY in cam


def _view3d(context):
    """(space, rv3d, region) of the 3D view of this context, else the first one; (None,) * 3 without one."""
    area = context.area if context.area is not None and context.area.type == "VIEW_3D" else None
    if area is None and context.screen is not None:
        area = next((a for a in context.screen.areas if a.type == "VIEW_3D"), None)
    if area is None:
        return None, None, None
    return area.spaces.active, area.spaces.active.region_3d, next((r for r in area.regions if r.type == "WINDOW"), None)


def _pin_data(space, rv3d, region, b):
    return {"location": list(rv3d.view_location), "rotation": list(rv3d.view_rotation),
            "distance": rv3d.view_distance, "perspective": rv3d.view_perspective, "lens": space.lens,
            "pos": list(b.stencil_pos), "dim": list(b.stencil_dimension), "angle": b.texture_slot.angle,
            "region": [region.width, region.height]}


def _pin_stencil(data, width, height):
    """The pinned stencil's (pos, dim) in a view of another size: Blender keeps the view's middle and scales the
    picture with the view's longer side."""
    w, h = data["region"]
    s = max(width, height) / max(w, h, 1)
    return ((width / 2 + (data["pos"][0] - w / 2) * s, height / 2 + (data["pos"][1] - h / 2) * s),
            (data["dim"][0] * s, data["dim"][1] * s))


def pin(context, cam):
    """cam keeps the view and the stencil as they are now. False when no free 3D view is there to keep."""
    space, rv3d, region = _view3d(context)
    if region is None or rv3d.view_perspective == "CAMERA":
        return False
    cam[PIN_KEY] = json.dumps(_pin_data(space, rv3d, region, _brush()))
    return True


def unpin(cam):
    if PIN_KEY in cam:
        del cam[PIN_KEY]


def pin_is_current(context, cam):
    """The view and the stencil are where cam's pin has them."""
    space, rv3d, region = _view3d(context)
    if not has_pin(cam) or region is None or rv3d.view_perspective == "CAMERA":
        return False
    data = json.loads(cam[PIN_KEY])
    now = _pin_data(space, rv3d, region, _brush())
    pos, dim = _pin_stencil(data, region.width, region.height)
    near = lambda a, b, tol: all(abs(x - y) <= tol for x, y in zip(a, b))
    return (near(now["location"], data["location"], 1e-4) and near(now["rotation"], data["rotation"], 1e-4)
            and abs(now["distance"] - data["distance"]) <= 1e-4 and near(now["pos"], pos, 1.0)
            and near(now["dim"], dim, 1.0) and abs(now["angle"] - data["angle"]) <= 1e-3)


def load_pin(context, cam):
    """The view and the stencil back as cam's pin has them."""
    space, rv3d, region = _view3d(context)
    if region is None or not has_pin(cam):
        return False
    data = json.loads(cam[PIN_KEY])
    rv3d.view_perspective = data["perspective"]
    rv3d.view_location = data["location"]
    rv3d.view_rotation = data["rotation"]
    rv3d.view_distance = data["distance"]
    space.lens = data["lens"]
    b = _brush()
    b.stencil_pos, b.stencil_dimension = _pin_stencil(data, region.width, region.height)
    b.texture_slot.angle = data["angle"]
    return True


def flat_changed(rb):
    """Flat on: the last version of the mesh at once, and kept; off: the timer gives it back."""
    if rb.flat and rb.target is not None:
        _final_mesh_on(rb.target)
    _resume()


def _forget_turned_on(ob):
    """GN- modifiers the user turned back on are the user's again: the end of Flat leaves them as they are then."""
    names = [n for n in ob.get(GN_OFF_KEY, []) if n in ob.modifiers and not ob.modifiers[n].show_viewport]
    if GN_OFF_KEY in ob and len(names) != len(ob[GN_OFF_KEY]):
        if names:
            ob[GN_OFF_KEY] = names
        else:
            del ob[GN_OFF_KEY]


def _release_gn():
    """The modifiers the Brush turned off back on."""
    for ob in bpy.data.objects:
        if GN_OFF_KEY in ob:
            for name in ob[GN_OFF_KEY]:
                m = ob.modifiers.get(name)
                if m is not None:
                    m.show_viewport = True
            del ob[GN_OFF_KEY]
            ob.update_tag()


def start(context, rb):
    """Texture Paint on the rebuilt object's last version: canvas BAp_ (made at BAo_'s size), uv_normal, the
    photo brush, the timeline stopped and its GN- modifiers off."""
    ob = rb.target
    _stop_timeline()
    _final_mesh_on(ob)
    bap = bake.ensure_painted(rb, ob)
    bake.ensure_mask(rb, ob)
    forget_look()
    core.ensure_uv(ob)
    if rb.shading != "PAINT":
        rb.shading = "PAINT"
    core.set_shading(ob, "PAINT")       # MultiCamProject's sync may have changed the slots
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
    _set_color(context, (1.0, 1.0, 1.0))
    fit_all()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=INTERVAL)


def stop(context):
    if context.active_object is not None and context.active_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    if not context.scene.livinglacquer_rebuild.flat:
        _release_gn()


def _frame(scene, cam, region, rv3d):
    """The camera frame's corners in region pixels (None when the view does not show them)."""
    frame = cam.data.view_frame(scene=scene)
    pts = [view3d_utils.location_3d_to_region_2d(region, rv3d, cam.matrix_world @ v) for v in frame]
    return None if any(p is None for p in pts) else pts


def stamping(context):
    """Free while painting: the photo stays on the screen, the view moves under it."""
    rb = getattr(context.scene, "livinglacquer_rebuild", None)
    return rb is not None and rb.focus == "FREE" and painting(context)


def stencil_corners():
    """The stencil's corners in region pixels, in the photo's order, as Blender places it; None without a photo."""
    b = bpy.data.brushes.get(BRUSH)
    if b is None or b.texture is None or getattr(b.texture, "image", None) is None:
        return None
    (x, y), (dx, dy) = b.stencil_pos, b.stencil_dimension
    c, s = math.cos(b.texture_slot.angle), math.sin(b.texture_slot.angle)
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in ((-dx, -dy), (dx, -dy), (dx, dy), (-dx, dy))]


def _visible_span(area, region):
    """The region's x range the toolbar and the sidebar leave free (they lie over it)."""
    left, right = 0, region.width
    for r in area.regions:
        if r.type == "TOOLS" and r.width > 1:
            left = max(left, r.x + r.width - region.x)
        elif r.type == "UI" and r.width > 1:
            right = min(right, r.x - region.x)
    return (left, right) if left < right else (0, region.width)


def _fit_free(b):
    """Keep what the user placed: only the photo's proportions, and back in sight when its middle is not
    (the camera frame may have left it behind the sidebar). Never placed: in the middle of the view."""
    img = b.texture.image if b.texture is not None else None
    w, h = img.size if img is not None else (0, 0)
    if not w or not h:
        return
    dx, dy = b.stencil_dimension
    if abs(dx - dy * w / h) > 0.5:
        b.stencil_dimension = (dy * w / h, dy)
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            region = next((r for r in area.regions if r.type == "WINDOW"), None) if area.type == "VIEW_3D" else None
            if region is not None:
                x, y = b.stencil_pos
                left, right = _visible_span(area, region)
                middle = ((left + right) / 2, region.height / 2)
                if (round(x), round(y)) == STENCIL_DEFAULT_POS:
                    dy = region.height * STAMP_HEIGHT / 2
                    b.stencil_dimension = (dy * w / h, dy)
                    b.stencil_pos = middle
                elif not (left <= x <= right and 0 <= y <= region.height):
                    b.stencil_pos = middle
                return


def fit_all():
    """Put the brush's stencil on the camera frame of the first 3D view looking through the camera
    (Free: it stays where it is on the screen)."""
    b = bpy.data.brushes.get(BRUSH)
    scene = bpy.context.scene
    cam = scene.camera
    if b is None or cam is None:
        return
    if scene.livinglacquer_rebuild.focus == "FREE":
        _fit_free(b)
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
            if b.texture_slot.angle:        # turned while stamping: the frame has none
                b.texture_slot.angle = 0.0
            return


def forget_look():
    """The next look at BAp_ only starts the comparing: Fill, Erase, an undo or a new session changed it."""
    _look.update(name="", px=None, stroking=False)


def _stroke_running():
    return any(op.bl_idname == STROKE_OP for win in bpy.context.window_manager.windows for op in win.modal_operators)


def _bap_look(bap, msk):
    """BAp_ under MSKp_'s pixels, its alpha marked 0 where MSKp_ is not white (written once, for the next stroke)."""
    rows = bake.grid(bap.size[0], msk.size[0])
    at = np.ix_(rows, rows)
    cur = bake.pixels(bap)
    a = cur[..., 3]
    marked = np.where(bake.pixels(msk)[..., 0] < 0.999, 0.0, a[at])
    if np.abs(marked - a[at]).max(initial=0.0) > 1e-6:
        a[at] = marked
        bake.set_pixels(bap, cur)
    return cur[at].copy()


def sync_stroke(rb):
    """After a stroke: MSKp_ goes white where BAp_ changed. Blender's image undo does not reach MSKp_."""
    ob, bap = rb.target, core.image(core.PAINTED, rb.target)
    msk = core.image(core.MASK, ob)
    if bap is None or msk is None or bpy.context.scene.tool_settings.image_paint.canvas != bap:
        return
    if _stroke_running():
        _look["stroking"] = True
        return
    if _look["px"] is None or _look["name"] != bap.name:
        _look.update(name=bap.name, px=_bap_look(bap, msk), stroking=False)
        return
    if not _look["stroking"]:
        return
    rows = bake.grid(bap.size[0], msk.size[0])
    now = bake.pixels(bap)[np.ix_(rows, rows)]
    k = np.clip(np.abs(now - _look["px"]).max(axis=2) * STROKE_GAIN, 0.0, 1.0)
    _look.update(px=now.copy(), stroking=False)
    if k.max(initial=0.0) > 0.0:
        px = bake.pixels(msk)
        px[..., :3] += (1.0 - px[..., :3]) * k[..., None]
        bake.set_pixels(msk, px)


def _tick():
    try:
        rb = bpy.context.scene.livinglacquer_rebuild
        on = painting(bpy.context)
        if not on and not rb.flat:
            _release_gn()
            return None             # stops; Brush and Flat start it again
        if on:
            if rb.target is not None:
                _final_mesh_on(rb.target)
                sync_stroke(rb)
            _stop_timeline()
            fit_all()
        elif rb.target is not None:
            _forget_turned_on(rb.target)
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


def _resume(*_args):
    """Flat, or the modifiers still off after a reload or a load: the timer goes on watching."""
    rb = getattr(bpy.context.scene, "livinglacquer_rebuild", None)
    if (rb is not None and rb.flat or any(GN_OFF_KEY in o for o in bpy.data.objects)) \
            and not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=INTERVAL)
    return None


@bpy.app.handlers.persistent
def _on_load(*_args):
    forget_look()
    _resume()


@bpy.app.handlers.persistent
def _on_undo(*_args):
    forget_look()


@bpy.app.handlers.persistent
def _on_save_pre(*_args):
    """MSKp_ goes with the .blend: there is no button for it."""
    for img in bpy.data.images:
        if img.name.startswith(core.MASK) and img.is_dirty and core.image_file(img):
            try:
                img.save()
            except RuntimeError as e:
                print(f"[LivingLacquer] {img.name} not saved: {e}")


def register():
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.undo_post.append(_on_undo)
    bpy.app.handlers.redo_post.append(_on_undo)
    bpy.app.handlers.save_pre.append(_on_save_pre)
    bpy.app.timers.register(_resume, first_interval=0.1)


def unregister():
    bpy.app.handlers.load_post.remove(_on_load)
    bpy.app.handlers.undo_post.remove(_on_undo)
    bpy.app.handlers.redo_post.remove(_on_undo)
    bpy.app.handlers.save_pre.remove(_on_save_pre)
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
