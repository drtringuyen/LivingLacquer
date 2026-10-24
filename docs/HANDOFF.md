# LivingLacquer - Handoff

## 0. Where we are

- 0.0.2: sidebar tab feature (drop-in `sidebar_tab.py`, checked live).
- 0.0.1: scaffold + **metashape** module (ported from `Metashape Camera Importer` 0.1.0, behavior unchanged).
- Smoke-tested in Blender 5.2.2 on 2026-10-24 with a synthetic 2-camera export: add-on enables, all panels / operators / File > Import entry register, import + undistort + Look Through / Step / Apply to All work, module toggle off/on works, unaligned cameras are skipped.
- Next: run the checklist below on a real Metashape export of a lacquer piece (alignment with the OBJ is the key unknown).
- No GitHub remote yet.

## 1. Purpose

LivingLacquer collects the tools used to model and texture scanned lacquerware into one add-on. Each tool is a module under `addons/LivingLacquer/modules/`, switchable from the Infos panel (Debug on).

## 2. Modules

| Module | Status | What it does |
|---|---|---|
| metashape | 0.0.1 | Metashape XML cameras -> Blender cameras with undistorted background photos |

## 3. metashape notes

- Coordinates: the OBJ must be imported Forward = Y, Up = Z. The chunk transform (rotation, translation, scale) is applied to every camera.
- Camera model: sensor width fixed at 36 mm, `lens = f * 36 / max(w, h)`, `shift = (-cx, cy) / max(w, h)`. The undistorted photo keeps f / cx / cy, so it lines up with the pinhole camera.
- Undistortion: Brown model (k1-k4, p1, p2, b1, b2) remapped with numpy in 256-row strips, bilinear sampling, black outside the source.
- Odd-size photos (different from the most common size) are skipped by default.
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

Ideas only, to be decided:
- More modeling / texture modules for the lacquer workflow (projection painting from the camera photos, cleanup of scan meshes).
