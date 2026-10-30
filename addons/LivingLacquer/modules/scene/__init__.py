"""Scene: steps 6-8 of the scan pipeline.

6 Build Scene imports OBJ_<Object>.abc / .fbx / .obj from 02.Geometry, turns it into the camera
  XML's coordinates (tries the X rotations and keeps the one where the mesh projects into the
  photos), assigns OBJ_<Object>*.jpg as material(s), builds the cameras from CAM_<Object>.xml
  into Cameras_<Object> and removes cameras that came with the model file. Re-running replaces
  OBJ_<Object> and updates the cameras by name.
7 Undistort & Backgrounds writes the missing / stale undistorted photos into 01.CAM_Photos
  (original names) and sets them as camera backgrounds. Runs by itself after Build.
8 Package copies the newest engine result (engine_result.json) into 01.CAM_Photos / 02.Geometry
  with the standard names, updates livinglacquer.json and makes the .blend paths relative.
"""
import bpy
from bpy.app.handlers import persistent

from . import build, gizmos, human, icons, operators, view


@persistent
def _on_load(*_args):
    build.migrate_scan()


def register():
    icons.register()
    operators.register()
    human.register()
    view.register()
    gizmos.register()
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(build.migrate_scan, first_interval=0.2)     # the file open while installing


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(build.migrate_scan):
        bpy.app.timers.unregister(build.migrate_scan)
    gizmos.unregister()
    view.unregister()
    human.unregister()
    operators.unregister()
    icons.unregister()
