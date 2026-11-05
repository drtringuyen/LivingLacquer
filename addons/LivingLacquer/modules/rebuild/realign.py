"""Realign Camera: a photo whose camera solved wrong (the object turned over, the background misleading the alignment)
gets its camera back from points matched by hand between the photo and the mesh. Only the points count, the background
plays no part, and the object stays where it is.

The photo opens beside the view. Click a point on the mesh (it snaps to a vertex nearby) and the same point on the photo,
in either order, four pairs or more; points at different depths hold better than points on one flat face, and a shape
that repeats (a hexagon) needs its pairs in the right turn. From four pairs on the mesh is drawn over the photo with the
error in photo pixels: judge by the parts no point was placed on. Wheel and middle drag zoom and pan the photo, a point
on it can be dragged, Backspace takes the last one back. Enter applies, Esc leaves the camera as it was.

No guarantee: a wrong lens, a mesh unlike the object or a few points close together give a poor camera, and the overlay
shows it. The camera's first position stays on it (ORIGINAL_KEY): Restore Camera puts it back."""
import blf
import bpy
import gpu
import numpy as np
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix
from mathutils.bvhtree import BVHTree

from . import core, paint, photo_panel

ORIGINAL_KEY = "ll_solved_matrix"       # camera key: its matrix before the first realign
MIN_PAIRS = 4
SNAP_PX = 12                            # a click this near a vertex takes the vertex
GRAB_PX = 10                            # a press this near a point on the photo drags it
PHOTO_SHARE = 0.5                       # of the view's free width
TEXT_TOP = 56                           # the line's distance from the top: under the view's header
MAX_WIRE = 40000
GOOD, FAIR = 0.005, 0.015               # the error, of the photo's width
STARTS = 48                             # directions tried for a first guess
ROLLS = 8
KEEP = 8                                # first guesses refined
COL_MESH = (0.2, 1.0, 0.3, 0.75)
COL_POINT = (1.0, 0.2, 0.9, 1.0)
COL_PENDING = (1.0, 0.85, 0.2, 1.0)


# ---------------------------------------------------------------- the camera from the points

def intrinsics(cam, width, height):
    """The camera's lens as a pixel matrix for a photo of this size (y down), as Blender frames it."""
    d = cam.data
    wide = width >= height if d.sensor_fit == "AUTO" else d.sensor_fit == "HORIZONTAL"
    fac = width if wide else height
    sensor = d.sensor_height if d.sensor_fit == "VERTICAL" else d.sensor_width
    f = d.lens / sensor * fac
    return np.array([[f, 0, width / 2 - d.shift_x * fac], [0, f, height / 2 + d.shift_y * fac], [0, 0, 1.0]])


def project(K, R, t, X):
    """Photo pixels of the world points X, and their depth (> 0 in front of the camera)."""
    c = X @ R.T + t
    z = c[:, 2]
    safe = np.where(np.abs(z) < 1e-9, 1e-9, z)
    return np.stack([K[0, 0] * c[:, 0] / safe + K[0, 2], K[1, 1] * c[:, 1] / safe + K[1, 2]], 1), z


def _rotation(w):
    """The rotation by the vector w (its length the angle)."""
    a = np.linalg.norm(w)
    if a < 1e-12:
        return np.eye(3)
    x, y, z = w / a
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + np.sin(a) * k + (1 - np.cos(a)) * k @ k


def _position_for(R, K, X, x):
    """The camera's t that fits best with its turn R (linear)."""
    u = (x[:, 0] - K[0, 2]) / K[0, 0]
    v = (x[:, 1] - K[1, 2]) / K[1, 1]
    c = X @ R.T
    n = len(X)
    A = np.zeros((2 * n, 3))
    A[:n, 0] = 1
    A[:n, 2] = -u
    A[n:, 1] = 1
    A[n:, 2] = -v
    b = np.concatenate([u * c[:, 2] - c[:, 0], v * c[:, 2] - c[:, 1]])
    return np.linalg.lstsq(A, b, rcond=None)[0]


def _errors(K, R, t, X, x):
    p, z = project(K, R, t, X)
    return np.linalg.norm(p - x, axis=1), z


def _refine(K, R, t, X, x, steps=40):
    """Levenberg-Marquardt on the reprojection."""
    def residual(R_, t_):
        return (project(K, R_, t_, X)[0] - x).ravel()

    lam = 1e-3
    r = residual(R, t)
    cost = r @ r
    for _ in range(steps):
        J = np.zeros((len(r), 6))
        eps = 1e-5
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            J[:, i] = (residual(_rotation(d) @ R, t) - r) / eps
            J[:, 3 + i] = (residual(R, t + d) - r) / eps
        H = J.T @ J
        g = J.T @ r
        for _ in range(8):
            try:
                step = np.linalg.solve(H + lam * np.diag(np.maximum(np.diag(H), 1e-9)), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            R2, t2 = _rotation(step[:3]) @ R, t + step[3:]
            r2 = residual(R2, t2)
            if r2 @ r2 < cost:
                improved = cost - r2 @ r2
                R, t, r, cost = R2, t2, r2, r2 @ r2
                lam = max(lam / 3, 1e-9)
                break
            lam *= 4
        else:
            break
        if improved < 1e-8 * max(cost, 1e-9):
            break
    return R, t


def _look_rotations():
    """Turns from every side: a spiral of view directions, each with some rolls."""
    out = []
    golden = np.pi * (3 - np.sqrt(5))
    for i in range(STARTS):
        z = 1 - 2 * (i + 0.5) / STARTS
        s = np.sqrt(max(0.0, 1 - z * z))
        forward = np.array([np.cos(i * golden) * s, np.sin(i * golden) * s, z])
        helper = np.array([0, 0, 1.0]) if abs(z) < 0.9 else np.array([1.0, 0, 0])
        right = np.cross(forward, helper)
        right /= np.linalg.norm(right)
        base = np.stack([right, np.cross(forward, right), forward])     # world to camera, z forward
        for k in range(ROLLS):
            out.append(_rotation(np.array([0, 0, 2 * np.pi * k / ROLLS])) @ base)
    return out


_LOOKS = _look_rotations()


def solve(K, X, x):
    """The camera for the world points X seen at the photo pixels x: {R, t, error, worst, errors}, the lowest error
    with every point in front; None with too few points or points that do not span anything."""
    X, x = np.asarray(X, float), np.asarray(x, float)
    if len(X) < MIN_PAIRS or len(X) != len(x):
        return None
    if np.linalg.svd(X - X.mean(0), compute_uv=False)[1] < 1e-6 * max(np.ptp(X, axis=0).max(), 1e-9):
        return None     # on one line
    guesses = []
    for R in _LOOKS:
        t = _position_for(R, K, X, x)
        err, z = _errors(K, R, t, X, x)
        if (z > 0).all():
            guesses.append((err.mean(), R, t))
    guesses.sort(key=lambda g: g[0])
    best = None
    for _e, R, t in guesses[:KEEP]:
        R, t = _refine(K, R, t, X, x)
        err, z = _errors(K, R, t, X, x)
        if (z > 0).all() and (best is None or err.mean() < best["error"]):
            best = {"R": R, "t": t, "error": float(err.mean()), "worst": float(err.max()), "errors": err}
    return best


def camera_matrix(cam, R, t):
    """The camera's matrix_world for the pose (x right, y down, z forward), its scale kept."""
    M = np.eye(4)
    M[:3, :3] = R.T @ np.diag([1.0, -1.0, -1.0]) * float(cam.matrix_world.to_scale()[0])
    M[:3, 3] = -R.T @ t
    return Matrix(M.tolist())


def apply(cam, R, t):
    """The camera to the pose; its first position stays on it for Restore Camera."""
    if ORIGINAL_KEY not in cam:
        cam[ORIGINAL_KEY] = [v for row in cam.matrix_world for v in row]
    cam.matrix_world = camera_matrix(cam, R, t)


def restore(cam):
    """The camera back at its first position. False when it was never realigned."""
    if ORIGINAL_KEY not in cam:
        return False
    v = list(cam[ORIGINAL_KEY])
    cam.matrix_world = Matrix([v[i:i + 4] for i in range(0, 16, 4)])
    del cam[ORIGINAL_KEY]
    return True


def quality(error, width):
    return "good" if error <= GOOD * width else "fair" if error <= FAIR * width else "poor"


def mesh_of(context, rb):
    """The active mesh, else the rebuilt object."""
    ob = context.active_object
    if ob is not None and ob.type == "MESH":
        return ob
    return core.final_mesh(rb)


# ---------------------------------------------------------------- the tool

_draws = []


def _lines(pts, color, width=1.0):
    if not len(pts):
        return
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    sh.uniform_float("color", color)
    gpu.state.line_width_set(width)
    batch_for_shader(sh, "LINES", {"pos": pts}).draw(sh)
    gpu.state.line_width_set(1.0)


def _marker(x, y, color, label):
    s = 5
    _lines([(x - s, y), (x + s, y), (x, y - s), (x, y + s)], color, 2.0)
    blf.size(0, 13)
    blf.color(0, *color)
    blf.position(0, x + 6, y + 6, 0)
    blf.draw(0, label)


class LIVINGLACQUER_OT_RealignCamera(bpy.types.Operator):
    """Give this photo's camera back from points you match between the photo and the mesh: for a photo whose camera
    solved wrong. Enter applies, Esc leaves it as it was"""
    bl_idname = "livinglacquer.realign_camera"
    bl_label = "Realign Camera"

    @classmethod
    def poll(cls, context):
        rb = context.scene.livinglacquer_rebuild
        cam = core.cameras().get(rb.photo)
        if cam is None or core.photo_image(cam) is None:
            cls.poll_message_set("Pick a photo first")
            return False
        if context.mode != "OBJECT" or context.area is None or context.area.type != "VIEW_3D":
            cls.poll_message_set("Object Mode, in the 3D viewport")
            return False
        if mesh_of(context, rb) is None:
            cls.poll_message_set("Select the mesh to match")
            return False
        return True

    def invoke(self, context, event):
        rb = context.scene.livinglacquer_rebuild
        self.cam = core.cameras()[rb.photo]
        self.photo = core.photo_image(self.cam)
        self.ob = mesh_of(context, rb)
        self.area, self.region = context.area, next(r for r in context.area.regions if r.type == "WINDOW")
        self.rv3d = context.area.spaces.active.region_3d
        self.W, self.H = self.photo.size
        if not self.W or not self.H:
            self.report({"WARNING"}, f"{self.photo.name} has no pixels: is its file there?")
            return {"CANCELLED"}
        self.K = intrinsics(self.cam, self.W, self.H)
        paint._final_mesh_on(self.ob)
        me = self.ob.data
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        mw = np.array(self.ob.matrix_world, float)
        self.verts = co.reshape(-1, 3).astype(float) @ mw[:3, :3].T + mw[:3, 3]
        self.tree = BVHTree.FromPolygons(self.verts.tolist(), [tuple(t.vertices) for t in me.loop_triangles])
        self.tris = [tuple(t.vertices) for t in me.loop_triangles]
        ed = np.empty(len(me.edges) * 2, np.int32)
        me.edges.foreach_get("vertices", ed)
        ed = ed.reshape(-1, 2)
        self.edges = ed[:: max(1, len(ed) // MAX_WIRE)]
        self.pairs = []         # [[world or None, photo or None]]
        self.solution = None
        self.wire = np.empty((0, 2))
        self.scale = None
        self.middle = [0.0, 0.0]
        self.grab = None
        self.pan = None
        self.done = None
        self._layout()
        self.scale = min((self.rect[2] - self.rect[0]) / self.W, (self.rect[3] - self.rect[1]) / self.H)
        self.middle = [self.W / 2, self.H / 2]
        self.handler = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        _draws.append(self.handler)
        self._status(context)
        context.window_manager.modal_handler_add(self)
        self.area.tag_redraw()
        return {"RUNNING_MODAL"}

    # the photo's place: the right of the view's free width

    def _layout(self):
        left, right = paint._visible_span(self.area, self.region)
        self.rect = (right - (right - left) * PHOTO_SHARE, 0, right, self.region.height)

    def _to_region(self, p):
        x0, y0, x1, y1 = self.rect
        return ((x0 + x1) / 2 + (p[0] - self.middle[0]) * self.scale, (y0 + y1) / 2 - (p[1] - self.middle[1]) * self.scale)

    def _to_photo(self, x, y):
        x0, y0, x1, y1 = self.rect
        return ((x - (x0 + x1) / 2) / self.scale + self.middle[0], ((y0 + y1) / 2 - y) / self.scale + self.middle[1])

    def _in_photo(self, x, y):
        x0, y0, x1, y1 = self.rect
        return x0 <= x < x1 and y0 <= y < y1

    # the points

    def _pair_open(self, side):
        """The first pair still missing this side (0 mesh, 1 photo), new when none."""
        for pair in self.pairs:
            if pair[side] is None:
                return pair
        self.pairs.append([None, None])
        return self.pairs[-1]

    def _pick_mesh(self, context, x, y):
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, (x, y))
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, (x, y))
        loc, _n, tri, _d = self.tree.ray_cast(origin, direction)
        if loc is None:
            return None
        best, gap = np.array(loc, float), SNAP_PX
        for v in self.tris[tri]:
            q = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, self.verts[v])
            if q is not None and (q.x - x) ** 2 + (q.y - y) ** 2 < gap ** 2:
                best, gap = self.verts[v], ((q.x - x) ** 2 + (q.y - y) ** 2) ** 0.5
        return best

    def _resolve(self):
        full = [p for p in self.pairs if p[0] is not None and p[1] is not None]
        self.solution = solve(self.K, [p[0] for p in full], [p[1] for p in full]) if len(full) >= MIN_PAIRS else None
        self.wire = np.empty((0, 2))
        if self.solution is not None:
            uv, z = project(self.K, self.solution["R"], self.solution["t"], self.verts)
            keep = (z[self.edges] > 0).all(1)
            self.wire = uv[self.edges[keep].ravel()]

    def _status(self, context):
        context.workspace.status_text_set(
            "Realign · click the mesh and the photo, the same point on each · wheel, middle drag: the photo · "
            "Backspace: last point · Enter: apply · Esc: leave the camera")

    # the modal

    def modal(self, context, event):
        if self.done is not None:       # finished from outside
            return self.done
        x, y = event.mouse_x - self.region.x, event.mouse_y - self.region.y
        inside = 0 <= x < self.region.width and 0 <= y < self.region.height
        self._layout()
        if event.type == "MOUSEMOVE":
            if self.grab is not None:
                self.grab[1] = self._to_photo(x, y)
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            if self.pan is not None:
                self.middle = [self.pan[2] - (x - self.pan[0]) / self.scale, self.pan[3] + (y - self.pan[1]) / self.scale]
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self.grab is not None:
            self.grab = None
            self._resolve()
            self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "MIDDLEMOUSE" and event.value == "RELEASE" and self.pan is not None:
            self.pan = None
            return {"RUNNING_MODAL"}
        if event.value != "PRESS" and not event.type.startswith("WHEEL"):
            return {"PASS_THROUGH"}
        if event.type == "ESC":
            self._finish(context)
            self.report({"INFO"}, f"{self.cam.name}: camera left as it was")
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"}:
            if self.solution is None:
                self.report({"WARNING"}, f"Match {MIN_PAIRS} points or more first")
                return {"RUNNING_MODAL"}
            return self._confirm(context)
        if event.type == "BACK_SPACE":
            if self.pairs:
                self.pairs.pop()
                self._resolve()
                self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if not inside or not paint._visible_span(self.area, self.region)[0] <= x <= self.rect[2]:
            return {"PASS_THROUGH"}
        over_panel = photo_panel.active(context) and photo_panel.hit(context, self.region, x, y) is not None
        if self._in_photo(x, y) and not over_panel:
            if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
                keep = self._to_photo(x, y)
                self.scale *= 1.25 if event.type == "WHEELUPMOUSE" else 0.8
                after = self._to_photo(x, y)
                self.middle = [self.middle[0] + keep[0] - after[0], self.middle[1] + keep[1] - after[1]]
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            if event.type == "MIDDLEMOUSE":
                self.pan = [x, y, self.middle[0], self.middle[1]]
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE":
                for pair in self.pairs:
                    if pair[1] is not None:
                        q = self._to_region(pair[1])
                        if (q[0] - x) ** 2 + (q[1] - y) ** 2 < GRAB_PX ** 2:
                            self.grab = pair
                            return {"RUNNING_MODAL"}
                self._pair_open(1)[1] = self._to_photo(x, y)
                self._resolve()
                self.area.tag_redraw()
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and not over_panel:
            p = self._pick_mesh(context, x, y)
            if p is not None:
                self._pair_open(0)[0] = p
                self._resolve()
                self.area.tag_redraw()
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def _confirm(self, context):
        s = self.solution
        apply(self.cam, s["R"], s["t"])
        paint.unpin(self.cam)           # the camera lines up now: a pinned view would hide it
        self._finish(context)
        rb = context.scene.livinglacquer_rebuild
        rb.focus = "FOCUS"
        bpy.ops.livinglacquer.rebuild_photo(name=self.cam.name)
        bpy.ops.ed.undo_push(message="Realign Camera")
        self.report({"INFO"}, f"{self.cam.name}: realigned, error {s['error']:.1f} px ({quality(s['error'], self.W)})")
        return {"FINISHED"}

    def _finish(self, context):
        if self.handler in _draws:
            _draws.remove(self.handler)
            bpy.types.SpaceView3D.draw_handler_remove(self.handler, "WINDOW")
        context.workspace.status_text_set(None)
        rb = context.scene.livinglacquer_rebuild
        if not rb.flat and not paint.painting(context):
            paint._release_gn()
        self.area.tag_redraw()

    # the drawing

    def _draw(self):
        context = bpy.context
        if context.area != self.area or context.region != self.region:
            return
        self._layout()
        x0, y0, x1, y1 = self.rect
        gpu.state.blend_set("ALPHA")
        sh = gpu.shader.from_builtin("UNIFORM_COLOR")
        sh.uniform_float("color", (0.06, 0.06, 0.06, 1.0))
        batch_for_shader(sh, "TRI_FAN", {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))}).draw(sh)
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(int(x0), int(y0), int(x1 - x0), int(y1 - y0))
        img = gpu.shader.from_builtin("IMAGE_SCENE_LINEAR_TO_REC709_SRGB")    # the photo's own brightness
        img.uniform_sampler("image", gpu.texture.from_image(self.photo))
        corners = [self._to_region(p) for p in ((0, self.H), (self.W, self.H), (self.W, 0), (0, 0))]
        batch_for_shader(img, "TRI_FAN", {"pos": corners, "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))}).draw(img)
        if len(self.wire):
            mx, my = self.middle
            w = self.wire
            pts = np.stack([(x0 + x1) / 2 + (w[:, 0] - mx) * self.scale, (y0 + y1) / 2 - (w[:, 1] - my) * self.scale], 1)
            _lines(pts.astype(np.float32).tolist(), COL_MESH)
        for i, (world, pix) in enumerate(self.pairs):
            if pix is not None:
                q = self._to_region(pix)
                _marker(q[0], q[1], COL_POINT if world is not None else COL_PENDING, str(i + 1))
        gpu.state.scissor_test_set(False)
        for i, (world, pix) in enumerate(self.pairs):
            if world is not None:
                q = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, world)
                if q is not None and q.x < x0:
                    _marker(q.x, q.y, COL_POINT if pix is not None else COL_PENDING, str(i + 1))
        self._draw_text(x0, y1 - TEXT_TOP)
        gpu.state.blend_set("NONE")

    def _draw_text(self, x, top):
        full = sum(1 for p in self.pairs if p[0] is not None and p[1] is not None)
        if self.solution is not None:
            e = self.solution["error"]
            q = quality(e, self.W)
            line = f"{full} pairs  ·  error {e:.1f} px ({q})"
            color = {"good": (0.5, 1, 0.5, 1), "fair": (1, 0.85, 0.3, 1), "poor": (1, 0.45, 0.4, 1)}[q]
        elif full >= MIN_PAIRS:
            line, color = f"{full} pairs: no camera fits them. Check their order", (1, 0.45, 0.4, 1)
        else:
            line = f"{self.cam.name}: {full} of {MIN_PAIRS} pairs"
            color = (0.95, 0.95, 0.95, 1)
        blf.size(0, 14)
        w, h = blf.dimensions(0, line)
        sh = gpu.shader.from_builtin("UNIFORM_COLOR")
        sh.uniform_float("color", (0, 0, 0, 0.7))
        batch_for_shader(sh, "TRI_FAN", {"pos": ((x, top - h - 12), (x + w + 16, top - h - 12), (x + w + 16, top), (x, top))}).draw(sh)
        blf.color(0, *color)
        blf.position(0, x + 8, top - h - 6, 0)
        blf.draw(0, line)


class LIVINGLACQUER_OT_RestoreCamera(bpy.types.Operator):
    """Put this photo's camera back where it was before Realign Camera"""
    bl_idname = "livinglacquer.restore_camera"
    bl_label = "Restore Camera"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        cam = core.cameras().get(context.scene.livinglacquer_rebuild.photo)
        return cam is not None and ORIGINAL_KEY in cam

    def execute(self, context):
        cam = core.cameras()[context.scene.livinglacquer_rebuild.photo]
        restore(cam)
        self.report({"INFO"}, f"{cam.name}: camera restored")
        return {"FINISHED"}


_CLASSES = (LIVINGLACQUER_OT_RealignCamera, LIVINGLACQUER_OT_RestoreCamera)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for h in _draws:
        bpy.types.SpaceView3D.draw_handler_remove(h, "WINDOW")
    _draws.clear()
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
