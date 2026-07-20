"""Tkinter GUI for the Lightning Blackjack solver.

A graphical version of the continuous ``wizard``: pick the revealed multiplier
set, punch in your hand and the dealer upcard, and the tool shows every action's
EV and the optimal play. You answer what you actually did and which card came;
the earned multiplier is carried straight into the next round.

Two conveniences over the CLI wizard:

* **Auto-play** — trivial and high-conviction decisions are played for you (see
  ``session.auto_action``); you are only asked about genuine choices. Toggle it
  and tune the conviction threshold live from the controls.
* **Reset / Bust** — one button drops the carry back to fresh at any time.

Pure standard library (tkinter), no third-party dependency. Launch with::

    python -m lbj_solver.cli gui
    python -m lbj_solver.gui           # equivalent
"""

import os
import tkinter as tk
from tkinter import ttk

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

# Felt / card cosmetics. Suits are decorative only — the model is suitless
# (infinite deck by rank), so a stable suit is derived per card position.
_FELT = "#35654d"
_SUITS = [("♠", "#111111"), ("♣", "#111111"),
          ("♥", "#c0392b"), ("♦", "#c0392b")]
_CARD_W, _CARD_H, _CARD_DX = 52, 74, 30   # card size + horizontal overlap step

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

        # Table view-model (what the canvas draws). Player hands are dicts
        # {cards, label, note}; there are two after a split.
        self.t_dealer_up = None
        self.t_dealer_final = None
        self.t_hands = []
        self.pair_rank = None
        self._card_ctx = None
        # This instance's own histogram file (created lazily on first record).
        self.session_hist_path = new_session_file()

        root.title("Lightning Blackjack — Optimal Strategy")
        root.minsize(760, 760)
        self._build()
        self._sync_status()
        self._phase("setup")
        self._log("Pick the revealed set, enter your hand and the dealer upcard, "
                  "then Deal.")

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = dict(padx=8, pady=4)

        # ---- header: carry / round / reset ------------------------------
        head = ttk.Frame(self.root)
        head.pack(fill="x", **pad)
        self.carry_var = tk.StringVar()
        self.round_var = tk.StringVar()
        ttk.Label(head, textvariable=self.carry_var,
                  font=("TkDefaultFont", 20, "bold")).pack(side="left")
        ttk.Label(head, textvariable=self.round_var,
                  font=("TkDefaultFont", 11)).pack(side="left", padx=16)
        ttk.Button(head, text="Reset / Bust", command=self._reset).pack(side="right")

        # ---- settings ---------------------------------------------------
        cfg = ttk.LabelFrame(self.root, text="Auto-play")
        cfg.pack(fill="x", **pad)
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text="Auto-play trivial / high-conviction decisions",
                        variable=self.auto_var,
                        command=self._on_auto_toggle).grid(row=0, column=0,
                                                           columnspan=3, sticky="w",
                                                           padx=6, pady=2)
        ttk.Label(cfg, text="Conviction threshold").grid(row=1, column=0, sticky="w",
                                                         padx=6)
        self.thr_var = tk.DoubleVar(value=0.20)
        self.thr_scale = ttk.Scale(cfg, from_=0.0, to=1.0, variable=self.thr_var,
                                   command=self._on_thr, length=220)
        self.thr_scale.grid(row=1, column=1, sticky="w")
        self.thr_lbl = ttk.Label(cfg, text="0.20", width=5)
        self.thr_lbl.grid(row=1, column=2, sticky="w")
        ttk.Label(cfg, text="Starting carry").grid(row=1, column=3, sticky="e", padx=6)
        self.start_carry_var = tk.IntVar(value=1)
        ttk.Spinbox(cfg, from_=1, to=25, width=4, textvariable=self.start_carry_var,
                    command=self._on_start_carry).grid(row=1, column=4, padx=6)

        # ---- histogram --------------------------------------------------
        hist = ttk.LabelFrame(self.root, text="Multiplier histogram")
        hist.pack(fill="x", **pad)
        self.store_hist_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(hist, text="Store each round's set",
                        variable=self.store_hist_var).pack(side="left", padx=6, pady=4)
        ttk.Button(hist, text="Show histogram",
                   command=self._show_histogram).pack(side="left", padx=6)
        ttk.Label(hist, text="last N games").pack(side="left", padx=(12, 2))
        self.hist_n_var = tk.IntVar(value=100)
        ttk.Spinbox(hist, from_=1, to=100000, width=7,
                    textvariable=self.hist_n_var).pack(side="left")
        ttk.Label(hist, text="(within the last 2 hours)").pack(side="left", padx=6)

        # ---- round setup ------------------------------------------------
        self.setup = ttk.LabelFrame(self.root, text="New round")
        self.setup.pack(fill="x", **pad)
        ttk.Label(self.setup, text="Revealed set").grid(row=0, column=0, sticky="w",
                                                        padx=6, pady=3)
        self.set_choice = tk.StringVar(value=str(TIER_BJ_VALUES[0]))
        set_row = ttk.Frame(self.setup)
        set_row.grid(row=0, column=1, columnspan=3, sticky="w", pady=3)
        for bj in TIER_BJ_VALUES:               # single-select tier buttons
            ttk.Radiobutton(set_row, text=f"BJ {bj}x", value=str(bj),
                            variable=self.set_choice, style="Toolbutton",
                            command=self._update_set_label).pack(side="left")
        self.set_body_var = tk.StringVar()
        ttk.Label(set_row, textvariable=self.set_body_var,
                  foreground="#555").pack(side="left", padx=(12, 0))

        ttk.Label(self.setup, text="Your hand").grid(row=1, column=0, sticky="w",
                                                    padx=6, pady=3)
        self.hand_var = tk.StringVar()
        ttk.Entry(self.setup, textvariable=self.hand_var, width=20).grid(
            row=1, column=1, sticky="w", pady=3)
        quick = ttk.Frame(self.setup)
        quick.grid(row=1, column=2, columnspan=3, sticky="w")
        for label, rank in _CARD_BUTTONS:
            ttk.Button(quick, text=label, width=3,
                       command=lambda l=label: self._append_hand(l)).pack(side="left")
        ttk.Button(quick, text="Clear", width=5,
                   command=lambda: self.hand_var.set("")).pack(side="left", padx=4)

        ttk.Label(self.setup, text="Dealer upcard").grid(row=2, column=0, sticky="w",
                                                        padx=6, pady=3)
        self.up_choice = tk.StringVar(value="10")
        up_row = ttk.Frame(self.setup)
        up_row.grid(row=2, column=1, columnspan=3, sticky="w", pady=3)
        for label, _rank in _CARD_BUTTONS:      # single-select card buttons
            ttk.Radiobutton(up_row, text=label, value=label, width=3,
                            variable=self.up_choice,
                            style="Toolbutton").pack(side="left")

        self.deal_btn = ttk.Button(self.setup, text="Deal", command=self._deal)
        self.deal_btn.grid(row=3, column=0, sticky="w", padx=6, pady=6)

        # ---- play area --------------------------------------------------
        play = ttk.LabelFrame(self.root, text="Play")
        play.pack(fill="both", expand=True, **pad)

        # Felt table with the dealt cards.
        self.canvas = tk.Canvas(play, height=300, bg=_FELT, highlightthickness=0)
        self.canvas.pack(fill="x", padx=6, pady=4)
        self.canvas.bind("<Configure>", lambda e: self._draw_table())

        self.situation_var = tk.StringVar(value="—")
        ttk.Label(play, textvariable=self.situation_var,
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w", padx=6, pady=4)

        self.ev_tree = ttk.Treeview(play, columns=("ev", "mark"), show="tree headings",
                                    height=5)
        self.ev_tree.heading("#0", text="Action")
        self.ev_tree.heading("ev", text="EV")
        self.ev_tree.heading("mark", text="")
        self.ev_tree.column("#0", width=120)
        self.ev_tree.column("ev", width=110, anchor="e")
        self.ev_tree.column("mark", width=160)
        self.ev_tree.tag_configure("best", background="#d7f0d7")
        self.ev_tree.pack(fill="x", padx=6, pady=4)

        self.prompt_var = tk.StringVar(value="")
        ttk.Label(play, textvariable=self.prompt_var,
                  font=("TkDefaultFont", 11)).pack(anchor="w", padx=6)
        self.controls = ttk.Frame(play)
        self.controls.pack(anchor="w", fill="x", padx=6, pady=6)

        # ---- log --------------------------------------------------------
        logf = ttk.LabelFrame(self.root, text="History")
        logf.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(logf, height=9, wrap="word", state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self._update_set_label()

    # ---------------------------------------------------------- table canvas
    def _draw_card(self, x, y, rank, suit_idx):
        cv, w, h = self.canvas, _CARD_W, _CARD_H
        glyph, color = _SUITS[suit_idx % 4]
        cv.create_rectangle(x, y, x + w, y + h, fill="white", outline="#222",
                            width=2)
        t = _rank_text(rank)
        cv.create_text(x + 5, y + 4, text=t, anchor="nw", fill=color,
                       font=("TkDefaultFont", 11, "bold"))
        cv.create_text(x + 5, y + 20, text=glyph, anchor="nw", fill=color,
                       font=("TkDefaultFont", 11))
        cv.create_text(x + w / 2, y + h / 2, text=glyph, fill=color,
                       font=("TkDefaultFont", 24, "bold"))
        cv.create_text(x + w - 5, y + h - 4, text=t, anchor="se", fill=color,
                       font=("TkDefaultFont", 11, "bold"))

    def _draw_back(self, x, y):
        cv, w, h = self.canvas, _CARD_W, _CARD_H
        cv.create_rectangle(x, y, x + w, y + h, fill="#2c3e70", outline="#111",
                            width=2)
        cv.create_rectangle(x + 6, y + 6, x + w - 6, y + h - 6, outline="#8fa3d0")

    def _draw_hand(self, x0, y, cards, label, note):
        cv = self.canvas
        cv.create_text(x0, y - 18, text=label, anchor="nw", fill="white",
                       font=("TkDefaultFont", 11, "bold"))
        x = x0
        for ci, rank in enumerate(cards):
            self._draw_card(x, y, rank, ci + 1)   # decorative, stable per index
            x += _CARD_DX
        width = _CARD_DX * (len(cards) - 1) + _CARD_W if cards else _CARD_W
        cv.create_text(x0, y + _CARD_H + 6, text=_total_text(cards), anchor="nw",
                       fill="#f5f5c0", font=("TkDefaultFont", 12, "bold"))
        if note:
            col = "#bff0bf" if "win" in note else "#f0c0c0"
            cv.create_text(x0, y + _CARD_H + 26, text=note, anchor="nw", fill=col,
                           font=("TkDefaultFont", 11, "bold"))
        return x0 + width

    def _draw_table(self):
        cv = self.canvas
        cv.delete("all")
        # Dealer row.
        cv.create_text(16, 8, text="Dealer", anchor="nw", fill="white",
                       font=("TkDefaultFont", 11, "bold"))
        if self.t_dealer_up is not None:
            x, y = 16, 28
            self._draw_card(x, y, self.t_dealer_up, 0)
            self._draw_back(x + _CARD_DX, y)
            if self.t_dealer_final is not None:
                txt = ("BUST" if self.t_dealer_final == "bust"
                       else f"= {self.t_dealer_final}")
                cv.create_text(x + _CARD_DX + _CARD_W + 16, y + _CARD_H / 2,
                               text=txt, anchor="w", fill="#f5f5c0",
                               font=("TkDefaultFont", 13, "bold"))
        # Player row (one hand, or two side by side after a split).
        x0, y = 16, 170
        for hand in self.t_hands:
            x_end = self._draw_hand(x0, y, hand["cards"], hand["label"],
                                    hand["note"])
            x0 = x_end + 46

    # ---- table view-model updates --------------------------------------
    def _ensure_split_hands(self):
        """Turn the single opening hand into two seeded split hands (once)."""
        if len(self.t_hands) == 2:
            return
        self.t_hands = [{"cards": [self.pair_rank], "label": "Hand 1", "note": ""},
                        {"cards": [self.pair_rank], "label": "Hand 2", "note": ""}]

    def _sync_hand(self, node):
        """Mirror a decision node's authoritative card list into the table."""
        idx = (node["hand_no"] - 1) if node["hand_no"] else 0
        if node["hand_no"]:
            self._ensure_split_hands()
        self.t_hands[idx]["cards"] = list(node["cards"])
        self._draw_table()

    def _play_card(self, rank):
        """A real drawn card was clicked: add it to the right hand, then feed
        the session."""
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
        """Blank the previous hand's inputs so a new hand starts fresh."""
        self.hand_var.set("")
        self.up_choice.set("10")
        self.set_choice.set(str(TIER_BJ_VALUES[0]))
        self._update_set_label()

    def _clear_controls(self):
        for w in self.controls.winfo_children():
            w.destroy()

    def _log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _sync_status(self):
        self.carry_var.set(f"Carry {self.session.carry}x")
        self.round_var.set(f"Round {self.session.round_no}")

    def _show_node(self, node, auto=None, reason=None):
        self._sync_hand(node)
        cards = hand_str(node["cards"])
        if node["hand_no"]:
            where = f"Split hand {node['hand_no']}  {cards}"
        else:
            where = f"Hand {cards}"
        self.situation_var.set(
            f"{where}  (total {node['total']}) vs dealer {_up_label(node['up'])}"
            f"   ·   carry {self.session.carry}x")
        best = node["best"].name
        self.ev_tree.delete(*self.ev_tree.get_children())
        for a in sorted(node["actions"], key=lambda a: -a.ev):
            mark = ""
            if a.name == best:
                mark = "◀ optimal"
                if auto == a.name:
                    mark = f"◀ auto: {reason}"
            self.ev_tree.insert("", "end", text=_ACTION_LABEL[a.name],
                                values=(f"{a.ev:+.4f}", mark),
                                tags=("best",) if a.name == best else ())

    # --------------------------------------------------------------- phases
    def _phase(self, name):
        """Enable exactly the controls valid for the current step."""
        setup_state = "normal" if name == "setup" else "disabled"
        for w in self.setup.winfo_children():
            self._set_state(w, setup_state)

    @staticmethod
    def _set_state(widget, state):
        for child in widget.winfo_children():
            LBJGui._set_state(child, state)
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass

    # ---------------------------------------------------- settings handlers
    def _on_auto_toggle(self):
        self.session.auto = self.auto_var.get()

    def _on_thr(self, _value):
        self.session.threshold = round(self.thr_var.get(), 2)
        self.thr_lbl.configure(text=f"{self.session.threshold:.2f}")

    def _on_start_carry(self):
        self.session.start_carry = self.start_carry_var.get()
        # If no round has been scored yet, the first round should use it too.
        if self.session.round_no == 1 and self.session.pending is None:
            self.session.carry = self.session.start_carry
            self._sync_status()

    def _reset(self):
        # A bust wipes the carry: always start fresh at 1x, whatever the
        # configured starting carry was.
        self.session.start_carry = 1
        self.start_carry_var.set(1)
        self.session.reset()
        self._sync_status()
        self._clear_controls()
        self.prompt_var.set("")
        self.situation_var.set("—")
        self.ev_tree.delete(*self.ev_tree.get_children())
        self.t_dealer_up = self.t_dealer_final = None
        self.t_hands = []
        self._draw_table()
        self._phase("setup")
        self._clear_inputs()

    # ---------------------------------------------------------- histogram
    _HIST_BLUE = "#2c5fb0"
    _HIST_RED = "#c0392b"

    def _show_histogram(self):
        try:
            n = int(self.hist_n_var.get())
        except (tk.TclError, ValueError):
            n = None
        # Blue: every session file pooled (grows as instances are pulled in).
        # Red: THIS instance's file (<=2h, last N).
        all_counts, all_total = overall_tier_counts()
        sess_counts, sess_total = observed_tier_counts(path=self.session_hist_path,
                                                       within_hours=2, last_n=n)

        win = tk.Toplevel(self.root)
        win.title("Observed multiplier histogram")
        win.transient(self.root)
        if not all_total:
            ttk.Label(win, text="No rounds recorded yet — enable "
                      "\"Store each round's set\" and play.",
                      font=("TkDefaultFont", 11)).pack(padx=20, pady=20)
            ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 12))
            return
        ttk.Label(win, text="Relative frequency per tier — all sessions vs this one",
                  font=("TkDefaultFont", 11, "bold")).pack(padx=10, pady=(10, 0))

        W, H = 580, 360
        cv = tk.Canvas(win, width=W, height=H, bg="white", highlightthickness=0)
        cv.pack(padx=10, pady=10)
        ml, mr, mt, mb = 44, 16, 56, 52
        plot_h, plot_w = H - mt - mb, W - ml - mr
        bjs = list(TIER_BJ_VALUES)
        gw = plot_w / len(bjs)
        y0 = mt + plot_h

        def prop(counts, total, bj):
            return counts[bj] / total if total else 0.0

        maxp = max([prop(all_counts, all_total, b) for b in bjs] +
                   [prop(sess_counts, sess_total, b) for b in bjs] + [1e-9])
        cv.create_line(ml, y0, W - mr, y0, fill="#888")

        # Legend.
        lx, ly = ml, 30
        for color, label in ((self._HIST_BLUE, f"All sessions (n={all_total})"),
                             (self._HIST_RED,
                              f"This session ≤2h, last {n} (n={sess_total})")):
            cv.create_rectangle(lx, ly - 6, lx + 14, ly + 6, fill=color, outline="")
            tid = cv.create_text(lx + 20, ly, text=label, anchor="w",
                                 font=("TkDefaultFont", 9))
            lx = cv.bbox(tid)[2] + 20

        def bar(x, w, counts, total, bj, color):
            h = plot_h * prop(counts, total, bj) / maxp
            cv.create_rectangle(x, y0 - h, x + w, y0, fill=color, outline="#111")
            if total:
                cv.create_text(x + w / 2, y0 - h - 8,
                               text=f"{100 * prop(counts, total, bj):.0f}%",
                               font=("TkDefaultFont", 8))

        for i, bj in enumerate(bjs):
            x = ml + i * gw
            bw = gw * 0.34
            bar(x + gw * 0.11, bw, all_counts, all_total, bj, self._HIST_BLUE)
            bar(x + gw * 0.11 + bw + gw * 0.06, bw, sess_counts, sess_total, bj,
                self._HIST_RED)
            cv.create_text(x + gw / 2, y0 + 16, text=f"BJ {bj}x",
                           font=("TkDefaultFont", 9))
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

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
            self._log(f"  recorded set (BJ {tier['BJ']}x) -> {os.path.basename(path)}")
        self.session.start_round(dict(tier))
        # Reset the table view-model for the new round.
        self.t_dealer_up, self.t_dealer_final = up, None
        self.pair_rank = cards[0]
        self.t_hands = [{"cards": list(cards), "label": "You", "note": ""}]
        self._draw_table()
        self._log(f"\n----- Round {self.session.round_no} (carry "
                  f"{self.session.carry}x) -----")
        self._log(f"set {describe_set(tier)}; hand {hand_str(cards)} vs dealer "
                  f"{_up_label(up)}")
        self._phase("play")
        self.session.deal(cards, up)

    def _on_decision(self, node):
        self._show_node(node)
        self.prompt_var.set("Your move:")
        self._clear_controls()
        for a in node["actions"]:
            emphasis = a.name == node["best"].name
            btn = ttk.Button(self.controls, text=_ACTION_LABEL[a.name],
                             command=lambda n=a.name: self.session.choose(n))
            btn.pack(side="left", padx=3)
            if emphasis:
                btn.state(["focus"])

    def _on_auto(self, node, action, reason):
        self._show_node(node, auto=action, reason=reason)
        self._clear_controls()
        self.prompt_var.set(f"Auto-played {_ACTION_LABEL[action]} ({reason}).")
        self._log(f"  auto {_ACTION_LABEL[action]} — {reason} "
                  f"(hand total {node['total']} vs {_up_label(node['up'])})")

    def _on_card(self, ctx):
        self._card_ctx = ctx
        self.prompt_var.set(f"Which card came? ({ctx['label']})")
        self._clear_controls()
        for label, rank in _CARD_BUTTONS:
            ttk.Button(self.controls, text=label, width=3,
                       command=lambda r=rank: self._play_card(r)).pack(side="left")

    def _on_dealer(self):
        self.prompt_var.set("Dealer's final total?")
        self._clear_controls()
        for label, val in _DEALER_BUTTONS:
            ttk.Button(self.controls, text=label,
                       command=lambda v=val: self.session.dealer(v)).pack(
                side="left", padx=2)

    def _on_round_done(self, summary):
        dealer = summary["dealer"]
        dtxt = "bust" if dealer in (None, "bust") else str(dealer)
        outcomes = summary["outcomes"]
        for i, oc in enumerate(outcomes, 1):
            label = f"hand {i}" if len(outcomes) > 1 else "result"
            note = f"win {oc['mult']}x" if oc["outcome"] == "win" else oc["outcome"]
            self._log(f"  {label}: {note}")
            if i - 1 < len(self.t_hands):
                self.t_hands[i - 1]["note"] = note
        self._log(f"  dealer {dtxt}  ·  carry {summary['old_carry']}x -> "
                  f"{summary['new_carry']}x")
        # Reveal the dealer total on the felt and freeze the final hands.
        self.t_dealer_final = "bust" if dealer is None else dealer
        self._draw_table()
        self._sync_status()
        self._clear_controls()
        self.prompt_var.set(f"Round over. Carry is now {summary['new_carry']}x — "
                            f"pick the next set and Deal.")
        self.ev_tree.delete(*self.ev_tree.get_children())
        self.situation_var.set("—")
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
