"""Steps 6-8: Build Scene, Undistort & Backgrounds, Package. All run as jobs, so the progress bar
(panel + status bar) shows what Blender is doing; Cancel stops them between photos."""
import os

import bpy

from ..ingest import orientation
from ..metashape.photos import undistort_image
from ..project import jobs, marker, paths, state
from . import build, level, turn, view

# last result line per step, for the panel
STATUS = {"build": "", "undistort": "", "package": "", "blend": None}


def _status(key, text):
    STATUS[key] = text
    STATUS["blend"] = bpy.data.filepath


def status(key):
    return STATUS[key] if STATUS["blend"] == bpy.data.filepath else ""


def undistort_steps(root, overwrite, ext, quality):
    """Step 7 as job steps: undistort what is missing / stale, set every camera background."""
    data = {"done": 0, "failed": 0}
    sigs = {}           # camera -> signature of the source photo its camera photo was made from

    def run(job):
        queue, prints = build.undistort_queue(root, overwrite, ext)
        total = sum(1 for j in queue if j[5])
        for n, (name, _sid, cal, photo, out, need) in enumerate(queue):
            yield n / max(len(queue), 1), (f"undistorting {name} ({data['done'] + 1}/{total})" if need
                                           else f"background {name}")
            if need:
                tmp = os.path.splitext(out)[0] + ".ll_tmp" + os.path.splitext(out)[1]
                try:
                    undistort_image(photo, tmp, cal, quality)
                    os.replace(tmp, out)
                    data["done"] += 1
                except Exception as e:
                    data["failed"] += 1
                    job.log(f"{name}: {e}")
                    continue
            if photo is not None and os.path.exists(out):
                try:
                    sigs[name] = build.photo_signature(photo)
                except OSError:
                    pass
            build.set_camera_background(name, out)
        build.save_fingerprints(root, prints if not data["failed"] else
                                (marker.read(root) or {}).get("calibration_fingerprint") or {}, sigs)
        _status("undistort", f"Undistort: {data['done']} photo(s) made"
                + (f", {data['failed']} failed" if data["failed"] else ""))

    steps = [jobs.Step("Undistort & backgrounds", run, weight=10)]
    if orientation.settings(root)["apply"] == "CAMERAS":       # keep the camera photos standing
        steps.append(jobs.Step("Turn camera photos", lambda job: turn.apply(root, quality), weight=2))
    return steps


def _undistort_args(context, redo_all=False):
    """(overwrite, extension, quality). Overwrite only for an explicit "redo all" (never a sticky switch)."""
    props = context.scene.livinglacquer_props
    return redo_all, build.EXT[props.pipe_out_format], props.pipe_quality


def show_first_camera():
    """Look through the first scan camera with its photo showing (after a re-Build)."""
    from ..metashape.cameras import set_view_camera
    rig = bpy.data.objects.get(build.TRANSFORM)
    cams = sorted((o for o in (rig.children if rig else []) if o.type == "CAMERA"), key=lambda o: o.name)
    if not cams:
        return
    props = bpy.context.scene.livinglacquer_props
    if props.pipe_pivot_origin:
        props.pipe_pivot_origin = False                 # it hides the cameras, and with them the photos
    with jobs.ui_override():
        set_view_camera(bpy.context, cams[0])


def start_scaling():
    """Select the Transform empty alone and start interactive scaling about the world origin (where
    Auto Level put the object's center). Returns False when there is no Transform or no 3D view."""
    rig = bpy.data.objects.get(build.TRANSFORM)
    if rig is None or bpy.context.view_layer.objects.get(rig.name) is None:
        return False
    for o in bpy.context.view_layer.objects.selected:
        o.select_set(False)
    rig.hide_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        with jobs.ui_override():
            bpy.ops.transform.resize("INVOKE_DEFAULT", center_override=(0.0, 0.0, 0.0))
    except RuntimeError:
        return False
    return True


class LIVINGLACQUER_OT_PipeAutoLevel(bpy.types.Operator):
    """Stand the scan upright (from the circle of cameras) and put its center on the world origin,
    keeping the scale. Only the Transform empty moves; Ctrl+Z undoes it"""
    bl_idname = "livinglacquer.pipe_auto_level"
    bl_label = "Auto Level & Center"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(build.TRANSFORM) is not None and not jobs.busy()

    def execute(self, context):
        rig = bpy.data.objects[build.TRANSFORM]
        obj = paths.object_name(state.get()["root"]) if state.get()["root"] else ""
        mesh = bpy.data.objects.get(f"OBJ_{obj}") or next((o for o in rig.children if o.type == "MESH"), None)
        tilt = level.level(rig, mesh, [o for o in rig.children if o.type == "CAMERA"])
        if tilt is None:
            self.report({"ERROR"}, "Needs at least 3 cameras under the Transform empty (run Build)")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Tilted {tilt:.0f} deg upright, centered on the origin")
        return {"FINISHED"}


class _PipeOp:
    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()


class LIVINGLACQUER_OT_PipeBuildScene(_PipeOp, bpy.types.Operator):
    """Import the model, assign its textures, build the cameras from the camera XML and line them up,
    then undistort the photos that are missing. Running it again updates everything in place"""
    bl_idname = "livinglacquer.pipe_build_scene"
    bl_label = "Build Scene"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = state.get()["root"]

        def scene_step(job):
            job.data["lines"] = yield from build.build_scene(root)
            job.data["levelled"] = any(l.startswith("Auto Level") for l in job.data["lines"])
            if not bpy.app.background:
                view.frame_scan()           # the scan in the middle of every 3D view, not the empty grid
            if job.data["levelled"]:        # first Build: scale / rotate the scan about the origin
                bpy.context.scene.livinglacquer_props.pipe_pivot_origin = True
            for line in job.data["lines"]:
                print("LivingLacquer Build Scene:", line)
            _status("build", " · ".join(l for l in job.data["lines"] if not l.startswith("Textures")))

        def done(job):
            if job.state != "done":
                _status("build", f"Build Scene: {job.error or job.state}")
            elif bpy.app.background:
                pass
            elif job.data.get("levelled"):
                start_scaling()             # first Build: hand the size over to the user right away
            else:
                show_first_camera()         # later Builds: show the result, a camera with its photo

        steps = [jobs.Step("Build scene", scene_step, weight=3)] + undistort_steps(root, *_undistort_args(context))
        jobs.run_or_start(jobs.Job("Build Scene", steps, on_done=done))
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeUndistort(_PipeOp, bpy.types.Operator):
    """Undistort the photos into 01.CAM_Photos (only the missing or stale ones) and set them as the
    camera backgrounds. Cancel stops between photos; finished photos are kept"""
    bl_idname = "livinglacquer.pipe_undistort"
    bl_label = "Undistort & Backgrounds"
    bl_options = {"REGISTER"}

    redo_all: bpy.props.BoolProperty(name="Redo All", default=False, options={"SKIP_SAVE"},
                                     description="Undistort every photo again, also the ones already made")

    def invoke(self, context, event):
        if self.redo_all:
            return context.window_manager.invoke_confirm(
                self, event, title="Undistort every photo again?",
                message="All camera photos are made again, also the ones already done (takes minutes)",
                confirm_text="Redo All")
        return self.execute(context)

    def execute(self, context):
        root = state.get()["root"]
        jobs.run_or_start(jobs.Job("Undistort", undistort_steps(root, *_undistort_args(context, self.redo_all))))
        return {"FINISHED"}


def package_steps(root):
    """Step 8 as job steps (also the last steps of the engine jobs)."""
    def publish(job):
        job.data["publish"] = yield from build.publish(root)

    def relative(job):
        try:
            with jobs.ui_override():
                bpy.ops.file.make_paths_relative()
        except RuntimeError as e:
            job.data["publish"].append(f"Some paths stay absolute: {e}")
        state.refresh()
        _status("package", job.data["publish"][0])

    return [jobs.Step("Publish", publish, weight=5), jobs.Step("Relative paths", relative, weight=0.5)]


class LIVINGLACQUER_OT_PipePackage(_PipeOp, bpy.types.Operator):
    """Publish the engine result into 01.CAM_Photos / 02.Geometry with the standard names, update
    livinglacquer.json and make every path in this .blend relative"""
    bl_idname = "livinglacquer.pipe_package"
    bl_label = "Package"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = state.get()["root"]
        jobs.run_or_start(jobs.Job("Package", package_steps(root)))
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeTurnCameras(_PipeOp, bpy.types.Operator):
    """Stand the camera photos the way step 2's "Photos stand" says and roll each camera with its photo,
    without reconstructing again: only the camera photos in 01.CAM_Photos and the cameras change (the
    source photos and the reconstruction stay as they are). Undistort / Build keep them turned"""
    bl_idname = "livinglacquer.pipe_turn_cameras"
    bl_label = "Turn Camera Photos"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return super().poll(context) and bpy.data.objects.get(build.TRANSFORM) is not None

    def execute(self, context):
        root = state.get()["root"]
        quality = context.scene.livinglacquer_props.pipe_quality

        def run(job):
            yield from turn.apply(root, quality, force=True)
            state.refresh()

        def done(job):
            if job.state != "done":
                turn.STATUS["text"] = f"Turn Camera Photos: {job.error or job.state}"
            elif not bpy.app.background:
                show_first_camera()

        jobs.run_or_start(jobs.Job("Turn Camera Photos", [jobs.Step("Turn camera photos", run)], on_done=done))
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeBuildScene, LIVINGLACQUER_OT_PipeUndistort, LIVINGLACQUER_OT_PipePackage,
           LIVINGLACQUER_OT_PipeAutoLevel, LIVINGLACQUER_OT_PipeTurnCameras)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
