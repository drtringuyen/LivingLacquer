"""Object folder rules (docs/PLAN_scan_pipeline.md §2): names, the folder tree, what to ignore,
and where the scan files of an object currently are. No bpy here."""
import os
import re
import unicodedata

SCAN = "zz.Scan"
SOURCE = "zz.Source_Photos"
ORIGINALS = "zz.Originals"
CAM = "01.CAM_Photos"
GEOMETRY = "02.Geometry"
AGISOFT = "zz.Agisoft"
OPEN = "zz.COLMAP_OMVS"
MASKS = "zz.Masks"         # one <photo stem>_mask.png per photo: white = subject, black = ignored

TREE = [
    SCAN,
    f"{SCAN}/{SOURCE}",
    f"{SCAN}/{SOURCE}/{ORIGINALS}",
    f"{SCAN}/{CAM}",
    f"{SCAN}/{GEOMETRY}",
    f"{SCAN}/{AGISOFT}",
    f"{SCAN}/{MASKS}",
    f"{SCAN}/{OPEN}/colmap",
    f"{SCAN}/{OPEN}/openmvs",
    f"{SCAN}/{OPEN}/logs",
]

# old folder names still accepted when reading; Check Links offers to rename them
VARIANTS = {
    SCAN: ["zz.scan"],
    SOURCE: ["00.SourcePhotos", "00.Source_Photos"],
    AGISOFT: ["01.Agisoft"],
}

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
RAW_EXTS = (".heic", ".heif", ".nef", ".dng", ".cr2", ".cr3", ".arw")
MODEL_EXTS = (".abc", ".fbx", ".obj")

OBJ_RE = re.compile(r"^(\d{2,})\.(.+)$")
CONFLICT_RE = re.compile(r" \(\d+\)$")          # Drive conflict copy: "name (1).ext"
_IGNORED = {"desktop.ini", "thumbs.db", "lock", ".lock"}


def is_ignored(name):
    """desktop.ini, Thumbs.db, lock files and Drive conflict copies."""
    low = name.lower()
    return low in _IGNORED or low.endswith(".lock") or is_conflict_copy(name)


def is_conflict_copy(name):
    return bool(CONFLICT_RE.search(os.path.splitext(name)[0]))


def object_root(blend_path):
    """The object folder when the .blend is saved as NN.<Object>.blend inside NN.<Object>\\, else ''."""
    if not blend_path:
        return ""
    root = os.path.dirname(os.path.abspath(blend_path))
    name = os.path.basename(root)
    stem = os.path.splitext(os.path.basename(blend_path))[0]
    return root if OBJ_RE.match(name) and stem == name else ""


def scan_name(obj):
    """The scan mesh's object in the .blend (its files stay OBJ_<Object>.*)."""
    return f"ORG_{obj}"


def object_name(root):
    """'01.BatTrang_Teapot' -> 'BatTrang_Teapot'."""
    m = OBJ_RE.match(os.path.basename(root))
    return m.group(2) if m else os.path.basename(root)


def sanitize(name):
    """'Bát Tràng teapot' -> 'Bat_Trang_teapot': ASCII letters, digits, '_' and '-' only,
    so the command-line tools never trip over the path."""
    name = name.replace("đ", "d").replace("Đ", "D")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9\-]+", "_", name).strip("_")


def next_number(parent):
    """Next free NN in the parent folder, two digits."""
    used = [int(m.group(1)) for d in _listdir(parent) if (m := OBJ_RE.match(d))
            and os.path.isdir(os.path.join(parent, d))]
    return "%02d" % (max(used) + 1 if used else 0)


def create_tree(root):
    """Make every folder of §2 that is missing. Returns the ones created (relative)."""
    made = []
    for rel in TREE:
        p = os.path.join(root, *rel.split("/"))
        if not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)
            made.append(rel)
    return made


def drive_account(path):
    """The Google Drive folder the path sits in ('My Drive', 'My Drive (tri@...)', 'Shared drives'),
    or '' for a normal folder."""
    parts = os.path.abspath(path).replace("\\", "/").split("/")
    top = parts[1] if len(parts) > 1 else ""
    return top if top.startswith(("My Drive", "Shared drives", "Other computers")) else ""


def rel(root, path):
    """Path relative to the object folder with forward slashes (the marker's form)."""
    return os.path.relpath(path, root).replace("\\", "/")


def _listdir(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def find_child(parent, canonical):
    """(path, actual name) of the folder named canonical or one of its old variants; (None, None)."""
    names = [d for d in _listdir(parent) if os.path.isdir(os.path.join(parent, d))]
    for d in names:
        if d == canonical:
            return os.path.join(parent, d), d
    wanted = [canonical.lower()] + [v.lower() for v in VARIANTS.get(canonical, [])]
    for w in wanted:
        for d in names:
            if d.lower() == w:
                return os.path.join(parent, d), d
    return None, None


def locate(root):
    """Where the scan files of the object are now. Absolute paths, None when missing, plus
    'renames': [(path, canonical name)] for folders that still have an old name."""
    obj = object_name(root)
    out = {"root": root, "object": obj, "renames": []}

    scan, name = find_child(root, SCAN)
    if scan and name != SCAN:
        out["renames"].append((scan, SCAN))
    out["scan"] = scan
    for key, canon in (("source", SOURCE), ("cam", CAM), ("geometry", GEOMETRY),
                       ("agisoft", AGISOFT), ("open", OPEN), ("masks", MASKS)):
        p, name = find_child(scan, canon) if scan else (None, None)
        if p and name != canon:
            out["renames"].append((p, canon))
        out[key] = p
    out["originals"] = find_child(out["source"], ORIGINALS)[0] if out["source"] else None

    out["xml"] = (_pick(out["cam"], f"CAM_{obj}", (".xml",))
                  or _pick(out["agisoft"], f"CAM_{obj}", (".xml",)))
    out["model"] = _pick(out["geometry"], f"OBJ_{obj}", MODEL_EXTS)
    out["psx"] = _pick(out["agisoft"], f"AGS_{obj}", (".psx",))
    out["textures"] = sorted(
        os.path.join(out["geometry"], f) for f in _listdir(out["geometry"] or "")
        if f.lower().startswith(f"obj_{obj}".lower()) and f.lower().endswith(PHOTO_EXTS)
        and not is_ignored(f)) if out["geometry"] else []
    return out


def _pick(folder, stem, exts):
    """folder/stem.<ext> for the first ext that exists, else the only file with one of exts."""
    if not folder:
        return None
    files = [f for f in _listdir(folder) if not is_ignored(f)]
    for ext in exts:
        for f in files:
            if f.lower() == (stem + ext).lower():
                return os.path.join(folder, f)
    any_ = [f for f in files if f.lower().endswith(exts)]
    return os.path.join(folder, any_[0]) if len(any_) == 1 else None
