"""Steps 2-3: Receive (iPhone server, watch folder) and Convert & Sort."""
import json
import os
import sys
import tempfile
import time

import bpy

from ..project import jobs, paths, state
from . import convert, deps, masks, orientation, preview, receiver

# panel state, for the open .blend only
STATUS = {"convert": "", "qr": "", "watch": False, "watch_sig": None, "watch_t": 0.0, "converted_at": 0,
          "orient": ""}
QUIET_SECONDS = 8       # uploads / folder changes must stop this long before Convert & Sort starts


def _folders(root):
    found = paths.locate(root)
    src = found["source"] or os.path.join(root, paths.SCAN, paths.SOURCE)
    return src, found["originals"] or os.path.join(src, paths.ORIGINALS)


def convert_job(root, fmt="JPG", quality=95):
    """Job for step 3, or a string saying why it cannot run."""
    paths.create_tree(root)
    src, orig = _folders(root)
    p = convert.plan(src, orig, {"JPG": ".jpg", "PNG": ".png", "TIF": ".tif"}[fmt])
    need = deps.missing(sorted(p["needs"]))
    if need:
        return "Install converters first (" + ", ".join(deps.PIP[k] for k in need) + ")"
    tasks_file = os.path.join(tempfile.gettempdir(), f"livinglacquer_convert_{os.getpid()}.json")
    total = len(p["convert"])

    def sort(job):
        moved = 0
        for n, (a, b) in enumerate(p["moves"]):
            yield n / max(len(p["moves"]), 1), os.path.basename(a)
            if os.path.exists(b):
                if os.path.getsize(a) == os.path.getsize(b):
                    os.remove(a)            # same file is already in zz.Originals
                    continue
                stem, ext = os.path.splitext(b)
                b = f"{stem}_dup{ext}"
            os.replace(a, b)
            moved += 1
        job.data["moved"] = moved
        with open(tasks_file, "w", encoding="utf-8") as f:
            json.dump({"quality": quality, "tasks": p["convert"]}, f)

    def on_line(job, line):
        if _count_turn_line(job, line):
            return
        if line.startswith(("OK\t", "FAIL\t")):
            job.data["n"] = job.data.get("n", 0) + 1
            job.data["fail"] = job.data.get("fail", 0) + line.startswith("FAIL")
            job.step_pct = 100.0 * job.data["n"] / max(total, 1)

    def done(job):
        if os.path.exists(tasks_file):
            os.remove(tasks_file)
        n_ok = job.data.get("n", 0) - job.data.get("fail", 0)
        jpg = convert.plan(src, orig)["jpg"]
        STATUS["convert"] = (f"{jpg} JPG ready · {n_ok} converted · {job.data.get('moved', 0)} moved to "
                             f"zz.Originals" + (f" · {job.data['fail']} failed" if job.data.get("fail") else "")
                             + ("" if job.state == "done" else f" · {job.state}"))
        STATUS["converted_at"] = time.time()
        for note in p["notes"]:
            print("LivingLacquer Convert & Sort:", note)
        if preview.STATE["show"] and not bpy.app.background:    # new photos: their thumbnails too
            bpy.app.timers.register(lambda: preview.start(root) and None, first_interval=0.2)

    steps = [jobs.Step("Sort", sort, weight=0.2)]
    if total:
        worker = os.path.join(os.path.dirname(__file__), "worker.py")
        steps.append(jobs.Step(f"Convert {total} photo(s)", [sys.executable, worker, tasks_file],
                               env=deps.worker_env(), weight=max(total, 1)))
    if orientation.settings(root)["apply"] == "PHOTOS":     # chosen once: new photos are turned as well
        steps += turn_steps(root, quality)
    log = os.path.join(root, paths.SCAN, paths.OPEN, "logs", "convert.log")
    return jobs.Job("Convert & Sort", steps, on_done=done, log_path=log, on_line=on_line)


def turn_steps(root, quality=95):
    """Apply to Photos as job steps: turn every source photo whose turn is not 0 in the worker (its mask
    too; the photo as it was kept in zz.Originals\\zz.Before_Turn), set the EXIF tag of the others to 1,
    then forget the single-photo turns (they are in the pixels now). Progress lines say "TURN<TAB>"."""
    tasks_file = os.path.join(tempfile.gettempdir(), f"livinglacquer_turn_{os.getpid()}.json")
    estimate = max(len(masks.photos(root)), 1)

    def prepare(job):
        s = orientation.settings(root)
        t = orientation.table(root, masks.photos(root))
        _src, orig = _folders(root)
        work = [[v["path"], v["turn"], os.path.join(orientation.backup_dir(orig), os.path.basename(v["path"])),
                 masks.mask_for(root, v["path"])] for v in t.values() if v["turn"]]
        cleared = 0
        if s["mode"] != "STORED":
            cleared = sum(orientation.clear_exif_orientation(v["path"]) for v in t.values()
                          if not v["turn"] and v["tag"] != 1)
        job.data.update(turn_total=len(work), turn_n=0, turn_fail=0, tag_cleared=cleared)
        with open(tasks_file, "w", encoding="utf-8") as f:
            json.dump({"quality": quality, "turn": work}, f)

    def finish(job):
        if os.path.exists(tasks_file):
            os.remove(tasks_file)
        s = orientation.settings(root)
        s["turns"], s["apply"] = {}, "PHOTOS"
        n_ok = job.data.get("turn_n", 0) - job.data.get("turn_fail", 0)
        if n_ok:
            s["photos_turned_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        orientation.save_settings(root, s)
        if job.data.get("turn_total"):
            fail = job.data.get("turn_fail", 0)
            STATUS["orient"] = (f"{n_ok} photo(s) turned" + (f", {fail} failed" if fail else "")
                                + (" · reconstruct again" if n_ok else ""))
        if preview.STATE["show"]:
            left = preview.update_icons(root)
            for n, stem in enumerate(left):
                yield n / max(len(left), 1), f"preview {stem}"
                v = preview.STATE["table"][stem]
                preview.STATE["icons"][stem] = preview._icon(stem, v["path"], v["turn"])

    worker = os.path.join(os.path.dirname(__file__), "worker.py")
    return [jobs.Step("Photo turns", prepare, weight=0.1),
            jobs.Step("Turn photos", [sys.executable, worker, tasks_file], env=deps.worker_env(),
                      weight=estimate, when=lambda job: job.data.get("turn_total", 0) > 0),
            jobs.Step("Turned", finish, weight=0.1)]


def _count_turn_line(job, line):
    """on_line for the turn worker: count its OK / FAIL lines while the turn step runs."""
    if "turn_total" not in job.data or job.data.get("turn_n", 0) >= job.data["turn_total"]:
        return False
    if line.startswith(("OK\t", "FAIL\t")):
        job.data["turn_n"] += 1
        job.data["turn_fail"] += line.startswith("FAIL")
        job.step_pct = 100.0 * job.data["turn_n"] / max(job.data["turn_total"], 1)
        job.detail = os.path.basename(line.split("\t")[1])
    return True


class LIVINGLACQUER_OT_PipeInstallDeps(bpy.types.Operator):
    """Download and install the Python packages this step needs into Blender's user scripts folder"""
    bl_idname = "livinglacquer.pipe_install_deps"
    bl_label = "Install"
    packages: bpy.props.StringProperty(default="PIL,heif")

    def execute(self, context):
        keys = [k for k in self.packages.split(",") if k in deps.PIP]
        try:
            jobs.start(deps.install_job(keys))
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeConvert(bpy.types.Operator):
    """Sort zz.Source_Photos: keep the JPGs, convert HEIC / RAW without a JPG, move originals, iPhone
    edits, videos and duplicate Drive copies into zz.Originals. Safe to run again"""
    bl_idname = "livinglacquer.pipe_convert"
    bl_label = "Convert & Sort"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        props = context.scene.livinglacquer_props
        job = convert_job(state.get()["root"], props.pipe_out_format, props.pipe_quality)
        if isinstance(job, str):
            self.report({"ERROR"}, job)
            return {"CANCELLED"}
        if bpy.app.background:
            jobs.run_blocking(job)
        else:
            jobs.start(job)
        return {"FINISHED"}


MODE_TIPS = {
    "AUTO": "Every photo as the phone showed it (its EXIF Orientation tag)",
    "PORTRAIT": "Every photo upright as the phone showed it, and portrait: a photo the phone tagged landscape "
                "(typical when it points straight down) is turned a further 90 deg",
    "LANDSCAPE": "Every photo upright as the phone showed it, and landscape",
    "STORED": "The pixels as the phone stored them, ignoring the EXIF tag (an iPhone stores portrait photos "
              "sideways). What LivingLacquer did before 0.4.4",
}


class LIVINGLACQUER_OT_PipePhotoMode(bpy.types.Operator):
    """How the photos stand (saved in livinglacquer.json). Nothing changes on disk until Apply to Photos
    (step 2) or Turn Camera Photos (step 4)"""
    bl_idname = "livinglacquer.pipe_photo_mode"
    bl_label = "Photos Stand"
    mode: bpy.props.EnumProperty(items=[(k, k.title(), v) for k, v in MODE_TIPS.items()])

    @classmethod
    def description(cls, context, props):
        return MODE_TIPS[props.mode]

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        root = state.get()["root"]
        s = orientation.settings(root)
        s["mode"] = self.mode
        orientation.save_settings(root, s)
        if preview.STATE["show"]:
            preview.start(root)
        else:
            preview.reload_table(root)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipePhotoTurn(bpy.types.Operator):
    """Turn this photo 90 deg clockwise. Shift: 180 deg (upside down). Ctrl: 90 deg counter-clockwise.
    Nothing changes on disk until Apply to Photos (step 2) or Turn Camera Photos (step 4)"""
    bl_idname = "livinglacquer.pipe_photo_turn"
    bl_label = "Turn Photo"
    stem: bpy.props.StringProperty(description="Photo name without extension; empty = every photo")
    deg: bpy.props.IntProperty(default=90)

    @classmethod
    def description(cls, context, props):
        if not props.stem:
            return "Turn every photo 180 deg (the whole set came out upside down)"
        return f"{props.stem}: click turns it 90° clockwise, Shift+click 180° (upside down), Ctrl+click 90° " \
               "counter-clockwise. Nothing changes on disk until Apply"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def invoke(self, context, event):
        if self.stem:
            self.deg = 180 if event.shift else 270 if event.ctrl else 90
        return self.execute(context)

    def execute(self, context):
        root = state.get()["root"]
        s = orientation.settings(root)
        stems = [self.stem] if self.stem else list(preview.STATE["table"] or masks.photos(root))
        for stem in stems:
            deg = (s["turns"].get(stem, 0) + self.deg) % 360
            if deg:
                s["turns"][stem] = deg
            else:
                s["turns"].pop(stem, None)
        orientation.save_settings(root, s)
        preview.start(root)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipePhotoPreview(bpy.types.Operator):
    """Show / hide small pictures of the photos, turned the way they will stand"""
    bl_idname = "livinglacquer.pipe_photo_preview"
    bl_label = "Photo Preview"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        if preview.STATE["show"]:
            preview.STATE["show"] = False
            return {"FINISHED"}
        err = preview.start(state.get()["root"])
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeApplyOrientation(bpy.types.Operator):
    """Turn the photos in zz.Source_Photos (and their masks) the way they stand in the preview, so every
    engine sees them upright. The photos as they were go to zz.Originals\\zz.Before_Turn. Reconstruct again
    afterwards. New photos are turned by Convert & Sort from now on"""
    bl_idname = "livinglacquer.pipe_apply_orientation"
    bl_label = "Apply to Photos"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def invoke(self, context, event):
        n = sum(1 for v in (preview.STATE["table"] or {}).values() if v["turn"])
        return context.window_manager.invoke_confirm(
            self, event, title="Apply to Photos",
            message=f"Turn {n} photo(s) in zz.Source_Photos? The photos as they were are kept in "
                    "zz.Originals\\zz.Before_Turn. The reconstruction has to run again.",
            confirm_text="Turn Photos")

    def execute(self, context):
        root = state.get()["root"]
        if deps.missing(["PIL"]):
            self.report({"ERROR"}, "Install converters first (pillow)")
            return {"CANCELLED"}
        props = context.scene.livinglacquer_props
        job = jobs.Job("Apply to Photos", turn_steps(root, props.pipe_quality),
                       on_line=lambda j, line: _count_turn_line(j, line),
                       log_path=os.path.join(root, paths.SCAN, paths.OPEN, "logs", "convert.log"))
        jobs.run_or_start(job)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeReceive(bpy.types.Operator):
    """Start / stop receiving photos from the iPhone over the local network (scan the QR code with the
    iPhone camera). Windows may ask to allow Blender through the firewall: allow private networks"""
    bl_idname = "livinglacquer.pipe_receive"
    bl_label = "Receive"
    action: bpy.props.EnumProperty(items=[("START", "Start", ""), ("STOP", "Stop", ""), ("WATCH", "Watch", "")])

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"])

    def execute(self, context):
        root = state.get()["root"]
        if self.action == "STOP":
            receiver.stop()
            STATUS["watch"] = False
            return {"FINISHED"}
        paths.create_tree(root)
        _src, orig = _folders(root)
        if self.action == "WATCH":
            STATUS["watch"] = not STATUS["watch"]
            STATUS["watch_sig"] = None
        else:
            try:
                link = receiver.start(orig)
            except OSError as e:
                self.report({"ERROR"}, f"Could not start the receiver: {e}")
                return {"CANCELLED"}
            STATUS["qr"] = _make_qr(link)
            self.report({"INFO"}, f"Receiving on {link}")
        if not bpy.app.timers.is_registered(_watch_tick):
            bpy.app.timers.register(_watch_tick, first_interval=1.0)
        return {"FINISHED"}


def _make_qr(link):
    """PNG of the QR code (segno) loaded as image 'LivingLacquer QR'; '' when segno is not installed."""
    if deps.missing(["segno"]):
        return ""
    import segno
    path = os.path.join(tempfile.gettempdir(), "livinglacquer_qr.png")
    segno.make(link, error="m").save(path, scale=8, border=2)
    img = bpy.data.images.get("LivingLacquer QR")
    if img:
        img.filepath = path
        img.reload()
    else:
        img = bpy.data.images.load(path)
        img.name = "LivingLacquer QR"
    img.preview_ensure()
    img.preview.reload()
    return img.name


def _signature(root):
    src, orig = _folders(root)
    sig = []
    for d in (src, orig):
        try:
            sig += [(f, os.path.getsize(os.path.join(d, f))) for f in os.listdir(d) if not f.endswith(".ll_tmp")]
        except OSError:
            pass
    return tuple(sorted(sig))


def _watch_tick():
    """Every 2 s while receiving / watching: start Convert & Sort once new files stopped arriving."""
    st = receiver.status()
    if not (st["running"] or STATUS["watch"]):
        return None
    root = state.get()["root"]
    if root and not jobs.busy():
        now = time.time()
        fresh = st["running"] and st["last"] > STATUS["converted_at"] and now - st["last"] > QUIET_SECONDS
        if STATUS["watch"]:
            sig = _signature(root)
            if STATUS["watch_sig"] is None:
                STATUS["watch_sig"] = sig
            elif sig != STATUS["watch_sig"]:
                STATUS["watch_sig"], STATUS["watch_t"] = sig, now
            elif STATUS["watch_t"] and now - STATUS["watch_t"] > QUIET_SECONDS:
                STATUS["watch_t"] = 0.0
                fresh = True
        if fresh:
            props = bpy.context.scene.livinglacquer_props
            job = convert_job(root, props.pipe_out_format, props.pipe_quality)
            if isinstance(job, str):
                STATUS["convert"] = job
                STATUS["converted_at"] = now
            else:
                jobs.start(job)
                STATUS["watch_sig"] = None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return 2.0


class LIVINGLACQUER_OT_PipeMakeMasks(bpy.types.Operator):
    """Make a black-and-white mask for every photo (zz.Scan/zz.Masks): white = the object, black = ignored by
    Metashape and COLMAP. For objects moved or flipped between photo sets. The photos are not changed"""
    bl_idname = "livinglacquer.pipe_make_masks"
    bl_label = "Make Masks"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        p = context.scene.livinglacquer_props
        job = masks.make_job(state.get()["root"], p.pipe_mask_method, p.pipe_mask_grow, p.pipe_mask_tolerance)
        if isinstance(job, str):
            self.report({"ERROR"}, job)
            return {"CANCELLED"}
        jobs.run_or_start(job)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeCheckMasks(bpy.types.Operator):
    """Show a sheet of photos with the masked (ignored) part tinted red, in its own window"""
    bl_idname = "livinglacquer.pipe_check_masks"
    bl_label = "Check Masks"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        def done(job):
            if job.state == "done" and masks.STATUS["sheet"] and not bpy.app.background:
                with jobs.ui_override():
                    masks.show_sheet(bpy.context, masks.STATUS["sheet"])
        try:
            deps.ensure_path()
            jobs.run_or_start(jobs.Job("Check Masks", masks.sheet_job(state.get()["root"]).steps, on_done=done))
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeInstallDeps, LIVINGLACQUER_OT_PipeConvert, LIVINGLACQUER_OT_PipeReceive,
           LIVINGLACQUER_OT_PipeMakeMasks, LIVINGLACQUER_OT_PipeCheckMasks, LIVINGLACQUER_OT_PipePhotoMode,
           LIVINGLACQUER_OT_PipePhotoTurn, LIVINGLACQUER_OT_PipePhotoPreview, LIVINGLACQUER_OT_PipeApplyOrientation)


def register():
    preview.register()
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    preview.unregister()
    receiver.stop()
    STATUS["watch"] = False
    if bpy.app.timers.is_registered(_watch_tick):
        bpy.app.timers.unregister(_watch_tick)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
