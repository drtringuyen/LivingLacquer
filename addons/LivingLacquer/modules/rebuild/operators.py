"""Step 5 - Mesh Rebuild operators. Anything that would write over a file asks first."""
import os

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import bake, budget, check, core, paint, uv_tools


def _rb(context):
    return context.scene.livinglacquer_rebuild


def _refresh_steps():
    from ..project import steps
    steps.refresh()


def _target_poll(context):
    ob = _rb(context).target
    return ob is not None and ob.name in context.view_layer.objects and not core.locked(ob)


def _confirm(op, context, event, path, what):
    """Ask before writing over path; go straight on when it does not exist yet."""
    if not os.path.isfile(path):
        return op.execute(context)
    return context.window_manager.invoke_confirm(
        op, event, title=f"Overwrite {os.path.basename(path)}?",
        message=f"{what} is replaced in {os.path.basename(os.path.dirname(path))}",
        confirm_text="Overwrite", icon="WARNING")


# ---------------------------------------------------------------- 5a

class LIVINGLACQUER_OT_RebuildRemesh(bpy.types.Operator):
    """Copy the scanned mesh ORG_<Object> as OBJ_<Object> with a Decimate modifier, the LL_ / MAT_
    materials and uv_normal (a copy made before is replaced)"""
    bl_idname = "livinglacquer.rebuild_remesh"
    bl_label = "Remesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return core.scan_mesh() is not None and context.mode == "OBJECT"

    def invoke(self, context, event):
        old = bpy.data.objects.get(f"OBJ_{core.object_name()}")
        if old is None:
            return self.execute(context)
        return context.window_manager.invoke_confirm(self, event, title=f"Replace {old.name}?",
                                                     message="The copy made before is deleted",
                                                     confirm_text="Replace", icon="WARNING")

    def execute(self, context):
        ob = core.remesh(_rb(context))
        self.report({"INFO"}, f"{ob.name}: decimate ratio {_rb(context).decimate_ratio:g}")
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildRetopoNew(bpy.types.Operator):
    """Start an empty mesh OBJ_<Object> on the scan, with the LL_ / MAT_ materials and uv_normal"""
    bl_idname = "livinglacquer.rebuild_retopo_new"
    bl_label = "New Retopo Object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        ob = core.new_retopo(_rb(context))
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildRetopoActive(bpy.types.Operator):
    """Use the active mesh object as the retopo object (it gets the LL_ / MAT_ materials and uv_normal)"""
    bl_idname = "livinglacquer.rebuild_retopo_active"
    bl_label = "Use Active Object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "MESH" and ob != core.scan_mesh()

    def execute(self, context):
        _rb(context).retopo_object = context.active_object
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildBakeScan(bpy.types.Operator):
    """Bake from the scan (ORG_<Object>) onto the rebuilt object's uv_normal at the set resolution:
    BAo_ its colour (BAp_ follows its size), NOR_ its surface detail"""
    bl_idname = "livinglacquer.rebuild_bake_scan"
    bl_label = "Bake from Scan"
    bl_options = {"REGISTER", "UNDO"}
    kind: EnumProperty(items=[("BAO", "BAo_", ""), ("NOR", "NOR_", "")])

    @classmethod
    def poll(cls, context):
        return _target_poll(context) and core.scan_mesh() is not None and _rb(context).target != core.scan_mesh()

    def invoke(self, context, event):
        rb = _rb(context)
        prefix = core.BAKED if self.kind == "BAO" else core.NORMAL
        return _confirm(self, context, event, core.bake_path(rb, prefix, rb.target), f"{prefix}{rb.target.name}")

    def execute(self, context):
        rb = _rb(context)
        if not len(rb.target.data.polygons):
            self.report({"WARNING"}, f"{rb.target.name} has no faces yet")
            return {"CANCELLED"}
        try:
            img = bake.bake_from_scan(context, rb, self.kind)
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{img.name} {core.size_label(img.size[0])} baked")
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildBaseDisc(bpy.types.Operator):
    """A filled circle to start the retopo from. Vertices selected in Edit Mode (the ring of a spout, on the scan
    or any mesh): the circle best fitting them. Nothing selected, or any other mode: under the scan's lowest 2%.
    Ends in Edit Mode with its face selected: go on with uvExtrude"""
    bl_idname = "livinglacquer.rebuild_base_disc"
    bl_label = "Create From Base"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=220, confirm_text="Create")

    def draw(self, context):
        self.layout.prop(_rb(context), "base_segments")

    def execute(self, context):
        selected = None
        if context.mode == "EDIT_MESH":
            obj = context.edit_object
            obj.update_from_editmode()
            n = len(obj.data.vertices)
            flags = np.zeros(n, bool)
            obj.data.vertices.foreach_get("select", flags)
            if flags.any():
                selected = core.world_points(obj, flags)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        ob = core.base_disc(_rb(context), selected, segments=_rb(context).base_segments)
        if ob is None:
            self.report({"WARNING"}, "Select at least 3 vertices that are not in one line" if selected is not None
                        else "No scan mesh yet: Build Scene first")
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode="EDIT")
        context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="SELECT")
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildBudget(bpy.types.Operator):
    """Measure the EXPORT collection's meshes against the budget (area and triangles, modifiers included)"""
    bl_idname = "livinglacquer.rebuild_budget"
    bl_label = "Measure"

    def execute(self, context):
        budget.measure(context)
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildCheckTextures(bpy.types.Operator):
    """Check where the rebuilt objects' textures are: files outside the bake folder / 02.Overrides, copies in other
    folders of the object. Changes nothing"""
    bl_idname = "livinglacquer.rebuild_check_textures"
    bl_label = "Check Textures"

    def execute(self, context):
        check.check(_rb(context))
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildFixTextures(bpy.types.Operator):
    """Fix what Check found: textures into their folder, images relinked, the other copies to the Recycle Bin"""
    bl_idname = "livinglacquer.rebuild_fix_textures"
    bl_label = "Fix Textures"

    @classmethod
    def poll(cls, context):
        return bool(check.REPORT["moves"] or check.REPORT["strays"]) and check.REPORT["blend"] == bpy.data.filepath

    def invoke(self, context, event):
        r = check.REPORT
        return context.window_manager.invoke_confirm(
            self, event, title="Fix Textures?",
            message=f"{len(r['moves'])} to put in place, {len(r['strays'])} copies to the Recycle Bin",
            confirm_text="Fix", icon="WARNING")

    def execute(self, context):
        try:
            placed, gone, removed = check.fix(_rb(context))
        except OSError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{placed} placed, {gone} to the Recycle Bin, {removed} empty folder(s) removed")
        _refresh_steps()
        return {"FINISHED"}


# ---------------------------------------------------------------- 5b: photos

class LIVINGLACQUER_OT_RebuildPhoto(bpy.types.Operator):
    """Paint from this photo (Focus / Lock: look through its camera)"""
    bl_idname = "livinglacquer.rebuild_photo"
    bl_label = "Load Photo"
    name: StringProperty()

    def execute(self, context):
        rb = _rb(context)
        cam = core.cameras().get(self.name)
        if cam is None:
            self.report({"WARNING"}, f"No camera {self.name}")
            return {"CANCELLED"}
        rb.photo = cam.name
        if paint.has_pin(cam):
            rb.focus = "FREE"           # a pinned view is a free one
            context.scene.camera = cam
            paint.update_brush(rb)
            paint.load_pin(context, cam)
            paint.fit_all()
            return {"FINISHED"}
        if rb.focus != "FREE":
            from ..metashape.cameras import set_view_camera
            set_view_camera(context, cam)
            paint.lock_views(rb.focus == "LOCK")
        else:
            context.scene.camera = cam
        paint.update_brush(rb)
        paint.fit_all()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildPin(bpy.types.Operator):
    """Keep this view and the photo's place on it for this photo, for when its camera does not line up: loading the
    photo comes back here. Pressed again without moving: the pin goes"""
    bl_idname = "livinglacquer.rebuild_pin"
    bl_label = "Pin View"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _rb(context).photo in core.cameras()

    def execute(self, context):
        rb = _rb(context)
        cam = core.cameras()[rb.photo]
        if paint.pin_is_current(context, cam):
            paint.unpin(cam)
            self.report({"INFO"}, f"{cam.name}: pin removed")
            return {"FINISHED"}
        again = paint.has_pin(cam)
        if not paint.pin(context, cam):
            self.report({"WARNING"}, "Leave the camera view first: Free, orbit to the view you want, then pin")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{cam.name}: pin {'updated' if again else 'saved'}")
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildPhotoStep(bpy.types.Operator):
    """Paint from the next / previous photo of All Photos, counted from the active camera"""
    bl_idname = "livinglacquer.rebuild_photo_step"
    bl_label = "Step Photo"
    direction: IntProperty(default=1)

    def execute(self, context):
        rb = _rb(context)
        names = sorted(core.cameras())
        if not names:
            return {"CANCELLED"}
        cam = context.scene.camera
        now = rb.photo if rb.photo in names else cam.name if cam else ""
        i = names.index(now) if now in names else -1
        return bpy.ops.livinglacquer.rebuild_photo(name=names[(i + self.direction) % len(names)])


class LIVINGLACQUER_OT_RebuildFavorite(bpy.types.Operator):
    """Add this photo to the Favorites, or take it out"""
    bl_idname = "livinglacquer.rebuild_favorite"
    bl_label = "Favorite"
    name: StringProperty()

    def execute(self, context):
        rb = _rb(context)
        names = core.favorites(rb)
        if self.name in names:
            names.remove(self.name)
        elif self.name:
            names.append(self.name)
        core.write_list(rb.favorites, names)
        return {"FINISHED"}


# ---------------------------------------------------------------- 5b: paint tools

class LIVINGLACQUER_OT_RebuildBrush(bpy.types.Operator):
    """Brush: paint the photo into BAp_ (Texture Paint, the photo as a stencil on the camera frame);
    again to stop painting"""
    bl_idname = "livinglacquer.rebuild_brush"
    bl_label = "Brush"

    @classmethod
    def poll(cls, context):
        return _target_poll(context) and len(_rb(context).target.data.polygons) > 0

    def execute(self, context):
        rb = _rb(context)
        if paint.painting(context) and not paint.masking(context):
            paint.stop(context)
            return {"FINISHED"}
        if rb.photo not in core.cameras():
            self.report({"WARNING"}, "Pick a photo first")
            return {"CANCELLED"}
        paint.start(context, rb)
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildMaskBrush(bpy.types.Operator):
    """Erase: paint black on MSKp_, BAo_ shows under the strokes; again to stop painting"""
    bl_idname = "livinglacquer.rebuild_mask_brush"
    bl_label = "Erase"

    @classmethod
    def poll(cls, context):
        return _target_poll(context) and len(_rb(context).target.data.polygons) > 0

    def execute(self, context):
        if paint.masking(context):
            paint.stop(context)
        else:
            paint.start_mask(context, _rb(context))
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildClearMask(bpy.types.Operator):
    """Clear MSKp_: all of it black, the whole object shows BAo_"""
    bl_idname = "livinglacquer.rebuild_clear_mask"
    bl_label = "Clear MSKp_"

    @classmethod
    def poll(cls, context):
        return _target_poll(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Clear MSKp_?",
                                                     message="All of it goes black: the whole object shows BAo_",
                                                     confirm_text="Clear", icon="WARNING")

    def execute(self, context):
        rb = _rb(context)
        bake.clear_mask(rb, rb.target)
        paint.forget_look()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildFlood(bpy.types.Operator):
    """Fill: the photo into BAp_ wherever its camera sees the object (not its back, not behind other
    parts), MSKp_ white there"""
    bl_idname = "livinglacquer.rebuild_flood"
    bl_label = "Fill"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rb = _rb(context)
        return _target_poll(context) and rb.photo in core.cameras() and len(rb.target.data.polygons) > 0

    def execute(self, context):
        try:
            share = bake.flood(context, _rb(context))
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        paint.forget_look()
        self.report({"INFO"}, f"Filled {share:.0%} of BAp_")
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildSavePainted(bpy.types.Operator):
    """Save BAp_ into its file in the bake folder"""
    bl_idname = "livinglacquer.rebuild_save_painted"
    bl_label = "Save BAp_"

    @classmethod
    def poll(cls, context):
        return core.image(core.PAINTED, _rb(context).target) is not None

    def execute(self, context):
        rb = _rb(context)
        img = core.image(core.PAINTED, rb.target)
        try:
            again = bake.save_painted(img, core.image_file(img) or core.bake_path(rb, core.PAINTED, rb.target))
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if again:
            self.report({"WARNING"}, "Saving lost the paint: it was put back and written again. Check BAp_")
        msk = core.image(core.MASK, rb.target)
        if msk is not None and msk.is_dirty and core.image_file(msk):
            msk.save()
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildResetPainted(bpy.types.Operator):
    """Clear BAp_<name>: everything painted from the photos goes, BAo_ shows again"""
    bl_idname = "livinglacquer.rebuild_reset_painted"
    bl_label = "Reset BAp_"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _target_poll(context) and core.image(core.PAINTED, _rb(context).target) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event, title="Reset BAp_?",
                                                     message="Everything painted is cleared (saved on Save BAp_)",
                                                     confirm_text="Reset", icon="WARNING")

    def execute(self, context):
        import numpy as np
        img = core.image(core.PAINTED, _rb(context).target)
        w, h = img.size
        bake.set_pixels(img, np.zeros((h, w, 4), np.float32))
        msk = core.image(core.MASK, _rb(context).target)
        if msk is not None:
            w, h = msk.size
            clear = np.zeros((h, w, 4), np.float32)
            clear[..., 3] = 1.0
            bake.set_pixels(msk, clear)
        paint.forget_look()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildSolo(bpy.types.Operator):
    """Solo: show only the rebuilt object (the cameras stay); again to show everything"""
    bl_idname = "livinglacquer.rebuild_solo"
    bl_label = "Solo"

    @classmethod
    def poll(cls, context):
        return _rb(context).target is not None

    def execute(self, context):
        paint.solo(context, _rb(context), not paint.is_solo(context))
        return {"FINISHED"}


# ---------------------------------------------------------------- 5c

class LIVINGLACQUER_OT_RebuildAlbedo(bpy.types.Operator):
    """Bake ALB_: LL_'s mix of BAo_, BAp_ and MSKp_, one texture in the bake folder"""
    bl_idname = "livinglacquer.rebuild_albedo"
    bl_label = "Bake ALB_"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rb = _rb(context)
        return _target_poll(context) and rb.alb_mode == "BAKE" and core.has_file(core.image(core.BAKED, rb.target))

    def invoke(self, context, event):
        rb = _rb(context)
        return _confirm(self, context, event, core.bake_path(rb, core.ALBEDO, rb.target),
                        f"{core.ALBEDO}{rb.target.name}")

    def execute(self, context):
        img = bake.combine_albedo(_rb(context))
        self.report({"INFO"}, f"{img.name} {core.size_label(img.size[0])} baked")
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildHighpass(bpy.types.Operator):
    """Generate NOR_ from ALB_ (high-pass of its brightness) into the bake folder"""
    bl_idname = "livinglacquer.rebuild_highpass"
    bl_label = "Generate NOR_"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rb = _rb(context)
        return _target_poll(context) and rb.nor_mode == "BAKE" and core.has_file(core.image(core.ALBEDO, rb.target))

    def invoke(self, context, event):
        rb = _rb(context)
        return _confirm(self, context, event, core.bake_path(rb, core.NORMAL, rb.target), f"{core.NORMAL}{rb.target.name}")

    def execute(self, context):
        img = bake.highpass_normal(_rb(context))
        self.report({"INFO"}, f"{img.name} {core.size_label(img.size[0])} generated")
        _refresh_steps()
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildSend(bpy.types.Operator):
    """Write the current texture on: ALB_ over BAo_ (paint on from it) or into 02.Overrides, NOR_ into
    02.Overrides (Load uses them)"""
    bl_idname = "livinglacquer.rebuild_send"
    bl_label = "Write Current"
    kind: EnumProperty(items=[("ALB", "ALB_", ""), ("NOR", "NOR_", "")], options={"SKIP_SAVE"})
    target: EnumProperty(items=[("ASK", "Ask", ""), ("BAO", "Overwrite BAo_", ""),
                                ("OVERRIDE", "Override", ""), ("CANCEL", "Cancel", "")],
                         default="ASK", options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _target_poll(context)

    def invoke(self, context, event):
        if self.target == "CANCEL":
            return {"CANCELLED"}
        if self.target != "ASK":
            return self.execute(context)
        rb = _rb(context)
        ob = rb.target
        prefix = core.KIND_PREFIX[self.kind]
        if not core.has_file(core.image(prefix, ob)):
            self.report({"WARNING"}, f"{prefix}{ob.name} has no file yet")
            return {"CANCELLED"}
        bao = core.image_file(core.image(core.BAKED, ob)) or core.bake_path(rb, core.BAKED, ob)
        ovr = core.override_path(rb, prefix, ob)
        idname, kind = self.bl_idname, self.kind

        def draw(menu, _context):
            col = menu.layout.column()
            if kind == "ALB":
                op = col.operator(idname, text=f"Overwrite {os.path.basename(bao)}", icon="IMAGE_DATA")
                op.kind, op.target = kind, "BAO"
            op = col.operator(idname, text=f"{'Override' if os.path.isfile(ovr) else 'Export'} "
                                           f"{os.path.basename(ovr)} (02.Overrides)", icon="EXPORT")
            op.kind, op.target = kind, "OVERRIDE"
            col.separator()
            op = col.operator(idname, text="Cancel", icon="CANCEL")
            op.kind, op.target = kind, "CANCEL"

        context.window_manager.popup_menu(draw, title=f"{prefix}{ob.name}: where to?", icon="QUESTION")
        return {"CANCELLED"}

    def execute(self, context):
        try:
            dst = bake.send_current(_rb(context), self.kind, self.target)
        except (OSError, RuntimeError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"{os.path.basename(dst)} written")
        return {"FINISHED"}


class LIVINGLACQUER_OT_RebuildLockExport(bpy.types.Operator):
    """Lock & Export: MAT_ (ALB_ + NOR_) on the rebuilt object, its FBX into the Export folder with the
    textures in Export/Textures, and the textures locked (no more bakes). Again to unlock"""
    bl_idname = "livinglacquer.rebuild_lock_export"
    bl_label = "Lock & Export FBX"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        rb = _rb(context)
        return rb.target is not None and context.mode == "OBJECT"

    def _path(self, context):
        rb = _rb(context)
        return os.path.join(core.folder(rb.export_dir), f"{rb.target.name}.fbx")

    def invoke(self, context, event):
        if core.locked(_rb(context).target):
            return self.execute(context)
        return _confirm(self, context, event, self._path(context), "The FBX")

    def execute(self, context):
        rb = _rb(context)
        ob = rb.target
        if core.locked(ob):
            del ob[core.LOCKED_KEY]
            _refresh_steps()
            return {"FINISHED"}
        if not core.has_file(core.image(core.ALBEDO, ob)):
            self.report({"WARNING"}, "No ALB_ file yet: Bake ALB_ (or Load one) first")
            return {"CANCELLED"}
        rb.shading = "FINAL"
        path = self._path(context)
        with core.lit(ob):
            bake.export_fbx(context, ob, path)
        ob[core.LOCKED_KEY] = True
        ob[core.EXPORTED_KEY] = core.rel(path)
        self.report({"INFO"}, f"{os.path.basename(path)} exported with its textures")
        _refresh_steps()
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_RebuildBaseDisc, LIVINGLACQUER_OT_RebuildBudget, LIVINGLACQUER_OT_RebuildCheckTextures,
           LIVINGLACQUER_OT_RebuildFixTextures, LIVINGLACQUER_OT_RebuildRemesh, LIVINGLACQUER_OT_RebuildRetopoNew, LIVINGLACQUER_OT_RebuildRetopoActive,
           LIVINGLACQUER_OT_RebuildBakeScan, LIVINGLACQUER_OT_RebuildPhoto, LIVINGLACQUER_OT_RebuildPin, LIVINGLACQUER_OT_RebuildPhotoStep,
           LIVINGLACQUER_OT_RebuildFavorite, LIVINGLACQUER_OT_RebuildBrush, LIVINGLACQUER_OT_RebuildMaskBrush,
           LIVINGLACQUER_OT_RebuildClearMask,
           LIVINGLACQUER_OT_RebuildFlood, LIVINGLACQUER_OT_RebuildSavePainted, LIVINGLACQUER_OT_RebuildResetPainted,
           LIVINGLACQUER_OT_RebuildSolo, LIVINGLACQUER_OT_RebuildAlbedo, LIVINGLACQUER_OT_RebuildHighpass, LIVINGLACQUER_OT_RebuildSend,
           LIVINGLACQUER_OT_RebuildLockExport)


def register():
    paint.register()
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    paint.unregister()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
