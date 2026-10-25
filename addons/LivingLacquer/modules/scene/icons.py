"""A standing-person icon (Blender's own person icons run or show a bust): the size-reference
silhouette, as a small PNG written when the add-on loads (previews for the sidebar; no image file in
the repo) and as the encoded polygon a 2D gizmo button can draw."""
import os
import struct
import tempfile
import zlib

import bpy.utils.previews
import numpy as np

from . import human

SIZE = 64
_previews = None


def _outline01():
    """The person outline scaled into 0-1 (x centred), y up."""
    pts = np.array(human.PERSON, dtype=float)
    pts[:, 0] = pts[:, 0] / human.HEIGHT_M + 0.5
    pts[:, 1] = pts[:, 1] / human.HEIGHT_M
    return pts


def person_tris01():
    """The outline as a triangle list (x, y in 0-1) for a gizmo's custom shape."""
    pts = _outline01()
    return [tuple(pts[i]) for tri in human.tris(human.PERSON) for i in tri]


def _inside(px, py, poly):
    """Even-odd point-in-polygon for arrays of points."""
    inside = np.zeros(px.shape, bool)
    x0, y0 = poly[-1]
    for x1, y1 in poly:
        cross = ((y1 > py) != (y0 > py)) & (px < (x0 - x1) * (py - y1) / ((y0 - y1) or 1e-12) + x1)
        inside ^= cross
        x0, y0 = x1, y1
    return inside


def _png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _make_png(path):
    """White standing person on transparent, 4x supersampled for smooth edges."""
    poly = _outline01() * 0.9 + np.array([0.05, 0.05])
    ss = 4
    n = SIZE * ss
    c = (np.arange(n) + 0.5) / n
    px, py = np.meshgrid(c, 1.0 - c)                     # PNG rows go top to bottom
    alpha = _inside(px, py, poly).reshape(SIZE, ss, SIZE, ss).mean(axis=(1, 3))
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
    rgba[..., :3] = 230
    rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
    _png(path, rgba)


def person_icon():
    """icon_value of the standing person (0 when it could not be made)."""
    return _previews["person"].icon_id if _previews and "person" in _previews else 0


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    path = os.path.join(tempfile.gettempdir(), "livinglacquer_person.png")
    try:
        _make_png(path)
        _previews.load("person", path, "IMAGE")
    except OSError:
        pass


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
