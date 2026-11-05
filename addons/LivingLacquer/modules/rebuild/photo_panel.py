"""The floating photo panel, Shift+Q in the 3D viewport. Blender's own panels cannot show a clickable or
draggable picture, so it draws itself (gpu) and handles the mouse:

    > View  > Model  > Budget  > Textures  > Recorder     foldable sections, on top
                                                (under Model while a uvTube is open: its values, Confirm, Cancel)
    [ Brush ] [ Fill ] [ Erase ]                the paint tools (BAp_ over BAo_)
    Favorites                                   click: load. Drag: order. Drag to the bin: out of them
    [<] Focus Lock Free  Solo Soft  name [>] [bin]   < > step through All Photos from the active camera
    All Photos                                  click: load. Not sortable. Drag up to Favorites: pin it

Drag the panel by any empty part, resize it by any side or corner (both saved with the scene). The wheel scrolls the grid under the mouse. A redraw only reuses cached geometry: the
batches are rebuilt only for positions not seen yet."""
import os
import sys

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import budget, check, core, paint, panel_icons, poly_cut, thumbs, uv_tube
from ..project import prefs, viewbar

WIDTH, HEIGHT = 430, 520    # the default size at UI scale 1
MIN_WIDTH, MIN_HEIGHT = 360, 270
GRIP = 16                   # the resize corner
TOOL_H = 30
PAD = 6
FAV_PX, ALL_PX = 100, 50
FAV_SHARE = 0.48             # of the two grids' height, rounded to whole rows of Favorites
BAR = 36                    # the row of the bin, < > and the modes
STATUS_H = 18
DRAG_PX = 5                 # a press moved further than this is a drag, not a click
LOAD_PER_DRAW = 4           # thumbnails read per redraw (the files may stream from Drive)
MAX_BATCHES = 2000
ROW_NUDGE = 16              # the panel opens with the mouse this far under its top

BACK = (0.11, 0.11, 0.11, 0.95)
BOX = (0.06, 0.06, 0.06, 1.0)
BTN = (0.26, 0.26, 0.26, 1.0)
BTN_ON = (0.27, 0.45, 0.77, 1.0)
BTN_OFF = (0.17, 0.17, 0.17, 1.0)
CURRENT = (0.3, 0.6, 1.0, 1.0)
TARGET = (1.0, 0.75, 0.2, 1.0)
DELETE = (0.85, 0.25, 0.2, 1.0)
HINT = (0.62, 0.62, 0.62, 0.9)
HINT_CORNER = 14            # the corner brackets' arms
SECTION_H, SECTION_ROW, LINE_H = 20, 24, 16
SECTIONS = ("View", "Model", "Budget", "Textures", "Recorder")      # rb.panel_open's order
TUBE = "uvTube"                                                     # only while one is open, never folded
OPS = {"base": ("livinglacquer", "rebuild_base_disc"), "extrude": ("livinglacquer", "uv_extrude"),
       "tube": ("livinglacquer", "uv_tube"), "poly": ("livinglacquer", "poly_cut_tool"),
       "realign": ("livinglacquer", "realign_camera"),
       "measure": ("livinglacquer", "rebuild_budget"), "check": ("livinglacquer", "rebuild_check_textures"),
       "fix": ("livinglacquer", "rebuild_fix_textures"), "edit_alb": ("livinglacquer", "alb_edit"),
       "rec_start": ("meshbuildtimelapse", "start"), "rec_pause": ("meshbuildtimelapse", "pause_resume"),
       "rec_capture": ("meshbuildtimelapse", "capture"), "rec_build": ("meshbuildtimelapse", "build_stages"),
       "rec_clear": ("meshbuildtimelapse", "clear_record")}
TUBE_SLIDERS = {"tube:Sides", "tube:Segments", "tube:Radius", "tube:Seam"}
TUBE_SWITCHES = {"tube:Smooth", "tube:Adaptive", "tube:Caps"}
SLIDERS = {"wire_opacity", "budget", "cage"} | TUBE_SLIDERS
COLLECTION_LABELS = {"Original Mesh": "Scan", "OBJECTS": "Objects", "EXPORT": "Export", "CAMERAS": "Cameras"}
ICON_PX = 16
STAMP_ALPHA = 0.55          # Free's photo over the view
STAMP_HINT = "Free: orbit under the photo  ·  Right-drag: move  ·  Shift: size  ·  Ctrl: turn"

DRAG = {"kind": "", "id": "", "x": 0, "y": 0, "moved": False, "over": None}
_pos = [None, None]         # the panel's left and top, in region pixels
_size = [None, None]        # its width and height
_batches = {}               # (shader, x0, y0, x1, y1) -> batch
_scroll = {"fav": 0, "all": 0}
_seen = {"photo": ""}       # the photo the All Photos grid last scrolled to
_handler = None
_stamp_handler = None
_keymaps = []
_waiting = {"on": False}


def active(context):
    rb = getattr(context.scene, "livinglacquer_rebuild", None)
    return bool(rb and rb.show_photos and core.cameras())


def tools_ready(rb, context):
    ob = rb.target
    return (ob is not None and ob.name in context.view_layer.objects and not core.locked(ob)
            and len(ob.data.polygons) > 0)


def _grid(names, x0, y1, width, size, pad, scroll):
    """[(name, x, y, size)] left to right, top to bottom from y1, and the grid's full height."""
    cols = max(1, int((width - pad) // (size + pad)))
    cells = []
    for i, n in enumerate(names):
        r, c = divmod(i, cols)
        cells.append((n, x0 + pad + c * (size + pad), y1 - (r + 1) * (size + pad) + scroll, size))
    rows = (len(names) + cols - 1) // cols
    return cells, rows * (size + pad) + pad


def _recorder_rows(context):
    """The Recorder section's buttons (action, label) and status line; (None, None) without MeshBuildTimelapse."""
    mod = next((m for k, m in sys.modules.items() if k.endswith("timelapse.cache")), None)
    if mod is None or not hasattr(bpy.ops, "meshbuildtimelapse"):
        return None, None
    obj = context.active_object
    if not bpy.data.filepath:
        return [], "Save the .blend to start recording"
    if obj is None or obj.type != "MESH":
        return [], "Select a mesh object"
    rec = mod.rec_of(obj)
    if rec is None:
        return [("rec_start", "Start Recording")], obj.name
    m = rec.m
    on = m["state"] == "RECORDING"
    return ([("rec_pause", "Pause" if on else "Resume"), ("rec_capture", "Capture"), ("rec_build", "Build"),
             ("rec_clear", "Clear")], f"{m['name']}: {m['head'] + 1} stages")


def _section_body(context, rb, name):
    """(rows of (action, label), text lines (text, red)) for an open section."""
    if name == TUBE:
        return [[("tube:Sides", ""), ("tube:Segments", ""), ("tube:Radius", "")],
                [("tube:Smooth", "Smooth"), ("tube:Adaptive", "Adaptive"), ("tube:Caps", "Caps"), ("tube_bezier", "Bezier")],
                [("tube_move", "Move"), ("tube_shape", "Shape"), ("tube:Seam", ""), ("tube_pick", "Pick Seam")],
                [("tube_confirm", "Confirm"), ("tube_cancel", "Cancel")]], \
            [(f"Drag a value  ·  red: the seam  ·  {uv_tube.faces_count(uv_tube.open_tube(context))} faces", False)]
    if name == "View":
        return ([[("ov_overlays", "Overlays"), ("ov_faces", "Faces"), ("ov_wire", "Wire"), ("wire_opacity", "")],
                 [("col:" + c, COLLECTION_LABELS[c]) for c, _i in viewbar.COLLECTIONS]], [])
    if name == "Model":
        return [[("mesh:ORG", "ORG_"), ("mesh:FINAL", "OBJ_"), ("realign", "Realign")],
                [("base", "From Base"), ("tube", "uvTube"), ("extrude", "uvExtrude"), ("poly", "Poly Cut")],
                [("pref:auto_seams", "Auto Seams"), ("pref:auto_uv", "Auto UV")]], []
    if name == "Budget":
        r = budget.ROWS
        rows = [[("budget", f"Budget {budget.short(rb.tri_budget)}"), ("measure", "Measure")]]
        if r["blend"] != bpy.data.filepath:
            return rows, [("Press Measure for the EXPORT collection", False)]
        text = [(f"{i['name']}  {i['share']:.0%}  {budget.short(i['tris'])} / {budget.short(i['budget'])}",
                 i["tris"] > i["budget"]) for i in r["items"][:6]]
        return rows, text + [(f"Total {budget.short(r['total_tris'])} / {budget.short(rb.tri_budget)}",
                              r["total_tris"] > rb.tri_budget)]
    if name == "Textures":
        r = check.REPORT
        rows = [[("check", "Check"), ("fix", "Fix"), ("edit_alb", "Edit ALB_"), ("cage", "")]]
        if r["blend"] != bpy.data.filepath:
            return rows, []
        text = [(f"{n} goes to {os.path.basename(os.path.dirname(w))}", True) for n, _s, w in r["moves"][:3]]
        text += [(f"Copy: {os.path.basename(os.path.dirname(p))}/{os.path.basename(p)}", True) for p in r["strays"][:3]]
        text += [(f"{n}: file missing", True) for n in r["missing"][:3]]
        return rows, text or [(f"All in place ({r['checked']} object(s))", False)]
    buttons, status = _recorder_rows(context)
    return ([buttons] if buttons else []), [(status, False)]


def _visible_sections(context):
    names = [n for n in SECTIONS if n != "Recorder" or _recorder_rows(context)[0] is not None]
    if uv_tube.open_tube(context) is not None:
        names.insert(names.index("Model") + 1, TUBE)
    return names


def _section_open(rb, name):
    return name == TUBE or rb.panel_open[SECTIONS.index(name)]


def sections_height(context):
    """The height of the foldable sections, with the padding under them."""
    rb = context.scene.livinglacquer_rebuild
    ui = context.preferences.system.ui_scale
    pad = int(PAD * ui)
    h = 0
    for name in _visible_sections(context):
        h += int(SECTION_H * ui)
        if _section_open(rb, name):
            rows, text = _section_body(context, rb, name)
            h += len(rows) * int(SECTION_ROW * ui) + len(text) * int(LINE_H * ui)
    return h + pad


def _layout_sections(context, rb, buttons, lines, x0, x1, top, ui):
    """Fill buttons and lines with the sections from top down; returns the y under them."""
    y = top
    for name in _visible_sections(context):
        h = int(SECTION_H * ui)
        buttons.append(("sec:" + name, (x0, y - h, x1, y), name))
        y -= h
        if not _section_open(rb, name):
            continue
        rows, text = _section_body(context, rb, name)
        for row in rows:
            h = int(SECTION_ROW * ui)
            bw = (x1 - x0) // max(1, len(row))
            for i, (action, label) in enumerate(row):
                buttons.append((action, (x0 + i * bw, y - h, x0 + (i + 1) * bw, y), label))
            y -= h
        for t, red in text:
            y -= int(LINE_H * ui)
            lines.append((t, x0 + int(4 * ui), y + int(3 * ui), red))
    return y - int(PAD * ui)


def layout(context, region):
    """Every part of the panel, in region pixels: {"panel": rect, "edge": px, "grip": rect, "buttons":
    [(action, rect, label)], "name": rect, "blue": rect, "fav_area": rect, "yellow": rect, "trash": rect,
    "fav": cells, "all": cells, "status": (x, y)}."""
    rb = context.scene.livinglacquer_rebuild
    ui = context.preferences.system.ui_scale
    pad = int(PAD * ui)
    tool_h, status_h, bar = int(TOOL_H * ui), int(STATUS_H * ui), int(BAR * ui)
    if _pos[0] is None:
        x, top, w, h = rb.panel_rect
        _pos[0], _pos[1] = (x, top) if w else (int(60 * ui), region.height - int(60 * ui))
        _size[0], _size[1] = (w, h) if w else (int(WIDTH * ui), int(HEIGHT * ui))
    w = max(int(MIN_WIDTH * ui), min(_size[0], region.width))
    sec_h = sections_height(context)
    h = max(int(MIN_HEIGHT * ui) + sec_h, min(_size[1], region.height))
    grids = h - (tool_h + status_h + 4 * pad + sec_h)
    strip = bar + pad                   # under the Favorites: the bar and the bin
    fav_row = int(FAV_PX * ui) + pad
    fav_h = pad + strip + fav_row * max(1, round((grids * FAV_SHARE - pad - strip) / fav_row))
    fav_h = min(fav_h, grids - (int(ALL_PX * ui) + 2 * pad))
    all_h = grids - fav_h
    x0 = max(0, min(_pos[0], region.width - w))
    top = max(h, min(_pos[1], region.height))
    x1 = x0 + w
    out = {"panel": (x0, top - h, x1, top), "edge": pad}
    grip = int(GRIP * ui)
    out["grip"] = (x1 - grip, top - h, x1, top - h + grip)

    buttons, lines = [], []
    y1 = _layout_sections(context, rb, buttons, lines, x0 + pad, x1 - pad, top - pad, ui)
    out["lines"] = lines
    # [Brush] [Fill] [Erase] [Clear]
    y0 = y1 - tool_h
    tw = (w - 2 * pad) // 4
    for i, (action, text) in enumerate((("brush", "Brush"), ("fill", "Fill"), ("erase", "Erase"), ("clear_mask", "Clear"))):
        buttons.append((action, (x0 + pad + i * tw, y0, x0 + pad + (i + 1) * tw, y1), text))
    # Favorites; along their bottom [<] Focus Lock Free Solo Soft name [>] [bin]
    y1 = y0 - pad
    y0 = y1 - fav_h
    out["blue"] = (x0 + pad, y0, x1 - pad, y1)
    out["fav_area"] = (x0 + pad, y0 + strip, x1 - pad, y1)
    by0, by1 = y0 + pad, y0 + pad + bar
    out["trash"] = (x1 - 2 * pad - bar, by0, x1 - 2 * pad, by1)
    right = x1 - 3 * pad - bar          # where the bar ends
    buttons.append(("prev", (x0 + 2 * pad, by0, x0 + 2 * pad + bar, by1), "<"))
    buttons.append(("next", (right - bar, by0, right, by1), ">"))
    x = x0 + 3 * pad + bar
    room = right - bar - pad - x
    bw = min(int(52 * ui), (room - pad) // 7)
    for action, text in (("FOCUS", "Focus"), ("LOCK", "Lock"), ("FREE", "Free"), ("solo", "Solo"), ("soft", "Soft"),
                         ("flat", "Flat"), ("pin", "Pin")):
        buttons.append((action, (x, by0, x + bw, by1), text))
        x += bw + (pad if action == "FREE" else 0)
    out["name"] = (x + pad, by0, right - bar - pad, by1)
    out["buttons"] = buttons
    names = core.favorites(rb)
    size = int(FAV_PX * ui)
    area_h = fav_h - strip
    _scroll["fav"] = max(0, _scroll["fav"])
    cells, full = _grid(names, x0 + pad, y1, w - 2 * pad, size, pad, _scroll["fav"])
    _scroll["fav"] = min(_scroll["fav"], max(0, full - area_h))
    out["fav"], _ = _grid(names, x0 + pad, y1, w - 2 * pad, size, pad, _scroll["fav"])
    # All Photos, sorted by name: scrolled to the photo when it changed
    y1 = y0 - pad
    y0 = y1 - all_h
    out["yellow"] = (x0 + pad, y0, x1 - pad, y1)
    names = sorted(core.cameras())
    size = int(ALL_PX * ui)
    cells, full = _grid(names, x0 + pad, y1, w - 2 * pad, size, pad, 0)
    if rb.photo != _seen["photo"]:
        _seen["photo"] = rb.photo
        for n, _x, y, _s in cells:
            if n == rb.photo:
                from_top = y1 - (y + size)
                if from_top < _scroll["all"]:
                    _scroll["all"] = from_top - pad
                elif from_top + size + pad > _scroll["all"] + all_h:
                    _scroll["all"] = from_top + size + 2 * pad - all_h
    _scroll["all"] = max(0, min(_scroll["all"], max(0, full - all_h)))
    out["all"], _ = _grid(names, x0 + pad, y1, w - 2 * pad, size, pad, _scroll["all"])
    out["status"] = (x0 + pad, y0 - pad - int(11 * ui))
    return out


def _inside(rect, mx, my):
    return rect[0] <= mx < rect[2] and rect[1] <= my < rect[3]


def hit(context, region, mx, my):
    """What is under the mouse: (kind, id), kind = edge (id: L, R, T, B, or two of them) / button / trash /
    fav / all / blue / yellow / panel; None off the panel."""
    lay = layout(context, region)
    x0, y0, x1, y1 = lay["panel"]
    e = lay["edge"]                     # the band of each side, inside and out (the hints straddle it)
    if not _inside((x0 - e, y0 - e, x1 + e, y1 + e), mx, my):
        return None
    if _inside(lay["grip"], mx, my):
        return "edge", "RB"
    sides = ("L" if mx < x0 + e else "R" if mx >= x1 - e else "") + ("B" if my < y0 + e else "T" if my >= y1 - e else "")
    if sides:
        return "edge", sides
    for action, rect, _text in lay["buttons"]:
        if _inside(rect, mx, my):
            return "button", action
    if _inside(lay["trash"], mx, my):
        return "trash", ""
    for kind, box, area in (("fav", "blue", "fav_area"), ("all", "yellow", "yellow")):
        if _inside(lay[box], mx, my):
            if _inside(lay[area], mx, my):
                for name, x, y, s in lay[kind]:
                    if x <= mx < x + s and y <= my < y + s:
                        return kind, name
            return box, ""
    return "panel", ""


def drop(rb, kind, name, over):
    """A photo dragged from kind (fav / all) ended on over: All Photos into the Favorites pins it, within
    the Favorites it moves, on the trash it goes out."""
    if over is None:
        return
    target, there = over
    names = core.favorites(rb)
    if kind == "fav" and target == "trash":
        names.remove(name)
    elif target in {"fav", "blue"}:
        if name in names:
            if kind == "all" or name == there:
                return
            names.remove(name)
        names.insert(names.index(there) if there in names else len(names), name)
    else:
        return
    core.write_list(rb.favorites, names)


def _op(action):
    module, name = OPS[action]
    return getattr(getattr(bpy.ops, module), name)


def _overlay(context):
    space = context.space_data
    return space.overlay if space is not None and space.type == "VIEW_3D" else None


def slide(context, action, x, rect, start_x=None, start_value=None):
    """The sliders: wire opacity follows the mouse, the budget grows and shrinks with the drag."""
    if action == "wire_opacity":
        ov = _overlay(context)
        if ov is not None:
            ov.wireframe_opacity = max(0.0, min(1.0, (x - rect[0]) / max(1, rect[2] - rect[0])))
    elif action == "cage":
        context.scene.livinglacquer_rebuild.cage = max(start_value, 0.0001) * 2 ** ((x - start_x) / 100.0)
    elif action in TUBE_SLIDERS:
        tube = uv_tube.open_tube(context)
        mod = uv_tube.modifier(tube)
        if mod is None or start_value is None:
            return
        name, dx = action[5:], x - start_x
        if name == "Seam":
            uv_tube.set_seam_side(tube, start_value + dx // 12)
            return
        if name == "Radius":
            value = start_value * 2 ** (dx / 100.0)
        else:
            value = max(3 if name == "Sides" else 1, start_value + dx // (12 if name == "Sides" else 4))
        if uv_tube.get_input(mod, name) != value:
            uv_tube.set_input(mod, name, value)
            tube.update_tag()
    elif start_value is not None:
        rb = context.scene.livinglacquer_rebuild
        rb.tri_budget = max(1000, int(round(start_value * 2 ** ((x - start_x) / 100.0) / 1000.0)) * 1000)


def _slider_start(context, action):
    """What a drag on the slider starts from."""
    if action in TUBE_SLIDERS:
        return _tube_value(context, action[5:])
    rb = context.scene.livinglacquer_rebuild
    return rb.cage if action == "cage" else rb.tri_budget


def _tube_value(context, name):
    tube = uv_tube.open_tube(context)
    if tube is None:
        return None
    return uv_tube.seam_side(tube) if name == "Seam" else uv_tube.get_input(uv_tube.modifier(tube), name)


def _press_tube(context, action):
    tube = uv_tube.open_tube(context)
    if tube is None:
        return
    if action in TUBE_SWITCHES:
        mod = uv_tube.modifier(tube)
        if mod is not None:
            uv_tube.set_input(mod, action[5:], not uv_tube.get_input(mod, action[5:]))
            tube.update_tag()
    elif action == "tube_bezier":
        uv_tube.set_bezier(context, tube, not uv_tube.is_bezier(tube))
    elif action == "tube_pick":
        bpy.ops.livinglacquer.uv_tube_seam_pick("INVOKE_DEFAULT")
    elif action in {"tube_move", "tube_shape"}:
        uv_tube.set_mode(context, tube, "OBJECT" if action == "tube_move" else "EDIT")
    else:
        bpy.ops.livinglacquer.uv_tube_finish(action="CONFIRM" if action == "tube_confirm" else "CANCEL")


def press_button(context, action):
    rb = context.scene.livinglacquer_rebuild
    if action == "sec:" + TUBE:
        pass
    elif action.startswith(("tube:", "tube_")):
        _press_tube(context, action)
    elif action.startswith("sec:"):
        before = sections_height(context)
        i = SECTIONS.index(action[4:])
        rb.panel_open[i] = not rb.panel_open[i]
        _size[1] += sections_height(context) - before    # the grids keep their size
    elif action.startswith("col:"):
        bpy.ops.livinglacquer.toggle_collection(name=action[4:])
    elif action.startswith("mesh:"):
        poly_cut.switch_to(context, action[5:])
    elif action.startswith("pref:"):
        p = prefs.get()
        if p is not None:
            setattr(p, action[5:], not getattr(p, action[5:]))
    elif action in {"ov_overlays", "ov_faces", "ov_wire"}:
        ov = _overlay(context)
        if ov is not None:
            prop = {"ov_overlays": "show_overlays", "ov_faces": "show_face_orientation", "ov_wire": "show_wireframes"}[action]
            setattr(ov, prop, not getattr(ov, prop))
    elif action in OPS:
        op = _op(action)
        if op.poll():
            op("INVOKE_DEFAULT")
    elif action in {"FOCUS", "LOCK", "FREE"}:
        rb.focus = action
    elif action == "soft":
        rb.soft = not rb.soft
    elif action == "flat":
        rb.flat = not rb.flat
    elif action == "pin":
        if bpy.ops.livinglacquer.rebuild_pin.poll():
            bpy.ops.livinglacquer.rebuild_pin()
    elif action == "solo":
        if rb.target is not None:
            bpy.ops.livinglacquer.rebuild_solo()
    elif action in {"prev", "next"}:
        bpy.ops.livinglacquer.rebuild_photo_step(direction=-1 if action == "prev" else 1)
    elif tools_ready(rb, context):
        if action == "brush":
            bpy.ops.livinglacquer.rebuild_brush()
        elif action == "erase":
            bpy.ops.livinglacquer.rebuild_mask_brush()
        elif action == "clear_mask":
            bpy.ops.livinglacquer.rebuild_clear_mask("INVOKE_DEFAULT")
        elif rb.photo in core.cameras():
            bpy.ops.livinglacquer.rebuild_flood()


# ---------------------------------------------------------------- drawing

def _batch(sh, x0, y0, x1, y1, tex_coords=False):
    """The quad's batch, made once for a position (a panel moved or scrolled makes new ones)."""
    key = (tex_coords, x0, y0, x1, y1)
    b = _batches.get(key)
    if b is None:
        if len(_batches) > MAX_BATCHES:
            _batches.clear()
        data = {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))}
        if tex_coords:
            data["texCoord"] = ((0, 0), (1, 0), (1, 1), (0, 1))
        b = _batches[key] = batch_for_shader(sh, "TRI_FAN", data)
    return b


def _rect(x0, y0, x1, y1, color):
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    sh.uniform_float("color", color)
    _batch(sh, x0, y0, x1, y1).draw(sh)


def _frame(x0, y0, x1, y1, color, w=2):
    _rect(x0, y0, x1, y0 + w, color)
    _rect(x0, y1 - w, x1, y1, color)
    _rect(x0, y0, x0 + w, y1, color)
    _rect(x1 - w, y0, x1, y1, color)


def _thumb(tex, x, y, s, alpha=1.0):
    sh = gpu.shader.from_builtin("IMAGE_COLOR")
    sh.uniform_sampler("image", tex)
    sh.uniform_float("color", (1, 1, 1, alpha))
    _batch(sh, x, y, x + s, y + s, True).draw(sh)


def _text(text, x, y, size, color=(0.9, 0.9, 0.9, 1.0)):
    blf.size(0, size)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, text)


def _centred(text, rect, size, color=(0.9, 0.9, 0.9, 1.0)):
    blf.size(0, size)
    w, h = blf.dimensions(0, text)
    _text(text, (rect[0] + rect[2] - w) / 2, (rect[1] + rect[3] - h) / 2, size, color)


def _icon(name, x, y, s, color):
    """A button's icon in the s x s square at x, y: its PNG, or its shape."""
    tex = panel_icons.texture(name)
    if tex is not None:
        _thumb(tex, x, y, s, color[3] if color[0] > 0.6 else 0.45)
        return
    tris = panel_icons.SHAPES.get(name)
    if tris is None:
        return
    key = ("icon", name, x, y, s)
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    b = _batches.get(key)
    if b is None:
        k = s / 16
        b = _batches[key] = batch_for_shader(
            sh, "TRIS", {"pos": [(x + px * k, y + py * k) for tri in tris for px, py in tri]})
    sh.uniform_float("color", color)
    b.draw(sh)


def _button_content(action, rect, text, size, ui, color):
    """Icon and label centred together; the label stays out when it does not fit. < > have only the icon."""
    x0, y0, x1, y1 = rect
    s = int(ICON_PX * ui)
    gap = int(4 * ui)
    if action in {"prev", "next"}:
        _icon(action, int((x0 + x1 - s) / 2), int((y0 + y1 - s) / 2), s, color)
        return
    if action not in panel_icons.SHAPES and action not in panel_icons.PNGS:
        _centred(text, rect, size, color)
        return
    blf.size(0, size)
    tw, th = blf.dimensions(0, text)
    if s + gap + tw + 2 * gap > x1 - x0:
        _icon(action, int((x0 + x1 - s) / 2), int((y0 + y1 - s) / 2), s, color)
        return
    left = int((x0 + x1 - s - gap - tw) / 2)
    _icon(action, left, int((y0 + y1 - s) / 2), s, color)
    _text(text, left + s + gap, (y0 + y1 - th) / 2, size, color)


def _draw_frame_hints(panel, ui):
    """Corner brackets and three dots on the middle of each side: drag these to resize."""
    x0, y0, x1, y1 = panel
    n = int(HINT_CORNER * ui)
    t = max(2, int(2 * ui))
    for cx, sx in ((x0, 1), (x1, -1)):
        for cy, sy in ((y0, 1), (y1, -1)):
            xa, xb = sorted((cx, cx + sx * n))
            ya, yb = sorted((cy, cy + sy * n))
            _rect(xa, min(cy, cy + sy * t), xb, max(cy, cy + sy * t), HINT)
            _rect(min(cx, cx + sx * t), ya, max(cx, cx + sx * t), yb, HINT)
    d = max(2, int(2 * ui))             # the dot's size
    gap = int(6 * ui)
    inset = int(2 * ui)
    midx, midy = (x0 + x1) // 2, (y0 + y1) // 2
    for i in (-1, 0, 1):
        for x in (x0 + inset, x1 - inset - d):
            _rect(x, midy + i * gap, x + d, midy + i * gap + d, HINT)
        for y in (y0 + inset, y1 - inset - d):
            _rect(midx + i * gap, y, midx + i * gap + d, y + d, HINT)


def _draw_section_header(rb, name, rect, size, ui):
    _rect(rect[0], rect[1] + 1, rect[2], rect[3] - 1, (0.17, 0.17, 0.17, 1.0))
    s = int(12 * ui)
    y = int((rect[1] + rect[3] - s) / 2)
    color = (0.85, 0.85, 0.85, 1.0)
    _icon("open" if _section_open(rb, name) else "next", rect[0] + int(3 * ui), y, s, color)
    _text(name, rect[0] + s + int(7 * ui), y + int(1 * ui), size, color)


def _draw_opacity(context, rect, size):
    ov = _overlay(context)
    if ov is None:
        return
    x = rect[0] + 1 + (rect[2] - rect[0] - 2) * ov.wireframe_opacity
    _rect(rect[0] + 1, rect[1] + 1, x, rect[3] - 1, BTN_ON)
    _centred(f"{ov.wireframe_opacity:.2f}", rect, size)


def _draw_tube_value(context, action, rect, size):
    value = _tube_value(context, action[5:])
    if value is not None:
        _centred(f"{action[5:]} {value:.4f}" if action == "tube:Radius" else f"{action[5:]} {value}", rect, size)


def _button_on(action, rb, context):
    if action in TUBE_SWITCHES:
        return bool(_tube_value(context, action[5:]))
    if action == "tube_bezier":
        return uv_tube.is_bezier(uv_tube.open_tube(context))
    if action == "tube_move":
        return context.mode == "OBJECT"
    if action == "tube_shape":
        return context.mode == "EDIT_CURVE"
    if action.startswith("mesh:"):
        return rb.edit_mesh == action[5:]
    if action.startswith("pref:"):
        p = prefs.get()
        return p is not None and getattr(p, action[5:])
    if action in {"ov_overlays", "ov_faces", "ov_wire"}:
        ov = _overlay(context)
        return ov is not None and getattr(ov, {"ov_overlays": "show_overlays", "ov_faces": "show_face_orientation",
                                               "ov_wire": "show_wireframes"}[action])
    if action.startswith("col:"):
        lc = viewbar._layer(context.view_layer, action[4:])
        return lc is not None and viewbar._shown(lc)
    if action in {"FOCUS", "LOCK", "FREE"}:
        return rb.focus == action
    if action == "soft":
        return rb.soft
    if action == "flat":
        return rb.flat
    if action == "pin":
        return paint.has_pin(core.cameras().get(rb.photo))
    if action == "solo":
        return paint.is_solo(context)
    if action == "brush":
        return paint.painting(context) and not paint.masking(context)
    if action == "erase":
        return paint.masking(context)
    return False


def _later():
    _waiting["on"] = False
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return None


def _draw_cells(cells, box, cams, rb, kind, ui, budget):
    x0, y0, x1, y1 = box
    gpu.state.scissor_test_set(True)
    gpu.state.scissor_set(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
    missing = False
    for name, x, y, s in cells:
        if y + s < y0 or y > y1:
            continue
        tex = thumbs.texture(core.photo_image(cams[name]), budget)
        dragged = DRAG["moved"] and DRAG["id"] == name and DRAG["kind"] == kind
        if tex is None:
            missing = True
            _rect(x, y, x + s, y + s, (0.2, 0.2, 0.2, 1.0))
        else:
            _thumb(tex, x, y, s, 0.3 if dragged else 1.0)
        if paint.has_pin(cams[name]):
            m = max(4, s // 8)
            _rect(x + s - m, y + s - m, x + s, y + s, TARGET)
        if name == rb.photo:
            _frame(x, y, x + s, y + s, CURRENT)
        if DRAG["moved"] and DRAG["over"] == (kind, name) and not dragged:
            _frame(x, y, x + s, y + s, TARGET)
    gpu.state.scissor_test_set(False)
    return missing


def _draw():
    context = bpy.context
    region = context.region
    if region is None or not active(context):
        return
    poly_cut.follow_active()
    rb = context.scene.livinglacquer_rebuild
    cams = core.cameras()
    ui = context.preferences.system.ui_scale
    lay = layout(context, region)
    ready = tools_ready(rb, context)
    gpu.state.blend_set("ALPHA")
    _rect(*lay["panel"], BACK)
    # Favorites
    blue, yellow, trash = lay["blue"], lay["yellow"], lay["trash"]
    _rect(*blue, BOX)
    _rect(*yellow, BOX)
    size = int(12 * ui)
    for action, rect, text in lay["buttons"]:
        grey = (action in {"brush", "fill", "erase", "clear_mask"} and not ready) \
            or (action == "fill" and rb.photo not in cams)
        if action in OPS and not _op(action).poll():
            grey = True
        if action == "mesh:FINAL" and core.final_mesh(rb) is None:
            grey = True
        if action == "tube:Smooth" and uv_tube.is_bezier(uv_tube.open_tube(context)):
            grey = True
        if action.startswith("sec:"):
            _draw_section_header(rb, action[4:], rect, size, ui)
            continue
        _rect(rect[0] + 1, rect[1] + 1, rect[2] - 1, rect[3] - 1,
              BTN_OFF if grey else BTN_ON if _button_on(action, rb, context) else BTN)
        if action == "wire_opacity":
            _draw_opacity(context, rect, size)
            continue
        if action in TUBE_SLIDERS:
            _draw_tube_value(context, action, rect, size)
            continue
        if action == "cage":
            _centred(f"Cage {rb.cage * 1000:.1f} mm", rect, size)
            continue
        _button_content(action, rect, text, size, ui, (0.5, 0.5, 0.5, 1.0) if grey else (0.95, 0.95, 0.95, 1.0))
    for text, x, y, red in lay["lines"]:
        _text(text, x, y, int(11 * ui), (1.0, 0.5, 0.45, 1.0) if red else (0.7, 0.7, 0.7, 1.0))
    nx0, ny0, nx1, ny1 = lay["name"]
    if nx1 > nx0:
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(nx0), int(ny0), int(nx1 - nx0), int(ny1 - ny0))
        _text(rb.photo or "No photo", nx0, ny0 + (ny1 - ny0 - size) / 2, size, (0.8, 0.8, 0.8, 1.0))
        gpu.state.scissor_test_set(False)
    budget = [LOAD_PER_DRAW]
    missing = _draw_cells(lay["fav"], lay["fav_area"], cams, rb, "fav", ui, budget)
    missing |= _draw_cells(lay["all"], yellow, cams, rb, "all", ui, budget)
    if not lay["fav"]:
        _centred("Favorites: drag a photo up here", lay["fav_area"], size, (0.6, 0.6, 0.6, 1.0))
    # the trash: a bin drawn from rectangles
    over_trash = DRAG["moved"] and DRAG["kind"] == "fav" and DRAG["over"] == ("trash", "")
    _rect(*trash, DELETE if over_trash else BTN_OFF)
    tw = trash[2] - trash[0]
    ink = (0.85, 0.85, 0.85, 1.0)
    _rect(trash[0] + tw * 0.25, trash[3] - tw * 0.3, trash[2] - tw * 0.25, trash[3] - tw * 0.24, ink)
    _rect(trash[0] + tw * 0.42, trash[3] - tw * 0.24, trash[2] - tw * 0.42, trash[3] - tw * 0.18, ink)
    _frame(trash[0] + tw * 0.31, trash[1] + tw * 0.2, trash[2] - tw * 0.31, trash[3] - tw * 0.33, ink, max(1, int(ui * 2)))
    if DRAG["moved"] and DRAG["over"] == ("blue", "") and DRAG["kind"] == "all":
        _frame(*blue, TARGET)
    if paint.stamping(context):
        status = STAMP_HINT
    elif rb.focus == "FREE" and ready:
        status = "Free: press Brush to see the photo over the view"
    elif ready:
        status = "Click: load  ·  Drag up: pin  ·  Drag to the bin: unpin"
    elif rb.target is None:
        status = "Tools need a rebuilt object: step 5a"
    else:
        status = f"Tools need faces on {rb.target.name}, unlocked"
    _text(status, *lay["status"], int(11 * ui), (0.6, 0.6, 0.6, 1.0))
    _draw_frame_hints(lay["panel"], ui)
    if DRAG["moved"] and DRAG["id"] in cams:
        s = int(ALL_PX * ui)
        tex = thumbs.texture(core.photo_image(cams[DRAG["id"]]), [1])
        if tex is not None:
            _thumb(tex, DRAG["x"] - s / 2, DRAG["y"] - s / 2, s)
    gpu.state.blend_set("NONE")
    if missing and not _waiting["on"]:      # read the next ones on the next redraw
        _waiting["on"] = True
        bpy.app.timers.register(_later, first_interval=0.2)


def _draw_stamp():
    """Free's photo over the view, under the panel: Blender's own stencil overlay would draw over the panel."""
    context = bpy.context
    if context.region is None or not paint.stamping(context):
        return
    corners = paint.stencil_corners()
    photo = bpy.data.brushes[paint.BRUSH].texture.image if corners else None
    if photo is None or not photo.size[0]:
        return
    sh = gpu.shader.from_builtin("IMAGE_COLOR")
    sh.uniform_sampler("image", gpu.texture.from_image(photo))
    sh.uniform_float("color", (1, 1, 1, STAMP_ALPHA))
    gpu.state.blend_set("ALPHA")
    batch_for_shader(sh, "TRI_FAN", {"pos": corners, "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))}).draw(sh)
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------- the mouse and Shift+Q

def _poll(context):
    return context.area is not None and context.area.type == "VIEW_3D" and context.region is not None \
        and context.region.type == "WINDOW"


class LIVINGLACQUER_OT_RebuildPhotoPanel(bpy.types.Operator):
    """Show / hide the floating photo panel"""
    bl_idname = "livinglacquer.rebuild_photo_panel"
    bl_label = "Photo Panel"

    def invoke(self, context, event):
        rb = context.scene.livinglacquer_rebuild
        region = context.region
        if not rb.show_photos and region is not None and region.type == "WINDOW":     # opens under the mouse
            x0, y0, x1, y1 = layout(context, region)["panel"]
            _pos[0] = event.mouse_region_x - (x1 - x0) // 2
            _pos[1] = event.mouse_region_y + int(ROW_NUDGE * context.preferences.system.ui_scale)
        return self.execute(context)

    def execute(self, context):
        rb = context.scene.livinglacquer_rebuild
        rb.show_photos = not rb.show_photos
        thumbs.forget()                     # photos turned or undistorted since show up new
        if rb.show_photos and not core.cameras():
            self.report({"WARNING"}, "No scan cameras yet: Build Scene first")
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildPanelPress(bpy.types.Operator):
    """Photo panel: a press on it. Off the panel the click goes on as always"""
    bl_idname = "livinglacquer.rebuild_panel_press"
    bl_label = "Photo Panel Press"

    @classmethod
    def poll(cls, context):
        return _poll(context) and active(context)

    def invoke(self, context, event):
        mx, my = event.mouse_region_x, event.mouse_region_y
        where = hit(context, context.region, mx, my)
        if where is None:
            return {"PASS_THROUGH"}
        kind, name = where
        DRAG.update(kind=kind, id=name, x=mx, y=my, moved=False, over=None)
        self._budget = _slider_start(context, name) if kind == "button" else None
        self._rect = None
        if kind == "button" and name in SLIDERS:
            self._rect = next(r for a, r, _t in layout(context, context.region)["buttons"] if a == name)
            slide(context, name, mx, self._rect, mx, self._budget)
        self._start = (mx, my)
        x0, y0, x1, y1 = layout(context, context.region)["panel"]
        _pos[0], _pos[1], _size[0], _size[1] = x0, y1, x1 - x0, y1 - y0
        self._pos = list(_pos)
        self._size = list(_size)
        if kind == "edge":
            context.window.cursor_modal_set({"L": "MOVE_X", "R": "MOVE_X", "T": "MOVE_Y", "B": "MOVE_Y"}.get(name, "SCROLL_XY"))
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        area, region = context.area, context.region
        if event.type == "MOUSEMOVE":
            mx, my = event.mouse_region_x, event.mouse_region_y
            DRAG.update(x=mx, y=my)
            if abs(mx - self._start[0]) + abs(my - self._start[1]) > DRAG_PX:
                DRAG["moved"] = True
            if DRAG["kind"] in {"panel", "blue", "yellow"}:      # empty part: the panel moves
                _pos[0] = self._pos[0] + mx - self._start[0]
                _pos[1] = self._pos[1] + my - self._start[1]
            elif DRAG["kind"] == "button" and DRAG["id"] in SLIDERS:
                slide(context, DRAG["id"], mx, self._rect, self._start[0], self._budget)
            elif DRAG["kind"] == "edge":
                self._resize(context, region, mx - self._start[0], my - self._start[1])
            else:
                DRAG["over"] = hit(context, region, mx, my)
            area.tag_redraw()
        elif event.type == "LEFTMOUSE" and event.value == "RELEASE":
            kind, name, moved, over = DRAG["kind"], DRAG["id"], DRAG["moved"], hit(context, region, DRAG["x"], DRAG["y"])
            self._end(area)
            rb = context.scene.livinglacquer_rebuild
            if tuple(rb.panel_rect) != (_pos[0], _pos[1], _size[0], _size[1]):
                rb.panel_rect = (_pos[0], _pos[1], _size[0], _size[1])
            if kind == "button":
                if over == ("button", name) and name not in SLIDERS:
                    press_button(context, name)
                    rb.panel_rect = (_pos[0], _pos[1], _size[0], _size[1])
            elif kind in {"fav", "all"}:
                if moved:
                    drop(context.scene.livinglacquer_rebuild, kind, name, over)
                else:
                    bpy.ops.livinglacquer.rebuild_photo(name=name)
            return {"FINISHED"}
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            _pos[0], _pos[1] = self._pos
            _size[0], _size[1] = self._size
            self._end(area)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def _resize(self, context, region, dx, dy):
        """The dragged sides move, the opposite ones stay; it stops at the smallest size and the viewport."""
        ui = context.preferences.system.ui_scale
        sx, st = self._pos
        sw, sh = self._size
        min_w, min_h = int(MIN_WIDTH * ui), int(MIN_HEIGHT * ui)
        sides = DRAG["id"]
        if "L" in sides:
            w = max(min_w, min(sw - dx, sx + sw))
            _size[0], _pos[0] = w, sx + sw - w
        elif "R" in sides:
            _size[0] = max(min_w, min(sw + dx, region.width - sx))
        if "T" in sides:
            h = max(min_h, min(sh + dy, region.height - (st - sh)))
            _size[1], _pos[1] = h, st - sh + h
        elif "B" in sides:
            _size[1] = max(min_h, min(sh - dy, st))

    @staticmethod
    def _end(area):
        DRAG.update(kind="", id="", moved=False, over=None)
        bpy.context.window.cursor_modal_restore()
        area.tag_redraw()


class LIVINGLACQUER_OT_RebuildPanelScroll(bpy.types.Operator):
    """Photo panel: the wheel scrolls the grid under the mouse. Off the panel it zooms as always"""
    bl_idname = "livinglacquer.rebuild_panel_scroll"
    bl_label = "Scroll Photo Panel"
    direction: bpy.props.IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        return _poll(context) and active(context)

    def invoke(self, context, event):
        where = hit(context, context.region, event.mouse_region_x, event.mouse_region_y)
        if where is None:
            return {"PASS_THROUGH"}
        key = {"fav": "fav", "blue": "fav", "all": "all", "yellow": "all"}.get(where[0])
        if key:
            step = (FAV_PX if key == "fav" else ALL_PX) * context.preferences.system.ui_scale
            _scroll[key] = max(0, _scroll[key] + int(self.direction * step))
            context.area.tag_redraw()
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_RebuildPhotoPanel, LIVINGLACQUER_OT_RebuildPanelPress, LIVINGLACQUER_OT_RebuildPanelScroll)


def register():
    global _handler, _stamp_handler
    for c in classes:
        bpy.utils.register_class(c)
    _stamp_handler = bpy.types.SpaceView3D.draw_handler_add(_draw_stamp, (), "WINDOW", "POST_PIXEL")
    _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:                          # background mode
        return
    # the mode keymaps too: Texture Paint would take the press for a stroke
    for name in ("3D View", "Image Paint", "Object Mode", "Mesh", "Curve", "Sculpt", "Weight Paint", "Vertex Paint"):
        km = kc.keymaps.new(name=name, space_type="VIEW_3D" if name == "3D View" else "EMPTY")
        _keymaps.append((km, km.keymap_items.new(LIVINGLACQUER_OT_RebuildPanelPress.bl_idname,
                                                 "LEFTMOUSE", "PRESS", head=True)))
        _keymaps.append((km, km.keymap_items.new(LIVINGLACQUER_OT_RebuildPhotoPanel.bl_idname,
                                                 "Q", "PRESS", shift=True, head=True)))
        for wheel, direction in (("WHEELDOWNMOUSE", 1), ("WHEELUPMOUSE", -1)):
            kmi = km.keymap_items.new(LIVINGLACQUER_OT_RebuildPanelScroll.bl_idname, wheel, "PRESS", head=True)
            kmi.properties.direction = direction
            _keymaps.append((km, kmi))


def unregister():
    global _handler, _stamp_handler
    _batches.clear()
    panel_icons.clear()
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
        _handler = None
    if _stamp_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_stamp_handler, "WINDOW")
        _stamp_handler = None
    if bpy.app.timers.is_registered(_later):
        bpy.app.timers.unregister(_later)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
