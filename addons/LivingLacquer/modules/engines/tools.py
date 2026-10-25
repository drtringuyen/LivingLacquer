"""Where the engine programs and the local work folder are (add-on preferences, with defaults)."""
import os

import bpy

from ..project import marker, paths, prefs

OPENMVS = ("InterfaceCOLMAP", "InterfaceMetashape", "DensifyPointCloud", "ReconstructMesh", "RefineMesh",
           "TextureMesh")


def _p(name):
    """Preference value; its default when the add-on is not enabled through the preferences (tests)."""
    p = prefs.get()
    if p is None:
        return prefs.LIVINGLACQUER_AP_Prefs.__annotations__[name].keywords.get("default", "")
    return bpy.path.abspath(getattr(p, name)) if getattr(p, name) else ""


def colmap_exe():
    d = _p("colmap_dir")
    for c in (os.path.join(d, "bin", "colmap.exe"), os.path.join(d, "colmap.exe")):
        if os.path.isfile(c):
            return c
    return ""


def colmap_env():
    """COLMAP.bat sets these: its bin on PATH and the Qt plugins."""
    exe = colmap_exe()
    if not exe:
        return {}
    bin_ = os.path.dirname(exe)
    root = os.path.dirname(bin_)
    return {"PATH": bin_ + os.pathsep + os.environ.get("PATH", ""),
            "QT_PLUGIN_PATH": os.path.join(root, "plugins")}


def openmvs(tool):
    exe = os.path.join(_p("openmvs_dir"), tool + ".exe")
    return exe if os.path.isfile(exe) else ""


def metashape_exe():
    exe = _p("metashape_exe")
    return exe if os.path.isfile(exe) else ""


def missing(engine):
    """Names of the programs the engine needs that are not found."""
    out = []
    if engine == "OPENSOURCE" and not colmap_exe():
        out.append("COLMAP")
    if engine in ("OPENSOURCE", "HYBRID"):
        out += [t for t in OPENMVS if t != ("InterfaceMetashape" if engine == "OPENSOURCE" else "InterfaceCOLMAP")
                and not openmvs(t)]
    if engine in ("AGISOFT", "HYBRID") and not metashape_exe():
        out.append("Metashape")
    return out


def work_dir(root, engine):
    """Local folder for one object's engine run: <work root>\\<object folder>_<id>\\<engine>."""
    base = _p("work_root") or os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LivingLacquer")
    m = marker.read(root) or {}
    tag = f"{os.path.basename(root)}_{(m.get('id') or 'noid')[:8]}"
    d = os.path.join(base, "work", paths.sanitize(tag) or "object", engine.lower())
    os.makedirs(d, exist_ok=True)
    return d
