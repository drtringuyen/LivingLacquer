"""Auto Seams: Blender's own Bevel, Extrude and Inset run untouched; when one finishes (hotkey, menu, tool, Adjust Last
Operation) the seams are put right.

Bevel: a seam turns into two, one on each rail of the strip: one rail is cleared, the left one seen from outside, on a
level strip the lower.
Extrude, Inset (face select): no new ring seams, the rings are where Mark Seam put them; one seam across the walls or
the inset strip, going on from the seam below when there is one, so they unfold as one island.
Auto UV: uv_normal unwrapped after each.

An undo step holds the mesh as the operator left it, before this ran, so landing on it by undo or redo puts the seams
back: Ctrl+Z over the operator itself goes to the mesh before it."""
import bmesh
import bpy
from mathutils import Vector

from ..project import prefs
from . import uv_tools

EXTRUDES = {"MESH_OT_extrude_region_move", "MESH_OT_extrude_context_move", "MESH_OT_extrude_region_shrink_fatten"}
KEEP = 64           # how many finished results are remembered for undo / redo
TICK = 0.1          # seconds between looks for a finished operator

_last = None        # (the operator and its settings, the mesh's edge count) last seen
_results = {}       # the mesh as an operator left it: (its seams after this module, unwrap)


# ---------------------------------------------------------------- Bevel

def _ladders(faces):
    """The quads' edges grouped by going across to the opposite edge, again and again: one group per row of the strip
    along it and one across it. {edge: group}"""
    groups = {}
    for f in faces:
        if len(f.edges) != 4:
            continue
        loops = list(f.loops)
        for a, b in ((loops[0].edge, loops[2].edge), (loops[1].edge, loops[3].edge)):
            ga, gb = groups.setdefault(a, {a}), groups.setdefault(b, {b})
            if ga is not gb:
                ga |= gb
                for e in gb:
                    groups[e] = ga
    return groups


def _size(group, rim):
    edges = [e for e in group if e in rim] or list(group)
    return sum(e.calc_length() for e in edges) / len(edges)


def _rails(faces, segments):
    """The seams along a strip of bevel `faces`. An along row crosses the strip, so it has segments + 1 edges and two on
    the strip's rim; when a row across happens to have as many, the longer of the two is the one along."""
    groups, rim = _ladders(faces), uv_tools.rim(faces)
    along = {id(g): g for g in groups.values() if len(g) == segments + 1}
    out = set()
    for g in along.values():
        ends = [e for e in g if e in rim]
        if len(ends) != 2 or not all(e.seam for e in ends):
            continue
        quad = next((f for f in ends[0].link_faces if f in faces and len(f.edges) == 4), None)
        if quad is None:
            continue
        other = next(groups[e] for e in quad.edges if groups[e] is not g)
        if id(other) in along and _size(other, rim) > _size(g, rim):
            continue
        out.update(ends)
    return out


def _kept(rails, faces):
    """Which of a strip's rails stays. Each rail: a connected list of edges."""
    normal = sum((f.normal for f in faces), Vector()).normalized()
    left = normal.cross(Vector((0, 0, 1)))

    def mid(rail):
        return sum((v.co for e in rail for v in e.verts), Vector()) / (2 * len(rail))
    a, b = rails
    side = (mid(a) - mid(b)).dot(left)
    if abs(side) > 0.3 * (mid(a) - mid(b)).length:
        return a if side > 0 else b
    return a if mid(a).z < mid(b).z else b


def one_rail(bm, segments):
    """Every selected strip keeps one of its two rails. Strips where seams meet (more than two rails) stay as they are."""
    for faces in uv_tools._regions([f for f in bm.faces if f.select]):
        rails = uv_tools._edge_groups(_rails(faces, segments))
        if len(rails) == 2:
            keep = _kept(rails, faces)
            dropped = rails[0] if rails[1] is keep else rails[1]
            ends = {v for e in dropped for v in e.verts}
            for e in dropped:
                e.seam = False
            # where a seam goes on past the strip, Bevel's end is a cap with a seam to each rail: only the kept one stays
            for f in faces:
                if len(f.edges) != 4:
                    for e in f.edges:
                        if any(v in ends for v in e.verts):
                            e.seam = False


# ---------------------------------------------------------------- Extrude, Inset

def walls_of(bm):
    """Each selected region (the moved top, the inset's inner faces): no seam inside it or on its ring, one seam across
    the faces around it going on from the seam below; the ring below stays as it was (a seam if marked: Mark Seam)."""
    for top in uv_tools._regions([f for f in bm.faces if f.select]):
        ring = uv_tools.rim(top)
        walls = {f for e in ring for f in e.link_faces if f not in top}
        if not walls:
            continue
        for f in top:
            for e in f.edges:
                e.seam = False
        wall_edges = {e for f in walls for e in f.edges}
        base = {v for f in walls for v in f.verts} - {v for f in top for v in f.verts}
        bm.verts.index_update()
        below = {v.index for v in base if any(e.seam and e not in wall_edges for e in v.link_edges)}
        for e in wall_edges:
            if not all(v in base for v in e.verts):
                e.seam = False
        uv_tools.wall_seams(bm, below=below, top=top, mark_base=False)


# ---------------------------------------------------------------- the watch

def _values(props):
    """An operator's settings as something to compare, a macro's parts included."""
    out = []
    for p in props.bl_rna.properties:
        if p.identifier == "rna_type":
            continue
        v = getattr(props, p.identifier)
        if hasattr(v, "bl_rna"):
            v = _values(v)
        elif hasattr(v, "__len__") and not isinstance(v, str):
            v = tuple(v)
        elif isinstance(v, set):
            v = tuple(sorted(v))
        out.append(v)
    return tuple(out)


def _state(obj, bm):
    bm.edges.index_update()
    return (obj.name, len(bm.verts), len(bm.edges), len(bm.faces), tuple(e.index for e in bm.edges if e.seam),
            tuple(f.index for f in bm.faces if f.select))


def _seam_setting(name):
    p = prefs.get()
    return name == "auto_seams" if p is None else getattr(p, name)


def _unwrap():
    obj = bpy.context.edit_object
    if obj is not None and obj.type == 'MESH':
        uv_tools.unwrap_all(bpy.context, obj)
    return None


def _fix(op, bm):
    if op.bl_idname == "MESH_OT_bevel":
        if op.properties.affect == 'EDGES':
            one_rail(bm, op.properties.segments)
    elif bpy.context.tool_settings.mesh_select_mode[2]:
        walls_of(bm)


def _watched(idname):
    return idname == "MESH_OT_bevel" or idname == "MESH_OT_inset" or idname in EXTRUDES


def _busy(wm):
    """One of the tools is still running: the mesh is theirs, and the last finished operator says nothing about it."""
    return any(_watched(o.bl_idname) or o.bl_idname.startswith("TRANSFORM_OT")
               for win in wm.windows for o in getattr(win, "modal_operators", ()))


def _check():
    global _last
    c = bpy.context
    wm = c.window_manager
    if c.mode != 'EDIT_MESH' or wm is None:
        return
    if not wm.operators:        # an undo empties the list: what comes next is new, whatever it looks like
        _last = None
        return
    op = wm.operators[-1]
    if not _watched(op.bl_idname) or _busy(wm):
        return
    run = (op.as_pointer(), _values(op.properties))
    obj = c.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    count = len(bm.edges)
    # new settings or more edges: it has just run. The same settings with fewer edges: an undo, nothing to do
    fresh = _last is None or _last[0] != run or count > _last[1]
    _last = run, count
    if not fresh or not _seam_setting("auto_seams"):
        return
    raw = _state(obj, bm)
    _fix(op, bm)
    bm.edges.index_update()
    unwrap = _seam_setting("auto_uv")
    while len(_results) >= KEEP:
        del _results[next(iter(_results))]
    _results[raw] = {e.index for e in bm.edges if e.seam}, unwrap
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    if unwrap:
        bpy.app.timers.register(_unwrap, first_interval=0.0)


@bpy.app.handlers.persistent
def _on_depsgraph(*_):
    _check()


def _tick():
    """A confirm after a drag changes nothing, so no depsgraph update tells of it."""
    _check()
    return TICK


@bpy.app.handlers.persistent
def _on_undo(*_):
    c = bpy.context
    if c.mode != 'EDIT_MESH' or not _results:
        return
    obj = c.edit_object
    bm = bmesh.from_edit_mesh(obj.data)
    found = _results.get(_state(obj, bm))
    if found is None:
        return
    seams, unwrap = found
    for e in bm.edges:
        e.seam = e.index in seams
    bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    if unwrap:
        bpy.app.timers.register(_unwrap, first_interval=0.0)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.undo_post.append(_on_undo)
    bpy.app.handlers.redo_post.append(_on_undo)
    bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers, f in ((bpy.app.handlers.redo_post, _on_undo), (bpy.app.handlers.undo_post, _on_undo),
                        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph)):
        if f in handlers:
            handlers.remove(f)
    _results.clear()
    if bpy.app.timers.is_registered(_unwrap):
        bpy.app.timers.unregister(_unwrap)
