"""Step 2 - Make Masks: one black-and-white mask per source photo in zz.Scan\\zz.Masks (<photo stem>_mask.png,
same size as the photo; white = the subject, black = ignored), so Metashape (Import Masks) and COLMAP
(--ImageReader.mask_path) only use the object - needed when the object was moved / flipped between photo
sets while the background stayed. The photos themselves are never changed.

AI: the U^2-Net salient-object model (176 MB, downloaded once from the rembg project's releases into
Blender's user data folder) run with onnxruntime (installed without its own numpy). COLOR: no download;
everything close to the background colour (taken from the photo border) is ignored. The masking runs in
mask_worker.py in its own process. Check Masks writes a sheet of photos with the ignored part tinted red."""
import json
import os
import sys
import tempfile
import urllib.request

import bpy

from ..linker.checks import index_photos, pick_jpg
from ..project import jobs, paths
from . import deps

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
MODEL_SIZE = 175997641          # bytes, to tell a finished download from a broken one
SHEET = "zz.check_masks.jpg"     # the Check Masks sheet, inside zz.Masks
STATUS = {"text": "", "sheet": ""}


def model_path():
    return os.path.join(bpy.utils.user_resource("DATAFILES", path="livinglacquer", create=True), "models", "u2net.onnx")


def model_ready():
    p = model_path()
    return os.path.exists(p) and os.path.getsize(p) == MODEL_SIZE


def masks_dir(root):
    found = paths.locate(root)
    return found["masks"] or os.path.join(root, paths.SCAN, paths.MASKS)


def mask_for(root, photo):
    return os.path.join(masks_dir(root), os.path.splitext(os.path.basename(photo))[0] + "_mask.png")


def photos(root):
    """{stem: photo} of the source photos the engines read (zz.Originals left out)."""
    found = paths.locate(root)
    src = index_photos(found["source"], skip=(paths.ORIGINALS,))
    return {stem: pick_jpg(v) for stem, v in sorted(src.items())}


def existing(root):
    d = masks_dir(root)
    return sorted(f for f in os.listdir(d) if f.endswith("_mask.png")) if os.path.isdir(d) else []


def _download(job):
    """Generator step: fetch the model in 1 MB pieces (progress), temp file + rename."""
    dst = model_path()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".ll_tmp"
    with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or MODEL_SIZE)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            yield got / total, f"AI model {got >> 20} / {total >> 20} MB"
    if os.path.getsize(tmp) != MODEL_SIZE:
        os.remove(tmp)
        raise RuntimeError("the AI model download is incomplete; try again")
    os.replace(tmp, dst)


def make_job(root, method="AI", grow=12, tolerance=0.12):
    """Job for Make Masks, or a string saying why it cannot run."""
    if method == "AI" and deps.missing(["ort", "PIL"]):
        return "Install the AI masking first (onnxruntime)"
    if method == "COLOR" and deps.missing(["PIL"]):
        return "Install converters first (pillow)"
    ph = photos(root)
    if not ph:
        return "No photos in zz.Source_Photos yet"
    out = masks_dir(root)
    tasks = [[p, mask_for(root, p)] for p in ph.values()]
    job_file = os.path.join(tempfile.gettempdir(), f"livinglacquer_masks_{os.getpid()}.json")
    total = len(tasks)

    def prepare(job):
        os.makedirs(out, exist_ok=True)
        with open(job_file, "w", encoding="utf-8") as f:
            json.dump({"method": method, "model": model_path(), "grow": grow, "tolerance": tolerance,
                       "tasks": tasks}, f)

    def on_line(job, line):
        if line.startswith(("OK\t", "FAIL\t")):
            job.data["n"] = job.data.get("n", 0) + 1
            job.data["fail"] = job.data.get("fail", 0) + line.startswith("FAIL")
            job.step_pct = 100.0 * job.data["n"] / max(total, 1)
            job.detail = os.path.basename(line.split("\t")[1])

    def done(job):
        if os.path.exists(job_file):
            os.remove(job_file)
        ok = job.data.get("n", 0) - job.data.get("fail", 0)
        STATUS["text"] = (f"{ok} mask(s) made ({'AI' if method == 'AI' else 'colour'})"
                          + (f", {job.data['fail']} failed" if job.data.get("fail") else "")
                          + ("" if job.state == "done" else f" · {job.state}"))

    steps = []
    if method == "AI" and not model_ready():
        steps.append(jobs.Step("Download the AI model (once)", _download, weight=20))
    steps += [jobs.Step("Prepare", prepare, weight=0.2),
              jobs.Step(f"Masks for {total} photo(s)", [sys.executable,
                                                         os.path.join(os.path.dirname(__file__), "mask_worker.py"),
                                                         job_file], env=deps.worker_env(), weight=total)]
    return jobs.Job("Make Masks", steps, on_done=done, on_line=on_line,
                    log_path=os.path.join(root, paths.SCAN, paths.OPEN, "logs", "masks.log"))


def sheet_job(root, count=12):
    """Job that writes the Check Masks sheet: up to `count` photos spread over the set, the ignored part
    tinted red. STATUS['sheet'] holds its path when done."""
    def run(job):
        import numpy as np
        from PIL import Image
        ph = list(photos(root).values())
        have = [p for p in ph if os.path.exists(mask_for(root, p))]
        if not have:
            raise RuntimeError("no masks yet: Make Masks first")
        pick = [have[round(i * (len(have) - 1) / max(count - 1, 1))] for i in range(min(count, len(have)))]
        tiles = []
        for n, p in enumerate(pick):
            yield n / len(pick), os.path.basename(p)
            im = Image.open(p).convert("RGB")
            im.thumbnail((360, 360))
            m = Image.open(mask_for(root, p)).convert("L").resize(im.size)
            a = np.asarray(im).astype(np.float32)
            keep = (np.asarray(m) > 127)[..., None]
            a = np.where(keep, a, a * 0.35 + np.array([255, 30, 30], np.float32) * 0.65)
            tiles.append((Image.fromarray(a.astype(np.uint8)), os.path.splitext(os.path.basename(p))[0]))
        cols = 4
        cw, ch = max(t.width for t, _ in tiles), max(t.height for t, _ in tiles)
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (cw + 8) + 8, rows * (ch + 8) + 8), (30, 30, 30))
        for i, (t, _name) in enumerate(tiles):
            sheet.paste(t, (8 + (i % cols) * (cw + 8), 8 + (i // cols) * (ch + 8)))
        dst = os.path.join(masks_dir(root), SHEET)
        sheet.save(dst, quality=88)
        STATUS["sheet"] = dst

    return jobs.Job("Check Masks", [jobs.Step("Check sheet", run)])


def show_sheet(context, path):
    """Open the sheet in its own small window (an Image Editor), like the Agisoft guide."""
    img = bpy.data.images.get("LivingLacquer Check Masks")
    if img is None:
        img = bpy.data.images.load(path, check_existing=False)
        img.name = "LivingLacquer Check Masks"
    else:
        img.filepath = path
        img.reload()
    wm = context.window_manager
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == "IMAGE_EDITOR" and area.spaces.active.image == img:
                area.tag_redraw()
                return True
    before = set(wm.windows[:])
    bpy.ops.screen.userpref_show("INVOKE_DEFAULT")
    new = [w for w in wm.windows if w not in before]
    if not new:
        return False
    area = new[0].screen.areas[0]
    area.ui_type = "IMAGE_EDITOR"
    area.spaces.active.image = img
    return True
