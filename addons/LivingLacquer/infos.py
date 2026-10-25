"""Info panel operators: Build popup, Reload, Debug toggle, Console toggle, Clear console."""
import bpy
import os
import json


def _read_build_info():
    build_file = os.path.join(os.path.dirname(__file__), "build_info.json")
    if os.path.exists(build_file):
        try:
            with open(build_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


class LIVINGLACQUER_OT_Build(bpy.types.Operator):
    """Show addon info and last build time"""
    bl_idname = "livinglacquer.build"
    bl_label = "Build"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        layout = self.layout
        layout.label(text="LivingLacquer", icon='ARMATURE_DATA')
        layout.separator()
        layout.label(text="Modeling and texturing assistant for scanned lacquerware: photogrammetry cameras, projection and cleanup tools")
        layout.separator()
        layout.label(text="Version: 0.0.1")
        layout.label(text="Author: ")
        layout.separator()
        build = _read_build_info()
        if build:
            layout.label(text="Last built: " + build.get("time", "Unknown"), icon='TIME')
        else:
            layout.label(text="Not built yet - run install.py first", icon='ERROR')

    def execute(self, context):
        return {'FINISHED'}


class LIVINGLACQUER_OT_Reload(bpy.types.Operator):
    """Reload addon in Blender (disable -> purge modules -> enable).
    Use when you want to apply in-place changes without running install.py."""
    bl_idname = "livinglacquer.reload"
    bl_label = "Reload Addon"

    def execute(self, context):
        import sys
        addon = "LivingLacquer"
        bpy.ops.preferences.addon_disable(module=addon)
        mods = [k for k in sys.modules if k == addon or k.startswith(addon + ".")]
        for m in mods:
            del sys.modules[m]
        bpy.ops.preferences.addon_enable(module=addon)
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleDebug(bpy.types.Operator):
    """Toggle debug mode - show/hide extra-info-label"""
    bl_idname = "livinglacquer.toggle_debug"
    bl_label = "Debug"

    def execute(self, context):
        props = context.scene.livinglacquer_props
        props.debug_mode = not props.debug_mode
        self.report({'INFO'}, "Debug: " + ("ON" if props.debug_mode else "OFF"))
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleConsole(bpy.types.Operator):
    """Toggle Blender system console"""
    bl_idname = "livinglacquer.toggle_console"
    bl_label = "Console"

    def execute(self, context):
        import sys
        if sys.platform == "win32":
            try:
                bpy.ops.wm.console_toggle()
            except AttributeError:
                import subprocess
                subprocess.Popen(
                    'start cmd',
                    shell=True,
                    creationflags=subprocess.DETACHED_PROCESS
                )
        else:
            self.report({'INFO'}, "Use Window > Toggle System Console")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ClearConsole(bpy.types.Operator):
    """Clear the system console output"""
    bl_idname = "livinglacquer.clear_console"
    bl_label = "Clear"

    def execute(self, context):
        import sys
        os.system("cls" if sys.platform == "win32" else "clear")
        return {'FINISHED'}



class LIVINGLACQUER_OT_ToggleMetashape(bpy.types.Operator):
    """Toggle Metashape module on/off"""
    bl_idname = "livinglacquer.toggle_metashape"
    bl_label = "Metashape"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("metashape")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleProject(bpy.types.Operator):
    """Toggle Project module (Scan Pipeline panel, step 1) on/off"""
    bl_idname = "livinglacquer.toggle_project"
    bl_label = "Project"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("project")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleLinker(bpy.types.Operator):
    """Toggle Linker module (step 5, Check Links) on/off"""
    bl_idname = "livinglacquer.toggle_linker"
    bl_label = "Linker"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("linker")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleScene(bpy.types.Operator):
    """Toggle Scene module (steps 6-8: Build Scene, Undistort, Package) on/off"""
    bl_idname = "livinglacquer.toggle_scene"
    bl_label = "Scene"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("scene")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleIngest(bpy.types.Operator):
    """Toggle Ingest module (steps 2-3: iPhone receiver, Convert & Sort) on/off"""
    bl_idname = "livinglacquer.toggle_ingest"
    bl_label = "Ingest"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("ingest")
        return {'FINISHED'}


class LIVINGLACQUER_OT_ToggleEngines(bpy.types.Operator):
    """Toggle Engines module (step 4: Agisoft / Hybrid / Open Source) on/off"""
    bl_idname = "livinglacquer.toggle_engines"
    bl_label = "Engines"

    def execute(self, context):
        from . import module_manager
        module_manager.toggle("engines")
        return {'FINISHED'}

def register():
    bpy.utils.register_class(LIVINGLACQUER_OT_Build)
    bpy.utils.register_class(LIVINGLACQUER_OT_Reload)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleDebug)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleConsole)
    bpy.utils.register_class(LIVINGLACQUER_OT_ClearConsole)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleMetashape)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleProject)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleLinker)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleScene)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleIngest)
    bpy.utils.register_class(LIVINGLACQUER_OT_ToggleEngines)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleEngines)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleIngest)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleScene)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleLinker)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleProject)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleMetashape)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ClearConsole)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleConsole)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_ToggleDebug)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_Reload)
    bpy.utils.unregister_class(LIVINGLACQUER_OT_Build)
