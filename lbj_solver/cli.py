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

from .cards import add_card, hand_from_cards, is_natural
from .config import GameConfig
from .engine import DOUBLE, HIT, SPLIT, STAND
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


_TIER_HELP = ("revealed multiplier set, chosen as a whole set (they are drawn as "
              "correlated sets, never per-bucket) by its Blackjack multiplier "
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


def _print_decision(sol, cards, up, carry, revealed_set, hand_label, up_label):
    actions, best, round_ev = sol.best_action(cards, up, carry, revealed_set)
    print(f"\nHand {hand_label}  vs dealer {up_label}   carry={carry}")
    print(f"Revealed set (BJ {revealed_set['BJ']}x): {describe_set(revealed_set)}")
    print("-" * 56)
    for a in sorted(actions, key=lambda a: -a.ev):
        star = "  <-- OPTIMAL" if a.name == best.name else ""
        print(f"  {a.name:<7} EV = {a.ev:+.4f}{star}")
    print("-" * 56)
    print(f"Optimal: {best.name.upper()}   (round EV incl. fee = {round_ev:+.4f})")


def _up_label(up):
    return "A" if up == 11 else str(up)


def cmd_query(args):
    sol = get_solution(args)
    cards = parse_hand(args.hand)
    given = [p for p in ("up", "carry", "tier") if getattr(args, p) is not None]
    if len(given) < 2:
        raise ValueError("give at least two of --up, --carry, --tier "
                         "(omit exactly one to sweep it)")
    up = parse_card(args.up) if args.up is not None else None
    carry = args.carry
    revealed_set = resolve_tier(sol.model, args.tier) if args.tier is not None else None

    if up is not None and carry is not None and revealed_set is not None:
        _print_decision(sol, cards, up, carry, revealed_set, args.hand, args.up)
        return
    missing = next(p for p in ("up", "carry", "tier") if getattr(args, p) is None)
    _print_sweep(sol, cards, args.hand, missing, up, carry, revealed_set)


def _print_sweep(sol, cards, hand_label, param, up, carry, revealed_set):
    """Sweep the one omitted parameter and summarise the optimal play by range."""
    from .multipliers import CARRY_VALUES, TIER_BJ_VALUES, tier_by_bj

    if param == "up":
        seq = [(u, _up_label(u)) for u in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11)]
        combo = lambda v: (v, carry, revealed_set)
        pname = "dealer up"
        fixed = f"carry={carry}, set BJ {revealed_set['BJ']}x"
    elif param == "carry":
        seq = [(v, str(v)) for v in CARRY_VALUES]
        combo = lambda v: (up, v, revealed_set)
        pname = "carry"
        fixed = f"up={_up_label(up)}, set BJ {revealed_set['BJ']}x"
    else:  # tier
        seq = [(bj, f"BJ{bj}") for bj in TIER_BJ_VALUES]
        combo = lambda v: (up, carry, tier_by_bj(v))
        pname = "set"
        fixed = f"up={_up_label(up)}, carry={carry}"

    results = []
    for value, label in seq:
        u, c, rs = combo(value)
        _, best, round_ev = sol.best_action(cards, u, c, rs)
        results.append((label, best.name, round_ev))

    # Group consecutive values that share the same optimal action.
    groups = []
    for label, action, ev in results:
        if groups and groups[-1][0] == action:
            groups[-1][1].append(label)
            groups[-1][2].append(ev)
        else:
            groups.append([action, [label], [ev]])

    print(f"\nHand {hand_label}  ({fixed})   — sweeping {pname}")
    print("-" * 56)
    if len(groups) == 1:
        print(f"Optimal action is {groups[0][0].upper()} for every {pname} value.")
    else:
        for action, labels, evs in groups:
            rng = labels[0] if len(labels) == 1 else f"{labels[0]}–{labels[-1]}"
            print(f"  {pname} {rng:<9}: {action.upper():<6} "
                  f"(EV {min(evs):+.2f} … {max(evs):+.2f})")
    best = max(results, key=lambda r: r[2])
    worst = min(results, key=lambda r: r[2])
    print("-" * 56)
    print(f"Highest EV at {pname}={best[0]} ({best[2]:+.2f}, {best[1].upper()}); "
          f"lowest at {pname}={worst[0]} ({worst[2]:+.2f})")


def cmd_table(args):
    sol = get_solution(args)
    revealed_set = resolve_tier(sol.model, args.tier)
    header, rows = strategy_grid(sol, args.carry, revealed_set,
                                 mark_deviations=not args.no_deviations)
    print(f"Optimal strategy   carry={args.carry}   "
          f"set BJ {revealed_set['BJ']}x  ({describe_set(revealed_set)})")
    print("Codes: S=stand H=hit D=double P=split   "
          "(* = deviation from plain blackjack)")
    print()
    print(format_grid(header, rows))


def _ask(prompt, parse, default=None):
    """Prompt until ``parse`` accepts the input; blank uses ``default``."""
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            return parse(raw)
        except (ValueError, KeyError) as e:
            print(f"  ! {e}")


_ACTION_ALIASES = {
    "s": STAND, "stand": STAND, "h": HIT, "hit": HIT,
    "d": DOUBLE, "double": DOUBLE, "p": SPLIT, "split": SPLIT,
}


def _card_label(c):
    return "A" if c == 11 else str(c)


def _hand_str(cards):
    return ",".join(_card_label(c) for c in cards)


def _parse_action(legal):
    """Return a parser accepting any action name in ``legal`` (or its initial)."""
    def parse(raw):
        a = _ACTION_ALIASES.get(raw.strip().lower())
        if a is None or a not in legal:
            raise ValueError(f"choose one of: {', '.join(legal)}")
        return a
    return parse


def _show_actions(actions, best, title):
    print(f"\n{title}")
    print("-" * 56)
    for a in sorted(actions, key=lambda a: -a.ev):
        star = "  <-- SUGGESTED" if a.name == best.name else ""
        print(f"  {a.name:<7} EV = {a.ev:+.4f}{star}")
    print("-" * 56)
    print(f"Suggested: {best.name.upper()}")


def parse_dealer(raw):
    """Parse a dealer final total: a number, or 'bust' (a number >21 is a bust)."""
    raw = raw.strip().lower()
    if raw in ("bust", "b", "busted", "x"):
        return "bust"
    n = int(raw)
    if n > 21:
        return "bust"      # over 21 is a bust
    if not 2 <= n <= 21:
        raise ValueError("dealer total must be 2-21, or 'bust'")
    return n


def _hand_outcome(total, dealer_final):
    """'win' / 'push' / 'loss' for a standing player ``total`` vs the dealer."""
    if total is None:
        return "loss"
    if dealer_final == "bust" or total > dealer_final:
        return "win"
    if total == dealer_final:
        return "push"
    return "loss"


def cmd_wizard(args):
    from .multipliers import TIERS, TIER_BJ_VALUES
    sol = get_solution(args)
    print("Lightning Blackjack — interactive strategy wizard")
    print("Plays a continuous session: each round it suggests the optimal play,")
    print("asks what you actually did and which card came (splits included), then")
    print("asks the dealer's result and carries the multiplier into the next round.")
    print("Press Ctrl-D (or Ctrl-C) at any prompt to quit.\n")

    def pick(raw):
        n = int(raw)
        if 1 <= n <= len(TIERS):        # menu number
            return dict(TIERS[n - 1])
        if n in TIER_BJ_VALUES:         # or the BJ value itself
            return next(dict(t) for t in TIERS if t["BJ"] == n)
        raise ValueError(f"choose 1-{len(TIERS)} or a BJ value {list(TIER_BJ_VALUES)}")

    carry = _ask("Carried-in multiplier to start [1 = none]: ", int, default=1)

    round_no = 1
    try:
        while True:
            print(f"\n{'='*56}\nRound {round_no}   (carrying in {carry}x)\n{'='*56}")
            print("Revealed multipliers this round — pick the set by its "
                  "Blackjack multiplier:")
            for i, tier in enumerate(TIERS, 1):
                body = " ".join(f"{b}:{tier[b]}" for b in ("18", "19", "20", "21"))
                print(f"  {i})  BJ {tier['BJ']:>2}x   ({body})")
            revealed_set = _ask("Set: ", pick)
            cards = _ask("Your hand (e.g. 10,6 or A,7): ", parse_hand)
            up = _ask("Dealer upcard (2-10, A): ", parse_card)

            ev = sol.evaluator(carry, revealed_set)
            print(f"\nSet BJ {revealed_set['BJ']}x  ({describe_set(revealed_set)})"
                  f"    carry={carry}    dealer {_up_label(up)}")
            hands = _interactive_round(ev, cards, up)
            carry = _resolve_round(ev, hands)
            print(f"\n  => carry into next round: {carry}x")
            round_no += 1
    except (EOFError, KeyboardInterrupt):
        print("\n\nSession ended.")


def _interactive_round(ev, cards, up):
    """Play one round interactively. Returns ``[(final_total_or_None, natural)]``
    — one entry per hand (two after a split)."""
    if is_natural(cards):
        print(f"\n{_hand_str(cards)} is a natural blackjack — no decision, "
              "you stand and get paid.")
        return [(21, True)]

    total, soft = hand_from_cards(cards)
    actions, best, _ = ev.evaluate(cards, up)
    _show_actions(actions, best,
                  f"Your hand {_hand_str(cards)} (total {total}) vs dealer "
                  f"{_up_label(up)}")
    chosen = _ask("What did you choose? ", _parse_action([a.name for a in actions]))

    if chosen == SPLIT:
        return _play_split(ev, cards[0], up)
    if chosen == STAND:
        print(f"  You stand at {total}.")
        return [(total, False)]
    if chosen == DOUBLE:
        c = _ask("Card drawn on the double? ", parse_card)
        nt, ns, bust = add_card(total, soft, c)
        print(f"  -> {_hand_str(cards + [c])} = {'BUST' if bust else nt} "
              "(doubled stake)")
        return [(None if bust else nt, False)]
    # hit
    c = _ask("Card drawn? ", parse_card)
    nt, ns, bust = add_card(total, soft, c)
    if bust:
        print(f"  -> {_hand_str(cards + [c])} = {nt} BUST")
        return [(None, False)]
    return [(_continue_solo_hand(ev, cards + [c], up), False)]


def _continue_solo_hand(ev, cards, up):
    """Play a single hand out card by card after the first hit. Returns the
    final total, or None if it busted."""
    total, soft = hand_from_cards(cards)
    while True:
        if total == 21:
            print(f"  {_hand_str(cards)} = 21 — you stand.")
            return 21
        actions, best = ev.node_actions(total, soft, False, up)  # no double after a hit
        _show_actions(actions, best,
                      f"Hand {_hand_str(cards)} (total {total}) vs dealer "
                      f"{_up_label(up)}")
        chosen = _ask("What did you choose? ", _parse_action([a.name for a in actions]))
        if chosen == STAND:
            print(f"  You stand at {total}.")
            return total
        c = _ask("Card drawn? ", parse_card)
        cards = cards + [c]
        total, soft, bust = add_card(total, soft, c)
        if bust:
            print(f"  -> {_hand_str(cards)} = {total} BUST")
            return None


def _play_split(ev, pair_rank, up):
    """Play both post-split hands in order; hand 2 is coupled to hand 1's total.
    Returns ``[(t1, False), (t2, False)]``."""
    print(f"\n=== SPLIT {_card_label(pair_rank)}s — two hands, played in order ===")
    print("Hand 1 is played first; hand 2's advice then accounts for hand 1's "
          f"final\ntotal, since the carry combines the two ({ev.cfg.split_carry_rule}).")
    t1 = _play_split_hand(ev, pair_rank, up, 1, partner="solo")
    t2 = _play_split_hand(ev, pair_rank, up, 2, partner=t1)
    return [(t1, False), (t2, False)]


def _play_split_hand(ev, pair_rank, up, hand_no, partner):
    """Play one post-split hand. ``partner`` is 'solo' (hand 1) or hand 1's final
    total / None (hand 2). Returns this hand's final total, or None if it busted.
    """
    if pair_rank == 11 and ev.cfg.split_aces_one_card:
        c = _ask(f"\nHand {hand_no}: card dealt to the split Ace? ", parse_card)
        total, _ = hand_from_cards([11, c])
        print(f"  Hand {hand_no}: A,{_card_label(c)} = {total} "
              "(split aces get one card only)")
        return total

    c = _ask(f"\nHand {hand_no}: first card dealt to the {_card_label(pair_rank)}? ",
             parse_card)
    cards = [pair_rank, c]
    total, soft = hand_from_cards(cards)
    while True:
        if total == 21:
            print(f"  Hand {hand_no} {_hand_str(cards)} = 21 — stands.")
            return 21
        if partner == "solo":
            actions, best = ev.node_actions(total, soft, False, up)  # no DAS
        else:
            actions, best = ev.joint_node_actions(total, soft, up, partner)
        _show_actions(actions, best,
                      f"Hand {hand_no} {_hand_str(cards)} (total {total}) vs "
                      f"dealer {_up_label(up)}")
        chosen = _ask("What did you choose? ", _parse_action([a.name for a in actions]))
        if chosen == STAND:
            print(f"  Hand {hand_no} stands at {total}.")
            return total
        c = _ask("Card drawn? ", parse_card)
        cards = cards + [c]
        total, soft, bust = add_card(total, soft, c)
        if bust:
            print(f"  Hand {hand_no} {_hand_str(cards)} = {total} BUST.")
            return None


def _resolve_round(ev, hands):
    """Ask the dealer's result, report each hand, and return the carry forward."""
    if all(t is None for t, _ in hands):
        print("\nAll hands busted — you lose. Carry resets to 1x.")
        return 1

    dealer = _ask("\nDealer's final total? (number, or 'bust'): ", parse_dealer)
    d_label = "bust" if dealer == "bust" else str(dealer)
    take_max = ev.cfg.split_carry_rule != "min"
    win_mults = []
    for i, (total, natural) in enumerate(hands, 1):
        label = f"Hand {i}" if len(hands) > 1 else "Your hand"
        outcome = _hand_outcome(total, dealer)
        if total is None:
            print(f"  {label}: bust — loss.")
        elif outcome == "win":
            m = ev.model.multiplier_for(ev.revealed_set, total, natural)
            win_mults.append(m)
            tag = "natural blackjack" if natural else f"{total}"
            print(f"  {label}: {tag} beats dealer {d_label} — WIN, earns {m}x carry.")
        elif outcome == "push":
            print(f"  {label}: {total} pushes dealer {d_label} — no carry.")
        else:
            print(f"  {label}: {total} loses to dealer {d_label}.")

    if not win_mults:
        print("  No winning hand — carry resets to 1x.")
        return 1
    carry = (max if take_max else min)(win_mults)
    if len(win_mults) > 1:
        which = "highest" if take_max else "lowest"
        print(f"  Two winning hands — carrying the {which}: {carry}x "
              f"(rule '{ev.cfg.split_carry_rule}').")
    return carry


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

    sp = sub.add_parser("wizard", help="interactive prompt-by-prompt query")
    common(sp); sp.set_defaults(func=cmd_wizard)

    sp = sub.add_parser("solve", help="compute & cache carry values")
    common(sp); sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("carry", help="print solved h(M)")
    common(sp); sp.set_defaults(func=cmd_carry)

    sp = sub.add_parser("query", help="optimal action; omit one param to sweep it")
    common(sp)
    sp.add_argument("--hand", required=True, help="e.g. 10,6 or A,7 (always required)")
    sp.add_argument("--up", default=None, help="dealer upcard 2-10/A (omit to sweep)")
    sp.add_argument("--carry", type=int, default=None,
                    help="carried-in multiplier, 1 = none (omit to sweep)")
    sp.add_argument("--tier", default=None, help=_TIER_HELP + " (omit to sweep)")
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
