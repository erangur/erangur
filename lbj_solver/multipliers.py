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

import csv
import datetime
import os
import re
import socket
import uuid
from collections import Counter

# Bucket keys in canonical order.
BUCKETS = ("<=17", "18", "19", "20", "21", "BJ")

# The correlated menu of multiplier sets (from lbj_env/multipliers.py tiers).
# A set is identified by its Blackjack multiplier (unique across the menu).
TIERS = [
    {"<=17": 2, "18": 2, "19": 3, "20": 4,  "21": 5,  "BJ": 6},
    {"<=17": 2, "18": 3, "19": 4, "20": 5,  "21": 6,  "BJ": 8},
    {"<=17": 2, "18": 3, "19": 4, "20": 5,  "21": 8,  "BJ": 12},
    {"<=17": 2, "18": 4, "19": 5, "20": 6,  "21": 10, "BJ": 15},
    {"<=17": 2, "18": 5, "19": 6, "20": 8,  "21": 12, "BJ": 20},
    {"<=17": 2, "18": 5, "19": 8, "20": 10, "21": 15, "BJ": 25},
]
# Blackjack multipliers, in menu order (the identifiers for the sets).
TIER_BJ_VALUES = tuple(tier["BJ"] for tier in TIERS)

# Observed per-bucket ranges (min..max across the menu).
BUCKET_RANGES = {b: tuple(sorted({tier[b] for tier in TIERS})) for b in BUCKETS}

# Every multiplier that can ever be carried forward (+ 1 = no carry). State space
# of the carry MDP.
CARRY_VALUES = tuple(sorted({1} | {m for tier in TIERS for m in tier.values()}))

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
# Legacy single-file log (pre-per-session); still folded into the overall view.
OBSERVED_SETS_FILE = os.path.join(_DATA_DIR, "observed_sets.csv")
# One CSV per session/instance lives here. Uniquely named so instances on
# different machines never collide — commit & pull them and the overall
# histogram simply grows.
HISTOGRAM_DIR = os.path.join(_DATA_DIR, "histograms")


def new_session_file(directory=None, host=None, now=None, token=None):
    """A unique CSV path for one running instance's histogram.

    Named ``session_<host>_<YYYYMMDD-HHMMSS>_<token>.csv`` so two instances —
    even on the same machine at the same second — never pick the same file and
    git merges cleanly. The file itself is created lazily on the first record.
    """
    directory = directory or HISTOGRAM_DIR
    host = re.sub(r"[^A-Za-z0-9]+", "-", host or socket.gethostname()).strip("-")
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    token = token or uuid.uuid4().hex[:8]
    return os.path.join(directory, f"session_{host or 'host'}_{stamp}_{token}.csv")


def record_observed_set(revealed_set, path=None, now=None):
    """Append one observed revealed set to a session CSV log.

    Each row is a single real-world sample of which multiplier set the game
    revealed in a round: a timestamp followed by the multiplier for every bucket
    (the BJ column alone identifies the tier, but the full set is kept for later
    analysis). Header is written once. Returns the path written to.
    """
    path = path or OBSERVED_SETS_FILE
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    is_new = not os.path.exists(path)
    stamp = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    with open(path, "a", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["timestamp", *BUCKETS])
        writer.writerow([stamp, *(revealed_set[b] for b in BUCKETS)])
    return path


def _read_rows(path):
    """All ``(timestamp, revealed_set)`` samples from one CSV (unfiltered)."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)                       # header
        for row in reader:
            if len(row) < 1 + len(BUCKETS):
                continue
            try:
                ts = datetime.datetime.fromisoformat(row[0])
                vals = [int(x) for x in row[1:1 + len(BUCKETS)]]
            except ValueError:
                continue
            rows.append((ts, dict(zip(BUCKETS, vals))))
    return rows


def _filter_rows(rows, last_n, within_hours, now):
    if within_hours:
        now = now or datetime.datetime.now()
        cutoff = now - datetime.timedelta(hours=within_hours)
        rows = [r for r in rows if r[0] >= cutoff]
    if last_n is not None:
        rows = rows[-last_n:]
    return rows


def histogram_files(directory=None, include_legacy=True):
    """Every session CSV to fold into the overall histogram."""
    directory = directory or HISTOGRAM_DIR
    files = []
    if include_legacy and os.path.exists(OBSERVED_SETS_FILE):
        files.append(OBSERVED_SETS_FILE)
    if os.path.isdir(directory):
        files += [os.path.join(directory, n) for n in sorted(os.listdir(directory))
                  if n.endswith(".csv")]
    return files


def load_observed_sets(path=None, last_n=None, within_hours=2, now=None):
    """Recent observed sets from ONE log file, filtered to the last
    ``within_hours`` (``None`` = no limit) then trimmed to the last ``last_n``."""
    return _filter_rows(_read_rows(path or OBSERVED_SETS_FILE), last_n,
                        within_hours, now)


def load_all_observed_sets(directory=None, last_n=None, within_hours=None,
                           now=None, include_legacy=True):
    """Observed sets pooled across ALL session files, sorted by time."""
    rows = []
    for path in histogram_files(directory, include_legacy):
        rows += _read_rows(path)
    rows.sort(key=lambda r: r[0])
    return _filter_rows(rows, last_n, within_hours, now)


def _tier_counts(rows):
    counts = {bj: 0 for bj in TIER_BJ_VALUES}
    for _, revealed_set in rows:
        bj = revealed_set.get("BJ")
        if bj in counts:
            counts[bj] += 1
    return counts, len(rows)


def observed_tier_counts(path=None, last_n=None, within_hours=2, now=None):
    """Tier frequencies from ONE session file (used for the current session).

    Returns ``(counts, total)`` where ``counts`` covers every menu BJ value.
    """
    return _tier_counts(load_observed_sets(path, last_n, within_hours, now))


def overall_tier_counts(directory=None, now=None, include_legacy=True):
    """Tier frequencies pooled across every session file (the overall view)."""
    return _tier_counts(load_all_observed_sets(directory, now=now,
                                               include_legacy=include_legacy))


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
    """The full set whose Blackjack multiplier is ``bj`` (its unique identifier)."""
    for tier in TIERS:
        if tier["BJ"] == bj:
            return dict(tier)
    raise ValueError(f"no set with BJ={bj}; valid BJ values: {list(TIER_BJ_VALUES)}")


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
        for tier in TIERS:
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
