# LivingLacquer - Handoff

## 0. Where we are

- 0.2.0: scan pipeline steps 1-8 all built (phases 2-6 of the plan). Tested headless only (Blender 5.2.2 background + scratch copies of the Teapot); the user tests the UI. See §6 for how each step works and what is left.
- 0.1.0: scan pipeline phase 1 (Object + Check Links + per-sensor size fix).

- 0.0.2: sidebar tab feature (drop-in `sidebar_tab.py`, checked live).
- 0.0.1: scaffold + **metashape** module (ported from `Metashape Camera Importer` 0.1.0, behavior unchanged).
- Smoke-tested in Blender 5.2.2 on 2026-10-24 with a synthetic 2-camera export: add-on enables, all panels / operators / File > Import entry register, import + undistort + Look Through / Step / Apply to All work, module toggle off/on works, unaligned cameras are skipped.
- Next: run the checklist below on a real Metashape export of a lacquer piece (alignment with the OBJ is the key unknown).
- Scan pipeline (target 0.1.x) agreed 2026-10-25: design in [PLAN_scan_pipeline.md](PLAN_scan_pipeline.md), session handoff (sample state, per-sensor size bug, build order) in [HANDOFF_scan_pipeline.md](HANDOFF_scan_pipeline.md).
- No GitHub remote yet.

## 1. Purpose

LivingLacquer collects the tools used to model and texture scanned lacquerware into one add-on. Each tool is a module under `addons/LivingLacquer/modules/`, switchable from the Infos panel (Debug on).

## 2. Modules

| Module | Status | What it does |
|---|---|---|
| project | 0.2.0 | Scan Pipeline panel, step 1 New / Open Object, livinglacquer.json, folder rules (`paths.py`), background jobs (`jobs.py`), local cache Pull / Push (`cache.py`), add-on preferences (tool paths, work folder) |
| ingest | 0.2.0 | Step 2 iPhone receiver (`receiver.py`, watch folder) and step 3 Convert & Sort (`convert.py` plan, `worker.py` subprocess, `deps.py` pip installer) |
| engines | 0.2.0 | Step 4: Agisoft guide / launcher / export watcher (`agisoft.py`), Open Source + Hybrid jobs (`pipelines.py`), COLMAP -> Agisoft XML (`colmap_xml.py`), tool paths (`tools.py`) |
| linker | 0.1.0 | Step 5 Check Links: folder / photo / XML checks (`checks.py`), .blend paths + fixes (`blendpaths.py`) |
| scene | 0.2.0 | Steps 6-8: model import + axis fix + alignment check + textures (`model.py`), cameras, undistort, publish (`build.py`) |
| metashape | 0.0.1 | Metashape XML cameras -> Blender cameras with undistorted background photos (per-sensor size check since 0.1.0) |

## 3. metashape notes

- Coordinates: the OBJ must be imported Forward = Y, Up = Z. The chunk transform (rotation, translation, scale) is applied to every camera.
- Camera model: sensor width fixed at 36 mm, `lens = f * 36 / max(w, h)`, `shift = (-cx, cy) / max(w, h)`. The undistorted photo keeps f / cx / cy, so it lines up with the pinhole camera.
- Undistortion: Brown model (k1-k4, p1, p2, b1, b2) remapped with numpy in 256-row strips, bilinear sampling, black outside the source.
- Photos that do not fit their own sensor (other aspect, rotated) are skipped by default; each lens is checked separately, so mixed-lens shoots keep all cameras.
- Camera objects keep `metashape_res` and `metashape_photo` custom properties.

## 4. Live test checklist (metashape)

- [ ] Add-on enables without errors; Infos and LivingLacquer > Metashape panels show.
- [ ] Debug on: Modules row shows Metashape; toggling it off removes the panel and the File > Import entry, on brings them back.
- [ ] Import a real export: cameras land in `Cameras_Metashape`, photos in `<photos>_undistorted`, progress shows in the header, Esc stops cleanly.
- [ ] Cameras line up with the imported OBJ (check edges of the lacquer piece against the photo).
- [ ] Step arrows cycle cameras and update render resolution.
- [ ] Apply to All Cameras changes opacity / depth.
- [ ] Re-import with Overwrite off reuses the undistorted photos.

## 5. Roadmap

- Scan pipeline (numbered steps, Agisoft / Hybrid / Open Source engines): see [PLAN_scan_pipeline.md](PLAN_scan_pipeline.md) §9 for the build phases.

Ideas only, to be decided:
- More modeling / texture modules for the lacquer workflow (projection painting from the camera photos, cleanup of scan meshes).

## 6. Scan pipeline notes (0.2.0)

- **Panel:** LivingLacquer › Scan Pipeline. Each step is drawn by the module that owns it (`project/ui.py` STEPS). **Every wait is a job** (`project/jobs.py`, one at a time): progress bar + Cancel at the top of the panel and the same line in the status bar; Python steps are generators yielding (fraction, "what"), run in 0.1 s slices, "Show Log" writes the log into the text block "LivingLacquer Log". Engine logs also land in `zz.Scan\zz.COLMAP_OMVS\logs`.
- **Step 2:** `receiver.py` serves on 0.0.0.0, first free port from 8765, random token in the URL (403 without it), photos only (415), 300 MB cap, writes to `zz.Originals` through a temp file. QR code needs segno (Install button). Windows asks once to allow Blender through the firewall. iOS Shortcut: Get Contents of URL, POST, `http://<pc>:<port>/upload?t=<token>&name=<file>`, body = file. Convert & Sort starts 8 s after the last upload. The eye button watches the photo folders instead.
- **Step 3:** pillow / pillow-heif / rawpy / segno are pip-installed into Blender's user `scripts\modules`. Conversion runs in `worker.py` with Blender's Python (process pool). Rule: a JPG of the photo wins; HEIC / RAW / PNG without one are converted (EXIF rotation baked, EXIF + ICC kept, q95, 4:4:4); originals, IMG_E edits, videos and Drive duplicates go to `zz.Originals`; received JPGs move from `zz.Originals` up to `zz.Source_Photos`.
- **Step 4:** Agisoft = Open Metashape (photo folder on the clipboard), the guide with copy buttons, and a watcher that waits until CAM xml + model + texture exist and stop growing. The Batch Process job file from the plan is NOT written (its format still needs checking in Metashape Standard). Hybrid = Agisoft only aligns + exports cameras; the XML is copied with absolute photo paths as labels (InterfaceMetashape reads photos from the labels), then Densify / Mesh / Refine / Texture. Open Source = photos copied locally into one folder per photo size (one COLMAP camera per lens), feature_extractor (OPENCV) / exhaustive_matcher / mapper / largest model / model_orientation_aligner / image_undistorter / model_converter TXT -> `CAM_<Object>.xml` (pinhole) / InterfaceCOLMAP / OpenMVS. Work folder: `%LOCALAPPDATA%\LivingLacquer\work\<object>_<id>\<engine>` (depth maps ~36 MB per photo stay off Drive). Result + `engine_result.json` -> `zz.COLMAP_OMVS\result`, then published automatically.
- **Step 6:** Alembic from Metashape is Z-up but Blender's importer turns it as Y-up, so ABC starts at X -90 deg; Build tries X 0 / -90 / +90 / 180 and keeps the rotation where most mesh vertices project inside 9 sample photos (Teapot: -90, 86 %). Cameras that come with the ABC are deleted (XML wins). `OBJ_<Object>` goes to the `OBJECTS` collection and is replaced on every Build; materials `MAT_<Object>[_n]` are linked to the object. Cameras go to `CAMERAS` (cameras only) and are updated by name; scan cameras no longer in the XML are removed. These are the names MultiCamProject looks for (its roles.py). The mesh and every camera are parented to the `Transform` empty (alone in the `TRANSFORM` collection) with their XML-space matrix as local matrix, so moving / rotating / scaling `Transform` moves the whole scan and survives re-runs. Old `Geometry_<Object>` / `Cameras_<Object>` collections are removed once empty.
- **Step 7:** undistorts only missing photos, or all of a lens whose calibration fingerprint changed (stored per sensor in livinglacquer.json). Skipped when the published photos are already undistorted (COLMAP).
- **Step 8:** copies the newest `engine_result.json` result into `01.CAM_Photos` / `02.Geometry` with the standard names (only changed files), rewrites the OpenMVS .mtl, records `published` in the marker, makes the .blend paths relative. With Agisoft exports there is nothing to copy.
- **Local cache (⚙):** Pull mirrors the object folder into `<work folder>\cache\` with robocopy and marks it checked out on Drive; Push copies newer files back (marker merged by hand) and releases it. COLMAP's dense folder is never copied.
- **Not done from the plan:** manual path slots in ⚙ (auto-detect only), "Exclude ultra-wide from texturing", the Metashape Batch Process file, the A1 confirm dialog (loose matches are only reported), MulticamProject reading the marker.
- **Auto Level & Center (`scene/level.py`):** computed from the data, never a stored G / R / S: up = normal of the plane through the camera positions (SVD of the camera centers; sign from the cameras' own up vectors), rotation = the smallest one taking that normal to +Z (no extra turn about Z), translation = minus the center of the mesh's vertex bounding box after that rotation, scale kept. Writes only the `Transform` matrix and sets `Transform["ll_levelled"]`. Runs by itself on a Build while `Transform` is still fresh (identity, never levelled), then starts interactive scaling (`transform.resize` with `center_override` = world origin); the Auto Level & Center and Scale buttons redo either one. On the Teapot it tilts 31 deg, matching the user's hand-levelled 30.7 deg; up within 0.3 deg. Fails for captures that are not a ring around the object (e.g. one straight line of photos): then level by hand.
- **1.7 m person (`scene/human.py`):** GPU overlay (POST_VIEW silhouettes in two crossed planes + POST_PIXEL label), toggle next to Build (`pipe_show_human`). Stands on the floor (Z = 0) beside the scan; honours Unit Scale. Vertex samples are cached per mesh, so it follows the scaling smoothly.
- **Viewport (`scene/view.py`):** after Build's scene step every 3D Viewport is centered on the scan mesh (vertex box, distance 1.8 x its size; a camera view switches to perspective). The pivot toggle (next to Scale) sets Pivot Point = 3D Cursor and keeps the cursor at the world origin with a 0.5 s timer while on; off restores the user's pivot and cursor (kept in scene["ll_prev_pivot"/"ll_prev_cursor"]).
