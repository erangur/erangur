"""Tiny static server that hands the self-contained web app to a browser.

The Lightning Blackjack web app (``web/index.html``) now runs **entirely in the
browser**: the solver is ported to JavaScript (verified against this package's
engine) and the page makes no API calls back to Python. This module's only job
is to *deliver* that page — e.g. load it once in Safari on a phone, then
**Add to Home Screen**. After that the app is offline (a service worker caches
it), so it keeps working even when this process is gone or the host app (a-Shell)
is suspended in the background — which is what made the old server-backed version
unusable on iOS.

Deliberately implemented as a **bare blocking ``socket.accept()`` loop** — no
``http.server``/``socketserver``/``selectors``/threads. a-Shell's sandboxed
Python has been seen to crash inside ``serve_forever`` → ``selectors.select``
("failed to read thread state"), and it can't hand sockets to worker threads
either. A one-request-at-a-time accept loop sidesteps all of that; it only has to
serve a handful of GETs for the initial load, so nothing fancy is needed.

    python -m lbj_solver.webserver              # serves http://127.0.0.1:8000
    python -m lbj_solver.webserver --port 8080
    python -m lbj_solver.webserver --host 0.0.0.0   # reachable over the LAN

Open the printed address in Safari, then Share -> Add to Home Screen.
"""

import argparse
import os
import socket
import time

# Bump on server-behaviour changes so a phone can confirm what it served.
_BUILD = "7 · bare-socket static loader"

# Per-connection read timeout: a browser's dataless "preconnect" can't wedge the
# single-threaded accept loop for more than this long.
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

_STATUS = {200: "OK", 204: "No Content", 400: "Bad Request",
           404: "Not Found", 500: "Internal Server Error"}


def _log(msg):
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


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


def _response(code, body, ctype):
    if not isinstance(body, (bytes, bytearray)):
        body = body.encode("utf-8")
    head = (
        f"HTTP/1.1 {code} {_STATUS.get(code, 'OK')}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).encode("latin1")
    return head + bytes(body)


def _build_reply(path):
    """``(response_bytes, code)`` for a GET ``path``."""
    if path == "/favicon.ico":
        return _response(204, b"", "image/x-icon"), 204
    full = _resolve(path)
    if not full or not os.path.isfile(full):
        return _response(404, b"not found", "text/plain"), 404
    try:
        with open(full, "rb") as fh:
            data = fh.read()
    except OSError as e:
        _log(f"read failed {full}: {e!r}")
        return _response(500, b"read error", "text/plain"), 500
    ext = os.path.splitext(full)[1].lower()
    return _response(200, data, _CTYPES.get(ext, "application/octet-stream")), 200


def _serve_one(conn):
    """Read one HTTP request off ``conn`` and send the reply. Never raises."""
    t0 = time.monotonic()
    try:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return                      # client hung up before sending a request
            buf += chunk
            if len(buf) > 65536:
                break                       # oversized header; treat as bad request
        line = buf.split(b"\r\n", 1)[0].decode("latin1", "replace")
        parts = line.split(" ")
        method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "/")
        if method != "GET":
            reply, code = _response(400, b"only GET", "text/plain"), 400
        else:
            reply, code = _build_reply(path.split("?", 1)[0])
        conn.sendall(reply)
        _log(f"GET  {path} -> {code}  ({(time.monotonic()-t0)*1000:.0f} ms)")
    except socket.timeout:
        pass                                # idle preconnect; just drop it
    except OSError as e:
        _log(f"conn error: {e!r}")


def run(host="127.0.0.1", port=8000):
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind((host, port))
    ls.listen(16)
    shown = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    _log(f"=== Lightning Blackjack loader — build {_BUILD} ===")
    print(f"serving the app at  http://{shown}:{port}", flush=True)
    print(f"open that EXACT address in Safari (use {shown}, not 'localhost'),", flush=True)
    print("then Share -> Add to Home Screen. After the first load the app runs", flush=True)
    print("fully offline in the browser — you can stop this and close the shell.", flush=True)
    print("--- request log (also on the phone via the bug button) ---", flush=True)
    try:
        while True:
            try:
                conn, _addr = ls.accept()
            except OSError as e:
                _log(f"accept error: {e!r}")
                continue
            try:
                conn.settimeout(_SOCK_TIMEOUT)
                _serve_one(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        ls.close()


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
