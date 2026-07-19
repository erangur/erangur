"""Exact per-hand EV / optimal-action engine for Lightning Blackjack.

Given a *carried-in* multiplier ``multiplier_in`` and the *revealed* multiplier set ``S``
(both known before you act), plus a carry-continuation value function ``h`` (see
``carry.py``), this computes the exact EV of every legal action and the optimum.

All values are NET of the base bet's return but EXCLUDE the flat per-round fee,
which is constant across actions and therefore irrelevant to the argmax. Helpers
that report round-level EV subtract the fee explicitly.

Reward model (units of B, stake s, carried multiplier multiplier_in), per DESIGN.md with
the internally-consistent reading (winnings = multiplier_in x stake, flat fee):
    win (non-natural) : +multiplier_in * s      and carry S[bucket(total)]
    natural BJ, multiplier_in=1: +1.5 * B       and carry S[BJ]
    natural BJ, multiplier_in>1: +multiplier_in * B      and carry S[BJ]
    push              :  0             carry killed (-> 1)
    loss             : -s              carry killed (-> 1)
The flat fee (-B) is added once per round elsewhere.
"""

from collections import namedtuple

from .cards import RANK_PROBS_F, RANKS, add_card, hand_from_cards, is_natural
from .config import DEFAULT_CONFIG
from .dealer import dealer_distribution
from .multipliers import bucket_of

# One evaluated action.
Action = namedtuple("Action", "name ev")

STAND, HIT, DOUBLE, SPLIT = "stand", "hit", "double", "split"


class Evaluator:
    """Evaluates hands for a fixed (config, model, carry_values, multiplier_in, revealed_set)."""

    def __init__(self, model, carry_values, multiplier_in, revealed_set,
                 config=DEFAULT_CONFIG):
        self.model = model
        # dict: multiplier -> continuation value; carry_values[1] == 0
        self.carry_values = carry_values
        self.multiplier_in = multiplier_in
        self.revealed_set = revealed_set
        self.cfg = config
        self._hand_cache = {}   # (total,soft,can_double,stake,upcard) -> ev
        self._ctx_cache = {}    # upcard -> ctx

    # ---- carry bonuses ---------------------------------------------------
    def _bonus(self, total, natural):
        """Continuation value earned by *winning* at this final total."""
        return self.carry_values[self.model.multiplier_for(self.revealed_set, total, natural)]

    # ---- dealer context per upcard --------------------------------------
    def _ctx(self, upcard):
        ctx = self._ctx_cache.get(upcard)
        if ctx is not None:
            return ctx
        p_bj, cond = dealer_distribution(upcard)
        does_peek = ((upcard == 11 and self.cfg.peek_on_ace) or
                     (upcard == 10 and self.cfg.peek_on_ten))
        if does_peek:
            p_in_play, peek_loss = 0.0, p_bj
        else:
            p_in_play, peek_loss = p_bj, 0.0
        ctx = {"cond": cond, "p_in_play": p_in_play, "peek_loss": peek_loss}
        self._ctx_cache[upcard] = ctx
        return ctx

    # ---- stand ----------------------------------------------------------
    @staticmethod
    def _win_push_loss(total, cond):
        """(P win, P push, P loss) for a standing player total vs dealer.

        Uses the conditional-on-no-dealer-BJ distribution ``cond``.
        """
        pw = pp = pl = 0.0
        for d, p in cond.items():
            if d == "bust":
                pw += p
            elif d > total:
                pl += p
            elif d == total:
                pp += p
            else:
                pw += p
        return pw, pp, pl

    def _stand_value(self, total, stake, ctx):
        pw, pp, pl = self._win_push_loss(total, ctx["cond"])
        q = ctx["p_in_play"]  # no-peek dealer-BJ mass folded in as a loss
        win_p = (1 - q) * pw
        loss_p = (1 - q) * pl + q
        # push contributes 0; carry killed on push/loss (bonus 0 via h[1]=0)
        return win_p * (self.multiplier_in * stake + self._bonus(total, False)) - loss_p * stake

    # ---- full hand DP (stand / hit / double) ----------------------------
    def _hand_value(self, total, soft, can_double, stake, upcard):
        key = (total, soft, can_double, stake, upcard)
        cached = self._hand_cache.get(key)
        if cached is not None:
            return cached
        ctx = self._ctx(upcard)
        best = self._stand_value(total, stake, ctx)

        hit = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            if bust:
                hit += p * (-stake)
            else:
                hit += p * self._hand_value(nt, ns, False, stake, upcard)
        if hit > best:
            best = hit

        if can_double and self.cfg.double_any_two:
            dbl = 0.0
            for r in RANKS:
                p = RANK_PROBS_F[r]
                nt, ns, bust = add_card(total, soft, r)
                if bust:
                    dbl += p * (-2 * stake)
                else:
                    dbl += p * self._stand_value(nt, 2 * stake, ctx)
            if dbl > best:
                best = dbl

        self._hand_cache[key] = best
        return best

    def hand_action(self, total, soft, can_double, stake, upcard):
        """Optimal in-hand action ('stand'/'hit'/'double') at a decision node.

        Used by the simulator to play a hand out card by card.
        """
        ctx = self._ctx(upcard)
        best_name, best_val = STAND, self._stand_value(total, stake, ctx)

        hit = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            hit += p * ((-stake) if bust else self._hand_value(nt, ns, False, stake, upcard))
        if hit > best_val:
            best_name, best_val = HIT, hit

        if can_double and self.cfg.double_any_two:
            dbl = 0.0
            for r in RANKS:
                p = RANK_PROBS_F[r]
                nt, ns, bust = add_card(total, soft, r)
                dbl += p * ((-2 * stake) if bust else self._stand_value(nt, 2 * stake, ctx))
            if dbl > best_val:
                best_name, best_val = DOUBLE, dbl
        return best_name

    # ---- split ----------------------------------------------------------
    def _post_split_final_dist(self, pair_rank, upcard):
        """Distribution over a post-split hand's final total ('bust' or 12..21).

        Follows the optimal hit/stand policy (no double after split, no resplit).
        Split Aces get exactly one card each.
        """
        ctx = self._ctx(upcard)

        if pair_rank == 11 and self.cfg.split_aces_one_card:
            dist = {}
            for r in RANKS:
                p = RANK_PROBS_F[r]
                t, _ = hand_from_cards([11, r])
                dist[t] = dist.get(t, 0.0) + p
            return dist

        memo = {}

        def final(total, soft):
            key = (total, soft)
            if key in memo:
                return memo[key]
            stand = self._stand_value(total, 1, ctx)
            hit = 0.0
            for r in RANKS:
                p = RANK_PROBS_F[r]
                nt, ns, bust = add_card(total, soft, r)
                if bust:
                    hit += p * (-1)
                else:
                    hit += p * self._hand_value(nt, ns, False, 1, upcard)
            if stand >= hit:
                res = {total: 1.0}
            else:
                res = {}
                for r in RANKS:
                    p = RANK_PROBS_F[r]
                    nt, ns, bust = add_card(total, soft, r)
                    sub = {"bust": 1.0} if bust else final(nt, ns)
                    for k, v in sub.items():
                        res[k] = res.get(k, 0.0) + p * v
            memo[key] = res
            return res

        # The split hand starts with one card (pair_rank) + one dealt card.
        dist = {}
        for r in RANKS:
            p = RANK_PROBS_F[r]
            t, soft = hand_from_cards([pair_rank, r])
            for k, v in final(t, soft).items():
                dist[k] = dist.get(k, 0.0) + p * v
        return dist

    def _split_value(self, pair_rank, upcard):
        """EV of splitting a pair (two independent hands, one shared fee).

        Both post-split hands have identical final-total distributions (infinite
        deck), so the immediate part is separable (2 x per-hand EV) and only the
        carry bonus needs the joint. The carried multiplier is combined per
        ``cfg.split_carry_rule`` ('max' default, or 'min').
        """
        ctx = self._ctx(upcard)
        cond = ctx["cond"]
        q = ctx["p_in_play"]
        P = self._post_split_final_dist(pair_rank, upcard)
        take_max = self.cfg.split_carry_rule != "min"

        # Precompute per final total: (prob, multiplier, h-value); 'bust' -> None.
        finals = []
        for t, p in P.items():
            if p <= 0:
                continue
            if t == "bust":
                finals.append((t, p, None, None))
            else:
                m = self.model.multiplier_for(self.revealed_set, t, False)
                finals.append((t, p, m, self.carry_values[m]))

        mult_in = self.multiplier_in
        total = 0.0
        for d, pd in cond.items():
            if pd == 0:
                continue
            pay_sum = 0.0    # sum_t prob * pay(t)      (separable across hands)
            win_p = 0.0      # prob this hand wins
            win_list = []    # winners: (prob, mult, h-value)
            for t, p, m, hv in finals:
                if t == "bust":
                    pay_sum -= p
                elif d == "bust" or t > d:
                    pay_sum += p * mult_in
                    win_p += p
                    win_list.append((p, m, hv))
                elif t == d:
                    pass          # push -> pay 0
                else:
                    pay_sum -= p  # loss
            immediate = 2 * pay_sum
            # carry bonus: exactly-one-wins + both-win terms (max/min rule).
            bonus = 2 * (1.0 - win_p) * sum(p * hv for p, _, hv in win_list)
            for p1, m1, hv1 in win_list:
                for p2, m2, hv2 in win_list:
                    mm = (m1 if m1 >= m2 else m2) if take_max else (m1 if m1 <= m2 else m2)
                    bonus += p1 * p2 * self.carry_values[mm]
            total += pd * (immediate + bonus)
        # No-peek dealer BJ: both hands lose their stake.
        return (1 - q) * total + q * (-2.0)

    # ---- mid-hand node (solo, no split) ---------------------------------
    def node_actions(self, total, soft, can_double, upcard, stake=1):
        """Evaluated actions at a solo decision node (stand / hit [/ double]).

        Like ``evaluate`` but for a hand already in progress: no natural and no
        split branch. Returns ``(actions, best)`` with fee-excluded EVs. Used to
        drive the interactive wizard card by card, and for the first hand of a
        split (played under the solo policy, exactly as the engine's split EV
        and the simulator assume).
        """
        ctx = self._ctx(upcard)
        acts = [Action(STAND, self._stand_value(total, stake, ctx))]

        hit = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            hit += p * ((-stake) if bust else self._hand_value(nt, ns, False, stake, upcard))
        acts.append(Action(HIT, hit))

        if can_double and self.cfg.double_any_two:
            dbl = 0.0
            for r in RANKS:
                p = RANK_PROBS_F[r]
                nt, ns, bust = add_card(total, soft, r)
                dbl += p * ((-2 * stake) if bust else self._stand_value(nt, 2 * stake, ctx))
            acts.append(Action(DOUBLE, dbl))

        best = max(acts, key=lambda a: a.ev)
        return acts, best

    # ---- second split hand, coupled to the sibling's final total --------
    def _sibling_carry(self, partner_total):
        """``(compare_total, multiplier)`` for the already-played sibling.

        ``partner_total`` is the sibling hand's final total (int) or ``None`` if
        it busted (a busted sibling never wins, so it carries nothing). Returns
        ``None`` for a busted / absent sibling.
        """
        if partner_total is None:
            return None
        m = self.model.multiplier_for(self.revealed_set, partner_total, False)
        return partner_total, m

    def _joint_lose_value(self, upcard, sibling):
        """EV when THIS hand loses (busts), given the fixed ``sibling``.

        Constant across this hand's total: only the sibling's own carry (when it
        beats the dealer) survives.
        """
        ctx = self._ctx(upcard)
        cond, q = ctx["cond"], ctx["p_in_play"]
        total = 0.0
        for d, pd in cond.items():
            if pd == 0:
                continue
            val = -1.0
            if sibling is not None and (d == "bust" or sibling[0] > d):
                val += self.carry_values[sibling[1]]
            total += pd * val
        return (1 - q) * total + q * (-1.0)

    def _joint_stand_value(self, t, upcard, sibling):
        """EV of standing at ``t`` with the sibling hand fixed.

        The carry both hands can earn is combined per ``cfg.split_carry_rule``
        (max by default), so the sibling's final total shifts this hand's value:
        a sibling that already secured a big multiplier removes this hand's
        incentive to chase one. With ``sibling is None`` this reduces exactly to
        the solo ``_stand_value``.
        """
        ctx = self._ctx(upcard)
        cond, q = ctx["cond"], ctx["p_in_play"]
        m2 = self.model.multiplier_for(self.revealed_set, t, False)
        take_max = self.cfg.split_carry_rule != "min"
        total = 0.0
        for d, pd in cond.items():
            if pd == 0:
                continue
            sib_win = sibling is not None and (d == "bust" or sibling[0] > d)
            if d == "bust" or t > d:               # this hand wins
                val = self.multiplier_in
                if sib_win:
                    m1 = sibling[1]
                    mm = (m1 if m1 >= m2 else m2) if take_max else (m1 if m1 <= m2 else m2)
                    val += self.carry_values[mm]
                else:
                    val += self.carry_values[m2]
            elif t == d:                           # push
                val = self.carry_values[sibling[1]] if sib_win else 0.0
            else:                                  # this hand loses
                val = -1.0 + (self.carry_values[sibling[1]] if sib_win else 0.0)
            total += pd * val
        return (1 - q) * total + q * (-1.0)

    def _joint_hand_value(self, total, soft, upcard, sibling, memo):
        key = (total, soft)
        cached = memo.get(key)
        if cached is not None:
            return cached
        best = self._joint_stand_value(total, upcard, sibling)
        lose = self._joint_lose_value(upcard, sibling)
        hit = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            hit += p * (lose if bust else self._joint_hand_value(nt, ns, upcard, sibling, memo))
        if hit > best:
            best = hit
        memo[key] = best
        return best

    def joint_node_actions(self, total, soft, upcard, partner_total):
        """Actions (stand / hit) for the SECOND split hand, coupled to the first.

        ``partner_total`` is the finished first hand's final total (int) or
        ``None`` if it busted. No double-after-split, so only stand / hit are
        offered. Returns ``(actions, best)``.
        """
        sibling = self._sibling_carry(partner_total)
        memo = {}
        stand = self._joint_stand_value(total, upcard, sibling)
        lose = self._joint_lose_value(upcard, sibling)
        hit = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            hit += p * (lose if bust else self._joint_hand_value(nt, ns, upcard, sibling, memo))
        acts = [Action(STAND, stand), Action(HIT, hit)]
        best = max(acts, key=lambda a: a.ev)
        return acts, best

    # ---- top-level: evaluate a starting hand ----------------------------
    def evaluate(self, cards, upcard):
        """Evaluate a starting hand (list of ranks) vs ``upcard``.

        Returns ``(actions, best_action, round_ev)`` where ``actions`` is a list
        of ``Action(name, ev)`` for each legal option (values EXCLUDE the flat
        fee), and ``round_ev`` is the net expected value INCLUDING the fee.
        """
        ctx = self._ctx(upcard)
        peek_loss = ctx["peek_loss"]

        # Natural blackjack: not a decision.
        if is_natural(cards):
            p_bj, _ = dealer_distribution(upcard)
            bonus = self._bonus(21, True)
            win_pay = (self.cfg.blackjack_payout if self.multiplier_in == 1 else self.multiplier_in)
            bj_val = (1 - p_bj) * (win_pay + bonus)  # dealer BJ -> push (0)
            return ([Action(STAND, bj_val)], Action(STAND, bj_val),
                    bj_val - self.cfg.fee)

        total, soft = hand_from_cards(cards)
        actions = []

        # Stand / hit / double via the DP (measure each separately for display).
        stand_ev = self._stand_value(total, 1, ctx)
        actions.append(Action(STAND, stand_ev))

        hit_ev = 0.0
        for r in RANKS:
            p = RANK_PROBS_F[r]
            nt, ns, bust = add_card(total, soft, r)
            hit_ev += p * ((-1.0) if bust else self._hand_value(nt, ns, False, 1, upcard))
        actions.append(Action(HIT, hit_ev))

        if self.cfg.double_any_two:
            dbl_ev = 0.0
            for r in RANKS:
                p = RANK_PROBS_F[r]
                nt, ns, bust = add_card(total, soft, r)
                dbl_ev += p * ((-2.0) if bust else self._stand_value(nt, 2, ctx))
            actions.append(Action(DOUBLE, dbl_ev))

        if (self.cfg.allow_split and len(cards) == 2 and cards[0] == cards[1]):
            actions.append(Action(SPLIT, self._split_value(cards[0], upcard)))

        best = max(actions, key=lambda a: a.ev)
        # Round-level peek term (dealer BJ resolved before you act -> lose base).
        play_value = best.ev
        round_play = (1 - peek_loss) * play_value + peek_loss * (-1.0)
        return actions, best, round_play - self.cfg.fee
