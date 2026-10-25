"""Step 5 - Check Links, .blend side: every file path in the open file (E26, G, relink) and the
fixes. Paths are written relative to the .blend (//...)."""
import os
import shutil

import bpy

from ..project import paths
from .checks import ERROR, INFO, OK, WARN, item, walk_files

PATH_COLLECTIONS = ("images", "cache_files", "libraries", "movieclips", "sounds", "fonts", "volumes")


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def _roles():
    """{image name: 'camera' | 'texture'} from camera backgrounds and material image nodes."""
    roles = {}
    for cd in bpy.data.cameras:
        for bg in cd.background_images:
            if bg.image:
                roles[bg.image.name] = "camera"
    for mat in bpy.data.materials:
        if mat.node_tree:
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image:
                    roles.setdefault(n.image.name, "texture")
    return roles


def entries():
    """[{'coll', 'id', 'raw', 'abs', 'role'}] for every datablock that points at a file."""
    roles = _roles()
    out = []
    for coll in PATH_COLLECTIONS:
        for idb in getattr(bpy.data, coll, []):
            raw = getattr(idb, "filepath", "")
            if not raw or raw == "<builtin>" or getattr(idb, "packed_file", None):
                continue
            if coll == "images" and idb.source not in {"FILE", "SEQUENCE", "TILED", "MOVIE"}:
                continue
            out.append({"coll": coll, "id": idb, "raw": raw,
                        "abs": os.path.normpath(bpy.path.abspath(raw, library=idb.library)),
                        "role": roles.get(idb.name, "") if coll == "images" else coll})
    return out


def _file_index(root):
    """{lower file name: [paths]} for the object folder."""
    idx = {}
    for d, f in walk_files(root):
        idx.setdefault(f.lower(), []).append(os.path.join(d, f))
    return idx


def _prefer(cands, role, found):
    """The candidate in the folder that matches the role (camera -> 01.CAM_Photos,
    texture -> 02.Geometry), else the only one."""
    want = {"camera": found.get("cam"), "texture": found.get("geometry")}.get(role)
    if want:
        hit = [c for c in cands if _norm(os.path.dirname(c)) == _norm(want)]
        if len(hit) == 1:
            return hit[0]
    return cands[0] if len(cands) == 1 else None


def plan(root, found):
    """Report items for the .blend paths plus the actions the Fix button would run:
    [('relink' | 'pull' | 'relative', entry, new_abs_path)]."""
    items, actions = [], []
    ents = entries()
    if not ents:
        items.append(item("E26", OK, "No external files linked yet"))
        return items, actions
    idx = _file_index(root)
    rootn = _norm(root)
    missing_tex = []
    missing, external, absolute, ok = [], [], [], 0
    for e in ents:
        inside = _norm(e["abs"]).startswith(rootn + os.sep)
        if not os.path.exists(e["abs"]):
            cands = idx.get(os.path.basename(e["abs"]).lower(), [])
            new = _prefer(cands, e["role"], found) if cands else None
            if new:
                actions.append(("relink", e, new))
            elif e["role"] == "texture":
                missing_tex.append(e)
            missing.append((e, new))
        elif not inside:
            external.append(e)
            actions.append(("pull", e, _pull_target(e, found)))
        elif not e["raw"].startswith("//"):
            absolute.append(e)
            actions.append(("relative", e, e["abs"]))
        else:
            ok += 1

    # textures renamed to the naming rule (OBJ_<Object>.jpg): map the lost ones page by page (D20)
    pages = [t for t in found["textures"] if not t.lower().endswith(("_normal.jpg", "_ao.jpg"))]
    if missing_tex and len(missing_tex) <= len(pages):
        for e, new in zip(sorted(missing_tex, key=lambda e: e["id"].name), pages):
            actions.append(("relink", e, new))
            missing = [(m, new if m is e else n) for m, n in missing]

    if missing:
        fixable = sum(1 for _, n in missing if n)
        lines = [f"{e['id'].name}: {e['raw']}" + (f"  ->  {paths.rel(root, n)}" if n else "  (not found)")
                 for e, n in missing]
        items.append(item("E26", ERROR, f"{len(missing)} missing file(s), {fixable} found in the object folder",
                          lines, fix="relink" if fixable else None))
    if external:
        items.append(item("G", ERROR, f"{len(external)} external link(s) outside the object folder",
                          [f"{e['id'].name}: {e['abs']}" for e in external], fix="pull"))
    if absolute:
        items.append(item("E26", WARN, f"{len(absolute)} absolute path(s) inside the object folder",
                          [f"{e['id'].name}: {e['raw']}" for e in absolute], fix="relative"))
    if ok:
        items.append(item("E26", OK, f"{ok} linked file(s) found, relative to the .blend"))
    drive = os.path.splitdrive(root)[0].lower()
    cross = [e for e in external if os.path.splitdrive(e["abs"])[0].lower() != drive]
    if cross:
        items.append(item("E26", INFO, f"{len(cross)} of the external links are on another drive (Blender cannot "
                          "store them relative)"))
    return items, actions


def _pull_target(e, found):
    """Where an external file is copied: camera photos -> 01.CAM_Photos, textures and Alembic ->
    02.Geometry, anything else -> the object folder."""
    if e["role"] == "camera" and found.get("cam"):
        folder = found["cam"]
    elif e["role"] in ("texture", "cache_files") and found.get("geometry"):
        folder = found["geometry"]
    else:
        folder = found["root"]
    return os.path.join(folder, os.path.basename(e["abs"]))


def set_path(e, new_abs):
    """Point the datablock at new_abs, relative to the .blend; reload what is cheap to reload."""
    idb = e["id"]
    idb.filepath = bpy.path.relpath(new_abs) if os.path.splitdrive(new_abs)[0].lower() == \
        os.path.splitdrive(bpy.data.filepath)[0].lower() else new_abs
    if e["coll"] == "images":
        idb.reload()
        for ob in bpy.data.objects:     # keep the metashape importer's note in step
            if ob.type == "CAMERA" and any(bg.image == idb for bg in ob.data.background_images):
                ob["metashape_photo"] = idb.filepath
    elif e["coll"] == "libraries":
        idb.reload()


def describe(root, actions, renames, tree, write_marker):
    """Lines for the confirm dialog."""
    lines = [f"Rename {os.path.basename(p)} -> {new}" for p, new in renames]
    if tree:
        lines.append(f"Create {len(tree)} missing scan folder(s)")
    n = {k: sum(1 for a in actions if a[0] == k) for k in ("relink", "pull", "relative")}
    if n["relink"]:
        lines.append(f"Relink {n['relink']} missing file(s) found in the object folder")
    if n["pull"]:
        lines.append(f"Copy {n['pull']} external file(s) into the object folder and relink them")
    if n["relative"]:
        lines.append(f"Make {n['relative']} path(s) relative")
    if write_marker:
        lines.append("Write livinglacquer.json")
    return lines


def rename_folder(path, new_name):
    """Rename a folder in place; a case-only change goes through a temp name (Windows)."""
    new = os.path.join(os.path.dirname(path), new_name)
    if _norm(path) == _norm(new):
        tmp = path + ".ll_tmp"
        os.rename(path, tmp)
        os.rename(tmp, new)
    else:
        if os.path.exists(new):
            raise OSError(f"{new_name} already exists next to {os.path.basename(path)}")
        os.rename(path, new)


def apply(actions):
    """Run relink / pull / relative actions. Returns (done, problems)."""
    done, problems = 0, []
    for kind, e, new in actions:
        try:
            if kind == "pull":
                if os.path.exists(new) and os.path.getsize(new) != os.path.getsize(e["abs"]):
                    problems.append(f"{e['id'].name}: {os.path.basename(new)} already exists with another size")
                    continue
                if not os.path.exists(new):
                    tmp = new + ".ll_tmp"
                    shutil.copy2(e["abs"], tmp)
                    os.replace(tmp, new)
            set_path(e, new)
            done += 1
        except Exception as ex:
            problems.append(f"{e['id'].name}: {ex}")
    return done, problems
