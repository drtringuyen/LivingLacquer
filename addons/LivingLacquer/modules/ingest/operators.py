"""Steps 2-3: Receive (iPhone server, watch folder) and Convert & Sort."""
import json
import os
import sys
import tempfile
import time

import bpy

from ..project import jobs, paths, state
from . import convert, deps, masks, receiver

# panel state, for the open .blend only
STATUS = {"convert": "", "qr": "", "watch": False, "watch_sig": None, "watch_t": 0.0, "converted_at": 0}
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

    steps = [jobs.Step("Sort", sort, weight=0.2)]
    if total:
        worker = os.path.join(os.path.dirname(__file__), "worker.py")
        steps.append(jobs.Step(f"Convert {total} photo(s)", [sys.executable, worker, tasks_file],
                               env=deps.worker_env(), weight=max(total, 1)))
    log = os.path.join(root, paths.SCAN, paths.OPEN, "logs", "convert.log")
    return jobs.Job("Convert & Sort", steps, on_done=done, log_path=log, on_line=on_line)


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
           LIVINGLACQUER_OT_PipeMakeMasks, LIVINGLACQUER_OT_PipeCheckMasks)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    receiver.stop()
    STATUS["watch"] = False
    if bpy.app.timers.is_registered(_watch_tick):
        bpy.app.timers.unregister(_watch_tick)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
