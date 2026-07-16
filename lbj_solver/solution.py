"""High-level solver: compute/cache the carry values and answer situations.

A ``Solution`` bundles the game config, the multiplier model and the solved
carry-continuation values ``h`` (plus the per-round gain ``g``). Because ``h`` is
independent of the fee (see module docs in ``carry.py``), we also store the
fee-independent gross value ``gross_value = g + fee`` so RTP/gain for any fee is instant.

Solutions are cached to ``data/solution.json`` keyed by the inputs that actually
affect ``h`` (multiplier marginals + split-carry rule + relevant rules), so the
~minute-long value iteration runs once.
"""

import hashlib
import json
import os

from .carry import solve_carry_values
from .config import DEFAULT_CONFIG, GameConfig
from .engine import Evaluator
from .multipliers import MultiplierModel

_CACHE = os.path.join(os.path.dirname(__file__), "data", "solution.json")


def _key(model, config):
    """Hash of everything that affects h (fee excluded on purpose)."""
    payload = {
        "marginals": {b: sorted(m.items()) for b, m in model.marginals.items()},
        "split_carry_rule": config.split_carry_rule,
        "dealer_stands_soft_17": config.dealer_stands_soft_17,
        "double_any_two": config.double_any_two,
        "allow_split": config.allow_split,
        "double_after_split": config.double_after_split,
        "split_aces_one_card": config.split_aces_one_card,
        "peek_on_ace": config.peek_on_ace,
        "peek_on_ten": config.peek_on_ten,
        "blackjack_payout": config.blackjack_payout,
    }
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


class Solution:
    def __init__(self, model, config, carry_values, gross_value):
        self.model = model
        self.config = config
        self.carry_values = carry_values
        # fee-independent gross per-round value (= gain + fee)
        self.gross_value = gross_value

    # ---- gain / RTP -----------------------------------------------------
    @property
    def gain(self):
        """Expected net result per round (units of B) at the config's fee."""
        return self.gross_value - self.config.fee

    # ---- solving / caching ---------------------------------------------
    @classmethod
    def solve(cls, model=None, config=DEFAULT_CONFIG, n_sets=None, iters=40,
              seed=12345, verbose=False):
        model = model or MultiplierModel.empirical()
        carry_values, gain, _ = solve_carry_values(
            model, config, n_sets=n_sets, iters=iters, seed=seed, verbose=verbose)
        return cls(model, config, carry_values, gain + config.fee)

    @classmethod
    def load_or_solve(cls, model=None, config=DEFAULT_CONFIG, n_sets=None,
                      iters=40, seed=12345, verbose=False, refresh=False):
        model = model or MultiplierModel.empirical()
        key = _key(model, config)
        cache = {}
        if os.path.exists(_CACHE):
            with open(_CACHE) as fh:
                cache = json.load(fh)
        if not refresh and key in cache:
            entry = cache[key]
            carry_values = {int(k): v for k, v in entry["carry_values"].items()}
            return cls(model, config, carry_values, entry["gross_value"])
        sol = cls.solve(model, config, n_sets=n_sets, iters=iters, seed=seed,
                        verbose=verbose)
        cache[key] = {
            "carry_values": {str(k): v for k, v in sol.carry_values.items()},
            "gross_value": sol.gross_value,
        }
        with open(_CACHE, "w") as fh:
            json.dump(cache, fh, indent=2)
        return sol

    # ---- querying -------------------------------------------------------
    def evaluator(self, multiplier_in, revealed_set):
        return Evaluator(self.model, self.carry_values, multiplier_in,
                         revealed_set, self.config)

    def best_action(self, cards, upcard, multiplier_in, revealed_set):
        """Return ``(actions, best, round_ev)`` for a situation."""
        return self.evaluator(multiplier_in, revealed_set).evaluate(cards, upcard)
