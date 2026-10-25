"""Steps 6-8 without operators: build the scene from the published folders, undistort, publish."""
import hashlib
import json
import os
import shutil
from datetime import datetime

import bpy
from mathutils import Matrix

from ..linker.checks import index_photos, match_photo, pick_jpg
from ..metashape.cameras import build_camera, get_collection, set_background
from ..metashape.parse import parse_metashape_xml
from ..metashape.photos import read_image_size, size_matches
from ..project import marker, paths
from ..project.jobs import ui_override as jobs_ui
from . import model

EXT = {"JPG": ".jpg", "PNG": ".png", "TIF": ".tif"}


# MultiCamProject finds these by name (roles.py): OBJECTS = scan meshes, CAMERAS = cameras only
OBJECTS = "OBJECTS"
CAMERAS = "CAMERAS"
TRANSFORM = "Transform"
FLIP = Matrix.Diagonal((1, -1, -1, 1))      # Metashape camera (Y down, Z forward) -> Blender camera


def transform_empty(scene):
    """The empty every scan object and camera hangs under, in the scene's root collection (outside
    OBJECTS / CAMERAS). Moving / rotating / scaling it moves the whole scan; Build keeps it."""
    ob = bpy.data.objects.get(TRANSFORM)
    if ob is None or ob.type != "EMPTY":
        ob = bpy.data.objects.new(TRANSFORM, None)
        ob.empty_display_type = "ARROWS"
        ob.empty_display_size = 1.0
    if ob.name not in scene.collection.objects:
        scene.collection.objects.link(ob)
    return ob


def parent_to(ob, parent, local):
    """Hang ob under parent with `local` as its matrix in the parent's space (no parent inverse),
    so a moved Transform keeps carrying everything on re-runs."""
    ob.parent = parent
    ob.matrix_parent_inverse.identity()
    ob.matrix_basis = local


def _drop_old_collection(name):
    """Collections of builds before 0.2.2 (Geometry_<Object>, Cameras_<Object>) once emptied."""
    col = bpy.data.collections.get(name)
    if col and not col.all_objects and not col.children:
        bpy.data.collections.remove(col)


def fingerprint(cal):
    """Short hash of a sensor calibration: undistorted photos made with another one are stale (C14)."""
    keys = ("f", "cx", "cy", "k1", "k2", "k3", "k4", "p1", "p2", "b1", "b2", "w", "h")
    return hashlib.sha1(json.dumps([round(cal.get(k, 0.0), 9) for k in keys]).encode()).hexdigest()[:12]


def published_undistorted(root):
    """True when the published photos in 01.CAM_Photos are already undistorted (COLMAP engines)."""
    m = marker.read(root) or {}
    return bool(m.get("published", {}).get("undistorted"))


def camera_jobs(root, found):
    """[(cam, cal, source photo, undistorted photo path)] for the aligned cameras with a photo
    that fits its own sensor. Plus the sensors and the list of skipped labels."""
    sensors, cams = parse_metashape_xml(found["xml"])
    src = index_photos(found["source"], skip=(paths.ORIGINALS,))
    undist = index_photos(found["cam"])
    pinhole = published_undistorted(root)       # COLMAP: the published photos are the camera images
    jobs, skipped = [], []
    for c in cams:
        cal = sensors[c["sensor"]]
        stem, _ = match_photo(c["label"], src)
        photo = pick_jpg(src[stem]) if stem and not pinhole else None
        out = pick_jpg(undist[c["label"]]) if c["label"] in undist else \
            os.path.join(found["cam"], c["label"] + ".jpg")
        check = out if pinhole else photo
        if check and os.path.exists(check) and not size_matches(read_image_size(check), cal):
            skipped.append(c["label"] + " (photo does not fit its sensor)")
            continue
        jobs.append((c, cal, photo, out))
    return sensors, cams, jobs, skipped


def build_scene(root):
    """Step 6 as a job step: model + textures + cameras from the published folders, updated in place.
    Generator: yields (progress, what); returns the report lines."""
    scene = bpy.context.scene
    found = paths.locate(root)
    obj = found["object"]
    if not found["xml"]:
        raise ValueError(f"No camera XML: CAM_{obj}.xml in {paths.SCAN}\\{paths.CAM}")
    props = scene.livinglacquer_props
    lines = []
    rig = transform_empty(scene)

    yield 0.02, "reading the camera XML and photo sizes"
    sensors, cams, jobs, skipped = camera_jobs(root, found)

    if found["model"]:
        yield 0.1, f"importing {os.path.basename(found['model'])} (Blender pauses while it loads)"
        geo = get_collection(scene, OBJECTS)
        with jobs_ui():
            ob, n_abc = model.import_model(found["model"], f"OBJ_{obj}", geo)
        lines.append(f"Model {os.path.basename(found['model'])} in {OBJECTS}" +
                     (f", {n_abc} camera(s) from the file removed (XML cameras win)" if n_abc else ""))
        parent_to(ob, rig, ob.matrix_basis)
        yield 0.4, "lining the mesh up with the cameras"
        score, deg, start = model.align(ob, sensors, cams)
        if deg is not None:
            lines.append(f"Alignment {score:.0%} of the mesh inside the photos, rotation X {deg:+.0f} deg"
                         + ("" if deg == start else f" (changed from {start:+.0f})"))
            if score < 0.5:
                lines.append("WARNING: the mesh does not line up with the cameras; check the model export")
        yield 0.5, "textures"
        lines.append("Textures: " + model.assign_textures(ob, found["textures"], obj))
    else:
        lines.append(f"No model yet (OBJ_{obj}.abc / .fbx / .obj in {paths.GEOMETRY})")

    col = get_collection(scene, CAMERAS)
    opts = {"bg_alpha": props.metashape_bg_alpha, "bg_depth": props.metashape_bg_depth, "display_size": 0.2,
            "clip_start": 0.01, "clip_end": 1000.0, "relative": True}
    keep = set()
    for n, (c, cal, photo, out) in enumerate(jobs):
        yield 0.55 + 0.45 * n / max(len(jobs), 1), f"camera {c['label']}"
        bg = out if os.path.exists(out) else None
        ob = build_camera(c, cal, bg, col, opts)
        model.move_to(ob, col)                  # only in CAMERAS (MultiCamProject wants cameras only there)
        parent_to(ob, rig, c["matrix"] @ FLIP)
        ob["ll_sensor"] = c["sensor"]
        keep.add(ob.name)
    removed = 0
    for o in list(col.objects):                 # scan cameras no longer in the XML; other cameras stay
        if o.type == "CAMERA" and o.name not in keep and "metashape_res" in o:
            model.remove_object(o)
            removed += 1
    for name in (f"Geometry_{obj}", f"Cameras_{obj}"):
        _drop_old_collection(name)
    props.metashape_collection = col.name
    lines.append(f"{len(keep)} camera(s) in {col.name}, all under the '{TRANSFORM}' empty"
                 + (f", {removed} old one(s) removed" if removed else ""))
    if skipped:
        lines.append(f"{len(skipped)} camera(s) skipped: " + ", ".join(skipped[:5]))
    no_photo = [c["label"] for c, _cal, photo, out in jobs if not photo and not os.path.exists(out)]
    if no_photo:
        lines.append(f"{len(no_photo)} camera(s) without a photo (no background): " + ", ".join(no_photo[:5]))
    if jobs:
        first = bpy.data.objects.get(jobs[0][0]["label"])
        if first:
            scene.camera = first
            res = first.get("metashape_res")
            if res:
                scene.render.resolution_x, scene.render.resolution_y = int(res[0]), int(res[1])
    return lines


def undistort_queue(root, overwrite=False, ext=".jpg"):
    """Step 7 work list: [(camera name, sensor id, cal, source photo, output path, needs undistort)]
    and the calibration fingerprints to store afterwards."""
    found = paths.locate(root)
    sensors, _cams, jobs, _ = camera_jobs(root, found)
    m = marker.read(root) or {}
    old = m.get("calibration_fingerprint") or {}
    old = old if isinstance(old, dict) else {}
    done_already = published_undistorted(root)
    q = []
    for c, cal, photo, out in jobs:
        stale = old.get(c["sensor"]) not in (None, fingerprint(cal))
        need = not done_already and photo is not None and (overwrite or stale or not os.path.exists(out))
        if need and not os.path.exists(out):
            out = os.path.splitext(out)[0] + ext
        q.append((c["label"], c["sensor"], cal, photo, out, need))
    return q, {sid: fingerprint(cal) for sid, cal in sensors.items()}


def set_camera_background(name, path):
    ob = bpy.data.objects.get(name)
    if ob and ob.type == "CAMERA" and os.path.exists(path):
        props = bpy.context.scene.livinglacquer_props
        set_background(ob.data, path, props.metashape_bg_alpha, props.metashape_bg_depth, relative=True)
        ob["metashape_photo"] = bpy.path.relpath(path) if bpy.data.filepath else path


def save_fingerprints(root, prints):
    m = marker.read(root)
    if m is None:
        m = marker.update(root)
    m["calibration_fingerprint"] = prints
    marker.write(root, m)


# ---- step 8: publish

def engine_result(root):
    """The newest engine_result.json under zz.Agisoft / zz.COLMAP_OMVS, as (folder, dict), or (None, None)."""
    found = paths.locate(root)
    best = (0, None, None)
    for base in (found["agisoft"], found["open"]):
        if not base:
            continue
        for d, _dirs, files in os.walk(base):
            if "engine_result.json" in files:
                p = os.path.join(d, "engine_result.json")
                try:
                    data = json.load(open(p, encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if os.path.getmtime(p) > best[0]:
                    best = (os.path.getmtime(p), d, data)
    return best[1], best[2]


def _set_aside(path, stamp):
    """Move a published file that is about to be replaced into <folder>\\zz.Replaced\\<stamp>\\
    (never delete an export the user made)."""
    if not os.path.exists(path):
        return
    d = os.path.join(os.path.dirname(path), "zz.Replaced", stamp)
    os.makedirs(d, exist_ok=True)
    os.replace(path, os.path.join(d, os.path.basename(path)))


def _copy(src, dst, stamp=None):
    """Copy unless dst already has the same size and is not older; temp + rename. True when copied.
    With stamp, a different dst is set aside first."""
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src) \
            and os.path.getmtime(dst) >= os.path.getmtime(src) - 1:
        return False
    if stamp:
        _set_aside(dst, stamp)
    tmp = dst + ".ll_tmp"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    return True


def publish(root):
    """Step 8. Copy the newest engine result into 01.CAM_Photos + 02.Geometry with the §2 names and
    record it in livinglacquer.json. Idempotent. Generator (job step): yields progress, returns
    report lines."""
    yield 0.0, "looking for the engine result"
    found = paths.locate(root)
    obj = found["object"]
    paths.create_tree(root)
    found = paths.locate(root)
    folder, res = engine_result(root)
    lines, copied = [], 0
    m = marker.read(root) or marker.update(root)
    if res:
        get = lambda key: os.path.join(folder, res[key]) if res.get(key) else None
        xml, mdl = get("cameras"), get("model")
        stamp = datetime.now().strftime("%y%m%d_%H%M")         # short: paths must stay under 260 characters
        same_engine = (m.get("published") or {}).get("engine") == res.get("engine")
        keep = None if same_engine else stamp      # replacing another engine's files: set them aside
        if xml and os.path.exists(xml):
            copied += _copy(xml, os.path.join(found["cam"], f"CAM_{obj}.xml"), keep)
        yield 0.05, "model"
        if mdl and os.path.exists(mdl):
            ext = os.path.splitext(mdl)[1].lower()
            for f in os.listdir(found["geometry"]):          # one model format at a time
                if f.lower().startswith(f"obj_{obj}".lower()) and f.lower().endswith(paths.MODEL_EXTS) \
                        and not f.lower().endswith(ext):
                    _set_aside(os.path.join(found["geometry"], f), stamp)
            if ext == ".obj":
                dst = os.path.join(found["geometry"], f"OBJ_{obj}{ext}")
                if keep and os.path.exists(dst):
                    _set_aside(dst, stamp)
                copied += _copy_obj(mdl, dst, f"OBJ_{obj}.mtl")
            else:
                copied += _copy(mdl, os.path.join(found["geometry"], f"OBJ_{obj}{ext}"), keep)
            if ext == ".obj" and res.get("mtl"):
                copied += _write_mtl(get("mtl"), os.path.join(found["geometry"], f"OBJ_{obj}.mtl"),
                                     res.get("textures", []), obj)
        for i, t in enumerate(res.get("textures", [])):
            yield 0.3, f"texture {i + 1}"
            src = os.path.join(folder, t)
            if os.path.exists(src):
                suffix = "" if i == 0 else f"_{i + 1}"
                copied += _copy(src, os.path.join(found["geometry"],
                                                  f"OBJ_{obj}{suffix}{os.path.splitext(src)[1].lower()}"), keep)
        pdir = get("photos")
        if pdir and os.path.isdir(pdir):
            photos = [f for f in os.listdir(pdir) if f.lower().endswith(paths.PHOTO_EXTS)]
            for n, f in enumerate(photos):
                yield 0.4 + 0.6 * n / len(photos), f
                copied += _copy(os.path.join(pdir, f), os.path.join(found["cam"], f))
        m["published"] = {"engine": res.get("engine", ""), "date": datetime.now().isoformat(timespec="seconds"),
                          "undistorted": bool(res.get("undistorted")), "source": paths.rel(root, folder)}
        lines.append(f"Published the {res.get('engine', '')} result: {copied} file(s) copied"
                     + ("" if copied else " (already up to date)"))
    else:
        m.setdefault("published", {})
        m["published"].update({"engine": m["published"].get("engine") or "AGISOFT",
                               "date": datetime.now().isoformat(timespec="seconds")})
        lines.append("No engine result to copy: the Agisoft exports in 01.CAM_Photos / 02.Geometry are used as they are")
    marker.write(root, m)
    marker.update(root)
    return lines


def _copy_obj(src, dst, mtl_name):
    """Copy an OBJ with its mtllib line pointing at the published .mtl; skipped when dst is newer."""
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return False
    tmp = dst + ".ll_tmp"
    with open(src, encoding="utf-8", errors="replace") as fi, open(tmp, "w", encoding="utf-8") as fo:
        for line in fi:
            fo.write(f"mtllib {mtl_name}\n" if line.startswith("mtllib ") else line)
    os.replace(tmp, dst)
    return True


def _write_mtl(src, dst, textures, obj):
    """OpenMVS writes texture names into the .mtl: point them at the published OBJ_<Object> names."""
    try:
        text = open(src, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    for i, t in enumerate(textures):
        new = f"OBJ_{obj}{'' if i == 0 else f'_{i + 1}'}{os.path.splitext(t)[1].lower()}"
        text = text.replace(os.path.basename(t), new)
    old = open(dst, encoding="utf-8").read() if os.path.exists(dst) else None
    if old == text:
        return False
    with open(dst + ".ll_tmp", "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(dst + ".ll_tmp", dst)
    return True
