"""Step 4 with Agisoft Metashape Standard (no Python there): Blender opens Metashape with the project,
puts the paths on the clipboard, shows the guide, and watches for the exports. The exports go straight
to the published names, so Build Scene can use them as soon as they are complete."""
import os
import subprocess
import time

from ..project import paths

# guide lines: (text, key of a path to copy or None)
GUIDE = {
    "AGISOFT": [
        ("1. Workflow › Add Folder: paste the photo folder", "source"),
        ("2. File › Save As: paste the project path", "psx"),
        ("3. Workflow › Align Photos (Accuracy High)", None),
        ("   check: all cameras aligned, only one component", None),
        ("4. Workflow › Build Model (from depth maps) › Build Texture", None),
        ("5. File › Export › Export Cameras (Agisoft XML):", "xml"),
        ("6. File › Export › Export Model (Alembic .abc):", "model"),
        ("7. File › Export › Export Texture (JPEG):", "texture"),
        ("Moved photos? right-click Chunk › Change Path › the photo folder", None),
    ],
    "HYBRID": [
        ("1. Workflow › Add Folder: paste the photo folder", "source"),
        ("2. File › Save As: paste the project path", "psx"),
        ("3. Workflow › Align Photos (High), check the alignment", None),
        ("4. File › Export › Export Cameras (Agisoft XML):", "xml"),
        ("Blender then builds mesh + texture with OpenMVS by itself", None),
    ],
}


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
