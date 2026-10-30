"""Step 5 - Mesh Rebuild: the rebuilt object, its materials, its texture files and the photo lists.

Names, for a rebuilt object called <name> (as MultiCamProject names them):
    LL_<name>   while painting: BAo_ (baked from the scan) with BAp_ (painted from the photos) over it,
                mixed by BAp_'s alpha
    MAT_<name>  final: ALB_ (BAo_ + BAp_ in one texture) and NOR_ (baked from the scan)
    uv_normal   the UV map all of them use (the object's own UV renamed; its layout is up to the user)
Files: <name>.png in the bake folder (01.Bake); a finished ALB_ / NOR_ of your own in 02.Overrides is used
with Load. Nothing is written over without asking.
"""
import os

import bpy

from ..project import paths, state

REBUILD_KEY = "ll_rebuild"          # object key: "REMESH" / "RETOPO", the object step 5 made or took
LOCKED_KEY = "ll_locked"            # object key: Lock & Export done, the textures stay as they are
EXPORTED_KEY = "ll_exported"        # object key: the FBX Lock & Export wrote
UV = "uv_normal"
PAINT, FINAL = "LL_", "MAT_"
BAKED, PAINTED, ALBEDO, NORMAL = "BAo_", "BAp_", "ALB_", "NOR_"
KIND_PREFIX = {"BAO": BAKED, "BAP": PAINTED, "ALB": ALBEDO, "NOR": NORMAL}


def final_mesh(rb):
    """The rebuilt mesh step 5 works on (OBJ_<Object>), None while there is none in this view layer."""
    ob = rb.target
    return ob if ob is not None and ob.name in bpy.context.view_layer.objects else None


def object_name():
    """The object folder's name (Wajima_Trap), '' outside an object folder."""
    root = state.get()["root"]
    return paths.object_name(root) if root else ""


def scan_mesh():
    """ORG_<Object>, the mesh Build Scene imported."""
    name = object_name()
    return bpy.data.objects.get(paths.scan_name(name)) if name else None


def image(prefix, ob):
    return bpy.data.images.get(f"{prefix}{ob.name}") if ob else None


def resolution(rb):
    return int(rb.resolution)


def size_label(n):
    return f"{n // 1024}K" if n and n % 1024 == 0 else str(n)


def folder(path):
    return os.path.normpath(bpy.path.abspath(path)) if path else ""


def rel(path):
    """path relative to the .blend (//...) when it can be: same drive and the file saved."""
    try:
        return bpy.path.relpath(path) if bpy.data.filepath else path
    except ValueError:              # another drive
        return path


def bake_path(rb, prefix, ob):
    return os.path.join(folder(rb.bake_dir), f"{prefix}{ob.name}.png")


def override_path(rb, prefix, ob):
    return os.path.join(folder(rb.override_dir), f"{prefix}{ob.name}.png")


def image_file(img):
    """The image's file (absolute), '' for none."""
    if img is None or img.source != "FILE" or not img.filepath:
        return ""
    return os.path.normpath(bpy.path.abspath(img.filepath, library=img.library))


def has_file(img):
    p = image_file(img)
    return bool(p) and isfile(p)


_stat = {}          # path -> (checked at, exists): the panel looks at a file at most every RECHECK s
RECHECK = 2.0


def isfile(path):
    """os.path.isfile, cached briefly: the panel draws often and the folders may stream from Drive."""
    import time
    now = time.monotonic()
    hit = _stat.get(path)
    if hit is None or now - hit[0] > RECHECK:
        hit = _stat[path] = (now, os.path.isfile(path))
    return hit[1]


def locked(ob):
    return bool(ob is not None and ob.get(LOCKED_KEY))


def stages(obj):
    """{9-11: (state, note)} for steps.compute_stages: 9 a rebuilt object, 10 BAp_ saved,
    11 locked and exported."""
    from ..project.steps import DONE, STALE, TODO
    rb = getattr(bpy.context.scene, "livinglacquer_rebuild", None)
    ob = rb.target if rb else None
    if ob is None or not ob.get(REBUILD_KEY):
        return {9: (TODO, ""), 10: (TODO, ""), 11: (TODO, "")}
    out = {9: (DONE, ob.name)}
    bap = image(PAINTED, ob)
    if not has_file(bap):
        out[10] = (TODO, "nothing painted yet")
    elif bap.is_dirty:
        out[10] = (STALE, "BAp_ not saved")
    else:
        out[10] = (DONE, "BAp_ saved")
    fbx = ob.get(EXPORTED_KEY, "")
    if locked(ob) and fbx and os.path.isfile(bpy.path.abspath(fbx)):
        out[11] = (DONE, f"exported {os.path.basename(fbx)}")
    else:
        out[11] = (TODO, "not exported yet")
    return out


# ---------------------------------------------------------------- 5a: the rebuilt object

def export_collection(scene):
    """The EXPORT collection new rebuilt objects go into, the one MultiCamProject uses: its picked
    one, else by name, else made (linked into the scene, its colour tag)."""
    props = getattr(scene, "multicamproject_props", None)
    coll = getattr(props, "export_collection", None) if props is not None else None
    if coll is None:
        coll = next((c for c in bpy.data.collections if c.name.lower() == "export"), None)
    if coll is None:
        coll = bpy.data.collections.new("EXPORT")
        coll.color_tag = "COLOR_03"
    if coll not in scene.collection.children_recursive:
        scene.collection.children.link(coll)
    return coll


def remesh(rb):
    """Copy ORG_<Object> as OBJ_<Object> (same parent and place) with a Decimate modifier, set up like
    a retopo object. A copy made before is replaced. Returns the copy, None without a scan mesh."""
    src = scan_mesh()
    if src is None:
        return None
    name = f"OBJ_{object_name()}"
    old = bpy.data.objects.get(name)
    if old is not None:
        me = old.data
        bpy.data.objects.remove(old)
        if me.users == 0:
            bpy.data.meshes.remove(me)          # else the new copy's mesh would be named .001
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = ob.data.name = name
    export_collection(bpy.context.scene).objects.link(ob)
    mod = ob.modifiers.new("Decimate", "DECIMATE")
    mod.ratio = rb.decimate_ratio
    setup_target(ob, rb, "REMESH")
    return ob


def new_retopo(rb):
    """An empty mesh OBJ_<Object> on the scan (same parent and place), set up as the retopo object."""
    src = scan_mesh()
    name = f"OBJ_{object_name() or 'Object'}"
    me = bpy.data.meshes.new(name)
    ob = bpy.data.objects.new(name, me)
    export_collection(bpy.context.scene).objects.link(ob)
    if src is not None:
        ob.parent = src.parent
        ob.matrix_world = src.matrix_world.copy()
    rb.retopo_object = ob           # its update sets it up
    return ob


def fit_circle(points):
    """The circle best fitting (n, 3) world points: (centre, radius, unit normal), None when they do not span a
    plane. A plane through them (SVD), then a least-squares circle in it, so part of a ring works too."""
    import numpy as np
    if len(points) < 3:
        return None
    mean = points.mean(axis=0)
    _u, sing, vt = np.linalg.svd(points - mean, full_matrices=False)
    if sing[1] < 1e-6 * max(sing[0], 1e-12):        # all on one line
        return None
    p = (points - mean) @ vt[:2].T
    a = np.column_stack((2 * p, np.ones(len(p))))
    (cx, cy, c), *_rest = np.linalg.lstsq(a, (p ** 2).sum(axis=1), rcond=None)
    return mean + cx * vt[0] + cy * vt[1], float(np.sqrt(max(c + cx * cx + cy * cy, 0.0))), vt[2]


def world_points(ob, indices=None):
    """World positions of the mesh's vertices (only indices when given), as (n, 3)."""
    import numpy as np
    me = ob.data
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    if indices is not None:
        co = co[indices]
    m = np.array(ob.matrix_world, np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def base_disc(rb, selected=None, segments=32, band=0.02):
    """A filled circle in the retopo object when it is still empty, else in a new OBJ_. selected ((n, 3) world
    points of the vertices the user selected): the circle best fitting them, facing away from the middle of their
    mesh. None: under the scan, from the bounding box of its lowest 2% in height, facing up.
    Returns the object; None without a scan or when selected does not span a plane."""
    import math

    import bmesh
    import numpy as np
    from mathutils import Vector
    src = scan_mesh()
    if selected is not None:
        fit = fit_circle(selected)
        if fit is None:
            return None
        centre, radius, normal = fit
        if src is not None and np.dot(normal, centre - world_points(src).mean(axis=0)) < 0:
            normal = -normal
    elif src is None:
        return None
    else:
        w = world_points(src)
        z0, z1 = w[:, 2].min(), w[:, 2].max()
        low = w[w[:, 2] <= z0 + (z1 - z0) * band]
        (x0, y0), (x1, y1) = low[:, :2].min(axis=0), low[:, :2].max(axis=0)
        centre = np.array(((x0 + x1) / 2, (y0 + y1) / 2, z0))
        radius = max(x1 - x0, y1 - y0) / 2
        normal = np.array((0.0, 0.0, 1.0))
    ob = rb.target if rb.target is not None and rb.target.get(REBUILD_KEY) == "RETOPO" \
        and not len(rb.target.data.polygons) and not len(rb.target.data.vertices) else None
    if ob is None:
        ob = new_retopo(rb)
    bpy.context.view_layer.update()
    inv = ob.matrix_world.inverted()
    n = Vector(normal).normalized()
    u = n.orthogonal().normalized()
    v = n.cross(u)
    c = Vector(centre)
    bm = bmesh.new()
    verts = [bm.verts.new(inv @ (c + u * (radius * math.cos(a)) + v * (radius * math.sin(a))))
             for a in (2 * math.pi * i / segments for i in range(segments))]
    f = bm.faces.new(verts)
    f.normal_update()
    if (ob.matrix_world.to_3x3().inverted().transposed() @ f.normal).dot(n) < 0:
        bmesh.ops.reverse_faces(bm, faces=[f])
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()
    setup_target(ob, rb)
    return ob


def ensure_uv(ob):
    """The object's UV map named uv_normal: the active one renamed, a new one when it has none. It is
    made the active one (painting and baking use the active UV map)."""
    me = ob.data
    uv = me.uv_layers.get(UV)
    if uv is None:
        uv = me.uv_layers.active
        if uv is None:
            uv = me.uv_layers.new(name=UV)
        else:
            uv.name = UV
    me.uv_layers.active = uv
    uv.active_render = True
    return uv


def _tex(nt, prefix, ob, loc):
    n = nt.nodes.new("ShaderNodeTexImage")
    n.name = n.label = prefix
    n.image = image(prefix, ob)
    n.location = loc
    uv = nt.nodes.get(UV) or nt.nodes.new("ShaderNodeUVMap")
    uv.name = uv.label = UV
    uv.uv_map = UV
    uv.location = (-750, 0)
    nt.links.new(uv.outputs["UV"], n.inputs["Vector"])
    return n


def _bsdf(nt):
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    bsdf.inputs["Roughness"].default_value = 1.0
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def _material(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    mat["livinglacquer"] = "rebuild"
    return mat


def paint_material(ob):
    """LL_<name>: BAo_ mixed with BAp_ by BAp_'s alpha (made once; an existing one is kept)."""
    mat = bpy.data.materials.get(f"{PAINT}{ob.name}")
    if mat is not None:
        return mat
    mat = _material(f"{PAINT}{ob.name}")
    nt = mat.node_tree
    bsdf = _bsdf(nt)
    bao = _tex(nt, BAKED, ob, (-450, 150))
    bap = _tex(nt, PAINTED, ob, (-450, -150))
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.location = (-150, 0)
    nt.links.new(bap.outputs["Alpha"], mix.inputs["Factor"])
    nt.links.new(bao.outputs["Color"], mix.inputs["A"])
    nt.links.new(bap.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    return mat


def final_material(ob):
    """MAT_<name>: ALB_ as colour, NOR_ through a Normal Map on uv_normal (made once)."""
    mat = bpy.data.materials.get(f"{FINAL}{ob.name}")
    if mat is not None:
        return mat
    mat = _material(f"{FINAL}{ob.name}")
    nt = mat.node_tree
    bsdf = _bsdf(nt)
    alb = _tex(nt, ALBEDO, ob, (-450, 150))
    nt.links.new(alb.outputs["Color"], bsdf.inputs["Base Color"])
    nor = _tex(nt, NORMAL, ob, (-450, -200))
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.uv_map = UV
    nmap.location = (-150, -200)
    nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def link_images(ob):
    """Point the texture nodes of LL_ / MAT_ at the current BAo_ / BAp_ / ALB_ / NOR_ images."""
    for mat in (bpy.data.materials.get(f"{PAINT}{ob.name}"), bpy.data.materials.get(f"{FINAL}{ob.name}")):
        if mat is None or not mat.use_nodes:
            continue
        for prefix in KIND_PREFIX.values():
            n = mat.node_tree.nodes.get(prefix)
            if n is not None and n.type == "TEX_IMAGE":
                n.image = image(prefix, ob)


def set_shading(ob, shading):
    """The simple switch between painting and final: every slot holds LL_<name> or MAT_<name>."""
    mat = paint_material(ob) if shading == "PAINT" else final_material(ob)
    if not ob.material_slots:
        ob.data.materials.append(mat)
    for slot in ob.material_slots:
        slot.material = mat


def setup_target(ob, rb, how="RETOPO"):
    """Make ob the rebuilt object: uv_normal, LL_ / MAT_ materials, the shading switch's material."""
    if ob.type != "MESH":
        return
    ensure_uv(ob)
    paint_material(ob)
    final_material(ob)
    link_images(ob)
    set_shading(ob, rb.shading)
    ob[REBUILD_KEY] = how
    rb.target = ob


# ---------------------------------------------------------------- 5b: the photos

def cameras():
    """{name: camera} of the scan cameras (under the Transform)."""
    rig = bpy.data.objects.get("Transform")
    return {o.name: o for o in (rig.children if rig else ()) if o.type == "CAMERA"}


def favorites(rb, cams=None):
    cams = cameras() if cams is None else cams
    return [it.name for it in rb.favorites if it.name in cams]


def photo_image(cam):
    bg = next((b for b in cam.data.background_images if b.image), None) if cam else None
    return bg.image if bg else None


def write_list(coll, names):
    coll.clear()
    for n in names:
        coll.add().name = n
