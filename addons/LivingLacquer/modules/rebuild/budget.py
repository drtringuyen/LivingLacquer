"""The triangle budget, as MultiCamProject's Polycount Estimation: the budget split over the EXPORT collection's
meshes by world-space surface area, against their triangle count with modifiers. Measured on the button:
evaluating the meshes on every redraw would slow the panel."""
import bpy
import numpy as np

from . import core

ROWS = {"blend": None, "items": [], "total_tris": 0}


def _area_and_tris(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        n = len(me.loop_triangles)
        if not n:
            return 0.0, 0
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        idx = np.empty(n * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", idx)
        m = np.array(ob.matrix_world, np.float64)
        w = co @ m[:3, :3].T + m[:3, 3]
        a, b, c = (w[idx[i::3]] for i in range(3))
        return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2), n
    finally:
        ev.to_mesh_clear()


def measure(context):
    rb = context.scene.livinglacquer_rebuild
    depsgraph = context.evaluated_depsgraph_get()
    obs = [o for o in core.export_collection(context.scene).all_objects if o.type == "MESH"]
    rows = [(o.name, *_area_and_tris(o, depsgraph)) for o in obs]
    total = sum(r[1] for r in rows) or 1.0
    items = [{"name": n, "share": a / total, "budget": int(round(rb.tri_budget * a / total)), "tris": t}
             for n, a, t in rows]
    ROWS.update(blend=bpy.data.filepath, items=sorted(items, key=lambda i: -i["share"]),
                total_tris=sum(i["tris"] for i in items))
    return ROWS


def short(n):
    """150000 -> '150K', 2400 -> '2.4K', 830 -> '830'."""
    if abs(n) >= 100000:
        return f"{n // 1000}K"
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)
