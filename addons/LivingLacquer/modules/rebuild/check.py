"""Check Textures / Fix, as MultiCamProject's Check Project: every rebuilt object's BAo_ / BAp_ / ALB_ / NOR_
belongs in the bake folder, a Loaded ALB_ / NOR_ in 02.Overrides. Check only reads: which image points
somewhere else, and which copies of the same file name lie in other folders of the object (a second 01.Bake or
02.Overrides). Fix keeps the file the image uses (a copy wins only when the image has none), puts it in
its place, relinks the image, sends the other copies to the Recycle Bin and removes folders left empty.
A locked object is left alone."""
import os
import shutil

import bpy

from ..project import state
from . import bake, core

SKIP_DIRS = {"zz.Scan", "Export", ".git"}       # photos and scan files; the export's own copies
REPORT = {"blend": None, "moves": [], "strays": [], "missing": [], "checked": 0}


def _n(path):
    return os.path.normcase(os.path.normpath(path))


def rebuilt_objects():
    return [o for o in bpy.data.objects if o.type == "MESH" and o.get(core.REBUILD_KEY) and not core.locked(o)]


def _scan(root):
    """{lower file name: [paths]} of the PNGs under the object folder, the scan's folders left out."""
    found = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith(".png"):
                found.setdefault(f.lower(), []).append(os.path.join(folder, f))
    return found


def check(rb):
    """Fill REPORT: moves [(image name, from, to)], strays [path], missing [image name]."""
    root = state.get()["root"]
    found = _scan(root) if root else {}
    moves, strays, missing = [], [], []
    objs = rebuilt_objects()
    for ob in objs:
        for kind, prefix in core.KIND_PREFIX.items():
            name = f"{prefix}{ob.name}"
            img = bpy.data.images.get(name)
            copies = found.get(f"{name}.png".lower(), [])
            bake_file = core.bake_path(rb, prefix, ob)
            over = core.override_path(rb, prefix, ob)
            load = kind in {"ALB", "NOR"} and getattr(rb, "alb_mode" if kind == "ALB" else "nor_mode") == "LOAD"
            want = over if load else bake_file
            legit = {_n(bake_file)} | ({_n(over)} if kind in {"ALB", "NOR"} else set())
            used = core.image_file(img)
            if img is None and not copies:
                continue
            source = used if used and os.path.isfile(used) else next(
                (c for c in copies if _n(c) == _n(want)), copies[0] if copies else "")
            if not source:
                missing.append(name)
                continue
            if _n(source) != _n(want) or (used and _n(used) != _n(want)):
                moves.append((name, source, want))
            strays += [c for c in copies if _n(c) not in legit and _n(c) != _n(source)]
            if _n(source) not in legit:
                strays.append(source)
    REPORT.update(blend=bpy.data.filepath, moves=moves, strays=sorted(set(strays)), missing=missing, checked=len(objs))
    return REPORT


def to_recycle_bin(paths):
    """Move files to the Recycle Bin (Windows; a wrong clean-up can be undone there), elsewhere delete them.
    Returns the paths that are gone."""
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        return []
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 0x10, 0x40, 0x400
        files = "\0".join(os.path.abspath(p) for p in paths) + "\0\0"
        op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=files,
                             fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    else:
        for p in paths:
            os.remove(p)
    return [p for p in paths if not os.path.exists(p)]


def fix(rb):
    """Do what the last check found. Returns (files placed, files sent to the Recycle Bin, folders removed)."""
    placed = 0
    for name, source, want in REPORT["moves"]:
        os.makedirs(os.path.dirname(want), exist_ok=True)
        if _n(source) != _n(want):
            shutil.copy2(source, want)
            placed += 1
        bake.load(name, want, non_color=name.startswith(core.NORMAL))
    for ob in rebuilt_objects():
        core.link_images(ob)
    wanted = {_n(m[2]) for m in REPORT["moves"]}
    strays = [p for p in REPORT["strays"] if _n(p) not in wanted]
    gone = to_recycle_bin(strays)
    removed = 0
    for folder in {os.path.dirname(p) for p in gone}:
        try:
            if not os.listdir(folder):
                os.rmdir(folder)
                removed += 1
        except OSError:
            pass
    check(rb)
    return placed, len(gone), removed
