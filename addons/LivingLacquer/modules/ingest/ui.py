"""Step 2 - Photos: receive (iPhone / watch folder) and convert & sort."""
import bpy

from ..project.ui import big_row
from . import deps, operators, receiver


def draw_step(number, layout, context):
    _draw_receive(layout)
    layout.separator()
    _draw_convert(layout, context)


def _draw_receive(layout):
    st = receiver.status()
    row = big_row(layout)
    if st["running"]:
        row.operator("livinglacquer.pipe_receive", text="2. Stop Receiving", icon="PAUSE").action = "STOP"
    else:
        row.operator("livinglacquer.pipe_receive", text="2. Start Receiving", icon="PLAY").action = "START"
    sub = row.row(align=True)
    sub.active_default = operators.STATUS["watch"]
    sub.operator("livinglacquer.pipe_receive", text="", icon="HIDE_OFF").action = "WATCH"
    if st["running"]:
        img = bpy.data.images.get(operators.STATUS["qr"]) if operators.STATUS["qr"] else None
        if img and img.preview:
            layout.template_icon(icon_value=img.preview.icon_id, scale=8)
        elif deps.missing(["segno"]):
            layout.operator("livinglacquer.pipe_install_deps", text="Install QR code (segno)",
                            icon="IMPORT").packages = "segno"
        layout.label(text=receiver.url())
        layout.label(text=f"{st['count']} photo(s) received" + (f", {st['errors']} failed" if st["errors"] else ""))
        if st["log"]:
            layout.label(text=st["log"][-1])
    elif operators.STATUS["watch"]:
        layout.label(text="Watching zz.Source_Photos: drop photos there (USB / Drive)", icon="HIDE_OFF")
    else:
        layout.label(text="iPhone on the same Wi-Fi: Start, scan the QR code")


def _draw_convert(layout, context):
    need = deps.missing(["PIL", "heif"])
    row = big_row(layout)
    row.operator("livinglacquer.pipe_convert", text="2. Convert & Sort", icon="IMAGE_DATA")
    if need:
        row.operator("livinglacquer.pipe_install_deps", text="Install converters", icon="IMPORT").packages = \
            ",".join(need)
    layout.label(text=operators.STATUS["convert"] or "Runs by itself after receiving")
