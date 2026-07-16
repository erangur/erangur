"""Monte-Carlo simulator: play full LBJ rounds under the solved strategy.

Validates the engine by (a) reproducing the value-iteration gain ``g`` as the
average net result per round and (b) reporting RTP to compare with the published
~99.56%. Faithfully models the carry mechanic, the flat fee, doubling, splitting
and the peek / no-peek dealer-blackjack rules.
"""

import random

from .cards import RANK_WEIGHTS, add_card, hand_from_cards, is_natural
from .engine import DOUBLE, SPLIT, STAND
from .multipliers import bucket_of

_RANK_POP = [r for r, w in RANK_WEIGHTS.items() for _ in range(w)]  # length 13


def _draw(rng):
    return rng.choice(_RANK_POP)


def _dealer_play(up, hole, rng):
    """Play the dealer out (stand on all 17s). Returns final total or 'bust'."""
    total, soft = hand_from_cards([up, hole])
    while total < 17:
        total, soft, bust = add_card(total, soft, _draw(rng))
        if bust:
            return "bust"
    return total


def _outcome(player_total, dealer_final):
    if player_total == "bust":
        return "loss"
    if dealer_final == "bust" or player_total > dealer_final:
        return "win"
    if player_total == dealer_final:
        return "push"
    return "loss"


class RoundResult:
    __slots__ = ("money_in", "returned", "new_carry")

    def __init__(self, money_in, returned, new_carry):
        self.money_in = money_in      # stake(s) + fee
        self.returned = returned      # paid back to player
        self.new_carry = new_carry    # multiplier carried to next round


def simulate(solution, n_rounds=1_000_000, seed=1, progress_every=0):
    """Run ``n_rounds`` and return a stats dict (RTP, gain, action mix, ...)."""
    cfg = solution.config
    model = solution.model
    rng = random.Random(seed)
    ev_cache = {}

    def get_ev(multiplier_in, revealed_set):
        key = (multiplier_in, tuple(sorted(revealed_set.items())))
        ev = ev_cache.get(key)
        if ev is None:
            ev = solution.evaluator(multiplier_in, revealed_set)
            ev_cache[key] = ev
        return ev

    multiplier_in = 1
    tot_in = tot_ret = 0.0
    net_sum = net_sq = 0.0
    action_counts = {STAND: 0, "hit": 0, DOUBLE: 0, SPLIT: 0}

    for i in range(n_rounds):
        revealed_set = model.sample_set(rng)
        res = _play_round(cfg, model, get_ev(multiplier_in, revealed_set), multiplier_in, revealed_set, rng, action_counts)
        net = res.returned - res.money_in
        tot_in += res.money_in
        tot_ret += res.returned
        net_sum += net
        net_sq += net * net
        multiplier_in = res.new_carry
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  {i+1:>10,} rounds  RTP={tot_ret/tot_in:.5f}  "
                  f"net/round={net_sum/(i+1):+.5f}")

    n = n_rounds
    mean = net_sum / n
    var = net_sq / n - mean * mean
    stderr = (var / n) ** 0.5
    return {
        "rounds": n,
        "rtp": tot_ret / tot_in,
        "gain_per_round": mean,
        "gain_stderr": stderr,
        "total_in": tot_in,
        "total_returned": tot_ret,
        "avg_turnover": tot_in / n,
        "action_mix": {k: v / max(1, sum(action_counts.values()))
                       for k, v in action_counts.items()},
    }


def _win_return(multiplier_in, stake, cfg, natural=False):
    """Amount returned on a winning sub-hand (stake back + winnings)."""
    if natural:
        winnings = (cfg.blackjack_payout if multiplier_in == 1 else multiplier_in) * stake
    else:
        winnings = multiplier_in * stake
    return stake + winnings


def _play_hand(ev, cards, up, multiplier_in, rng, can_double, action_counts,
               count_actions=True):
    """Play one hand to completion. Returns (final_total_or_'bust', stake)."""
    total, soft = hand_from_cards(cards)
    stake = 1.0
    while True:
        a = ev.hand_action(total, soft, can_double, stake, up)
        if count_actions:
            action_counts[a] += 1
            count_actions = False  # only count the first (top-level) decision
        if a == STAND:
            return total, stake
        if a == DOUBLE:
            total, soft, bust = add_card(total, soft, _draw(rng))
            return ("bust" if bust else total), 2.0
        total, soft, bust = add_card(total, soft, _draw(rng))  # hit
        can_double = False
        if bust:
            return "bust", stake


def _play_round(cfg, model, ev, multiplier_in, revealed_set, rng, action_counts):
    fee = cfg.fee
    player = [_draw(rng), _draw(rng)]
    up = _draw(rng)
    hole = _draw(rng)
    dealer_bj = up in (10, 11) and hand_from_cards([up, hole])[0] == 21
    does_peek = ((up == 11 and cfg.peek_on_ace) or (up == 10 and cfg.peek_on_ten))
    player_nat = is_natural(player)

    # Peek resolves dealer BJ before the player commits extra money.
    if does_peek and dealer_bj:
        stake = 1.0
        returned = stake if player_nat else 0.0  # push returns the bet
        return RoundResult(stake + fee, returned, 1)

    # Player natural: stands as blackjack.
    if player_nat:
        if dealer_bj:  # only reachable with no-peek on this upcard
            return RoundResult(1.0 + fee, 1.0, 1)
        returned = _win_return(multiplier_in, 1.0, cfg, natural=True)
        return RoundResult(1.0 + fee, returned, revealed_set["BJ"])

    # Decide the top-level action.
    actions, best, _ = ev.evaluate(player, up)
    action = best.name

    if action == SPLIT:
        action_counts[SPLIT] += 1
        hands = _play_split(ev, player[0], up, multiplier_in, rng)
        total_stake = sum(s for _, s in hands)
        money_in = total_stake + fee
        if dealer_bj:  # no-peek: dealer BJ takes everything staked
            return RoundResult(money_in, 0.0, 1)
        dealer_final = _dealer_play(up, hole, rng)
        returned = 0.0
        win_mults = []
        for ft, s in hands:
            r = _outcome(ft, dealer_final)
            if r == "win":
                returned += _win_return(multiplier_in, s, cfg)
                win_mults.append(revealed_set[bucket_of(ft, False)])
            elif r == "push":
                returned += s
        carry = _combine(win_mults, cfg) if win_mults else 1
        return RoundResult(money_in, returned, carry)

    # Stand / hit / double: play the single hand.
    ft, stake = _play_hand(ev, player, up, multiplier_in, rng, cfg.double_any_two,
                           action_counts)
    money_in = stake + fee
    if dealer_bj:  # no-peek: lose full stake
        return RoundResult(money_in, 0.0, 1)
    dealer_final = _dealer_play(up, hole, rng)
    r = _outcome(ft, dealer_final)
    if r == "win":
        return RoundResult(money_in, _win_return(multiplier_in, stake, cfg),
                           revealed_set[bucket_of(ft, False)])
    if r == "push":
        return RoundResult(money_in, stake, 1)
    return RoundResult(money_in, 0.0, 1)


def _play_split(ev, pair_rank, up, multiplier_in, rng):
    """Play both post-split hands. Returns [(final_total_or_'bust', stake), ...]."""
    hands = []
    for _ in range(2):
        first = _draw(rng)
        if pair_rank == 11 and ev.cfg.split_aces_one_card:
            total, _ = hand_from_cards([11, first])
            hands.append((total, 1.0))
        else:
            ft, stake = _play_hand(ev, [pair_rank, first], up, multiplier_in, rng,
                                   ev.cfg.double_after_split, None,
                                   count_actions=False)
            hands.append((ft, stake))
    return hands


def _combine(mults, cfg):
    return min(mults) if cfg.split_carry_rule == "min" else max(mults)
