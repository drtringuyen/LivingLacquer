# Installing LivingLacquer

This guide takes you from nothing to a working scan pipeline on Windows: the add-on itself, the Python
packages it uses, and the two free photogrammetry programs, **COLMAP** and **OpenMVS**, that the
**Open Source** engine runs. Agisoft Metashape is optional and only needed for the **Agisoft** and
**Hybrid** engines.

Tested with: Windows 11, Blender 5.2, COLMAP 4.2.1, OpenMVS 2.4.0, NVIDIA RTX 4080.

---

## 1. What you need

| | Minimum | Recommended |
|---|---|---|
| System | Windows 10 or 11, 64-bit | Windows 11 |
| Blender | 4.2 | 5.2 |
| Graphics card | none (CPU builds work, slowly) | NVIDIA with an up-to-date driver (CUDA builds) |
| Memory | 16 GB | 32 GB or more |
| Free disk | 10 GB | 50 GB on a fast local SSD |
| Internet | for the downloads and Python packages | |

The engines write large temporary files: about **36 MB per photo** for depth maps alone. A 100-photo
object can use several GB in the local work folder (see [step 7](#7-tell-the-add-on-where-everything-is)).

---

## 2. Install the add-on

1. Get the code:
   ```bash
   git clone https://github.com/drtringuyen/LivingLacquer.git
   ```
   or on GitHub click **Code > Download ZIP** and unzip it.
2. Build the installable zip (needs any Python 3):
   ```bash
   cd LivingLacquer
   python zip_addon.py
   ```
   This writes `LivingLacquer.zip` next to the script. Do **not** install GitHub's own download zip
   directly: the add-on sits in `addons/LivingLacquer/` inside it and Blender will not find it.
3. In Blender: **Edit > Preferences > Add-ons**, the **v** menu at the top right, **Install from Disk...**,
   pick `LivingLacquer.zip`, then tick **LivingLacquer** in the list.
4. In the 3D View press **N**: the **LivingLacquer** tab appears in the sidebar.

To update later: `git pull`, run `python zip_addon.py` again and reinstall the zip (restart Blender
afterwards).

> Developers working from the repository can use `python install.py` instead, which copies the add-on
> straight into Blender's add-ons folder and reloads it.

---

## 3. Python packages (automatic)

Some steps need Python packages that Blender does not ship with: **pillow** and **pillow-heif** (iPhone
HEIC photos), **rawpy** (RAW photos), **segno** (the QR code for receiving photos) and **onnxruntime**
(AI masks). You do not install them by hand: when a step needs one, its panel shows an **Install ...**
button. Click it once, wait for the progress bar, done. They go into Blender's own user `scripts/modules`
folder, not into your system Python.

---

## 4. COLMAP and OpenMVS: the one-click way

**Open Source** (COLMAP + OpenMVS) is the default engine. The first time you open step
**3. Reconstruct** without them, it shows **Install Engines (COLMAP + OpenMVS)**:

1. Click it and confirm **Download**.
2. The add-on downloads the tested releases, **COLMAP 4.2.1** and **OpenMVS 2.4.0**, from their official
   GitHub pages: the CUDA builds if you have an NVIDIA card (about 430 MB), the CPU builds otherwise (about
   150 MB). The progress bar follows the download and the unpacking. Blender stays usable meanwhile.
3. They go into the **Engines Folder**, `%LOCALAPPDATA%\LivingLacquer\engines` unless you pick another one
   in **Edit > Preferences > Add-ons > LivingLacquer**. The add-on then points its COLMAP and OpenMVS
   folders at them and saves the preferences. Done: skip to [step 8](#8-first-run).

To install them again (a broken folder, or after switching graphics cards), click **Install Engines** next
to **Engines Folder** in the add-on's preferences. Nothing is ever downloaded without that click.

If the download is blocked (a company network, no internet on the scan computer), install them by hand
with steps 5 and 6 below.

---

## 5. Install COLMAP by hand (aligns the cameras)

COLMAP finds the photos' features, matches them and solves where every camera stood.

1. Open the releases page: <https://github.com/colmap/colmap/releases/latest>
2. Under **Assets** download **one** of:
   - `colmap-x64-windows-cuda.zip` (about 415 MB): for an NVIDIA graphics card. Much faster.
   - `colmap-x64-windows-nocuda.zip` (about 130 MB): any other computer.
3. Make the folder `C:\Photogrametry Tools\` (spelled exactly like this if you want to skip step 7's
   settings; any other folder works too).
4. Right-click the zip, **Extract All...**, and extract it into `C:\Photogrametry Tools\`. You must end up
   with:
   ```
   C:\Photogrametry Tools\colmap-x64-windows-cuda\
       bin\colmap.exe
       plugins\
       COLMAP.bat
   ```
   If you see `colmap-x64-windows-cuda\colmap-x64-windows-cuda\bin`, the zip was extracted one level too
   deep: move the inner folder up.
5. Check it: double-click `COLMAP.bat`. The COLMAP window opens. Close it. (Help > About shows the
   version.)

Use COLMAP **4.x**. The add-on passes COLMAP 4 option names, and older 3.x releases may refuse them.

---

## 6. Install OpenMVS by hand (builds the mesh and texture)

OpenMVS turns the aligned cameras into a dense point cloud, a mesh and a texture.

1. Open the releases page: <https://github.com/cdcseacave/openMVS/releases/latest>
2. Under **Assets** download **one** of:
   - `OpenMVS_Windows_x64_CUDA.7z` (about 11 MB): for an NVIDIA graphics card.
   - `OpenMVS_Windows_x64.zip` (about 22 MB): any other computer.
3. A `.7z` file needs **7-Zip** (<https://www.7-zip.org>) unless your Windows already opens `.7z` in
   Explorer. Right-click it, **7-Zip > Extract to "OpenMVS_Windows_x64_CUDA\"**. The CUDA `.7z` is
   complete on its own: it does not need the CPU zip. The CPU zip keeps its files in `vc17\x64\Release\`:
   use that innermost folder.
4. Put that folder in `C:\Photogrametry Tools\`. You must end up with the programs directly inside it,
   next to many `.dll` files:
   ```
   C:\Photogrametry Tools\OpenMVS_Windows_x64_CUDA\
       InterfaceCOLMAP.exe
       InterfaceMetashape.exe
       DensifyPointCloud.exe
       ReconstructMesh.exe
       RefineMesh.exe
       TextureMesh.exe
       ...dll
   ```
   With the non-CUDA zip the folder is named differently; that is fine, just point the add-on to it in
   step 7.

---

## 7. Tell the add-on where everything is

After **Install Engines**, or if you used exactly the folders above, there is nothing to do. Otherwise:

1. Open the LivingLacquer tab (**N** in the 3D View), and in the scan pipeline panel click the
   **gear** button next to the engine switch (**Agisoft / Hybrid / Open Source**). The **Advanced** box
   opens. The same settings are in **Edit > Preferences > Add-ons > LivingLacquer**.
2. Set:
   - **COLMAP**: the folder that holds `bin\colmap.exe` (not the `bin` folder itself).
   - **Engines Folder**: where **Install Engines** puts them (empty = `%LOCALAPPDATA%\LivingLacquer\engines`).
   - **OpenMVS**: the folder that holds `DensifyPointCloud.exe`.
   - **Local Work Folder**: where the big temporary files go. Leave it empty for
     `%LOCALAPPDATA%\LivingLacquer`, or pick a folder on a fast local drive with plenty of space. Not a
     cloud-synced folder (Google Drive, OneDrive, Dropbox).
   - **Metashape**: only if you use Agisoft (default `C:\Program Files\Agisoft\Metashape\metashape.exe`).
3. Select **Open Source** in the engine switch and open step **3. Reconstruct**. When everything is found,
   there is **no** red line saying `Not found: ...`. If there is one, it names the program that is
   missing: fix that path.

---

## 8. First run

1. Step 1: create the object. Step 2: bring in the photos (from the iPhone or a folder) and run
   **Convert & Sort**.
2. Step 3: engine **Open Source**, pick a quality (**Fast** for a first try, **Normal** for real work,
   **High** is slow), click **Reconstruct: COLMAP + OpenMVS**. The progress bar names each stage:
   Features, Matching, Align cameras, Undistort, Dense point cloud, Mesh, Refine mesh, Texture.
3. If masks were made in step 2, the option **Use masks: object only in the mesh** appears: it cuts the background out of the
   mesh, while the cameras still align on the whole photo.
4. When it finishes, step 4 builds the scene with the cameras and photos.

Logs of every run are kept in the object's folder under `zz.Scan\zz.COLMAP_OMVS\logs`; **Show Log** in
step 3 opens the current one.

---

## 9. Troubleshooting

| What you see | Why, and what to do |
|---|---|
| **Install Engines** fails | Its log is `install.log` in the Engines Folder. A blocked download: install by hand (steps 5 and 6). |
| `Not found: COLMAP` | The COLMAP path is not the folder holding `bin\colmap.exe`. Often the zip was extracted one level too deep. |
| `Not found: DensifyPointCloud, ...` | The OpenMVS path is not the folder holding the `.exe` files. |
| A program fails with a missing `MSVCP140.dll` / `VCRUNTIME140.dll` | Install the Microsoft Visual C++ Redistributable (x64): <https://aka.ms/vs/17/release/vc_redist.x64.exe> |
| A CUDA build fails with a CUDA or driver error | Update the NVIDIA driver, or use the non-CUDA builds. |
| `COLMAP could not align the photos` | Too little overlap or a plain, shiny object. Shoot more photos with about 60-70% overlap, add texture to the background (newspaper under the object), avoid blur. |
| Only some photos aligned | Same as above; the photos that did not align show in the log. |
| The disk fills up | Point **Local Work Folder** to a bigger drive. Old runs can be deleted from it safely. |
| The run stops at "Dense point cloud" with an access violation | Leftover depth maps from another run; the add-on clears them at the start of each run. Delete the object's folder inside the Local Work Folder and run again. |
| Anything else | Open **Show Log** and look at the last lines; the program's own error is there. |

---

## 10. Licenses

LivingLacquer is GPL-3.0-or-later. COLMAP (BSD license, <https://colmap.github.io>) and OpenMVS
(AGPL-3.0, <https://github.com/cdcseacave/openMVS>) are separate programs by their own authors. The
add-on does not ship them: **Install Engines** downloads their official, unmodified releases straight from
their authors' GitHub pages, and the add-on only runs them. Please cite them if you publish work made with them.
