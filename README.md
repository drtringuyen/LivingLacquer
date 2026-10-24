# LivingLacquer

A Blender add-on that gathers the tools for modeling and texturing scanned lacquerware: bring a photogrammetry scan in with its cameras and photos, then model, project and clean up on top of it. Each tool is a module that can be switched on and off.

**Status:** 0.0.1. Scaffold (blender-addon-init) plus the first module, **metashape**, ported from the standalone Metashape Camera Importer script. Smoke-tested in Blender 5.2.2 with a synthetic export; not yet tried on a real scan. See [docs/HANDOFF.md](docs/HANDOFF.md) for where things stand and what comes next.

## Layout

```
LivingLacquer/
├── addons/LivingLacquer/
│   ├── __init__.py, properties.py, panels.py, infos.py, assets.py   scaffold (blender-addon-init)
│   ├── module_manager.py, modules_config.json                       module system
│   └── modules/metashape/
│       ├── parse.py      Metashape XML -> sensors + camera matrices
│       ├── photos.py     find photos, undistort through the Brown model
│       ├── cameras.py    build Blender cameras, look through them
│       ├── operators.py  Import, Look Through, Step Camera, Apply Background settings
│       └── ui.py         Metashape sub-panel
├── docs/HANDOFF.md                resume point, design notes, roadmap
├── install.py                     copy to Blender + MCP reload
├── update.py / update.bat         pull, merge cloud branches, push, install
├── auto_deploy.py / .bat          watch GitHub main and reinstall
├── zip_addon.py / build_extension.py
└── manifest.toml
```

## Install

```
python install.py
```
Copies the add-on into Blender 5.2's add-ons folder and reloads it through the Blender MCP (port 9876). Enable **LivingLacquer** once in Preferences > Add-ons. Change `BLENDER_VERSION` in `install.py` for another Blender.

## Modules

Turn on **Debug** in the Infos panel to see the Modules row; click a module to switch it on or off (remembered in `modules_config.json`). Add new ones with `/blender-addon-modules add`.

### metashape

Imports Agisoft Metashape cameras, undistorts the photos and sets them as camera backgrounds.

1. In Metashape: File > Export > Export Cameras (Agisoft XML) and Export Model (OBJ).
2. In Blender: import the OBJ with Forward = Y, Up = Z so it keeps Metashape's coordinates.
3. File > Import > **Agisoft Metashape Cameras (.xml)**, or Sidebar (N) > LivingLacquer > Metashape > **Import Metashape Cameras**. Pick the XML, check the photo folder, OK. Photos are undistorted into `<photo folder>_undistorted`; the originals are never touched. Esc stops a long run and keeps the cameras already built.
4. Use the arrows around **Look Through Camera** to step through the cameras. The render resolution follows each camera's photo.
5. **Background Photo**: set Opacity / Depth, then **Apply to All Cameras**.

## Publishing

```
python zip_addon.py         # LivingLacquer.zip (Preferences > Add-ons > Install)
python build_extension.py   # LivingLacquer-extension.zip (extensions.blender.org)
```
