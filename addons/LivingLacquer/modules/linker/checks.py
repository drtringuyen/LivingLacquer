"""Step 5 - Check Links, folder side: the object folder, the photos and the camera XML
(plan §6 table, codes A-G). Each check adds report items; no bpy here."""
import os
import xml.etree.ElementTree as ET

from ..metashape.photos import read_image_size
from ..project import marker, paths

OK, INFO, WARN, ERROR = "OK", "INFO", "WARN", "ERROR"
MAX_PATH = 260


def item(code, sev, title, lines=(), fix=None):
    return {"code": code, "sev": sev, "title": title, "lines": list(lines), "fix": fix}


def walk_files(root):
    """Every file under root, ignored names skipped: [(dirpath, name)]."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not paths.is_ignored(d)]
        out += [(dirpath, f) for f in files]
    return out


def read_xml(path):
    """Light summary of an Agisoft cameras XML, nothing computed:
    {'chunks', 'components', 'transform', 'sensors': {id: (w, h, label)},
     'cameras': [{'label', 'sensor', 'aligned', 'enabled'}]}."""
    root = ET.parse(path).getroot()
    chunks = root.findall("chunk")
    chunk = chunks[0]
    sensors = {}
    for s in chunk.find("sensors") if chunk.find("sensors") is not None else []:
        res = s.find("resolution")
        sensors[s.get("id")] = (int(res.get("width")), int(res.get("height")), s.get("label", ""))
    comps = chunk.find("components")
    cams = [{"label": c.get("label"), "sensor": c.get("sensor_id"),
             "aligned": c.find("transform") is not None, "enabled": c.get("enabled") != "false"}
            for c in chunk.find("cameras").iter("camera")]
    return {"chunks": len(chunks), "components": len(comps) if comps is not None else 0,
            "transform": chunk.find("transform") is not None, "sensors": sensors, "cameras": cams}


def match_photo(label, photos):
    """(stem, rule) of the photo for a camera label: exact, case, or "(2)"-suffix stripped."""
    if label in photos:
        return label, ""
    low = {s.lower(): s for s in photos}
    if label.lower() in low:
        return low[label.lower()], "case"
    base = paths.CONFLICT_RE.sub("", label)
    if base != label and base.lower() in low:
        return low[base.lower()], "suffix"
    return None, None


def index_photos(folder, skip=()):
    """{stem: [paths]} of the photos (JPG/PNG/TIFF) under folder, subfolders in skip left out."""
    out = {}
    if not folder:
        return out
    for dirpath, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip and not paths.is_ignored(d)]
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in paths.PHOTO_EXTS and not paths.is_ignored(f):
                out.setdefault(stem, []).append(os.path.join(dirpath, f))
    return out


def pick_jpg(files):
    """JPG first when a stem has several files (A2)."""
    return sorted(files, key=lambda p: os.path.splitext(p)[1].lower() not in (".jpg", ".jpeg"))[0]


def drain(gen):
    """Run a progress generator to the end and return its result (for callers without a job)."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def check_folder(root):
    """Folder checks. Returns (items, found) where found is paths.locate(root)."""
    return drain(check_folder_iter(root))


def check_folder_iter(root):
    """check_folder as a job step: yields (progress 0-1, what) and returns (items, found)."""
    items = []
    yield 0.0, "folders"
    found = paths.locate(root)
    obj = found["object"]

    # marker + Drive account (G)
    m = marker.read(root)
    if m is None:
        items.append(item("G", WARN, "No livinglacquer.json marker yet", fix="marker"))
    else:
        acc = paths.drive_account(root)
        if m.get("account", "") != acc:
            items.append(item("G", WARN, "Opened under another Drive folder than recorded",
                              [f"recorded: {m.get('account') or '(none)'}", f"now: {acc or '(none)'}"],
                              fix="marker"))
        else:
            items.append(item("G", OK, f"Marker found ({acc or 'local folder'})"))

    # old folder names (E28), missing folders
    if found["renames"]:
        items.append(item("E28", WARN, f"{len(found['renames'])} folder(s) with an old name",
                          [f"{os.path.basename(p)} -> {new}" for p, new in found["renames"]], fix="rename"))
    missing = [r for r in paths.TREE if not os.path.isdir(os.path.join(root, *r.split("/")))
               and not any(os.path.normcase(os.path.join(root, *r.split("/"))).startswith(
                   os.path.normcase(os.path.join(os.path.dirname(p), new))) for p, new in found["renames"])]
    if missing:
        items.append(item("E28", INFO, f"{len(missing)} scan folder(s) missing", missing, fix="tree"))

    yield 0.05, "listing files"
    files = walk_files(root)
    # Drive conflict copies (E23), Agisoft lock (E27), long paths (E25), non-ASCII (E24)
    conflicts = [os.path.join(d, f) for d, f in files if paths.is_conflict_copy(f)]
    if conflicts:
        items.append(item("E23", WARN, f"{len(conflicts)} Drive conflict copies (ignored)",
                          [paths.rel(root, p) for p in conflicts]))
    if found["agisoft"]:
        locks = [os.path.join(d, f) for d, f in walk_files(found["agisoft"])
                 if f.lower() == "lock" or f.lower().endswith(".lock")]
        if locks:
            items.append(item("E27", WARN, "Agisoft project looks open (lock file); close Metashape first",
                              [paths.rel(root, p) for p in locks]))
    long_ = [os.path.join(d, f) for d, f in files if len(os.path.join(d, f)) >= MAX_PATH]
    if long_:
        items.append(item("E25", WARN, f"{len(long_)} path(s) over {MAX_PATH} characters; use a local cache",
                          [paths.rel(root, p) for p in long_[:20]]))
    if not root.isascii():
        items.append(item("E24", INFO, "Non-ASCII characters in the folder path (the CLI engines may need a "
                          "local cache)", [root]))

    # photos (A2, A3, A4)
    yield 0.1, "photos"
    src = index_photos(found["source"], skip=(paths.ORIGINALS,))
    stray = [f for d, f in files if found["source"] and os.path.normcase(d) == os.path.normcase(found["source"])
             and os.path.splitext(f)[1].lower() in paths.RAW_EXTS]
    extras = [f for d, f in files if found["source"] and os.path.normcase(d).startswith(
        os.path.normcase(found["source"])) and (f.upper().startswith("IMG_E") or f.lower().endswith(".mov"))]
    if found["source"]:
        items.append(item("A2", OK, f"{len(src)} source photos in {paths.SOURCE}"))
    else:
        items.append(item("A2", WARN, f"No {paths.SOURCE} folder", fix="tree"))
    multi = {s: v for s, v in src.items()
             if len({os.path.normcase(os.path.dirname(p)) for p in v}) == 1 and len(v) > 1}
    if multi:
        items.append(item("A2", INFO, f"{len(multi)} photo(s) in several formats, JPG is used",
                          [f"{s}: " + ", ".join(os.path.basename(p) for p in v) for s, v in list(multi.items())[:20]]))
    dup = {s: v for s, v in src.items() if len({os.path.normcase(os.path.dirname(p)) for p in v}) > 1}
    if dup:
        items.append(item("A3", ERROR, f"{len(dup)} photo name(s) used in several folders",
                          [f"{s}: " + ", ".join(paths.rel(root, p) for p in v) for s, v in list(dup.items())[:20]]))
    if stray:
        items.append(item("A2", INFO, f"{len(stray)} HEIC/RAW file(s) next to the JPGs (step 3 moves them to "
                          f"{paths.ORIGINALS})", stray[:20]))
    if extras:
        items.append(item("A4", INFO, f"{len(extras)} iPhone extra(s) (IMG_E edits, .MOV) ignored", extras[:20]))

    yield from _check_cameras(root, found, src, items)
    _check_geometry(root, found, items)
    yield 1.0, "done"
    return items, found


def _check_cameras(root, found, src, items):
    """Generator: the photo headers are read one by one (they may stream from Drive)."""
    yield 0.15, "camera XML"
    obj = found["object"]
    xml = found["xml"]
    cam_dir = found["cam"]
    undist = index_photos(cam_dir)
    if not xml:
        items.append(item("B7", WARN, f"No camera XML yet: export cameras from Agisoft as CAM_{obj}.xml "
                          f"into {paths.SCAN}\\{paths.CAM}"))
        if undist:
            items.append(item("C14", INFO, f"{len(undist)} undistorted photos in {paths.CAM} (not checked "
                              "without the XML)"))
        return
    if os.path.basename(xml) != f"CAM_{obj}.xml":
        items.append(item("B7", INFO, f"Camera XML is named {os.path.basename(xml)}, expected CAM_{obj}.xml"))
    try:
        x = read_xml(xml)
    except Exception as e:
        items.append(item("B7", ERROR, f"Could not read {os.path.basename(xml)}: {e}"))
        return
    yield 0.2, "matching photos"

    if x["chunks"] > 1:
        items.append(item("B9", WARN, f"{x['chunks']} chunks in the XML, the first one is used"))
    if x["components"] > 1:
        items.append(item("B10", WARN, f"{x['components']} components in the XML (not all cameras share "
                          "one alignment)"))
    if x["transform"]:
        items.append(item("C19", OK, "Chunk transform found, applied to the cameras"))

    cams = x["cameras"]
    aligned = [c for c in cams if c["aligned"] and c["enabled"]]
    skipped = [c["label"] for c in cams if not (c["aligned"] and c["enabled"])]
    items.append(item("B8", OK, f"{len(aligned)} aligned cameras in {os.path.basename(xml)}"))
    if skipped:
        items.append(item("B8", INFO, f"{len(skipped)} unaligned / disabled camera(s) skipped", skipped[:30]))

    # names (A1, A5), coverage (B6, B7)
    by_rule, no_photo, used = [], [], set()
    for c in aligned:
        stem, rule = match_photo(c["label"], src)
        if stem is None:
            no_photo.append(c["label"])
            continue
        used.add(stem)
        c["photo"] = pick_jpg(src[stem])
        if rule:
            by_rule.append(f"{c['label']} -> {stem} ({rule})")
    if by_rule:
        items.append(item("A1", WARN, f"{len(by_rule)} camera(s) matched to a photo by a loose rule", by_rule))
    if no_photo:
        items.append(item("B7", WARN, f"{len(no_photo)} camera(s) without a photo (no background)", no_photo))
    unused = sorted(set(src) - used)
    labels = {c["label"] for c in cams}
    not_in_xml = [s for s in unused if s not in labels]
    if not_in_xml:
        items.append(item("B6", INFO, f"{len(not_in_xml)} photo(s) not in the XML", not_in_xml))

    # lenses and photo sizes (C11, C12, C13), checked per sensor
    lenses = {}
    for c in aligned:
        lenses.setdefault(c["sensor"], []).append(c)
    if len(lenses) > 1:
        items.append(item("C11", INFO, f"{len(lenses)} lenses, each checked against its own sensor",
                          [f"{x['sensors'][sid][2] or 'sensor ' + sid}: {x['sensors'][sid][0]}x"
                           f"{x['sensors'][sid][1]}, {len(v)} camera(s)" for sid, v in lenses.items()
                           if sid in x["sensors"]]))
    # COLMAP publishes pinhole cameras: their images are the undistorted photos, not the source ones
    pinhole = bool(((marker.read(root) or {}).get("published") or {}).get("undistorted"))
    scaled, rotated, wrong = [], [], []
    for n, c in enumerate(aligned):
        yield 0.2 + 0.5 * n / max(len(aligned), 1), c["label"]
        photo = pick_jpg(undist[c["label"]]) if pinhole and c["label"] in undist else \
            (None if pinhole else c.get("photo"))
        if not photo or c["sensor"] not in x["sensors"]:
            continue
        sw, sh, _ = x["sensors"][c["sensor"]]
        size = read_image_size(photo)
        if not size or size == (sw, sh):
            continue
        w, h = size
        if (w, h) == (sh, sw):
            rotated.append(f"{c['label']}: {w}x{h}, sensor {sw}x{sh}")
        elif abs(w * sh - h * sw) <= max(w, h) // 500:
            scaled.append(f"{c['label']}: {w}x{h}, sensor {sw}x{sh}")
        else:
            wrong.append(f"{c['label']}: {w}x{h}, sensor {sw}x{sh}")
    if scaled:
        items.append(item("C12", WARN, f"{len(scaled)} photo(s) resized since alignment (calibration is scaled)",
                          scaled))
    if rotated:
        items.append(item("C13", ERROR, f"{len(rotated)} photo(s) rotated against their sensor (EXIF rotation "
                          "baked in?)", rotated))
    if wrong:
        items.append(item("C12", ERROR, f"{len(wrong)} photo(s) do not fit their sensor", wrong))
    if not (scaled or rotated or wrong):
        items.append(item("C12", OK, "Every photo fits its own sensor"))

    # undistorted photos (C14)
    have = [c for c in aligned if c["label"] in undist]
    bad = []
    for n, c in enumerate(have):
        yield 0.7 + 0.25 * n / max(len(have), 1), c["label"] + " (undistorted)"
        sw, sh, _ = x["sensors"].get(c["sensor"], (0, 0, ""))
        size = read_image_size(pick_jpg(undist[c["label"]]))
        if size and sw and size != (sw, sh):
            bad.append(f"{c['label']}: {size[0]}x{size[1]}, sensor {sw}x{sh}")
    if bad:
        items.append(item("C14", ERROR, f"{len(bad)} undistorted photo(s) have another size than the sensor "
                          "(stale, re-undistort)", bad))
    if len(have) < len(aligned):
        items.append(item("C14", INFO, f"{len(have)} of {len(aligned)} cameras have an undistorted photo; "
                          "step 7 makes the rest"))
    elif not bad:
        items.append(item("C14", OK, f"All {len(aligned)} cameras have an undistorted photo"))


def _check_geometry(root, found, items):
    obj = found["object"]
    model, xml = found["model"], found["xml"]
    if not model:
        items.append(item("D20", WARN, f"No model yet: OBJ_{obj}.abc / .fbx / .obj in {paths.SCAN}\\{paths.GEOMETRY}"))
        return
    items.append(item("D20", OK, f"Model {os.path.basename(model)}"))
    if xml and os.path.getmtime(model) + 1 < os.path.getmtime(xml):
        items.append(item("C17", WARN, "The model is older than the camera XML (re-export the model?)"))
    tex = found["textures"]
    if not tex:
        items.append(item("D20", WARN, f"No texture OBJ_{obj}.jpg next to the model"))
    else:
        items.append(item("D20", OK, f"{len(tex)} texture file(s)", [os.path.basename(t) for t in tex]))
