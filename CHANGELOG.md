# Changelog

## 0.4.5 (2026-10-28)

- **Portrait cameras now line up with the mesh after MultiCamProject looks through them.** Build used to measure a portrait camera's lens and shift on the photo's height (Sensor Fit Vertical). MultiCamProject sets every camera it looks through to Sensor Fit Horizontal without converting, so the frame came out 1.33x too big and the photo did not sit on the mesh (BatTrang Teapot, IMG_3248).
- **Every camera is now Sensor Fit Horizontal, with lens and shift measured on the photo's width.** Portrait IMG_3248: 34.09 mm instead of 25.57 mm on Vertical. A landscape camera does not change.
- **Turn Camera Photos** keeps Horizontal and scales lens and shift to the new width on a 90° turn.
- **Older files are converted once on open** (cameras with the ll_width_fit key are left alone), also cameras MultiCamProject already switched to Horizontal.
- The odd lens shift warning still measures on the long side, so its 0.5 limit is unchanged.

## 0.4.4 (2026-10-26)

- **Why portrait iPhone photos came out sideways:** the iPhone stores the pixels landscape plus an EXIF Orientation tag ("turn 90° to show"). Convert & Sort kept JPGs as they were, and COLMAP, Metashape and Blender all ignore the tag, so the cameras were landscape and lay on their sides.
- **"Photos stand" (step 2):** As Shot (the EXIF tag) / Portrait / Landscape / Stored (as before), saved in livinglacquer.json. **Preview** shows every photo turned the way it will stand. Clicking a photo's name turns it 90° right, Shift+click 180° (upside down: the tag is unreliable when the phone points straight down), Ctrl+click 90° left, and the ⟳ button turns the whole set 180°.
- **Apply to Photos (step 2):** turns the photos in zz.Source_Photos and their masks (EXIF kept, tag set to 1, quality 95) and keeps the photos as they were in zz.Originals\zz.Before_Turn. Convert & Sort turns new photos too. Step 3 shows "reconstruct again".
- **Turn Camera Photos (step 4):** no new reconstruction. It turns only the camera photos in 01.CAM_Photos and rolls each camera with its photo (resolution and lens shift too). Build, Undistort and Package keep them turned, and choosing Stored turns them back. It names cameras that look upside down next to the others.
- **Auto Level stood sideways-stored sets upside down:** the cameras' up directions averaged out, so which way is up was a coin toss. It now goes by the cameras looking down at the object when their ups do not agree, and Turn Camera Photos levels again when the scene stands upside down.
- **Look Through / ◀ ▶ with CAMERAS unticked in the outliner:** the camera "is not in View Layer" error is gone. Looking through a camera turns its collection on, and turns it back off (unticked / hidden, as it was) once no 3D view looks through a camera. Tested on Wajima Trap.
- **Look Through + "Work on the Transform" together:** the toggle no longer drops the camera view and its photo. While a 3D view looks through a scan camera, only the other cameras are hidden, so the photo stays and G / R / S move the Transform against it. ◀ ▶ keep the toggle on and the Transform selected, and Look Through uses the scene camera then. Leaving the camera view hides all cameras again, the toggle off shows them all. Tested on Wajima Trap: on, ▶, scale, off.
- **Odd lens shift warning:** Build Scene and Import Metashape Cameras warn, per sensor, when its lens shift is past 0.5 (the principal point off by more than half the photo's long side: most likely a bad calibration in Metashape). The shift itself is kept as solved, since MultiCamProject now projects the photos through it.
- Removed the Turn 90° buttons from the first 0.4.4 build (they turned the scene, not the photos).
- Checked on a copy of the BatTrang Disk (29 photos, Open Source): Turn Camera Photos gives 29 portrait cameras; the same mesh points sample the same colours in the turned photos (mean difference 1.5/255, JPEG); a rebuild keeps them and does not turn the files again. Apply to Photos: 29 photos 4284×5712 with tag 1 in 6 s, EXIF focal length kept, a 180° flip exact, backups made, Convert & Sort does not turn them twice. Auto Level now stands it upright with the photos stored or turned. Panel screenshot-tested in a separate Blender window.

## 0.4.3 (2026-10-26)

- **Open Source aligns far more photos:** more features, guided matching and looser alignment thresholds. Teacup upright set: 30 of 30 photos instead of 13 (the side views of a plain lid had too few features with the defaults).
- **"Use masks: object only in the mesh":** the masks no longer touch the alignment (the background still helps to place the cameras). They are undistorted like the photos and keep the table / floor out of the dense point cloud and so out of the mesh.
- **Fix: black blobs in the texture.** TextureMesh's seam levelling painted black patches over the texture (or crashed); it is now off. Texturing also reads the photos without the masks.
- Tested on a copy of the Teacup: 30 cameras, only the cup in the mesh, clean texture, 5 minutes.

## 0.4.2 (2026-10-26)

- **Fix: a second Open Source run crashed in the dense point cloud** (access violation). OpenMVS reuses the depth maps left in the work folder by image number; from a run with other cameras they belong to other photos. Every Open Source run now starts without old depth maps / scene files (Hybrid already did). Checked: the same DensifyPointCloud call crashed with the old files and finished (94,242 points, 41 s) without them.

## 0.4.1 (2026-10-26)

- **Make Masks (step 2):** one black-and-white mask per photo in `zz.Scan\zz.Masks` (white = the object, black = ignored), for objects moved or flipped between photo sets. **AI cut-out** (U²-Net model, 176 MB downloaded once, runs offline with onnxruntime) or **Colour key** (no download, plain backgrounds). The photos are never changed. About 1 s per photo, in the background with a progress bar.
- **Check Masks:** a sheet of photos with the ignored part tinted red, in its own window.
- **Agisoft guide:** "1b. Import Masks" with a copy button for the file-name template, and "Apply masks to: Key points" on Align, shown when masks exist.
- **Open Source engine:** "Use masks" (off by default) passes them to COLMAP. Tested: on the glossy Teacup, masked COLMAP aligned only 13 of 45 photos (the top-down set) instead of 33 - a plain glossy object needs its background to align, so masks are opt-in there.
- ⚙ Advanced: Mask edge (how many pixels the kept area is widened).
- Checked on a copy of the 45 Teacup photos: AI masks keep only the cup in every view (upside down, side, top), 52 s for 45 photos.

## 0.4.0 (2026-10-26)

- **Folder + Name copy buttons:** every Agisoft step that opens a file dialog (Save As, the 3 exports) has two buttons: Folder (paste into the dialog's address bar) and Name (paste into File name); Metashape's dialogs did not take a whole path. The last one copied stays lit; the guide text says which to use.
- **Guide window stays on top** of Metashape (Windows), with a "Keep on top" switch in its sidebar.
- Checked in a separate Blender window: the guide window is marked topmost (the main window is not), unpinning works, Folder / Name copy the right parts; live on the Teacup: pinned, watcher running.

## 0.3.9 (2026-10-26)

- **Switching engines (Open Source -> Agisoft) works:** the Agisoft guide no longer takes another engine's published files for Agisoft exports (they count only when written after that engine's publish), and Align / Build Model come from the Metashape project itself. On the Teacup it now shows Align, Build Model / Texture and the 3 exports instead of "Nothing left to do".
- **Fix:** after a COLMAP publish, a new Agisoft camera XML was treated as already undistorted; the "already undistorted" mark now only holds while the XML is still the engine's own.

## 0.3.8 (2026-10-26)

- **Blender stays responsive while the engines run:** COLMAP and OpenMVS now run at below-normal priority and OpenMVS leaves two cores free; before, Windows marked Blender "not responding" during the dense cloud / mesh stages (the job itself kept running).
- **Texture no longer kills the run:** OpenMVS TextureMesh crashed (access violation) in its seam levelling on the 45-photo Teacup; the job now lets that fail softly and textures again without seam levelling (8K texture, 2 s).
- **New Object refuses an object folder as the place for a new object** (the Teacup ended up inside the Teapot's folder); the remembered objects folder steps up to its parent when it points at an object folder.

## 0.3.7 (2026-10-26)

- **iPhone browsers that force https:** Brave turned the QR link into `https://` and showed ERR_SSL_PROTOCOL_ERROR. The receiver now spots such a secure attempt, closes it at once (some browsers then fall back to http by themselves) and step 2 shows in red what to do: open the link in Safari, or turn off Brave's "Upgrade connections to HTTPS" for it. Step 2 also says that the link opens in the phone's default browser.
- **Fix:** on Windows a second Blender could take the same receiver port and get the phone's photos; each receiver now gets a port of its own.
- Checked: a TLS client is closed at once and counted; normal page + upload still work; a second receiver moves to port 8766 while 8765 is in use.

## 0.3.6 (2026-10-26)

- **A replaced photo is noticed:** Undistort records each source photo's size and date in livinglacquer.json. When a photo in zz.Source_Photos changes under the same name, its camera photo is made again by the next Undistort / Build, step 4 turns red ("N photo(s) replaced") and Check Links lists it. The first run after this update takes the current photos as the starting point (nothing is redone).
- Checked on a scratch Teapot: baseline -> photo swapped (detected, only that one redone) -> original put back (detected again, redone).

## 0.3.5 (2026-10-26)

- **Fix: saving the .blend turned step 3 red.** Check Links was counted as out of date whenever any file was newer than the check, the .blend included; now only new exports (cameras / model) make it stale.
- **Fix: Undistort redid all 52 photos every time.** The ↻ next to it was a sticky "Overwrite" switch (left on in the Teapot file). It is now a one-shot **Redo All** with a confirmation; normal Undistort / Build only make the missing or stale photos.
- **Camera photos show after Build:** only the first Build (the one that levels the scan) switches on "Work on the Transform" and starts scaling; every later Build ends looking through the first camera with its photo visible.
- Checked in a separate Blender window: re-Build with the toggle on -> toggle off, camera view IMG_3234 with its photo, 0 photos redone.

## 0.3.4 (2026-10-25)

- **Step 3 no longer stays red when the cameras were exported after the model** in a scene built before 0.3.1: the add-on now measures from the built scene how well the mesh lines up with the cameras (`scene.model.scene_alignment`, cached) instead of asking for another Build. Check Links' C17 uses the same measurement: "Cameras exported after the model, and they line up (86 %)" is OK; only a real mismatch stays a warning.
- Checked on a scratch Teapot with no Build record (step 3 done, C17 OK) and live on the Teapot (step 3 done, 86 %).

## 0.3.3 (2026-10-25)

- **Context-aware Agisoft guide:** it reads Metashape's own project files (photos added and whether they are where Metashape looks, cameras aligned, model built, project open) and the exports, and shows only the steps still to do, keeping their numbers. When photos were moved it starts with "0. Change Path". When nothing is left in Agisoft it says so and names the next step in Blender. Copy buttons only for the steps left; "Show all steps" lists the done ones as [done]. The window updates itself every 3 s while open.
- Checked read-only on the real Teapot project (52 photos, 52 aligned, model built, all photos looked for in the old `zz.Agisoft\00.Photos` -> only Change Path is left) and in a separate Blender window for a project not saved yet.

## 0.3.2 (2026-10-25)

- **5 steps instead of 8:** 1 Object · 2 Photos (receive + convert & sort) · 3 Reconstruct (engine + Check Links) · 4 Build Scene & Cameras (build + undistort + camera photos) · 5 Package. Green = done, red = a problem, ▶ = the step to work on.
- **Metashape panel merged into step 4:** Look Through Camera with ◀ ▶, photo opacity and front / back (now applied to all cameras as you change them, no Apply button). The separate panel is gone; its importer is still in File › Import.
- **Fix: camera photos did not show.** "Work on the Transform" hides the cameras, and Blender draws no photo for a hidden camera. Looking through a camera (or ◀ ▶) now switches that toggle off, and step 4 says when photos are hidden because of it.
- **Agisoft guide:** buttons carry their guide step number (1. Photo folder, 2. Project .psx, 5. Cameras .xml, ...) and the last one you copied stays lit.
- Checked in a separate Blender window: photo visible / hidden by the toggle / back after ▶; the 5-step panel colours; the numbered guide.

## 0.3.1 (2026-10-25)

- **Agisoft guide window:** its sidebar shows only "Agisoft Paths" (Blender's Find & Replace / Properties panels are hidden in that window only); buttons are named Photo folder, Project .psx, Cameras .xml, Model .abc, Texture .jpg; the paths are left out of the text unless **Show paths** is switched on.
- **Step 4 is no longer flagged just because the cameras were exported after the model:** Build now records how well the mesh lines up with the cameras, and when that was measured on these exact files (>= 50 %), step 4 is done ("line up 86 %").
- Checked: step 4 before / after Build on the scratch Teapot with newer cameras, guide text with and without paths, Blender's panels restored on unregister, guide window in a separate Blender window.

## 0.3.0 (2026-10-25)

- **Step status:** the add-on works out which steps are done from the object folder and the .blend (done ✔ / stale ⚠ / to do / blocked 🔒, with a one-line summary each) and which one is current (▶). Refreshed after every job and file load; refresh button next to the engine switch.
- **Panel:** done steps are greyed and folded, the current step is open, later steps stay locked until what they need is done; click a step's header to open or close it. Each step's main button is big and carries the step's name ("3. Convert & Sort", "6. Build Scene", ...).
- **Agisoft guide in its own window:** "How to work in Agisoft" opens a small movable window with the whole guide and every path written out, plus copy buttons; Open Metashape opens it too.
- **Fix:** a new camera alignment (Agisoft re-aligned, or another engine) resets the Transform and levels it again, instead of keeping a rotation / scale made for the old alignment.
- **Fix:** the standing-person viewport button could not be clicked (error on hover).
- Checked: step detection on 5 objects at different stages (headless), re-alignment reset, panel and guide window in a separate Blender window.

## 0.2.8 (2026-10-25)

- Size refs and Auto Level & Center swapped: Auto Level first, then the person, in the sidebar row and in the viewport column.
- **Standing-person icon** instead of Blender's running man: a small icon generated from the size-reference silhouette (sidebar) and a custom round viewport button drawing the same figure.
- Fixed a crash from the first try of this icon (Blender's 2D button `shape` property), installed only for about two minutes; the viewport button is now a Python gizmo and was tested in a separate Blender window before being installed.

## 0.2.7 (2026-10-25)

- **Viewport buttons:** Size refs, Auto Level & Center and Work on the Transform are also round buttons in the 3D Viewport, right under Blender's zoom / pan / camera / ortho buttons. Toggles light up blue while on. They follow the sidebar width and the navigation gizmo size, hide with Show Gizmo / Navigate off, and only appear when the file is an object folder.
- Checked live in Blender 5.2.2: the three buttons continue Blender's column at the same spacing.

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
