"""Size references drawn in the 3D Viewport (GPU overlay, not objects) beside the scan, so the user can
see how big to scale the Transform empty: a 1.7 m person, a 0.75 m table (1.2 x 0.7 m top) and a 0.30 m
cat, side by side on the floor (Z = 0), labelled. Silhouettes are drawn in two crossed planes so they
read from any side. Sizes are real metres, converted with the scene's Unit Scale."""
import bpy
import blf
import gpu
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from . import model

HEIGHT_M = 1.7                                  # person
TABLE_M = (1.2, 0.7, 0.75)                      # top width, depth, height
CAT_M = 0.30                                    # height to the ear tips
GAP_M = 0.4                                     # space between the references
FILL = (0.35, 0.65, 1.0, 0.18)
LINE = (0.35, 0.65, 1.0, 0.9)

# right half of a standing person seen from the front, height 1 (x, z), top of the head to the crotch
_HALF = [(0.0, 1.0), (0.035, 0.995), (0.06, 0.975), (0.07, 0.94), (0.065, 0.905), (0.05, 0.88), (0.03, 0.865),
         (0.03, 0.845), (0.11, 0.82), (0.15, 0.80), (0.165, 0.76), (0.18, 0.65), (0.19, 0.55), (0.19, 0.47),
         (0.17, 0.44), (0.15, 0.46), (0.15, 0.55), (0.14, 0.65), (0.12, 0.70), (0.11, 0.62), (0.105, 0.53),
         (0.11, 0.40), (0.10, 0.25), (0.09, 0.06), (0.11, 0.02), (0.11, 0.0), (0.03, 0.0), (0.03, 0.06),
         (0.035, 0.25), (0.02, 0.45), (0.0, 0.47)]
PERSON = [(x * HEIGHT_M, z * HEIGHT_M) for x, z in _HALF + [(-x, z) for x, z in reversed(_HALF[1:-1])]]
# a cat seen from the side, facing +X, in metres (tail up at the back, ears at 0.31)
CAT = [(0.00, 0.24), (0.02, 0.25), (0.05, 0.16), (0.10, 0.18), (0.25, 0.19), (0.32, 0.20), (0.34, 0.25),
       (0.355, 0.29), (0.365, 0.31), (0.38, 0.28), (0.40, 0.285), (0.41, 0.31), (0.42, 0.27), (0.44, 0.24),
       (0.43, 0.21), (0.40, 0.19), (0.37, 0.15), (0.36, 0.0), (0.33, 0.0), (0.32, 0.11), (0.14, 0.11),
       (0.12, 0.0), (0.09, 0.0), (0.08, 0.12), (0.04, 0.14), (0.03, 0.22), (0.01, 0.22)]
CAT = [(x - 0.22, z * CAT_M / 0.31) for x, z in CAT]          # centred on x = 0, ears at CAT_M


def tris(outline):
    return tessellate_polygon([[Vector((x, z, 0)) for x, z in outline]])


_PERSON_TRIS, _CAT_TRIS = tris(PERSON), tris(CAT)
_handles = []
_samples = {}          # mesh name -> (mesh data pointer, (n, 4) local points): read once per mesh


def world_box(meshes):
    """World min / max of the mesh vertices (a rotated object's bound_box is too big). The vertex sample
    is read once per mesh; each redraw only multiplies it by the matrix, so scaling stays smooth."""
    pts = []
    for m in meshes:
        key = m.data.as_pointer() if m.data else 0
        if _samples.get(m.name, (None,))[0] != key:
            s = model.sample_vertices(m, 12000)
            _samples[m.name] = (key, np.c_[s, np.ones(len(s))])
        local = _samples[m.name][1]
        pts.append((local @ np.array(m.matrix_world).T)[:, :3])
    pts = np.vstack(pts)
    return pts.min(0), pts.max(0)


def _placement(context):
    """(where the person stands, Blender units per metre). Beside the scan mesh, feet on Z = 0."""
    u = 1.0 / (context.scene.unit_settings.scale_length or 1.0)
    rig = bpy.data.objects.get("Transform")
    meshes = [o for o in (rig.children if rig else []) if o.type == "MESH" and o.visible_get()]
    if not meshes:
        return Vector((0.6 * u, 0, 0)), u
    lo, hi = world_box(meshes)
    return Vector((float(hi[0]) + 0.5 * u, float(lo[1] + hi[1]) / 2, 0.0)), u


def _layout(context):
    """Origins (feet / floor centre) of person, table and cat, units per metre, and the labels."""
    person, u = _placement(context)
    w, d, h = TABLE_M
    table = person + Vector(((0.25 + GAP_M + w / 2) * u, 0, 0))
    cat = table + Vector(((w / 2 + GAP_M + 0.22) * u, 0, 0))
    labels = [(person + Vector((0, 0, HEIGHT_M * 1.04 * u)), f"person {HEIGHT_M:.2f} m"),
              (table + Vector((0, 0, (h + 0.08) * u)), f"table {h:.2f} m  ({w:.1f} x {d:.1f} m)"),
              (cat + Vector((0, 0, (CAT_M + 0.06) * u)), f"cat {CAT_M:.2f} m")]
    return person, table, cat, u, labels


def _shown(context):
    props = getattr(context.scene, "livinglacquer_props", None)
    return props is not None and props.pipe_show_human


def _silhouette(flat, line, outline, tris, origin, u):
    """outline (metres, x / z) in the XZ plane and, crossed, in the YZ plane through origin."""
    for to3d in (lambda x, z: origin + Vector((x * u, 0, z * u)), lambda x, z: origin + Vector((0, x * u, z * u))):
        verts = [to3d(x, z) for x, z in outline]
        flat.bind()
        flat.uniform_float("color", FILL)
        batch_for_shader(flat, "TRIS", {"pos": verts}, indices=tris).draw(flat)
        line.bind()
        line.uniform_float("color", LINE)
        batch_for_shader(line, "LINE_LOOP", {"pos": verts}).draw(line)


def _table(flat, line, origin, u):
    """Top slab (filled) and four legs."""
    w, d, h = (v * u for v in TABLE_M)
    t = 0.04 * u
    c = [origin + Vector((sx * w / 2, sy * d / 2, 0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    top = [p + Vector((0, 0, h)) for p in c]
    under = [p + Vector((0, 0, h - t)) for p in c]
    flat.bind()
    flat.uniform_float("color", FILL)
    batch_for_shader(flat, "TRIS", {"pos": top}, indices=((0, 1, 2), (0, 2, 3))).draw(flat)
    inset = 0.05 * u
    legs = []
    for p in c:
        q = origin + (p - origin) - Vector((np.sign(p.x - origin.x) * inset, np.sign(p.y - origin.y) * inset, 0))
        legs += [q, q + Vector((0, 0, h - t))]
    edges = []
    for ring in (top, under):
        for i in range(4):
            edges += [ring[i], ring[(i + 1) % 4]]
    edges += [p for i in range(4) for p in (top[i], under[i])]
    line.bind()
    line.uniform_float("color", LINE)
    batch_for_shader(line, "LINES", {"pos": edges + legs}).draw(line)


def _draw_3d():
    context = bpy.context
    if not _shown(context):
        return
    person, table, cat, u, _labels = _layout(context)
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    flat = gpu.shader.from_builtin("UNIFORM_COLOR")
    line = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    line.bind()
    line.uniform_float("viewportSize", (context.region.width, context.region.height))
    line.uniform_float("lineWidth", 2.0)
    _silhouette(flat, line, PERSON, _PERSON_TRIS, person, u)
    _table(flat, line, table, u)
    _silhouette(flat, line, CAT, _CAT_TRIS, cat, u)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def _draw_2d():
    context = bpy.context
    if not _shown(context) or context.region_data is None:
        return
    font = 0
    blf.size(font, 14)
    blf.color(font, *LINE[:3], 1.0)
    for pos, text in _layout(context)[4]:
        p = location_3d_to_region_2d(context.region, context.region_data, pos)
        if p is None:
            continue
        w, _ = blf.dimensions(font, text)
        blf.position(font, p.x - w / 2, p.y, 0)
        blf.draw(font, text)


def register():
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_3d, (), "WINDOW", "POST_VIEW"))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_2d, (), "WINDOW", "POST_PIXEL"))


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
