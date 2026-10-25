"""The "How to work in Agisoft" guide in its own small Blender window (a Text Editor), so it can sit next
to Metashape while the user clicks through it. Context aware: it reads Metashape's own project files
(agisoft.project_state) and the exports, and lists only the steps still to do (Change Path first when the
photos are not where Metashape looks), or what to do next in Blender when Agisoft has nothing left;
rewritten every 3 s while the window is open. The sidebar holds only "Agisoft Paths" (copy buttons for the
steps left; Blender's Find / Properties panels are hidden there), "Show all steps" and "Show paths"."""
import os

import bpy

from ..project import state
from . import agisoft

TEXT = "LivingLacquer Agisoft Guide"
LABELS = {"source": "Photo folder", "psx": "Project .psx", "xml": "Cameras .xml", "model": "Model .abc",
          "texture": "Texture .jpg"}
_patched = []           # Blender's text editor panels that hide themselves in the guide window


_cache = {"lines": [], "key": None}     # the guide lines as last written, for the sidebar (no disk in draw)


def _next_in_blender():
    """'3. Reconstruct' style name of the step to do next in Blender (from the cached step list)."""
    from ..project import steps
    n = steps.current()
    return f"{n}. {steps.NAMES[n]}" if n else ""


def guide_text(root, engine, show_paths=False, show_all=False):
    """The guide for this object right now: only the lines still to do (unless show_all), the project's
    state on top, and what to do next in Blender when Agisoft has nothing left."""
    t = agisoft.targets(root)
    lines_, p = agisoft.guide_status(root, engine)
    _cache["lines"] = lines_
    title = "AGISOFT" if engine == "AGISOFT" else "HYBRID (Agisoft aligns, OpenMVS builds)"
    out = [f"HOW TO WORK IN AGISOFT - {title}", "", f"Object: {os.path.basename(root)}"]
    if p["psx"]:
        out.append(f"Project: {p['photos']} photos, {p['aligned']} aligned, "
                   f"{'model built' if p['model'] else 'no model yet'}" + ("  (open in Metashape)" if p["open"] else ""))
    else:
        out.append("Project: not saved yet")
    if p["missing"]:
        where = os.path.relpath(p["looks_in"], root) if p["looks_in"].startswith(root) else p["looks_in"]
        out.append(f"! {p['missing']} photo(s) not found: Metashape looks in {where}")
    out.append("")
    todo = [l for l in lines_ if not l[3] or (show_all and l[2] != "path")]
    if not any(not l[3] for l in lines_):
        out += ["Nothing left to do in Agisoft: photos, alignment, model and all exports are there.", ""]
        nxt = _next_in_blender()
        if nxt:
            out.append(f"Next, in Blender: {nxt}")
        if not show_all:
            return "\n".join(out)
        out.append("")
    else:
        hidden = len({l[2] for l in lines_ if l[3] and l[2] != "path"})      # steps, not lines
        out.append("Still to do (each path has a copy button on the right; click it, then Ctrl+V in Metashape):")
        out.append("")
    for text, key, what, done in todo:
        mark = "[done] " if done else ""
        out.append(mark + text + (f"   [copy: {LABELS[key]}]" if key and not show_paths and not done else ""))
        if key and show_paths and not done:
            out.append(f"      {t[key]}")
    if not show_all and any(not l[3] for l in lines_):
        if hidden:
            out += ["", f"({hidden} step(s) already done are hidden: 'Show all steps' in the sidebar)"]
        out += ["", "Blender ticks the exports in step 3 as they appear.",
                "Close Metashape before pressing Check Links (an open project locks its folder)."]
    return "\n".join(out)


def write_text(context):
    root = state.get()["root"]
    txt = bpy.data.texts.get(TEXT) or bpy.data.texts.new(TEXT)
    props = context.scene.livinglacquer_props
    engine = props.pipe_engine if props.pipe_engine in agisoft.GUIDE else "AGISOFT"
    body = guide_text(root, engine, props.pipe_guide_paths, props.pipe_guide_all)
    if txt.as_string() != body:
        txt.clear()
        txt.write(body)
    txt.use_fake_user = False
    return txt


def _guide_open():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "TEXT_EDITOR" and area.spaces.active.text and area.spaces.active.text.name == TEXT:
                return area
    return None


def _tick():
    """While the guide window is open: rewrite it when Metashape's project or the exports change."""
    area = _guide_open()
    if area is None or not state.get()["root"]:
        return None
    try:
        write_text(bpy.context)
        area.tag_redraw()
    except Exception as e:
        print("LivingLacquer guide:", e)
    return 3.0


def open_window(context):
    """Open (or refresh) the guide window; returns False when Blender gave no new window."""
    txt = write_text(context)
    wm = context.window_manager
    for win in wm.windows:                            # already open: just refresh the text
        for area in win.screen.areas:
            if area.type == "TEXT_EDITOR" and area.spaces.active.text == txt:
                area.tag_redraw()
                if not bpy.app.timers.is_registered(_tick):
                    bpy.app.timers.register(_tick, first_interval=3.0)
                return True
    before = set(wm.windows[:])
    bpy.ops.screen.userpref_show("INVOKE_DEFAULT")    # Blender's small temporary window...
    new = [w for w in wm.windows if w not in before]
    if not new:
        return False
    area = new[0].screen.areas[0]
    area.ui_type = "TEXT_EDITOR"                      # ...turned into a text editor with the guide
    space = area.spaces.active
    space.text = txt
    space.show_word_wrap = True
    space.show_line_numbers = False
    space.show_syntax_highlight = False
    space.font_size = 13
    space.show_region_ui = True
    space.top = 0
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=3.0)
    return True


class LIVINGLACQUER_OT_PipeAgisoftWindow(bpy.types.Operator):
    """Open the step-by-step Agisoft guide in its own window, to keep next to Metashape"""
    bl_idname = "livinglacquer.pipe_agisoft_window"
    bl_label = "How to work in Agisoft"

    @classmethod
    def poll(cls, context):
        return bool(state.get()["root"]) and context.scene.livinglacquer_props.pipe_engine in ("AGISOFT", "HYBRID")

    def execute(self, context):
        if not open_window(context):
            self.report({"WARNING"}, f"Could not open a window: see the text block '{TEXT}' in a Text Editor")
        return {"FINISHED"}


class LIVINGLACQUER_PT_AgisoftGuide(bpy.types.Panel):
    bl_label = "Agisoft Paths"
    bl_idname = "LIVINGLACQUER_PT_agisoft_guide"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Text"              # the tab a new text editor shows first
    bl_order = 0

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and sd.text is not None and sd.text.name == TEXT

    def draw(self, context):
        root = state.get()["root"]
        if not root:
            self.layout.label(text="Open the object's .blend first")
            return
        props = context.scene.livinglacquer_props
        col = self.layout.column(align=True)
        from .operators import STATUS
        todo = [(text, key) for text, key, what, done in _cache["lines"] if key and not done]
        if not todo:
            col.label(text="Nothing left to copy", icon="CHECKMARK")
        for text, key in todo:
            row = col.row(align=True)
            row.scale_y = 1.4
            number = text.split(".")[0]                 # the guide step it belongs to
            row.operator("livinglacquer.pipe_copy_path", text=f"{number}. {LABELS[key]}", icon="COPYDOWN",
                         depress=STATUS["copied"] == key).key = key
        col.separator()
        col.prop(props, "pipe_guide_all", text="Show all steps", toggle=True,
                 icon="HIDE_OFF" if props.pipe_guide_all else "HIDE_ON")
        col.prop(props, "pipe_guide_paths", text="Show paths", toggle=True,
                 icon="HIDE_OFF" if props.pipe_guide_paths else "HIDE_ON")


def _hide_in_guide(cls):
    """Give one of Blender's text editor sidebar panels a poll that hides it in the guide window only."""
    def poll(c, context):
        sd = context.space_data
        return not (sd is not None and sd.text is not None and sd.text.name == TEXT)
    bpy.utils.unregister_class(cls)
    cls.poll = classmethod(poll)
    bpy.utils.register_class(cls)
    _patched.append(cls)


classes = (LIVINGLACQUER_OT_PipeAgisoftWindow, LIVINGLACQUER_PT_AgisoftGuide)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    for name in ("TEXT_PT_find", "TEXT_PT_properties"):
        cls = getattr(bpy.types, name, None)
        if cls is not None and "poll" not in cls.__dict__:
            _hide_in_guide(cls)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    while _patched:                                   # Blender's panels back as they were
        cls = _patched.pop()
        bpy.utils.unregister_class(cls)
        del cls.poll
        bpy.utils.register_class(cls)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
