"""Human-readable strategy tables and situation queries.

Because the revealed multiplier set is known before you act, a full "strategy" is
a function f(hand, upcard, multiplier_in, revealed_set). We render it as grids for
chosen (multiplier_in, revealed_set) scenarios and highlight where LBJ play
deviates from plain blackjack for the same rules (the deviations are the point).
"""

from .engine import DOUBLE, HIT, SPLIT, STAND
from .multipliers import BUCKET_RANGES, BUCKETS

# Action -> one-letter code.
CODE = {STAND: "S", HIT: "H", DOUBLE: "D", SPLIT: "P"}

UPCARDS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
UP_LABEL = {11: "A", 10: "10"}


def _rep_hard(total):
    """A representative non-pair, hard two-card combo for a hard total."""
    if total <= 11:
        base = {5: (3, 2), 6: (4, 2), 7: (5, 2), 8: (5, 3), 9: (5, 4),
                10: (6, 4), 11: (6, 5)}
        return list(base[total])
    return [10, total - 10]  # 12..19 -> 10 + x


def rep_hands():
    """Ordered (label, cards) for hard totals, soft totals and pairs."""
    rows = []
    for t in range(5, 20):
        rows.append((f"Hard {t}", _rep_hard(t)))
    for x in range(2, 10):
        rows.append((f"Soft {11 + x} (A,{x})", [11, x]))
    for r in range(2, 10):
        rows.append((f"Pair {r},{r}", [r, r]))
    rows.append(("Pair 10,10", [10, 10]))
    rows.append(("Pair A,A", [11, 11]))
    return rows


def action_code(actions, best):
    return CODE[best.name]


def build_set(spec=None, preset=None, model=None):
    """Construct a revealed set S.

    ``preset`` selects a whole tier from the menu (sets are correlated, so a
    per-bucket mix is not a real set): 'min' = lowest, 'max' = highest,
    'modal' = most probable. ``spec`` overrides individual buckets afterwards.
    """
    revealed_set = {b: BUCKET_RANGES[b][0] for b in BUCKETS}  # default: lowest tier
    if model is not None and getattr(model, "sets", None):
        if preset == "max":
            revealed_set = dict(max(model.sets, key=lambda sp: sp[0]["BJ"])[0])
        elif preset == "modal":
            revealed_set = dict(max(model.sets, key=lambda sp: sp[1])[0])
        else:  # 'min' or None
            revealed_set = dict(min(model.sets, key=lambda sp: sp[0]["BJ"])[0])
    elif preset == "max":
        revealed_set = {b: BUCKET_RANGES[b][-1] for b in BUCKETS}
    if spec:
        for b, m in spec.items():
            revealed_set[b] = m
    revealed_set["<=17"] = 2
    return revealed_set


def strategy_grid(solution, multiplier_in, revealed_set, mark_deviations=True):
    """Return (header, rows) where each row is (label, [codes...])."""
    ev = solution.evaluator(multiplier_in, revealed_set)
    # Plain-blackjack baseline: same rules, no LBJ mechanic (carry=0, mult_in=1).
    base_carry = {m: 0.0 for m in solution.carry_values}
    from .engine import Evaluator
    base = Evaluator(solution.model, base_carry, 1, revealed_set, solution.config)

    header = ["Hand"] + [UP_LABEL.get(u, str(u)) for u in UPCARDS]
    rows = []
    for label, cards in rep_hands():
        codes = []
        for up in UPCARDS:
            _, best, _ = ev.evaluate(cards, up)
            code = CODE[best.name]
            if mark_deviations:
                _, bbest, _ = base.evaluate(cards, up)
                if best.name != bbest.name:
                    code = code + "*"  # deviation from plain blackjack
            codes.append(code)
        rows.append((label, codes))
    return header, rows


def format_grid(header, rows):
    widths = [max(len(header[0]), max(len(r[0]) for r in rows))]
    for i in range(1, len(header)):
        widths.append(max(4, len(header[i])))
    out = []
    out.append("  ".join(cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i])
                          for i, cell in enumerate(header)))
    out.append("  ".join("-" * widths[i] for i in range(len(header))))
    for label, codes in rows:
        line = [label.ljust(widths[0])]
        line += [c.rjust(widths[i + 1]) for i, c in enumerate(codes)]
        out.append("  ".join(line))
    return "\n".join(out)


def describe_set(revealed_set):
    return " ".join(f"{b}:{revealed_set[b]}x" for b in BUCKETS)
