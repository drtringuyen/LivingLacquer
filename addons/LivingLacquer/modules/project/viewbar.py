"""The collections' on / off (found by name), as in MultiCamProject, for the photo panel's View section."""
import bpy

# (collection, icon) in the order of the row
COLLECTIONS = (("Original Mesh", "MESH_ICOSPHERE"), ("OBJECTS", "MESH_CUBE"), ("EXPORT", "EXPORT"),
               ("CAMERAS", "OUTLINER_OB_CAMERA"))


def _layers(view_layer):
    out, stack = [], list(view_layer.layer_collection.children)
    while stack:
        lc = stack.pop()
        out.append(lc)
        stack.extend(lc.children)
    return out


def _layer(view_layer, name):
    return next((lc for lc in _layers(view_layer) if lc.collection.name.lower() == name.lower()), None)


def _shown(lc):
    return not lc.exclude and not lc.hide_viewport


class LIVINGLACQUER_OT_ToggleCollection(bpy.types.Operator):
    """Show / hide this collection (showing also includes an excluded one)"""
    bl_idname = "livinglacquer.toggle_collection"
    bl_label = "Show / Hide Collection"
    bl_options = {"REGISTER", "UNDO"}
    name: bpy.props.StringProperty(options={"SKIP_SAVE"})

    @classmethod
    def description(cls, context, props):
        return f"Show / hide {props.name}"

    def execute(self, context):
        lc = _layer(context.view_layer, self.name)
        if lc is None:
            self.report({"WARNING"}, f"No {self.name} collection")
            return {"CANCELLED"}
        show = not _shown(lc)
        lc.exclude = not show
        lc.hide_viewport = not show
        return {"FINISHED"}


def register():
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleCollection)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleCollection)
