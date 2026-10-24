"""Find the photos for the cameras and undistort them through Metashape's Brown model."""
import os

import bpy
import numpy as np

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".exr")


def index_images(folder):
    """{stem: path} for the images in folder; JPG wins when several share a stem."""
    out = {}
    if folder and os.path.isdir(folder):
        for f in os.listdir(folder):
            stem, ext = os.path.splitext(f)
            if ext.lower() in IMAGE_EXTS:
                if stem not in out or ext.lower() in (".jpg", ".jpeg"):
                    out[stem] = os.path.join(folder, f)
    return out


def guess_image_dir(xml_path, labels):
    """The XML's folder or a subfolder of it that holds photos named like the cameras."""
    base = os.path.dirname(xml_path)
    want = set(labels[:5])
    candidates = [base] + [os.path.join(base, d) for d in sorted(os.listdir(base))
                           if os.path.isdir(os.path.join(base, d)) and not d.endswith("_undistorted")]
    for d in candidates:
        if want & set(index_images(d)):
            return d
    return base


def undistort_image(src_path, dst_path, cal, quality=95):
    """Remap a photo through Metashape's Brown model so it becomes a pinhole image
    with the same f / cx / cy. Writes dst_path. Returns (w, h)."""
    img = bpy.data.images.load(src_path, check_existing=False)
    try:
        w, h = img.size
        s = w / cal["w"]  # scale calibration if the photo is a different size than the sensor
        f = cal["f"] * s
        cx, cy = cal.get("cx", 0.0) * s, cal.get("cy", 0.0) * s
        k1, k2, k3, k4 = (cal.get(k, 0.0) for k in ("k1", "k2", "k3", "k4"))
        p1, p2 = cal.get("p1", 0.0), cal.get("p2", 0.0)
        b1, b2 = cal.get("b1", 0.0) * s, cal.get("b2", 0.0) * s

        ch = img.channels
        px = np.empty(w * h * ch, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, ch)[::-1]  # top-down rows, like Metashape
        out = np.empty_like(px)
        black = np.zeros(ch, np.float32)
        if ch == 4:
            black[3] = 1.0

        u = np.arange(w, dtype=np.float64) + 0.5
        step = 256
        for y0 in range(0, h, step):
            v = np.arange(y0, min(h, y0 + step), dtype=np.float64) + 0.5
            U, V = np.meshgrid(u, v)
            x = (U - w * 0.5 - cx) / f
            y = (V - h * 0.5 - cy) / f
            r2 = x * x + y * y
            rad = 1 + r2 * (k1 + r2 * (k2 + r2 * (k3 + r2 * k4)))
            xd = x * rad + p1 * (r2 + 2 * x * x) + 2 * p2 * x * y
            yd = y * rad + p2 * (r2 + 2 * y * y) + 2 * p1 * x * y
            su = w * 0.5 + cx + xd * f + xd * b1 + yd * b2 - 0.5
            sv = h * 0.5 + cy + yd * f - 0.5
            xi = np.clip(np.floor(su).astype(np.int64), 0, w - 2)
            yi = np.clip(np.floor(sv).astype(np.int64), 0, h - 2)
            fx = np.clip(su - xi, 0, 1)[..., None]
            fy = np.clip(sv - yi, 0, 1)[..., None]
            val = ((px[yi, xi] * (1 - fx) + px[yi, xi + 1] * fx) * (1 - fy)
                   + (px[yi + 1, xi] * (1 - fx) + px[yi + 1, xi + 1] * fx) * fy)
            val[(su < -0.5) | (su > w - 0.5) | (sv < -0.5) | (sv > h - 0.5)] = black
            out[y0:y0 + len(v)] = val

        img.pixels.foreach_set(out[::-1].ravel())
        ext = os.path.splitext(dst_path)[1].lower()
        img.file_format = "PNG" if ext == ".png" else ("TIFF" if ext in (".tif", ".tiff") else "JPEG")
        img.filepath_raw = dst_path
        img.save(filepath=dst_path, quality=quality)
        return w, h
    finally:
        bpy.data.images.remove(img)
