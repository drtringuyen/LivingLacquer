"""Seam Select (Edit Mode), replacing MultiCamProject's Set Faces: only the seam stays. Click around the part
you want; a double click closes the outline and adds those faces to the selection, or takes them out
(A / S). Faces the view does not see stay as they are. Enter marks a seam on the border of the selection and
keeps the tool open for the next part. Backspace drops the last point, right click / Esc drops the outline,
then leaves. The middle mouse and the wheel still move the view."""
import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils.bvhtree import BVHTree

from . import core, uv_tools

COLORS = {"ADD": (0.3, 0.9, 0.4, 1.0), "SUB": (1.0, 0.35, 0.3, 1.0)}
NAVIGATION = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3",
              "NUMPAD_4", "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9", "NUMPAD_PERIOD"}


def inside_polygon(pts, poly):
    """Even-odd test of (n, 2) points in the polygon [(x, y)...]."""
    px, py = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    x0, y0 = poly[-1]
    for x1, y1 in poly:
        cross = ((y1 > py) != (y0 > py)) & (px < (x0 - x1) * (py - y1) / ((y0 - y1) or 1e-12) + x1)
        inside ^= cross
        x0, y0 = x1, y1
    return inside


def faces_in_outline(bm, ob, region, rv3d, poly):
    """The faces whose centre lies in the outline, in front of the view and not behind other faces."""
    bm.faces.ensure_lookup_table()
    if not bm.faces:
        return []
    centres = np.array([f.calc_center_median() for f in bm.faces], np.float64)
    full = np.array(rv3d.perspective_matrix @ ob.matrix_world, np.float64)
    h = centres @ full[:3, :3].T + full[:3, 3]
    w = centres @ full[3, :3] + full[3, 3]
    front = w > 1e-9
    xy = np.zeros((len(centres), 2))
    xy[front, 0] = (h[front, 0] / w[front] + 1) * region.width / 2
    xy[front, 1] = (h[front, 1] / w[front] + 1) * region.height / 2
    chosen = np.nonzero(front & inside_polygon(xy, poly))[0]
    if not len(chosen):
        return []
    tree = BVHTree.FromBMesh(bm)
    inv = ob.matrix_world.inverted()
    view = rv3d.view_matrix.inverted()
    out = []
    for i in chosen:
        f = bm.faces[int(i)]
        c = f.calc_center_median()
        if rv3d.is_perspective:
            eye = inv @ view.translation
            direction = (c - eye).normalized()
            start = eye
        else:
            direction = (inv.to_3x3() @ (view.to_3x3() @ __import__("mathutils").Vector((0, 0, -1)))).normalized()
            start = c - direction * (10 * max(ob.dimensions.length, 1.0))
        hit = tree.ray_cast(start, direction)
        if hit[2] is not None and hit[2] != f.index and (hit[0] - c).length > 1e-4 * max(ob.dimensions.length, 1e-6):
            continue
        out.append(f)
    return out


def apply_outline(ob, region, rv3d, poly, mode):
    """Add the outline's faces to the selection or take them out. Returns how many it touched."""
    bm = bmesh.from_edit_mesh(ob.data)
    faces = faces_in_outline(bm, ob, region, rv3d, poly)
    for f in faces:
        f.select = mode == "ADD"
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)
    return len(faces)


def mark_border(ob):
    """A seam on the border of the selection, then nothing selected. Returns the border's edge count."""
    bm = bmesh.from_edit_mesh(ob.data)
    sel = [f for f in bm.faces if f.select]
    rim = uv_tools.rim(sel)
    for e in rim:
        e.seam = True
    for f in sel:
        f.select = False
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data)
    return len(rim)


class LIVINGLACQUER_OT_RebuildSeamSelect(bpy.types.Operator):
    """Seam Select: click an outline, double click closes it and adds (A) or subtracts (S) those faces, Enter
    marks the seam on the selection's border and stays open. Esc leaves"""
    bl_idname = "livinglacquer.rebuild_seam_select"
    bl_label = "Seam Select"

    @classmethod
    def poll(cls, context):
        ob = context.scene.livinglacquer_rebuild.target
        return ob is not None and ob.type == "MESH" and context.area is not None and context.area.type == "VIEW_3D" \
            and ob.name in context.view_layer.objects

    def invoke(self, context, event):
        rb = context.scene.livinglacquer_rebuild
        ob = rb.target
        area = next(a for a in context.screen.areas if a.type == "VIEW_3D")
        self._area = area
        self._region = next(r for r in area.regions if r.type == "WINDOW")
        if context.active_object != ob or ob.mode != "EDIT":
            if context.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for o in context.selected_objects:
                o.select_set(False)
            ob.hide_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode="EDIT")
        context.tool_settings.mesh_select_mode = (False, False, True)
        self._ob = ob.name
        self._points = []
        self._mode = "ADD"
        self._mouse = (0, 0)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        self._status(context)
        context.window_manager.modal_handler_add(self)
        area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _status(self, context):
        context.workspace.status_text_set(
            f"Seam Select: {'ADD' if self._mode == 'ADD' else 'SUBTRACT'}  ·  click: point  ·  double click: close  ·  "
            "A / S: add / subtract  ·  Enter: seam on the border  ·  Backspace: last point  ·  Esc: leave")

    def _draw(self):
        if bpy.context.region != self._region or not self._points:
            return
        pts = self._points + [self._mouse]
        sh = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        sh.uniform_float("color", COLORS[self._mode])
        batch_for_shader(sh, "LINE_LOOP", {"pos": pts}).draw(sh)
        batch_for_shader(sh, "POINTS", {"pos": self._points}).draw(sh)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

    def _close(self, context):
        ob = bpy.data.objects.get(self._ob)
        if ob is not None and len(self._points) >= 3:
            n = apply_outline(ob, self._region, self._area.spaces.active.region_3d, self._points, self._mode)
            bpy.ops.ed.undo_push(message="Seam Select")
            self.report({"INFO"}, f"{'Added' if self._mode == 'ADD' else 'Took out'} {n} face(s)")
        self._points = []

    def _end(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
        context.workspace.status_text_set(None)
        self._area.tag_redraw()

    def modal(self, context, event):
        ob = bpy.data.objects.get(self._ob)
        if ob is None or ob.mode != "EDIT":
            self._end(context)
            return {"CANCELLED"}
        self._area.tag_redraw()
        if event.type in NAVIGATION or (event.type == "MOUSEMOVE" and event.alt):
            return {"PASS_THROUGH"}
        if event.type == "MOUSEMOVE":
            self._mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y)
            return {"RUNNING_MODAL"}
        mx, my = event.mouse_x - self._region.x, event.mouse_y - self._region.y
        over = 0 <= mx < self._region.width and 0 <= my < self._region.height
        if event.type == "LEFTMOUSE":
            if event.value == "DOUBLE_CLICK":
                self._close(context)
            elif event.value == "PRESS":
                if not over:
                    return {"PASS_THROUGH"}         # the sidebar's buttons still work
                self._points.append((mx, my))
            return {"RUNNING_MODAL"}
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type in {"A", "S"}:
            self._mode = "ADD" if event.type == "A" else "SUB"
            self._status(context)
        elif event.type == "BACK_SPACE":
            if self._points:
                self._points.pop()
        elif event.type in {"RET", "NUMPAD_ENTER"}:
            if len(self._points) >= 3:
                self._close(context)
            n = mark_border(ob)
            bpy.ops.ed.undo_push(message="Seam Select: mark seam")
            self.report({"INFO"}, f"Seam on {n} border edge(s)" if n else "Nothing selected")
        elif event.type in {"ESC", "RIGHTMOUSE"}:
            if self._points:
                self._points = []
            else:
                self._end(context)
                return {"FINISHED"}
        return {"RUNNING_MODAL"}


def register():
    bpy.utils.register_class(LIVINGLACQUER_OT_RebuildSeamSelect)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_OT_RebuildSeamSelect)
