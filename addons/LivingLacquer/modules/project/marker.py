"""livinglacquer.json: the project marker in the object folder (plan §7). No bpy here."""
import json
import os
import uuid
from datetime import datetime

from . import paths

MARKER = "livinglacquer.json"
VERSION = 1


def marker_path(root):
    return os.path.join(root, MARKER)


def read(root):
    """The marker as a dict, or None when missing / unreadable."""
    try:
        with open(marker_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write(root, data):
    """Write through a temp file + rename, so Drive never syncs a half-written marker."""
    path = marker_path(root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def update(root, engine=None):
    """Create the marker or refresh its paths from what is on disk now. Keeps id, published,
    calibration_fingerprint and checked_out_by. Returns the marker."""
    data = read(root) or {
        "version": VERSION,
        "id": uuid.uuid4().hex,
        "created": datetime.now().isoformat(timespec="seconds"),
        "calibration_fingerprint": "",
        "published": {},
        "checked_out_by": "",
    }
    found = paths.locate(root)
    data["object"] = found["object"]
    data["account"] = paths.drive_account(root)
    if engine:
        data["engine"] = engine
    data["paths"] = {"blend": os.path.basename(root) + ".blend"}
    for key in ("source", "cam", "geometry", "agisoft", "open", "xml", "model", "psx"):
        if found.get(key):
            data["paths"][key] = paths.rel(root, found[key])
    data["paths"]["textures"] = [paths.rel(root, t) for t in found["textures"]]
    data["updated"] = datetime.now().isoformat(timespec="seconds")
    write(root, data)
    return data
