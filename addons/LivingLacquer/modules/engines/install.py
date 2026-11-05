"""Install Engines: download the tested COLMAP and OpenMVS releases from their GitHub pages into a folder of the
user's (Preferences > Engines Folder, default %LOCALAPPDATA%\\LivingLacquer\\engines) and point the add-on's
COLMAP / OpenMVS folders at them. Nothing is bundled with the add-on; nothing is downloaded until the user
clicks. With an NVIDIA card (nvidia-smi answers) the CUDA builds, else the CPU ones; OpenMVS's CUDA build is a
.7z, unpacked by Windows' own tar, and falls back to the CPU .zip where that tar cannot read 7z.

The download and unpacking run in engine_worker.py, a separate process: Blender stays responsive and the
progress bar follows its "NN%" lines. Already found engines are left alone unless Reinstall is asked."""
import json
import os
import shutil
import subprocess
import sys

import bpy

from ..project import jobs, prefs
from . import tools

# tested together with the pipeline's options (pipelines.py); bump both after testing a new release
COLMAP = {"repo": "colmap/colmap", "tag": "4.2.1", "marker": os.path.join("bin", "colmap.exe"),
          "cuda": [("colmap-x64-windows-cuda.zip", 414666626)],
          "cpu": [("colmap-x64-windows-nocuda.zip", 127731595)]}
OPENMVS = {"repo": "cdcseacave/openMVS", "tag": "v2.4.0", "marker": "DensifyPointCloud.exe",
           "cuda": [("OpenMVS_Windows_x64_CUDA.7z", 11334115), ("OpenMVS_Windows_x64.zip", 22363227)],
           "cpu": [("OpenMVS_Windows_x64.zip", 22363227)]}
LICENSES = {"COLMAP": "BSD, https://colmap.github.io/license.html",
            "OpenMVS": "AGPL-3.0, source at https://github.com/cdcseacave/openMVS"}
_gpu = {}


def has_nvidia():
    """True when nvidia-smi lists a GPU (the NVIDIA driver installs it). Cached for the session."""
    if "nvidia" not in _gpu:
        exe = shutil.which("nvidia-smi") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                                          "nvidia-smi.exe")
        try:
            r = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _gpu["nvidia"] = r.returncode == 0 and "GPU" in r.stdout
        except (OSError, subprocess.SubprocessError):
            _gpu["nvidia"] = False
    return _gpu["nvidia"]


def engines_root():
    p = prefs.get()
    d = bpy.path.abspath(p.engines_root) if p and p.engines_root else ""
    return d or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LivingLacquer", "engines")


def needed(reinstall=False):
    """The engines to install: the ones not found, or both with reinstall."""
    out = []
    if reinstall or not tools.colmap_exe():
        out.append("COLMAP")
    if reinstall or not all(tools.openmvs(t) for t in tools.OPENMVS):
        out.append("OpenMVS")
    return out


def _task(name, spec, cuda, root):
    kind = "cuda" if cuda else "cpu"
    folder = f"{name.lower()}-{spec['tag'].lstrip('v')}-{kind}"
    tries = [{"url": f"https://github.com/{spec['repo']}/releases/download/{spec['tag']}/{asset}", "size": size}
             for asset, size in spec[kind]]
    return {"name": name, "dest": os.path.join(root, folder), "marker": spec["marker"], "tries": tries}


def install_job(reinstall=False, on_done=None):
    root = engines_root()
    os.makedirs(root, exist_ok=True)
    cuda = sys.platform == "win32" and has_nvidia()
    worker = os.path.join(os.path.dirname(__file__), "engine_worker.py")
    steps = []
    names = needed(reinstall)
    dests = {}
    for name in names:
        spec = COLMAP if name == "COLMAP" else OPENMVS
        task = _task(name, spec, cuda, root)
        dests[name] = task["dest"]
        path = os.path.join(root, f"{name.lower()}_task.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2)
        steps.append(jobs.Step(f"{name} {spec['tag']}" + (" (CUDA)" if cuda else ""),
                               [sys.executable, "-I", worker, path], weight=40 if name == "COLMAP" else 5))

    def use(job):
        """Point the preferences at the folders the worker filled and save them."""
        p = prefs.get()
        if p is None:
            raise RuntimeError("enable LivingLacquer in the Preferences first")
        if "COLMAP" in dests and os.path.isfile(os.path.join(dests["COLMAP"], COLMAP["marker"])):
            p.colmap_dir = dests["COLMAP"]
        if "OpenMVS" in dests and os.path.isfile(os.path.join(dests["OpenMVS"], OPENMVS["marker"])):
            p.openmvs_dir = dests["OpenMVS"]
        for name in names:
            job.log(f"{name}: {LICENSES[name]}")
        for f in os.listdir(root):
            if f.endswith("_task.json"):
                os.remove(os.path.join(root, f))
        left = needed()
        if left:
            raise RuntimeError("still not found: " + ", ".join(left))
        try:
            bpy.ops.wm.save_userpref()
        except RuntimeError:
            pass                    # auto-save preferences off and not allowed here: they hold until closing

    steps.append(jobs.Step("Use the new engines", use, weight=0.1))
    return jobs.Job("Install engines", steps, on_done=on_done, log_path=os.path.join(root, "install.log"))
