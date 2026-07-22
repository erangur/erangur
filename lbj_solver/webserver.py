"""Tiny static server that hands the self-contained web app to a browser.

The Lightning Blackjack web app (``web/index.html``) now runs **entirely in the
browser**: the solver is ported to JavaScript (verified against this package's
engine) and the page makes no API calls back to Python. This module's only job
is to *deliver* that page — e.g. load it once in Safari on a phone, then
**Add to Home Screen**. After that the app is offline (a service worker caches
it), so it keeps working even when this process is gone or the host app (a-Shell)
is suspended in the background — which is what made the old server-backed version
unusable on iOS.

    python -m lbj_solver.webserver              # serves http://127.0.0.1:8000
    python -m lbj_solver.webserver --port 8080
    python -m lbj_solver.webserver --host 0.0.0.0   # reachable over the LAN

Open the printed address in Safari, then Share -> Add to Home Screen.
"""

import argparse
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Bump on server-behaviour changes so a phone can confirm what it served.
_BUILD = "6 · static loader (serverless app)"

# A short per-connection timeout so a browser's dataless "preconnect" socket
# can't wedge the single request-handling thread (a-Shell has no usable threads).
_SOCK_TIMEOUT = 4

_WEB = os.path.join(os.path.dirname(__file__), "web")

_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
}


class _DebugLog:
    """Timestamped ring buffer that also echoes to the console."""

    def __init__(self, cap=250):
        self.cap = cap
        self.lines = []

    def add(self, msg):
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        self.lines.append(line)
        del self.lines[:-self.cap]
        print(line, flush=True)


DEBUG = _DebugLog()


def _resolve(path):
    """Map a URL path to a file inside ``web/`` (``/`` -> index.html).

    Returns an absolute path under ``_WEB`` or ``None`` (not found / traversal).
    """
    p = path.split("?", 1)[0]
    if p in ("/", "/index.html"):
        return os.path.join(_WEB, "index.html")
    full = os.path.normpath(os.path.join(_WEB, p.lstrip("/")))
    if full != _WEB and not full.startswith(_WEB + os.sep):
        return None                      # path-traversal guard
    return full


def _make_handler():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = _SOCK_TIMEOUT

        def log_message(self, fmt, *args):
            DEBUG.add("http  " + (fmt % args))

        def log_error(self, fmt, *args):
            DEBUG.add("http! " + (fmt % args))

        def _send(self, code, body, ctype):
            data = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            self.close_connection = True
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if data:
                    self.wfile.write(data)
            except OSError as e:
                DEBUG.add(f"send failed ({code}): {e!r}")

        def do_GET(self):
            t0 = time.monotonic()
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                code = 204
            else:
                full = _resolve(path)
                if full and os.path.isfile(full):
                    ext = os.path.splitext(full)[1].lower()
                    try:
                        with open(full, "rb") as fh:
                            self._send(200, fh.read(), _CTYPES.get(ext, "application/octet-stream"))
                        code = 200
                    except OSError as e:
                        self._send(500, b"read error", "text/plain")
                        code = 500
                        DEBUG.add(f"read failed {full}: {e!r}")
                else:
                    self._send(404, b"not found", "text/plain")
                    code = 404
            DEBUG.add(f"GET  {path} -> {code}  ({(time.monotonic()-t0)*1000:.0f} ms)")

    return Handler


def run(host="127.0.0.1", port=8000):
    httpd = HTTPServer((host, port), _make_handler())
    shown = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    DEBUG.add(f"=== Lightning Blackjack loader — build {_BUILD} ===")
    print(f"serving the app at  http://{shown}:{port}", flush=True)
    print(f"open that EXACT address in Safari (use {shown}, not 'localhost'),", flush=True)
    print("then Share -> Add to Home Screen. After the first load the app runs", flush=True)
    print("fully offline in the browser — you can stop this and close the shell.", flush=True)
    print("--- request log (also on the phone via the bug button) ---", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        httpd.server_close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="lbj_solver.webserver",
                                description="Static loader for the LBJ web app")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (127.0.0.1 = this device only; "
                        "0.0.0.0 = reachable over the LAN)")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
