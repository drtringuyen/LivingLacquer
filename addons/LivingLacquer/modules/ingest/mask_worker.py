"""Mask maker run by Blender's Python in its own process (step 2, Make Masks), so Blender stays responsive.

    python mask_worker.py <job.json>

job.json: {"method": "AI" | "COLOR", "model": path to u2net.onnx, "grow": px, "tolerance": 0-1,
           "tasks": [[photo, mask], ...]}
Writes one mask per photo: same size, white = the subject (used), black = ignored. Metashape (Import
Masks, From File) and COLMAP (--ImageReader.mask_path) read black as "ignore". Prints "OK<TAB>mask" or
"FAIL<TAB>photo<TAB>error" per photo, then "DONE".

AI: the U^2-Net salient-object model (the one rembg uses), run with onnxruntime at 320 x 320.
COLOR: the background colour is taken from the photo's border; everything close to it is ignored.
Both: keep the shape nearest the centre, fill its holes, grow the edge a few pixels."""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

WORK = 640              # clean-up resolution (long side)


def _ai_session(model):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 2)     # cores left for Blender
    return ort.InferenceSession(model, sess_options=opts, providers=["CPUExecutionProvider"])


def ai_probability(session, im):
    """0-1 subject probability at im's size (rembg's u2net pre / post-processing)."""
    small = im.convert("RGB").resize((320, 320), Image.LANCZOS)
    x = np.asarray(small, np.float32)
    x = x / max(float(x.max()), 1e-6)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    pred = session.run(None, {session.get_inputs()[0].name: x})[0][0, 0]
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    return np.asarray(Image.fromarray((pred * 255).astype(np.uint8)).resize(im.size, Image.LANCZOS),
                      np.float32) / 255.0


def color_probability(im, tolerance):
    """1 where the pixel is far from the background colour (median of a 4 % border)."""
    rgb = np.asarray(im.convert("RGB"), np.float32) / 255.0
    h, w, _ = rgb.shape
    b = max(2, int(min(h, w) * 0.04))
    border = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                             rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(-1)) / np.sqrt(3)
    return np.clip((dist - tolerance) / max(tolerance, 1e-3) + 0.5, 0, 1)


def clean(prob, size, grow):
    """Threshold, keep the shape nearest the centre, fill its holes, grow its edge by `grow` px (done at
    the small working size), and return the mask at `size`. Nothing found: everything is kept (safe)."""
    w, h = size
    s = WORK / max(w, h)
    sw, sh = max(1, int(w * s)), max(1, int(h * s))
    small = np.asarray(Image.fromarray((prob * 255).astype(np.uint8)).resize((sw, sh), Image.BILINEAR)) > 127
    if not small.any():
        return Image.new("L", size, 255)
    ys, xs = np.nonzero(small)
    i = int(np.argmin((ys - sh / 2) ** 2 + (xs - sw / 2) ** 2))
    img = Image.fromarray((small * 255).astype(np.uint8)).copy()     # copy: an array-backed image is read-only
    ImageDraw.floodfill(img, (int(xs[i]), int(ys[i])), 128)          # the shape nearest the centre
    keep = np.asarray(img) == 128
    pad = Image.fromarray(np.pad(np.where(keep, 0, 255).astype(np.uint8), 1, constant_values=255)).copy()
    ImageDraw.floodfill(pad, (0, 0), 128)                             # outside = reachable from the border
    keep = np.asarray(pad)[1:-1, 1:-1] != 128                         # so holes inside the shape are filled
    m = Image.fromarray((keep * 255).astype(np.uint8))
    g = int(round(grow * s))
    if g > 0:
        m = m.filter(ImageFilter.MaxFilter(2 * g + 1))
    return m.resize((w, h), Image.BILINEAR).point(lambda v: 255 if v > 127 else 0)


def make_mask(session, photo, dst, method, grow, tolerance):
    im = Image.open(photo)                    # the pixels as stored, as Metashape / COLMAP read them
    prob = ai_probability(session, im) if method == "AI" else color_probability(im, tolerance)
    m = clean(prob, im.size, grow)
    tmp = os.path.splitext(dst)[0] + ".ll_tmp.png"
    m.save(tmp)
    os.replace(tmp, dst)
    return dst


def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    method = job.get("method", "AI")
    session = _ai_session(job["model"]) if method == "AI" else None
    for photo, dst in job["tasks"]:
        try:
            print("OK\t" + make_mask(session, photo, dst, method, job.get("grow", 8), job.get("tolerance", 0.12)),
                  flush=True)
        except Exception as e:
            print(f"FAIL\t{photo}\t{e}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
