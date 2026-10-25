"""Step 4 row of the Scan Pipeline panel: changes with the engine."""
import os

from ..project import state
from . import agisoft, operators, tools

ICON = {"missing": "CHECKBOX_DEHLT", "writing": "SORTTIME", "ready": "CHECKMARK"}


def draw_step(number, layout, context):
    props = context.scene.livinglacquer_props
    engine = props.pipe_engine
    need = tools.missing(engine)
    if engine == "OPENSOURCE":
        row = layout.row(align=True)
        row.operator("livinglacquer.pipe_reconstruct", text="Run COLMAP + OpenMVS", icon="PLAY").action = "START"
        row.prop(props, "pipe_preset", text="")
    else:
        row = layout.row(align=True)
        row.operator("livinglacquer.pipe_reconstruct", text="Open Metashape", icon="WINDOW").action = "START"
        if engine == "HYBRID":
            row.operator("livinglacquer.pipe_reconstruct", text="Run OpenMVS", icon="PLAY").action = "OPENMVS"
            row.prop(props, "pipe_preset", text="")
        if operators.STATUS["watch"] is not None:
            row.operator("livinglacquer.pipe_reconstruct", text="", icon="PAUSE").action = "STOP"
        ws = operators.STATUS["watch_state"]
        if ws:
            r = layout.row(align=True)
            for key, val in ws.items():
                r.label(text=key, icon=ICON[val])
        _draw_guide(layout, props, engine)
    if need:
        layout.label(text="Not found: " + ", ".join(need) + " (⚙ Advanced)", icon="ERROR")
    line = operators.status()
    if line:
        layout.label(text=line)
    layout.operator("livinglacquer.pipe_show_log", text="Show Log", icon="TEXT", emboss=False)


def _draw_guide(layout, props, engine):
    layout.prop(props, "pipe_show_guide", icon="TRIA_DOWN" if props.pipe_show_guide else "TRIA_RIGHT", emboss=False)
    if not props.pipe_show_guide:
        return
    root = state.get()["root"]
    t = agisoft.targets(root) if root else {}
    col = layout.column(align=True)
    for text, key in agisoft.GUIDE[engine]:
        if key:
            row = col.row(align=True)
            row.label(text=text)
            row.operator("livinglacquer.pipe_copy_path", text="", icon="COPYDOWN").key = key
            col.label(text="      " + os.path.basename(t.get(key, "")) if key != "source" else
                      "      " + t.get(key, "")[-60:])
        else:
            col.label(text=text)
