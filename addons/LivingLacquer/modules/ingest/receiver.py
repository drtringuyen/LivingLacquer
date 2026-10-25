"""Step 2 - Receive: a small HTTP server inside Blender, on the local network only, that takes photos
from the iPhone and writes them into zz.Source_Photos\\zz.Originals.

- Safari: open the URL / scan the QR code, pick photos, they upload one by one.
- iOS Shortcut "Send to Blender": Get Contents of URL, method POST, URL
  http://<pc>:<port>/upload?t=<token>&name=<file name>, request body = File (the photo).
Every request must carry the random token from the QR code. Only image files are accepted;
names are reduced to their base name. No bpy here."""
import html
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ALLOWED = (".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff", ".dng", ".nef", ".avif")
MAX_BYTES = 300 * 1024 * 1024

_srv = {"server": None, "thread": None, "token": "", "port": 0, "dest": "", "count": 0, "bytes": 0,
        "last": 0.0, "log": [], "errors": 0, "https": 0}


def lan_ip():
    """This PC's address on the local network (no packet is sent: UDP connect only picks the route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def url():
    return f"http://{lan_ip()}:{_srv['port']}/?t={_srv['token']}" if _srv["server"] else ""


def status():
    return dict(_srv, running=_srv["server"] is not None)


def _log(msg):
    _srv["log"].append(time.strftime("%H:%M:%S ") + msg)
    del _srv["log"][:-50]


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Send to Blender</title>
<style>
body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px 16px;background:#1d1d1f;color:#f5f5f7}
h1{font-size:22px;margin:0 0 4px}p{color:#a1a1a6;margin:0 0 20px}
label{display:block;background:#0a84ff;color:#fff;text-align:center;padding:18px;border-radius:14px;font-size:18px;font-weight:600}
input{display:none}#bar{height:8px;background:#333;border-radius:4px;margin:20px 0 8px;overflow:hidden}
#fill{height:100%;width:0;background:#30d158;transition:width .2s}#log{font-size:14px;color:#a1a1a6;white-space:pre-line}
</style></head><body>
<h1>Send to Blender</h1><p>OBJECT</p>
<label>Choose photos<input id="f" type="file" multiple accept="image/*,.heic,.heif,.dng"></label>
<div id="bar"><div id="fill"></div></div><div id="log">Pick photos from the library. Keep this page open until it says Done.</div>
<script>
const T=new URLSearchParams(location.search).get('t');
document.getElementById('f').onchange=async e=>{
 const files=[...e.target.files];let ok=0,bad=0;const log=document.getElementById('log'),fill=document.getElementById('fill');
 for(let i=0;i<files.length;i++){const f=files[i];log.textContent=`Sending ${i+1} / ${files.length}: ${f.name}`;
  try{const r=await fetch(`/upload?t=${T}&name=${encodeURIComponent(f.name)}`,{method:'POST',body:f});
   if(r.ok)ok++;else bad++;}catch(err){bad++;}
  fill.style.width=`${100*(i+1)/files.length}%`;}
 log.textContent=`Done: ${ok} sent`+(bad?`, ${bad} failed`:'')+'. You can pick more.';e.target.value='';};
</script></body></html>"""


class _Server(ThreadingHTTPServer):
    """The port to itself: http.server sets SO_REUSEADDR, which on Windows lets a second Blender bind the
    same port and steal the phone's requests. Exclusive use instead, so start() moves to the next port."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(BaseHTTPRequestHandler):
    server_version = "LivingLacquer"

    def log_message(self, *args):
        pass

    def handle(self):
        """Browsers that force https (Brave, Chrome's HTTPS-First) open a TLS handshake on this plain
        http port. Spot it (first byte 0x16), count it for the panel's hint and close at once: a refused
        connection lets some browsers fall back to http, a garbage answer never does."""
        try:
            first = self.request.recv(1, socket.MSG_PEEK)
        except OSError:
            return
        if first == b"\x16":
            _srv["https"] += 1
            _log("the phone tried https:// - open the link in Safari")
            return
        super().handle()

    def _ok_token(self):
        q = parse_qs(urlparse(self.path).query)
        return secrets.compare_digest(q.get("t", [""])[0], _srv["token"]), q

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        ok, _q = self._ok_token()
        if not ok:
            return self._send(403, "Wrong or missing token: scan the QR code in Blender again.", "text/plain")
        obj = html.escape(os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(_srv["dest"])))))
        self._send(200, PAGE.replace("OBJECT", obj), "text/html; charset=utf-8")

    def do_POST(self):
        ok, q = self._ok_token()
        if not ok or urlparse(self.path).path != "/upload":
            return self._send(403, '{"error":"token"}')
        name = os.path.basename(q.get("name", [""])[0].replace("\\", "/")).strip()
        ext = os.path.splitext(name)[1].lower()
        if not name or ext not in ALLOWED:
            return self._send(415, '{"error":"only photos"}')
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BYTES:
            return self._send(413, '{"error":"size"}')
        dst = os.path.join(_srv["dest"], name)
        if os.path.exists(dst) and os.path.getsize(dst) == n:
            self.rfile.read(n)
            _log(f"{name}: already here")
            return self._send(200, json.dumps({"ok": True, "skipped": True}))
        tmp = dst + ".ll_tmp"
        try:
            with open(tmp, "wb") as f:
                left = n
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        raise OSError("connection closed")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(tmp, dst)
        except OSError as e:
            _srv["errors"] += 1
            _log(f"{name}: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)
            return self._send(500, '{"error":"write"}')
        _srv["count"] += 1
        _srv["bytes"] += n
        _srv["last"] = time.time()
        _log(f"{name}: {n // 1024} KB")
        self._send(200, json.dumps({"ok": True}))


def start(dest, port=8765):
    """Serve on all interfaces of this PC; returns the URL for the phone."""
    if _srv["server"]:
        stop()
    os.makedirs(dest, exist_ok=True)
    server = None
    for p in range(port, port + 20):            # next free port
        try:
            server = _Server(("0.0.0.0", p), _Handler)
            break
        except OSError:
            continue
    if server is None:
        raise OSError(f"No free port from {port}")
    server.daemon_threads = True
    _srv.update(server=server, token=secrets.token_urlsafe(9), port=server.server_address[1], dest=dest,
                count=0, bytes=0, last=0.0, errors=0, https=0, log=[])
    _srv["thread"] = threading.Thread(target=server.serve_forever, daemon=True)
    _srv["thread"].start()
    _log(f"Listening on {lan_ip()}:{_srv['port']}")
    return url()


def stop():
    s = _srv["server"]
    if s:
        s.shutdown()
        s.server_close()
    _srv.update(server=None, thread=None)
