"""Per-machine settings (Edit > Preferences > Add-ons > LivingLacquer)."""
import bpy
from bpy.props import StringProperty

ADDON = __package__.split(".modules.")[0]


class LIVINGLACQUER_AP_Prefs(bpy.types.AddonPreferences):
    bl_idname = ADDON

    objects_root: StringProperty(
        name="Objects Folder", subtype="DIR_PATH",
        description="Folder holding the NN.<Object> folders (e.g. 00.3D); New Object remembers the last one")
    work_root: StringProperty(
        name="Local Work Folder", subtype="DIR_PATH",
        description="Fast local folder for the engines' big temporary files (depth maps...) and the local "
                    "cache; empty = %LOCALAPPDATA%\\LivingLacquer")
    colmap_dir: StringProperty(name="COLMAP", subtype="DIR_PATH",
                               default=r"C:\Photogrametry Tools\colmap-x64-windows-cuda",
                               description="COLMAP folder (holding bin\\colmap.exe)")
    openmvs_dir: StringProperty(name="OpenMVS", subtype="DIR_PATH",
                                default=r"C:\Photogrametry Tools\OpenMVS_Windows_x64_CUDA",
                                description="OpenMVS folder (holding DensifyPointCloud.exe ...)")
    metashape_exe: StringProperty(name="Metashape", subtype="FILE_PATH",
                                  default=r"C:\Program Files\Agisoft\Metashape\metashape.exe",
                                  description="Agisoft Metashape program")

    def draw(self, context):
        for p in ("objects_root", "work_root", "colmap_dir", "openmvs_dir", "metashape_exe"):
            self.layout.prop(self, p)


def get():
    addon = bpy.context.preferences.addons.get(ADDON)
    return addon.preferences if addon else None


def register():
    bpy.utils.register_class(LIVINGLACQUER_AP_Prefs)


def unregister():
    bpy.utils.unregister_class(LIVINGLACQUER_AP_Prefs)
