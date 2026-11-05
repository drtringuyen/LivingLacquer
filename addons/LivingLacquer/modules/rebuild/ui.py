"""Step 5 - Mesh Rebuild: 5a Remesh / Retopo (+ BAo_ from the scan), 5b Paint (the photo, its tools,
Favorites, All Photos), 5c Bake & Export (ALB_ / NOR_ Bake | Load, where ALB_ goes, Lock & Export)."""
import os

import bpy

from ..project.ui import big_row, done_mark, label
from . import core, paint, thumbs

PHOTO_PX = 200          # the photo being painted from, in pixels at UI scale 1
_waiting = {"on": False}


def draw_step(number, layout, context):
    rb = context.scene.livinglacquer_rebuild
    _draw_rebuild(layout, rb)
    layout.separator()
    cams = core.cameras()
    _draw_paint(layout, context, rb, cams)
    _draw_photo_panel(layout, rb)
    layout.separator()
    _draw_bake(layout, rb)


def _draw_rebuild(layout, rb):
    row = big_row(layout)
    row.label(text=label(9, "Remesh / Retopo"), icon="MOD_DECIM")
    done_mark(row, 9)
    layout.row(align=True).prop(rb, "mode", expand=True)
    if rb.mode == "REMESH":
        row = layout.row(align=True)
        row.operator("livinglacquer.rebuild_remesh", text="Copy Scan Mesh", icon="DUPLICATE")
        row.prop(rb, "decimate_ratio", slider=True)
        if core.scan_mesh() is None:
            layout.label(text=f"No ORG_{core.object_name()} yet: Build Scene first", icon="ERROR")
    else:
        layout.row(align=True).prop(rb, "retopo_source", expand=True)
        row = layout.row(align=True)
        if rb.retopo_source == "NEW":
            row.operator("livinglacquer.rebuild_retopo_new", text="New Empty Object", icon="OUTLINER_OB_MESH")
        else:
            row.prop(rb, "retopo_object", text="")
            row.operator("livinglacquer.rebuild_retopo_active", text="", icon="EYEDROPPER")
    ob = rb.target
    if ob is None:
        return
    row = layout.row(align=True)
    row.label(text=ob.name, icon="LOCKED" if core.locked(ob) else "OBJECT_DATA")
    row.prop(rb, "shading", expand=True)
    # BAo_: [4K v] [Bake BAo_ from Scan (4K)] [Cage]
    row = layout.row(align=True)
    sizes = row.row(align=True)
    sizes.ui_units_x = 2.6
    sizes.prop(rb, "resolution", text="")
    row.operator("livinglacquer.rebuild_bake_scan", text=f"Bake BAo_ from Scan ({core.size_label(core.resolution(rb))})",
                 icon="RENDER_STILL").kind = "BAO"
    cage = row.row(align=True)
    cage.ui_units_x = 4.5
    cage.prop(rb, "cage")
    _file_row(layout, core.image(core.BAKED, ob), "BAo_")
    if not len(ob.data.polygons):
        layout.label(text="Model the retopo first: it has no faces yet", icon="INFO")


def _needs_above(layout, text):
    """A step that cannot run yet: an arrow up to the one to do first."""
    row = layout.row()
    row.alert = True
    row.label(text=text, icon="TRIA_UP")


def _needs_5a(ob):
    """What 5a still owes the steps below it, '' when it is done."""
    if not len(ob.data.polygons):
        return "Do 5a first: model the retopo, it has no faces yet"
    return "" if core.has_file(core.image(core.BAKED, ob)) else "Do 5a first: Bake BAo_ from Scan"


def _file_row(layout, img, what):
    """'<what>: <file> (size)' greyed, red when the file is gone; '(none yet)' without one."""
    row = layout.row()
    path = core.image_file(img)
    if img is None:
        row.active = False
        row.label(text=f"{what}: none yet", icon="CHECKBOX_DEHLT")
        return
    row.alert = bool(path) and not core.isfile(path)
    row.active = row.alert
    dirty = " · not saved" if img.is_dirty else ""
    where = f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)}" if path else "(no file)"
    row.label(text=f"{what}: {where}  {core.size_label(img.size[0])}{dirty}", icon="IMAGE_DATA")


def _draw_paint(layout, context, rb, cams):
    """The blue part: the photo being painted from, big, and the paint tools."""
    box = layout.box()
    row = big_row(box)
    row.label(text=label(10, "Paint from Photos into BAp_"), icon="BRUSH_DATA")
    done_mark(row, 10)
    cam = cams.get(rb.photo)
    row = box.row(align=True)
    row.operator("livinglacquer.rebuild_photo_step", text="", icon="TRIA_LEFT").direction = -1
    row.label(text=cam.name if cam else "Pick a photo: Shift+Q", icon="OUTLINER_OB_CAMERA")
    if cam:
        fav = cam.name in core.favorites(rb, cams)
        row.operator("livinglacquer.rebuild_favorite", text="", icon="SOLO_ON" if fav else "SOLO_OFF",
                     depress=fav).name = cam.name
    row.operator("livinglacquer.rebuild_photo_step", text="", icon="TRIA_RIGHT").direction = 1
    if cam:
        box.template_icon(icon_value=_icon(cam) or bpy.types.UILayout.icon("IMAGE_DATA"), scale=PHOTO_PX / 20)
    # [Brush] [Fill] [Erase]  ·  Focus | Lock | Free
    row = box.row(align=True)
    row.scale_y = 1.3
    masking = paint.masking(context)
    row.operator("livinglacquer.rebuild_brush", text="Brush", icon="BRUSH_DATA",
                 depress=paint.painting(context) and not masking)
    row.operator("livinglacquer.rebuild_flood", text="Fill", icon="GP_DRAW_FILL")
    row.operator("livinglacquer.rebuild_mask_brush", text="Erase", icon="EVENT_TABLET_ERASER", depress=masking)
    row.operator("livinglacquer.rebuild_clear_mask", text="Clear", icon="X")
    box.row(align=True).prop(rb, "focus", expand=True)
    row = box.row(align=True)
    row.operator("livinglacquer.rebuild_solo", text="Solo", icon="HIDE_OFF", depress=paint.is_solo(context))
    row.prop(rb, "soft", toggle=True, icon="SMOOTHCURVE")
    row.prop(rb, "flat", toggle=True, icon="SHADING_TEXTURE")
    row.operator("livinglacquer.rebuild_save_painted", text="Save BAp_", icon="FILE_TICK")
    row.operator("livinglacquer.rebuild_reset_painted", text="", icon="TRASH")
    box.operator("livinglacquer.rebuild_pin", text="Pin View for This Photo", icon="PINNED" if paint.has_pin(cam) else "UNPINNED",
                 depress=paint.has_pin(cam))
    row = box.row(align=True)
    row.operator("livinglacquer.realign_camera", text="Realign Camera", icon="CON_CAMERASOLVER")
    row.operator("livinglacquer.restore_camera", text="", icon="LOOP_BACK")
    _file_row(box, core.image(core.PAINTED, rb.target), "BAp_")
    if rb.target is not None and _needs_5a(rb.target):
        _needs_above(box, _needs_5a(rb.target))


def _draw_photo_panel(layout, rb):
    """Favorites, All Photos and the tools float in the viewport: a picture here cannot be clicked or dragged."""
    layout.operator("livinglacquer.rebuild_photo_panel", text="Photo Panel (Shift+Q)", icon="RENDERLAYERS",
                    depress=rb.show_photos)


def _draw_bake(layout, rb):
    """5c, like MultiCamProject's 07 / 08: ALB_ and NOR_ each Bake (01.Bake) or Load (02.Overrides), where
    the finished ALB_ goes, then Lock & Export."""
    box = layout.box()
    row = big_row(box)
    row.label(text=label(11, "Bake & Export"), icon="RENDER_STILL")
    done_mark(row, 11)
    ob = rb.target
    if ob is None:
        box.label(text="Remesh or pick a retopo object first (5a)")
        return
    col = box.column(align=True)
    col.enabled = not core.locked(ob)
    # ALB_: [Bake|Load] [Bake ALB_] [where to?]
    row = col.row(align=True)
    sw = row.row(align=True)
    sw.ui_units_x = 5
    sw.prop(rb, "alb_mode", expand=True)
    if rb.alb_mode == "BAKE":
        row.operator("livinglacquer.rebuild_albedo", text="Bake ALB_ (BAo_ + BAp_)", icon="RENDER_STILL")
    else:
        row.label(text="ALB_ from 02.Overrides")
    row.operator("livinglacquer.alb_edit", text="", icon="IMAGE")
    row.operator("livinglacquer.rebuild_send", text="", icon="EXPORT").kind = "ALB"
    _file_row(col, core.image(core.ALBEDO, ob), "ALB_")
    if rb.alb_mode == "BAKE" and _needs_5a(ob):
        _needs_above(col, _needs_5a(ob))
    _override_note(col, rb, "ALB", ob)
    col.separator()
    # NOR_: [Bake|Load] [Bake NOR_ from Scan]
    row = col.row(align=True)
    sw = row.row(align=True)
    sw.ui_units_x = 5
    sw.prop(rb, "nor_mode", expand=True)
    if rb.nor_mode == "BAKE":
        if rb.nor_source == "HIGHPASS":
            row.operator("livinglacquer.rebuild_highpass", text="Generate NOR_ (High-pass)", icon="NORMALS_FACE")
        else:
            row.operator("livinglacquer.rebuild_bake_scan", text="Bake NOR_ from Scan", icon="NORMALS_FACE").kind = "NOR"
    else:
        row.label(text="NOR_ from 02.Overrides")
    row.operator("livinglacquer.rebuild_send", text="", icon="EXPORT").kind = "NOR"
    if rb.nor_mode == "BAKE":
        col.row(align=True).prop(rb, "nor_source", expand=True)
        if rb.nor_source == "HIGHPASS":
            row = col.row(align=True)
            row.prop(rb, "nor_strength")
            row.prop(rb, "nor_radius")
            row.prop(rb, "nor_invert", text="", icon="ARROW_LEFTRIGHT")
    _file_row(col, core.image(core.NORMAL, ob), "NOR_")
    if rb.nor_mode == "BAKE" and rb.nor_source == "HIGHPASS" and not core.has_file(core.image(core.ALBEDO, ob)):
        _needs_above(col, _needs_5a(ob) or "Bake ALB_ above first")
    _override_note(col, rb, "NOR", ob)
    # Lock & Export
    row = big_row(box)
    if core.locked(ob):
        row.operator("livinglacquer.rebuild_lock_export", text="Unlock", icon="UNLOCKED")
        fbx = ob.get(core.EXPORTED_KEY, "")
        if fbx:
            box.label(text=f"Exported: {os.path.basename(fbx)}", icon="CHECKMARK")
    else:
        row.operator("livinglacquer.rebuild_lock_export", text="Lock & Export FBX", icon="LOCKED")
    # folders
    box.prop(rb, "show_folders", icon="DISCLOSURE_TRI_DOWN" if rb.show_folders else "DISCLOSURE_TRI_RIGHT",
             emboss=False)
    if rb.show_folders:
        col = box.column(align=True)
        col.prop(rb, "bake_dir", text="01 Bake")
        col.prop(rb, "override_dir", text="02 Overrides")
        col.prop(rb, "export_dir", text="Export")


def _override_note(layout, rb, kind, ob):
    """As MultiCamProject: an override found while on Bake (grey), none found while on Load (red)."""
    prefix = core.KIND_PREFIX[kind]
    found = core.isfile(core.override_path(rb, prefix, ob))
    mode = rb.alb_mode if kind == "ALB" else rb.nor_mode
    if mode == "BAKE" and found:
        r = layout.row()
        r.active = False
        r.label(text=f"{prefix}{ob.name}.png found in 02.Overrides: Load to use it", icon="INFO")
    elif mode == "LOAD" and not found:
        r = layout.row()
        r.alert = True
        r.label(text=f"No {prefix}{ob.name}.png in 02.Overrides", icon="ERROR")


def _icon(cam):
    i = thumbs.icon(core.photo_image(cam))
    if not i and not _waiting["on"]:       # the thumbnail is still being read: draw again soon
        _waiting["on"] = True
        bpy.app.timers.register(_redraw, first_interval=0.5)
    return i


def _redraw():
    _waiting["on"] = False
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return None
