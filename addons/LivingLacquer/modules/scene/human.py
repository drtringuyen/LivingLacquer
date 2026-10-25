"""A 1.7 m person drawn in the 3D Viewport (GPU overlay, not an object) next to the scan, so the user
can see how big to scale the Transform empty. Two crossed silhouettes, so it reads from any side; it
stands on the floor (Z = 0), just beside the scan. Respects the scene's Unit Scale."""
import bpy
import blf
import gpu
import numpy as np
from bpy_extras.view3d_utils import location_3d_to_region_2d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from . import model

HEIGHT_M = 1.7
FILL = (0.35, 0.65, 1.0, 0.18)
LINE = (0.35, 0.65, 1.0, 0.9)

# right half of a standing person seen from the front, height 1 (x, z), top of the head to the crotch
_HALF = [(0.0, 1.0), (0.035, 0.995), (0.06, 0.975), (0.07, 0.94), (0.065, 0.905), (0.05, 0.88), (0.03, 0.865),
         (0.03, 0.845), (0.11, 0.82), (0.15, 0.80), (0.165, 0.76), (0.18, 0.65), (0.19, 0.55), (0.19, 0.47),
         (0.17, 0.44), (0.15, 0.46), (0.15, 0.55), (0.14, 0.65), (0.12, 0.70), (0.11, 0.62), (0.105, 0.53),
         (0.11, 0.40), (0.10, 0.25), (0.09, 0.06), (0.11, 0.02), (0.11, 0.0), (0.03, 0.0), (0.03, 0.06),
         (0.035, 0.25), (0.02, 0.45), (0.0, 0.47)]
OUTLINE = _HALF + [(-x, z) for x, z in reversed(_HALF[1:-1])]
_TRIS = tessellate_polygon([[Vector((x, z, 0)) for x, z in OUTLINE]])
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
    """(base point, height in Blender units) beside the scan mesh, or beside the origin."""
    h = HEIGHT_M / (context.scene.unit_settings.scale_length or 1.0)
    rig = bpy.data.objects.get("Transform")
    meshes = [o for o in (rig.children if rig else []) if o.type == "MESH" and o.visible_get()]
    if not meshes:
        return Vector((h * 0.4, 0, 0)), h
    lo, hi = world_box(meshes)
    return Vector((float(hi[0]) + h * 0.3, float(lo[1] + hi[1]) / 2, 0.0)), h      # feet on the floor (Z = 0)


def _shown(context):
    props = getattr(context.scene, "livinglacquer_props", None)
    return props is not None and props.pipe_show_human


def _draw_3d():
    context = bpy.context
    if not _shown(context):
        return
    base, h = _placement(context)
    planes = [lambda x, z: base + Vector((x * h, 0, z * h)), lambda x, z: base + Vector((0, x * h, z * h))]
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    flat = gpu.shader.from_builtin("UNIFORM_COLOR")
    line = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    region = context.region
    for to3d in planes:
        verts = [to3d(x, z) for x, z in OUTLINE]
        batch = batch_for_shader(flat, "TRIS", {"pos": verts}, indices=_TRIS)
        flat.bind()
        flat.uniform_float("color", FILL)
        batch.draw(flat)
        line.bind()
        line.uniform_float("viewportSize", (region.width, region.height))
        line.uniform_float("lineWidth", 2.0)
        line.uniform_float("color", LINE)
        batch_for_shader(line, "LINE_LOOP", {"pos": verts}).draw(line)
    # height bar with a tick at the top
    bar = [base + Vector((-0.3 * h, 0, 0)), base + Vector((-0.3 * h, 0, h)),
           base + Vector((-0.35 * h, 0, h)), base + Vector((-0.25 * h, 0, h))]
    batch_for_shader(line, "LINES", {"pos": bar}).draw(line)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def _draw_2d():
    context = bpy.context
    if not _shown(context) or context.region_data is None:
        return
    base, h = _placement(context)
    p = location_3d_to_region_2d(context.region, context.region_data, base + Vector((0, 0, h * 1.04)))
    if p is None:
        return
    font = 0
    blf.size(font, 14)
    blf.color(font, *LINE[:3], 1.0)
    text = f"{HEIGHT_M:.2f} m person"
    w, _ = blf.dimensions(font, text)
    blf.position(font, p.x - w / 2, p.y, 0)
    blf.draw(font, text)


def redraw(_self=None, _context=None):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def register():
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_3d, (), "WINDOW", "POST_VIEW"))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(_draw_2d, (), "WINDOW", "POST_PIXEL"))


def unregister():
    while _handles:
        bpy.types.SpaceView3D.draw_handler_remove(_handles.pop(), "WINDOW")
