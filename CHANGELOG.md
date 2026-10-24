# Changelog

## 0.0.1 (2026-10-24)

- Scaffold from blender-addon-init: Infos panel (Build / Reload / Debug / Console / Clear), main panel, global properties, `assets.py`, module system.
- install.py, update.py / .bat and auto_deploy.py / .bat taken over from MeshBuildTimelapse (git commit in build_info.json, Blender 5.2).
- **metashape** module, ported from the standalone Metashape Camera Importer 0.1.0:
  - File > Import > Agisoft Metashape Cameras (.xml) and an Import button in the sidebar.
  - Brown-model undistortion into `<photo folder>_undistorted`, modal with progress bar and Esc.
  - Look Through Camera, step previous / next, background Opacity / Depth for all cameras.
  - Operators renamed to `livinglacquer.metashape_*`; the scene properties moved into `livinglacquer_props` (`metashape_collection`, `metashape_bg_alpha`, `metashape_bg_depth`). Importing sets the sidebar's collection to the one just filled.
