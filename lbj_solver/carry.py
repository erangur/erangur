"""Carry-continuation value: the outer MDP over carried multipliers.

The state is the carried-in multiplier ``multiplier_in in {1} u (all set values)``.
Each round you (a) see a revealed set, (b) play optimally, (c) receive a net
reward R and (d) transition to a new carry (= revealed_set[final total] on a win,
else 1).

This is a continuing average-reward MDP. We solve the relative value function
``carry_values`` and the ``gain`` (expected net reward per round) by relative
value iteration, writing V for the one-step value, m for the carry state:

    V(m)             = E_{deal, set}[ R + carry_values(next) | m ]   (one backup)
    gain             = V(1)                        (reference state = no carry)
    carry_values(m) <- V(m) - gain                 (carry_values(1) stays 0)

``V(m)`` is exactly what ``Evaluator.evaluate`` returns as ``round_ev`` (it
already folds in the immediate reward, the flat fee, and the continuation value
of the carry earned). So one backup = re-evaluating every starting deal under the
current ``carry_values``.

Why this matters: at multiplier_in = 1 a base win nets zero cash, so the ENTIRE
value of a hand is the carry it earns -> ``carry_values`` is first-order there,
not a refinement. It is what makes the per-situation engine prefer
higher-multiplier totals.
"""

import random

from .cards import RANK_PROBS_F, RANKS
from .config import DEFAULT_CONFIG
from .engine import Evaluator
from .multipliers import CARRY_VALUES


def _starting_deals():
    """All distinct (cards, upcard, probability) starting positions."""
    deals = []
    for i, a in enumerate(RANKS):
        for b in RANKS[i:]:
            pair_prob = RANK_PROBS_F[a] * RANK_PROBS_F[b] * (1 if a == b else 2)
            for u in RANKS:
                p = pair_prob * RANK_PROBS_F[u]
                deals.append(([a, b], u, p))
    return deals


def solve_carry_values(model, config=DEFAULT_CONFIG, n_sets=None, iters=40,
                       tol=1e-7, seed=12345, verbose=False):
    """Solve for ``(carry_values, gain, history)``.

    ``n_sets``: number of sampled revealed sets used to approximate the
    expectation each backup (``None`` -> exact enumeration of the whole menu,
    which is cheap since the menu is small). Common random sets are reused across
    iterations for stable convergence. ``history`` is the gain per iteration.
    """
    deals = _starting_deals()

    if n_sets is None:
        sets = list(model.enumerate_sets())            # (revealed_set, prob)
    else:
        rng = random.Random(seed)
        sets = [(model.sample_set(rng), 1.0 / n_sets) for _ in range(n_sets)]

    carry_values = {m: 0.0 for m in CARRY_VALUES}
    history = []

    for it in range(iters):
        round_value = {}
        for multiplier_in in CARRY_VALUES:
            acc = 0.0
            for revealed_set, set_prob in sets:
                ev = Evaluator(model, carry_values, multiplier_in, revealed_set,
                               config)
                for cards, upcard, deal_prob in deals:
                    _, _, round_ev = ev.evaluate(cards, upcard)
                    acc += set_prob * deal_prob * round_ev
            round_value[multiplier_in] = acc
        gain = round_value[1]
        new_values = {m: round_value[m] - gain for m in CARRY_VALUES}
        delta = max(abs(new_values[m] - carry_values[m]) for m in CARRY_VALUES)
        carry_values = new_values
        history.append(gain)
        if verbose:
            print(f"  iter {it:2d}  gain={gain:+.5f}  delta={delta:.2e}")
        if delta < tol:
            break

    return carry_values, gain, history
