"""Step 3 - Convert & Sort, the plan (no bpy): which files move to zz.Originals and which get
converted to JPG. Rule (plan §3): a JPG of the photo exists -> use it; otherwise convert the
original (HEIC, NEF, PNG...). Unused originals, iPhone edits (IMG_E...) and videos go to
zz.Originals. Drive conflict copies that duplicate their original go there too."""
import hashlib
import os

from ..project import paths

JPG = (".jpg", ".jpeg")
CONVERTIBLE = (".heic", ".heif", ".png", ".tif", ".tiff", ".webp", ".bmp", ".avif") + paths.RAW_EXTS
SIDECAR = (".mov", ".mp4", ".aae", ".xmp")
RAW_ONLY = (".nef", ".dng", ".cr2", ".cr3", ".arw")      # need rawpy


def _files(folder):
    try:
        return sorted(f for f in os.listdir(folder)
                      if os.path.isfile(os.path.join(folder, f)) and f.lower() not in ("desktop.ini", "thumbs.db"))
    except OSError:
        return []


def _quick_hash(path):
    """Size + first and last 64 KB: enough to spot a Drive conflict copy without reading the whole photo."""
    h = hashlib.sha1(str(os.path.getsize(path)).encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        f.seek(max(0, os.path.getsize(path) - 65536))
        h.update(f.read())
    return h.hexdigest()


def is_iphone_edit(stem, stems):
    """IMG_E1234 next to IMG_1234."""
    return stem.upper().startswith("IMG_E") and ("IMG_" + stem[5:]).upper() in stems


def plan(source, originals, out_ext=".jpg"):
    """{'moves': [(src, dst)], 'convert': [(src, dst)], 'jpg': n, 'notes': [str], 'needs': {'PIL', 'heif', 'rawpy'}}."""
    top = _files(source)
    orig = _files(originals) if originals and os.path.isdir(originals) else []
    stems_upper = {os.path.splitext(f)[0].upper() for f in top + orig}
    have = {os.path.splitext(f)[0].upper() for f in top if f.lower().endswith(JPG)
            and not paths.is_conflict_copy(f)}
    moves, convert, notes, needs = [], [], [], set()
    dups = edits = side = 0

    def to_orig(f):
        moves.append((os.path.join(source, f), os.path.join(originals, f)))

    for f in top:
        stem, ext = os.path.splitext(f)
        ext = ext.lower()
        if paths.is_conflict_copy(f):
            base = paths.CONFLICT_RE.sub("", stem) + os.path.splitext(f)[1]
            bp = os.path.join(source, base)
            if os.path.exists(bp) and _quick_hash(bp) == _quick_hash(os.path.join(source, f)):
                to_orig(f)
                dups += 1
            continue
        if is_iphone_edit(stem, stems_upper):
            to_orig(f)
            edits += 1
        elif ext in SIDECAR:
            to_orig(f)
            side += 1
        elif ext in CONVERTIBLE:
            to_orig(f)
            if stem.upper() not in have:
                convert.append((os.path.join(originals, f), os.path.join(source, stem + out_ext)))
                have.add(stem.upper())
    for f in orig:                  # received JPGs land in zz.Originals: the engines read them from the top
        stem, ext = os.path.splitext(f)
        if ext.lower() in JPG and stem.upper() not in have and not is_iphone_edit(stem, stems_upper) \
                and not paths.is_conflict_copy(f):
            moves.append((os.path.join(originals, f), os.path.join(source, f)))
            have.add(stem.upper())
    for f in orig:
        stem, ext = os.path.splitext(f)
        if ext.lower() in CONVERTIBLE and stem.upper() not in have and not is_iphone_edit(stem, stems_upper) \
                and not paths.is_conflict_copy(f):
            convert.append((os.path.join(originals, f), os.path.join(source, stem + out_ext)))
            have.add(stem.upper())

    for src, _dst in convert:
        ext = os.path.splitext(src)[1].lower()
        needs.add("PIL")
        if ext in (".heic", ".heif", ".avif"):
            needs.add("heif")
        if ext in RAW_ONLY:
            needs.add("rawpy")
    jpg = len(have)
    if dups:
        notes.append(f"{dups} Drive conflict copy(ies) identical to the photo -> zz.Originals")
    if edits:
        notes.append(f"{edits} iPhone edit(s) (IMG_E...) -> zz.Originals")
    if side:
        notes.append(f"{side} video / sidecar file(s) -> zz.Originals")
    return {"moves": moves, "convert": convert, "jpg": jpg, "notes": notes, "needs": needs}
