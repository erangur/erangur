"""UI-agnostic controller for a continuous Lightning Blackjack session.

This is the engine behind both the interactive CLI wizard and the GUI: it drives
one round at a time, carrying the earned multiplier forward, and centralises the
*auto-play* policy (trivial / high-conviction decisions are played automatically
so the human is only asked about genuine choices).

The round itself is a generator (``play_round``) that mirrors the CLI wizard's
play-by-play semantics exactly — natural blackjacks, hit/double/split, splits
played hand-by-hand with the second hand coupled to the first — but instead of
calling ``input``/``print`` it *yields* requests:

    ("log",    message)      informational; the driver just records it
    ("action", node)         a decision node; the driver replies with an action
    ("card",   ctx)          a real drawn card is needed; the driver replies rank

``Session`` pumps that generator, applies the auto-play policy to every action
node, and calls the view's callbacks. Because the whole thing is plain callbacks
it is fully testable without a display (see ``tests``).
"""

from .cards import add_card, hand_from_cards, is_natural
from .engine import DOUBLE, HIT, SPLIT, STAND


def _card_label(c):
    return "A" if c == 11 else str(c)


def hand_str(cards):
    return ",".join(_card_label(c) for c in cards)


def hand_outcome(total, dealer_final):
    """'win' / 'push' / 'loss' for a standing player ``total`` vs the dealer."""
    if total is None:
        return "loss"
    if dealer_final == "bust" or total > dealer_final:
        return "win"
    if total == dealer_final:
        return "push"
    return "loss"


# ---------------------------------------------------------------------------
# Round generators.  Each ``yield`` is a request the driver must satisfy; the
# value sent back in reply is documented per site.  ``return`` yields the round
# result as ``[(final_total_or_None, natural_flag)]`` (two entries after a split).
# ---------------------------------------------------------------------------
def _node(kind, cards, total, soft, up, actions, best, hand_no=None,
          partner_total=None):
    return {
        "kind": kind, "cards": list(cards), "total": total, "soft": soft,
        "up": up, "actions": actions, "best": best, "hand_no": hand_no,
        "partner_total": partner_total,
    }


def play_round(ev, cards, up):
    """Play one round. Yields requests; returns ``[(total_or_None, natural)]``."""
    if is_natural(cards):
        yield ("log", f"{hand_str(cards)} = natural blackjack.")
        return [(21, True)]

    total, soft = hand_from_cards(cards)
    actions, best, _ = ev.evaluate(cards, up)
    chosen = yield ("action", _node("open", cards, total, soft, up, actions, best))

    if chosen == SPLIT:
        return (yield from _play_split(ev, cards[0], up))
    if chosen == STAND:
        yield ("log", f"stand at {total}.")
        return [(total, False)]
    if chosen == DOUBLE:
        c = yield ("card", {"label": "card drawn on the double", "hand_no": None})
        nt, ns, bust = add_card(total, soft, c)
        yield ("log", f"{hand_str(cards + [c])} = {'BUST' if bust else nt} (doubled).")
        return [(None if bust else nt, False)]

    # hit
    c = yield ("card", {"label": "card drawn", "hand_no": None})
    cards = cards + [c]
    nt, ns, bust = add_card(total, soft, c)
    if bust:
        yield ("log", f"{hand_str(cards)} = {nt} BUST.")
        return [(None, False)]
    final = yield from _continue_solo(ev, cards, up)
    return [(final, False)]


def _continue_solo(ev, cards, up):
    """Play a solo hand out card by card after the first hit (no double now)."""
    total, soft = hand_from_cards(cards)
    while True:
        if total == 21:
            yield ("log", f"{hand_str(cards)} = 21 — stand.")
            return 21
        actions, best = ev.node_actions(total, soft, False, up)
        chosen = yield ("action", _node("hit", cards, total, soft, up, actions, best))
        if chosen == STAND:
            yield ("log", f"stand at {total}.")
            return total
        c = yield ("card", {"label": "card drawn", "hand_no": None})
        cards = cards + [c]
        total, soft, bust = add_card(total, soft, c)
        if bust:
            yield ("log", f"{hand_str(cards)} = {total} BUST.")
            return None


def _play_split(ev, pair_rank, up):
    """Play both post-split hands in order; hand 2 is coupled to hand 1's total."""
    yield ("log", f"split {_card_label(pair_rank)}s.")
    t1 = yield from _play_split_hand(ev, pair_rank, up, 1, partner="solo")
    t2 = yield from _play_split_hand(ev, pair_rank, up, 2, partner=t1)
    return [(t1, False), (t2, False)]


def _play_split_hand(ev, pair_rank, up, hand_no, partner):
    """Play one post-split hand. ``partner`` is 'solo' (hand 1) or hand 1's final
    total / None (hand 2). Returns this hand's final total, or None if busted."""
    if pair_rank == 11 and ev.cfg.split_aces_one_card:
        c = yield ("card", {"label": f"hand {hand_no} card", "hand_no": hand_no})
        total, _ = hand_from_cards([11, c])
        yield ("log", f"hand {hand_no}: A,{_card_label(c)} = {total}.")
        return total

    c = yield ("card", {"label": f"hand {hand_no} first card", "hand_no": hand_no})
    cards = [pair_rank, c]
    total, soft = hand_from_cards(cards)
    while True:
        if total == 21:
            yield ("log", f"hand {hand_no} {hand_str(cards)} = 21 — stands.")
            return 21
        if partner == "solo":
            actions, best = ev.node_actions(total, soft, False, up)   # no DAS
            kind, ptot = "split1", None
        else:
            actions, best = ev.joint_node_actions(total, soft, up, partner)
            kind, ptot = "split2", partner
        chosen = yield ("action", _node(kind, cards, total, soft, up, actions,
                                         best, hand_no=hand_no, partner_total=ptot))
        if chosen == STAND:
            yield ("log", f"hand {hand_no} stands at {total}.")
            return total
        c = yield ("card", {"label": f"hand {hand_no} card drawn", "hand_no": hand_no})
        cards = cards + [c]
        total, soft, bust = add_card(total, soft, c)
        if bust:
            yield ("log", f"hand {hand_no} {hand_str(cards)} = {total} BUST.")
            return None


# ---------------------------------------------------------------------------
# Auto-play policy.
# ---------------------------------------------------------------------------
def _can_bust(node):
    """True iff *some* single card can bust this hand. A soft hand or a hard
    total <= 11 can never bust on one card (the Ace demotes / 11+10 = 21)."""
    return not (node["soft"] or node["total"] <= 11)


def auto_action(node, carry, enabled, threshold):
    """Decide whether to auto-play ``node``.

    Returns ``(action_name, reason)`` to auto-play, or ``(None, None)`` to ask
    the human. The policy has three tiers:

    * a node with only one legal action is always auto-played;
    * *risk-free*: the solver's pick is HIT on a hand that cannot bust — there is
      nothing to weigh, so take the free card (covers "small total, no carry");
    * *high conviction*: the best action beats the second-best by a margin that,
      normalised by the current carry, clears ``threshold`` — this fires the
      aggressive chase plays a big carry makes clearly correct (e.g. doubling a
      soft 15 vs a 10). Normalising by carry keeps a genuine "ask" zone at every
      carry level instead of collapsing to always-auto when the carry is large.
    """
    actions, best = node["actions"], node["best"]
    if len(actions) == 1:
        return best.name, "only legal option"
    if not enabled:
        return None, None
    if best.name == HIT and not _can_bust(node):
        return HIT, "risk-free · cannot bust"
    ordered = sorted(actions, key=lambda a: -a.ev)
    margin = ordered[0].ev - ordered[1].ev
    norm = margin / max(1, carry)
    if norm >= threshold:
        return best.name, f"high conviction · Δ/carry={norm:.2f}"
    return None, None


def resolve_carry(ev, hands, dealer_final):
    """Score the round. Returns ``(new_carry, outcomes)`` where ``outcomes`` is a
    per-hand list of ``{'outcome', 'mult', 'total', 'natural'}``. The carry
    forward is the max (or min, per rule) winning multiplier, else 1."""
    take_max = ev.cfg.split_carry_rule != "min"
    win_mults, outcomes = [], []
    for total, natural in hands:
        oc = hand_outcome(total, dealer_final)
        mult = None
        if oc == "win":
            mult = ev.model.multiplier_for(ev.revealed_set, total, natural)
            win_mults.append(mult)
        outcomes.append({"outcome": oc, "mult": mult, "total": total,
                         "natural": natural})
    new_carry = (max if take_max else min)(win_mults) if win_mults else 1
    return new_carry, outcomes


# ---------------------------------------------------------------------------
# Session driver.
# ---------------------------------------------------------------------------
class Session:
    """Drives a continuous carry-tracking session, calling view callbacks.

    Wire up the callbacks (``on_*``) after constructing, then call ``start_round``
    -> ``deal`` -> (``choose`` / ``card`` as requested) -> ``dealer``. The driver
    auto-plays trivial nodes itself, so ``on_decision`` fires only for genuine
    choices. ``reset`` returns the session to a fresh carry at any time.
    """

    def __init__(self, sol, start_carry=1, auto=True, threshold=0.20):
        self.sol = sol
        self.start_carry = start_carry
        self.carry = start_carry
        self.round_no = 1
        self.auto = auto
        self.threshold = threshold

        # View callbacks — default to no-ops so the driver is usable headless.
        self.on_log = lambda message: None
        self.on_decision = lambda node: None
        self.on_auto = lambda node, action, reason: None
        self.on_card = lambda ctx: None
        self.on_dealer = lambda: None
        self.on_round_done = lambda summary: None

        # Per-round state.
        self.revealed_set = None
        self.ev = None
        self.up = None
        self._gen = None
        self._hands = None
        self._pending = None      # 'action' | 'card' | 'dealer' | None
        self.node = None          # the decision node currently awaiting a human

    # ---- session control ------------------------------------------------
    def reset(self):
        """Bust out / start fresh: carry back to the starting value, round 1."""
        self.carry = self.start_carry
        self.round_no = 1
        self.revealed_set = self.ev = self.up = None
        self._gen = self._hands = self.node = None
        self._pending = None
        self.on_log(f"— reset — fresh session, carry {self.carry}x —")

    def start_round(self, revealed_set):
        """Begin a round with the revealed multiplier set, awaiting the hand."""
        self.revealed_set = revealed_set
        self.ev = self.sol.evaluator(self.carry, revealed_set)
        self._hands = self.node = None
        self._pending = None

    def deal(self, cards, up):
        """Provide the starting hand + dealer upcard and start play."""
        self.up = up
        self._gen = play_round(self.ev, cards, up)
        self._drive(None)

    def choose(self, action):
        """Human answer to an ``on_decision`` request."""
        if self._pending != "action":
            raise RuntimeError("no decision is pending")
        self._pending = self.node = None
        self._drive(action)

    def card(self, rank):
        """Human answer to an ``on_card`` request (the real card that came)."""
        if self._pending != "card":
            raise RuntimeError("no card is pending")
        self._pending = None
        self._drive(rank)

    def dealer(self, final):
        """Human answer to an ``on_dealer`` request. ``final`` is 2..21 or 'bust'."""
        if self._pending != "dealer":
            raise RuntimeError("no dealer result is pending")
        self._pending = None
        self._finish(final)

    @property
    def pending(self):
        return self._pending

    # ---- internal pump --------------------------------------------------
    def _drive(self, value):
        """Resume the round generator, auto-playing trivial nodes, until the human
        (or the dealer step) is genuinely needed."""
        gen = self._gen
        while True:
            try:
                req = gen.send(value)
            except StopIteration as exc:
                self._hands = exc.value
                self._request_dealer()
                return
            value = None
            tag, payload = req[0], req[1] if len(req) > 1 else None
            if tag == "log":
                self.on_log(payload)
                continue
            if tag == "action":
                action, reason = auto_action(payload, self.carry, self.auto,
                                             self.threshold)
                if action is not None:
                    self.on_auto(payload, action, reason)
                    value = action
                    continue
                self._pending = "action"
                self.node = payload
                self.on_decision(payload)
                return
            if tag == "card":
                self._pending = "card"
                self.on_card(payload)
                return
            raise AssertionError(f"unknown request {tag!r}")

    def _request_dealer(self):
        if all(total is None for total, _ in self._hands):
            self.on_log("all hands bust — loss.")
            self._finish(None)     # dealer result irrelevant; carry dies to 1
            return
        self._pending = "dealer"
        self.on_dealer()

    def _finish(self, dealer_final):
        new_carry, outcomes = resolve_carry(self.ev, self._hands, dealer_final)
        summary = {
            "round": self.round_no, "outcomes": outcomes, "dealer": dealer_final,
            "old_carry": self.carry, "new_carry": new_carry,
        }
        self.carry = new_carry
        self.round_no += 1
        self._gen = self._hands = self.node = None
        self._pending = None
        self.on_round_done(summary)
