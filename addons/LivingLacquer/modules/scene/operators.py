"""Steps 6-8: Build Scene, Undistort & Backgrounds (modal, Esc stops), Package."""
import os

import bpy

from ..metashape.photos import undistort_image
from ..project import paths, state
from . import build

# last result line per step, for the panel
STATUS = {"build": "", "undistort": "", "package": "", "blend": None}


def _status(key, text):
    STATUS[key] = text
    STATUS["blend"] = bpy.data.filepath


def status(key):
    return STATUS[key] if STATUS["blend"] == bpy.data.filepath else ""


class _PipeOp:
    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"])


class LIVINGLACQUER_OT_PipeBuildScene(_PipeOp, bpy.types.Operator):
    """Import the model, assign its textures, build the cameras from the camera XML and line them up.
    Running it again updates everything in place. Undistorts the photos afterwards when needed"""
    bl_idname = "livinglacquer.pipe_build_scene"
    bl_label = "Build Scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = state.get()["root"]
        if context.window:
            context.window.cursor_set("WAIT")
        try:
            lines = build.build_scene(context, root)
        except Exception as e:
            self.report({"ERROR"}, f"Build Scene: {e}")
            return {"CANCELLED"}
        finally:
            if context.window:
                context.window.cursor_set("DEFAULT")
        for line in lines:
            print("LivingLacquer Build Scene:", line)
        warn = any(l.startswith("WARNING") for l in lines)
        _status("build", " · ".join(l for l in lines if not l.startswith("Textures")))
        self.report({"WARNING" if warn else "INFO"}, "Build Scene: " + "; ".join(lines))
        props = context.scene.livinglacquer_props
        q, _ = build.undistort_queue(root, props.pipe_overwrite, build.EXT[props.pipe_out_format])
        if q:                   # step 7 runs inside step 6: undistort what is missing, set the backgrounds
            if bpy.app.background:
                bpy.ops.livinglacquer.pipe_undistort("EXEC_DEFAULT")
            else:
                bpy.ops.livinglacquer.pipe_undistort("INVOKE_DEFAULT")
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeUndistort(_PipeOp, bpy.types.Operator):
    """Undistort the photos into 01.CAM_Photos (only the missing or stale ones) and set them as the
    camera backgrounds. Esc stops; finished photos are kept"""
    bl_idname = "livinglacquer.pipe_undistort"
    bl_label = "Undistort & Backgrounds"
    bl_options = {"REGISTER"}

    _timer = None

    def _prepare(self, context):
        props = context.scene.livinglacquer_props
        self.root = state.get()["root"]
        self.queue, self.prints = build.undistort_queue(self.root, props.pipe_overwrite,
                                                        build.EXT[props.pipe_out_format])
        self.quality = props.pipe_quality
        self.total = sum(1 for j in self.queue if j[5])
        self.done = self.failed = 0
        self.stopped = False

    def _step(self, context):
        name, _sid, cal, photo, out, need = self.queue.pop(0)
        if need:
            tmp = os.path.splitext(out)[0] + ".ll_tmp" + os.path.splitext(out)[1]
            try:
                undistort_image(photo, tmp, cal, self.quality)
                os.replace(tmp, out)
                self.done += 1
            except Exception as e:
                self.failed += 1
                print(f"LivingLacquer Undistort: {name}: {e}")
                return
        build.set_camera_background(context, name, out)

    def _finish(self, context):
        if not self.stopped and not self.failed:
            build.save_fingerprints(self.root, self.prints)
        msg = f"Undistort: {self.done} photo(s) made" + (f", {self.failed} failed" if self.failed else "") \
              + (", stopped" if self.stopped else "")
        _status("undistort", msg)
        self.report({"WARNING" if self.failed or self.stopped else "INFO"}, msg)

    def invoke(self, context, event):
        self._prepare(context)
        if not self.queue:
            self.report({"WARNING"}, "No cameras to undistort (build the scene first)")
            return {"CANCELLED"}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.progress_begin(0, max(len(self.queue), 1))
        wm.modal_handler_add(self)
        self.n0 = len(self.queue)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        self._prepare(context)
        while self.queue:
            self._step(context)
        self._finish(context)
        return {"FINISHED"}

    def modal(self, context, event):
        wm = context.window_manager
        if event.type == "ESC":
            self.stopped = True
            self.queue = [j[:5] + (False,) for j in self.queue]     # keep setting backgrounds, stop undistorting
        if event.type not in ("TIMER", "ESC"):
            return {"PASS_THROUGH"}
        if self.queue:
            self._step(context)
            n = self.n0 - len(self.queue)
            wm.progress_update(n)
            if context.area:
                context.area.header_text_set(f"Undistort: {self.done}/{self.total} photos, camera {n}/{self.n0}"
                                             "  (Esc to stop)")
            return {"RUNNING_MODAL"}
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        if context.area:
            context.area.header_text_set(None)
        self._finish(context)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipePackage(_PipeOp, bpy.types.Operator):
    """Publish the engine result into 01.CAM_Photos / 02.Geometry with the standard names, update
    livinglacquer.json and make every path in this .blend relative"""
    bl_idname = "livinglacquer.pipe_package"
    bl_label = "Package"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = state.get()["root"]
        try:
            lines = build.publish(root)
        except Exception as e:
            self.report({"ERROR"}, f"Package: {e}")
            return {"CANCELLED"}
        try:
            bpy.ops.file.make_paths_relative()
        except RuntimeError as e:
            lines.append(f"Some paths stay absolute: {e}")
        state.refresh()
        _status("package", lines[0])
        self.report({"INFO"}, "Package: " + "; ".join(lines) + "; save the .blend")
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeBuildScene, LIVINGLACQUER_OT_PipeUndistort, LIVINGLACQUER_OT_PipePackage)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
