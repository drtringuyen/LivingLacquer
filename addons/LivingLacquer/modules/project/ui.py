"""Scan Pipeline panel: the numbered steps (plan §3). Each step is a box whose header shows its state
(steps.py: done / stale / to do / blocked) and opens or closes it; done steps are greyed and closed,
the current step is open. The step's content is drawn by the module that owns it, with its main action
as a big button named after the step."""
import importlib
import os

import bpy

from . import state, steps

# number, module that draws the step (its ui.draw_step(number, layout, context))
STEPS = [(1, ("project",)), (2, ("ingest",)), (3, ("engines", "linker")), (4, ("scene",)), (5, ("scene",))]
BIG = 1.5               # height of a step's main button
# green = done, red = a problem (alert), the current step is lit and marked with a play arrow
ICON = {steps.DONE: "STRIP_COLOR_04", steps.STALE: "STRIP_COLOR_01", steps.TODO: "RADIOBUT_OFF",
        steps.BLOCKED: "LOCKED"}


def big_row(layout):
    """Row for a step's main button (taller, easier to read and hit)."""
    row = layout.row(align=True)
    row.scale_y = BIG
    return row


def draw_step(number, layout, context):
    """Step 1 - Object (this module)."""
    st = state.get()
    row = big_row(layout)
    row.operator("livinglacquer.pipe_new_object", text="1. New Object…", icon="FILE_NEW")
    row.operator("livinglacquer.pipe_open_object", text="Open Object…", icon="FILE_FOLDER")
    if not st["root"]:
        layout.label(text="Not in an object folder: New Object saves it into one" if bpy.data.filepath
                     else "Save as an object to start", icon="ERROR")


class LIVINGLACQUER_PT_Pipeline(bpy.types.Panel):
    bl_label = "Scan Pipeline"
    bl_idname = "LIVINGLACQUER_PT_pipeline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LivingLacquer"
    bl_parent_id = "LIVINGLACQUER_PT_main"
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(icon='SEQUENCE')

    def draw(self, context):
        from ... import module_manager
        props = context.scene.livinglacquer_props
        st = state.get()
        layout = self.layout

        from . import jobs
        jobs.draw_progress(layout)

        row = layout.row(align=True)
        row.prop(props, "pipe_engine", expand=True)
        row.operator("livinglacquer.pipe_refresh_steps", text="", icon="FILE_REFRESH")
        row.prop(props, "pipe_show_gear", text="", icon="PREFERENCES")
        if props.pipe_show_gear:
            self._draw_gear(layout, context, st)

        status = steps.get()
        current = steps.current()
        for number, mods in STEPS:
            state_, note = status.get(number, (steps.TODO, ""))
            loaded = [m for m in mods if m == "project" or module_manager.is_loaded(m)]
            box = layout.box()
            hdr = box.row(align=True)
            hdr.alert = state_ == steps.STALE                          # a problem: red
            hdr.active = state_ != steps.BLOCKED
            icon = "PLAY" if number == current else ICON[state_]
            text = f"{number}. {steps.NAMES[number]}" + (f"   ·   {note}" if note else "")
            hdr.operator("livinglacquer.pipe_toggle_step", text=text, icon=icon, emboss=False,
                         depress=number == current).step = number
            if state_ == steps.DONE and number != current:
                hdr.label(text="", icon="CHECKMARK")
            is_open = steps.expanded(number)
            hdr.label(text="", icon="DISCLOSURE_TRI_DOWN" if is_open else "DISCLOSURE_TRI_RIGHT")
            if not is_open:
                continue
            col = box.column()
            col.enabled = bool(loaded) and (number == 1 or (bool(st["root"]) and state_ != steps.BLOCKED))
            for mod in mods:
                if mod not in loaded:
                    col.label(text=f"Module '{mod}' is off (Infos › Debug › Modules)")
                elif mod == "project":
                    draw_step(number, col, context)
                else:
                    importlib.import_module(f"..{mod}.ui", __package__).draw_step(number, col, context)
            if state_ == steps.BLOCKED:
                need = ", ".join(f"{r}. {steps.NAMES[r]}" for r in steps.NEEDS.get(number, ()))
                box.label(text=f"Do {need} first", icon="LOCKED")

    def _draw_gear(self, layout, context, st):
        box = layout.box()
        box.label(text="Advanced", icon="PREFERENCES")
        from . import prefs
        p = prefs.get()
        if p:
            col = box.column(align=True)
            for name in ("objects_root", "work_root", "colmap_dir", "openmvs_dir", "metashape_exe"):
                col.prop(p, name)
        props = context.scene.livinglacquer_props
        row = box.row(align=True)
        row.prop(props, "pipe_out_format", text="Photos")
        if props.pipe_out_format == "JPG":
            row.prop(props, "pipe_quality")
        row = box.row(align=True)
        row.prop(props, "pipe_preset", text="Engine quality")
        row.prop(props, "pipe_mask_grow", text="Mask edge")
        m = st["marker"]
        if st["root"]:
            from .operators import CACHE
            row = box.row(align=True)
            if m and m.get("drive_root"):
                row.operator("livinglacquer.pipe_cache", text="Push to Drive", icon="EXPORT").action = "PUSH"
            else:
                row.operator("livinglacquer.pipe_cache", text="Pull to Local", icon="IMPORT").action = "PULL"
            if CACHE["open"]:
                row.operator("livinglacquer.pipe_cache", text="Open copy", icon="FILE_BLEND").action = "OPEN"
            if m and m.get("checked_out_by"):
                box.label(text=f"Checked out by {m['checked_out_by']}", icon="LOCKED")
            if CACHE["text"]:
                box.label(text=CACHE["text"])
        if m:
            col = box.column(align=True)
            col.label(text=f"Marker: {m.get('object', '')}  ·  {m.get('account') or 'local folder'}")
            for key, val in m.get("paths", {}).items():
                if isinstance(val, str):
                    col.label(text=f"{key}: {val}")
        elif st["root"]:
            box.label(text="No livinglacquer.json yet (Check Links › Fix writes it)", icon="INFO")


def register():
    from ... import sidebar_tab
    sidebar_tab.register_panel(LIVINGLACQUER_PT_Pipeline)     # in the tab the user named


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_PT_Pipeline)
