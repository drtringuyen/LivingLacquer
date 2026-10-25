"""Step 1 - Object: New Object (folder tree + marker + save as NN.<Object>.blend) and Open Object."""
import os

import bpy
from bpy.props import BoolProperty, StringProperty

from . import marker, paths, prefs, state


def _start_folder():
    """Last objects folder, else the parent of the current object folder."""
    p = prefs.get()
    if p and p.objects_root and os.path.isdir(bpy.path.abspath(p.objects_root)):
        folder = bpy.path.abspath(p.objects_root).rstrip("\\/")
        blend = os.path.join(folder, os.path.basename(folder) + ".blend")
        return os.path.dirname(folder) if paths.object_root(blend) and os.path.isfile(blend) else folder
    root = state.get()["root"]
    return os.path.dirname(root) if root else ""


class LIVINGLACQUER_OT_PipeNewObject(bpy.types.Operator):
    """Create NN.<Object>\\ with the scan folders and save the current file into it as NN.<Object>.blend"""
    bl_idname = "livinglacquer.pipe_new_object"
    bl_label = "New Object"
    bl_options = {"REGISTER"}

    parent_dir: StringProperty(name="Objects Folder", subtype="DIR_PATH",
                               description="Folder holding the NN.<Object> folders (e.g. 00.3D)")
    object_name: StringProperty(name="Name", description="Object name, e.g. BatTrang_Teapot")

    def _parent_is_object(self):
        """The picked folder is itself an object folder (NN.<Object> with its .blend): not a place for
        another object."""
        parent = bpy.path.abspath(self.parent_dir).rstrip("\/")
        return bool(parent) and bool(paths.object_root(os.path.join(parent, os.path.basename(parent) + ".blend")))             and os.path.isfile(os.path.join(parent, os.path.basename(parent) + ".blend"))

    def _target(self):
        parent = bpy.path.abspath(self.parent_dir)
        name = paths.sanitize(self.object_name)
        if not (parent and os.path.isdir(parent) and name) or self._parent_is_object():
            return None
        folder = f"{paths.next_number(parent)}.{name}"
        return os.path.join(parent, folder)

    def invoke(self, context, event):
        if not self.parent_dir:
            self.parent_dir = _start_folder()
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "parent_dir")
        lay.prop(self, "object_name")
        root = self._target()
        if root:
            lay.label(text=f"{os.path.basename(root)}\\{os.path.basename(root)}.blend", icon="FILE_BLEND")
            lay.label(text="The current file is saved there, unsaved changes included.", icon="INFO")
        elif self._parent_is_object():
            lay.label(text=f"{os.path.basename(bpy.path.abspath(self.parent_dir).rstrip(os.sep))} is an object "
                      "folder: pick the folder that holds the objects (e.g. 00.3D)", icon="ERROR")
        else:
            lay.label(text="Pick an existing folder and type a name", icon="ERROR")

    def execute(self, context):
        root = self._target()
        if not root and self._parent_is_object():
            self.report({"ERROR"}, "That folder is an object folder: pick the folder that holds the objects")
            return {"CANCELLED"}
        if not root:
            self.report({"ERROR"}, "Pick an existing objects folder and type a name")
            return {"CANCELLED"}
        if os.path.exists(root):
            self.report({"ERROR"}, f"{root} already exists")
            return {"CANCELLED"}
        try:
            paths.create_tree(root)
            marker.update(root, engine=context.scene.livinglacquer_props.pipe_engine)
        except OSError as e:
            self.report({"ERROR"}, f"Could not create the object folder: {e}")
            return {"CANCELLED"}
        p = prefs.get()
        if p:
            p.objects_root = bpy.path.abspath(self.parent_dir)
        blend = os.path.join(root, os.path.basename(root) + ".blend")
        bpy.ops.wm.save_as_mainfile(filepath=blend, relative_remap=True)
        state.refresh()
        self.report({"INFO"}, f"Saved as {blend}")
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeOpenObject(bpy.types.Operator):
    """Open the .blend of an object folder (pick the folder or its .blend)"""
    bl_idname = "livinglacquer.pipe_open_object"
    bl_label = "Open Object"

    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(default="*.blend", options={"HIDDEN"})
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    discard: BoolProperty(name="Discard Unsaved Changes", default=False,
                          description="Open even though the current file has unsaved changes")

    def invoke(self, context, event):
        start = _start_folder()
        if start:
            self.directory = start + os.sep
            self.filepath = start + os.sep
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        if bpy.data.is_dirty:
            self.layout.prop(self, "discard")

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        if os.path.isdir(path):         # a folder picked: its NN.<Object>.blend
            path = os.path.join(path, os.path.basename(path.rstrip("\\/")) + ".blend")
        if not (path.lower().endswith(".blend") and os.path.isfile(path)):
            self.report({"ERROR"}, "No NN.<Object>.blend there")
            return {"CANCELLED"}
        if bpy.data.is_dirty and not self.discard:
            self.report({"ERROR"}, "The current file has unsaved changes: save it, or tick Discard Unsaved Changes")
            return {"CANCELLED"}
        p = prefs.get()
        root = paths.object_root(path)
        if p and root:
            p.objects_root = os.path.dirname(root)
        bpy.ops.wm.open_mainfile(filepath=path)
        return {"FINISHED"}


CACHE = {"open": "", "text": ""}


class LIVINGLACQUER_OT_PipeCache(bpy.types.Operator):
    """Pull: copy this object from Drive to the local work folder and check it out on this computer.
    Push: copy the changed files back to Drive and release it"""
    bl_idname = "livinglacquer.pipe_cache"
    bl_label = "Local Cache"
    action: bpy.props.EnumProperty(items=[("PULL", "Pull to Local", ""), ("PUSH", "Push to Drive", ""),
                                          ("OPEN", "Open", "")])
    force: BoolProperty(name="Force", default=False, description="Pull even if another computer has it")

    @classmethod
    def poll(cls, context):
        from . import jobs
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        from . import cache, jobs
        root = state.get()["root"]
        if self.action == "OPEN":
            if CACHE["open"] and os.path.isfile(CACHE["open"]):
                if bpy.data.is_dirty:
                    self.report({"ERROR"}, "Save the current file first")
                    return {"CANCELLED"}
                bpy.ops.wm.open_mainfile(filepath=CACHE["open"])
            return {"FINISHED"}
        if bpy.data.is_dirty:
            self.report({"ERROR"}, "Save the .blend first")
            return {"CANCELLED"}

        def done(job):
            CACHE["text"] = f"{job.name}: {job.state}" + (f" ({job.error})" if job.error else "")
            CACHE["open"] = job.data.get("blend", "") if job.state == "done" else ""

        try:
            job = cache.pull_job(root, done, self.force) if self.action == "PULL" else cache.push_job(root, done)
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if bpy.app.background:
            jobs.run_blocking(job)
        else:
            jobs.start(job)
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeNewObject, LIVINGLACQUER_OT_PipeOpenObject, LIVINGLACQUER_OT_PipeCache)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
