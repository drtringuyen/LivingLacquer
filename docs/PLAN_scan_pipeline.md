# LivingLacquer – Scan Pipeline Plan

Status: agreed 2026-10-25 · Target: LivingLacquer 0.1.x · Blender 5.2 · Windows

## 1. Goal

Replace the manual chain
`iPhone → Google Drive → PC → HEIC→JPG → sort folders → Agisoft → export → import in Blender`
with numbered steps in one Blender panel:
`iPhone → Blender → (Agisoft | Hybrid | Open Source) → mesh + textures + cameras + undistorted backgrounds in Blender`.

Principles
- **The saved .blend is the root.** Nothing runs until the file is saved as `NN.<Object>.blend` inside its object folder.
- **One output contract.** Every engine publishes the same files to the same place, so everything after Reconstruct is shared code.
- **Relative paths only.** Links must survive moving between Google Drive, local cache and other computers/accounts.
- **Casual users see steps; power users open the gear.**

## 2. Folder convention

```
00.3D\
└─ NN.<Object>\
   ├─ NN.<Object>.blend
   ├─ livinglacquer.json              project marker (see §7)
   └─ zz.Scan\
      ├─ zz.Source_Photos\            engine input: JPG
      │  └─ zz.Originals\             HEIC / NEF / anything not used directly
      ├─ 01.CAM_Photos\               CAM_<Object>.xml + undistorted photos   ← published
      ├─ 02.Geometry\                 OBJ_<Object>.<abc|fbx|obj> + textures    ← published
      ├─ zz.Agisoft\                  AGS_<Object>.psx + AGS_<Object>.files
      └─ zz.COLMAP_OMVS\
         ├─ colmap\                   database.db, sparse\, dense\
         ├─ openmvs\                  scene.mvs, dense, mesh, textured
         └─ logs\
```

Naming
| Item | Name |
|---|---|
| Object | folder name without `NN.` → `BatTrang_Teapot` |
| Agisoft project | `AGS_<Object>.psx` |
| Cameras | `CAM_<Object>.xml` (Agisoft XML format, for every engine) |
| Model | `OBJ_<Object>.abc` (or .fbx / .obj) |
| Textures | `OBJ_<Object>.jpg`, multi-page `OBJ_<Object>_1.jpg…`, maps `_normal`, `_ao` |
| Photos | **original stem kept** (`IMG_3234.jpg`, `DSC_7078.jpg`); camera labels = photo stems |
| Undistorted | same stem as the camera label, inside `01.CAM_Photos` |

Accepted variants when reading old folders: `zz.scan`, `00.SourcePhotos`, `00.Source_Photos`, `01.Agisoft` (Check Links offers to rename them).
Ignored everywhere: `desktop.ini`, `Thumbs.db`, `.lock`, `lock`, Drive conflict copies `name (1).ext`.

Publishing rule: engines write only in their own `zz.` folder. **Step 8 publishes** the chosen engine's result into `01.CAM_Photos` + `02.Geometry`. Those two folders are "the current truth" that Blender and MulticamProject link to.

## 3. Panel

```
LivingLacquer › Scan Pipeline
Engine: [ Agisoft | Hybrid | Open Source ]  ⚙
────────────────────────────────────────────
1. Object            [New Object…] [Open Object…]     ✔ 01.BatTrang_Teapot
2. Receive           [Start Receiving]  QR · 0 photos
3. Convert & Sort    (auto after 2)                   ✔ 112 JPG
4. Reconstruct       (engine-specific, see §5)
5. Check Links       [Check]   ✔ 52  ⚠ 60  ✖ 0   [Fix…]
6. Build Scene       [Build]   mesh · textures · cameras
7. Undistort & BG    (auto inside 6 when needed)
8. Package           [Publish to 01.CAM_Photos / 02.Geometry]
```

- Every step shows ✔ / ⚠ / ✖ + one status line; it is greyed out until the steps it depends on pass.
- Long operations are modal with a progress bar and Esc to cancel.
- **⚙ Gear (advanced, collapsed by default)**
  - Manual path slots, each with a picker, a status icon and Auto-detect: model (fbx/abc/obj), iPhone source photos, converted photos, undistorted photos, camera XML / COLMAP folder, textures, Agisoft .psx.
  - Output format: **JPG (default)** / PNG / TIFF, quality.
  - Undistort: overwrite, format.
  - Tool paths (COLMAP, OpenMVS, Metashape.exe).
  - Local Work Root + Pull / Push (see §7).
  - Engine presets (quality levels), "Exclude ultra-wide from texturing" (off by default).

### Step 1 – Object
- **New Object:** parent folder (remembered, e.g. `00.3D`) + name → next free `NN.` → creates the §2 tree + `livinglacquer.json` → **saves the current file** as `NN.<Object>.blend`.
- **Open Object:** pick an object folder → opens its .blend.
- If the current file is unsaved or not inside an object folder → steps 2–8 are disabled with "Save as an object to start".

### Step 2 – Receive
- Local HTTP server inside Blender, on the LAN only, with a random pairing token in the URL; the panel shows a QR code + URL + counter + log.
- iPhone Safari upload page (zero setup) and an iOS Shortcut "Send to Blender" (share sheet, originals).
- Fallback: watch folder (USB / Drive drop).
- Originals are written to `zz.Source_Photos\zz.Originals\` first.

### Step 3 – Convert & Sort
- Reuses the `convert_images.py` logic: pillow-heif, `exif_transpose`, EXIF + ICC kept, quality 95, subsampling 0, parallel.
- Rule: JPG available → use it; otherwise convert (HEIC, NEF…) to JPG. Unused originals go to `zz.Originals`.
- Skips duplicates (hash); reports iPhone extras (IMG_E…, .MOV).
- Wheels bundled in the extension (pillow-heif; rawpy only if NEF without JPG is needed).

## 4. Output contract (all engines)
After step 4 the engine has produced, in its own folder:
- the cameras as `CAM_<Object>.xml` in Agisoft format (COLMAP is converted to it, pinhole when already undistorted)
- the model `OBJ_<Object>.*` + textures
- either distorted photos + calibration (Agisoft, Hybrid) → step 7 undistorts, or already undistorted photos (COLMAP) → step 7 skips.
A small `engine_result.json` says which applies, plus the axis convention of the model.

## 5. Engines (step 4)

### 5a Agisoft Standard – semi-auto
1. **Prepare Metashape:** Blender writes a Batch Process job file (align → depth maps → mesh → texture → export cameras / model / texture with §2 names and paths), launches Metashape.exe and copies the photo folder path + .psx path to the clipboard.
2. **User (≈ 3 clicks):** Workflow › Add Folder (paste) → File › Save As (paste) → Workflow › Batch Process › Load → OK.
3. **Waiting for exports:** a timer watches `zz.Agisoft`; when the XML, model and texture are complete (sizes stable), go to step 5.
- Collapsible **"How to work in Agisoft"** guide: recommended lacquer settings, what to check after alignment, export names/paths with copy buttons, the Change Path fix for moved photos.
- Fallback if the batch can't do a step in Standard: the guide lists the manual export with exact names.

### 5b Hybrid – Agisoft alignment + OpenMVS
1. The user in Agisoft: add photos → Align → check → Export Cameras (path given by Blender). About 2 min of clicks.
2. Blender sees the XML and runs in the background:
   `InterfaceMetashape` → `DensifyPointCloud` → `ReconstructMesh` → `RefineMesh` → `TextureMesh`.
3. Output → contract → steps 5–8.
- Benefits: Agisoft's alignment on glossy lacquer; no mesh/texture clicking; re-mesh with other settings without Agisoft; fair comparison on identical cameras.

### 5c Open Source – full auto
`colmap feature_extractor` (camera_model OPENCV, one camera per lens/EXIF) → `exhaustive_matcher` (≤ ~300 images) → `mapper` → `image_undistorter` → `InterfaceCOLMAP` → `DensifyPointCloud` → `ReconstructMesh` → `RefineMesh` → `TextureMesh` → convert the COLMAP cameras to `CAM_<Object>.xml` (pinhole).
- Subprocesses with a timer poll, log parsing for the stage + %, cancel kills the process tree.
- Presets: Fast / Normal / High (resolution level, refine on/off, texture size).

### To verify before building 5a / 5b
- Which steps Metashape Standard's Batch Process supports (Add Photos? Export Cameras / Model / Texture with paths?).
- Whether InterfaceMetashape accepts Standard's XML (+ tie points?) and undistorts the images itself.

## 6. Steps 5–8 (shared)

### Step 5 – Check Links
Reads `livinglacquer.json` + scans the folders → report grouped by severity, with a Fix button where possible.

| # | Check | Action |
|---|---|---|
| A1 | camera label ≠ photo stem | fuzzy match → confirm dialog |
| A2 | extension/case variants, HEIC+JPG same stem | prefer JPG |
| A3 | duplicate stems across shoots | ✖, list |
| A4 | IMG_E edits, Live Photo .MOV | ignore, report |
| A5 | "(2)" labels | strip suffix match |
| B6 | photos not in xml | report only |
| B7 | cameras without photo | ⚠, camera without BG |
| B8 | unaligned / disabled cameras | skip, report |
| B9–10 | several chunks / components | report; pick active |
| C11 | mixed lenses | **per-sensor size check** (fixes the global skip_odd_size bug) |
| C12 | photo size ≠ sensor size | scale calibration if same aspect, else ✖ |
| C13 | EXIF rotation baked vs not | compare orientation vs sensor w/h |
| C14 | stale undistorted (calibration changed) | fingerprint → re-undistort |
| C15 | COLMAP vs Agisoft undistort mixed | ✖ via engine_result.json |
| C16 | model axes (ABC/FBX Y-up vs XML Z-up), shift, scale | auto axis fix + **alignment check**: project the mesh bbox into 3 cameras |
| C17 | model older than xml (stale) | ⚠ timestamps |
| C18 | ABC-embedded cameras vs XML cameras | XML wins; hide/remove the ABC cameras |
| C19 | chunk transform | applied (parse.py already does this) |
| D20 | textures by naming rule, multi-page, maps | auto-assign |
| D21 | absolute texture paths in .mtl/FBX | relink relative |
| D22 | color space | diffuse sRGB, normal/AO Non-Color |
| E23 | Drive placeholders, locks, conflict copies, desktop.ini | ignore / warn on .psx lock |
| E24 | spaces / non-ASCII in paths | quoting test for the CLI tools |
| E25 | path > 260 chars | ⚠ suggest local cache |
| E26 | absolute paths in the .blend | make relative; flag cross-drive |
| E27 | psx open (lock) | ⚠ before touching zz.Agisoft |
| E28 | old folder names | offer rename to §2 |
| F29 | re-import duplicates | update in place by name |
| F30 | half-written files | temp + rename |
| F31 | settings changed vs existing outputs | offer re-run |
| G | file outside the object folder / other Drive account | ✖ "external link" → Pull into project |

### Step 6 – Build Scene
- Import the model with the axis fix for its format; assign textures by the naming rule; the existing `metashape` importer builds cameras from `CAM_<Object>.xml` into the collection `Cameras_<Object>`.
- Update in place on re-run (match by name), never duplicate.

### Step 7 – Undistort & Backgrounds
- Only when the engine delivered distorted photos. Reuse `photos.undistort_image` (Brown k1–k4, p1, p2, b1, b2; same f/cx/cy).
- Output to `01.CAM_Photos` with the original stems; set the camera backgrounds (opacity/depth from the existing settings).

### Step 8 – Package
- Publish the chosen engine's result into `01.CAM_Photos` + `02.Geometry` with §2 names; update `livinglacquer.json`; make all .blend paths relative.

## 7. Paths, Google Drive, local cache
- **Every path relative to the .blend.** Blender can't make paths relative across drive letters → the add-on detects this (root cause of the two-Drive wrong linking).
- **Contained project:** all files live inside `NN.<Object>\`. Anything outside = red "external link" + Pull into project (copy + relink).
- **`livinglacquer.json`:** `{ id, object, account (Drive folder label), engine, paths (relative), calibration_fingerprint, published: {engine, date}, checked_out_by }`. If the .blend sits under another Drive account folder than recorded → warning before linking.
- **Local cache (gear):** per-machine Local Work Root (e.g. `D:\LL_Cache`) stored in add-on preferences.
  - Pull to Local: mirror the object folder (same relative tree), open the local .blend.
  - Push to Drive: copy changed files back (by size/mtime); `zz.COLMAP_OMVS\colmap\dense` optional, off by default.
  - `checked_out_by` blocks a second machine from editing at the same time.
- MulticamProject should read the same `livinglacquer.json` and the published folders (check its code first).

## 8. Code layout (new modules)
```
addons/LivingLacquer/modules/
├─ metashape/       existing: XML import, undistort, cameras (+ per-sensor fix)
├─ project/         step 1, livinglacquer.json, folder tree, path rules, cache pull/push
├─ linker/          step 5 checks + fixes, report UI
├─ scene/           steps 6–8 (model import, axis fix, textures, publish)
├─ ingest/          steps 2–3 (server, QR, convert, sort)
└─ engines/
   ├─ base.py       subprocess runner, progress, cancel, logs, output contract
   ├─ agisoft.py    batch file writer, launcher, watcher, guide text
   ├─ hybrid.py
   └─ opensource.py
```
The pipeline panel is a new sub-panel; the steps call operators `livinglacquer.pipe_<step>`.

## 9. Build phases and done criteria
1. **Object + Check Links:** New/Open Object, forced save, json marker; checks A–G; per-sensor size fix. *Done when* both samples report correctly and the Wajima/Teapot blends relink from the new folders.
2. **Build Scene + Undistort + Package.** *Done when* the Teapot imports with all 52 cameras (incl. 12 ultra-wide), the mesh lines up in the alignment check, and publishing is idempotent.
3. **Convert & Sort.** *Done when* HEIC → JPG with EXIF, Nikon JPG+NEF sorted, re-run makes no duplicates.
4. **Open Source engine.** *Done when* Teapot photos → textured mesh + cameras in Blender with no clicks.
5. **Agisoft semi-auto + Hybrid** (after the §5 verifications).
6. **iPhone receiver.**

## 10. Capture notes for lacquer (for the Agisoft guide / README)
- Cross-polarized light; turntable + fixed soft light; lock AE/AF; turn off Macro Control (otherwise the iPhone switches to the ultra-wide up close).
- Mixed lenses are allowed (calibrated separately) but the ultra-wide gives a softer texture.
