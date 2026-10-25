"""Local cache (plan §7): Pull an object folder from Google Drive to the local work folder, work there,
Push the changed files back. livinglacquer.json on Drive records who has it checked out, so a second
computer does not edit the same object at the same time. Copies run through robocopy (changed files
only); COLMAP's dense folder stays local."""
import os
import platform

from . import jobs, marker, prefs

SKIP_DIRS = ["dense", "__pycache__"]
SKIP_FILES = ["desktop.ini", "Thumbs.db", "*.lock", "*.ll_tmp", "*.blend1"]


def machine():
    return platform.node() or "this computer"


def cache_root():
    p = prefs.get()
    base = (p.work_root if p and p.work_root else "") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LivingLacquer")
    return os.path.join(base, "cache")


def local_copy(drive_root):
    return os.path.join(cache_root(), os.path.basename(drive_root))


def is_local(root):
    m = marker.read(root) or {}
    return bool(m.get("drive_root")) and os.path.normcase(os.path.abspath(root)).startswith(
        os.path.normcase(os.path.abspath(cache_root())))


def _robocopy(label, src, dst, newer_only, skip=()):
    args = ["robocopy", src, dst, "/E", "/R:1", "/W:1", "/NP", "/NDL", "/NJH", "/XJ",
            "/XD"] + SKIP_DIRS + ["/XF"] + SKIP_FILES + list(skip)
    if newer_only:
        args.append("/XO")              # never overwrite a newer file at the destination
    return jobs.Step(label, args, weight=10, ok_codes=tuple(range(8)))     # robocopy: 0-7 = success


def pull_job(drive_root, on_done=None, force=False):
    m = marker.read(drive_root) or {}
    owner = m.get("checked_out_by", "")
    if owner and owner != machine() and not force:
        raise RuntimeError(f"Checked out by {owner}: push from there first (or force)")
    local = local_copy(drive_root)

    def mark(job):
        dm = marker.read(drive_root) or marker.update(drive_root)
        dm["checked_out_by"] = machine()
        marker.write(drive_root, dm)
        lm = marker.read(local) or dict(dm)
        lm["drive_root"] = drive_root
        lm["checked_out_by"] = machine()
        marker.write(local, lm)
        job.data["blend"] = os.path.join(local, os.path.basename(local) + ".blend")

    return jobs.Job("Pull to Local", [_robocopy("Copy to the local cache", drive_root, local, False),
                                      jobs.Step("Check out", mark, weight=0.1)], on_done=on_done)


def push_job(local_root, on_done=None, release=True):
    lm = marker.read(local_root) or {}
    drive_root = lm.get("drive_root")
    if not drive_root or not os.path.isdir(drive_root):
        raise RuntimeError("This folder was not pulled from Drive (no drive_root in livinglacquer.json)")

    def unmark(job):
        dm = marker.read(drive_root) or {}
        dm.pop("drive_root", None)
        if release:
            dm["checked_out_by"] = ""
        for k in ("published", "calibration_fingerprint", "engine"):
            if k in lm:
                dm[k] = lm[k]
        marker.write(drive_root, dm)
        marker.update(drive_root)
        job.data["blend"] = os.path.join(drive_root, os.path.basename(drive_root) + ".blend")

    return jobs.Job("Push to Drive", [_robocopy("Copy changed files to Drive", local_root, drive_root, True,
                                                skip=[marker.MARKER]),
                                      jobs.Step("Release", unmark, weight=0.1)], on_done=on_done)
