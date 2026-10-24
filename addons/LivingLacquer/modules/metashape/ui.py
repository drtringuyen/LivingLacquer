import bpy


class LIVINGLACQUER_PT_Metashape(bpy.types.Panel):
    bl_label = "Metashape"
    bl_idname = "LIVINGLACQUER_PT_metashape"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "LivingLacquer"
    bl_parent_id = "LIVINGLACQUER_PT_main"
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(icon='OUTLINER_OB_CAMERA')

    def draw(self, context):
        sc = context.scene
        props = sc.livinglacquer_props
        layout = self.layout
        layout.operator("livinglacquer.metashape_import", icon='IMPORT')
        layout.prop(props, "metashape_collection", text="Collection")

        row = layout.row(align=True)
        row.operator("livinglacquer.metashape_step_camera", text="", icon='TRIA_LEFT').direction = -1
        row.operator("livinglacquer.metashape_look_through", icon='VIEW_CAMERA')
        row.operator("livinglacquer.metashape_step_camera", text="", icon='TRIA_RIGHT').direction = 1
        if sc.camera:
            layout.label(text=f"Scene camera: {sc.camera.name}")

        box = layout.box()
        box.label(text="Background Photo")
        box.prop(props, "metashape_bg_alpha")
        box.row().prop(props, "metashape_bg_depth", expand=True)
        box.operator("livinglacquer.metashape_bg_settings")


def register():
    from ... import sidebar_tab
    sidebar_tab.register_panel(LIVINGLACQUER_PT_Metashape)     # in the tab the user named


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_PT_Metashape)
