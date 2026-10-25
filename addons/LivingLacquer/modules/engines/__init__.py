"""Engines: step 4 of the scan pipeline, for the engine picked at the top of the panel.

Agisoft: Open Metashape opens the project with the photo folder on the clipboard; the guide lists
  each click with copy buttons for the export paths; Blender watches for the exports.
Hybrid: same, but only aligning + Export Cameras in Agisoft; Blender then runs OpenMVS
  (InterfaceMetashape, Densify, Mesh, Refine, Texture) by itself.
Open Source: COLMAP (one camera per lens) + OpenMVS, no clicks.
OpenMVS / COLMAP work in a local folder (⚙ Local Work Folder); the result is copied into
zz.COLMAP_OMVS and published into 01.CAM_Photos / 02.Geometry when the job ends.
"""
from . import guide, operators


def register():
    operators.register()
    guide.register()


def unregister():
    guide.unregister()
    operators.unregister()
