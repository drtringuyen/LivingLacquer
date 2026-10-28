"""Step 4 - Turn Camera Photos: step 2's "Photos stand" applied only to the camera photos in 01.CAM_Photos
and the cameras, so the reconstruction (made from the photos as stored) stays as it is.

A camera photo turned d deg clockwise is the same picture seen by the camera rolled d deg about its
view axis: matrix @ Rz(d), width / height swapped for 90 / 270, the lens shift turned with it
and lens and shift scaled to the new width (Sensor Fit stays Horizontal). Each
camera remembers its roll (ll_turn; Build starts from the XML, so 0) and livinglacquer.json
"camera_photo_turns" remembers which camera photo files are turned ({camera: [deg, size, mtime]}), so a
photo undistorted or published again (as stored) is turned again and one already turned is left alone."""
import math
import os

import bpy
from mathutils import Matrix, Vector

from ..ingest import deps, masks, orientation
from ..linker.checks import match_photo
from ..metashape.cameras import to_width_fit
from ..project import marker
from . import build, level

PIL_TURNS = {90: "ROTATE_270", 180: "ROTATE_180", 270: "ROTATE_90"}     # clockwise -> PIL (counter-clockwise)
STATUS = {"text": ""}


def wanted(root):
    """{photo stem: clockwise deg} from step 2's settings when they are applied to the cameras, else None."""
    s = orientation.settings(root)
    if s["apply"] != "CAMERAS":
        return None
    t = orientation.table(root, masks.photos(root))
    return {stem: v["turn"] for stem, v in t.items()}


def turn_camera(ob, deg):
    """Roll the camera so it shows its photo turned deg clockwise (from the way Build made it)."""
    delta = (deg - int(ob.get("ll_turn", 0))) % 360
    if not delta:
        return False
    to_width_fit(ob)
    ob.matrix_basis = ob.matrix_basis @ Matrix.Rotation(math.radians(delta), 4, "Z")
    cd = ob.data
    sx, sy = cd.shift_x, cd.shift_y
    c, s = round(math.cos(math.radians(-delta))), round(math.sin(math.radians(-delta)))
    cd.shift_x, cd.shift_y = c * sx - s * sy, s * sx + c * sy
    res = ob.get("metashape_res")
    if res and delta % 180:
        # lens and shift are measured on the photo's width (Sensor Fit Horizontal), which is now the old height
        k = int(res[0]) / int(res[1])
        cd.lens *= k
        cd.shift_x *= k
        cd.shift_y *= k
        ob["metashape_res"] = [int(res[1]), int(res[0])]
    ob["ll_turn"] = deg
    return True


def turn_file(path, delta, quality=95):
    """Turn an image file delta deg clockwise in place (pillow); EXIF Orientation = 1."""
    from PIL import Image
    with Image.open(path) as im:
        exif = im.getexif()
        icc = im.info.get("icc_profile")
        out = im.transpose(getattr(Image.Transpose, PIL_TURNS[delta]))
    exif[orientation.ORIENTATION_TAG] = 1
    kw = {"exif": exif.tobytes()}
    if icc:
        kw["icc_profile"] = icc
    stem, ext = os.path.splitext(path)
    tmp = stem + ".ll_tmp" + ext
    if ext.lower() in (".jpg", ".jpeg"):
        out.convert("RGB").save(tmp, "JPEG", quality=quality, subsampling=0, **kw)
    else:
        out.save(tmp, **kw)
    os.replace(tmp, path)


def _photo_path(ob):
    bg = next((b for b in ob.data.background_images if b.image), None)
    p = bpy.path.abspath(bg.image.filepath) if bg else bpy.path.abspath(ob.get("metashape_photo", ""))
    return (p if p and os.path.exists(p) else None), (bg.image if bg else None)


def upside_down(cams):
    """Cameras whose up points against the scan's up (from all the cameras): their photo is likely
    upside down next to the others (the phone's tag is unreliable pointing straight down / up)."""
    up = level.scan_up(cams)
    if up is None:
        return []
    return [c.name for c in cams if (c.matrix_basis.to_3x3() @ Vector((0, 1, 0))).normalized().dot(up) < -0.5]


def apply(root, quality=95, force=False):
    """Job step (generator): roll every scan camera and turn its photo file the way step 2 says.
    force: also when step 2's choice is not applied to the cameras (the Turn Camera Photos button)."""
    if force:
        s = orientation.settings(root)
        s["apply"] = "CAMERAS"
        orientation.save_settings(root, s)
    want = wanted(root)
    if want is None:
        return
    rig = bpy.data.objects.get(build.TRANSFORM)
    cams = sorted((o for o in (rig.children if rig else []) if o.type == "CAMERA"), key=lambda o: o.name)
    m = marker.read(root) or marker.update(root)
    rec = dict(m.get(build.TURN_RECORDS) or {})
    files = 0
    missing_pil = bool(deps.missing(["PIL"]))
    for n, ob in enumerate(cams):
        yield n / max(len(cams), 1), f"turning {ob.name}"
        stem, _ = match_photo(ob.name, want)
        deg = want.get(stem, 0) if stem else 0
        turn_camera(ob, deg)
        path, img = _photo_path(ob)
        if not path:
            continue
        delta = (deg - build.file_turn(rec, ob.name, path)) % 360
        if delta:
            if missing_pil:
                raise RuntimeError("Install converters first (pillow) to turn the camera photos")
            turn_file(path, delta, quality)
            files += 1
            if img:
                img.reload()
        if deg:
            rec[ob.name] = [deg] + build.photo_signature(path)
        else:
            rec.pop(ob.name, None)
    m = marker.read(root) or m
    m[build.TURN_RECORDS] = rec
    marker.write(root, m)
    sc = bpy.context.scene
    if sc.camera and sc.camera.get("metashape_res"):
        sc.render.resolution_x, sc.render.resolution_y = (int(v) for v in sc.camera["metashape_res"])
    flipped = upside_down(cams)
    relevel = False
    if rig and rig.get("ll_levelled") and cams:
        # levelled while the cameras lay on their sides: now that they stand, an upside-down scene shows
        bpy.context.view_layer.update()
        if sum((c.matrix_world.to_3x3() @ Vector((0, 1, 0))).normalized().z for c in cams) < -0.3 * len(cams):
            mesh = next((o for o in rig.children if o.type == "MESH"), None)
            relevel = level.level(rig, mesh, cams) is not None
    STATUS["text"] = (f"Turned: {sum(1 for v in rec.values() if v[0])} camera photo(s)"
                      + (f", {files} file(s) now" if files else "")
                      + (" · levelled again (it stood upside down)" if relevel else "")
                      + (f" · {len(flipped)} look upside down: {', '.join(flipped[:3])}" if flipped else ""))
    if flipped:
        print("LivingLacquer Turn Camera Photos: upside down next to the others:", ", ".join(flipped))
