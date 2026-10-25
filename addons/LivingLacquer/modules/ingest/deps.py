"""Python packages the pipeline installs into Blender's user scripts/modules folder (on sys.path):
pillow + pillow-heif (step 3), rawpy (RAW without a JPG), segno (QR code for step 2)."""
import importlib
import importlib.util
import os
import sys

import bpy

from ..project import jobs

PIP = {"PIL": "pillow", "heif": "pillow-heif", "rawpy": "rawpy", "segno": "segno", "ort": "onnxruntime"}
IMPORT = {"PIL": "PIL", "heif": "pillow_heif", "rawpy": "rawpy", "segno": "segno", "ort": "onnxruntime"}
# installed without their dependencies: onnxruntime would otherwise bring its own numpy next to Blender's
NO_DEPS = {"ort"}
_cache = {}


def target():
    return bpy.utils.user_resource("SCRIPTS", path="modules", create=True)


def ensure_path():
    t = target()
    if t not in sys.path:
        sys.path.append(t)
        importlib.invalidate_caches()
    return t


def missing(keys):
    """The keys of PIP whose package cannot be imported (cached until the next install)."""
    ensure_path()
    out = []
    for k in keys:
        if k not in _cache:
            _cache[k] = importlib.util.find_spec(IMPORT[k]) is not None
        if not _cache[k]:
            out.append(k)
    return out


def install_job(keys, on_done=None):
    py = sys.executable
    t = ensure_path()
    pkgs = [PIP[k] for k in keys if k not in NO_DEPS]
    bare = [PIP[k] for k in keys if k in NO_DEPS]

    def done(job):
        _cache.clear()
        importlib.invalidate_caches()
        if on_done:
            on_done(job)

    steps = [jobs.Step("pip", [py, "-m", "ensurepip", "--user"], ok_codes=(0, 1))]
    if pkgs:
        steps.append(jobs.Step("pip install", [py, "-m", "pip", "install", "--upgrade", "--no-warn-script-location",
                                               "--target", t] + pkgs, weight=5))
    if bare:
        steps.append(jobs.Step("pip install (no dependencies)", [py, "-m", "pip", "install", "--upgrade", "--no-deps",
                                                                 "--no-warn-script-location", "--target", t] + bare,
                               weight=5))
    return jobs.Job("Install " + ", ".join(pkgs + bare), steps, on_done=done)


def worker_env():
    return {"PYTHONPATH": os.pathsep.join([ensure_path(), os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)}
