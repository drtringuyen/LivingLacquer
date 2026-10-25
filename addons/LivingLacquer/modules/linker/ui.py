"""Step 5 row of the Scan Pipeline panel and the report under it."""
import bpy

from . import checks, operators

ICONS = {checks.OK: "CHECKMARK", checks.INFO: "INFO", checks.WARN: "ERROR", checks.ERROR: "CANCEL"}
ORDER = {checks.ERROR: 0, checks.WARN: 1, checks.INFO: 2, checks.OK: 3}
MAX_LINES = 12


def draw_step(number, layout, context):
    props = context.scene.livinglacquer_props
    rep = operators.REPORT
    current = rep["blend"] == bpy.data.filepath and rep["items"]
    row = layout.row(align=True)
    row.operator("livinglacquer.pipe_check_links", text="Check", icon="VIEWZOOM")
    if current:
        ok, warn, err = operators.counts()
        row.label(text=str(ok), icon="CHECKMARK")
        row.label(text=str(warn), icon="ERROR")
        row.label(text=str(err), icon="CANCEL")
    sub = row.row(align=True)
    sub.enabled = bool(current) and operators.has_fixes()
    sub.operator("livinglacquer.pipe_fix_links", text="Fix…", icon="TOOL_SETTINGS")
    if not current:
        return
    layout.prop(props, "pipe_show_report", icon="TRIA_DOWN" if props.pipe_show_report else "TRIA_RIGHT",
                emboss=False)
    col = layout.column(align=True)
    for it in sorted(rep["items"], key=lambda i: ORDER[i["sev"]]):
        if not props.pipe_show_report and it["sev"] in (checks.OK, checks.INFO):
            continue
        col.label(text=f"{it['code']}  {it['title']}", icon=ICONS[it["sev"]])
        if props.pipe_show_report:
            for line in it["lines"][:MAX_LINES]:
                col.label(text="      " + line)
            if len(it["lines"]) > MAX_LINES:
                col.label(text=f"      … {len(it['lines']) - MAX_LINES} more")
