import bpy
import os
import json

from . import sidebar_tab


def _build_label():
    """Return 'dd/mm/yy HH:MM' from build_info.json, or 'Build' if not built yet."""
    build_file = os.path.join(os.path.dirname(__file__), "build_info.json")
    if os.path.exists(build_file):
        try:
            with open(build_file, "r") as f:
                data = json.load(f)
            t = data.get("time", "")
            if len(t) >= 16:
                yyyy, mm, dd = t[0:4], t[5:7], t[8:10]
                hhmm = t[11:16]
                return "{}/{}/{} {}".format(dd, mm, yyyy[2:], hhmm)
        except Exception:
            pass
    return "Build"


class LIVINGLACQUER_PT_Infos(bpy.types.Panel):
    """Infos panel - build time, debug, console"""
    bl_label = ""               # drawn by draw_header: "Infos" + the add-on name, greyed
    bl_idname = "LIVINGLACQUER_PT_infos"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LivingLacquer"
    bl_order = 0
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        sidebar_tab.draw_header(self.layout, "Infos")

    def draw(self, context):
        layout = self.layout
        props = context.scene.livinglacquer_props

        # Single row: Build info popup + Reload + Debug toggle + Console + Clear
        row = layout.row(align=True)
        row.operator("livinglacquer.build", text=_build_label(), icon='RESTRICT_VIEW_ON')
        row.operator("livinglacquer.reload", text="", icon='FILE_REFRESH')
        sub = row.row(align=True)
        sub.active_default = props.debug_mode
        sub.operator("livinglacquer.toggle_debug", text="", icon='INFO')
        row.operator("livinglacquer.toggle_console", text="", icon='CONSOLE')
        row.operator("livinglacquer.clear_console", text="", icon='TRASH')

        if props.debug_mode:
            sidebar_tab.draw(layout)          # Tab name + up / down

            # Modules row — hidden unless debug mode is on
            from . import module_manager
            row = layout.row(align=True)
            row.label(text="Modules:", text_ctxt="extra-info-label")
            for m in module_manager.ALL_MODULES:
                sub = row.row(align=True)
                sub.active_default = module_manager.is_loaded(m["name"])
                sub.operator(m["op"], text=m["name"].capitalize(), icon=m["icon"])
            
            layout.label(text="Version: " + props.addon_version,
                         text_ctxt="extra-info-label")


class LIVINGLACQUER_PT_MainPanel(bpy.types.Panel):
    """Main panel - modules register subpanels here via bl_parent_id"""
    bl_label = "LivingLacquer"
    bl_idname = "LIVINGLACQUER_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LivingLacquer"
    bl_order = 1

    def draw(self, context):
        pass


def register():
    for c in (LIVINGLACQUER_PT_Infos, LIVINGLACQUER_PT_MainPanel):
        sidebar_tab.register_panel(c)     # in the tab the user named


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_PT_MainPanel)
    bpy.utils.unregister_class(LIVINGLACQUER_PT_Infos)
