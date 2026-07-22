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
import selectors
import socket
import time

from .cli import parse_card, parse_hand
from .config import GameConfig
from .multipliers import (MultiplierModel, TIERS, TIER_BJ_VALUES,
                          new_session_file, observed_tier_counts,
                          overall_tier_counts, record_observed_set)
from .session import Session, hand_str
from .solution import Solution
from .strategy import describe_set

# Bump on every server-behaviour change so a phone can confirm what it runs.
_BUILD = "4 · non-blocking event loop"

_HERE = os.path.dirname(__file__)
_INDEX = os.path.join(_HERE, "web", "index.html")

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


_STATUS = {200: "OK", 400: "Bad Request", 404: "Not Found",
           405: "Method Not Allowed", 500: "Internal Server Error"}


def _response(code, body, ctype):
    """A complete HTTP/1.1 response as bytes. Always closes the connection."""
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


def _dispatch(app, method, path, body):
    """Route one parsed request to a response (never raises)."""
    p = path.split("?", 1)[0]
    if method == "GET":
        if p in ("/", "/index.html"):
            try:
                with open(_INDEX, "rb") as fh:
                    return _response(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                return _response(500, b"index.html missing", "text/plain")
        return _response(404, b"not found", "text/plain")
    if method == "POST":
        name = _ROUTES.get(p)
        if name is None:
            return _response(404, b'{"error":"not found"}', "application/json")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return _response(400, b'{"error":"bad json"}', "application/json")
        try:
            result = getattr(app, name)(data)
        except Exception as e:  # one bad request must never kill the server
            return _response(500, json.dumps({"error": str(e)}), "application/json")
        return _response(200, json.dumps(result), "application/json")
    return _response(405, b"method not allowed", "text/plain")


class _Conn:
    """Per-connection parse/serve state held by the event loop."""
    __slots__ = ("sock", "inbuf", "outbuf", "last")

    def __init__(self, sock, now):
        self.sock = sock
        self.inbuf = bytearray()
        self.outbuf = b""
        self.last = now

    def parse(self):
        """``(method, path, body)`` once the whole request is buffered, else None."""
        sep = self.inbuf.find(b"\r\n\r\n")
        if sep == -1:
            return None
        lines = bytes(self.inbuf[:sep]).decode("latin1").split("\r\n")
        try:
            method, path, _ = lines[0].split(" ", 2)
        except ValueError:
            return "", "", b""            # malformed request line; dispatch 4xx
        clen = 0
        for line in lines[1:]:
            k, _, v = line.partition(":")
            if k.strip().lower() == "content-length":
                try:
                    clen = int(v.strip())
                except ValueError:
                    clen = 0
        body = self.inbuf[sep + 4:]
        if len(body) < clen:
            return None                   # body still on the wire
        return method, path, bytes(body[:clen])


def _listen_sockets(host, port):
    """Bind IPv4 and (best-effort) IPv6 so ``http://localhost`` is fast either way.

    A browser resolving ``localhost`` may try ``::1`` before ``127.0.0.1``; if we
    listen on only one family the other attempt stalls (Happy-Eyeballs fallback),
    which surfaces as a multi-second page load. Binding both removes the stall.
    """
    families = [(socket.AF_INET, host)]
    if host == "127.0.0.1":
        families.append((socket.AF_INET6, "::1"))
    elif host == "0.0.0.0":
        families.append((socket.AF_INET6, "::"))
    socks = []
    for family, addr in families:
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                try:
                    s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                except OSError:
                    pass
            s.bind((addr, port))
            s.listen(64)
            s.setblocking(False)
            socks.append(s)
        except OSError:
            pass          # e.g. IPv6 unavailable in the sandbox — IPv4 suffices
    if not socks:
        raise OSError(f"could not bind {host}:{port}")
    return socks


def _close(sel, sock):
    try:
        sel.unregister(sock)
    except (KeyError, ValueError):
        pass
    try:
        sock.close()
    except OSError:
        pass


def _accept(sel, lsock):
    try:
        csock, _addr = lsock.accept()
    except OSError:
        return
    csock.setblocking(False)
    try:
        csock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    sel.register(csock, selectors.EVENT_READ, _Conn(csock, time.monotonic()))


def _flush(sel, conn):
    try:
        sent = conn.sock.send(conn.outbuf)
    except (BlockingIOError, InterruptedError):
        return
    except OSError:
        _close(sel, conn.sock)
        return
    conn.outbuf = conn.outbuf[sent:]
    conn.last = time.monotonic()
    if not conn.outbuf:
        _close(sel, conn.sock)            # Connection: close — one shot, done


def _read(sel, app, conn):
    try:
        chunk = conn.sock.recv(65536)
    except (BlockingIOError, InterruptedError):
        return
    except OSError:
        _close(sel, conn.sock)
        return
    if not chunk:                         # client closed
        _close(sel, conn.sock)
        return
    conn.inbuf += chunk
    conn.last = time.monotonic()
    if len(conn.inbuf) > 2_000_000:       # runaway-request guard
        _close(sel, conn.sock)
        return
    parsed = conn.parse()
    if parsed is None:
        return                            # need more bytes
    method, path, body = parsed
    conn.outbuf = _dispatch(app, method, path, body)
    sel.modify(conn.sock, selectors.EVENT_WRITE, conn)
    _flush(sel, conn)


def _reap(sel, idle):
    """Drop connections idle longer than ``idle`` seconds (dataless preconnects)."""
    now = time.monotonic()
    stale = [k.fileobj for k in list(sel.get_map().values())
             if k.data is not None and now - k.data.last > idle]
    for sock in stale:
        _close(sel, sock)


def run(config=None, host="127.0.0.1", port=8000):
    app = App(config)
    listeners = _listen_sockets(host, port)
    sel = selectors.DefaultSelector()
    for ls in listeners:
        sel.register(ls, selectors.EVENT_READ, None)   # data=None marks a listener
    shown = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Lightning Blackjack web app (build {_BUILD})", flush=True)
    print(f"serving at http://{shown}:{port}", flush=True)
    print("Open that in Safari, then Share → Add to Home Screen.", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        while True:
            for key, _mask in sel.select(timeout=5.0):
                if key.data is None:               # a listening socket
                    _accept(sel, key.fileobj)
                elif key.data.outbuf:              # mid-response
                    _flush(sel, key.data)
                else:                              # request bytes arriving
                    _read(sel, app, key.data)
            _reap(sel, idle=15.0)
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        sel.close()
        for ls in listeners:
            ls.close()


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
