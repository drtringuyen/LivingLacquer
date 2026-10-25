"""Which of the 8 steps the open object has done, read from the files and the .blend (no stored "current
step"): each step is DONE, STALE (done, but something it used changed since), TODO, or BLOCKED (an
earlier step it needs is not done). Cached: computed after a file loads, after every job and Check, and
on the panel's refresh button, never while drawing (the folders may stream from Google Drive)."""
import json
import os
import time

import bpy
from bpy.app.handlers import persistent

from . import marker, paths, state

DONE, STALE, TODO, BLOCKED = "DONE", "STALE", "TODO", "BLOCKED"
NAMES = {1: "Object", 2: "Photos", 3: "Reconstruct", 4: "Build Scene & Cameras", 5: "Package"}
NEEDS = {2: (1,), 3: (2,), 4: (3,), 5: (4,)}
# the 5 steps are made of these checks (the 8 stages of docs/PLAN_scan_pipeline.md)
STAGES = {1: (1,), 2: (2, 3), 3: (4, 5), 4: (6, 7), 5: (8,)}
STAGE_NAMES = {1: "Object", 2: "Receive", 3: "Convert & Sort", 4: "Reconstruct", 5: "Check Links",
               6: "Build Scene", 7: "Undistort & BG", 8: "Package"}
STAGE_NEEDS = {2: (1,), 3: (2,), 4: (3,), 5: (1,), 6: (4,), 7: (6,), 8: (6,)}
MIN_PHOTOS = 3

_cache = {"blend": None, "steps": {}, "time": 0.0, "expanded": {}}


def _mtime(p):
    try:
        return os.path.getmtime(p) if p else 0.0
    except OSError:
        return 0.0


def _photos(found):
    n = 0
    for d in (found.get("source"), found.get("originals")):
        if d and os.path.isdir(d):
            n += sum(1 for f in os.listdir(d)
                     if f.lower().endswith(paths.PHOTO_EXTS + paths.RAW_EXTS) and not paths.is_ignored(f))
    return n


def compute_stages(root):
    """{stage 1-8: (state, note)} for the object folder root (the open .blend)."""
    out = {}
    if not root:
        out[1] = (TODO, "save the file as an object")
        for n in range(2, 9):
            out[n] = (BLOCKED, "")
        return out
    found = paths.locate(root)
    obj = found["object"]
    m = marker.read(root) or {}
    out[1] = (DONE, os.path.basename(root))

    n_photos = _photos(found)
    out[2] = (DONE, f"{n_photos} photos") if n_photos >= MIN_PHOTOS else (TODO, f"{n_photos} photos")

    try:                                              # 3: nothing left to sort / convert
        from ..ingest import convert
        p = convert.plan(found["source"] or "", found["originals"])
        left = len(p["moves"]) + len(p["convert"])
        out[3] = (DONE, f"{p['jpg']} JPG") if not left and p["jpg"] >= MIN_PHOTOS else \
            (TODO, f"{left} to sort / convert" if left else f"{p['jpg']} JPG")
    except Exception:
        out[3] = (DONE, "") if n_photos >= MIN_PHOTOS else (TODO, "")

    xml, model, tex = found["xml"], found["model"], found["textures"]
    t_xml, t_model = _mtime(xml), _mtime(model)
    rig = bpy.data.objects.get("Transform")
    built = json.loads(rig.get("ll_built", "{}")) if rig else {}
    # Build measured how well these very files line up (same dates): that beats comparing file dates
    checked = built.get("align") is not None and abs(built.get("xml", 0) - t_xml) <= 1 \
        and abs(built.get("model", 0) - t_model) <= 1
    mesh = bpy.data.objects.get(f"OBJ_{obj}")
    if not checked and xml and rig and mesh is not None and mesh.parent == rig and t_model + 1 < t_xml:
        try:                                          # built before Build recorded it: measure the scene now
            from ..scene.model import scene_alignment
            score = scene_alignment(mesh, xml)
        except Exception:
            score = None
        if score is not None:
            built = dict(built, align=score)
            checked = True
    if xml and model and tex:
        if checked and built["align"] >= 0.5:
            out[4] = (DONE, f"{os.path.basename(model)} + cameras, line up {built['align']:.0%}")
        elif checked:
            out[4] = (STALE, f"model and cameras do not line up ({built['align']:.0%})")
        elif t_model + 1 < t_xml:
            out[4] = (STALE, "model older than the cameras: Build checks if they match")
        else:
            out[4] = (DONE, f"{os.path.basename(model)} + cameras")
    else:
        missing = [n for n, v in (("cameras", xml), ("model", model), ("texture", tex)) if not v]
        out[4] = (TODO, "no " + ", ".join(missing))
    try:                                              # an engine result not published yet
        from ..scene import build
        folder, res = build.engine_result(root)
        pub = (m.get("published") or {}).get("date", "")
        if res and res.get("date", "") > pub:
            out[4] = (TODO, f"{res.get('engine', '')} result not published")
    except Exception:
        pass

    chk = m.get("last_check") or {}
    if not chk:
        out[5] = (TODO, "not checked yet")
    elif chk.get("errors"):
        out[5] = (STALE, f"{chk['errors']} error(s) in Check Links")
    elif chk.get("time", 0) + 1 < max(t_xml, t_model):     # new exports since the check (saving the .blend is not)
        out[5] = (STALE, "files changed since the check")
    else:
        out[5] = (DONE, f"{chk.get('warnings', 0)} warning(s)")

    cams = [o for o in (rig.children if rig else []) if o.type == "CAMERA"]
    mesh = bpy.data.objects.get(f"OBJ_{obj}")
    if rig and cams and mesh and mesh.parent == rig:
        if built and (t_xml > built.get("xml", 0) + 1 or t_model > built.get("model", 0) + 1):
            out[6] = (STALE, "newer export: Build again")
        else:
            out[6] = (DONE, f"{len(cams)} cameras")
    else:
        out[6] = (TODO, "")

    if cams:
        have = 0
        for c in cams:
            bg = next((b for b in c.data.background_images if b.image), None)
            have += bool(bg and os.path.exists(bpy.path.abspath(bg.image.filepath)))
        stale = False
        try:
            from ..metashape.parse import parse_metashape_xml
            from ..scene.build import fingerprint
            sensors, _ = parse_metashape_xml(xml)
            prints = m.get("calibration_fingerprint") or {}
            stale = isinstance(prints, dict) and any(prints.get(s) not in (None, fingerprint(c))
                                                     for s, c in sensors.items())
        except Exception:
            pass
        changed = []                                  # source photos replaced since their camera photo
        sigs = m.get("photo_signatures") or {}
        if sigs and found["source"]:
            try:
                from ..linker.checks import index_photos, pick_jpg
                from ..scene.build import photo_changed
                src = index_photos(found["source"], skip=(paths.ORIGINALS,))
                changed = [c.name for c in cams if c.name in src and photo_changed(sigs.get(c.name),
                                                                                     pick_jpg(src[c.name]))]
            except Exception:
                changed = []
        if stale:
            out[7] = (STALE, "calibration changed: undistort again")
        elif changed:
            out[7] = (STALE, f"{len(changed)} photo(s) replaced: undistort again")
        elif have == len(cams):
            out[7] = (DONE, f"{have} backgrounds")
        else:
            out[7] = (TODO, f"{have} of {len(cams)} backgrounds")
    else:
        out[7] = (TODO, "")

    pub = (m.get("published") or {}).get("date")
    absolute = [i for i in bpy.data.images if i.source == "FILE" and i.filepath and not i.packed_file
                and not i.filepath.startswith("//")]
    if not pub:
        out[8] = (TODO, "")
    elif absolute:
        out[8] = (TODO, f"{len(absolute)} absolute path(s)")
    elif bpy.data.is_dirty:
        out[8] = (TODO, "save the .blend")
    else:
        out[8] = (DONE, f"published {pub[:10]}")

    if out[4][0] == DONE and out[3][0] == TODO:       # photos added since the reconstruction
        out[4] = (STALE, "new photos are not in this reconstruction")
    for n in range(2, 9):                             # blocked by an earlier stage that is not done
        if any(out[r][0] not in (DONE, STALE) for r in STAGE_NEEDS[n]):
            # files left from an earlier run do not count before the scene is built (6, 7, 8)
            if out[n][0] != DONE or n in (6, 7, 8):
                out[n] = (BLOCKED, out[n][1] if out[n][0] != DONE else "")
    return out


def compute(root):
    """{step 1-5: (state, note)}: a step is done when all its stages are; else it takes the state of its
    first stage that is not done (a problem = STALE shows red), with that stage named in the note."""
    st = compute_stages(root)
    out = {}
    for n, stages in STAGES.items():
        open_ = [k for k in stages if st[k][0] != DONE]
        if not open_:
            out[n] = (DONE, " · ".join(st[k][1] for k in stages if st[k][1]))
            continue
        k = next((k for k in open_ if st[k][0] == STALE), open_[0])
        note = st[k][1]
        if len(stages) > 1:
            note = f"{STAGE_NAMES[k]}: {note}" if note else STAGE_NAMES[k]
        out[n] = (st[k][0], note)
    return out


def refresh():
    blend = bpy.data.filepath
    try:
        steps = compute(state.get()["root"])
    except Exception as e:                            # never break the panel
        steps = {n: (TODO, f"? {e}") for n in NAMES}
    _cache.update(blend=blend, steps=steps, time=time.time())
    for win in bpy.context.window_manager.windows if bpy.context.window_manager else []:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return steps


def get():
    """{step: (state, note)}; empty until the first refresh for this file."""
    return _cache["steps"] if _cache["blend"] == bpy.data.filepath else {}


def current():
    """The step to work on: the first one to do; else the first stale one; None when all are done."""
    s = get()
    for wanted in (TODO, STALE):
        n = next((n for n in NAMES if s.get(n, (TODO,))[0] == wanted), None)
        if n is not None:
            return n
    return None


def expanded(n):
    """Open: the step the user opened, else the current one."""
    return _cache["expanded"].get(n, n == current())


def toggle(n):
    _cache["expanded"][n] = not expanded(n)


def record_check(root, ok, warn, err):
    """Remember the last Check Links result in livinglacquer.json (step 5's state)."""
    m = marker.read(root)
    if m is None:
        return
    m["last_check"] = {"time": time.time(), "ok": ok, "warnings": warn, "errors": err}
    marker.write(root, m)


def _later():
    refresh()
    return None


@persistent
def _on_load(*_args):
    _cache["expanded"].clear()
    if not bpy.app.timers.is_registered(_later):
        bpy.app.timers.register(_later, first_interval=0.5)


class LIVINGLACQUER_OT_PipeToggleStep(bpy.types.Operator):
    """Open / close this step"""
    bl_idname = "livinglacquer.pipe_toggle_step"
    bl_label = "Step"
    step: bpy.props.IntProperty()

    def execute(self, context):
        toggle(self.step)
        return {"FINISHED"}


class LIVINGLACQUER_OT_PipeRefreshSteps(bpy.types.Operator):
    """Look at the object folder and the .blend again and update which steps are done"""
    bl_idname = "livinglacquer.pipe_refresh_steps"
    bl_label = "Refresh Steps"

    def execute(self, context):
        state.refresh()
        refresh()
        return {"FINISHED"}


classes = (LIVINGLACQUER_OT_PipeToggleStep, LIVINGLACQUER_OT_PipeRefreshSteps)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.save_post.append(_on_load)
    bpy.app.timers.register(_later, first_interval=1.0)
    from . import jobs
    jobs.ON_FINISH.append(lambda job: refresh())


def unregister():
    from . import jobs
    jobs.ON_FINISH.clear()
    for h in (bpy.app.handlers.load_post, bpy.app.handlers.save_post):
        if _on_load in h:
            h.remove(_on_load)
    if bpy.app.timers.is_registered(_later):
        bpy.app.timers.unregister(_later)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
