"""Exact dealer final-total distribution (infinite deck, stand on all 17s).

For each upcard we produce:
  * ``p_bj``   : probability the dealer has a natural blackjack.
  * ``dist``   : distribution over {17,18,19,20,21,'bust'} GIVEN not a natural
                 blackjack (a proper distribution summing to 1).

Peek handling is left to the engine; here we just split off the natural-BJ mass
and renormalise the rest, using the correct conditional hole-card weights:
  * Ace upcard   -> a natural needs a ten hole (4/13). Conditional-on-no-BJ
                    hole is drawn from {A,2..9}.
  * Ten upcard   -> a natural needs an Ace hole (1/13). Conditional-on-no-BJ
                    hole is drawn from {2..10}.
  * Other upcard -> no natural possible.
"""

from functools import lru_cache

from .cards import RANK_PROBS_F, RANKS, add_card, hand_from_cards

OUTCOMES = (17, 18, 19, 20, 21, "bust")


@lru_cache(maxsize=None)
def _final_dist(total, soft):
    """Distribution over final outcomes from a dealer hand ``(total, soft)``.

    Dealer stands on all 17s (incl. soft 17), hits below 17.
    """
    if total > 21:
        return {"bust": 1.0}
    if total >= 17:
        return {total: 1.0}
    out = {}
    for r in RANKS:
        p = RANK_PROBS_F[r]
        nt, ns, _ = add_card(total, soft, r)
        for k, v in _final_dist(nt, ns).items():
            out[k] = out.get(k, 0.0) + p * v
    return out


@lru_cache(maxsize=None)
def dealer_distribution(upcard):
    """Return ``(p_bj, dist)`` for a dealer showing ``upcard`` (2..10 or 11).

    ``dist`` is conditional on the dealer NOT having a natural blackjack.
    """
    p_bj = 0.0
    # Weighted sum over hole cards.
    agg = {}
    for hole in RANKS:
        p_hole = RANK_PROBS_F[hole]
        total, soft = hand_from_cards([upcard, hole])
        # Natural blackjack?
        if total == 21:  # two-card 21 = Ace + ten
            p_bj += p_hole
            continue
        for k, v in _final_dist(total, soft).items():
            agg[k] = agg.get(k, 0.0) + p_hole * v

    # Renormalise conditional-on-no-BJ.
    norm = 1.0 - p_bj
    dist = {k: v / norm for k, v in agg.items()} if norm > 0 else {}
    # Ensure all outcome keys exist.
    for k in OUTCOMES:
        dist.setdefault(k, 0.0)
    return p_bj, dist
