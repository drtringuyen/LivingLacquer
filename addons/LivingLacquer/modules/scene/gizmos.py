"""Step 6's icon buttons also in the 3D Viewport, in the column under Blender's own navigation buttons
(zoom, pan, camera, ortho): Size refs, Auto Level & Center, Work on the Transform. Toggles light up while
on. Shown only with gizmos + navigation gizmos on, and only when the file is an object folder."""
import bpy
from mathutils import Vector

from ..project import state
from . import icons

# Blender's navigation buttons (view3d_gizmo_navigate.cc), measured in Blender 5.2: button size = nav size
# * 0.35, one slot = nav size * 0.371, column x = visible right edge - 0.75 slot, first button
# 0.52 * 1.25 * 2.1 nav sizes under the visible top. Ours continue the column after its 4 buttons.
MINI_FAC = 0.35
SLOT_FAC = 0.371
TOP_FAC = 0.52 * 1.25 * 2.1
NAV_SLOTS = 4           # zoom, pan, camera, ortho
OFF = (0.0, 0.0, 0.0)
ON = (0.25, 0.5, 1.0)

BUTTONS = [      # (icon, None = the standing person button; toggle property or None; operator; its properties)
    ("ORIENTATION_GLOBAL", None, "livinglacquer.pipe_auto_level", {}),
    (None, "pipe_show_human", "wm.context_toggle",
     {"data_path": "scene.livinglacquer_props.pipe_show_human"}),
    ("PIVOT_CURSOR", "pipe_pivot_origin", "wm.context_toggle",
     {"data_path": "scene.livinglacquer_props.pipe_pivot_origin"}),
]


def _visible(context):
    """(right edge, top) of the part of the viewport not covered by an overlapping sidebar / headers."""
    region, area = context.region, context.area
    xmax, ymax = region.width, region.height
    if context.preferences.system.use_region_overlap:
        for r in area.regions:
            if r.width <= 1 or r.height <= 1:
                continue
            if r.type == "UI" and r.x + r.width >= area.x + area.width - 1:
                xmax -= r.width
            elif r.type in ("HEADER", "TOOL_HEADER") and r.y > area.y + area.height / 2:
                ymax -= r.height
    return xmax, ymax


def _circle(n=32):
    from math import cos, pi, sin
    tris = []
    for i in range(n):
        a, b = 2 * pi * i / n, 2 * pi * (i + 1) / n
        tris += [(0.0, 0.0), (cos(a), sin(a)), (cos(b), sin(b))]
    return tris


class LIVINGLACQUER_GT_PersonButton(bpy.types.Gizmo):
    """A round button like Blender's GIZMO_GT_button_2d, showing a standing person (no Blender icon is
    one). Drawn with the documented Python gizmo API: backdrop circle + the person silhouette."""
    bl_idname = "LIVINGLACQUER_GT_person_button"
    __slots__ = ("backdrop", "person")

    def setup(self):
        self.backdrop = self.new_custom_shape("TRIS", _circle())
        self.person = self.new_custom_shape("TRIS", [((x - 0.5) * 1.5, (y - 0.5) * 1.5)
                                                       for x, y in icons.person_tris01()])

    def draw(self, context):
        self.draw_custom_shape(self.backdrop)
        keep = (tuple(self.color), self.alpha, tuple(self.color_highlight), self.alpha_highlight)
        self.color = self.color_highlight = (0.9, 0.9, 0.9)
        self.alpha = self.alpha_highlight = 1.0
        self.draw_custom_shape(self.person)
        self.color, self.alpha, self.color_highlight, self.alpha_highlight = keep

    def test_select(self, context, location):
        mw = self.matrix_world
        r = (mw.col[0].xyz).length
        return 0 if (mw.translation.xy - Vector(location)).length <= r else -1


class LIVINGLACQUER_GGT_Pipeline(bpy.types.GizmoGroup):
    bl_idname = "LIVINGLACQUER_GGT_pipeline"
    bl_label = "LivingLacquer Scan"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SCALE"}

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return (sd is not None and sd.show_gizmo and sd.show_gizmo_navigate
                and hasattr(context.scene, "livinglacquer_props") and bool(state.get()["root"]))

    def setup(self, context):
        size = context.preferences.view.gizmo_size_navigate_v3d * MINI_FAC
        self.buttons = []
        for icon, prop, op, op_props in BUTTONS:
            if icon:
                gz = self.gizmos.new("GIZMO_GT_button_2d")
                gz.icon = icon
                gz.draw_options = {"BACKDROP", "OUTLINE"}
            else:
                gz = self.gizmos.new(LIVINGLACQUER_GT_PersonButton.bl_idname)
            gz.color = OFF
            gz.alpha = 0.0
            gz.color_highlight = (0.8, 0.8, 0.8)
            gz.alpha_highlight = 0.2
            gz.scale_basis = size / 2                   # same as Blender's own buttons
            gz.use_draw_modal = False
            props = gz.target_set_operator(op)
            for k, v in op_props.items():
                setattr(props, k, v)
            self.buttons.append((gz, prop))

    def draw_prepare(self, context):
        ui = context.preferences.system.ui_scale
        nav = context.preferences.view.gizmo_size_navigate_v3d
        step = nav * SLOT_FAC * ui
        xmax, ymax = _visible(context)
        x = xmax - step * 0.75
        top = ymax - nav * TOP_FAC * ui                 # Blender's first button (zoom), under the axis gizmo
        props = context.scene.livinglacquer_props
        for i, (gz, prop) in enumerate(self.buttons):
            gz.matrix_basis[0][3] = round(x)
            gz.matrix_basis[1][3] = round(top - step * (NAV_SLOTS + i))
            on = bool(prop and getattr(props, prop))
            gz.color = ON if on else OFF
            gz.alpha = 0.6 if on else 0.0


def register():
    bpy.utils.register_class(LIVINGLACQUER_GT_PersonButton)
    bpy.utils.register_class(LIVINGLACQUER_GGT_Pipeline)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_GGT_Pipeline)
    bpy.utils.unregister_class(LIVINGLACQUER_GT_PersonButton)
