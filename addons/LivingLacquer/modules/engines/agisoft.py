"""Step 4 with Agisoft Metashape Standard (no Python there): Blender opens Metashape with the project,
puts the paths on the clipboard, shows the guide, and watches for the exports. The exports go straight
to the published names, so Build Scene can use them as soon as they are complete."""
import os
import subprocess
import time

from ..project import paths

# guide lines: (text, key of a path to copy or None, what the line is about: see guide_status)
_PATH = ("0. Photos moved: in Metashape's Workspace pane right-click the photos › Change Path… › "
         "pick the photo folder", "source", "path")
GUIDE = {
    "AGISOFT": [
        _PATH,
        ("1. Workflow › Add Folder: paste the photo folder", "source", "folder"),
        ("1b. File › Import › Import Masks…: Method From File, Operation Replacement, Filename template: paste "
         "the mask template, Apply to All cameras", "masks", "masks"),
        ("2. File › Save As: paste the project path", "psx", "save"),
        ("3. Workflow › Align Photos (Accuracy High)", None, "align"),
        ("   check: all cameras aligned, only one component", None, "align"),
        ("4. Workflow › Build Model (from depth maps) › Build Texture", None, "build"),
        ("5. File › Export › Export Cameras (Agisoft XML):", "xml", "xml"),
        ("6. File › Export › Export Model (Alembic .abc):", "model", "model"),
        ("7. File › Export › Export Texture (JPEG):", "texture", "texture"),
    ],
    "HYBRID": [
        _PATH,
        ("1. Workflow › Add Folder: paste the photo folder", "source", "folder"),
        ("1b. File › Import › Import Masks…: Method From File, Operation Replacement, Filename template: paste "
         "the mask template, Apply to All cameras", "masks", "masks"),
        ("2. File › Save As: paste the project path", "psx", "save"),
        ("3. Workflow › Align Photos (High), check the alignment", None, "align"),
        ("4. File › Export › Export Cameras (Agisoft XML):", "xml", "xml"),
    ],
}
_project_cache = {}     # frame.zip path -> (its mtime, parsed state)


def project_state(root):
    """What the Metashape project already holds, read from its own files (no Metashape needed):
    {'psx', 'open' (lock file), 'photos', 'missing' (photos not where Metashape looks), 'looks_in',
     'aligned', 'model'}. Reads the small doc.xml inside .files/0/0/frame.zip and .files/0/chunk.zip."""
    import re
    import zipfile
    psx = targets(root)["psx"]
    st = {"psx": os.path.exists(psx), "open": False, "photos": 0, "missing": 0, "looks_in": "", "aligned": 0,
          "model": False, "masks": False}
    files = os.path.splitext(psx)[0] + ".files"
    if not (st["psx"] and os.path.isdir(files)):
        return st
    st["open"] = os.path.exists(os.path.join(files, "lock"))
    frame = os.path.join(files, "0", "0", "frame.zip")
    chunk = os.path.join(files, "0", "chunk.zip")
    key = (os.path.getmtime(frame) if os.path.exists(frame) else 0,
           os.path.getmtime(chunk) if os.path.exists(chunk) else 0)
    hit = _project_cache.get(files)
    if hit and hit[0] == key:
        st.update(hit[1])
        return st
    parsed = {}
    try:
        with zipfile.ZipFile(frame) as z:
            doc = z.read("doc.xml").decode("utf-8", "replace")
        photos = re.findall(r'<photo path="([^"]+)"', doc)
        base = os.path.dirname(frame)
        resolved = [os.path.normpath(os.path.join(base, p)) if not os.path.isabs(p) else p for p in photos]
        missing = [p for p in resolved if not os.path.exists(p)]
        parsed.update(photos=len(photos), missing=len(missing), model="<model" in doc, masks="<mask" in doc
                      or os.path.isdir(os.path.join(base, "masks")),
                      looks_in=os.path.dirname(missing[0]) if missing else "")
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    try:
        with zipfile.ZipFile(chunk) as z:
            doc = z.read("doc.xml").decode("utf-8", "replace")
        parsed["aligned"] = doc.count("<transform>")
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    _project_cache[files] = (key, parsed)
    st.update(parsed)
    return st


def guide_status(root, engine):
    """[(text, key, what, done)] for the guide lines, from the project files and the exports."""
    t = targets(root)
    p = project_state(root)
    # files another engine published (Open Source / Hybrid) sit under the same names: they only count as
    # Agisoft exports when written after that publish
    from datetime import datetime
    from ..project import marker
    pub = (marker.read(root) or {}).get("published") or {}
    since = 0.0
    if pub.get("engine") not in (None, "", "AGISOFT", engine):
        try:
            since = datetime.fromisoformat(pub.get("date", "")).timestamp() + 5
        except ValueError:
            since = 0.0

    def exported(k):
        cands = [t[k]] + ([os.path.splitext(t[k])[0] + e for e in paths.MODEL_EXTS] if k == "model" else [])
        return any(os.path.exists(c) and os.path.getmtime(c) > since for c in cands)

    done = {
        "path": not p["missing"],                       # nothing to fix: the line stays hidden
        "folder": p["photos"] > 0,
        "save": p["psx"],
        "align": p["aligned"] > 0,                      # from the Metashape project itself
        "build": p["model"],
        "masks": p["masks"],
        "xml": exported("xml"), "model": exported("model"), "texture": exported("texture"),
    }
    has_masks = bool(os.path.isdir(os.path.dirname(t["masks"])) and any(
        f.endswith("_mask.png") for f in os.listdir(os.path.dirname(t["masks"]))))
    out = []
    for text, key, what in GUIDE[engine]:
        if what == "masks" and not has_masks:
            continue                                    # no masks made: no import line
        if what == "align" and has_masks and text.startswith("3."):
            text += " - Apply masks to: Key points"
        out.append((text, key, what, done[what]))
    return out, p


def targets(root):
    """The paths the guide hands out: photo folder, project, and the export names (published)."""
    found = paths.locate(root)
    obj = found["object"]
    scan = os.path.join(root, paths.SCAN)
    return {
        "source": found["source"] or os.path.join(scan, paths.SOURCE),
        "psx": found["psx"] or os.path.join(scan, paths.AGISOFT, f"AGS_{obj}.psx"),
        "xml": os.path.join(found["cam"] or os.path.join(scan, paths.CAM), f"CAM_{obj}.xml"),
        "model": os.path.join(found["geometry"] or os.path.join(scan, paths.GEOMETRY), f"OBJ_{obj}.abc"),
        "texture": os.path.join(found["geometry"] or os.path.join(scan, paths.GEOMETRY), f"OBJ_{obj}.jpg"),
        # Metashape's Import Masks "Filename template": folder + {filename} (the photo name without extension)
        "masks": os.path.join(found["masks"] or os.path.join(scan, paths.MASKS), "{filename}_mask.png"),
    }


def launch(exe, root):
    """Open Metashape, with the project when it exists."""
    psx = targets(root)["psx"]
    args = [exe] + ([psx] if os.path.exists(psx) else [])
    subprocess.Popen(args, close_fds=True)


class Watcher:
    """Exports newer than `since` whose size stayed the same for two looks -> complete."""

    def __init__(self, root, engine, since=None):
        self.root, self.engine = root, engine
        self.since = time.time() if since is None else since
        self.sizes = {}

    def wanted(self):
        return ["xml"] if self.engine == "HYBRID" else ["xml", "model", "texture"]

    def check(self):
        """{key: 'missing' | 'writing' | 'ready'}."""
        t = targets(self.root)
        out = {}
        for key in self.wanted():
            p = t[key]
            if key == "model" and not os.path.exists(p):         # any model format counts
                for ext in paths.MODEL_EXTS:
                    alt = os.path.splitext(p)[0] + ext
                    if os.path.exists(alt):
                        p = alt
                        break
            if not os.path.exists(p) or os.path.getmtime(p) < self.since - 2:
                out[key] = "missing"
                continue
            size = os.path.getsize(p)
            out[key] = "ready" if self.sizes.get(key) == size and size > 0 else "writing"
            self.sizes[key] = size
        return out
