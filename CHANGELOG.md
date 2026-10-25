# Changelog

## 0.2.6 (2026-10-25)

- Step 6 is one row: **Build** + three icons: Size refs, Auto Level & Center, Work on the Transform. The Scale button is gone (press S; the first Build still starts scaling by itself).
- **Work on the Transform** (the pivot icon, switched on by Build): besides the pivot at the world origin it selects the Transform empty and makes it active, shows the TRANSFORM collection and hides the cameras. Switching it off hides TRANSFORM again and gives back the cameras' visibility, your pivot, cursor, selection and active object.
- Checked headless: Build -> on; off restores; a user state (Individual Origins, Cube + Light selected, cameras hidden) survives on -> off unchanged.

## 0.2.5 (2026-10-25)

- **Pivot at World Origin is switched on by Build**, so scaling / rotating right after a Build happens about the center of the world (switch it off to get your own pivot back).
- **Size references:** next to the 1.7 m person there is now a table (0.75 m high, 1.2 x 0.7 m top) and a 0.30 m cat, all on the floor and labelled; the toggle next to Build is now "Size refs".
- Checked live in Blender 5.2.2: all three draw with their labels.

## 0.2.4 (2026-10-25)

- The 1.7 m person always stands on the floor (Z = 0), beside the scan.
- **Pivot at World Origin** toggle (next to Scale): Pivot Point = 3D Cursor with the cursor held at (0, 0, 0) while it is on; off gives back your own pivot and cursor.
- **Build frames the scan:** every 3D Viewport is centered on the scan mesh after Build (also on files built before 0.2.2).
- Checked live in Blender 5.2.2: toggle on / off restores Median Point and the cursor, framing centers the Teapot, the person stands at Z = 0.

## 0.2.3 (2026-10-25)

- **Auto Level & Center:** on the first Build the scan is stood upright and centered on the world origin by itself. Up comes from the circle of cameras (the normal of the plane they lie on), the center from the mesh's vertices; nothing is copied from a previous object. Only the `Transform` empty moves; a Transform the user has changed is left alone on later Builds. Button to redo it.
- **Scale mode:** right after that first Build, Blender is in interactive scaling of `Transform` about the world origin; the **Scale** button starts it again any time.
- **1.7 m person:** GPU overlay beside the scan (toggle "1.7 m" next to Build) to judge the size while scaling.
- `Transform` now lives alone in its own `TRANSFORM` collection.
- Checked headless (levelling 31 deg vs the user's 30.7 deg by hand, mesh centered within 0.02, user scale kept on re-Build, button) and live (the person overlay draws in Blender 5.2.2). Not checked: the automatic scale mode right after Build in the UI.

## 0.2.2 (2026-10-25)

- **Build Scene, ready for MultiCamProject:** the scan mesh goes to the `OBJECTS` collection and the cameras to `CAMERAS` (cameras only), the names MultiCamProject picks up by itself. Both hang under one empty, `Transform` (scene root collection): move / rotate / scale it to place the whole scan; Build keeps it and re-places everything under it on re-runs. Only scan cameras (with `metashape_res`) are ever removed from `CAMERAS`. Old `Geometry_<Object>` / `Cameras_<Object>` collections are cleaned up when empty.
- Checked headless on the scratch Teapot: collections, parenting (mesh + 52 cameras), and a Transform moved / rotated / scaled between two Builds (everything follows, no duplicates).

## 0.2.1 (2026-10-25)

- **Progress bar for every wait.** Check Links, Fix, Build Scene (+ Undistort), Undistort, Package and the engines' publishing now run as background jobs: a progress bar with the current item and Cancel at the top of the Scan Pipeline panel, and the same line in Blender's status bar (visible with the sidebar closed). Python steps run in 0.1 s slices (generators that yield their progress), so Blender redraws between them; the one call that cannot be split (the model import) is announced first.
- Engine jobs publish (step 8) as their last job steps; Convert & Sort's moves and the engines' photo copies report per file.
- Fix uses the last Check's result, so its dialog opens at once.
- Checked: headless tests re-run (Build, Fix, Convert, Hybrid, panel draw) and a live Check Links in Blender 5.2.2 through the timer.

## 0.2.0 (2026-10-25)

Scan pipeline steps 2-8 (plan phases 2-6). Details per step in docs/HANDOFF.md §6.

- **Step 2 Receive** (ingest): local-network server with a random token and QR code; Safari upload page and iOS Shortcut POST; photos land in `zz.Originals`; Convert & Sort starts once uploads stop. Eye button: watch the photo folders instead (USB / Drive).
- **Step 3 Convert & Sort** (ingest): JPG wins, HEIC / RAW / PNG without a JPG are converted in a background process (EXIF + ICC kept, rotation baked); originals, IMG_E edits, videos and Drive duplicates move to `zz.Originals`. "Install converters" pip-installs pillow / pillow-heif (rawpy, segno on demand) into Blender's user scripts.
- **Step 4 Reconstruct** (engines): Agisoft = open Metashape + guide with copy buttons + export watcher; Hybrid = Agisoft cameras -> OpenMVS by itself; Open Source = COLMAP (one camera per lens, levelled) + OpenMVS, no clicks. Heavy files stay in a local work folder; results are published automatically. Fast / Normal / High presets.
- **Step 6 Build Scene** (scene): model import with automatic axis fix (tries X rotations, keeps the one where the mesh projects into the photos), textures by naming rule (pages, normal, AO), cameras from the XML into `Cameras_<Object>`, Alembic cameras removed, everything updated in place.
- **Step 7 Undistort & BG** (scene): only missing or stale photos (calibration fingerprint per lens), modal with Esc, runs after Build.
- **Step 8 Package** (scene): publishes the newest engine result with the standard names; files of another engine are moved to `zz.Replaced\<date>` instead of being deleted; marker + relative paths.
- **Background jobs** (project): one at a time, progress bar + Cancel in the panel, Show Log. **Local cache** in ⚙: Pull to Local / Push to Drive with check-out in livinglacquer.json. ⚙ also holds the tool paths, work folder, photo format and engine quality.
- Check Links knows COLMAP's pinhole cameras (checks the undistorted photos against them).
- Tested headless in Blender 5.2.2 on scratch copies: Build on the Teapot ABC (axis -90, 86 % alignment, 8 photos undistorted incl. ultra-wide, re-run idempotent); Convert & Sort (HEIC, PNG, duplicates, edits, video, received JPG; re-run idempotent); receiver (page, upload, bad token 403, non-photo 415); Open Source on 20 photos (82 s Fast, 20 cameras, 100 % alignment); Hybrid on 8 photos (26 s, 99 %, Agisoft files set aside); export watcher; Pull / Push; panel draw for all engines; unregister. Not tested: anything in the Blender UI (timers, modal, QR display, Metashape launch), an iPhone, a full 112-photo run.

## 0.1.0 (2026-10-25)

Scan pipeline, build phase 1 (docs/PLAN_scan_pipeline.md §9).

- **Scan Pipeline** panel: engine switch (Agisoft / Hybrid / Open Source, stored in livinglacquer.json), ⚙ advanced box (objects folder, marker paths), steps 1-8; steps not built yet show greyed out.
- **project** module, step 1: **New Object** picks the next free NN in the objects folder, creates `NN.<Object>\zz.Scan\...` (§2), writes `livinglacquer.json` and saves the current file as `NN.<Object>.blend` (relative paths). Names are made ASCII (`Bát Tràng teapot` → `Bat_Trang_teapot`). **Open Object** opens the .blend of an object folder; refuses when the current file has unsaved changes unless Discard is ticked. The objects folder is remembered in the add-on preferences.
- **linker** module, step 5: **Check** reports the marker / Drive folder, old folder names, missing scan folders, conflict copies, Agisoft lock, long / non-ASCII paths, photos (formats, duplicate names, iPhone extras), camera XML (chunks, components, unaligned cameras, loose name matches, cameras without photo, photos not in the XML, lenses, photo size per sensor, rotated photos, undistorted coverage and size), model and textures, and every file path in the .blend (missing, external, absolute). **Fix…** (with a confirm list) renames old folders, creates missing ones, relinks missing files found in the object folder (camera photos prefer 01.CAM_Photos, lost textures map to `OBJ_<Object>.jpg`), copies external files in, makes paths relative and writes the marker.
- **metashape**: the odd-size skip is now per sensor (photo vs its own sensor, same aspect accepted), so mixed-lens shoots keep every camera (Teapot: 52 instead of 40). An XML in `01.CAM_Photos` takes its photos from `zz.Source_Photos` and undistorts next to the XML.
- Checked headless in Blender 5.2.2: Check on both samples (Teapot 1 relink, Wajima 107 relinks, all resolve relative, in memory only); Teapot import gives 52 cameras (40 main + 12 ultra-wide); New Object + Fix on a scratch folder (renames `zz.scan` / `01.Agisoft`, pulls an external file, makes an absolute path relative, writes the marker); panel draw code dry-run.

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
