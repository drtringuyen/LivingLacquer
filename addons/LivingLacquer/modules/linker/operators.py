"""Step 5 - Check Links: Check (report) and Fix (confirm, then rename / relink / pull / relative / marker)."""
import os
import time

import bpy
from bpy.app.handlers import persistent

from ..project import marker, paths, state
from . import blendpaths, checks

# last report, for the open .blend only
REPORT = {"blend": None, "items": [], "seconds": 0.0}


def run_check(root):
    t = time.time()
    items, found = checks.check_folder(root)
    blend_items, actions = blendpaths.plan(root, found)
    REPORT.update(blend=bpy.data.filepath, items=items + blend_items, seconds=time.time() - t)
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
        return bool(state.get()["root"])

    def execute(self, context):
        if context.window:
            context.window.cursor_set("WAIT")
        try:
            run_check(state.get()["root"])
        except Exception as e:
            self.report({"ERROR"}, f"Check Links failed: {e}")
            return {"CANCELLED"}
        finally:
            if context.window:
                context.window.cursor_set("DEFAULT")
        ok, warn, err = counts()
        self.report({"INFO"}, f"Check Links: {ok} ok, {warn} warnings, {err} errors ({REPORT['seconds']:.1f} s)")
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeFixLinks(bpy.types.Operator):
    """Rename old folders, relink missing files, copy external files in, make paths relative and
    write livinglacquer.json. Renames and copies on disk cannot be undone"""
    bl_idname = "livinglacquer.pipe_fix_links"
    bl_label = "Fix Links"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"])

    def _gather(self, root):
        found, actions = run_check(root)
        self.renames = found["renames"]
        self.tree = [r for r in paths.TREE if not os.path.isdir(os.path.join(root, *r.split("/")))]
        self.actions = actions
        self.write_marker = True
        self.lines = blendpaths.describe(root, actions, self.renames, self.tree, self.write_marker)

    def invoke(self, context, event):
        self._gather(state.get()["root"])
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
        problems = []
        for p, new in self.renames:
            try:
                blendpaths.rename_folder(p, new)
            except OSError as e:
                problems.append(str(e))
        if self.renames:        # paths moved: plan again on the new names
            found, self.actions = run_check(root)
        paths.create_tree(root)
        done, more = blendpaths.apply(self.actions)
        problems += more
        try:
            marker.update(root, engine=context.scene.livinglacquer_props.pipe_engine)
        except OSError as e:
            problems.append(f"livinglacquer.json: {e}")
        state.refresh()
        run_check(root)
        for p in problems:
            print("LivingLacquer Fix Links:", p)
        msg = f"Fix Links: {done} path(s) updated, {len(self.renames)} folder(s) renamed"
        if problems:
            self.report({"WARNING"}, msg + f", {len(problems)} problem(s) (see the console)")
        else:
            self.report({"INFO"}, msg + "; save the .blend to keep them")
        return {"FINISHED"}


@persistent
def _clear(*_args):
    REPORT.update(blend=None, items=[], seconds=0.0)


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
