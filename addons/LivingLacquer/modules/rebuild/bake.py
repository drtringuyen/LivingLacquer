"""Step 5's texture work: bake BAo_ / NOR_ from the scan, make BAp_ (always BAo_'s size), Fill / Erase a
photo into BAp_, combine ALB_, the Bake | Load switch and where a finished ALB_ goes (over BAo_ or into
02.Overrides). Each one writes its PNG in the bake folder; the operators ask before replacing a file.

Fill / Erase: the photo is projected onto the rebuilt object through its camera (a UV Project modifier
on a temporary UV map) and baked into uv_normal. Where the camera sees the surface is a second bake: a
point light at the camera, so faces turned away or hidden behind other parts stay dark (as the brush,
which paints only what the view sees). What it lights turns MSKp_ white there, so BAp_ shows."""
import os
import shutil
from contextlib import contextmanager

import bpy
import numpy as np

from . import core

CAM_UV = "ll_cam"
PROJECT_MOD = "LL Photo Project"
MARGIN = 16


# ---------------------------------------------------------------- images and files

def new_image(name, size, non_color=False, alpha=False):
    """The image called name at size x size: the existing one scaled to it, or a new one."""
    img = bpy.data.images.get(name)
    if img is not None and tuple(img.size) != (size, size):
        img.scale(size, size)
    if img is None:
        img = bpy.data.images.new(name, size, size, alpha=alpha, float_buffer=False)
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    img.alpha_mode = "STRAIGHT"
    return img


def _write_rgba(img, path):
    """img's pixels as an RGBA PNG: an image loaded from an RGB file saves without its alpha, whatever it holds."""
    w, h = img.size
    tmp = bpy.data.images.new(img.name + "_LL_TMP", w, h, alpha=True)
    try:
        buf = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(buf)
        tmp.pixels.foreach_set(buf)
        tmp.filepath_raw = path
        tmp.file_format = "PNG"
        tmp.save(filepath=path)
    finally:
        bpy.data.images.remove(tmp)


def save(img, path):
    """Write img to path as PNG and keep it pointing there (relative when the .blend is saved). BAp_ keeps its alpha."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if img.name.startswith(core.PAINTED):
        _write_rgba(img, path)
    else:
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
    img.source = "FILE"
    img.filepath = core.rel(path)
    img.reload()


def _painted(a):
    """How many pixels of an RGBA array carry paint."""
    return int((a[..., 3] > 0.01).sum())


def _painted_on_disk(path):
    """How many pixels of the PNG at path carry paint: its file, read apart from any image in the scene."""
    probe = bpy.data.images.load(path, check_existing=False)
    try:
        return _painted(pixels(probe))
    finally:
        bpy.data.images.remove(probe)


def save_painted(img, path):
    """Save BAp_ so that paint cannot go missing: never an empty image over a file with paint in it, the file it
    replaces kept as <path>.bak, and the file read back afterwards; paint gone from it or from the image is put back
    and written again. Returns True when that was needed. Raises RuntimeError when the paint is not safely on disk."""
    before = pixels(img).copy()
    painted = _painted(before)
    if os.path.isfile(path):
        if not painted and _painted_on_disk(path):
            raise RuntimeError(f"BAp_ is empty but {os.path.basename(path)} has paint: the file was not touched")
        shutil.copy2(path, path + ".bak")
    save(img, path)
    margin = max(1, painted // 1000)        # the PNG's rounding at the alpha's edge
    if abs(_painted(pixels(img)) - painted) <= margin and abs(_painted_on_disk(path) - painted) <= margin:
        return False
    set_pixels(img, before)
    img.save()
    if abs(_painted(pixels(img)) - painted) > margin or abs(_painted_on_disk(path) - painted) > margin:
        raise RuntimeError(f"{os.path.basename(path)} did not keep the paint: the previous file is {os.path.basename(path)}.bak")
    return True


def load(name, path, non_color=False):
    """The image called name pointing at the file path (reloaded)."""
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.load(path, check_existing=False)
        img.name = name
    else:
        img.source = "FILE"
        img.filepath = core.rel(path)
        img.reload()
    img.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
    return img


def pixels(img):
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def set_pixels(img, a):
    img.pixels.foreach_set(np.ascontiguousarray(a, np.float32).ravel())
    img.update()


# ---------------------------------------------------------------- baking

def _layer_chain(lc, col):
    """The layer collections from lc down to the one of col, [] when it is not under lc."""
    if lc.collection == col:
        return [lc]
    for child in lc.children:
        chain = _layer_chain(child, col)
        if chain:
            return [lc, *chain]
    return []


def _show_for_bake(context, objects):
    """objects in the view layer, in the render and in every Local View, whatever hid them (Solo, the
    outliner, an unticked collection). Returns what to put back: (collection, attr, value), (owner, attr,
    value) and (object, space)."""
    in_layer, flags, local = [], [], []
    root = context.view_layer.layer_collection
    for o in objects:
        for col in o.users_collection:
            for lc in _layer_chain(root, col):
                for attr in ("exclude", "hide_viewport"):
                    if getattr(lc, attr):
                        in_layer.append((lc.collection, attr, True))
                        setattr(lc, attr, False)
                for attr in ("hide_viewport", "hide_render"):
                    if getattr(lc.collection, attr):
                        flags.append((lc.collection, attr, True))
                        setattr(lc.collection, attr, False)
        for attr in ("hide_viewport", "hide_render"):
            if getattr(o, attr):
                flags.append((o, attr, True))
                setattr(o, attr, False)
    context.view_layer.update()
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            space = area.spaces.active if area.type == "VIEW_3D" else None
            if space is not None and space.local_view is not None:
                for o in objects:
                    if not o.local_view_get(space):
                        o.local_view_set(space, True)
                        local.append((o, space))
    return in_layer, flags, local


def is_gn(m):
    """A GN- modifier: Mesh Build's playback and the like, which show something else than the mesh."""
    return m.type == "NODES" and (m.name.startswith("GN-") or (m.node_group and m.node_group.name.startswith("GN-")))


def _gn_off(objects):
    """The GN- modifiers of objects off (Mesh Build's playback shows an older stage): what is baked is the
    mesh itself, on its uv_normal. Returns what to put back: (modifier, attr, value)."""
    done = []
    for o in objects:
        for m in o.modifiers:
            if is_gn(m):
                for attr in ("show_viewport", "show_render"):
                    if getattr(m, attr):
                        done.append((m, attr, True))
                        setattr(m, attr, False)
    return done


@contextmanager
def _bake_setup(context, target, sources=(), hide_others=False, keep_lit=()):
    """Cycles, object mode, only target (+ sources) selected with target active, shown whatever hid them and
    without their GN- modifiers; afterwards everything as it was. hide_others: every other object out of the
    render but keep_lit, and no world (the visibility bake)."""
    scene = context.scene
    keep = {"engine": scene.render.engine, "samples": scene.cycles.samples,
            "world": scene.world, "mode": target.mode,
            "active": context.view_layer.objects.active,
            "selected": list(context.selected_objects)}
    hidden, unhid = [], []
    in_layer, flags, local, gn = [], [], [], []
    try:
        if target.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 4
        objects = (target, *sources)
        in_layer, flags, local = _show_for_bake(context, objects)
        gn = _gn_off(objects)
        for o in context.view_layer.objects:
            o.select_set(False)
        for o in objects:
            if o.hide_get():
                o.hide_set(False)
                unhid.append(o)
            o.select_set(True)
        context.view_layer.objects.active = target
        if hide_others:
            scene.world = None
            for o in scene.objects:
                if o != target and o not in keep_lit and not o.hide_render \
                        and o.type in {"MESH", "CURVE", "SURFACE", "META", "FONT", "LIGHT", "VOLUME"}:
                    o.hide_render = True
                    hidden.append(o)
        context.view_layer.update()
        yield
    finally:
        for o in hidden:
            o.hide_render = False
        for m, attr, value in gn:
            setattr(m, attr, value)
        scene.render.engine = keep["engine"]
        scene.cycles.samples = keep["samples"]
        scene.world = keep["world"]
        for o in context.view_layer.objects:
            o.select_set(o in keep["selected"])
        context.view_layer.objects.active = keep["active"]
        if keep["mode"] != "OBJECT" and keep["active"] == target:
            bpy.ops.object.mode_set(mode=keep["mode"])
        for o, space in local:
            o.local_view_set(space, False)
        for o in unhid:
            o.hide_set(True)
        for owner, attr, value in flags:
            setattr(owner, attr, value)
        root = context.view_layer.layer_collection
        for col, attr, value in reversed(in_layer):
            chain = _layer_chain(root, col)
            if chain:
                setattr(chain[-1], attr, value)


@contextmanager
def _bake_node(target, img):
    """img as the active Image Texture node in every material of target (where bakes write)."""
    added = []
    for mat in {s.material for s in target.material_slots if s.material}:
        nt = mat.node_tree
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.location = (-900, -500)
        for o in nt.nodes:
            o.select = False
        n.select = True
        nt.nodes.active = n
        added.append((nt, n))
    try:
        yield
    finally:
        for nt, n in added:
            nt.nodes.remove(n)


def _cage_extrusion(rb, ob):
    """rb.cage is a distance in the world; Blender reads cage_extrusion in the object's own units."""
    return rb.cage / max(max(abs(v) for v in ob.matrix_world.to_scale()), 1e-6)


def bake_from_scan(context, rb, kind):
    """BAo_ (the scan's colour) or NOR_ (its surface detail as a tangent normal map) baked from
    ORG_<Object> onto the rebuilt object's uv_normal, at the set resolution, into the bake folder.
    BAp_ follows BAo_'s size. Returns the image."""
    ob, src = rb.target, core.scan_mesh()
    size = core.resolution(rb)
    prefix = core.BAKED if kind == "BAO" else core.NORMAL
    img = new_image(f"{prefix}{ob.name}", size, non_color=kind == "NOR")
    core.ensure_uv(ob)
    with _bake_setup(context, ob, (src,)), _bake_node(ob, img):
        kw = dict(use_selected_to_active=True, cage_extrusion=_cage_extrusion(rb, ob), max_ray_distance=0.0, margin=MARGIN,
                  target="IMAGE_TEXTURES", use_clear=True)
        if kind == "BAO":
            bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, **kw)
        else:
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", **kw)
    save(img, core.bake_path(rb, prefix, ob))
    if kind == "BAO":
        ensure_painted(rb, ob)
    core.link_images(ob)
    return img


def ensure_painted(rb, ob):
    """BAp_<name>, transparent, BAo_'s size (the set resolution without a BAo_); an existing one is
    scaled to BAo_'s size and keeps its paint. Written to the bake folder when new or resized."""
    bao = core.image(core.BAKED, ob)
    size = bao.size[0] if bao is not None and bao.size[0] else core.resolution(rb)
    img = core.image(core.PAINTED, ob)
    if img is not None and tuple(img.size) == (size, size) and core.has_file(img):
        return img
    fresh = img is None
    img = new_image(f"{core.PAINTED}{ob.name}", size, alpha=True)
    if fresh:
        set_pixels(img, np.zeros((size, size, 4), np.float32))
    save(img, core.bake_path(rb, core.PAINTED, ob))
    core.link_images(ob)
    return img


def ensure_mask(rb, ob):
    """MSKp_<name>, 1K, black (all of it BAo_), written to the bake folder when new."""
    img = core.image(core.MASK, ob)
    if img is not None and core.has_file(img):
        return img
    img = new_image(f"{core.MASK}{ob.name}", core.MASK_SIZE, non_color=True)
    px = np.zeros((core.MASK_SIZE, core.MASK_SIZE, 4), np.float32)
    px[..., 3] = 1.0
    set_pixels(img, px)
    save(img, core.bake_path(rb, core.MASK, ob))
    core.link_images(ob)
    return img


def grid(size, n=core.MASK_SIZE):
    """The rows / columns of a (size, size) image that lie under an (n, n) one's pixels."""
    return ((np.arange(n) + 0.5) * size / n).astype(np.int32)


def clear_mask(rb, ob):
    """All of MSKp_ black, all of the object BAo_. Only the 1K mask is written."""
    msk = ensure_mask(rb, ob)
    n = msk.size[0]
    px = np.zeros((n, n, 4), np.float32)
    px[..., 3] = 1.0
    set_pixels(msk, px)
    return msk


def _smooth(x, lo, hi):
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _projector_material(photo, visibility):
    """Temporary material: the photo through ll_cam (Emission), or for visibility a white diffuse
    surface, white only inside the photo's frame (its Diffuse Colour)."""
    mat = bpy.data.materials.new("LL_tmp_project")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = CAM_UV
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = photo
    tex.extension = "CLIP"
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    if visibility:
        sh = nt.nodes.new("ShaderNodeBsdfDiffuse")
        nt.links.new(tex.outputs["Alpha"], sh.inputs["Color"])
        nt.links.new(sh.outputs["BSDF"], out.inputs["Surface"])
    else:
        sh = nt.nodes.new("ShaderNodeEmission")
        nt.links.new(tex.outputs["Color"], sh.inputs["Color"])
        nt.links.new(sh.outputs["Emission"], out.inputs["Surface"])
    return mat


@contextmanager
def _projected(ob, cam, photo):
    """ll_cam on ob: the camera's view as UVs (UV Project modifier, the photo's aspect), removed after."""
    me = ob.data
    keep_active = me.uv_layers.active.name if me.uv_layers.active else core.UV
    if CAM_UV not in me.uv_layers:
        me.uv_layers.new(name=CAM_UV)
    me.uv_layers.active = me.uv_layers[core.UV]          # bakes write into the active UV map
    mod = ob.modifiers.new(PROJECT_MOD, "UV_PROJECT")
    mod.uv_layer = CAM_UV
    mod.projector_count = 1
    mod.projectors[0].object = cam
    w, h = photo.size
    mod.aspect_x, mod.aspect_y = float(w), float(h)
    try:
        yield
    finally:
        ob.modifiers.remove(mod)
        if CAM_UV in me.uv_layers:
            me.uv_layers.remove(me.uv_layers[CAM_UV])
        if keep_active in me.uv_layers:
            me.uv_layers.active = me.uv_layers[keep_active]


@contextmanager
def _materials(ob, mat):
    keep = [s.material for s in ob.material_slots]
    for s in ob.material_slots:
        s.material = mat
    try:
        yield
    finally:
        for s, m in zip(ob.material_slots, keep):
            s.material = m
        bpy.data.materials.remove(mat)


def flood(context, rb):
    """Fill: the current photo into BAp_ wherever its camera sees the rebuilt object, MSKp_ white there. Soft blends
    the edge over the grazing / hidden parts."""
    ob = rb.target
    cam = core.cameras().get(rb.photo)
    photo = core.photo_image(cam)
    bap = ensure_painted(rb, ob)
    msk = ensure_mask(rb, ob)
    size = bap.size[0]
    col_img = new_image("LL_tmp_colour", size)
    vis_img = new_image("LL_tmp_visible", size, non_color=True)
    light_data = bpy.data.lights.new("LL_tmp_light", "POINT")
    light_data.shadow_soft_size = 0.0
    light_data.energy = 1000.0
    light = bpy.data.objects.new("LL_tmp_light", light_data)
    context.scene.collection.objects.link(light)
    light.matrix_world.translation = cam.matrix_world.translation
    if not ob.material_slots:
        core.set_shading(ob, rb.shading)
    try:
        with _projected(ob, cam, photo):
            with _bake_setup(context, ob, hide_others=True, keep_lit=(light,)):
                kw = dict(margin=MARGIN, target="IMAGE_TEXTURES", use_clear=True)
                with _materials(ob, _projector_material(photo, False)), _bake_node(ob, col_img):
                    bpy.ops.object.bake(type="EMIT", **kw)
                with _materials(ob, _projector_material(photo, True)), _bake_node(ob, vis_img):
                    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"DIRECT", "COLOR"}, **kw)
        vis = pixels(vis_img)[..., 0]
        lit = vis[vis > 1e-6]
        top = float(np.percentile(lit, 98)) if lit.size else 1.0
        v = vis / max(top, 1e-6)
        m = _smooth(v, 0.05, 0.35) if rb.soft else (v > 0.15).astype(np.float32)
        cur = pixels(bap)
        a = cur[..., 3]
        rows = grid(size, msk.size[0])
        mp = pixels(msk)
        mp[..., :3] += (1.0 - mp[..., :3]) * m[np.ix_(rows, rows)][..., None]
        src = pixels(col_img)[..., :3]
        na = m + a * (1.0 - m)
        rgb = (src * m[..., None] + cur[..., :3] * (a * (1.0 - m))[..., None]) / np.maximum(na, 1e-6)[..., None]
        cur[..., :3] = np.where(na[..., None] > 1e-6, rgb, cur[..., :3])
        cur[..., 3] = na
        set_pixels(bap, cur)
        set_pixels(msk, mp)
    finally:
        bpy.data.objects.remove(light)
        bpy.data.lights.remove(light_data)
        for img in (col_img, vis_img):
            bpy.data.images.remove(img)
    return float(m.mean())


def combine_albedo(rb):
    """ALB_ = what LL_ shows (BAo_, BAp_ and MSKp_ mixed by the shader) baked unlit at BAo_'s size, into the
    bake folder. Shading stays as it was."""
    ob = rb.target
    bao = core.image(core.BAKED, ob)
    ensure_painted(rb, ob)
    ensure_mask(rb, ob)
    img = new_image(f"{core.ALBEDO}{ob.name}", bao.size[0])
    context = bpy.context
    mat = core.paint_material(ob)
    core.set_shading(ob, "PAINT")
    core.set_flat(mat, True)
    try:
        with _bake_setup(context, ob), _bake_node(ob, img):
            bpy.ops.object.bake(type="EMIT", margin=MARGIN, target="IMAGE_TEXTURES", use_clear=True)
    finally:
        core.set_shading(ob, rb.shading)
        if rb.shading != "PAINT":
            core.set_flat(mat, False)
    save(img, core.bake_path(rb, core.ALBEDO, ob))
    core.link_images(ob)
    return img


# ---------------------------------------------------------------- Bake | Load (as MultiCamProject's TexOverride)

def apply_mode(rb, kind):
    """ALB_ / NOR_ switched: Load points the image at its file in 02.Overrides (back to Bake when there
    is none); Bake points it back at the bake folder's file when there is one."""
    ob = rb.target
    if ob is None:
        return
    prefix = core.KIND_PREFIX[kind]
    prop = "alb_mode" if kind == "ALB" else "nor_mode"
    if getattr(rb, prop) == "LOAD":
        path = core.override_path(rb, prefix, ob)
        if not os.path.isfile(path):
            setattr(rb, prop, "BAKE")
            return
    else:
        path = core.bake_path(rb, prefix, ob)
        if not os.path.isfile(path):
            return
    load(f"{prefix}{ob.name}", path, non_color=kind == "NOR")
    core.link_images(ob)


def highpass_normal(rb):
    """NOR_ generated from ALB_ (16-bit, Non-Color, OpenGL), as MultiCamProject's 07 High-pass, in the
    bake folder."""
    from . import highpass, pngio
    ob = rb.target
    alb = core.image(core.ALBEDO, ob)
    size = alb.size[0]
    rgb = highpass.generate(alb, size, rb)
    path = core.bake_path(rb, core.NORMAL, ob)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pngio.write_rgb16(path, rgb, 1)
    img = load(f"{core.NORMAL}{ob.name}", path, non_color=True)
    core.link_images(ob)
    return img


def send_current(rb, kind, target):
    """The current ALB_ / NOR_ goes on: target BAO copies ALB_ over BAo_ (painting goes on from it),
    OVERRIDE copies it into 02.Overrides as its override (Load uses it)."""
    import shutil
    ob = rb.target
    prefix = core.KIND_PREFIX[kind]
    src = core.image_file(core.image(prefix, ob))
    if target == "BAO":
        dst = core.image_file(core.image(core.BAKED, ob)) or core.bake_path(rb, core.BAKED, ob)
    else:
        dst = core.override_path(rb, prefix, ob)
    if os.path.normcase(os.path.normpath(src)) == os.path.normcase(os.path.normpath(dst)):
        raise RuntimeError("Source and target are the same file")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    if target == "BAO":
        load(f"{core.BAKED}{ob.name}", dst)
        core.link_images(ob)
    return dst


# ---------------------------------------------------------------- export (as MultiCamProject's)

def export_fbx(context, ob, path):
    """<folder>/<name>.fbx with ALB_ / NOR_ copied to <folder>/Textures/, the FBX's relative texture paths
    pointing there. While it is written MAT_ shows temporary images of those copies under the same names."""
    import shutil
    folder = os.path.dirname(path)
    tex = os.path.join(folder, "Textures")
    os.makedirs(tex, exist_ok=True)
    mat = core.final_material(ob)
    swapped = []
    keep = (list(context.selected_objects), context.view_layer.objects.active)
    try:
        for n in mat.node_tree.nodes:
            img = n.image if n.type == "TEX_IMAGE" else None
            src = core.image_file(img)
            if not src or not os.path.isfile(src):
                continue
            name = img.name
            dst = os.path.join(tex, name + ".png")
            if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dst)):
                shutil.copy2(src, dst)
            copy = bpy.data.images.load(dst, check_existing=False)
            copy.colorspace_settings.name = img.colorspace_settings.name
            img.name = name + "__ll_tmp"
            copy.name = name
            n.image = copy
            swapped.append((n, img, copy, name))
        for o in context.view_layer.objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"},
                                 use_mesh_modifiers=True, path_mode="RELATIVE", embed_textures=False,
                                 apply_scale_options="FBX_SCALE_ALL", bake_space_transform=True,
                                 add_leaf_bones=False, use_tspace=True, mesh_smooth_type="OFF")
    finally:
        for n, img, copy, name in swapped:
            n.image = img
            bpy.data.images.remove(copy)
            img.name = name
        for o in context.view_layer.objects:
            o.select_set(o in keep[0])
        context.view_layer.objects.active = keep[1]
