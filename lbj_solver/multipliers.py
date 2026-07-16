"""Multiplier sets and their distribution.

The game does NOT draw each winning-total bucket independently. It draws one of a
small **correlated menu of sets** (a "low" set is low across every bucket, a
"high" set high across every bucket). Reconstructed from the old
``lbj_env/multipliers.py`` tier tables; the 67-sample histogram in
``data/bj_multiplier_histogram.txt`` samples *which set occurred* — each distinct
Blackjack multiplier {6,8,12,15,20,25} identifies exactly one tier, so the
histogram of BJ values is the tier frequency.

A revealed set ``S`` maps each bucket to a multiplier:
    keys: '<=17', '18', '19', '20', '21', 'BJ'.

Per-hand decisions use the *actual revealed* set, so the distribution only drives
(a) the carry-continuation value h and (b) RTP — but because the buckets are
correlated, that distribution must be the real menu, not an independent product.
"""

import os
from collections import Counter

# Bucket keys in canonical order.
BUCKETS = ("<=17", "18", "19", "20", "21", "BJ")

# The correlated menu of multiplier sets (from lbj_env/multipliers.py tiers).
# Each tier is identified by its Blackjack multiplier.
TIERS = [
    ("Low",      {"<=17": 2, "18": 2, "19": 3, "20": 4,  "21": 5,  "BJ": 6}),
    ("Low-Mid",  {"<=17": 2, "18": 3, "19": 4, "20": 5,  "21": 6,  "BJ": 8}),
    ("Mid",      {"<=17": 2, "18": 3, "19": 4, "20": 5,  "21": 8,  "BJ": 12}),
    ("Mid-High", {"<=17": 2, "18": 4, "19": 5, "20": 6,  "21": 10, "BJ": 15}),
    ("High",     {"<=17": 2, "18": 5, "19": 6, "20": 8,  "21": 12, "BJ": 20}),
    ("Nadir",    {"<=17": 2, "18": 5, "19": 8, "20": 10, "21": 15, "BJ": 25}),
]
# BJ multiplier -> tier index (the histogram key).
_BJ_TO_TIER = {tier["BJ"]: i for i, (_, tier) in enumerate(TIERS)}

# Observed per-bucket ranges (min..max across the menu) — used only for parsing
# / validating user-supplied sets, not for the distribution.
BUCKET_RANGES = {b: tuple(sorted({tier[b] for _, tier in TIERS})) for b in BUCKETS}

# Every multiplier that can ever be carried forward (+ 1 = no carry). State space
# of the carry MDP.
CARRY_VALUES = tuple(sorted({1} | {m for _, tier in TIERS for m in tier.values()}))

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_bj_histogram(path=None):
    """Load the empirical Blackjack-multiplier counts -> {multiplier: count}."""
    path = path or os.path.join(_DATA_DIR, "bj_multiplier_histogram.txt")
    counts = Counter()
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                counts[int(line)] += 1
    return dict(counts)


def tier_by_bj(bj):
    """The full tier set whose Blackjack multiplier is ``bj`` (unique key)."""
    for name, tier in TIERS:
        if tier["BJ"] == bj:
            return name, dict(tier)
    valid = [tier["BJ"] for _, tier in TIERS]
    raise ValueError(f"no tier with BJ={bj}; valid BJ values: {valid}")


def tier_by_name(name):
    for tname, tier in TIERS:
        if tname.lower() == name.lower():
            return tname, dict(tier)
    raise ValueError(f"unknown tier '{name}'; valid: {[n for n, _ in TIERS]}")


def tier_name_of(revealed_set):
    """Name of the tier matching a set, or 'custom' if it isn't a real tier."""
    for name, tier in TIERS:
        if all(revealed_set.get(b) == tier[b] for b in tier):
            return name
    return "custom"


def bucket_of(total, natural):
    """Which bucket a *winning* final hand falls into."""
    if natural:
        return "BJ"
    if total <= 17:
        return "<=17"
    return str(total)


class MultiplierModel:
    """A distribution over multiplier sets, held as an explicit menu.

    ``sets`` is a list of ``(set_dict, probability)`` that sums to 1.
    """

    def __init__(self, sets):
        self.sets = sets

    # ---- constructors ---------------------------------------------------
    @classmethod
    def from_tiers(cls, bj_hist=None):
        """The real correlated menu: TIERS weighted by the BJ histogram."""
        bj_hist = bj_hist or load_bj_histogram()
        total = sum(bj_hist.values())
        sets = []
        for _, tier in TIERS:
            count = bj_hist.get(tier["BJ"], 0)
            if count:
                sets.append((dict(tier), count / total))
        return cls(sets)

    # Default model used everywhere.
    @classmethod
    def empirical(cls, bj_hist=None):
        return cls.from_tiers(bj_hist)

    @classmethod
    def independent(cls, bj_hist=None):
        """Legacy independent-bucket model (kept only for comparison).

        BJ marginal from the histogram; buckets 18-21 uniform over their ranges,
        drawn independently. This is the *incorrect* model — use ``from_tiers``.
        """
        bj_hist = bj_hist or load_bj_histogram()
        tot = sum(bj_hist.get(m, 0) for m in BUCKET_RANGES["BJ"])
        marg = {}
        for b in BUCKETS:
            rng = BUCKET_RANGES[b]
            if b == "BJ":
                marg[b] = {m: bj_hist.get(m, 0) / tot for m in rng}
            else:
                marg[b] = {m: 1 / len(rng) for m in rng}

        def rec(i, S, p):
            if i == len(BUCKETS):
                yield dict(S), p
                return
            b = BUCKETS[i]
            for mult, pm in marg[b].items():
                S[b] = mult
                yield from rec(i + 1, S, p * pm)

        return cls(list(rec(0, {}, 1.0)))

    # ---- derived views --------------------------------------------------
    @property
    def marginals(self):
        """Per-bucket marginal {multiplier: prob}, derived from the menu."""
        marg = {b: {} for b in BUCKETS}
        for S, p in self.sets:
            for b in BUCKETS:
                marg[b][S[b]] = marg[b].get(S[b], 0.0) + p
        return marg

    # ---- lookups --------------------------------------------------------
    def multiplier_for(self, S, total, natural):
        """Carry multiplier a winning hand earns under revealed set ``S``."""
        return S[bucket_of(total, natural)]

    # ---- sampling / enumeration ----------------------------------------
    def sample_set(self, rng):
        r, cum = rng.random(), 0.0
        for S, p in self.sets:
            cum += p
            if r <= cum:
                return S
        return self.sets[-1][0]

    def enumerate_sets(self):
        """Yield ``(set, probability)`` over the whole menu."""
        for S, p in self.sets:
            yield dict(S), p
