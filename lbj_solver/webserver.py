"""Dependency-free web front-end for the Lightning Blackjack solver.

A phone-friendly twin of the tkinter GUI (``gui.py``) that runs anywhere Python
runs — including on an iPhone via a-Shell / Pythonista — because it uses **only
the standard library** (``http.server``). There is no build step and nothing to
``pip install``: the whole solver package is pure stdlib and the solved carry
values ship cached in ``data/solution.json``.

How it works
------------
The browser is the "view"; this process holds one live :class:`session.Session`
(single player, single device) and a small :class:`_View` that mirrors exactly
what ``gui.LBJGui`` keeps on screen — the felt table, the EV chips, the morphing
dock and the history log — but serialises it to JSON instead of drawing it. Every
HTTP action pumps the session and returns the resulting snapshot; the page
re-renders from that snapshot. Because the session is a synchronous
callback-driven state machine, one HTTP request drives it until it next needs the
human (a move, the drawn card, or the dealer's total).

Launch (identical spirit to ``python -m lbj_solver.gui``)::

    python -m lbj_solver.webserver              # serves on http://localhost:8000
    python -m lbj_solver.webserver --port 8080
    python -m lbj_solver.webserver --host 0.0.0.0   # reachable over the LAN

Then open the printed URL in Safari and *Add to Home Screen*.
"""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from .cli import parse_card, parse_hand
from .config import GameConfig
from .multipliers import (MultiplierModel, TIERS, TIER_BJ_VALUES,
                          new_session_file, observed_tier_counts,
                          overall_tier_counts, record_observed_set)
from .session import Session, hand_str
from .solution import Solution
from .strategy import describe_set

# Bump on every server-behaviour change so a phone can confirm what it runs.
_BUILD = "5 · single-thread + logging"

# How long a single connection may sit without completing its request before we
# drop it. Keeps a browser's dataless "preconnect" socket from wedging the (one)
# request-handling thread — the worst case is one short stall, not a hang.
_SOCK_TIMEOUT = 4

_HERE = os.path.dirname(__file__)
_INDEX = os.path.join(_HERE, "web", "index.html")


class _DebugLog:
    """A tiny timestamped ring buffer that also echoes to the console.

    Everything the server does lands here: it prints to the a-Shell console
    (so you can watch it live) and keeps the tail so the phone UI can pull it
    via ``/api/debug`` when the console isn't visible.
    """

    def __init__(self, cap=250):
        self.cap = cap
        self.lines = []

    def add(self, msg):
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        self.lines.append(line)
        del self.lines[:-self.cap]
        print(line, flush=True)

    def tail(self, n=120):
        return self.lines[-n:]


DEBUG = _DebugLog()

_ACTION_LABEL = {"stand": "Stand", "hit": "Hit", "double": "Double",
                 "split": "Split"}
_LOG_CAP = 300      # keep the tail of the history, like the scrolling log box


def _up_label(up):
    return "A" if up == 11 else str(up)


class _View:
    """Server-side mirror of the GUI's on-screen state, serialised to JSON.

    The callback bodies below are line-for-line equivalents of the ones in
    ``gui.LBJGui`` (minus the tkinter drawing), so play semantics stay identical.
    """

    def __init__(self, session):
        self.session = session
        session.on_log = self._log
        session.on_decision = self._on_decision
        session.on_auto = self._on_auto
        session.on_card = self._on_card
        session.on_dealer = self._on_dealer
        session.on_round_done = self._on_round_done

        # Table view-model (what the canvas would draw).
        self.t_dealer_up = None
        self.t_dealer_final = None
        self.t_hands = []
        self.t_set = None
        self.pair_rank = None
        self._card_ctx = None

        # Read-out / dock / log.
        self.situation = "—"
        self.evs = []
        self.move_buttons = []
        self.dock_title = "NEW ROUND"
        self.prompt = ""
        self.phase = "setup"
        self.log_lines = []

        # Settings (mirror the GUI defaults).
        self.store = False
        self.session_hist_path = new_session_file()

    # ---- table helpers (ported from gui.py) -----------------------------
    def _ensure_split_hands(self):
        if len(self.t_hands) == 2:
            return
        self.t_hands = [{"cards": [self.pair_rank], "label": "Hand 1", "note": ""},
                        {"cards": [self.pair_rank], "label": "Hand 2", "note": ""}]

    def _sync_hand(self, node):
        idx = (node["hand_no"] - 1) if node["hand_no"] else 0
        if node["hand_no"]:
            self._ensure_split_hands()
        self.t_hands[idx]["cards"] = list(node["cards"])

    def play_card(self, rank):
        ctx = self._card_ctx
        hand_no = ctx.get("hand_no") if ctx else None
        if hand_no:
            self._ensure_split_hands()
            self.t_hands[hand_no - 1]["cards"].append(rank)
        elif self.t_hands:
            self.t_hands[0]["cards"].append(rank)
        self.session.card(rank)

    # ---- read-out --------------------------------------------------------
    def _show_node(self, node, auto=None, reason=None):
        self._sync_hand(node)
        cards = hand_str(node["cards"])
        where = (f"Split hand {node['hand_no']}  {cards}" if node["hand_no"]
                 else f"Hand {cards}")
        self.situation = (
            f"{where}  ·  total {node['total']} vs dealer "
            f"{_up_label(node['up'])}  ·  carry {self.session.carry}×")
        best = node["best"].name
        self.evs = []
        for a in sorted(node["actions"], key=lambda a: -a.ev):
            self.evs.append({
                "name": a.name, "label": _ACTION_LABEL[a.name], "ev": a.ev,
                "best": a.name == best,
                "auto": reason if (auto == a.name) else None,
            })

    # ---- session callbacks ----------------------------------------------
    def _log(self, message):
        self.log_lines.append(message)
        del self.log_lines[:-_LOG_CAP]

    def _on_decision(self, node):
        self._show_node(node)
        self.dock_title = "YOUR MOVE"
        self.prompt = ""
        best = node["best"].name
        self.move_buttons = [{"name": a.name, "label": _ACTION_LABEL[a.name],
                              "best": a.name == best} for a in node["actions"]]

    def _on_auto(self, node, action, reason):
        self._show_node(node, auto=action, reason=reason)
        self.dock_title = "AUTO-PLAYED"
        self.prompt = f"Auto-played {_ACTION_LABEL[action]} — {reason}"
        self._log(f"  auto {_ACTION_LABEL[action]} — {reason} "
                  f"(hand total {node['total']} vs {_up_label(node['up'])})")

    def _on_card(self, ctx):
        self._card_ctx = ctx
        self.dock_title = "WHICH CARD CAME?"
        self.prompt = ctx["label"]

    def _on_dealer(self):
        self.dock_title = "DEALER'S FINAL TOTAL"
        self.prompt = ""

    def _on_round_done(self, summary):
        dealer = summary["dealer"]
        dtxt = "bust" if dealer in (None, "bust") else str(dealer)
        outcomes = summary["outcomes"]
        for i, oc in enumerate(outcomes, 1):
            label = f"hand {i}" if len(outcomes) > 1 else "result"
            note = f"win {oc['mult']}×" if oc["outcome"] == "win" else oc["outcome"]
            self._log(f"  {label}: {note}")
            if i - 1 < len(self.t_hands):
                self.t_hands[i - 1]["note"] = note
        self._log(f"  dealer {dtxt}  ·  carry {summary['old_carry']}× -> "
                  f"{summary['new_carry']}×")
        self.t_dealer_final = "bust" if dealer is None else dealer
        self.situation = (f"Round over — carry is now {summary['new_carry']}×."
                          "  Pick the next set and Deal.")
        self.phase = "setup"

    # ---- snapshot --------------------------------------------------------
    def snapshot(self):
        s = self.session
        return {
            "carry": s.carry, "round": s.round_no,
            "phase": self.phase, "pending": s.pending,
            "dock_title": self.dock_title, "prompt": self.prompt,
            "situation": self.situation, "evs": self.evs,
            "move_buttons": self.move_buttons if s.pending == "action" else [],
            "card_ctx": self._card_ctx if s.pending == "card" else None,
            "table": {
                "set": self.t_set, "dealer_up": self.t_dealer_up,
                "dealer_final": self.t_dealer_final, "hands": self.t_hands,
            },
            "log": self.log_lines,
            "settings": {"auto": s.auto, "threshold": round(s.threshold, 2),
                         "start_carry": s.start_carry, "store": self.store},
            "tiers": [dict(t) for t in TIERS],
            "bj_values": list(TIER_BJ_VALUES),
        }


class App:
    """Owns the solution, the session, the view and the request lock."""

    def __init__(self, config=None):
        self.solution = Solution.load_or_solve(MultiplierModel.empirical(),
                                                config or GameConfig())
        self._new_session()

    def _new_session(self):
        self.session = Session(self.solution, start_carry=1, auto=True,
                               threshold=0.20)
        self.view = _View(self.session)
        self.view._log("Pick the revealed set, enter your hand and the dealer "
                       "upcard, then Deal.")

    # ---- actions (each returns the snapshot) ----------------------------
    def state(self, _body):
        return self.view.snapshot()

    def deal(self, body):
        v, s = self.view, self.session
        try:
            cards = parse_hand(str(body.get("hand", "")))
            if len(cards) < 2:
                raise ValueError("enter at least two cards, e.g. 10,6")
            up = parse_card(str(body.get("up", "")))
            bj = int(body.get("bj"))
            tier = next(dict(t) for t in TIERS if t["BJ"] == bj)
        except (ValueError, KeyError, TypeError, StopIteration) as e:
            v._log(f"! {e}")
            return v.snapshot()
        if v.store:
            path = record_observed_set(dict(tier), path=v.session_hist_path)
            v._log(f"  recorded set (BJ {tier['BJ']}×) -> {os.path.basename(path)}")
        s.start_round(dict(tier))
        v.t_dealer_up, v.t_dealer_final = up, None
        v.t_set = dict(tier)
        v.pair_rank = cards[0]
        v.t_hands = [{"cards": list(cards), "label": "YOU", "note": ""}]
        v._log(f"\n----- Round {s.round_no} (carry {s.carry}×) -----")
        v._log(f"set {describe_set(tier)}; hand {hand_str(cards)} vs dealer "
               f"{_up_label(up)}")
        v.phase = "play"
        s.deal(cards, up)
        return v.snapshot()

    def choose(self, body):
        if self.session.pending == "action":
            self.session.choose(str(body.get("action")))
        return self.view.snapshot()

    def card(self, body):
        if self.session.pending == "card":
            self.view.play_card(int(body.get("rank")))
        return self.view.snapshot()

    def dealer(self, body):
        if self.session.pending == "dealer":
            val = body.get("value")
            self.session.dealer("bust" if val in (None, "bust") else int(val))
        return self.view.snapshot()

    def reset(self, _body):
        self._new_session()
        self.view._log("— reset — fresh session, carry 1× —")
        return self.view.snapshot()

    def settings(self, body):
        s, v = self.session, self.view
        if "auto" in body:
            s.auto = bool(body["auto"])
        if "threshold" in body:
            s.threshold = round(float(body["threshold"]), 2)
        if "start_carry" in body:
            s.start_carry = int(body["start_carry"])
            if s.round_no == 1 and s.pending is None:
                s.carry = s.start_carry
        if "store" in body:
            v.store = bool(body["store"])
            v._log("  histogram recording " + ("ON — each dealt set is saved"
                                               if v.store else "off"))
        return v.snapshot()

    def stats(self, body):
        try:
            n = int(body.get("last_n")) if body.get("last_n") else None
        except (ValueError, TypeError):
            n = None
        all_counts, all_total = overall_tier_counts()
        sess_counts, sess_total = observed_tier_counts(
            path=self.view.session_hist_path, within_hours=2, last_n=n)
        return {
            "bj_values": list(TIER_BJ_VALUES),
            "all": {"counts": all_counts, "total": all_total},
            "session": {"counts": sess_counts, "total": sess_total, "last_n": n},
        }


_ROUTES = {
    "/api/state": "state", "/api/deal": "deal", "/api/choose": "choose",
    "/api/card": "card", "/api/dealer": "dealer", "/api/reset": "reset",
    "/api/settings": "settings", "/api/stats": "stats",
}


def _make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 but every response says ``Connection: close`` — one request
        # per socket. Reusing a kept-alive socket was a source of hangs on the
        # phone, and there is no throughput reason to keep it open here.
        protocol_version = "HTTP/1.1"
        timeout = _SOCK_TIMEOUT

        # Route the stdlib's own access/error lines through our logger so the
        # console shows a single, consistent, timestamped stream.
        def log_message(self, fmt, *args):
            DEBUG.add("http  " + (fmt % args))

        def log_error(self, fmt, *args):
            DEBUG.add("http! " + (fmt % args))

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, (bytes, bytearray)) else body.encode("utf-8")
            self.close_connection = True
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except OSError as e:            # client hung up mid-write; not fatal
                DEBUG.add(f"send failed ({code}): {e!r}")

        def do_GET(self):
            t0 = time.monotonic()
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                try:
                    with open(_INDEX, "rb") as fh:
                        html = fh.read()
                    self._send(200, html, "text/html; charset=utf-8")
                    code = 200
                except OSError as e:
                    self._send(500, b"index.html missing", "text/plain")
                    code = 500
                    DEBUG.add(f"index read failed: {e!r}")
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                code = 204
            elif path == "/api/debug":
                self._send(200, json.dumps({"build": _BUILD, "lines": DEBUG.tail()}))
                code = 200
            else:
                self._send(404, b"not found", "text/plain")
                code = 404
            DEBUG.add(f"GET  {path} -> {code}  ({(time.monotonic()-t0)*1000:.0f} ms)")

        def do_POST(self):
            t0 = time.monotonic()
            path = self.path.split("?", 1)[0]
            name = _ROUTES.get(path)
            if name is None:
                self._send(404, b'{"error":"not found"}')
                DEBUG.add(f"POST {path} -> 404 (no such route)")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
            except (ValueError, OSError) as e:
                self._send(400, b'{"error":"bad body"}')
                DEBUG.add(f"POST {path} -> 400 (body read: {e!r})")
                return
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._send(400, b'{"error":"bad json"}')
                DEBUG.add(f"POST {path} -> 400 (bad json)")
                return
            try:
                result = getattr(app, name)(body)
            except Exception as e:          # one bad request must never kill the server
                self._send(500, json.dumps({"error": str(e)}))
                DEBUG.add(f"POST {path} -> 500 ({e!r})")
                return
            self._send(200, json.dumps(result))
            DEBUG.add(f"POST {path} -> 200  ({(time.monotonic()-t0)*1000:.0f} ms)")

    return Handler


def run(config=None, host="127.0.0.1", port=8000):
    app = App(config)
    httpd = HTTPServer((host, port), _make_handler(app))
    shown = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    DEBUG.add(f"=== Lightning Blackjack web app — build {_BUILD} ===")
    print(f"serving at  http://{shown}:{port}", flush=True)
    print(f"open that EXACT address in Safari (use {shown}, not 'localhost'),",
          flush=True)
    print("then Share -> Add to Home Screen.  Ctrl-C to stop.", flush=True)
    print("--- live request log (also on the phone via the bug button) ---",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    finally:
        httpd.server_close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="lbj_solver.webserver",
                                description="Web front-end for the LBJ solver")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (127.0.0.1 = this device only; "
                        "0.0.0.0 = reachable over the LAN)")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
