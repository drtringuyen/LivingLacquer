"""COLMAP text model -> Agisoft cameras XML (plan §4), so the shared importer reads every engine.
The undistorted COLMAP model is PINHOLE: no distortion terms are written. No bpy here."""
import math
import os
import xml.etree.ElementTree as ET


def _quat_to_rot(qw, qx, qy, qz):
    n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz) or 1.0
    w, x, y, z = qw / n, qx / n, qy / n, qz / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def read_cameras(path):
    cams = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        cid, model, w, h = parts[0], parts[1], int(parts[2]), int(parts[3])
        p = [float(v) for v in parts[4:]]
        if model == "PINHOLE":
            fx, fy, cx, cy = p[:4]
        elif model in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"):
            fx = fy = p[0]
            cx, cy = p[1], p[2]
        else:                                   # OPENCV etc.: fx fy cx cy ... (distortion ignored)
            fx, fy, cx, cy = p[:4]
        cams[cid] = {"w": w, "h": h, "f": (fx + fy) / 2, "cx": cx - w / 2, "cy": cy - h / 2, "model": model}
    return cams


def read_images(path):
    """[(name, camera id, 4x4 camera->world rows)]: images.txt has world->camera (R, t)."""
    out = []
    lines = [l for l in open(path, encoding="utf-8") if not l.startswith("#")]
    for i in range(0, len(lines), 2):
        parts = lines[i].split()
        if len(parts) < 10:
            continue
        qw, qx, qy, qz, tx, ty, tz = (float(v) for v in parts[1:8])
        cid, name = parts[8], " ".join(parts[9:])
        R = _quat_to_rot(qw, qx, qy, qz)
        Rt = [[R[j][i2] for j in range(3)] for i2 in range(3)]          # transpose
        c = [-(Rt[r][0] * tx + Rt[r][1] * ty + Rt[r][2] * tz) for r in range(3)]
        out.append((name, cid, [Rt[0] + [c[0]], Rt[1] + [c[1]], Rt[2] + [c[2]], [0.0, 0.0, 0.0, 1.0]]))
    return out


def write_xml(model_dir, dst):
    """model_dir holds cameras.txt + images.txt. Labels are the photo stems. Returns the camera count."""
    cams = read_cameras(os.path.join(model_dir, "cameras.txt"))
    imgs = read_images(os.path.join(model_dir, "images.txt"))
    doc = ET.Element("document", version="1.2.0")
    chunk = ET.SubElement(doc, "chunk", label="COLMAP", enabled="true")
    sensors = ET.SubElement(chunk, "sensors", next_id=str(len(cams)))
    ids = {}
    for n, (cid, c) in enumerate(sorted(cams.items(), key=lambda kv: int(kv[0]))):
        ids[cid] = str(n)
        s = ET.SubElement(sensors, "sensor", id=str(n), label=f"COLMAP camera {cid} ({c['w']}x{c['h']})", type="frame")
        ET.SubElement(s, "resolution", width=str(c["w"]), height=str(c["h"]))
        cal = ET.SubElement(s, "calibration", type="frame", **{"class": "adjusted"})
        ET.SubElement(cal, "resolution", width=str(c["w"]), height=str(c["h"]))
        for k in ("f", "cx", "cy"):
            ET.SubElement(cal, k).text = repr(c[k])
    cams_el = ET.SubElement(chunk, "cameras", next_id=str(len(imgs)))
    for n, (name, cid, m) in enumerate(sorted(imgs, key=lambda t: os.path.basename(t[0]))):
        label = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]
        cam = ET.SubElement(cams_el, "camera", id=str(n), sensor_id=ids.get(cid, "0"), label=label)
        ET.SubElement(cam, "transform").text = " ".join(repr(v) for row in m for v in row)
    ET.ElementTree(doc).write(dst, encoding="UTF-8", xml_declaration=True)
    return len(imgs)


def metashape_xml_with_paths(src, dst, photos):
    """Copy of an Agisoft cameras XML whose labels are the absolute photo paths (OpenMVS
    InterfaceMetashape reads the photos from the labels). Cameras without photo / alignment are
    dropped. photos: {label: path}. Returns the kept count."""
    tree = ET.parse(src)
    chunk = tree.getroot().find("chunk")
    kept = 0
    for parent in chunk.find("cameras").iter():
        for c in list(parent.findall("camera")):
            p = photos.get(c.get("label"))
            if p and c.find("transform") is not None and c.get("enabled") != "false":
                c.set("label", p.replace("\\", "/"))
                kept += 1
            else:
                parent.remove(c)
    tree.write(dst, encoding="UTF-8", xml_declaration=True)
    return kept
