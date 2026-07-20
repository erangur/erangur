"""Tkinter GUI for the Lightning Blackjack solver.

A graphical version of the continuous ``wizard``, laid out for a live table where
you have only a few seconds per decision. The design is **one screen, no tabs, no
scrolling**:

* a fixed header (carry / round, plus ⚙ settings and 📊 stats popovers, and
  Reset/Bust);
* an always-visible felt table with the dealt cards;
* a compact EV read-out (a chip per action, the optimal one in gold);
* a **morphing dock** pinned to the bottom whose contents swap by phase — the
  revealed-set / hand / upcard / Deal fields between rounds, big action keys on
  your turn, then card-entry and dealer-result keys as the hand plays out.

Because the board and read-out never move and the dock is always in the same
spot, the controls you need land in the same place every hand.

Two conveniences over the CLI wizard:

* **Auto-play** — trivial and high-conviction decisions are played for you (see
  ``session.auto_action``); tune it in the ⚙ settings popover.
* **Reset / Bust** — one button drops the carry back to fresh at any time.

Pure standard library (tkinter), no third-party dependency. Launch with::

    python -m lbj_solver.cli gui
    python -m lbj_solver.gui           # equivalent
"""

import os
import tkinter as tk
from tkinter import font as tkfont

from .cards import hand_from_cards
from .cli import parse_card, parse_hand
from .config import GameConfig
from .engine import DOUBLE, HIT, SPLIT, STAND
from .multipliers import (MultiplierModel, TIERS, TIER_BJ_VALUES,
                          new_session_file, observed_tier_counts,
                          overall_tier_counts, record_observed_set)
from .session import Session, hand_str
from .solution import Solution
from .strategy import describe_set

# ---- dark casino palette ---------------------------------------------------
_BG = "#101b16"          # window ground (deep felt-black)
_BAR = "#182821"         # header / dock bars
_PANEL = "#0d1813"       # recessed read-out
_LINE = "#25382e"
_INK = "#e9f1eb"
_MUTED = "#93a99b"
_GOLD = "#d9a52c"
_GOLD_HOVER = "#eebb47"
_GOLD_INK = "#2a1f04"
_KEY = "#2a3b33"         # neutral button
_KEY_HOVER = "#374c41"
_KEY_INK = "#e7efe9"
_GOOD = "#5cc088"
_BAD = "#e58067"
_DANGER = "#c0563f"
_DANGER_HOVER = "#d16a52"
_DISABLED = "#1c2a23"
_DISABLED_FG = "#51625a"

# Felt / card cosmetics. Suits are decorative only — the model is suitless
# (infinite deck by rank), so a stable suit is derived per card position.
_FELT = "#2c6b4a"
_FELT_2 = "#215139"
_SUITS = [("♠", "#16110a"), ("♣", "#16110a"),
          ("♥", "#c0392b"), ("♦", "#c0392b")]
_CARD_W, _CARD_H, _CARD_DX = 56, 80, 33    # card size + horizontal overlap step
_CARD_R = 8                                # card corner radius

# Quick-entry card buttons (10 covers J/Q/K).
_CARD_BUTTONS = [("A", 11)] + [(str(n), n) for n in range(2, 11)]
# Dealer under S17 always finishes 17-21 or busts.
_DEALER_BUTTONS = [("17", 17), ("18", 18), ("19", 19), ("20", 20), ("21", 21),
                   ("Bust", "bust")]
_ACTION_LABEL = {STAND: "Stand", HIT: "Hit", DOUBLE: "Double", SPLIT: "Split"}


def _up_label(up):
    return "A" if up == 11 else str(up)


def _rank_text(rank):
    return "A" if rank == 11 else str(rank)


def _total_text(cards):
    if not cards:
        return ""
    total, soft = hand_from_cards(cards)
    if total > 21:
        return f"{total} · BUST"
    return f"soft {total}" if soft else f"{total}"


def _ui_family(root):
    """Pick the nicest available UI font, degrading gracefully per platform."""
    prefer = ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Roboto", "Ubuntu",
              "DejaVu Sans", "Arial")
    try:
        families = set(tkfont.families(root))
    except tk.TclError:
        return "TkDefaultFont"
    for fam in prefer:
        if fam in families:
            return fam
    return "TkDefaultFont"


def _round_points(x1, y1, x2, y2, r):
    """Control points for a rounded rectangle drawn as a smoothed polygon."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    return canvas.create_polygon(_round_points(x1, y1, x2, y2, r),
                                 smooth=True, **kw)


class RoundedButton(tk.Canvas):
    """A flat, rounded push-button drawn on a canvas (ttk can't round corners).

    Supports hover feedback, an enabled/disabled state, and a ``selected``
    visual used to build single-select toggle rows.
    """

    def __init__(self, parent, text="", command=None, *, width=110, height=42,
                 radius=13, fill=_KEY, hover=_KEY_HOVER, fg=_KEY_INK,
                 selected_fill=_GOLD, selected_fg=_GOLD_INK, font=None,
                 surface=_BG):
        super().__init__(parent, width=width, height=height, bg=surface,
                         highlightthickness=0, bd=0, takefocus=0)
        self.command = command
        self._fill, self._hover, self._fg = fill, hover, fg
        self._sel_fill, self._sel_fg = selected_fill, selected_fg
        self._radius = radius
        self._selected = False
        self._enabled = True
        self._shape = _round_rect(self, 1, 1, width - 1, height - 1, radius,
                                  fill=fill, outline="")
        self._text_id = self.create_text(width / 2, height / 2, text=text,
                                          fill=fg, font=font)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_configure(self, e):
        self.coords(self._shape,
                    *_round_points(1, 1, e.width - 1, e.height - 1, self._radius))
        self.coords(self._text_id, e.width / 2, e.height / 2)

    def _paint(self, fill, fg):
        self.itemconfigure(self._shape, fill=fill)
        self.itemconfigure(self._text_id, fill=fg)

    def _restore(self):
        if not self._enabled:
            self._paint(_DISABLED, _DISABLED_FG)
        elif self._selected:
            self._paint(self._sel_fill, self._sel_fg)
        else:
            self._paint(self._fill, self._fg)

    def _on_enter(self, _e):
        if self._enabled and not self._selected:
            self._paint(self._hover, self._fg)

    def _on_leave(self, _e):
        self._restore()

    def _on_press(self, _e):
        if self._enabled and not self._selected:
            self._paint(self._hover, self._fg)

    def _on_release(self, _e):
        if not self._enabled:
            return
        self._restore()
        if self.command:
            self.command()

    def set_selected(self, value):
        self._selected = bool(value)
        self._restore()

    def set_text(self, text):
        self.itemconfigure(self._text_id, text=text)

    def set_enabled(self, value):
        self._enabled = bool(value)
        self._restore()


class LBJGui:
    def __init__(self, root, sol):
        self.root = root
        self.session = Session(sol, start_carry=1, auto=True, threshold=0.20)
        s = self.session
        s.on_log = self._log
        s.on_decision = self._on_decision
        s.on_auto = self._on_auto
        s.on_card = self._on_card
        s.on_dealer = self._on_dealer
        s.on_round_done = self._on_round_done

        # Table view-model (what the canvas draws).
        self.t_dealer_up = None
        self.t_dealer_final = None
        self.t_hands = []
        self.t_set = None
        self.pair_rank = None
        self._card_ctx = None
        self._settings_win = None
        self._stats_win = None
        self.session_hist_path = new_session_file()

        # Settings state (widgets built lazily in the ⚙ popover).
        self.auto_var = tk.BooleanVar(value=True)
        self.thr_var = tk.DoubleVar(value=0.20)
        self.start_carry_var = tk.IntVar(value=1)
        self.store_hist_var = tk.BooleanVar(value=False)
        self.hist_n_var = tk.IntVar(value=100)
        self.thr_lbl = None

        root.title("Lightning Blackjack — Optimal Strategy")
        root.configure(bg=_BG)
        root.minsize(900, 700)
        root.geometry("940x760")
        self._init_fonts()
        self._build()
        self._sync_status()
        self._phase("setup")
        self._log("Pick the revealed set, enter your hand and the dealer upcard, "
                  "then Deal.")

    def _init_fonts(self):
        fam = _ui_family(self.root)
        self.f_base = (fam, 11)
        self.f_bold = (fam, 11, "bold")
        self.f_carry = (fam, 22, "bold")
        self.f_lead = (fam, 13, "bold")
        self.f_small = (fam, 9)
        self.f_label = (fam, 9, "bold")
        self.f_deal = (fam, 16, "bold")
        self.f_key = (fam, 13, "bold")
        self.f_chip = (fam, 11, "bold")

    # ------------------------------------------------------------ small parts
    def _btn(self, parent, text, command, *, surface=_BG, **kw):
        kw.setdefault("font", self.f_key if kw.get("height", 0) >= 46 else self.f_bold)
        return RoundedButton(parent, text=text, command=command, surface=surface,
                             **kw)

    def _lbl(self, parent, text="", *, bg, fg=_INK, font=None):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=font or self.f_base)

    def _radio_row(self, parent, options, var, *, on_change=None, width=48,
                   height=38, radius=11, surface=_BAR):
        """A single-select row of rounded toggle buttons bound to ``var``."""
        buttons = {}

        def select(value):
            var.set(value)
            for val, btn in buttons.items():
                btn.set_selected(val == value)
            if on_change:
                on_change()

        for label, value in options:
            btn = self._btn(parent, label, lambda v=value: select(v),
                            width=width, height=height, radius=radius,
                            surface=surface)
            btn.pack(side="left", padx=3)
            buttons[value] = btn
        select(var.get())
        return buttons, select

    # ------------------------------------------------------------------ build
    def _build(self):
        # ---- header ------------------------------------------------------
        head = tk.Frame(self.root, bg=_BAR)
        head.pack(fill="x")
        headpad = tk.Frame(head, bg=_BAR)
        headpad.pack(fill="x", padx=16, pady=10)
        self.carry_var = tk.StringVar()
        self.round_var = tk.StringVar()
        tk.Label(headpad, textvariable=self.carry_var, bg=_BAR, fg=_GOLD,
                 font=self.f_carry).pack(side="left")
        tk.Label(headpad, textvariable=self.round_var, bg=_BAR, fg=_MUTED,
                 font=(self.f_base[0], 12)).pack(side="left", padx=16)
        self._btn(headpad, "Reset / Bust", self._reset, width=132, height=40,
                  fill=_KEY, hover=_KEY_HOVER, fg=_DANGER,
                  surface=_BAR).pack(side="right")
        self._btn(headpad, "📊", self._open_stats, width=42, height=40,
                  fill=_KEY, hover=_KEY_HOVER, surface=_BAR).pack(side="right", padx=6)
        self._btn(headpad, "⚙", self._open_settings, width=42, height=40,
                  fill=_KEY, hover=_KEY_HOVER, surface=_BAR).pack(side="right")

        # ---- felt table --------------------------------------------------
        self.canvas = tk.Canvas(self.root, height=252, bg=_FELT,
                                highlightthickness=0)
        self.canvas.pack(fill="x")
        self.canvas.bind("<Configure>", lambda e: self._draw_table())

        # ---- EV read-out -------------------------------------------------
        readout = tk.Frame(self.root, bg=_PANEL)
        readout.pack(fill="x")
        rpad = tk.Frame(readout, bg=_PANEL)
        rpad.pack(fill="x", padx=16, pady=10)
        self.situation_var = tk.StringVar(value="—")
        tk.Label(rpad, textvariable=self.situation_var, bg=_PANEL, fg=_INK,
                 font=self.f_lead, anchor="w").pack(fill="x")
        self.ev_frame = tk.Frame(rpad, bg=_PANEL)
        self.ev_frame.pack(fill="x", pady=(8, 0))

        # ---- morphing dock ----------------------------------------------
        dock = tk.Frame(self.root, bg=_BAR)
        dock.pack(fill="x")
        self.dockpad = tk.Frame(dock, bg=_BAR)
        self.dockpad.pack(fill="x", padx=16, pady=12)
        self.dock_title_var = tk.StringVar(value="New round")
        tk.Label(self.dockpad, textvariable=self.dock_title_var, bg=_BAR,
                 fg=_MUTED, font=self.f_label, anchor="w").pack(fill="x",
                                                                pady=(0, 10))

        # setup panel (persistent widgets, shown between rounds)
        self.setup_panel = tk.Frame(self.dockpad, bg=_BAR)
        self._build_setup_panel(self.setup_panel)
        # action panel (dynamic controls, shown during play)
        self.action_panel = tk.Frame(self.dockpad, bg=_BAR)
        self.prompt_var = tk.StringVar(value="")
        tk.Label(self.action_panel, textvariable=self.prompt_var, bg=_BAR,
                 fg=_MUTED, font=self.f_base, anchor="w").pack(fill="x",
                                                               pady=(0, 8))
        self.controls = tk.Frame(self.action_panel, bg=_BAR)
        self.controls.pack(fill="x")

        # ---- history -----------------------------------------------------
        logf = tk.Frame(self.root, bg=_BG)
        logf.pack(fill="both", expand=True, padx=16, pady=(10, 12))
        tk.Label(logf, text="HISTORY", bg=_BG, fg=_MUTED,
                 font=self.f_label, anchor="w").pack(fill="x", pady=(0, 4))
        logbox = tk.Frame(logf, bg=_PANEL)
        logbox.pack(fill="both", expand=True)
        self.log_text = tk.Text(logbox, height=5, wrap="word", state="disabled",
                                relief="flat", bg=_PANEL, fg=_INK,
                                font=self.f_base, padx=10, pady=8,
                                highlightthickness=0, insertbackground=_INK)
        sb = tk.Scrollbar(logbox, command=self.log_text.yview, bg=_BAR,
                          troughcolor=_PANEL, bd=0, highlightthickness=0)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    def _build_setup_panel(self, parent):
        # revealed set
        row1 = tk.Frame(parent, bg=_BAR)
        row1.pack(fill="x", pady=3)
        self._lbl(row1, "SET", bg=_BAR, fg=_MUTED, font=self.f_label).pack(
            side="left", padx=(0, 10))
        self.set_choice = tk.StringVar(value=str(TIER_BJ_VALUES[0]))
        self.set_body_var = tk.StringVar()
        self.set_buttons, self.set_select = self._radio_row(
            row1, [(f"BJ {bj}x", str(bj)) for bj in TIER_BJ_VALUES],
            self.set_choice, on_change=self._update_set_label, width=66)
        tk.Label(row1, textvariable=self.set_body_var, bg=_BAR, fg=_MUTED,
                 font=self.f_base).pack(side="left", padx=(12, 0))

        # your hand
        row2 = tk.Frame(parent, bg=_BAR)
        row2.pack(fill="x", pady=3)
        self._lbl(row2, "HAND", bg=_BAR, fg=_MUTED, font=self.f_label).pack(
            side="left", padx=(0, 10))
        self.hand_var = tk.StringVar()
        tk.Entry(row2, textvariable=self.hand_var, width=10, font=self.f_base,
                 bg=_PANEL, fg=_INK, insertbackground=_INK, relief="flat",
                 highlightthickness=1, highlightbackground=_LINE,
                 highlightcolor=_GOLD).pack(side="left", padx=(0, 10), ipady=5)
        for label, _rank in _CARD_BUTTONS:
            self._btn(row2, label, lambda l=label: self._append_hand(l),
                      width=42, height=38, radius=11, surface=_BAR).pack(
                side="left", padx=2)
        self._btn(row2, "Clear", lambda: self.hand_var.set(""), width=58,
                  height=38, radius=11, surface=_BAR).pack(side="left", padx=(8, 0))

        # dealer upcard
        row3 = tk.Frame(parent, bg=_BAR)
        row3.pack(fill="x", pady=3)
        self._lbl(row3, "UPCARD", bg=_BAR, fg=_MUTED, font=self.f_label).pack(
            side="left", padx=(0, 10))
        self.up_choice = tk.StringVar(value="10")
        self.up_buttons, self.up_select = self._radio_row(
            row3, [(label, label) for label, _r in _CARD_BUTTONS],
            self.up_choice, width=42)

        # deal
        self.deal_btn = self._btn(parent, "DEAL", self._deal, height=54,
                                  radius=15, fill=_GOLD, hover=_GOLD_HOVER,
                                  fg=_GOLD_INK, font=self.f_deal, surface=_BAR)
        self.deal_btn.pack(fill="x", pady=(10, 0))
        self._update_set_label()

    # ---------------------------------------------------------- table canvas
    def _draw_card(self, x, y, rank, suit_idx):
        cv, w, h = self.canvas, _CARD_W, _CARD_H
        glyph, color = _SUITS[suit_idx % 4]
        _round_rect(cv, x + 2, y + 3, x + w + 2, y + h + 3, _CARD_R,
                    fill="#183524", outline="")                 # soft shadow
        _round_rect(cv, x, y, x + w, y + h, _CARD_R, fill="#fbfbf7",
                    outline="#d8ddce")
        t = _rank_text(rank)
        cv.create_text(x + 7, y + 6, text=t, anchor="nw", fill=color,
                       font=("TkDefaultFont", 12, "bold"))
        cv.create_text(x + w / 2, y + h / 2 + 4, text=glyph, fill=color,
                       font=("TkDefaultFont", 24, "bold"))

    def _draw_back(self, x, y):
        cv, w, h = self.canvas, _CARD_W, _CARD_H
        _round_rect(cv, x + 2, y + 3, x + w + 2, y + h + 3, _CARD_R,
                    fill="#183524", outline="")
        _round_rect(cv, x, y, x + w, y + h, _CARD_R, fill="#2c4a86",
                    outline="#16294d")
        _round_rect(cv, x + 7, y + 7, x + w - 7, y + h - 7, _CARD_R - 3,
                    fill="", outline="#7f97c8")

    def _draw_hand(self, x0, y, cards, label, note):
        cv = self.canvas
        cv.create_text(x0, y - 20, text=label, anchor="nw", fill="#e8f4ec",
                       font=("TkDefaultFont", 10, "bold"))
        x = x0
        for ci, rank in enumerate(cards):
            self._draw_card(x, y, rank, ci + 1)   # decorative, stable per index
            x += _CARD_DX
        width = _CARD_DX * (len(cards) - 1) + _CARD_W if cards else _CARD_W
        cv.create_text(x0 + width + 14, y + _CARD_H / 2, text=_total_text(cards),
                       anchor="w", fill="#f6f2c8",
                       font=("TkDefaultFont", 14, "bold"))
        if note:
            col = "#bff0bf" if "win" in note else "#f0c0c0"
            cv.create_text(x0, y + _CARD_H + 8, text=note, anchor="nw", fill=col,
                           font=("TkDefaultFont", 11, "bold"))
        return x0 + width + 70

    def _draw_table(self):
        cv = self.canvas
        cv.delete("all")
        # revealed-set indicator (top-right), once a round is live.
        if self.t_set is not None:
            w = cv.winfo_width() or 900
            body = "/".join(str(self.t_set[b]) for b in ("18", "19", "20", "21"))
            cv.create_text(w - 16, 16, anchor="ne", fill="#cfe4d6",
                           font=("TkDefaultFont", 11, "bold"),
                           text=f"SET  BJ {self.t_set['BJ']}×")
            cv.create_text(w - 16, 33, anchor="ne", fill="#9cc0aa",
                           font=("TkDefaultFont", 9), text=f"18-21: {body}")
        # Dealer row.
        cv.create_text(18, 12, text="DEALER", anchor="nw", fill="#a9c7b5",
                       font=("TkDefaultFont", 10, "bold"))
        if self.t_dealer_up is not None:
            x, y = 18, 30
            self._draw_card(x, y, self.t_dealer_up, 0)
            self._draw_back(x + _CARD_DX, y)
            if self.t_dealer_final is not None:
                txt = ("BUST" if self.t_dealer_final == "bust"
                       else f"= {self.t_dealer_final}")
                cv.create_text(x + _CARD_DX + _CARD_W + 16, y + _CARD_H / 2,
                               text=txt, anchor="w", fill="#f6f2c8",
                               font=("TkDefaultFont", 14, "bold"))
        # Player row (one hand, or two side by side after a split).
        x0, y = 18, 140
        for hand in self.t_hands:
            x0 = self._draw_hand(x0, y, hand["cards"], hand["label"], hand["note"])

    # ---- table view-model updates --------------------------------------
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
        self._draw_table()

    def _play_card(self, rank):
        ctx = self._card_ctx
        hand_no = ctx.get("hand_no") if ctx else None
        if hand_no:
            self._ensure_split_hands()
            self.t_hands[hand_no - 1]["cards"].append(rank)
        elif self.t_hands:
            self.t_hands[0]["cards"].append(rank)
        self._draw_table()
        self.session.card(rank)

    # -------------------------------------------------------------- helpers
    def _selected_tier(self):
        bj = int(self.set_choice.get())
        return TIERS[TIER_BJ_VALUES.index(bj)]

    def _update_set_label(self):
        tier = self._selected_tier()
        body = "/".join(str(tier[b]) for b in ("18", "19", "20", "21"))
        self.set_body_var.set(f"18-21: {body}")

    def _append_hand(self, label):
        cur = self.hand_var.get().strip()
        self.hand_var.set(f"{cur},{label}" if cur else label)

    def _clear_inputs(self):
        self.hand_var.set("")
        self.up_select("10")
        self.set_select(str(TIER_BJ_VALUES[0]))

    def _clear_controls(self):
        for w in self.controls.winfo_children():
            w.destroy()

    def _clear_evs(self):
        for w in self.ev_frame.winfo_children():
            w.destroy()

    def _log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _sync_status(self):
        self.carry_var.set(f"Carry {self.session.carry}×")
        self.round_var.set(f"Round {self.session.round_no}")

    def _chip(self, action, ev, *, best=False, auto_reason=None):
        text = f"{_ACTION_LABEL[action]}  {ev:+.3f}"
        if best:
            text += "  ◀ auto" if auto_reason else "  ◀"
            fg, bg = _GOLD_INK, _GOLD
        else:
            fg, bg = (_GOOD if ev >= 0 else _BAD), _KEY
        lbl = tk.Label(self.ev_frame, text=text, bg=bg, fg=fg, font=self.f_chip,
                       padx=11, pady=6)
        lbl.pack(side="left", padx=(0, 8))

    def _show_node(self, node, auto=None, reason=None):
        self._sync_hand(node)
        cards = hand_str(node["cards"])
        where = (f"Split hand {node['hand_no']}  {cards}" if node["hand_no"]
                 else f"Hand {cards}")
        self.situation_var.set(
            f"{where}  ·  total {node['total']}  vs dealer {_up_label(node['up'])}"
            f"  ·  carry {self.session.carry}×")
        best = node["best"].name
        self._clear_evs()
        for a in sorted(node["actions"], key=lambda a: -a.ev):
            self._chip(a.name, a.ev, best=(a.name == best),
                       auto_reason=(reason if auto == a.name else None))

    # --------------------------------------------------------------- phases
    def _phase(self, name):
        """Swap the dock between the setup fields and the action controls."""
        if name == "setup":
            self.action_panel.pack_forget()
            self.setup_panel.pack(fill="x")
            self.dock_title_var.set("NEW ROUND")
        else:
            self.setup_panel.pack_forget()
            self.action_panel.pack(fill="x")

    # ---------------------------------------------------- settings popover
    def _open_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        win = tk.Toplevel(self.root, bg=_BG)
        self._settings_win = win
        win.title("Settings")
        win.configure(padx=18, pady=16)
        win.transient(self.root)

        tk.Checkbutton(win, text="Auto-play trivial / high-conviction decisions",
                       variable=self.auto_var, command=self._on_auto_toggle,
                       bg=_BG, fg=_INK, selectcolor=_KEY, activebackground=_BG,
                       activeforeground=_INK, font=self.f_base,
                       highlightthickness=0, bd=0).grid(row=0, column=0,
                                                        columnspan=3, sticky="w",
                                                        pady=(0, 10))
        tk.Label(win, text="Conviction threshold", bg=_BG, fg=_INK,
                 font=self.f_base).grid(row=1, column=0, sticky="w")
        tk.Scale(win, from_=0.0, to=1.0, resolution=0.01, orient="horizontal",
                 variable=self.thr_var, command=self._on_thr, length=220,
                 bg=_BG, fg=_INK, troughcolor=_KEY, highlightthickness=0,
                 activebackground=_GOLD, bd=0, showvalue=False).grid(
            row=1, column=1, padx=10)
        self.thr_lbl = tk.Label(win, text=f"{self.thr_var.get():.2f}", bg=_BG,
                                fg=_GOLD, font=self.f_bold, width=5)
        self.thr_lbl.grid(row=1, column=2, sticky="w")

        tk.Label(win, text="Starting carry", bg=_BG, fg=_INK,
                 font=self.f_base).grid(row=2, column=0, sticky="w", pady=(10, 0))
        tk.Spinbox(win, from_=1, to=25, width=5, textvariable=self.start_carry_var,
                   command=self._on_start_carry, bg=_PANEL, fg=_INK, relief="flat",
                   buttonbackground=_KEY, insertbackground=_INK,
                   highlightthickness=1, highlightbackground=_LINE,
                   font=self.f_base).grid(row=2, column=1, sticky="w",
                                          padx=10, pady=(10, 0))

        tk.Checkbutton(win, text="Store each round's set (for the histogram)",
                       variable=self.store_hist_var, bg=_BG, fg=_INK,
                       selectcolor=_KEY, activebackground=_BG,
                       activeforeground=_INK, font=self.f_base,
                       highlightthickness=0, bd=0).grid(row=3, column=0,
                                                        columnspan=3, sticky="w",
                                                        pady=(14, 0))
        self._btn(win, "Close", win.destroy, width=90, height=38,
                  surface=_BG).grid(row=4, column=0, columnspan=3, pady=(16, 0))

    def _on_auto_toggle(self):
        self.session.auto = self.auto_var.get()

    def _on_thr(self, _value):
        self.session.threshold = round(self.thr_var.get(), 2)
        if self.thr_lbl is not None and self.thr_lbl.winfo_exists():
            self.thr_lbl.configure(text=f"{self.session.threshold:.2f}")

    def _on_start_carry(self):
        self.session.start_carry = self.start_carry_var.get()
        if self.session.round_no == 1 and self.session.pending is None:
            self.session.carry = self.session.start_carry
            self._sync_status()

    def _reset(self):
        # A bust wipes the carry: always start fresh at 1×.
        self.session.start_carry = 1
        self.start_carry_var.set(1)
        self.session.reset()
        self._sync_status()
        self._clear_controls()
        self._clear_evs()
        self.prompt_var.set("")
        self.situation_var.set("—")
        self.t_dealer_up = self.t_dealer_final = self.t_set = None
        self.t_hands = []
        self._draw_table()
        self._phase("setup")
        self._clear_inputs()

    # ---------------------------------------------------------- stats popover
    _HIST_BLUE = "#4f8fe0"
    _HIST_RED = "#e07a63"

    def _open_stats(self):
        if self._stats_win is not None and self._stats_win.winfo_exists():
            self._stats_win.lift()
            return
        win = tk.Toplevel(self.root, bg=_BG)
        self._stats_win = win
        win.title("Multiplier histogram")
        win.configure(padx=14, pady=12)
        win.transient(self.root)

        ctl = tk.Frame(win, bg=_BG)
        ctl.pack(fill="x", pady=(0, 10))
        tk.Label(ctl, text="This session: last", bg=_BG, fg=_INK,
                 font=self.f_base).pack(side="left")
        tk.Spinbox(ctl, from_=1, to=100000, width=7, textvariable=self.hist_n_var,
                   bg=_PANEL, fg=_INK, relief="flat", buttonbackground=_KEY,
                   insertbackground=_INK, highlightthickness=1,
                   highlightbackground=_LINE, font=self.f_base).pack(side="left",
                                                                     padx=6)
        tk.Label(ctl, text="games (≤ 2 h)", bg=_BG, fg=_MUTED,
                 font=self.f_base).pack(side="left")
        cv = tk.Canvas(win, width=600, height=360, bg=_PANEL,
                       highlightthickness=0)
        cv.pack()
        self._btn(ctl, "Redraw", lambda: self._draw_histogram(cv), width=84,
                  height=34, surface=_BG).pack(side="right")
        self._btn(win, "Close", win.destroy, width=90, height=38,
                  surface=_BG).pack(pady=(10, 0))
        self._draw_histogram(cv)

    def _draw_histogram(self, cv):
        cv.delete("all")
        try:
            n = int(self.hist_n_var.get())
        except (tk.TclError, ValueError):
            n = None
        all_counts, all_total = overall_tier_counts()
        sess_counts, sess_total = observed_tier_counts(path=self.session_hist_path,
                                                       within_hours=2, last_n=n)
        W = int(cv["width"]) if str(cv["width"]).isdigit() else 600
        H = int(cv["height"]) if str(cv["height"]).isdigit() else 360
        if not all_total:
            cv.create_text(W / 2, H / 2, fill=_MUTED, font=self.f_base,
                           text="No rounds recorded yet — enable \"Store each\n"
                                "round's set\" in ⚙ Settings and play.")
            return
        ml, mr, mt, mb = 44, 16, 54, 50
        plot_h, plot_w = H - mt - mb, W - ml - mr
        bjs = list(TIER_BJ_VALUES)
        gw = plot_w / len(bjs)
        y0 = mt + plot_h

        def prop(counts, total, bj):
            return counts[bj] / total if total else 0.0

        maxp = max([prop(all_counts, all_total, b) for b in bjs] +
                   [prop(sess_counts, sess_total, b) for b in bjs] + [1e-9])
        cv.create_line(ml, y0, W - mr, y0, fill=_LINE)

        lx, ly = ml, 28
        for color, label in ((self._HIST_BLUE, f"All sessions (n={all_total})"),
                             (self._HIST_RED,
                              f"This session ≤2h, last {n} (n={sess_total})")):
            _round_rect(cv, lx, ly - 7, lx + 16, ly + 7, 4, fill=color, outline="")
            tid = cv.create_text(lx + 24, ly, text=label, anchor="w", fill=_INK,
                                 font=self.f_small)
            lx = cv.bbox(tid)[2] + 22

        def bar(x, w, counts, total, bj, color):
            h = plot_h * prop(counts, total, bj) / maxp
            if h < 1:
                return
            r = min(6, w / 2, h / 2)
            _round_rect(cv, x, y0 - h, x + w, y0 + r, r, fill=color, outline="")
            cv.create_text(x + w / 2, y0 - h - 9, fill=_INK, font=self.f_small,
                           text=f"{100 * prop(counts, total, bj):.0f}%")

        for i, bj in enumerate(bjs):
            x = ml + i * gw
            bw = gw * 0.34
            bar(x + gw * 0.11, bw, all_counts, all_total, bj, self._HIST_BLUE)
            bar(x + gw * 0.11 + bw + gw * 0.06, bw, sess_counts, sess_total, bj,
                self._HIST_RED)
            cv.create_text(x + gw / 2, y0 + 16, text=f"BJ {bj}×", fill=_MUTED,
                           font=self.f_small)

    # ------------------------------------------------------------ round flow
    def _deal(self):
        try:
            cards = parse_hand(self.hand_var.get())
            if len(cards) < 2:
                raise ValueError("enter at least two cards, e.g. 10,6")
            up = parse_card(self.up_choice.get())
        except (ValueError, KeyError) as e:
            self._log(f"! {e}")
            return
        tier = self._selected_tier()
        if self.store_hist_var.get():
            path = record_observed_set(dict(tier), path=self.session_hist_path)
            self._log(f"  recorded set (BJ {tier['BJ']}×) -> {os.path.basename(path)}")
        self.session.start_round(dict(tier))
        self.t_dealer_up, self.t_dealer_final = up, None
        self.t_set = dict(tier)
        self.pair_rank = cards[0]
        self.t_hands = [{"cards": list(cards), "label": "YOU", "note": ""}]
        self._draw_table()
        self._log(f"\n----- Round {self.session.round_no} (carry "
                  f"{self.session.carry}×) -----")
        self._log(f"set {describe_set(tier)}; hand {hand_str(cards)} vs dealer "
                  f"{_up_label(up)}")
        self._phase("play")
        self.session.deal(cards, up)

    def _on_decision(self, node):
        self._show_node(node)
        self.dock_title_var.set("YOUR MOVE")
        self.prompt_var.set("")
        self._clear_controls()
        best = node["best"].name
        for a in node["actions"]:
            emphasis = a.name == best
            self._btn(self.controls, _ACTION_LABEL[a.name],
                      lambda n=a.name: self.session.choose(n),
                      height=52, radius=14,
                      fill=_GOLD if emphasis else _KEY,
                      hover=_GOLD_HOVER if emphasis else _KEY_HOVER,
                      fg=_GOLD_INK if emphasis else _KEY_INK,
                      surface=_BAR).pack(side="left", fill="x", expand=True,
                                         padx=4)

    def _on_auto(self, node, action, reason):
        self._show_node(node, auto=action, reason=reason)
        self.dock_title_var.set("AUTO-PLAYED")
        self._clear_controls()
        self.prompt_var.set(f"Auto-played {_ACTION_LABEL[action]} — {reason}")
        self._log(f"  auto {_ACTION_LABEL[action]} — {reason} "
                  f"(hand total {node['total']} vs {_up_label(node['up'])})")

    def _on_card(self, ctx):
        self._card_ctx = ctx
        self.dock_title_var.set("WHICH CARD CAME?")
        self.prompt_var.set(ctx["label"])
        self._clear_controls()
        for label, rank in _CARD_BUTTONS:
            self._btn(self.controls, label, lambda r=rank: self._play_card(r),
                      width=40, height=48, radius=12,
                      surface=_BAR).pack(side="left", fill="x", expand=True,
                                         padx=3)

    def _on_dealer(self):
        self.dock_title_var.set("DEALER'S FINAL TOTAL")
        self.prompt_var.set("")
        self._clear_controls()
        for label, val in _DEALER_BUTTONS:
            danger = val == "bust"
            self._btn(self.controls, label, lambda v=val: self.session.dealer(v),
                      height=50, radius=12,
                      fill=_DANGER if danger else _KEY,
                      hover=_DANGER_HOVER if danger else _KEY_HOVER,
                      fg="white" if danger else _KEY_INK,
                      surface=_BAR).pack(side="left", fill="x", expand=True,
                                         padx=4)

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
        self._draw_table()
        self._sync_status()
        self._clear_controls()
        self._clear_evs()
        self.prompt_var.set("")
        self.situation_var.set(f"Round over — carry is now {summary['new_carry']}×."
                               "  Pick the next set and Deal.")
        self._phase("setup")
        self._clear_inputs()


def build_solution(config=None):
    return Solution.load_or_solve(MultiplierModel.empirical(),
                                  config or GameConfig())


def run(config=None):
    root = tk.Tk()
    LBJGui(root, build_solution(config))
    root.mainloop()


def main(argv=None):
    run()


if __name__ == "__main__":
    main()
