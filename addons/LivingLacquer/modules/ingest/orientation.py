"""Step 2 - Photo orientation: which way each photo stands, and its EXIF Orientation tag. No bpy.

A phone stores the sensor's pixels (landscape on an iPhone) plus an EXIF Orientation tag saying how to
turn them for display. Explorer / Photos follow the tag; COLMAP, Metashape and Blender use the stored
pixels, so a portrait set came out as landscape cameras with sideways photos (before 0.4.4).

The user picks how the set stands (livinglacquer.json "orientation" -> "mode"):
  STORED      the stored pixels as they are (what the pipeline did before 0.4.4)
  AUTO        as the phone showed them (the EXIF tag)
  PORTRAIT / LANDSCAPE   as the phone showed them, turned a further 90 deg where that is the other format
and can turn single photos ("turns": {stem: deg}): the tag is unreliable when the phone points straight
down or up - typical for scans - so a photo can come out upside down or sideways while the rest are
fine. turn() = degrees clockwise the stored pixels turn. It is applied to the photos themselves
(step 2, "apply": "PHOTOS") or only to the camera photos and cameras (step 4, "apply": "CAMERAS")."""
import os
import struct

from ..project import marker

MODES = ("STORED", "AUTO", "PORTRAIT", "LANDSCAPE")
ORIENTATION_TAG = 0x0112
# EXIF Orientation -> clockwise turn that stands the stored pixels up (mirrored values: their turn only)
EXIF_TURN = {1: 0, 2: 0, 3: 180, 4: 180, 5: 90, 6: 90, 7: 270, 8: 270}


def exif_orientation(path):
    """(Orientation value, file offset of its 2 bytes, byte order) of a JPEG; (1, None, None) without one."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1, None, None
            while True:
                head = f.read(4)
                if len(head) < 4 or head[0] != 0xFF or head[1] in (0xDA, 0xD9):
                    return 1, None, None
                n = struct.unpack(">H", head[2:])[0]
                start = f.tell()
                if head[1] == 0xE1:
                    seg = f.read(n - 2)
                    if seg[:6] == b"Exif\x00\x00":
                        tiff = seg[6:]
                        bo = "<" if tiff[:2] == b"II" else ">"
                        ifd = struct.unpack(bo + "I", tiff[4:8])[0]
                        count = struct.unpack(bo + "H", tiff[ifd:ifd + 2])[0]
                        for i in range(count):
                            e = ifd + 2 + 12 * i
                            tag, typ = struct.unpack(bo + "HH", tiff[e:e + 4])
                            if tag == ORIENTATION_TAG and typ == 3:
                                value = struct.unpack(bo + "H", tiff[e + 8:e + 10])[0]
                                return value, start + 6 + e + 8, bo
                        return 1, None, None
                f.seek(start + n - 2)
    except (OSError, struct.error, IndexError):
        pass
    return 1, None, None


def clear_exif_orientation(path):
    """Set the tag to 1 (as stored) in place, without touching the pixels. True when it changed."""
    value, offset, bo = exif_orientation(path)
    if offset is None or value == 1:
        return False
    with open(path, "r+b") as f:
        f.seek(offset)
        f.write(struct.pack(bo + "H", 1))
    return True


def turn_for(w, h, tag, mode, extra=0):
    """Clockwise degrees the stored w x h pixels turn for `mode`, plus the photo's own extra turn."""
    if mode == "STORED":
        base = 0
    else:
        base = EXIF_TURN.get(tag, 0)
        if mode in ("PORTRAIT", "LANDSCAPE"):
            uw, uh = (h, w) if base % 180 else (w, h)
            if uw != uh and (uh > uw) != (mode == "PORTRAIT"):
                # the tag says the other format (phone pointing down / up): a further quarter turn, the
                # way back to the pixels as stored when that is one of the two (never upside down)
                base = 0 if base in (90, 270) else base + 90
    return (base + extra) % 360


def turned_size(w, h, deg):
    return (h, w) if deg % 180 else (w, h)


def settings(root):
    """{"mode", "turns": {stem: deg}, "apply": None | "PHOTOS" | "CAMERAS", "chosen": bool}."""
    s = dict((marker.read(root) or {}).get("orientation") or {})
    s["chosen"] = s.get("mode") in MODES
    s.setdefault("mode", "STORED")
    s["turns"] = dict(s.get("turns") or {})
    s.setdefault("apply", None)
    return s


def save_settings(root, s):
    m = marker.read(root) or marker.update(root)
    m["orientation"] = {k: s[k] for k in ("mode", "turns", "apply", "photos_turned_at") if k in s}
    marker.write(root, m)


def table(root, photos):
    """{stem: {"path", "w", "h", "tag", "turn"}} for photos ({stem: path}) with the saved settings."""
    from ..metashape.photos import read_image_size
    s = settings(root)
    out = {}
    for stem, path in photos.items():
        w, h = read_image_size(path) or (0, 0)
        tag = exif_orientation(path)[0] if path.lower().endswith((".jpg", ".jpeg")) else 1
        out[stem] = {"path": path, "w": w, "h": h, "tag": tag,
                     "turn": turn_for(w, h, tag, s["mode"], s["turns"].get(stem, 0))}
    return out


def summary(t):
    """'29 portrait, 1 landscape · 3 turned 90°, 1 turned 180°' for a table()."""
    port = sum(1 for v in t.values() if turned_size(v["w"], v["h"], v["turn"])[1] > turned_size(v["w"], v["h"], v["turn"])[0])
    land = len(t) - port
    parts = [", ".join(p for p in (f"{port} portrait" if port else "", f"{land} landscape" if land else "") if p)]
    by = {}
    for v in t.values():
        if v["turn"]:
            by[v["turn"]] = by.get(v["turn"], 0) + 1
    for d, n in sorted(by.items()):
        parts.append(f"{n} turned {'90° right' if d == 90 else '90° left' if d == 270 else '180°'}")
    return " · ".join(p for p in parts if p)


def backup_dir(originals):
    """Where Apply to Photos keeps the photos as they were (inside zz.Originals, which nothing reads)."""
    return os.path.join(originals, "zz.Before_Turn")
