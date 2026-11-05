"""uvTube: the selected edges become a tube with uv_normal, a helper over the mesh until Enter / Esc.

Start (Edit Mode, edge select): the edges, split into chains at their ends and forks, become
a Poly curve object over the mesh (its matrix, its collection), with the MCP-uvTube Geometry
Nodes modifier: Catmull-Rom smoothing (Smooth), resampled to Segments per chain (Adaptive: shared
out per span of the curve, so dense points get dense rings, and every point keeps a ring), swept
by a circle of Sides points and Radius, scaled by each point's own radius - Alt+S in the curve's
Edit Mode, as the Skin modifier's points do. The curve is what the user edits: Shape moves its
points (the curve's Edit Mode), Move the whole tube (Object Mode). The mesh stays as it is, the
photos and the view stay free, and the values live in the photo panel and the sidebar. Bezier
swaps the points for few ones with handles, and back. The seam along the tube shows in the view
before Confirm: Seam steps it around, Pick Seam takes the line clicked.

Enter (or Confirm): the evaluated tube becomes faces of the mesh where it now stands, uv_normal laid out from the
attributes the nodes stored (u around, v along, caps planar), seams on the u = 0 line, the
v = 0 ring and around the caps; the source edges that had no faces go. Esc (or Cancel): the
curve goes, the mesh is as it was.

A file saved mid-session keeps the curve (TARGET_KEY on it): Confirm / Cancel in the uvTube panel."""
import math

import bmesh
import bpy
import gpu
import numpy as np
from bpy_extras.view3d_utils import region_2d_to_origin_3d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import interpolate_bezier

from .gn_util import B, _iface

GROUP = "LL-uvTube"
VERSION = 3
_VERSION_KEY = "livinglacquer_uvtube_version"
TARGET_KEY = "livinglacquer_uvtube_target"    # tube curve object: the mesh it goes into
SEAM_KEY = "livinglacquer_uvtube_seam"        # tube curve object: the side the seam runs along
MOD = "uvTube"
UV = "uv_normal"
INPUTS = ("Sides", "Segments", "Radius", "Smooth", "Adaptive", "Caps")
SIMPLIFY = 0.01                 # to Bezier: how far from the points it may go, of the chain's length
BEZIER_STEPS = 4                # back from Bezier: points per span
_ATTR_U, _ATTR_V, _ATTR_LEN, _ATTR_ID = "uvt_u", "uvt_v", "uvt_len", "uvt_id"
_CURVE_ATTRS = ("radius", "tilt", "resolution", "cyclic", "curve_type", "normal_mode",
                "nurbs_weight", "nurbs_order", "knots_mode", "handle_left", "handle_right",
                "handle_type_left", "handle_type_right")


# ---------------------------------------------------------------- the node group

def _store(b, geo, name, value, loc):
    s = b.n("GeometryNodeStoreNamedAttribute", loc, data_type='FLOAT', domain='POINT')
    s.inputs["Name"].default_value = name
    b.link(geo, s.inputs["Geometry"])
    b.link(value, s.inputs["Value"])
    return s.outputs["Geometry"]


def ensure_group():
    ng = bpy.data.node_groups.get(GROUP)
    if ng is not None and ng.get(_VERSION_KEY) == VERSION:
        return ng
    kept = [(m, {n: get_input(m, n) for n in INPUTS}) for m in _modifiers_of(ng)]
    if ng is None:
        ng = bpy.data.node_groups.new(GROUP, 'GeometryNodeTree')
    else:                       # rebuilt in place: modifiers keep their reference
        ng.nodes.clear()
        ng.interface.clear()
    ng.is_modifier = True
    ng[_VERSION_KEY] = VERSION
    _iface(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _iface(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    _iface(ng, "Sides", "INPUT", "NodeSocketInt", 8, 3, 64, single=True)
    _iface(ng, "Segments", "INPUT", "NodeSocketInt", 16, 1, 1000, single=True)
    _iface(ng, "Radius", "INPUT", "NodeSocketFloat", 0.02, 0.0, single=True)
    _iface(ng, "Smooth", "INPUT", "NodeSocketBool", True, single=True)
    _iface(ng, "Caps", "INPUT", "NodeSocketBool", False, single=True)
    _iface(ng, "Adaptive", "INPUT", "NodeSocketBool", True, single=True)
    b = B(ng)
    gi = b.n("NodeGroupInput", (-1000, 0))
    go = b.n("NodeGroupOutput", (900, 0))

    # the path: smoothed (Catmull-Rom through the points) or as drawn, Bezier keeping its handles
    st = b.n("GeometryNodeCurveSplineType", (-800, 120), spline_type='CATMULL_ROM')
    b.link(gi.outputs["Geometry"], st.inputs["Curve"])
    kind = b.n("GeometryNodeInputNamedAttribute", (-1200, 120), data_type='INT')
    kind.inputs["Name"].default_value = "curve_type"
    b.link(b.math('GREATER_THAN', b.math('ABSOLUTE', b.math('SUBTRACT', kind.outputs["Attribute"], 2.0, (-1100, 120)),
                                         None, (-1000, 120)), 0.5, (-900, 120)), st.inputs["Selection"])
    sw = b.n("GeometryNodeSwitch", (-600, 60), input_type='GEOMETRY')
    b.link(gi.outputs["Smooth"], sw.inputs["Switch"])
    b.link(gi.outputs["Geometry"], sw.inputs["False"])
    b.link(st.outputs["Curve"], sw.inputs["True"])
    # even: resampled by count
    count = b.n("GeometryNodeSwitch", (-600, -120), input_type='INT')
    b.link(b.n("GeometryNodeInputSplineCyclic", (-800, -120)).outputs["Cyclic"],
           count.inputs["Switch"])
    b.link(b.math('ADD', gi.outputs["Segments"], 1.0, (-800, -220)), count.inputs["False"])
    b.link(gi.outputs["Segments"], count.inputs["True"])
    rs = b.n("GeometryNodeResampleCurve", (-400, 60))
    rs.inputs["Mode"].default_value = 'Count'
    b.link(sw.outputs["Output"], rs.inputs["Curve"])
    b.link(count.outputs["Output"], rs.inputs["Count"])

    # Adaptive: Segments shared out over the spans, floor(S (k + 1) / n) - floor(S k / n) rings each
    cop = b.n("GeometryNodeCurveOfPoint", (-1000, -700))
    poc = b.n("GeometryNodePointsOfCurve", (-800, -800))
    b.link(cop.outputs["Curve Index"], poc.inputs["Curve Index"])
    spans = b.n("GeometryNodeSwitch", (-600, -800), input_type='INT')
    b.link(b.n("GeometryNodeInputSplineCyclic", (-800, -950)).outputs["Cyclic"], spans.inputs["Switch"])
    b.link(b.math('SUBTRACT', poc.outputs["Total"], 1.0, (-800, -1050)), spans.inputs["False"])
    b.link(poc.outputs["Total"], spans.inputs["True"])
    k = cop.outputs["Index in Curve"]
    upto = lambda i, y: b.math('FLOOR', b.math('DIVIDE', b.math('MULTIPLY', gi.outputs["Segments"], i, (-600, y)),
                                               spans.outputs["Output"], (-400, y)), None, (-200, y))
    cuts = b.math('SUBTRACT', b.math('SUBTRACT', upto(b.math('ADD', k, 1.0, (-800, -600)), -600), upto(k, -700),
                                     (0, -650)), 1.0, (200, -650))
    sub = b.n("GeometryNodeSubdivideCurve", (-400, 300))
    b.link(sw.outputs["Output"], sub.inputs["Curve"])
    b.link(cuts, sub.inputs["Cuts"])
    poly = b.n("GeometryNodeCurveSplineType", (-300, 300), spline_type='POLY')
    b.link(sub.outputs["Curve"], poly.inputs["Curve"])
    way = b.n("GeometryNodeSwitch", (-250, 150), input_type='GEOMETRY')
    b.link(gi.outputs["Adaptive"], way.inputs["Switch"])
    b.link(rs.outputs["Curve"], way.inputs["False"])
    b.link(poly.outputs["Curve"], way.inputs["True"])

    # what the uv_normal layout reads: v (length along), the chain's length and index
    par = b.n("GeometryNodeSplineParameter", (-200, -160))
    path = _store(b, way.outputs["Output"], _ATTR_V, par.outputs["Length"], (-200, 60))
    path = _store(b, path, _ATTR_LEN,
                  b.n("GeometryNodeSplineLength", (0, -160)).outputs["Length"], (0, 60))
    idx = b.n("GeometryNodeFieldOnDomain", (200, -160), domain='CURVE', data_type='FLOAT')
    b.link(b.n("GeometryNodeInputIndex", (0, -260)).outputs["Index"], idx.inputs[0])
    path = _store(b, path, _ATTR_ID, idx.outputs[0], (200, 60))

    # the profile: a circle, u = 0..1 around it
    circle = b.n("GeometryNodeCurvePrimitiveCircle", (-200, -400), mode='RADIUS')
    b.link(gi.outputs["Sides"], circle.inputs["Resolution"])
    b.link(gi.outputs["Radius"], circle.inputs["Radius"])
    prof = _store(b, circle.outputs["Curve"], _ATTR_U,
                  b.n("GeometryNodeSplineParameter", (0, -500)).outputs["Factor"], (200, -400))

    ctm = b.n("GeometryNodeCurveToMesh", (500, 0))
    b.link(path, ctm.inputs["Curve"])
    b.link(prof, ctm.inputs["Profile Curve"])
    b.link(b.n("GeometryNodeInputRadius", (300, -200)).outputs["Radius"], ctm.inputs["Scale"])
    b.link(gi.outputs["Caps"], ctm.inputs["Fill Caps"])
    b.link(ctm.outputs["Mesh"], go.inputs["Geometry"])
    for mod, values in kept:    # the new sockets are new inputs: the values come back
        for name, value in values.items():
            if value is not None:
                set_input(mod, name, value)
        if values["Adaptive"] is None:     # a tube from before Adaptive: on, as new ones
            set_input(mod, "Adaptive", True)
    return ng


def _modifiers_of(ng):
    if ng is None:
        return []
    return [m for o in bpy.data.objects for m in o.modifiers if m.type == 'NODES' and m.node_group == ng]


def _upgrade(*_args):
    """A tube opened with an older add-on gets the nodes of this one."""
    tubes = [o for o in bpy.data.objects if o.type == 'CURVE' and TARGET_KEY in o]
    if tubes:
        ensure_group()
    for tube in tubes:
        for spl in tube.data.splines:
            _one_sided_ends(spl)
        tube.data.update_tag()
    return None


@bpy.app.handlers.persistent
def _on_load(*_args):
    _upgrade()


# ---------------------------------------------------------------- modifier inputs

def modifier(obj):
    return obj.modifiers.get(MOD) if obj is not None else None


def _input(mod, name):
    item = mod.node_group.interface.items_tree.get(name) if mod is not None and mod.node_group else None
    return getattr(mod.properties.inputs, item.identifier) if item is not None else None


def get_input(mod, name):
    inp = _input(mod, name)
    return inp.value if inp is not None else None


def set_input(mod, name, value):
    inp = _input(mod, name)
    if inp is not None:
        inp.value = value


def draw_input(layout, mod, name):
    inp = _input(mod, name)
    if inp is not None:
        layout.prop(inp, "value", text=name)


# ---------------------------------------------------------------- the session

def session_object(context):
    """The active object when it is an open uvTube curve, else None."""
    obj = context.active_object
    return obj if obj is not None and obj.type == 'CURVE' and TARGET_KEY in obj else None


def open_tube(context):
    """The open uvTube curve of the view layer, active or not (a click in Object Mode may have
    selected something else)."""
    tube = session_object(context)
    if tube is not None:
        return tube
    return next((o for o in context.view_layer.objects if o.type == 'CURVE' and TARGET_KEY in o), None)


def seam_side(tube):
    mod = modifier(tube)
    sides = get_input(mod, "Sides") if mod is not None else None
    return int(tube.get(SEAM_KEY, 0)) % max(1, sides or 1)


def set_seam_side(tube, side):
    mod = modifier(tube)
    tube[SEAM_KEY] = side % max(1, get_input(mod, "Sides") or 1)
    _tag_redraw()


def is_bezier(tube):
    """Read from the curve itself: undo restores its splines."""
    return tube is not None and any(s.type == 'BEZIER' for s in tube.data.splines)


def _simplify(pts, tol):
    """The indices of pts to keep so the line stays within tol (Ramer-Douglas-Peucker)."""
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        line = pts[b] - pts[a]
        n = line.length_squared

        def dist(i):
            d = pts[i] - pts[a]
            return (d - line * (d.dot(line) / n)).length if n > 0 else d.length

        i = max(range(a + 1, b), key=dist)
        if dist(i) > tol:
            keep.add(i)
            stack += [(a, i), (i, b)]
    return sorted(keep)


def _to_bezier_points(spl):
    """A chain as few points with handles: [(co, left, right, radius)]."""
    if spl.type == 'BEZIER':
        return [(p.co.copy(), p.handle_left.copy(), p.handle_right.copy(), p.radius) for p in spl.bezier_points]
    pts = [Vector(p.co[:3]) for p in spl.points]
    radii = [p.radius for p in spl.points]
    closed = spl.use_cyclic_u
    if closed:                  # two open halves, from the start and the point farthest from it
        far = max(range(len(pts)), key=lambda i: (pts[i] - pts[0]).length)
        run = pts + pts[:1]
        length = sum((q - p).length for p, q in zip(run, run[1:]))
        tol = length * SIMPLIFY
        keep = _simplify(pts[:far + 1], tol) + [far + i for i in _simplify(run[far:], tol)[1:-1]]
    else:
        length = sum((q - p).length for p, q in zip(pts, pts[1:]))
        keep = _simplify(pts, length * SIMPLIFY)
    out, n = [], len(keep)
    for j, i in enumerate(keep):
        prev = pts[keep[j - 1]] if closed or j > 0 else pts[i]
        nxt = pts[keep[(j + 1) % n]] if closed or j < n - 1 else pts[i]
        t = (nxt - prev).normalized()
        out.append((pts[i], pts[i] - t * (pts[i] - prev).length / 3, pts[i] + t * (nxt - pts[i]).length / 3, radii[i]))
    return out


def _one_sided_ends(spl):
    """The ends of an open Bezier chain get one handle, along the tube: free, as an aligned pair with a zero
    side makes Blender throw the other side a unit away. Ends already free are the user's."""
    bp = spl.bezier_points
    if spl.type != 'BEZIER' or spl.use_cyclic_u or len(bp) < 2:
        return
    for p, other, inner, outer in ((bp[0], bp[1], "handle_right", "handle_left"),
                                   (bp[-1], bp[-2], "handle_left", "handle_right")):
        if p.handle_left_type == 'FREE' and p.handle_right_type == 'FREE':
            continue
        p.handle_left_type = p.handle_right_type = 'FREE'
        if (getattr(p, inner) - p.co).length < 1e-6:
            setattr(p, inner, p.co + (other.co - p.co) / 3)
        setattr(p, outer, p.co.copy())


def _to_poly_points(spl):
    """A chain as points along it: [(co, radius)]."""
    if spl.type != 'BEZIER':
        return [(Vector(p.co[:3]), p.radius) for p in spl.points]
    bp = list(spl.bezier_points)
    out = []
    pairs = list(zip(bp, bp[1:] + bp[:1] if spl.use_cyclic_u else bp[1:]))
    for a, b in pairs:
        line = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, BEZIER_STEPS + 1)
        for i, co in enumerate(line[:-1]):
            out.append((co, a.radius + (b.radius - a.radius) * i / BEZIER_STEPS))
    if not spl.use_cyclic_u:
        out.append((bp[-1].co.copy(), bp[-1].radius))
    return out


def set_bezier(context, tube, on):
    """The tube's points as Bezier (few, with handles) or as Poly again; the mode stays."""
    if is_bezier(tube) == on:
        return
    shaping = context.mode == 'EDIT_CURVE'
    set_mode(context, tube, 'OBJECT')
    cd = tube.data
    if on:
        chains = [(_to_bezier_points(s), s.use_cyclic_u) for s in cd.splines]
    else:
        chains = [(_to_poly_points(s), s.use_cyclic_u) for s in cd.splines]
    cd.splines.clear()
    for points, cyclic in chains:
        spl = cd.splines.new('BEZIER' if on else 'POLY')
        if on:
            spl.bezier_points.add(len(points) - 1)
            for bp, (co, left, right, radius) in zip(spl.bezier_points, points):
                bp.handle_left_type = bp.handle_right_type = 'ALIGNED'
                bp.co, bp.handle_left, bp.handle_right, bp.radius = co, left, right, radius
            _one_sided_ends(spl)
        else:
            spl.points.add(len(points) - 1)
            for p, (co, radius) in zip(spl.points, points):
                p.co = (*co, 1.0)
                p.radius = radius
        spl.use_cyclic_u = cyclic
    cd.update_tag()
    tube.update_tag()
    if shaping:
        set_mode(context, tube, 'EDIT')
        bpy.ops.curve.select_all(action='SELECT')


def set_mode(context, tube, mode):
    """The tube alone selected and active: 'OBJECT' moves it whole, 'EDIT' shapes its points."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.view_layer.objects.selected:
        o.select_set(False)
    tube.select_set(True)
    context.view_layer.objects.active = tube
    if mode == 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')


def _chains(edges):
    """`edges` as vertex chains [(verts, cyclic)]: split at their ends and forks."""
    link = {}
    for e in edges:
        for v in e.verts:
            link.setdefault(v, []).append(e)
    left, out = set(edges), []

    def walk(v, e):
        chain = [v]
        while True:
            left.discard(e)
            v = e.other_vert(v)
            chain.append(v)
            nxt = [g for g in link[v] if g in left]
            if len(link[v]) != 2 or not nxt:
                return chain
            e = nxt[0]

    for v, es in link.items():          # open chains: from every end / fork
        if len(es) != 2:
            for e in es:
                if e in left:
                    out.append((walk(v, e), False))
    while left:                         # what is left are loops
        e = next(iter(left))
        chain = walk(e.verts[0], e)
        out.append((chain[:-1], True))
    return out


def start(context, mesh_obj):
    """The selected edges of `mesh_obj` (Edit Mode) to a tube curve in Edit Mode. Returns the
    curve object, or raises ValueError."""
    bm = bmesh.from_edit_mesh(mesh_obj.data)
    edges = [e for e in bm.edges if e.select]
    if not edges:
        raise ValueError("Select edges first")
    chains = _chains(edges)
    mean = sum(e.calc_length() for e in edges) / len(edges)
    longest = max(len(c) - (0 if cyc else 1) for c, cyc in chains)

    cd = bpy.data.curves.new(f"uvTube_{mesh_obj.name}", 'CURVE')
    cd.dimensions = '3D'
    for verts, cyclic in chains:
        spl = cd.splines.new('POLY')
        spl.points.add(len(verts) - 1)
        for p, v in zip(spl.points, verts):
            p.co = (*v.co, 1.0)
            p.radius = 1.0
        spl.use_cyclic_u = cyclic
    tube = bpy.data.objects.new(cd.name, cd)
    tube.matrix_world = mesh_obj.matrix_world.copy()
    tube[TARGET_KEY] = mesh_obj.name
    (mesh_obj.users_collection or (context.scene.collection,))[0].objects.link(tube)
    mod = tube.modifiers.new(MOD, 'NODES')
    mod.node_group = ensure_group()
    set_input(mod, "Segments", max(4, longest * 2))
    set_input(mod, "Radius", max(0.001, mean * 0.15))

    bpy.ops.object.mode_set(mode='OBJECT')          # the mesh's edits written
    for o in context.view_layer.objects.selected:
        o.select_set(False)
    tube.select_set(True)
    context.view_layer.objects.active = tube
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.curve.select_all(action='SELECT')
    return tube


def _back_to(context, mesh_obj):
    """`mesh_obj` active and in Edit Mode again."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in context.view_layer.objects.selected:
        o.select_set(False)
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj
    bpy.ops.object.mode_set(mode='EDIT')


def _remove(tube):
    cd = tube.data
    bpy.data.objects.remove(tube)
    if cd.users == 0:
        bpy.data.curves.remove(cd)


def cancel(context, tube):
    mesh_obj = bpy.data.objects.get(tube.get(TARGET_KEY, ""))
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    _remove(tube)
    if mesh_obj is not None:
        _back_to(context, mesh_obj)


def _signed_area(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


def _layout_uvs(bm, radius, cyclic_ids, sides, seam):
    """uv_normal from the stored attributes; seams marked, the one along the tube on side `seam`.
    Returns the uv layer."""
    lu = bm.verts.layers.float.get(_ATTR_U)
    for v in bm.verts:              # u = 0 on the seam
        v[lu] = ((round(v[lu] * sides) - seam) % sides) / sides
    lv = bm.verts.layers.float.get(_ATTR_V)
    ll = bm.verts.layers.float.get(_ATTR_LEN)
    li = bm.verts.layers.float.get(_ATTR_ID)
    uv = bm.loops.layers.uv.get(UV) or bm.loops.layers.uv.new(UV)
    circ = 2 * math.pi * max(radius, 1e-6)
    gap = circ * 0.1

    def is_cap(f):
        vs = [v[lv] for v in f.verts]
        return max(vs) - min(vs) < 1e-7

    # per chain: [u, v] of every corner of its sleeve faces, cap faces apart
    sleeves, caps = {}, {}
    for f in bm.faces:
        k = int(round(f.verts[0][li]))
        if is_cap(f):
            caps.setdefault(k, []).append(f)
            continue
        us = [lp.vert[lu] for lp in f.loops]
        vs = [lp.vert[lv] for lp in f.loops]
        if max(us) - min(us) > 0.5:             # across the u = 0 line
            us = [u + 1 if u < 0.5 else u for u in us]
        length = f.verts[0][ll]
        if k in cyclic_ids and max(vs) - min(vs) > length / 2:     # across a loop's start
            vs = [v + length if v < length / 2 else v for v in vs]
        sleeves.setdefault(k, []).append((f, [[u * circ, v] for u, v in zip(us, vs)]))

    x = 0.0
    height = 0.0
    for k in sorted(set(sleeves) | set(caps)):
        faces = sleeves.get(k, [])
        if faces:       # mirrored against the faces' winding: u runs the other way
            f0, pts = faces[0]
            if _signed_area([tuple(p) for p in pts]) < 0:
                for _f, pts in faces:
                    for p in pts:
                        p[0] = circ - p[0]
            for f, pts in faces:
                for lp, (u, v) in zip(f.loops, pts):
                    lp[uv].uv = (x + u, v)
                height = max(height, max(p[1] for p in pts))
        x += circ + gap
        y = cap_w = 0.0
        for f in caps.get(k, []):       # planar, beside the sleeve
            f.normal_update()
            n = f.normal
            t = (f.verts[1].co - f.verts[0].co).normalized()
            bt = n.cross(t)
            c = f.calc_center_median()
            r = max(((v.co - c).length for v in f.verts), default=0.0)
            for lp in f.loops:
                d = lp.vert.co - c
                lp[uv].uv = (x + r + d.dot(t), y + r + d.dot(bt))
            y += 2 * r + gap
            height = max(height, y)
            cap_w = max(cap_w, 2 * r + gap)
        x += cap_w
    scale = 1.0 / max(x - gap, height, 1e-9)     # into 0..1, square texels kept
    for f in bm.faces:
        for lp in f.loops:
            lp[uv].uv = lp[uv].uv * scale

    for e in bm.edges:
        a, b = e.verts
        cap_side = sum(is_cap(f) for f in e.link_faces) == 1
        on_u0 = a[lu] == 0.0 and b[lu] == 0.0 and a[lv] != b[lv]
        on_v0 = a[lv] == 0.0 and b[lv] == 0.0
        e.seam = cap_side or on_u0 or on_v0
    for name in (_ATTR_U, _ATTR_V, _ATTR_LEN, _ATTR_ID):    # by name: a removal moves the rest
        bm.verts.layers.float.remove(bm.verts.layers.float[name])
    return uv


def confirm(context, tube):
    """The tube into its mesh as faces (uv_normal, seams), selected; the curve goes. Returns
    the number of faces added."""
    mesh_obj = bpy.data.objects.get(tube.get(TARGET_KEY, ""))
    if mesh_obj is None or mesh_obj.type != 'MESH':
        raise ValueError("The mesh this tube goes into is gone - Cancel it")
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    mod = modifier(tube)
    radius = get_input(mod, "Radius") if mod is not None else 0.02
    cyclic = {i for i, s in enumerate(tube.data.splines) if s.use_cyclic_u}
    dg = context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tube.evaluated_get(dg))
    try:
        bm = bmesh.new()
        bm.from_mesh(me)
        added = len(bm.faces)
        if added:
            _layout_uvs(bm, radius, cyclic, get_input(mod, "Sides"), seam_side(tube))
            for f in bm.faces:
                f.select = True
                f.smooth = True
            bm.to_mesh(me)
        bm.free()
        # from where the tube stands now into the mesh's space
        to_mesh = mesh_obj.matrix_world.inverted_safe() @ tube.matrix_world
        me.transform(to_mesh)
        if to_mesh.determinant() < 0:
            me.flip_normals()
        for name in _CURVE_ATTRS:       # the curve's own attributes, carried over
            if name in me.attributes and name not in mesh_obj.data.attributes:
                me.attributes.remove(me.attributes[name])

        bm = bmesh.new()
        bm.from_mesh(mesh_obj.data)
        guides = [e for e in bm.edges if e.select and not e.link_faces]
        bmesh.ops.delete(bm, geom=guides, context='EDGES')     # wire source edges go
        for seq in (bm.verts, bm.edges, bm.faces):
            for el in seq:
                el.select = False
        if added:
            bm.from_mesh(me)        # appended (layers matched by name)
        bm.to_mesh(mesh_obj.data)
        bm.free()
    finally:
        bpy.data.meshes.remove(me)
    mesh_obj.data.update()
    _remove(tube)
    _back_to(context, mesh_obj)
    return added


# ---------------------------------------------------------------- the seam in the view

_preview = {"tube": "", "sides": 0, "lines": {}, "rings": None, "co": None, "normal": None, "side": None, "faces": 0}
_pick = {"on": False, "hover": None}
_handlers = {"draw": None}


def faces_count(tube):
    return _preview["faces"] if _preview["tube"] == tube.name else 0


def _tag_redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _segments(co, order, closed):
    """Line pairs through co[order]."""
    if len(order) < 2:
        return np.empty((0, 3), np.float32)
    a = np.append(order, order[0]) if closed else order
    return co[np.stack((a[:-1], a[1:]), axis=1).ravel()]


def _rebuild_preview(depsgraph, tube):
    """Every line along the tube and the rings that will be seams, from what the nodes made."""
    ev = tube.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        n = len(me.vertices)
        attrs = me.attributes
        mod = modifier(tube)
        sides = get_input(mod, "Sides") if mod is not None else 0
        if not n or not sides or any(a not in attrs for a in (_ATTR_U, _ATTR_V, _ATTR_ID)):
            _preview.update(tube="", lines={}, rings=None, faces=0)
            return

        def read(name):
            out = np.empty(n, np.float32)
            attrs[name].data.foreach_get("value", out)
            return out

        u, v, ids = read(_ATTR_U), read(_ATTR_V), np.rint(read(_ATTR_ID)).astype(int)
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        nor = np.empty(n * 3, np.float32)
        me.vertex_normals.foreach_get("vector", nor)
        m = np.array(ev.matrix_world, np.float32)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        nor = nor.reshape(-1, 3) @ np.linalg.inv(m[:3, :3])
        side = np.rint(u * sides).astype(int) % sides
        cyclic = {i for i, s in enumerate(tube.data.splines) if s.use_cyclic_u}
        caps = bool(get_input(mod, "Caps"))
        lines, rings = {}, []
        for k in np.unique(ids):
            here = np.flatnonzero(ids == k)
            for s in range(sides):
                idx = here[side[here] == s]
                seg = _segments(co, idx[np.argsort(v[idx])], k in cyclic)
                lines[s] = np.concatenate((lines[s], seg)) if s in lines else seg
            ends = [v[here].min()] + ([v[here].max()] if caps and k not in cyclic else [])
            for end in ends:
                idx = here[np.abs(v[here] - end) < 1e-6]
                rings.append(_segments(co, idx[np.argsort(side[idx])], True))
        _preview.update(tube=tube.name, sides=sides, lines=lines, co=co, normal=nor, side=side,
                        rings=np.concatenate(rings) if rings else None, faces=len(me.polygons))
    finally:
        ev.to_mesh_clear()


@bpy.app.handlers.persistent
def _on_depsgraph(scene, depsgraph):
    tube = next((u.id.original for u in depsgraph.updates if isinstance(u.id, bpy.types.Object)
                 and u.id.type == 'CURVE' and TARGET_KEY in u.id), None)
    if tube is not None:
        _rebuild_preview(depsgraph, tube)
    elif _preview["tube"] and _preview["tube"] not in bpy.data.objects:
        _preview.update(tube="", lines={}, rings=None, faces=0)


def _draw_lines(pts, color, width, region):
    if pts is None or not len(pts):
        return
    sh = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    sh.uniform_float("viewportSize", (region.width, region.height))
    sh.uniform_float("lineWidth", width)
    sh.uniform_float("color", color)
    batch_for_shader(sh, "LINES", {"pos": pts}).draw(sh)


def _draw_preview():
    context = bpy.context
    tube = open_tube(context)
    region = context.region
    if tube is None or region is None:
        return
    if _preview["tube"] != tube.name:       # opened or loaded since the last update
        _rebuild_preview(context.evaluated_depsgraph_get(), tube)
        if _preview["tube"] != tube.name:
            return
    seam = seam_side(tube)
    line = _preview["lines"].get(seam)
    gpu.state.blend_set("ALPHA")
    for depth, alpha in (('NONE', 0.3), ('LESS_EQUAL', 1.0)):    # behind the tube faint, in front full
        gpu.state.depth_test_set(depth)
        if _pick["on"]:
            for s, seg in _preview["lines"].items():
                if s != _pick["hover"]:
                    _draw_lines(seg, (0.3, 0.8, 1.0, 0.6 * alpha), 1.5, region)
            _draw_lines(_preview["lines"].get(_pick["hover"]), (1.0, 1.0, 1.0, alpha), 4.0, region)
        _draw_lines(line, (1.0, 0.2, 0.15, alpha), 3.0, region)
        _draw_lines(_preview["rings"], (1.0, 0.2, 0.15, 0.7 * alpha), 2.0, region)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set("NONE")


def _side_at(context, mx, my):
    """The side whose line is nearest the mouse among the points facing the view."""
    co = _preview["co"]
    if co is None or not len(co):
        return None
    r3d = context.region_data
    region = context.region
    m = np.array(r3d.perspective_matrix, np.float32)
    h = co @ m[:3, :3].T + m[:3, 3]
    w = co @ m[3, :3] + m[3, 3]
    front = w > 1e-6
    x = (h[:, 0] / np.where(front, w, 1) + 1) * region.width / 2
    y = (h[:, 1] / np.where(front, w, 1) + 1) * region.height / 2
    origin = np.array(region_2d_to_origin_3d(region, r3d, (mx, my)), np.float32)
    view = co - origin if r3d.is_perspective else np.array(r3d.view_rotation @ Vector((0, 0, -1)), np.float32)
    facing = np.sum(_preview["normal"] * view, axis=-1) < 0
    d = (x - mx) ** 2 + (y - my) ** 2
    d[~front] = np.inf
    pool = d if not np.any(facing & front) else np.where(facing, d, np.inf)
    return int(_preview["side"][int(np.argmin(pool))])


# ---------------------------------------------------------------- operators

def _status(context):
    context.workspace.status_text_set(
        "uvTube · values in the photo panel · Tab move / shape · Alt+S radius per point · "
        "Enter confirm · Esc cancel")


def _over_view3d(context, event):
    """The mouse is over a 3D Viewport: Enter and Esc elsewhere are not for the tube."""
    return any(a.type == 'VIEW_3D' and a.x <= event.mouse_x < a.x + a.width
               and a.y <= event.mouse_y < a.y + a.height for a in context.window.screen.areas)


class LIVINGLACQUER_OT_uv_tube(bpy.types.Operator):
    """Turn the selected edges into a helper tube over the mesh: move and shape it with the photos and
    the view free, set its values in the photo panel, Enter puts it into the mesh, Esc cancels"""
    bl_idname = "livinglacquer.uv_tube"
    bl_label = "uvTube"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_MESH' or not context.tool_settings.mesh_select_mode[1]:
            cls.poll_message_set("Edit Mode, edge select")
            return False
        if context.edit_object.data.total_edge_sel == 0:
            cls.poll_message_set("Select edges first")
            return False
        if open_tube(context) is not None:
            cls.poll_message_set("Confirm or cancel the open uvTube first")
            return False
        return True

    def invoke(self, context, event):
        try:
            tube = start(context, context.edit_object)
        except ValueError as e:
            self.report({'WARNING'}, str(e))
            return {'CANCELLED'}
        bpy.ops.ed.undo_push(message="uvTube start")
        self._tube = tube.name
        _status(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.workspace.status_text_set(None)

    def modal(self, context, event):
        tube = bpy.data.objects.get(self._tube)
        if tube is None or TARGET_KEY not in tube:      # confirmed / cancelled elsewhere
            self._end(context)
            return {'FINISHED'}
        if context.active_object is not tube or event.value != 'PRESS' or not _over_view3d(context, event):
            return {'PASS_THROUGH'}
        if event.type in {'RET', 'NUMPAD_ENTER'} and not (event.ctrl or event.alt):
            self._end(context)
            try:
                n = confirm(context, tube)
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            bpy.ops.ed.undo_push(message="uvTube")
            self.report({'INFO'}, f"uvTube: {n} faces added")
            return {'FINISHED'}
        if event.type == 'ESC':
            self._end(context)
            cancel(context, tube)
            bpy.ops.ed.undo_push(message="uvTube cancel")
            self.report({'INFO'}, "uvTube cancelled")
            return {'CANCELLED'}
        return {'PASS_THROUGH'}


class LIVINGLACQUER_OT_uv_tube_finish(bpy.types.Operator):
    """Confirm the uvTube (its faces into the mesh) or cancel it (the curve goes)"""
    bl_idname = "livinglacquer.uv_tube_finish"
    bl_label = "uvTube"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=(('CONFIRM', "Confirm", ""), ('CANCEL', "Cancel", "")),
                                   options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return open_tube(context) is not None

    def execute(self, context):
        tube = open_tube(context)
        if self.action == 'CANCEL':
            cancel(context, tube)
            return {'FINISHED'}
        try:
            n = confirm(context, tube)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"uvTube: {n} faces added")
        return {'FINISHED'}


class LIVINGLACQUER_OT_uv_tube_bezier(bpy.types.Operator):
    """Bezier: the tube's points become few ones with handles. Off: points along the curve again"""
    bl_idname = "livinglacquer.uv_tube_bezier"
    bl_label = "Bezier"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return open_tube(context) is not None

    def execute(self, context):
        tube = open_tube(context)
        set_bezier(context, tube, not is_bezier(tube))
        return {'FINISHED'}


class LIVINGLACQUER_OT_uv_tube_seam_pick(bpy.types.Operator):
    """Click the line along the tube that will be the seam. The view stays free, Esc keeps the seam as it is"""
    bl_idname = "livinglacquer.uv_tube_seam_pick"
    bl_label = "Pick Seam"

    @classmethod
    def poll(cls, context):
        return open_tube(context) is not None and context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        _pick.update(on=True, hover=None)
        context.window.cursor_modal_set('EYEDROPPER')
        context.workspace.status_text_set("Pick Seam · click a line along the tube · Esc: keep the seam")
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _end(self, context):
        _pick.update(on=False, hover=None)
        context.window.cursor_modal_restore()
        _status(context)
        context.area.tag_redraw()

    def modal(self, context, event):
        tube = open_tube(context)
        if tube is None or event.type in {'ESC', 'RIGHTMOUSE'}:
            self._end(context)
            return {'CANCELLED'}
        region = context.region
        inside = region is not None and 0 <= event.mouse_region_x < region.width and 0 <= event.mouse_region_y < region.height
        if event.type == 'MOUSEMOVE' and inside:
            _pick["hover"] = _side_at(context, event.mouse_region_x, event.mouse_region_y)
            context.area.tag_redraw()
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and inside:
            side = _side_at(context, event.mouse_region_x, event.mouse_region_y)
            if side is not None:
                set_seam_side(tube, side)
            self._end(context)
            return {'FINISHED'}
        return {'PASS_THROUGH'}


class LIVINGLACQUER_PT_uv_tube(bpy.types.Panel):
    """The open uvTube's values: here they can be typed in"""
    bl_label = "uvTube"
    bl_idname = "LIVINGLACQUER_PT_uv_tube"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LivingLacquer"
    bl_parent_id = "LIVINGLACQUER_PT_main"
    bl_order = -1

    @classmethod
    def poll(cls, context):
        return open_tube(context) is not None

    def draw(self, context):
        layout = self.layout
        tube = open_tube(context)
        mod = modifier(tube)
        if mod is not None:
            col = layout.column(align=True)
            for name in INPUTS:
                draw_input(col, mod, name)
        row = layout.row(align=True)
        row.operator("livinglacquer.uv_tube_bezier", text="Bezier", depress=is_bezier(tube))
        row.operator("livinglacquer.uv_tube_seam_pick", text="Pick Seam", icon='EYEDROPPER')
        row = layout.row(align=True)
        row.operator("livinglacquer.uv_tube_finish", text="Confirm", icon='CHECKMARK').action = 'CONFIRM'
        row.operator("livinglacquer.uv_tube_finish", text="Cancel", icon='X').action = 'CANCEL'


_CLASSES = (LIVINGLACQUER_OT_uv_tube, LIVINGLACQUER_OT_uv_tube_finish, LIVINGLACQUER_OT_uv_tube_bezier,
            LIVINGLACQUER_OT_uv_tube_seam_pick, LIVINGLACQUER_PT_uv_tube)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    _handlers["draw"] = bpy.types.SpaceView3D.draw_handler_add(_draw_preview, (), 'WINDOW', 'POST_VIEW')
    bpy.app.timers.register(_upgrade, first_interval=0.1)


def unregister():
    bpy.types.SpaceView3D.draw_handler_remove(_handlers["draw"], 'WINDOW')
    bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    bpy.app.handlers.load_post.remove(_on_load)
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
