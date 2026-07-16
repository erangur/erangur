"""Game rules and payout configuration for Lightning Blackjack.

Everything the solver treats as a rule lives here so that assumptions (some of
which the design flags as *unconfirmed*) can be changed in one place and the
whole engine + simulator recomputed.

Units: the base bet is ``B = 1``. All monetary values are in units of B.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameConfig:
    # ---- Fee -------------------------------------------------------------
    # The "Lightning Fee". Per the DESIGN.md model this equals the base bet
    # (fee = B) and is a flat per-ROUND charge that never scales with
    # double/split and is never returned. Real Evolution LBJ uses a 20% fee
    # (fee = 0.2). Kept configurable because the two give very different
    # strategies/RTP; DESIGN's payout table implies fee == 1.0.
    fee: float = 1.0

    # ---- Payouts ---------------------------------------------------------
    # Natural blackjack pays 3:2, but ONLY when no multiplier is carried in
    # (multiplier_in == 1). With a carried multiplier the BJ is paid at the multiplier
    # with no extra 1.5x (DESIGN payout table).
    blackjack_payout: float = 1.5

    # ---- Dealer ----------------------------------------------------------
    dealer_stands_soft_17: bool = True  # stands on all 17s incl. soft 17

    # ---- Player options --------------------------------------------------
    double_any_two: bool = True          # double allowed on any 2-card total
    allow_split: bool = True
    resplit: bool = False                # one split only, no re-split
    double_after_split: bool = False     # DAS not allowed
    split_aces_one_card: bool = True     # split Aces get exactly one card each
    surrender: bool = False
    six_card_charlie: bool = False

    # ---- Dealer peek -----------------------------------------------------
    peek_on_ace: bool = True             # dealer peeks on Ace upcard
    peek_on_ten: bool = False            # dealer does NOT peek on 10 upcard

    # ---- Split + carry rule (UNCONFIRMED in DESIGN) ----------------------
    # When you split and one/both hands win, a single multiplier is carried to
    # the next round. Rule options:
    #   'max' -> carry the highest winning bucket multiplier (default)
    #   'min' -> carry the lowest winning bucket multiplier
    # This only affects the carry-continuation value, not the base EV.
    split_carry_rule: str = "max"


DEFAULT_CONFIG = GameConfig()
