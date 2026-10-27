"""Step 2 - the photo preview under "Photos stand": a small thumbnail of every source photo, turned the
way it will stand (orientation.turn_for), so a photo the phone saved upside down or sideways shows
before anything is reconstructed. Thumbnails (pillow, JPEG draft decoding: fast) are cached in the temp
folder, one per photo as stored plus one per turn, and shown through a preview collection."""
import hashlib
import os
import tempfile

import bpy
import bpy.utils.previews

from ..project import jobs
from . import deps, masks, orientation

THUMB = 192             # long side in px
# what the panel draws, for STATE["root"] only: settings, the turn table, {stem: icon id}
STATE = {"root": None, "settings": None, "table": {}, "icons": {}, "show": False}
_pcoll = None


def _cache_dir():
    d = os.path.join(tempfile.gettempdir(), "livinglacquer_thumbs")
    os.makedirs(d, exist_ok=True)
    return d


def _base_thumb(path):
    """Thumbnail of the stored pixels (no EXIF turn), cached by path + size + date."""
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
    out = os.path.join(_cache_dir(), key + ".png")
    if not os.path.exists(out):
        from PIL import Image
        with Image.open(path) as im:
            im.draft("RGB", (THUMB, THUMB))
            im = im.convert("RGB")
            im.thumbnail((THUMB, THUMB))
            im.save(out)
    return key, out


def _turned_thumb(key, base, deg):
    if not deg:
        return base
    out = os.path.join(_cache_dir(), f"{key}_{deg}.png")
    if not os.path.exists(out):
        from PIL import Image
        op = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}[deg]
        with Image.open(base) as im:
            im.transpose(op).save(out)
    return out


def _icon(stem, path, deg):
    key, base = _base_thumb(path)
    name = f"{key}_{deg}"
    item = _pcoll.get(name) or _pcoll.load(name, _turned_thumb(key, base, deg), "IMAGE")
    return item.icon_id


def reload_table(root):
    """Re-read the settings and the turn of every photo (fast: headers only)."""
    STATE["root"] = root
    STATE["settings"] = orientation.settings(root)
    STATE["table"] = orientation.table(root, masks.photos(root))


def update_icons(root, stems=None):
    """Icons for stems (all when None) whose thumbnail is cached already; returns the stems still to make."""
    reload_table(root)
    left = []
    for stem, v in STATE["table"].items():
        if stems is not None and stem not in stems:
            continue
        try:
            st = os.stat(v["path"])
            key = hashlib.sha1(f"{v['path']}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
        except OSError:
            continue
        if os.path.exists(os.path.join(_cache_dir(), key + ".png")):
            STATE["icons"][stem] = _icon(stem, v["path"], v["turn"])
        else:
            left.append(stem)
    for stem in list(STATE["icons"]):
        if stem not in STATE["table"]:
            del STATE["icons"][stem]
    return left


def job(root):
    """Job that makes the missing thumbnails and shows the preview."""
    def run(job_):
        left = update_icons(root)
        for n, stem in enumerate(left):
            yield n / max(len(left), 1), stem
            v = STATE["table"][stem]
            try:
                STATE["icons"][stem] = _icon(stem, v["path"], v["turn"])
            except Exception as e:
                job_.log(f"{stem}: {e}")
        STATE["show"] = True

    return jobs.Job("Photo preview", [jobs.Step("Thumbnails", run)])


def start(root):
    """Show the preview (making thumbnails in a job when some are missing). A string when it cannot."""
    if deps.missing(["PIL"]):
        return "Install converters first (pillow)"
    deps.ensure_path()
    if not update_icons(root):
        STATE["show"] = True
        return None
    jobs.run_or_start(job(root))
    return None


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
    STATE.update(root=None, settings=None, table={}, icons={}, show=False)
