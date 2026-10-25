"""Step 4 - Reconstruct, for the engine chosen at the top of the panel."""
import os
import time

import bpy

from ..project import jobs, state
from ..scene import operators as scene_ops
from . import agisoft, guide, pipelines, tools

STATUS = {"text": "", "watch": None, "watch_state": {}, "blend": None, "copied": ""}


def _set(text):
    STATUS["text"] = text
    STATUS["blend"] = bpy.data.filepath


def status():
    return STATUS["text"] if STATUS["blend"] == bpy.data.filepath else ""


def _published(job):
    """on_done of the engine jobs (their last steps published the result, step 8)."""
    if job.state != "done":
        _set(f"{job.name}: {job.error or job.state} (see Show Log)")
        return
    _set(f"{job.name} done · {job.data['publish'][0]} · now press Build")


def _start(job):
    """Engine job + publishing (step 8) as its last steps, with the progress bar."""
    job.steps += scene_ops.package_steps(state.get()["root"])
    jobs.run_or_start(job)


class LIVINGLACQUER_OT_PipeReconstruct(bpy.types.Operator):
    """Agisoft / Hybrid: open Metashape with the paths on the clipboard and watch for the exports.
    Open Source: run COLMAP + OpenMVS in the background (no clicks)"""
    bl_idname = "livinglacquer.pipe_reconstruct"
    bl_label = "Reconstruct"
    action: bpy.props.EnumProperty(items=[("START", "Start", ""), ("OPENMVS", "Run OpenMVS", ""),
                                          ("STOP", "Stop watching", "")])

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        props = context.scene.livinglacquer_props
        root = state.get()["root"]
        engine = props.pipe_engine
        if self.action == "STOP":
            STATUS["watch"] = None
            return {"FINISHED"}
        if self.action == "OPENMVS":
            need = [t for t in tools.missing("HYBRID") if t != "Metashape"]
        else:
            need = tools.missing(engine)
        if need:
            self.report({"ERROR"}, "Not found: " + ", ".join(need) + " (set the paths in ⚙ Advanced)")
            return {"CANCELLED"}
        try:
            if engine == "OPENSOURCE" and self.action == "START":
                _set("Open Source running…")
                _start(pipelines.opensource_job(root, props.pipe_preset, on_done=_published,
                                                with_masks=props.pipe_colmap_masks))
            elif self.action == "OPENMVS":
                _set("Hybrid: OpenMVS running…")
                _start(pipelines.hybrid_job(root, props.pipe_preset, on_done=_published))
            else:
                t = agisoft.targets(root)
                context.window_manager.clipboard = t["source"]
                agisoft.launch(tools.metashape_exe(), root)
                STATUS["watch"] = agisoft.Watcher(root, engine)
                STATUS["watch_state"] = {}
                _set("Metashape opened; the photo folder is on the clipboard. Follow the guide.")
                if not bpy.app.background:
                    guide.open_window(context)     # the guide next to Metashape
                if not bpy.app.timers.is_registered(_watch_tick):
                    bpy.app.timers.register(_watch_tick, first_interval=2.0)
        except Exception as e:
            self.report({"ERROR"}, f"Reconstruct: {e}")
            return {"CANCELLED"}
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeCopyPath(bpy.types.Operator):
    """Copy to the clipboard for Metashape's file dialog: the folder (paste it into the dialog's address
    bar) or the file name (paste it into File name), or the whole path"""
    bl_idname = "livinglacquer.pipe_copy_path"
    bl_label = "Copy Path"
    key: bpy.props.StringProperty()
    part: bpy.props.EnumProperty(items=[("FULL", "Path", ""), ("FOLDER", "Folder", ""), ("NAME", "Name", "")],
                                 default="FULL")

    def execute(self, context):
        root = state.get()["root"]
        if not root:
            return {"CANCELLED"}
        p = agisoft.targets(root).get(self.key, "")
        if self.part == "FOLDER":
            p = os.path.dirname(p)
        elif self.part == "NAME":
            p = os.path.basename(p)
        context.window_manager.clipboard = p
        STATUS["copied"] = f"{self.key}:{self.part}"   # the guide keeps this button lit: where you are
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        self.report({"INFO"}, f"Copied: {p}")
        return {"FINISHED"}


def _watch_tick():
    w = STATUS["watch"]
    if w is None:
        return None
    st = w.check()
    STATUS["watch_state"] = st
    if all(v == "ready" for v in st.values()):
        STATUS["watch"] = None
        if w.engine == "HYBRID":
            if not jobs.busy():
                try:
                    _set("Cameras received: OpenMVS running…")
                    _start(pipelines.hybrid_job(w.root, bpy.context.scene.livinglacquer_props.pipe_preset,
                                                on_done=_published))
                except Exception as e:
                    _set(f"Hybrid: {e}")
        else:
            _set(f"Agisoft exports complete ({time.strftime('%H:%M')}) · now press Build")
            state.refresh()
        return None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return 2.0


classes = (LIVINGLACQUER_OT_PipeReconstruct, LIVINGLACQUER_OT_PipeCopyPath)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    STATUS["watch"] = None
    if bpy.app.timers.is_registered(_watch_tick):
        bpy.app.timers.unregister(_watch_tick)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
