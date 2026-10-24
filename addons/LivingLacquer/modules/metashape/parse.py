"""Agisoft Metashape XML (cameras export) -> sensors + camera world matrices."""
import xml.etree.ElementTree as ET

from mathutils import Matrix

SENSOR_WIDTH_MM = 36.0


def _floats(text):
    return [float(v) for v in text.split()]


def parse_metashape_xml(path):
    """Return (sensors, cameras).
    sensors: {sensor_id: {"f", "cx", "cy", "k1".., "p1", "p2", "b1", "b2", "w", "h"}}
    cameras: [{"label", "sensor", "matrix"}] for enabled, aligned cameras only."""
    root = ET.parse(path).getroot()
    chunk = root.find("chunk")
    if chunk is None:
        raise ValueError("No <chunk> in XML")

    sensors = {}
    for s in chunk.find("sensors"):
        res = s.find("resolution")
        cal_el = s.find("calibration")
        cal = {}
        if cal_el is not None:
            for e in cal_el:
                if e.tag != "resolution" and e.text:
                    cal[e.tag] = float(e.text)
        w, h = int(res.get("width")), int(res.get("height"))
        if "f" not in cal:  # uncalibrated sensor: fall back to focal_length / pixel size
            props = {p.get("name"): p.get("value") for p in s.findall("property")}
            fmm = float(props.get("focal_length", 50))
            pw = float(props.get("pixel_width", SENSOR_WIDTH_MM / w))
            cal["f"] = fmm / pw
        cal["w"], cal["h"] = w, h
        sensors[s.get("id")] = cal

    # optional chunk transform (when the chunk is referenced / scaled)
    chunk_m = Matrix.Identity(4)
    ct = chunk.find("transform")
    if ct is not None:
        rot = ct.find("rotation")
        tr = ct.find("translation")
        sc = ct.find("scale")
        r = _floats(rot.text) if rot is not None else [1, 0, 0, 0, 1, 0, 0, 0, 1]
        t = _floats(tr.text) if tr is not None else [0, 0, 0]
        k = float(sc.text) if sc is not None else 1.0
        R = Matrix((r[0:3], r[3:6], r[6:9]))
        chunk_m = Matrix.Translation(t) @ (R * k).to_4x4()

    cameras = []
    for c in chunk.find("cameras").iter("camera"):
        t = c.find("transform")
        if t is None or c.get("enabled") == "false":
            continue
        m = _floats(t.text)
        M = Matrix((m[0:4], m[4:8], m[8:12], m[12:16]))
        cameras.append({"label": c.get("label"), "sensor": c.get("sensor_id"), "matrix": chunk_m @ M})
    return sensors, cameras
