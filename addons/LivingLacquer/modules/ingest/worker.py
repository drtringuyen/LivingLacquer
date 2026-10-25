"""Converter run by Blender's Python in its own process (step 3), so Blender stays responsive.

    python worker.py <tasks.json>

tasks.json: {"quality": 95, "tasks": [[src, dst], ...]}. Prints one line per photo:
"OK<TAB>dst" or "FAIL<TAB>src<TAB>error", then "DONE". Same conversion as convert_images.py:
EXIF rotation baked into the pixels, EXIF + ICC kept, JPG quality 95, no chroma subsampling.
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

ORIENTATION_TAG = 0x0112
RAW = (".nef", ".dng", ".cr2", ".cr3", ".arw")


def convert_one(src, dst, quality):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    if os.path.splitext(src)[1].lower() in RAW:
        import rawpy
        with rawpy.imread(src) as raw:
            im = Image.fromarray(raw.postprocess(use_camera_wb=True))
        exif, icc = None, None
    else:
        im = Image.open(src)
        exif = im.getexif()
        icc = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im)
        if ORIENTATION_TAG in exif:
            exif[ORIENTATION_TAG] = 1
    kw = {}
    if icc:
        kw["icc_profile"] = icc
    if exif is not None and len(exif):
        kw["exif"] = exif.tobytes()
    ext = os.path.splitext(dst)[1].lower()
    tmp = os.path.splitext(dst)[0] + ".ll_tmp" + ext
    if ext in (".jpg", ".jpeg"):
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.save(tmp, "JPEG", quality=quality, subsampling=0, optimize=True, **kw)
    elif ext == ".png":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "I;16"):
            im = im.convert("RGB")
        im.save(tmp, "PNG", **kw)
    else:
        im.save(tmp, "TIFF", compression="tiff_lzw", **kw)
    os.replace(tmp, dst)
    return dst


def main():
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    tasks, quality = job["tasks"], job.get("quality", 95)
    workers = max(1, min(len(tasks), (os.cpu_count() or 4) - 1))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(convert_one, s, d, quality): s for s, d in tasks}
        for fut in as_completed(futs):
            try:
                print("OK\t" + fut.result(), flush=True)
            except Exception as e:
                print(f"FAIL\t{futs[fut]}\t{e}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
