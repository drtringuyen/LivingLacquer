"""Edit ALB_: one session in the Image Editor with Lasso, Fill (inpaint), Patch, Move and Liquify, switched by a key
like Photoshop's tools. It edits ALB_ itself and saves over its file; there is no _inpaint copy. To paint on from
the result, send ALB_ over BAo_ (5c).

    L  Lasso    click points, double click (or Enter) closes. Shift: add, Alt: subtract, neither: a new selection
    F  Fill     the selection rebuilt from the pixels around it (inpaint_fill.py, from MultiCamProject)
    P  Patch    drag to another area: the selection takes its pixels, colour matched to the edge
    G  Move     drag: the selection's pixels move, the place they left is filled
    W  Liquify  drag: push the pixels. [ ] the brush size

    Ctrl+Z  undo    Ctrl+S  save    Esc  drop the outline / the selection, then leave (unsaved edits stay in memory)
    Enter  save and leave"""
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import core, inpaint_fill as ipf
from .poly_cut import inside_polygon

UNDO_STEPS = 20
REDRAW_EVERY = 0.1          # seconds between image updates during a Liquify stroke (a 4K update takes a moment)
COLORS = {"ADD": (0.3, 0.9, 0.4, 1.0), "SUB": (1.0, 0.35, 0.3, 1.0), "DRAG": (1.0, 0.75, 0.2, 1.0)}
NAV = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "HOME", "NUMPAD_PERIOD", "TRACKPADPAN", "TRACKPADZOOM"}


class Canvas:
    """The pixels being edited, with undo. Pure numpy, rows bottom-up as Blender gives them."""

    def __init__(self, buf):
        self.buf = buf
        self.h, self.w = buf.shape[:2]
        self.sel = np.zeros((self.h, self.w), bool)
        self.undo_stack = []

    def _push(self, y0, y1, x0, x1):
        self.undo_stack.append((y0, y1, x0, x1, self.buf[y0:y1, x0:x1].copy()))
        del self.undo_stack[:-UNDO_STEPS]

    def undo(self):
        """Back one edit. Returns False when there is none."""
        if not self.undo_stack:
            return False
        y0, y1, x0, x1, px = self.undo_stack.pop()
        self.buf[y0:y1, x0:x1] = px
        return True

    def select(self, polygon, how):
        """polygon in pixels; how: NEW, ADD or SUB."""
        pts = np.asarray(polygon, np.float64)
        x0, y0 = np.maximum(np.floor(pts.min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(pts.max(axis=0)).astype(int) + 1, (self.w, self.h))
        if how == "NEW":
            self.sel[:] = False
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1]
        grid = np.column_stack((xs.ravel() + 0.5, ys.ravel() + 0.5))
        inside = inside_polygon(grid, [tuple(p) for p in pts]).reshape(ys.shape)
        if how == "SUB":
            self.sel[y0:y1, x0:x1] &= ~inside
        else:
            self.sel[y0:y1, x0:x1] |= inside

    def _sel_box(self, margin):
        """(y0, y1, x0, x1) around the selection, with margin; None when there is none."""
        ys, xs = np.nonzero(self.sel)
        if not len(ys):
            return None
        return (max(ys.min() - margin, 0), min(ys.max() + margin + 1, self.h),
                max(xs.min() - margin, 0), min(xs.max() + margin + 1, self.w))

    def _valid(self, y0, y1, x0, x1):
        """Painted pixels: the black outside the UV islands must never bleed in."""
        return self.buf[y0:y1, x0:x1, :3].sum(axis=2) > 0.0

    def fill(self, margin=64):
        """The selection rebuilt from the pixels around it. Returns the pixels changed."""
        box = self._sel_box(margin)
        if box is None:
            return 0
        y0, y1, x0, x1 = box
        self._push(y0, y1, x0, x1)
        out, used = ipf.fill(self.buf[y0:y1, x0:x1], self.sel[y0:y1, x0:x1], valid=self._valid(y0, y1, x0, x1))
        self.buf[y0:y1, x0:x1] = out
        return int(used.sum())

    def patch(self, dx, dy, margin=4):
        """The selection takes the pixels at (dx, dy) from it, colour matched to its edge. Returns the pixels used."""
        box = self._sel_box(margin)
        if box is None:
            return 0
        y0, y1, x0, x1 = box
        dx, dy = int(round(dx)), int(round(dy))
        dx = max(-x0, min(dx, self.w - x1))
        dy = max(-y0, min(dy, self.h - y1))
        self._push(y0, y1, x0, x1)
        out, used = ipf.patch(self.buf[y0:y1, x0:x1], self.buf[y0 + dy:y1 + dy, x0 + dx:x1 + dx],
                              self.sel[y0:y1, x0:x1])
        self.buf[y0:y1, x0:x1] = out
        self.sel[:] = False
        return int(np.sum(used)) if np.ndim(used) else int(used)

    def move(self, dx, dy, margin=64):
        """The selection's pixels go (dx, dy); the place they left is filled. The selection follows them."""
        box = self._sel_box(margin)
        if box is None:
            return 0
        dx, dy = int(round(dx)), int(round(dy))
        ys, xs = np.nonzero(self.sel)
        ty, tx = ys + dy, xs + dx
        keep = (ty >= 0) & (ty < self.h) & (tx >= 0) & (tx < self.w)
        y0 = max(min(box[0], ty[keep].min() if keep.any() else box[0]), 0)
        y1 = min(max(box[1], ty[keep].max() + 1 if keep.any() else box[1]), self.h)
        x0 = max(min(box[2], tx[keep].min() if keep.any() else box[2]), 0)
        x1 = min(max(box[3], tx[keep].max() + 1 if keep.any() else box[3]), self.w)
        self._push(y0, y1, x0, x1)
        moved = self.buf[ys[keep], xs[keep]].copy()
        out, _used = ipf.fill(self.buf[y0:y1, x0:x1], self.sel[y0:y1, x0:x1], valid=self._valid(y0, y1, x0, x1))
        self.buf[y0:y1, x0:x1] = out
        self.buf[ty[keep], tx[keep]] = moved
        self.sel[:] = False
        self.sel[ty[keep], tx[keep]] = True
        return int(keep.sum())

    def begin_stroke(self):
        self._stroke = self.buf.copy()
        self._box = None

    def push(self, cx, cy, radius, ddx, ddy, strength=0.8):
        """Liquify: the pixels under the brush pushed along (ddx, ddy), bilinear, smooth falloff."""
        r = max(1, int(radius))
        x0, x1 = max(int(cx) - r, 0), min(int(cx) + r + 1, self.w)
        y0, y1 = max(int(cy) - r, 0), min(int(cy) + r + 1, self.h)
        if x1 <= x0 or y1 <= y0:
            return
        ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        d2 = ((xs - cx) ** 2 + (ys - cy) ** 2) / float(r * r)
        wgt = np.clip(1.0 - d2, 0.0, 1.0) ** 2 * strength
        sx = np.clip(xs - wgt * ddx, 0, self.w - 1.001)
        sy = np.clip(ys - wgt * ddy, 0, self.h - 1.001)
        ix, iy = sx.astype(int), sy.astype(int)
        fx, fy = (sx - ix)[..., None], (sy - iy)[..., None]
        b = self.buf
        out = (b[iy, ix] * (1 - fx) * (1 - fy) + b[iy, ix + 1] * fx * (1 - fy)
               + b[iy + 1, ix] * (1 - fx) * fy + b[iy + 1, ix + 1] * fx * fy)
        b[y0:y1, x0:x1] = out
        box = self._box
        self._box = (y0, y1, x0, x1) if box is None else (min(box[0], y0), max(box[1], y1), min(box[2], x0), max(box[3], x1))

    def end_stroke(self):
        """The whole stroke as one undo step."""
        if self._box is not None:
            y0, y1, x0, x1 = self._box
            self.undo_stack.append((y0, y1, x0, x1, self._stroke[y0:y1, x0:x1].copy()))
            del self.undo_stack[:-UNDO_STEPS]
        self._stroke = None


def _image_editor(context):
    """(window, area, region) of an Image Editor: the one in use, else a new window with one."""
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "IMAGE_EDITOR":
                return win, area, next(r for r in area.regions if r.type == "WINDOW")
    bpy.ops.wm.window_new()
    win = context.window_manager.windows[-1]
    area = max(win.screen.areas, key=lambda a: a.width * a.height)
    area.ui_type = "IMAGE_EDITOR"
    return win, area, next(r for r in area.regions if r.type == "WINDOW")


def _albedo(context):
    rb = context.scene.livinglacquer_rebuild
    return rb.target, core.image(core.ALBEDO, rb.target)


class LIVINGLACQUER_OT_AlbEdit(bpy.types.Operator):
    """Edit ALB_ in the Image Editor: Lasso, Fill, Patch, Move and Liquify in one session, saved over ALB_"""
    bl_idname = "livinglacquer.alb_edit"
    bl_label = "Edit ALB_"

    @classmethod
    def poll(cls, context):
        ob, img = _albedo(context)
        return ob is not None and not core.locked(ob) and core.has_file(img)

    def invoke(self, context, event):
        if context.area is None or context.area.type != "IMAGE_EDITOR":
            win, area, region = _image_editor(context)
            with context.temp_override(window=win, area=area, region=region):
                return bpy.ops.livinglacquer.alb_edit("INVOKE_DEFAULT")
        _ob, img = _albedo(context)
        self._area = context.area
        self._region = context.region
        self._area.spaces.active.image = img
        self._image = img.name
        w, h = img.size
        buf = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(buf)
        self._canvas = Canvas(buf.reshape(h, w, 4))
        self._tool = "LASSO"
        self._points = []           # the outline being drawn, in pixels
        self._polys = []            # the selection's outlines: [(pixels, ADD / SUB)]
        self._grab = None           # patch / move / liquify: the press's pixel position
        self._last = None
        self._last_update = 0.0
        self._radius = max(8, w // 40)
        self._mouse = (0, 0)
        self._handle = bpy.types.SpaceImageEditor.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        self._status(context)
        context.window_manager.modal_handler_add(self)
        self._area.tag_redraw()
        return {"RUNNING_MODAL"}

    # ------------------------------------------------ view

    def _to_px(self, rx, ry):
        c = self._canvas
        u, v = self._region.view2d.region_to_view(rx, ry)
        return u * c.w, v * c.h

    def _to_region(self, px, py):
        c = self._canvas
        return self._region.view2d.view_to_region(px / c.w, py / c.h, clip=False)

    def _status(self, context):
        context.workspace.status_text_set(
            f"Edit ALB_: {self._tool}  ·  L Lasso  F Fill  P Patch  G Move  W Liquify  [ ] size  ·  Ctrl+Z undo  "
            "Ctrl+S save  ·  Enter save and leave  ·  Esc leave")

    def _draw(self):
        if bpy.context.region != self._region:
            return
        sh = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        off = (0.0, 0.0)
        if self._grab is not None and self._tool in {"PATCH", "MOVE"}:
            off = (self._mouse[0] - self._grab[0], self._mouse[1] - self._grab[1])
        for pts, how in self._polys:
            sh.uniform_float("color", COLORS[how])
            line = [self._to_region(x, y) for x, y in pts]
            batch_for_shader(sh, "LINE_LOOP", {"pos": line}).draw(sh)
            if off != (0.0, 0.0):
                sh.uniform_float("color", COLORS["DRAG"])
                line = [self._to_region(x + off[0], y + off[1]) for x, y in pts]
                batch_for_shader(sh, "LINE_LOOP", {"pos": line}).draw(sh)
        if self._points:
            sh.uniform_float("color", COLORS["DRAG"])
            line = [self._to_region(x, y) for x, y in self._points + [self._mouse]]
            batch_for_shader(sh, "LINE_STRIP", {"pos": line}).draw(sh)
        if self._tool == "LIQUIFY":
            import math
            sh.uniform_float("color", (1, 1, 1, 0.8))
            ring = [self._to_region(self._mouse[0] + self._radius * math.cos(a / 24 * 2 * math.pi),
                                    self._mouse[1] + self._radius * math.sin(a / 24 * 2 * math.pi)) for a in range(24)]
            batch_for_shader(sh, "LINE_LOOP", {"pos": ring}).draw(sh)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

    # ------------------------------------------------ the image

    def _show(self):
        img = bpy.data.images.get(self._image)
        if img is not None:
            img.pixels.foreach_set(self._canvas.buf.ravel())
            img.update()
        self._area.tag_redraw()

    def _save(self):
        img = bpy.data.images.get(self._image)
        self._show()
        img.save()
        self.report({"INFO"}, f"{img.name} saved")
        from ..project import steps
        steps.refresh()

    def _close_outline(self, event):
        how = "ADD" if event.shift else "SUB" if (event.alt or event.ctrl) else "NEW"
        if len(self._points) >= 3:
            self._canvas.select(self._points, how)
            if how == "NEW":
                self._polys = []
            self._polys.append((self._points, "SUB" if how == "SUB" else "ADD"))
        self._points = []

    def _end(self, context):
        bpy.types.SpaceImageEditor.draw_handler_remove(self._handle, "WINDOW")
        context.workspace.status_text_set(None)
        self._area.tag_redraw()

    # ------------------------------------------------ events

    def modal(self, context, event):
        import time
        self._area.tag_redraw()
        if bpy.data.images.get(self._image) is None:
            self._end(context)
            return {"CANCELLED"}
        mx, my = event.mouse_x - self._region.x, event.mouse_y - self._region.y
        over = 0 <= mx < self._region.width and 0 <= my < self._region.height
        if event.type in NAV:
            return {"PASS_THROUGH"}
        if event.type == "MOUSEMOVE":
            self._mouse = self._to_px(mx, my)
            if self._tool == "LIQUIFY" and self._last is not None:
                self._canvas.push(self._last[0], self._last[1], self._radius,
                                  self._mouse[0] - self._last[0], self._mouse[1] - self._last[1])
                self._last = self._mouse
                if time.monotonic() - self._last_update > REDRAW_EVERY:
                    self._show()
                    self._last_update = time.monotonic()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE":
            if event.value == "RELEASE":
                return self._release()
            if event.value == "DOUBLE_CLICK" and self._tool == "LASSO":
                self._close_outline(event)
                return {"RUNNING_MODAL"}
            if event.value == "PRESS":
                if not over:
                    return {"PASS_THROUGH"}
                p = self._to_px(mx, my)
                self._mouse = p
                if self._tool == "LASSO":
                    self._points.append(p)
                elif self._tool == "LIQUIFY":
                    self._canvas.begin_stroke()
                    self._last = p
                else:
                    self._grab = p
            return {"RUNNING_MODAL"}
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        c = self._canvas
        if event.ctrl and event.type == "Z":
            if self._points:
                self._points.pop()
            elif c.undo():
                self._show()
        elif event.ctrl and event.type == "S":
            self._save()
        elif event.type == "L":
            self._set_tool(context, "LASSO")
        elif event.type == "P":
            self._set_tool(context, "PATCH")
        elif event.type == "G":
            self._set_tool(context, "MOVE")
        elif event.type == "W":
            self._set_tool(context, "LIQUIFY")
        elif event.type == "F":
            if c.fill():
                self._polys = []
                c.sel[:] = False
                self._show()
        elif event.type == "LEFT_BRACKET":
            self._radius = max(2, int(self._radius / 1.25))
        elif event.type == "RIGHT_BRACKET":
            self._radius = int(self._radius * 1.25) + 1
        elif event.type in {"RET", "NUMPAD_ENTER"}:
            if len(self._points) >= 3:
                self._close_outline(event)
            else:
                self._save()
                self._end(context)
                return {"FINISHED"}
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            if self._points:
                self._points = []
            elif self._polys:
                self._polys = []
                c.sel[:] = False
            else:
                self._show()
                self._end(context)
                return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _set_tool(self, context, tool):
        self._tool = tool
        self._points = []
        self._status(context)

    def _release(self):
        c = self._canvas
        if self._tool == "LIQUIFY" and self._last is not None:
            c.end_stroke()
            self._last = None
            self._show()
        elif self._grab is not None:
            dx, dy = self._mouse[0] - self._grab[0], self._mouse[1] - self._grab[1]
            self._grab = None
            if abs(dx) + abs(dy) >= 1:
                if self._tool == "PATCH":
                    if c.patch(dx, dy):
                        self._polys = []
                elif c.move(dx, dy):
                    self._polys = [([(x + dx, y + dy) for x, y in pts], how) for pts, how in self._polys]
                self._show()
        return {"RUNNING_MODAL"}


def register():
    bpy.utils.register_class(LIVINGLACQUER_OT_AlbEdit)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_OT_AlbEdit)
