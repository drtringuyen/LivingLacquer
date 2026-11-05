"""Download and unpack one engine (COLMAP or OpenMVS) in its own process, so Blender never waits on the network.

    python engine_worker.py <task.json>

task: {"name", "dest", "marker", "tries": [{"url", "size"}, ...]}. Each try is downloaded into <dest>.download
and unpacked into <dest>; the first that unpacks and holds the marker file (bin/colmap.exe,
DensifyPointCloud.exe) wins, so a .7z that this Windows cannot unpack falls back to the next try (a .zip).
The folder holding the marker is moved up to <dest> itself. Prints "NN%" lines for the job's progress bar
and "FOLDER <path>" at the end. Exit code 0 = installed."""
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
import zipfile

CHUNK = 1 << 20
AGENT = "LivingLacquer-Blender-addon"


def say(line):
    print(line, flush=True)


def _context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url, path, size_hint, label):
    part = path + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, context=_context(), timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or size_hint or 0)
        got, shown = 0, -1
        while True:
            b = r.read(CHUNK)
            if not b:
                break
            f.write(b)
            got += len(b)
            pct = int(100 * got / total) if total else 0
            if pct != shown:
                shown = pct
                say(f"Downloading {label}: {got >> 20} / {total >> 20} MB  {pct}%")
    if total and got != total:
        os.remove(part)
        raise IOError(f"download cut short ({got} of {total} bytes)")
    os.replace(part, path)


def unpack(archive, into):
    if archive.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            names = z.infolist()
            for n, info in enumerate(names):
                z.extract(info, into)
                if n % 20 == 0:
                    say(f"Unpacking {int(100 * n / len(names))}%")
        return
    # .7z: Windows 10 1803+ ships bsdtar as System32\tar.exe; recent ones read 7z
    tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
    say("Unpacking (Windows tar)")
    r = subprocess.run([tar, "-xf", archive, "-C", into], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise IOError(f"tar could not unpack it: {(r.stderr or r.stdout).strip()[:200]}")


def find_marker(top, marker):
    """The folder that holds marker (a relative path like bin/colmap.exe), or None."""
    for d, _dirs, _files in os.walk(top):
        if os.path.isfile(os.path.join(d, marker)):
            return d
    return None


def install(task):
    dest, marker = task["dest"], task["marker"]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for t in task["tries"]:
        url = t["url"]
        archive = os.path.join(os.path.dirname(dest), os.path.basename(url))
        tmp = dest + ".unpack"
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            if not (os.path.exists(archive) and t.get("size") and os.path.getsize(archive) == t["size"]):
                say(f"Download {url}")
                download(url, archive, t.get("size"), task["name"])
            os.makedirs(tmp)
            unpack(archive, tmp)
            found = find_marker(tmp, marker)
            if not found:
                raise IOError(f"no {marker} inside {os.path.basename(url)}")
            shutil.rmtree(dest, ignore_errors=True)
            if os.path.exists(dest):
                raise IOError(f"could not replace {dest} (a program in it is still running?)")
            os.replace(found, dest)
            shutil.rmtree(tmp, ignore_errors=True)
            os.remove(archive)
            say(f"FOLDER {dest}")
            return
        except Exception as e:
            last = e
            say(f"WARNING {os.path.basename(url)}: {e}")
            shutil.rmtree(tmp, ignore_errors=True)
    raise SystemExit(f"ERROR {task['name']} could not be installed: {last}")


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        install(json.load(f))
