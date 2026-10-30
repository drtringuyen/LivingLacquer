"""Poly Cut, a tool in Sculpt Mode's toolbar, as MultiCamProject's PolyCut; Ctrl+Shift+K or the photo panel's button
bring you there, on the mesh the ORG_ / OBJ_ switch names. Nothing happens until Ctrl+click starts an outline:

    click        add a point (the points stay on the object while you navigate)
    click the first point (it lights up green under the mouse) or double click: close the shape. The closed path over
                 the mesh's edges shows in yellow. A popup: Set Boundary as Seam, Add to Selection, Remove from
                 Selection (the faces inside that the view sees), Close Hole
    Enter        a path over the mesh's own edges through the points, shortest on the surface, shown in yellow; no new
                 geometry. A popup: Mark as Seam, or Cancel
    Esc          drop the outline

The selection lives only until its seam is set: a temporary Sculpt face set, shown in the face set colours. The
writes happen in Object Mode (Sculpt's undo does not record seams)."""
import heapq
import time
from types import SimpleNamespace

import bmesh
import bpy
import gpu
import numpy as np
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import core, uv_tools

FACE_SETS = ".sculpt_face_set"
SELECTION = 100000          # the temporary face set of the running selection
LINE_ATTR = "ll_cut_line"   # edge attribute: the edges of the last path, until the popup is answered
TOOL_ID = "livinglacquer.poly_cut_sculpt"
SAME_PX = 4
POINT_PX = 12               # a click this near an existing point is on it
DOUBLE_SECONDS, DOUBLE_PX = 0.45, 6     # a second click this soon, from when the first was done, and this near
COLOR = (1.0, 0.85, 0.2, 1.0)
CLOSE_COLOR = (0.3, 1.0, 0.4, 1.0)
NAVIGATE = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE"}
PENDING = {"object": "", "outline": None}   # the closed outline the popup is about: view and points
_preview = {"lines": None, "handle": None}  # the path on show (world points), until the popup is answered


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


def faces_in_outline(ob, region, rv3d, poly):
    """Indices of the faces whose centre lies in the outline, in front of the view and not behind other faces.
    Reads the mesh (Object or Sculpt Mode data)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    try:
        if not bm.faces:
            return np.zeros(0, np.int64)
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
            return chosen
        tree = BVHTree.FromBMesh(bm)
        inv = ob.matrix_world.inverted()
        view = rv3d.view_matrix.inverted()
        size = max(ob.dimensions.length, 1e-6)
        out = []
        for i in chosen:
            c = Vector(centres[i])
            if rv3d.is_perspective:
                start = inv @ view.translation
                direction = (c - start).normalized()
            else:
                direction = (inv.to_3x3() @ (view.to_3x3() @ Vector((0, 0, -1)))).normalized()
                start = c - direction * (10 * max(size, 1.0))
            hit = tree.ray_cast(start, direction)
            if hit[2] is None or hit[2] == i or (hit[0] - c).length <= 1e-4 * size:
                out.append(i)
        return np.array(out, np.int64)
    finally:
        bm.free()


# ---------------------------------------------------------------- the selection: a temporary face set

def _read_sets(me):
    a = me.attributes.get(FACE_SETS)
    v = np.ones(len(me.polygons), np.int32)
    if a is not None:
        a.data.foreach_get("value", v)
    return v


def _write_sets(me, v):
    a = me.attributes.get(FACE_SETS) or me.attributes.new(FACE_SETS, "INT", "FACE")
    a.data.foreach_set("value", v)
    me.update()


def add_to_selection(ob, faces):
    v = _read_sets(ob.data)
    v[faces] = SELECTION
    _write_sets(ob.data, v)
    return int((v == SELECTION).sum())


def remove_from_selection(ob, faces):
    v = _read_sets(ob.data)
    hit = faces[v[faces] == SELECTION]
    v[hit] = 1
    _write_sets(ob.data, v)
    return int((v == SELECTION).sum())


def _selected_with(ob, faces):
    """The selection's faces, with the outline's."""
    v = _read_sets(ob.data)
    sel = v == SELECTION
    sel[faces] = True
    return sel


def has_selection(ob):
    return bool((_read_sets(ob.data) == SELECTION).any())


def clear_selection(ob):
    v = _read_sets(ob.data)
    v[v == SELECTION] = 1
    _write_sets(ob.data, v)


def set_boundary_seam(ob, faces):
    """A seam on the border of the selection + the outline; the temporary face set goes. Returns the edge count."""
    sel = _selected_with(ob, faces)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    rim = uv_tools.rim([bm.faces[int(i)] for i in np.nonzero(sel)[0]])
    for e in rim:
        e.seam = True
    n = len(rim)
    bm.to_mesh(ob.data)
    bm.free()
    clear_selection(ob)
    return n


def close_hole(ob, faces):
    """The selection + the outline deleted and closed with one flat cap (Close Hole). Returns (triangles, warnings)."""
    sel = _selected_with(ob, faces)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f.select = bool(sel[f.index])
    new, warnings = uv_tools.close_holes(bm)
    bm.to_mesh(ob.data)
    bm.free()
    clear_selection(ob)
    return len(new), warnings


def mark_line_seam(ob):
    """The last path's edges become a seam. Returns the edge count."""
    me = ob.data
    a = me.attributes.get(LINE_ATTR)
    if a is None:
        return 0
    flags = np.zeros(len(me.edges), bool)
    a.data.foreach_get("value", flags)
    seams = np.zeros(len(me.edges), bool)
    me.edges.foreach_get("use_seam", seams)
    me.edges.foreach_set("use_seam", seams | flags)
    me.update()
    return int(flags.sum())


def forget_line(ob):
    a = ob.data.attributes.get(LINE_ATTR)
    if a is not None:
        ob.data.attributes.remove(a)


def path_edges(ob, points3d):
    """The mesh's own edges from each clicked point's nearest vertex to the next, shortest over the surface (A*):
    no new geometry, nothing projected. Returns a bool per edge."""
    me = ob.data
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    verts = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", verts)
    verts = verts.reshape(-1, 2)
    inv = ob.matrix_world.inverted()
    stops = []
    for q in points3d:
        i = int(np.argmin(((co - np.array(inv @ q, np.float64)) ** 2).sum(axis=1)))
        if not stops or stops[-1] != i:
            stops.append(i)
    order = np.argsort(np.concatenate((verts[:, 0], verts[:, 1])))
    ends = np.concatenate((verts[:, 1], verts[:, 0]))[order]
    edge_ids = np.concatenate((np.arange(len(verts)), np.arange(len(verts))))[order]
    first = np.searchsorted(np.concatenate((verts[:, 0], verts[:, 1]))[order], np.arange(len(co) + 1))
    flags = np.zeros(len(verts), bool)
    for start, goal in zip(stops, stops[1:]):
        target = co[goal]
        cost, came, heap = {start: 0.0}, {}, [(0.0, start)]
        while heap:
            _f, v = heapq.heappop(heap)
            if v == goal:
                break
            c = cost[v]
            for n, e in zip(ends[first[v]:first[v + 1]].tolist(), edge_ids[first[v]:first[v + 1]].tolist()):
                step = c + float(np.linalg.norm(co[n] - co[v]))
                if step < cost.get(n, np.inf):
                    cost[n], came[n] = step, (v, e)
                    heapq.heappush(heap, (step + float(np.linalg.norm(co[n] - target)), n))
        v = goal
        while v in came:
            v, e = came[v]
            flags[e] = True
    return flags


def mark_path(ob, points3d):
    """LINE_ATTR on the path's edges, for the popup. Returns the edge count."""
    flags = path_edges(ob, points3d)
    me = ob.data
    a = me.attributes.get(LINE_ATTR) or me.attributes.new(LINE_ATTR, "BOOLEAN", "EDGE")
    a.data.foreach_set("value", flags)
    return int(flags.sum())


def _draw_path():
    """The path until the popup is answered: it is not a seam yet."""
    if not _preview["lines"]:
        return
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    sh.uniform_float("lineWidth", 3.0)
    sh.uniform_float("color", COLOR)
    batch_for_shader(sh, "LINES", {"pos": _preview["lines"]}).draw(sh)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def _show_path(ob):
    me = ob.data
    flags = np.zeros(len(me.edges), bool)
    me.attributes[LINE_ATTR].data.foreach_get("value", flags)
    m = ob.matrix_world
    _preview["lines"] = [tuple(m @ me.vertices[v].co) for i in np.nonzero(flags)[0].tolist() for v in me.edges[i].vertices]
    if _preview["handle"] is None:
        _preview["handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw_path, (), "WINDOW", "POST_VIEW")


def _hide_path():
    _preview["lines"] = None
    if _preview["handle"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_preview["handle"], "WINDOW")
        _preview["handle"] = None


# ---------------------------------------------------------------- operators

def switch_object(context):
    """The mesh the ORG_ / OBJ_ switch names."""
    rb = context.scene.livinglacquer_rebuild
    return core.scan_mesh() if rb.edit_mesh == "ORG" else rb.target


def _in_object_mode(context, ob, work):
    """Run work() in Object Mode on ob (Sculpt's undo does not record seams), then back to where it was."""
    mode = ob.mode
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        return work()
    finally:
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)


class LIVINGLACQUER_OT_PolyCut(bpy.types.Operator):
    """Ctrl+click: start an outline. Click: points. The first point or a double click: close it. Enter: an open
    path along the mesh's edges. Esc: drop it"""
    bl_idname = "livinglacquer.poly_cut"
    bl_label = "Poly Cut"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "MESH" and context.mode == "SCULPT" \
            and context.area is not None and context.area.type == "VIEW_3D"

    def _add(self, context, p):
        region, rv3d = self._win, self._rv3d
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, p)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, p).normalized()
        hit, loc, *_rest = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
        if not hit:
            depth = self._points3d[-1] if self._points3d else rv3d.view_location
            loc = view3d_utils.region_2d_to_location_3d(region, rv3d, p, depth)
        self._points3d.append(loc.copy())

    def _points(self):
        out = []
        for co in self._points3d:
            p = view3d_utils.location_3d_to_region_2d(self._win, self._rv3d, co)
            out.append(None if p is None else (p.x, p.y))
        return out

    def _draw(self, _context):
        points = [p for p in self._points() if p is not None]
        if not points or bpy.context.region != self._win:
            return
        sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")
        sh.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        sh.uniform_float("lineWidth", 2.0)
        sh.uniform_float("color", COLOR)
        batch_for_shader(sh, "LINE_STRIP", {"pos": points + [self._mouse]}).draw(sh)
        sh.uniform_float("color", (COLOR[0], COLOR[1], COLOR[2], 0.35))
        batch_for_shader(sh, "LINES", {"pos": [self._mouse, points[0]]}).draw(sh)
        dots = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.point_size_set(7.0)
        dots.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        batch_for_shader(dots, "POINTS", {"pos": points}).draw(dots)
        gpu.state.point_size_set(11.0)
        dots.uniform_float("color", COLOR)          # the last point clicked
        batch_for_shader(dots, "POINTS", {"pos": [points[-1]]}).draw(dots)
        under = self._under_mouse()
        if under is not None:
            closing = under == 0 and len(self._points3d) >= 3
            gpu.state.point_size_set(15.0)
            dots.uniform_float("color", CLOSE_COLOR if closing else (1.0, 1.0, 1.0, 1.0))
            batch_for_shader(dots, "POINTS", {"pos": [self._points()[under]]}).draw(dots)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set("NONE")

    def _under_mouse(self):
        """The index of the point under the mouse, None for none."""
        best, found = POINT_PX, None
        for i, p in enumerate(self._points()):
            if p is not None:
                d = (Vector(p) - Vector(self._mouse)).length
                if d < best:
                    best, found = d, i
        return found

    def _pos(self, event):
        return (event.mouse_x - self._win.x, event.mouse_y - self._win.y)

    def _end(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
        context.workspace.status_text_set(None)
        context.window.cursor_modal_restore()
        self._area.tag_redraw()

    def invoke(self, context, event):
        _hide_path()
        self._area = context.area
        self._win = next((r for r in context.area.regions if r.type == "WINDOW"), None)
        self._rv3d = context.area.spaces.active.region_3d
        if self._win is None:
            return {"CANCELLED"}
        self._points3d = []
        self._mouse = self._pos(event)
        self._last_pos = self._mouse
        if event.type == "LEFTMOUSE":
            self._add(context, self._mouse)
        self._last_click = time.monotonic()
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (context,), "WINDOW", "POST_PIXEL")
        context.window.cursor_modal_set("CROSSHAIR")
        context.workspace.status_text_set("Poly Cut: click: point  ·  click the first point or double click: close  ·  "
                                          "Enter: path along the mesh's edges  ·  Esc: cancel")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        self._area.tag_redraw()
        if event.type == "MOUSEMOVE":
            self._mouse = self._pos(event)
            return {"RUNNING_MODAL"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._cut_line(context)
        if event.type in NAVIGATE or event.type.startswith(("NUMPAD_", "NDOF_")):
            return {"PASS_THROUGH"}
        if event.type == "ESC" and event.value == "PRESS":
            self._end(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value in {"PRESS", "DOUBLE_CLICK"}:
            p = self._pos(event)
            self._mouse = p
            # the clock runs from when the last click was done: on a dense mesh adding a point takes a moment, which
            # Blender's own double click counts against you
            again = (time.monotonic() - self._last_click < DOUBLE_SECONDS
                     and (Vector(p) - Vector(self._last_pos)).length < DOUBLE_PX)
            if (event.value == "DOUBLE_CLICK" or again or self._under_mouse() == 0) and len(self._points3d) >= 3:
                return self._close(context)
            if not again and event.value == "PRESS":
                self._add(context, p)
            self._last_pos = p
            self._last_click = time.monotonic()
        return {"RUNNING_MODAL"}

    def _close(self, context):
        """The closed path shows, the popup asks; the faces inside are only looked for when they are asked for."""
        pts = self._points()
        pts3d = list(self._points3d)
        self._end(context)
        if len(pts) < 3 or None in pts:
            self.report({"WARNING"}, "Closing needs at least 3 points in front of the view")
            return {"CANCELLED"}
        ob = context.active_object
        n = _in_object_mode(context, ob, lambda: mark_path(ob, pts3d + [pts3d[0]]))
        _in_object_mode(context, ob, lambda: _show_path(ob))
        rv3d = self._rv3d
        view = SimpleNamespace(perspective_matrix=rv3d.perspective_matrix.copy(), view_matrix=rv3d.view_matrix.copy(),
                               is_perspective=rv3d.is_perspective)
        PENDING.update(object=ob.name, outline=(SimpleNamespace(width=self._win.width, height=self._win.height), view, pts))
        context.space_data.overlay.show_sculpt_face_sets = True
        self._area.tag_redraw()
        _popup(context, "CLOSED", f"Closed: {n:,} edges")
        return {"FINISHED"}

    def _cut_line(self, context):
        pts3d = list(self._points3d)
        self._end(context)
        if len(pts3d) < 2:
            self.report({"WARNING"}, "Poly Cut needs at least 2 points")
            return {"CANCELLED"}
        ob = context.active_object
        n = _in_object_mode(context, ob, lambda: mark_path(ob, pts3d))
        if not n:
            self.report({"WARNING"}, "The points lie on one vertex")
            return {"CANCELLED"}
        _in_object_mode(context, ob, lambda: _show_path(ob))
        self._area.tag_redraw()
        _popup(context, "LINE", f"{n:,} edges in the path")
        return {"FINISHED"}


class LIVINGLACQUER_OT_PolyCutApply(bpy.types.Operator):
    """What happens to the outline or the line just made"""
    bl_idname = "livinglacquer.poly_cut_apply"
    bl_label = "Poly Cut"
    bl_options = {"REGISTER", "UNDO"}
    action: bpy.props.EnumProperty(items=[("ADD", "Add to Selection", ""), ("REMOVE", "Remove from Selection", ""),
                                          ("SEAM", "Set Boundary as Seam", ""), ("HOLE", "Close Hole", ""),
                                          ("LINE_SEAM", "Mark as Seam", ""), ("LINE_CANCEL", "Cancel", "")],
                                   options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        ob = context.active_object
        outline = PENDING["outline"] if PENDING["object"] == ob.name else None
        PENDING.update(object="", outline=None)

        def faces():
            return faces_in_outline(ob, outline[0], outline[1], outline[2]) if outline else np.zeros(0, np.int64)

        def work():
            if self.action == "ADD":
                return f"Selection: {add_to_selection(ob, faces()):,} faces"
            if self.action == "REMOVE":
                return f"Selection: {remove_from_selection(ob, faces()):,} faces"
            if self.action == "HOLE":
                n, warnings = close_hole(ob, faces())
                forget_line(ob)
                return "; ".join(warnings) if warnings else f"Close Hole: {n:,} triangles"
            if self.action == "SEAM" and has_selection(ob):
                forget_line(ob)
                return f"Seam on {set_boundary_seam(ob, np.zeros(0, np.int64)):,} border edges"
            n = mark_line_seam(ob) if self.action in {"SEAM", "LINE_SEAM"} else 0
            forget_line(ob)
            return f"Seam on {n:,} edges" if n else "Path dropped"

        _hide_path()
        self.report({"INFO"}, _in_object_mode(context, ob, work))
        return {"FINISHED"}


def _popup(context, kind, title):
    def draw(menu, _context):
        col = menu.layout.column()
        idname = LIVINGLACQUER_OT_PolyCutApply.bl_idname
        rows = ((("SEAM", "Set Boundary as Seam", "UV_EDGESEL"), ("ADD", "Add to Selection", "ADD"),
                 ("REMOVE", "Remove from Selection", "REMOVE"), ("HOLE", "Close Hole", "MESH_PLANE"))
                if kind == "CLOSED" else
                (("LINE_SEAM", "Mark as Seam", "UV_EDGESEL"), ("LINE_CANCEL", "Cancel", "CANCEL")))
        for action, text, icon in rows:
            col.operator(idname, text=text, icon=icon).action = action

    context.window_manager.popup_menu(draw, title=title, icon="QUESTION")


class LIVINGLACQUER_OT_PolyCutTool(bpy.types.Operator):
    """Poly Cut: the ORG_ / OBJ_ mesh in Sculpt Mode with the tool on. Ctrl+click starts an outline"""
    bl_idname = "livinglacquer.poly_cut_tool"
    bl_label = "Poly Cut"

    def execute(self, context):
        ob = switch_object(context)
        if ob is None:
            self.report({"WARNING"}, "No OBJ_ mesh yet: make one in Step 5a or From Base")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in context.selected_objects:
            o.select_set(False)
        ob.hide_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode="SCULPT")
        area = context.area if context.area is not None and context.area.type == "VIEW_3D" else next(
            (a for a in context.screen.areas if a.type == "VIEW_3D"), None)
        if area is not None:
            region = next(r for r in area.regions if r.type == "WINDOW")
            with context.temp_override(area=area, region=region):
                bpy.ops.wm.tool_set_by_id(name=TOOL_ID)
        return {"FINISHED"}


class LIVINGLACQUER_TL_PolyCut(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "SCULPT"
    bl_idname = TOOL_ID
    bl_label = "Poly Cut"
    bl_description = ("Ctrl+Click starts an outline: click points, the first point or a double click closes it, Enter makes a path "
                      "along the mesh's edges, Esc cancels")
    bl_icon = "ops.sculpt.lasso_face_set"
    bl_widget = None
    bl_keymap = ((LIVINGLACQUER_OT_PolyCut.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True}, None),)

    @staticmethod
    def draw_settings(context, layout, tool):
        layout.label(text="Ctrl+Click: Poly Cut")


classes = (LIVINGLACQUER_OT_PolyCut, LIVINGLACQUER_OT_PolyCutApply, LIVINGLACQUER_OT_PolyCutTool)
_keymaps = []
_seen = {"active": None}


def follow_active(*_args):
    """The ORG_ / OBJ_ switch follows the mesh you select: the scan is ORG_, a rebuilt object is OBJ_ (and the one step 5
    works on). Any other object leaves it as it is, and only a change of the active object counts: pressing the
    switch itself selects the mesh. Without a final mesh it stays on ORG_. Blender has no event for a click in the
    view, so this runs on every depsgraph update and when the photo panel draws: it must stay cheap."""
    context = bpy.context
    rb = getattr(context.scene, "livinglacquer_rebuild", None)
    if rb is None or context.view_layer is None:
        return
    if rb.edit_mesh == "FINAL" and core.final_mesh(rb) is None:
        rb.edit_mesh = "ORG"
    ob = context.view_layer.objects.active
    name = ob.name if ob is not None else None
    if name == _seen["active"]:
        return
    _seen["active"] = name
    if ob is None or ob.type != "MESH":
        return
    if ob == core.scan_mesh():
        wanted = "ORG"
    elif ob.get(core.REBUILD_KEY):
        wanted = "FINAL"
        if rb.target != ob:
            rb.target = ob
    else:
        return
    if rb.edit_mesh != wanted:
        rb.edit_mesh = wanted
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


@bpy.app.handlers.persistent
def _on_depsgraph(*_args):
    follow_active()


@bpy.app.handlers.persistent
def _on_load(*_args):
    _seen["active"] = None
    follow_active()


def switch_to(context, which):
    """The switch pressed: that mesh selected and active, in the mode it was in (Sculpt: with the tool on)."""
    rb = context.scene.livinglacquer_rebuild
    ob = core.scan_mesh() if which == "ORG" else core.final_mesh(rb)
    if ob is None:
        return False
    rb.edit_mesh = which
    mode = context.mode
    if mode == "SCULPT":
        bpy.ops.livinglacquer.poly_cut_tool()
        return True
    if mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.selected_objects:
        o.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if mode == "EDIT_MESH":
        bpy.ops.object.mode_set(mode="EDIT")
    return True


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.utils.register_tool(LIVINGLACQUER_TL_PolyCut, separator=True)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    for name in ("Object Mode", "Sculpt"):      # Ctrl+Shift+K, as in MultiCamProject
        km = kc.keymaps.new(name=name, space_type="EMPTY")
        _keymaps.append((km, km.keymap_items.new(LIVINGLACQUER_OT_PolyCutTool.bl_idname, "K", "PRESS", ctrl=True, shift=True, head=True)))


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    _hide_path()
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    try:
        bpy.utils.unregister_tool(LIVINGLACQUER_TL_PolyCut)
    except (ValueError, RuntimeError):
        pass
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
