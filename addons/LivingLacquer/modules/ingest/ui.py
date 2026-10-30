"""Step 2 - Photos: receive (iPhone / watch folder) and convert & sort."""
import bpy

from ..project import jobs, state
from ..project.ui import big_row, done_mark, label
from . import deps, masks, operators, orientation, preview, receiver


def draw_step(number, layout, context):
    _draw_receive(layout)
    layout.separator()
    _draw_convert(layout, context)
    layout.separator()
    _draw_orientation(layout)
    layout.separator()
    _draw_masks(layout, context)


MODE_LABELS = (("AUTO", "As Shot"), ("PORTRAIT", "Portrait"), ("LANDSCAPE", "Landscape"), ("STORED", "Stored"))
TURN_ICONS = {90: "LOOP_FORWARDS", 180: "FILE_REFRESH", 270: "LOOP_BACK"}


def _draw_orientation(layout):
    """How the photos stand: the choice, a preview turned that way, Apply to Photos."""
    root = state.get()["root"]
    if root and preview.STATE["root"] != root:
        try:
            preview.reload_table(root)
        except Exception:
            preview.STATE["root"] = root
    s = preview.STATE["settings"] or {"mode": "STORED", "chosen": False, "apply": None}
    t = preview.STATE["table"]
    box = layout.box()
    row = box.row()
    row.label(text="2c. Photos stand (optional)", icon="ORIENTATION_GIMBAL")
    done_mark(row, done=bool(s.get("apply")))
    row = box.row(align=True)
    for mode, label in MODE_LABELS:
        row.operator("livinglacquer.pipe_photo_mode", text=label, depress=s["mode"] == mode).mode = mode
    row = box.row(align=True)
    row.operator("livinglacquer.pipe_photo_preview", text="Preview", icon="IMAGE_DATA",
                 depress=preview.STATE["show"])
    row.operator("livinglacquer.pipe_photo_turn", text="", icon="FILE_REFRESH").stem = ""
    row.operator("livinglacquer.pipe_apply_orientation", text="Apply to Photos", icon="CHECKMARK")
    sideways = sum(1 for v in t.values() if v["tag"] not in (1, 2))
    if not s["chosen"] and sideways:
        col = box.column(align=True)
        col.alert = True
        col.label(text=f"{sideways} photo(s) stored sideways", icon="ERROR")
        col.label(text="Choose how they stand, check the preview")
    elif t:
        col = box.column(align=True)
        for part in (orientation.summary(t) or f"{len(t)} photos").split(" · "):
            col.label(text=part)
    job = jobs.current()
    if preview.STATE["show"] and preview.STATE["icons"] and jobs.busy() and job.name != "Photo preview":
        # the grid is tall: folded while a job runs, so the progress bar at the top stays in view
        box.label(text=f"Preview folded while {job.name} runs", icon="TIME")
    elif preview.STATE["show"] and preview.STATE["icons"]:
        grid = box.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
        for stem in sorted(preview.STATE["icons"]):
            col = grid.column(align=True)
            col.template_icon(icon_value=preview.STATE["icons"][stem], scale=4.0)
            turn = t.get(stem, {}).get("turn", 0)
            col.operator("livinglacquer.pipe_photo_turn", text=stem[-4:], icon=TURN_ICONS[turn] if turn else "NONE",
                         depress=bool(s.get("turns", {}).get(stem))).stem = stem
        col = box.column(align=True)
        col.label(text="Click a name: 90° right", icon="INFO")
        col.label(text="Shift: 180° (upside down) · Ctrl: 90° left")
    if operators.STATUS["orient"]:
        box.label(text=operators.STATUS["orient"])
    elif s.get("apply") == "PHOTOS":
        box.label(text="Applied to the photos; new ones are turned too", icon="CHECKMARK")
    elif s.get("apply") == "CAMERAS":
        box.label(text="Applied to the camera photos only (step 4)", icon="CHECKMARK")


def _draw_receive(layout):
    st = receiver.status()
    row = big_row(layout)
    if st["running"]:
        row.operator("livinglacquer.pipe_receive", text=label(2, "Stop Receiving"), icon="PAUSE").action = "STOP"
    else:
        row.operator("livinglacquer.pipe_receive", text=label(2, "Start Receiving"), icon="PLAY").action = "START"
    sub = row.row(align=True)
    sub.active_default = operators.STATUS["watch"]
    sub.operator("livinglacquer.pipe_receive", text="", icon="HIDE_OFF").action = "WATCH"
    done_mark(row, 2)
    if st["running"]:
        img = bpy.data.images.get(operators.STATUS["qr"]) if operators.STATUS["qr"] else None
        if img and img.preview:
            layout.template_icon(icon_value=img.preview.icon_id, scale=8)
        elif deps.missing(["segno"]):
            layout.operator("livinglacquer.pipe_install_deps", text="Install QR code (segno)",
                            icon="IMPORT").packages = "segno"
        layout.label(text=receiver.url())
        layout.label(text="Opens in the phone's default browser; Safari works best", icon="INFO")
        if st["https"] and not st["count"]:
            col = layout.column(align=True)
            col.alert = True                              # red: the phone forced a secure link
            col.label(text="The phone tried a secure (https) link and failed.", icon="ERROR")
            col.label(text="Long-press the QR code › Open in Safari,")
            col.label(text="or in Brave: Shields › Upgrade to HTTPS off")
        layout.label(text=f"{st['count']} photo(s) received" + (f", {st['errors']} failed" if st["errors"] else ""))
        if st["log"]:
            layout.label(text=st["log"][-1])
    elif operators.STATUS["watch"]:
        layout.label(text="Watching zz.Source_Photos: drop photos there (USB / Drive)", icon="HIDE_OFF")
    else:
        layout.label(text="iPhone on the same Wi-Fi: Start, scan the QR code")


def _draw_masks(layout, context):
    """Optional: masks so only the object counts (flipped / moved between photo sets)."""
    props = context.scene.livinglacquer_props
    row = big_row(layout)
    row.operator("livinglacquer.pipe_make_masks", text="2d. Make Masks", icon="MOD_MASK")
    row.prop(props, "pipe_mask_method", text="")
    row.operator("livinglacquer.pipe_check_masks", text="", icon="HIDE_OFF")
    if props.pipe_mask_method == "AI" and deps.missing(["ort"]):
        layout.operator("livinglacquer.pipe_install_deps", text="Install AI masking (onnxruntime)",
                        icon="IMPORT").packages = "ort"
    elif props.pipe_mask_method == "COLOR":
        layout.prop(props, "pipe_mask_tolerance", slider=True)
    layout.label(text=masks.STATUS["text"] or "Optional: only if the object moved between photo sets")


def _draw_convert(layout, context):
    need = deps.missing(["PIL", "heif"])
    row = big_row(layout)
    row.operator("livinglacquer.pipe_convert", text=label(3, "Convert & Sort"), icon="IMAGE_DATA")
    if need:
        row.operator("livinglacquer.pipe_install_deps", text="Install converters", icon="IMPORT").packages = \
            ",".join(need)
    done_mark(row, 3)
    layout.label(text=operators.STATUS["convert"] or "Runs by itself after receiving")
