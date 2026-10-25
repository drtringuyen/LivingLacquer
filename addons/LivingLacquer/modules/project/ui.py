"""Scan Pipeline panel: the numbered steps (plan §3). Each step is drawn by the module that owns
it; a step whose module is off is greyed out."""
import os

import bpy

from . import state

import importlib

# number, title, module that draws the step (its ui.draw_step(number, layout, context))
STEPS = [
    (2, "Receive", "ingest"),
    (3, "Convert & Sort", "ingest"),
    (4, "Reconstruct", "engines"),
    (5, "Check Links", "linker"),
    (6, "Build Scene", "scene"),
    (7, "Undistort & BG", "scene"),
    (8, "Package", "scene"),
]


def _step_box(layout, number, title, enabled=True):
    box = layout.box()
    box.enabled = enabled
    box.label(text=f"{number}. {title}")
    return box


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
        row.prop(props, "pipe_show_gear", text="", icon="PREFERENCES")
        if props.pipe_show_gear:
            self._draw_gear(layout, context, st)

        # 1. Object
        box = _step_box(layout, 1, "Object")
        row = box.row(align=True)
        row.operator("livinglacquer.pipe_new_object", text="New Object…", icon="FILE_NEW")
        row.operator("livinglacquer.pipe_open_object", text="Open Object…", icon="FILE_FOLDER")
        if st["root"]:
            box.label(text=os.path.basename(st["root"]), icon="CHECKMARK")
        elif bpy.data.filepath:
            box.label(text="Not in an object folder: New Object saves it into one", icon="ERROR")
        else:
            box.label(text="Save as an object to start", icon="ERROR")

        for number, title, mod in STEPS:
            box = _step_box(layout, number, title, enabled=bool(st["root"]) and module_manager.is_loaded(mod))
            if module_manager.is_loaded(mod):
                importlib.import_module(f"..{mod}.ui", __package__).draw_step(number, box, context)
            else:
                box.label(text=f"Module '{mod}' is off (Infos › Debug › Modules)")

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
        row.prop(props, "pipe_overwrite")
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
