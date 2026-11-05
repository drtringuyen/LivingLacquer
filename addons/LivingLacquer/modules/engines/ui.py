"""Step 3 - Reconstruct, first part: the engine (changes with the engine switch)."""
import os

from ..project import state
from ..project.ui import big_row, done_mark, label
from . import agisoft, operators, tools

ICON = {"missing": "CHECKBOX_DEHLT", "writing": "SORTTIME", "ready": "CHECKMARK"}


def draw_step(number, layout, context):
    props = context.scene.livinglacquer_props
    engine = props.pipe_engine
    need = tools.missing(engine)
    if engine == "OPENSOURCE":
        row = big_row(layout)
        row.operator("livinglacquer.pipe_reconstruct", text=label(4, "Reconstruct: COLMAP + OpenMVS"), icon="PLAY").action = "START"
        row.prop(props, "pipe_preset", text="")
        done_mark(row, 4)
        root = state.get()["root"]
        if root and os.path.isdir(os.path.join(root, "zz.Scan", "zz.Masks")):
            layout.prop(props, "pipe_colmap_masks")
    else:
        row = big_row(layout)
        row.operator("livinglacquer.pipe_reconstruct", text=label(4, "Reconstruct: Open Metashape"), icon="WINDOW").action = "START"
        if engine == "HYBRID":
            row.operator("livinglacquer.pipe_reconstruct", text="Run OpenMVS", icon="PLAY").action = "OPENMVS"
            row.prop(props, "pipe_preset", text="")
        if operators.STATUS["watch"] is not None:
            row.operator("livinglacquer.pipe_reconstruct", text="", icon="PAUSE").action = "STOP"
        done_mark(row, 4)
        ws = operators.STATUS["watch_state"]
        if ws:
            r = layout.row(align=True)
            for key, val in ws.items():
                r.label(text=key, icon=ICON[val])
        _draw_guide(layout, props, engine)
    if need:
        layout.label(text="Not found: " + ", ".join(need) + " (⚙ Advanced)", icon="ERROR")
        if any(n != "Metashape" for n in need):
            row = layout.row()
            row.scale_y = 1.4
            row.operator("livinglacquer.pipe_install_engines", text="Install Engines (COLMAP + OpenMVS)",
                         icon="IMPORT")
    line = operators.status()
    if line:
        layout.label(text=line)
    layout.operator("livinglacquer.pipe_show_log", text="Show Log", icon="TEXT", emboss=False)


def _draw_guide(layout, props, engine):
    """The guide opens in its own window (guide.py), so it can stay next to Metashape."""
    layout.operator("livinglacquer.pipe_agisoft_window", text="How to work in Agisoft  (own window)",
                    icon="WINDOW")
