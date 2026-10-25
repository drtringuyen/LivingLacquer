"""Step 6 - the model: import OBJ_<Object>.abc / .fbx / .obj, put it in the camera XML's
coordinates (axis fix + alignment check, C16), and give it its textures (D20-D22)."""
import math
import os

import bpy
import numpy as np
from mathutils import Matrix

# Metashape writes the model Z-up in the chunk's coordinates. Blender's Alembic importer
# assumes Y-up and turns it +90 deg about X, so ABC starts with -90 deg; OBJ / FBX come in as is.
START = {".abc": -90.0, ".fbx": 0.0, ".obj": 0.0}
CANDIDATES = (0.0, -90.0, 90.0, 180.0)          # rotation about world X tried by the alignment check


def _import(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=path, as_background_job=False, set_frame_range=False)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path, use_manual_orientation=True, axis_forward="Y", axis_up="Z")
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path, forward_axis="Y", up_axis="Z")
    else:
        raise ValueError(f"Unsupported model format {ext}")


def move_to(ob, col):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    col.objects.link(ob)


def remove_object(ob):
    """Delete the object and the mesh / camera data and Alembic cache only it used."""
    data = ob.data
    caches = [m.cache_file for m in ob.modifiers if m.type == "MESH_SEQUENCE_CACHE" and m.cache_file]
    bpy.data.objects.remove(ob)
    if isinstance(data, bpy.types.Mesh) and data.users == 0:
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Camera) and data.users == 0:
        bpy.data.cameras.remove(data)
    for c in caches:
        if not any(m.type == "MESH_SEQUENCE_CACHE" and m.cache_file == c
                   for o in bpy.data.objects for m in o.modifiers):
            bpy.data.cache_files.remove(c)


def import_model(path, name, col):
    """Import the model as object `name` in col, replacing an older one of that name.
    Cameras that come with the file are removed (the XML cameras win, C18).
    Returns (object, removed camera count)."""
    old = bpy.data.objects.get(name)
    if old:
        remove_object(old)
    before = set(bpy.data.objects)
    _import(path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        for o in new:
            remove_object(o)
        raise ValueError(f"No mesh in {os.path.basename(path)}")
    cams = [o for o in new if o.type == "CAMERA"]
    rest = [o for o in new if o.type != "CAMERA"]
    for o in cams:
        remove_object(o)
    ob = max(meshes, key=lambda o: len(o.data.vertices))
    for o in rest:
        if o is not ob:
            move_to(o, col)            # extra objects (rare) stay, next to the model
    ob.parent = None
    ob.name = name
    if ob.data:
        ob.data.name = name
    for m in ob.modifiers:
        if m.type == "MESH_SEQUENCE_CACHE" and m.cache_file:
            m.cache_file.name = os.path.basename(path)
            m.cache_file.filepath = bpy.path.relpath(path) if bpy.data.filepath else path
    move_to(ob, col)
    ob.matrix_basis = Matrix.Rotation(math.radians(START.get(os.path.splitext(path)[1].lower(), 0.0)), 4, "X")
    return ob, len(cams)


def sample_vertices(ob, n=1500):
    """(n, 3) local vertex positions of the evaluated mesh (Alembic meshes live in a modifier)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        co = np.empty(len(me.vertices) * 3, np.float64)
        me.vertices.foreach_get("co", co)
    finally:
        ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    if len(co) > n:
        co = co[np.linspace(0, len(co) - 1, n).astype(int)]
    return co


def _score(world_pts, cams, sensors):
    """Share of (vertex, camera) pairs that land inside the photo, in front of the camera."""
    hits = total = 0
    homog = np.c_[world_pts, np.ones(len(world_pts))]
    for c in cams:
        cal = sensors[c["sensor"]]
        inv = np.array(c["matrix"].inverted())
        p = homog @ inv.T
        z = p[:, 2]
        front = z > 1e-6
        u = cal["f"] * p[:, 0] / np.where(front, z, 1) + cal["w"] * 0.5 + cal.get("cx", 0.0)
        v = cal["f"] * p[:, 1] / np.where(front, z, 1) + cal["h"] * 0.5 + cal.get("cy", 0.0)
        inside = front & (u >= 0) & (u < cal["w"]) & (v >= 0) & (v < cal["h"])
        hits += int(inside.sum())
        total += len(p)
    return hits / total if total else 0.0


def align(ob, sensors, cameras, n_cams=9):
    """Try the X rotations, keep the one where the mesh projects into the most photos.
    Returns (score 0-1, rotation in degrees, start rotation in degrees)."""
    if not cameras:
        return 0.0, None, None
    pick = [cameras[i] for i in np.linspace(0, len(cameras) - 1, min(n_cams, len(cameras))).astype(int)]
    local = sample_vertices(ob)
    start = round(math.degrees(ob.matrix_basis.to_euler().x))
    best = (-1.0, 0.0)
    for deg in CANDIDATES:
        m = np.array(Matrix.Rotation(math.radians(deg), 4, "X"))
        pts = (np.c_[local, np.ones(len(local))] @ m.T)[:, :3]
        s = _score(pts, pick, sensors)
        if s > best[0] + 1e-6:
            best = (s, deg)
    ob.matrix_basis = Matrix.Rotation(math.radians(best[1]), 4, "X")       # in the Transform empty's space
    return best[0], best[1], start


def _image(path, non_color=False):
    img = bpy.data.images.load(path, check_existing=True)
    if bpy.data.filepath:
        img.filepath = bpy.path.relpath(path)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def _material(name, color, normal=None, ao=None):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.location = (-400, 200)
    tex.image = _image(color)
    if ao:
        aon = nt.nodes.new("ShaderNodeTexImage")
        aon.location = (-400, -100)
        aon.image = _image(ao, non_color=True)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.location = (-120, 150)
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(tex.outputs["Color"], mix.inputs["A"])
        nt.links.new(aon.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if normal:
        nn = nt.nodes.new("ShaderNodeTexImage")
        nn.location = (-400, -400)
        nn.image = _image(normal, non_color=True)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.location = (-120, -400)
        nt.links.new(nn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def split_textures(textures, obj_name):
    """{'pages': [color paths in page order], 'normal': path|None, 'ao': path|None} by the naming rule
    OBJ_<Object>.jpg, OBJ_<Object>_1.jpg..., OBJ_<Object>_normal.jpg, OBJ_<Object>_ao.jpg."""
    out = {"pages": [], "normal": None, "ao": None}
    base = f"OBJ_{obj_name}".lower()
    for t in sorted(textures):
        stem = os.path.splitext(os.path.basename(t))[0].lower()
        rest = stem[len(base):]
        if rest == "_normal":
            out["normal"] = t
        elif rest == "_ao":
            out["ao"] = t
        elif rest == "" or (rest.startswith("_") and rest[1:].isdigit()):
            out["pages"].append((int(rest[1:]) if rest else 0, t))
    out["pages"] = [t for _, t in sorted(out["pages"])]
    return out


def assign_textures(ob, textures, obj_name):
    """One material per texture page: MAT_<Object> (page 1), MAT_<Object>_2, ... Slots are linked to the
    object so an Alembic reload keeps them. Returns a note for the report."""
    tx = split_textures(textures, obj_name)
    if not tx["pages"]:
        return "no texture found"
    mats = [_material(f"MAT_{obj_name}" + (f"_{i + 1}" if i else ""), page,
                      tx["normal"] if i == 0 else None, tx["ao"] if i == 0 else None)
            for i, page in enumerate(tx["pages"])]
    if not ob.material_slots:
        ob.data.materials.append(None)
    for i, slot in enumerate(ob.material_slots):
        slot.link = "OBJECT"
        slot.material = mats[min(i, len(mats) - 1)]
    note = f"{len(mats)} texture page(s)"
    if len(mats) > 1 and len(ob.material_slots) < len(mats):
        note += f", but the mesh has {len(ob.material_slots)} material slot(s): pages after the first are unused"
    if tx["normal"]:
        note += ", normal map"
    if tx["ao"]:
        note += ", AO"
    return note
