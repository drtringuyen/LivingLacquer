"""Metashape: import Agisoft Metashape XML cameras, undistort the photos and set them as
camera backgrounds, then step through the cameras from the sidebar.

How to use
1. In Metashape: File > Export > Export Cameras (Agisoft XML) and Export Model (OBJ).
2. In Blender: import the OBJ with Forward = Y, Up = Z so it keeps Metashape's coordinates.
3. File > Import > Agisoft Metashape Cameras (.xml) (or the Import button in the sidebar),
   pick the XML, check the photo folder, OK. Photos are undistorted into
   "<photo folder>_undistorted" (originals are never touched). Esc stops a long run;
   cameras already built are kept.
4. Select a camera and press Look Through Camera so the render resolution matches its photo.
"""
from . import operators, ui


def register():
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
