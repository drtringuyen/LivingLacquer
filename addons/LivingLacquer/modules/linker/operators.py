"""Step 5 - Check Links: Check (report) and Fix (confirm, then rename / relink / pull / relative / marker).
Both run as jobs (progress bar + status bar): the photo headers may stream from Google Drive."""
import os
import time

import bpy
from bpy.app.handlers import persistent

from ..project import jobs, marker, paths, state, steps
from . import blendpaths, checks

# last report, for the open .blend only; found / actions feed the Fix dialog
REPORT = {"blend": None, "items": [], "seconds": 0.0, "found": None, "actions": []}


def check_steps(root):
    """Job steps that fill REPORT."""
    def folder(job):
        job.data["t0"] = time.time()
        job.data["items"], job.data["found"] = yield from checks.check_folder_iter(root)

    def blend(job):
        items, actions = blendpaths.plan(root, job.data["found"])
        REPORT.update(blend=bpy.data.filepath, items=job.data["items"] + items, found=job.data["found"],
                      actions=actions, seconds=time.time() - job.data["t0"])
        steps.record_check(root, *counts())          # step 5's state for the step list

    return [jobs.Step("Folders and photos", folder, weight=9), jobs.Step(".blend paths", blend, weight=1)]


def run_check(root):
    """Check without a job (tests, Fix in background mode). Returns (found, actions)."""
    t = time.time()
    items, found = checks.check_folder(root)
    blend_items, actions = blendpaths.plan(root, found)
    REPORT.update(blend=bpy.data.filepath, items=items + blend_items, seconds=time.time() - t, found=found,
                  actions=actions)
    return found, actions


def counts():
    """(ok, warn, error) of the current report; INFO counts as ok."""
    sevs = [i["sev"] for i in REPORT["items"]] if REPORT["blend"] == bpy.data.filepath else []
    return (sum(s in (checks.OK, checks.INFO) for s in sevs), sevs.count(checks.WARN), sevs.count(checks.ERROR))


def has_fixes():
    return REPORT["blend"] == bpy.data.filepath and any(i["fix"] for i in REPORT["items"])


class LIVINGLACQUER_OT_PipeCheckLinks(bpy.types.Operator):
    """Check the object folder, the photos, the camera XML and every file path in this .blend"""
    bl_idname = "livinglacquer.pipe_check_links"
    bl_label = "Check Links"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def execute(self, context):
        def done(job):
            if job.state == "done":
                ok, warn, err = counts()
                print(f"LivingLacquer Check Links: {ok} ok, {warn} warnings, {err} errors "
                      f"({REPORT['seconds']:.1f} s)")
        jobs.run_or_start(jobs.Job("Check Links", check_steps(state.get()["root"]), on_done=done))
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeFixLinks(bpy.types.Operator):
    """Rename old folders, relink missing files, copy external files in, make paths relative and
    write livinglacquer.json. Renames and copies on disk cannot be undone"""
    bl_idname = "livinglacquer.pipe_fix_links"
    bl_label = "Fix Links"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and not jobs.busy()

    def _gather(self, root):
        if REPORT["blend"] != bpy.data.filepath or REPORT["found"] is None:
            run_check(root)
        found = REPORT["found"]
        self.renames = found["renames"]
        self.tree = [r for r in paths.TREE if not os.path.isdir(os.path.join(root, *r.split("/")))]
        self.actions = REPORT["actions"]
        self.lines = blendpaths.describe(root, self.actions, self.renames, self.tree, True)

    def invoke(self, context, event):
        self._gather(state.get()["root"])          # from the last Check: no wait before the dialog
        return context.window_manager.invoke_props_dialog(self, width=480, confirm_text="Fix")

    def draw(self, context):
        col = self.layout.column(align=True)
        for line in self.lines:
            col.label(text=line, icon="DOT")
        col.separator()
        col.label(text="Save the .blend afterwards to keep the new paths.", icon="INFO")

    def execute(self, context):
        root = state.get()["root"]
        if not hasattr(self, "lines"):
            self._gather(root)
        renames, engine = self.renames, context.scene.livinglacquer_props.pipe_engine
        data = {"problems": [], "done": 0, "actions": self.actions}

        def rename(job):
            for n, (p, new) in enumerate(renames):
                yield n / max(len(renames), 1), os.path.basename(p)
                try:
                    blendpaths.rename_folder(p, new)
                except OSError as e:
                    data["problems"].append(str(e))
            if renames:                     # paths moved: plan again on the new names
                found, data["actions"] = run_check(root)
            paths.create_tree(root)

        def relink(job):
            data["done"], more = yield from blendpaths.apply(data["actions"])
            data["problems"] += more
            try:
                marker.update(root, engine=engine)
            except OSError as e:
                data["problems"].append(f"livinglacquer.json: {e}")
            state.refresh()

        def done(job):
            for p in data["problems"]:
                print("LivingLacquer Fix Links:", p)
            print(f"LivingLacquer Fix Links: {data['done']} path(s) updated, {len(renames)} folder(s) renamed, "
                  f"{len(data['problems'])} problem(s); save the .blend")

        steps = [jobs.Step("Rename folders", rename, weight=1), jobs.Step("Relink", relink, weight=4)] \
            + check_steps(root)
        jobs.run_or_start(jobs.Job("Fix Links", steps, on_done=done))
        return {"FINISHED"}


@persistent
def _clear(*_args):
    REPORT.update(blend=None, items=[], seconds=0.0, found=None, actions=[])


classes = (LIVINGLACQUER_OT_PipeCheckLinks, LIVINGLACQUER_OT_PipeFixLinks)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(_clear)


def unregister():
    if _clear in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_clear)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
