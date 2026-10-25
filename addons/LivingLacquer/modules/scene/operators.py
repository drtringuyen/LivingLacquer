"""Steps 6-8: Build Scene, Undistort & Backgrounds, Package. All run as jobs, so the progress bar
(panel + status bar) shows what Blender is doing; Cancel stops them between photos."""
import os

import bpy

from ..metashape.photos import undistort_image
from ..project import jobs, state
from . import build

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
            build.set_camera_background(name, out)
        if not data["failed"]:
            build.save_fingerprints(root, prints)
        _status("undistort", f"Undistort: {data['done']} photo(s) made"
                + (f", {data['failed']} failed" if data["failed"] else ""))

    return [jobs.Step("Undistort & backgrounds", run, weight=10)]


def _undistort_args(context):
    props = context.scene.livinglacquer_props
    return props.pipe_overwrite, build.EXT[props.pipe_out_format], props.pipe_quality


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
            for line in job.data["lines"]:
                print("LivingLacquer Build Scene:", line)
            _status("build", " · ".join(l for l in job.data["lines"] if not l.startswith("Textures")))

        def done(job):
            if job.state != "done":
                _status("build", f"Build Scene: {job.error or job.state}")

        steps = [jobs.Step("Build scene", scene_step, weight=3)] + undistort_steps(root, *_undistort_args(context))
        jobs.run_or_start(jobs.Job("Build Scene", steps, on_done=done))
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeUndistort(_PipeOp, bpy.types.Operator):
    """Undistort the photos into 01.CAM_Photos (only the missing or stale ones) and set them as the
    camera backgrounds. Cancel stops between photos; finished photos are kept"""
    bl_idname = "livinglacquer.pipe_undistort"
    bl_label = "Undistort & Backgrounds"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = state.get()["root"]
        jobs.run_or_start(jobs.Job("Undistort", undistort_steps(root, *_undistort_args(context))))
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


classes = (LIVINGLACQUER_OT_PipeBuildScene, LIVINGLACQUER_OT_PipeUndistort, LIVINGLACQUER_OT_PipePackage)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
