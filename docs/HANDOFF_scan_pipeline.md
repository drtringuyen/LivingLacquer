# LivingLacquer – Scan Pipeline Handoff (2026-10-25)

## Context
- Repo: D:\Documents\04.Blender Addon Development\LivingLacquer (v0.0.2, blender-addon-init scaffold, module system, sidebar_tab.py)
- Existing module `modules/metashape/`: parse.py (Agisoft XML → sensors + camera matrices), photos.py (Brown-model undistort with numpy), cameras.py, operators.py (`livinglacquer.metashape_import`, look-through, step, BG apply), ui.py. See docs/HANDOFF.md.
- Blender 5.2.2 with the Blender MCP; Windows PC with an RTX 4080.
- Agisoft Metashape **Standard** (no Python/headless). Batch Process is available.
- Tools: C:\Photogrametry Tools\colmap-x64-windows-cuda\bin\colmap.exe
         C:\Photogrametry Tools\OpenMVS_Windows_x64_CUDA\ (InterfaceCOLMAP, InterfaceMetashape, DensifyPointCloud, ReconstructMesh, RefineMesh, TextureMesh .exe)
- Objects: H:\My Drive\12.BudhaKing\14.SonMai-Interactive\00.3D\NN.<Object>\ (Google Drive streaming)
- Should later work together with the MulticamProject add-on (shared links/manifest).
- Full design: docs/PLAN_scan_pipeline.md

## Folder convention (both samples already renamed)
```
NN.<Object>\
├─ NN.<Object>.blend              ← root; all paths relative to it
└─ zz.Scan\
   ├─ zz.Source_Photos\           JPGs the engines read (convert only if no JPG; JPG default)
   │  └─ zz.Originals\            NEF / HEIC / unused originals
   ├─ 01.CAM_Photos\              CAM_<Object>.xml + undistorted photos (original names = camera labels)
   ├─ 02.Geometry\                OBJ_<Object>.abc + OBJ_<Object>.jpg (+ _1/_2, _normal, _ao)
   ├─ zz.Agisoft\                 AGS_<Object>.psx + .files
   └─ zz.COLMAP_OMVS\             colmap\, openmvs\, logs
```
- <Object> = folder name without "NN." (e.g. BatTrang_Teapot). Prefixes in caps with underscore.
- Ignore desktop.ini, .lock, Thumbs.db and Drive conflict copies "(1)" everywhere.

## Current state of the samples
- 00.Wajima_Trap: Nikon Z50. 107 JPG in zz.Source_Photos (DSC_7077 has no NEF/undistorted copy), 106 NEF in zz.Originals, 106 undistorted JPG in 01.CAM_Photos (no EXIF, black borders), OBJ_Wajima_Trap.abc/.jpg, AGS_Wajima_Trap.psx. **No CAM xml yet.**
- 01.BatTrang_Teapot: iPhone 15 Pro Max. 112 JPG, CAM_BatTrang_Teapot.xml (52 aligned cameras, 1 chunk, no chunk transform), OBJ_BatTrang_Teapot.abc/.jpg, AGS_BatTrang_Teapot.psx. **No undistorted photos yet.**
- Both .blend files still point to the old paths → good first test for Check Links / relink.
- Both Agisoft projects need the photos relinked once (right-click → Change Path → zz.Source_Photos).

## Known bug to fix first
- Teapot mixes lenses: sensor 0 = main 6.765 mm 4284×5712 (40 cams), sensor 1 = ultra-wide 2.22 mm 3024×4032 (12 cams).
- operators.py `skip_odd_size` (default on) compares to the global most common size → silently drops the 12 ultra-wide cameras. Make the check **per sensor** (photo size vs that sensor's resolution). Keep all lenses.

## UI (sidebar, numbered steps)
```
Engine: [ Agisoft | Hybrid | Open Source ]  ⚙
1. Object        New Object… / Open Object…
2. Receive       iPhone upload (local server + QR + token)
3. Convert & Sort
4. Reconstruct   ← only step that changes per engine
5. Check Links   ✔ / ⚠ / ✖ report + fixes
6. Build Scene   mesh + textures + cameras
7. Undistort & Backgrounds (if needed)
8. Package       publish into 01.CAM_Photos + 02.Geometry
```
- A step stays greyed out until the steps it depends on are green; each step shows a one-line status.
- ⚙ gear (hidden from casual users): manual path slots (model fbx/abc/obj, source photos, converted, undistorted, xml or COLMAP folder, textures, psx), output format (JPG default / PNG / TIFF), quality, tool paths, local cache, overwrite.
- Step 1: New Object asks for the parent folder (remembered) + name, picks the next free NN, creates the tree, **saves the current file as NN.<Object>.blend**. Open Object opens its blend. Steps 2–8 are disabled until the file is saved inside an object folder.

## Engines (all publish the same output so steps 5–8 are shared)
- **Agisoft (semi-auto):** Blender writes a Batch Process file with exports pre-named and pre-pathed, opens Metashape, copies paths to the clipboard; the user does Add Folder → Save As → Batch Process Load → OK; Blender watches for the exports. Collapsible step-by-step "How to work in Agisoft" guide with copy buttons for paths.
- **Hybrid:** user only aligns + checks + exports cameras in Agisoft → Blender auto-runs InterfaceMetashape → DensifyPointCloud → ReconstructMesh → RefineMesh → TextureMesh.
- **Open Source (full auto):** COLMAP feature_extractor (OPENCV model, one camera per lens) → exhaustive_matcher → mapper → image_undistorter → InterfaceCOLMAP → OpenMVS chain. Convert COLMAP cameras to an Agisoft-format CAM_<Object>.xml (pinhole) so the existing importer is reused; COLMAP-undistorted images skip step 7.
- Run in the background (subprocess + timer), progress bar, cancel; logs in zz.COLMAP_OMVS.
- To verify: which steps Standard's Batch Process allows (Add Photos? export jobs?); whether InterfaceMetashape works from Standard's exports and undistorts the images itself.

## Links / Google Drive
- Every path the add-on writes is relative to the .blend (//...). Blender cannot make paths relative across drive letters → that is the two-Google-Drive bug source.
- `livinglacquer.json` marker in the object folder: project ID, owning Drive account, relative paths, calibration fingerprint, dates, "checked out by <machine>".
- Check Links flags files outside the object folder (red, "Pull into project" button) and a .blend opened under a different Drive account (e.g. "My Drive (tri@…)").
- Per-machine Local Work Root (e.g. D:\LL_Cache) in preferences: Pull to Local (mirror with the same relative tree) / Push to Drive (changed files only; COLMAP temp optional).

## Check Links coverage
- Names: label ≠ filename, extension/case variants, HEIC+JPG same stem, duplicate stems across shoots, IMG_E edits, Live Photo .MOV, "(2)" labels.
- Coverage: photos not in xml (report only), cameras without photo, unaligned/disabled cameras, several chunks/components (report).
- Geometry: mixed lenses, photo size ≠ sensor size, EXIF rotation baked vs not, stale undistort (fingerprint), COLMAP vs Agisoft undistort mixing, ABC/FBX Y-up vs XML Z-up (auto axis fix + alignment check projecting mesh into 3 cameras), stale model vs xml (timestamps), ABC-embedded cameras vs xml, chunk transform.
- Textures: assign by naming rule (ABC has no texture link), multi-page, absolute .mtl/FBX paths, sRGB vs Non-Color.
- Files: Drive placeholders/locks/conflicts, desktop.ini, non-ASCII/space paths in CLI quoting, 260-char limit, .psx open/locked.
- Re-runs: update in place by name (no duplicates), write to temp then rename, settings changed vs existing outputs.

## Build order
1. Step 1 Object + Step 5 Check Links (+ per-sensor size fix) → test on both samples (relink the Wajima/Teapot blends)
2. Step 6 Build Scene + 7 Undistort/BG + 8 Package
3. Step 3 Convert & Sort (reuse logic from 00.3D\zz.Temp Conversion\convert_images.py: pillow-heif, exif_transpose, EXIF kept; JPG default; NEF via JPG if present else convert)
4. Open Source engine
5. Agisoft semi-auto + Hybrid
6. Step 2 iPhone receiver (Safari upload page + iOS Shortcut, watch-folder fallback)
