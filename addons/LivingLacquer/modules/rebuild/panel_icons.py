"""The photo panel's button icons. It draws itself, and Blender gives Python no way to draw its own icons
there, so they are shapes in a 16 x 16 box drawn after MultiCamProject's (camera, lock, eye, star, curve),
and its toolbar PNGs for Fill and Erase."""
import math
import os
import struct
import zlib

import gpu

FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "icons")
PNGS = {"fill": "fill.png", "erase": "erase.png"}
_textures = {}


def _read_png(path):
    """(width, height, RGBA floats bottom row first) of an 8-bit RGBA / RGB PNG, else None."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _c, _f, inter = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or inter:
                return None
            ch = 4 if ctype == 6 else 3
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * ch
    rows, prev = [], bytearray(stride)
    for y in range(h):
        ft = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if ft == 1:
                line[i] = (line[i] + a) & 255
            elif ft == 2:
                line[i] = (line[i] + b) & 255
            elif ft == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    px = []
    for line in reversed(rows):         # Blender: bottom row first
        for x in range(w):
            r, g, b = line[x * ch:x * ch + 3]
            px += (r / 255, g / 255, b / 255, line[x * ch + 3] / 255 if ch == 4 else 1.0)
    return w, h, px


def texture(name):
    """The GPUTexture of a PNG icon, None when it has none or cannot be read."""
    if name not in PNGS:
        return None
    if name not in _textures:
        tex = None
        try:
            read = _read_png(os.path.join(FOLDER, PNGS[name]))
            if read:
                w, h, px = read
                tex = gpu.types.GPUTexture((w, h), format="RGBA8", data=gpu.types.Buffer("FLOAT", w * h * 4, px))
        except (OSError, ValueError, zlib.error, struct.error) as e:
            print(f"[LivingLacquer] icon {name}: {e}")
        _textures[name] = tex
    return _textures[name]


def clear():
    _textures.clear()


def _fan(points):
    return [(points[0], points[i], points[i + 1]) for i in range(1, len(points) - 1)]


def _rect(x0, y0, x1, y1):
    return _fan([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _circle(cx, cy, r, n=14):
    return _fan([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)])


def _stroke(points, w=1.6):
    tris = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        k = (w / 2) / max(math.hypot(dx, dy), 1e-6)
        nx, ny = -dy * k, dx * k
        tris += _fan([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])
    return tris


def _arc(cx, cy, rx, ry, a0, a1, n=12):
    return [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def _star(cx, cy, r0, r1):
    pts = [(cx + (r0 if i % 2 == 0 else r1) * math.sin(math.pi * i / 5), cy + (r0 if i % 2 == 0 else r1) * math.cos(math.pi * i / 5))
           for i in range(10)]
    return _fan([(cx, cy)] + pts + [pts[0]])


# name -> triangles in the 16 x 16 box
SHAPES = {
    "prev": _fan([(11, 2.5), (11, 13.5), (4.5, 8)]),
    "next": _fan([(5, 2.5), (11.5, 8), (5, 13.5)]),
    "open": _fan([(2.5, 11), (13.5, 11), (8, 4.5)]),
    "FOCUS": _rect(1.5, 4, 10.5, 12) + _fan([(11.5, 8), (15, 11.5), (15, 4.5)]),
    "LOCK": _rect(3, 1.5, 13, 8.5) + _stroke(_arc(8, 8.5, 3.4, 4.8, 0, 180)),
    "FREE": _stroke(_arc(8, 5, 7.5, 6, 25, 155)) + _stroke(_arc(8, 11, 7.5, 6, 205, 335)) + _circle(8, 8, 2.3),
    "solo": _star(8, 8, 7, 2.9),
    "soft": _stroke([(1.5, 2.5)] + [(1.5 + 13 * i / 16, 2.5 + 10.5 * (0.5 - 0.5 * math.cos(2 * math.pi * i / 16))) for i in range(1, 17)]),
    "brush": _stroke([(14, 14), (7.5, 6.5)], 2.2) + _circle(5, 4.5, 3.2),
}
