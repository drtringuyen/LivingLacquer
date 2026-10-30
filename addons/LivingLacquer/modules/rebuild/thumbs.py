"""Photo thumbnails for step 5's lists, read the way the File Browser does: from the file through the OS
thumbnail cache, never the 12-45 MP photo itself into memory. Each photo gets a second preview with the
whole picture fitted into a square (transparent around it), so a portrait photo shows whole.

    icon(img)   the thumbnail's icon id, 0 while it is not read yet (the panel draws again later)"""
import os

import bpy

SIZE = 128          # the fitted square, in pixels
_files = None       # the files' thumbnails as Blender reads them
_made = None        # the fitted squares
_textures = {}      # image name -> GPUTexture, for the viewport's photo panel


def _collections():
    global _files, _made
    if _files is None:
        import bpy.utils.previews
        _files, _made = bpy.utils.previews.new(), bpy.utils.previews.new()
    return _files, _made


def _fit(key, src):
    import numpy as np
    w, h = src.image_size           # reading it loads the file's thumbnail
    if not w or not h:
        return None
    px = np.empty(w * h * 4, np.float32)
    src.image_pixels_float.foreach_get(px)
    px = px.reshape(h, w, 4)
    s = SIZE / max(w, h)
    fw, fh = max(1, round(w * s)), max(1, round(h * s))
    ys = np.minimum((np.arange(fh) + 0.5) * h / fh, h - 1).astype(int)
    xs = np.minimum((np.arange(fw) + 0.5) * w / fw, w - 1).astype(int)
    sq = np.zeros((SIZE, SIZE, 4), np.float32)
    y0, x0 = (SIZE - fh) // 2, (SIZE - fw) // 2
    sq[y0:y0 + fh, x0:x0 + fw] = px[ys][:, xs]
    p = _collections()[1].new(key)
    p.icon_size = p.image_size = (SIZE, SIZE)
    p.icon_pixels_float.foreach_set(sq.ravel())
    p.image_pixels_float.foreach_set(sq.ravel())
    return p


def icon(img):
    if img is None or img.source != "FILE" or not img.filepath:
        return 0
    try:
        path = os.path.normpath(bpy.path.abspath(img.filepath, library=img.library))
        mtime = os.path.getmtime(path)
        key = f"{os.path.normcase(path)}|{mtime}"
        files, made = _collections()
        p = made.get(key)
        if p is None:
            src = files.get(key) or files.load(key, path, "IMAGE")
            p = _fit(key, src)
            if p is None:
                return 0
        return p.icon_id
    except (OSError, ReferenceError, RuntimeError, KeyError, ValueError):
        return 0


def texture(img, budget):
    """A GPUTexture of the fitted thumbnail, None while it is not read yet. budget ([n]): how many new
    ones may still be read this redraw. Found by image name, so a redraw does no path work."""
    if img is None:
        return None
    tex = _textures.get(img.name)
    if tex is not None or budget[0] <= 0:
        return tex
    if img.source != "FILE" or not img.filepath:
        return None
    budget[0] -= 1
    i = icon(img)
    p = next((v for v in _made.values() if v.icon_id == i), None) if i else None
    if p is None:
        return None
    import gpu
    import numpy as np
    w, h = p.image_size
    px = np.empty(w * h * 4, np.float32)
    p.image_pixels_float.foreach_get(px)
    buf = gpu.types.Buffer("FLOAT", px.size, px)
    tex = _textures[img.name] = gpu.types.GPUTexture((w, h), format="RGBA8", data=buf)  # 1/4 of RGBA32F's memory
    return tex


def forget():
    """The next redraw reads the thumbnails again (the panel opened: photos may have been turned)."""
    _textures.clear()


def clear():
    global _files, _made
    _textures.clear()
    if _files is not None:
        import bpy.utils.previews
        bpy.utils.previews.remove(_files)
        bpy.utils.previews.remove(_made)
        _files = _made = None
