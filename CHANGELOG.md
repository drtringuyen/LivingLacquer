# Changelog

## 0.0.2 (2026-10-24)

- **Sidebar tab**: drop-in `sidebar_tab.py` (same file as MeshBuildTimelapse / MultiCamProject). With Debug on, the Infos panel shows **Tab name** with reset and up / down; the Infos header shows "Infos (LivingLacquer)". Name and order live in the shared `<Blender config>/sidebar_tabs.json`.
- Infos, main panel and the Metashape sub-panel register through `sidebar_tab.register_panel`, so a module turned back on lands in the named tab.
- Checked in Blender 5.2.2: rename moves all panels and keeps the sidebar on the tab, up / down reorders, reset returns to "LivingLacquer", toggling Metashape off / on keeps the renamed tab, and the tab is shared with MeshBuildTimelapse and MultiCamProject (both named "LivingLacquer" in sidebar_tabs.json).

## 0.0.1 (2026-10-24)

- Scaffold from blender-addon-init: Infos panel (Build / Reload / Debug / Console / Clear), main panel, global properties, `assets.py`, module system.
- install.py, update.py / .bat and auto_deploy.py / .bat taken over from MeshBuildTimelapse (git commit in build_info.json, Blender 5.2).
- **metashape** module, ported from the standalone Metashape Camera Importer 0.1.0:
  - File > Import > Agisoft Metashape Cameras (.xml) and an Import button in the sidebar.
  - Brown-model undistortion into `<photo folder>_undistorted`, modal with progress bar and Esc.
  - Look Through Camera, step previous / next, background Opacity / Depth for all cameras.
  - Operators renamed to `livinglacquer.metashape_*`; the scene properties moved into `livinglacquer_props` (`metashape_collection`, `metashape_bg_alpha`, `metashape_bg_depth`). Importing sets the sidebar's collection to the one just filled.
