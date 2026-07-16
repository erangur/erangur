"""Card / hand-value primitives for an infinite-deck blackjack model.

Infinite deck: every draw is i.i.d. with rank weights out of 13:
    2..9  -> weight 1 each
    10    -> weight 4 (10, J, Q, K)
    Ace   -> weight 1   (represented as rank 11)

A hand is summarised by the sufficient statistic ``(total, soft)`` where
``soft`` means "at least one Ace is currently counted as 11". This pair is a
sufficient statistic for optimal blackjack play (a standard result), which keeps
the state space tiny.
"""

from fractions import Fraction

# rank -> weight (out of 13). Ace is rank 11.
RANK_WEIGHTS = {2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 4, 11: 1}
DECK_SIZE = 13

# Probabilities as exact fractions (used for exact dealer/hand recursions).
RANK_PROBS = {r: Fraction(w, DECK_SIZE) for r, w in RANK_WEIGHTS.items()}
# Float version for speed-sensitive Monte-Carlo / large enumerations.
RANK_PROBS_F = {r: w / DECK_SIZE for r, w in RANK_WEIGHTS.items()}

RANKS = tuple(sorted(RANK_WEIGHTS))  # (2,3,...,10,11)


def add_card(total, soft, rank):
    """Add ``rank`` to a hand summarised by ``(total, soft)``.

    Returns ``(new_total, new_soft, busted)``. ``rank`` is 2..10 or 11 (Ace).
    """
    if rank == 11:
        was_soft = soft
        total += 11
        if total > 21:
            # This new Ace must count as 1.
            total -= 10
            soft = was_soft  # still soft only if a prior Ace is still an 11
        else:
            soft = True
    else:
        total += rank
        if total > 21 and soft:
            # Demote the usable Ace from 11 to 1.
            total -= 10
            soft = False
    return total, soft, total > 21


def hand_from_cards(ranks):
    """Build ``(total, soft)`` from a list of ranks (2..10, 11 for Ace)."""
    total, soft = 0, False
    for r in ranks:
        total, soft, _ = add_card(total, soft, r)
    return total, soft


def is_pair(card_a, card_b):
    """Two cards form a splittable pair iff they share the same *value*.

    Any two ten-valued cards (10/J/Q/K) count as a pair of tens.
    """
    return card_a == card_b


def is_natural(ranks):
    """True iff exactly two cards making 21 (Ace + ten) -> a natural blackjack."""
    return len(ranks) == 2 and hand_from_cards(ranks)[0] == 21
