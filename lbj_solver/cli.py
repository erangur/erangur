"""Command-line tool for the Lightning Blackjack strategy engine.

Examples
--------
  # one-time precompute of the carry values (cached to disk)
  python -m lbj_solver.cli solve

  # optimal play for a concrete situation
  python -m lbj_solver.cli query --hand 10,6 --up 10 --carry 3 --set 21:12,BJ:25

  # full strategy grid for a scenario, deviations from plain blackjack marked *
  python -m lbj_solver.cli table --carry 1 --preset modal

  # validate RTP by simulation
  python -m lbj_solver.cli simulate --rounds 500000

  # dump the solved carry-continuation values
  python -m lbj_solver.cli carry
"""

import argparse
import sys

from .config import GameConfig
from .multipliers import MultiplierModel
from .solution import Solution
from .strategy import (resolve_tier, describe_set, format_grid, strategy_grid)

_RANK = {"A": 11, "J": 10, "Q": 10, "K": 10, "T": 10}


def parse_card(tok):
    tok = tok.strip().upper()
    if tok in _RANK:
        return _RANK[tok]
    n = int(tok)
    if n == 1:
        return 11
    if 2 <= n <= 11:
        return n
    raise ValueError(f"bad card: {tok}")


def parse_hand(s):
    return [parse_card(t) for t in s.replace(" ", ",").split(",") if t]


_TIER_HELP = ("revealed multiplier set, chosen as a whole tier (they are drawn "
              "as correlated sets, never per-bucket): a tier name (Low, Low-Mid, "
              "Mid, Mid-High, High, Nadir), its Blackjack multiplier "
              "(6/8/12/15/20/25), or min/max/modal")


def make_config(args):
    kw = {}
    if getattr(args, "fee", None) is not None:
        kw["fee"] = args.fee
    if getattr(args, "peek_ten", False):
        kw["peek_on_ten"] = True
    if getattr(args, "split_carry", None):
        kw["split_carry_rule"] = args.split_carry
    return GameConfig(**kw)


def get_solution(args, verbose=False):
    cfg = make_config(args)
    model = MultiplierModel.empirical()
    # The real menu has only 6 sets, so exact enumeration is the default.
    n_sets = None if getattr(args, "exact", False) else getattr(args, "nsets", None)
    return Solution.load_or_solve(model, cfg, n_sets=n_sets, iters=40,
                                  verbose=verbose,
                                  refresh=getattr(args, "refresh", False))


# --------------------------------------------------------------------------
def cmd_solve(args):
    sol = get_solution(args, verbose=True)
    print(f"\nGain (net per round, units of bet, fee={sol.config.fee}): {sol.gain:+.5f}")
    print(f"Gross value (fee-independent, = gain + fee): {sol.gross_value:+.5f}")
    print("For any fee, gain = gross_value - fee; break-even fee = "
          f"{sol.gross_value:.4f}")
    print("\nCarry continuation values (extra future value of carrying M):")
    for m in sorted(sol.carry_values):
        print(f"  h({m:>2}) = {sol.carry_values[m]:+.4f}")


def cmd_carry(args):
    sol = get_solution(args)
    print("Carry continuation values h(M)  (extra future value of carrying M):")
    for m in sorted(sol.carry_values):
        print(f"  h({m:>2}) = {sol.carry_values[m]:+.4f}")


def cmd_query(args):
    sol = get_solution(args)
    cards = parse_hand(args.hand)
    up = parse_card(args.up)
    tier_name, revealed_set = resolve_tier(sol.model, args.tier)
    actions, best, round_ev = sol.best_action(cards, up, args.carry, revealed_set)
    print(f"Hand {args.hand}  vs dealer {args.up}   carry={args.carry}")
    print(f"Revealed tier: {tier_name}  ({describe_set(revealed_set)})")
    print("-" * 56)
    for a in sorted(actions, key=lambda a: -a.ev):
        star = "  <-- OPTIMAL" if a.name == best.name else ""
        print(f"  {a.name:<7} EV = {a.ev:+.4f}{star}")
    print("-" * 56)
    print(f"Optimal: {best.name.upper()}   (round EV incl. fee = {round_ev:+.4f})")


def cmd_table(args):
    sol = get_solution(args)
    tier_name, revealed_set = resolve_tier(sol.model, args.tier)
    header, rows = strategy_grid(sol, args.carry, revealed_set,
                                 mark_deviations=not args.no_deviations)
    print(f"Optimal strategy   carry={args.carry}   "
          f"tier: {tier_name} ({describe_set(revealed_set)})")
    print("Codes: S=stand H=hit D=double P=split   "
          "(* = deviation from plain blackjack)")
    print()
    print(format_grid(header, rows))


def cmd_simulate(args):
    from .simulator import simulate
    sol = get_solution(args)
    print(f"Simulating {args.rounds:,} rounds (fee={sol.config.fee})...")
    stats = simulate(sol, n_rounds=args.rounds, seed=args.seed,
                     progress_every=args.rounds // 5 or None)
    print("-" * 56)
    print(f"  RTP                = {stats['rtp']:.5f}  "
          f"({stats['rtp']*100:.3f}%)")
    print(f"  net gain / round   = {stats['gain_per_round']:+.5f} "
          f"+/- {stats['gain_stderr']:.5f}")
    print(f"  VI  gain / round   = {sol.gain:+.5f}  (cross-check)")
    print(f"  avg turnover/round = {stats['avg_turnover']:.3f}")
    print(f"  action mix         = " +
          ", ".join(f"{k}={v:.3f}" for k, v in stats["action_mix"].items()))


def build_parser():
    p = argparse.ArgumentParser(prog="lbj_solver.cli",
                                description="Lightning Blackjack optimal strategy")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--fee", type=float, default=None,
                        help="Lightning fee in units of B (default 1.0 per DESIGN)")
        sp.add_argument("--peek-ten", action="store_true", dest="peek_ten",
                        help="dealer peeks on 10 upcard too (US/OBO rules)")
        sp.add_argument("--split-carry", choices=["max", "min"], dest="split_carry")
        sp.add_argument("--exact", action="store_true",
                        help="force exact enumeration (already the default)")
        sp.add_argument("--nsets", type=int, default=None,
                        help="sample N sets instead of exact enumeration")
        sp.add_argument("--refresh", action="store_true",
                        help="ignore cache and re-solve")

    sp = sub.add_parser("solve", help="compute & cache carry values")
    common(sp); sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("carry", help="print solved h(M)")
    common(sp); sp.set_defaults(func=cmd_carry)

    sp = sub.add_parser("query", help="optimal action for a situation")
    common(sp)
    sp.add_argument("--hand", required=True, help="e.g. 10,6 or A,7")
    sp.add_argument("--up", required=True, help="dealer upcard, e.g. 10 or A")
    sp.add_argument("--carry", type=int, default=1, help="multiplier carried into this round (1 = none)")
    sp.add_argument("--tier", default="modal", help=_TIER_HELP)
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("table", help="strategy grid for a scenario")
    common(sp)
    sp.add_argument("--carry", type=int, default=1, help="multiplier carried into this round (1 = none)")
    sp.add_argument("--tier", default="modal", help=_TIER_HELP)
    sp.add_argument("--no-deviations", action="store_true")
    sp.set_defaults(func=cmd_table)

    sp = sub.add_parser("simulate", help="Monte-Carlo RTP validation")
    common(sp)
    sp.add_argument("--rounds", type=int, default=1_000_000)
    sp.add_argument("--seed", type=int, default=1)
    sp.set_defaults(func=cmd_simulate)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ValueError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
