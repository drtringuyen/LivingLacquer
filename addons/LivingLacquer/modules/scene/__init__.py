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
from . import human, operators


def register():
    operators.register()
    human.register()


def unregister():
    human.unregister()
    operators.unregister()
