"""Lokální HTTP server: statická appka (balená docs/), data z pipeline (/data/*.json) a malé API pro appku.
Poslouchá jen na 127.0.0.1. Zápisy (PUT/POST) vyžadují hlavičku X-Signaly (cizí web ji bez CORS preflightu nepošle)
a kontroluje se Host (ochrana proti DNS rebinding)."""
import json, mimetypes, os, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-=^]{0,14}$")       # stejné jako pipeline.watch.SYMBOL_RE (hlídá test)
MAX_SYMBOLS = 80
MAX_BODY = 512 * 1024
MIME = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8", ".webmanifest": "application/manifest+json", ".png": "image/png",
        ".svg": "image/svg+xml", ".ico": "image/x-icon"}

def clean_symbols(lst):
    out = []
    for x in lst if isinstance(lst, list) else []:
        x = str(x).strip().upper()
        if SYMBOL_RE.match(x) and x not in out:
            out.append(x)
    return out[:MAX_SYMBOLS]

def atomic_write(path, text):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

def make_handler(ctx):
    """ctx: objekt s atributy static (Path), site (Path s data/*.json), home (Path), port (int), sched (Scheduler)."""
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Signaly"

        def log_message(self, *a):
            pass

        # ---- pomocné
        def _send(self, code, body=b"", ctype="application/json; charset=utf-8", cache="no-store"):
            if isinstance(body, (dict, list)) or body is None:
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _host_ok(self):
            return (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{ctx.port}", f"localhost:{ctx.port}")

        def _write_ok(self):
            if not self._host_ok() or self.headers.get("X-Signaly") != "1":
                return False
            o = self.headers.get("Origin")
            return o is None or o.lower() in (f"http://127.0.0.1:{ctx.port}", f"http://localhost:{ctx.port}")

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if n <= 0 or n > MAX_BODY:
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return None

        def _file(self, root, rel):
            try:
                p = (root / rel).resolve()
                p.relative_to(root.resolve())
            except Exception:
                return self._send(404, {"error": "nenalezeno"})
            if not p.is_file():
                return self._send(404, {"error": "nenalezeno"})
            ct = MIME.get(p.suffix.lower()) or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            self._send(200, p.read_bytes(), ct, cache="no-cache")

        # ---- metody
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "špatný Host"})
            path = urlsplit(self.path).path
            if path == "/api/status":
                st = ctx.sched.status()
                st["port"] = ctx.port
                return self._send(200, st)
            if path == "/api/state":
                f = ctx.home / "user_state.json"
                try:
                    return self._send(200, json.loads(f.read_text(encoding="utf-8")) if f.exists() else None)
                except Exception:
                    return self._send(200, None)
            if path.startswith("/data/"):
                rel = path[len("/data/"):]
                if not re.fullmatch(r"[\w.\-]+\.json", rel):
                    return self._send(404, {"error": "nenalezeno"})
                return self._file(ctx.site, rel)
            return self._file(ctx.static, "index.html" if path in ("/", "") else path.lstrip("/"))

        def do_PUT(self):
            if urlsplit(self.path).path != "/api/state":
                return self._send(404, {"error": "nenalezeno"})
            if not self._write_ok():
                return self._send(403, {"error": "zakázáno"})
            j = self._body()
            if not isinstance(j, dict) or j.get("v") != 1 or not isinstance(j.get("fav"), list):
                return self._send(400, {"error": "neplatný stav"})
            atomic_write(ctx.home / "user_state.json", json.dumps(j, ensure_ascii=False))
            return self._send(200, {"ok": True})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/watchlist":
                return self._send(404, {"error": "nenalezeno"})
            if not self._write_ok():
                return self._send(403, {"error": "zakázáno"})
            j = self._body()
            if not isinstance(j, dict) or not isinstance(j.get("symbols"), list):
                return self._send(400, {"error": "očekávám {\"symbols\": [...]}"})
            syms = clean_symbols(j["symbols"])
            return self._send(200, {"ok": True, "symbols": syms, "result": ctx.sched.request_custom(syms)})
    return H

def start(ctx, host="127.0.0.1"):
    srv = ThreadingHTTPServer((host, ctx.port), make_handler(ctx))
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
