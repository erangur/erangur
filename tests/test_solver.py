"""Standalone test suite for the LBJ solver.  Run: python tests/test_solver.py

Covers card arithmetic, the exact dealer distribution, engine correctness
(reduces to basic strategy + known house edge), split arithmetic, carry-value
convergence, and simulator/engine consistency.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lbj_solver import GameConfig, MultiplierModel, Evaluator
from lbj_solver.cards import add_card, hand_from_cards
from lbj_solver.carry import _starting_deals, solve_carry_values
from lbj_solver.dealer import dealer_distribution
from lbj_solver.multipliers import CARRY_VALUES
from lbj_solver.cards import RANK_PROBS_F, RANKS
from lbj_solver.solution import Solution
from lbj_solver.simulator import _play_round

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


A = 11
SAMPLE_SET = {"<=17": 2, "18": 2, "19": 3, "20": 4, "21": 5, "BJ": 6}


def test_cards():
    print("cards:")
    check("A+A soft 12", hand_from_cards([A, A]) == (12, True))
    check("A+9 soft 20", hand_from_cards([A, 9]) == (20, True))
    t, s, bust = add_card(20, True, 5)  # soft20 + 5 -> hard 15
    check("soft20+5 -> hard15", (t, s, bust) == (15, False, False))
    t, s, bust = add_card(13, False, A)  # hard13 + A -> hard14
    check("hard13+A -> hard14", (t, s, bust) == (14, False, False))
    t, s, bust = add_card(15, False, 10)
    check("hard15+10 -> bust", bust and t == 25)


def test_dealer():
    print("dealer:")
    for u in RANKS:
        pbj, d = dealer_distribution(u)
        check(f"up {u} dist sums 1", abs(sum(d.values()) - 1.0) < 1e-9)
    check("p_bj on 10 = 1/13", abs(dealer_distribution(10)[0] - 1 / 13) < 1e-9)
    check("p_bj on A = 4/13", abs(dealer_distribution(11)[0] - 4 / 13) < 1e-9)
    check("bust vs 6 ~ 0.423", abs(dealer_distribution(6)[1]["bust"] - 0.4232) < 1e-3)
    check("bust vs 10 ~ 0.230", abs(dealer_distribution(10)[1]["bust"] - 0.2298) < 1e-3)


def _neutral_ev():
    model = MultiplierModel.empirical()
    carry_values = {m: 0.0 for m in CARRY_VALUES}
    return Evaluator(model, carry_values, 1, SAMPLE_SET, GameConfig(fee=0.0))


def test_basic_strategy():
    print("basic strategy (LBJ neutralised):")
    ev = _neutral_ev()

    def act(cards, up):
        return ev.evaluate(cards, up)[1].name

    cases = {
        ((10, 6), 10): "hit", ((10, 6), 6): "stand", ((10, 2), 4): "stand",
        ((6, 5), 5): "double", ((5, 4), 6): "double", ((A, 7), 3): "double",
        ((A, 7), 8): "stand", ((8, 8), 7): "split", ((9, 9), 7): "stand",
        ((10, 10), 6): "stand", ((5, 5), 6): "double", ((A, A), 8): "split",
        ((3, 3), 4): "split", ((10, 7), 10): "stand",
    }
    for (cards, up), exp in cases.items():
        check(f"{cards} v{up} -> {exp}", act(list(cards), up) == exp)


def test_house_edge():
    print("house edge (LBJ neutralised):")
    ev = _neutral_ev()
    deals = _starting_deals()
    edge = sum(p * ev.evaluate(c, u)[2] for c, u, p in deals)
    # fee=0 so round_ev == pure blackjack EV; ENHC no-peek-on-10 rules.
    check(f"edge {edge:.4f} in [-0.009,-0.006]", -0.009 < edge < -0.006)


def test_split_arithmetic():
    print("split arithmetic:")
    ev = _neutral_ev()
    for pair, up in [(8, 9), (2, 6), (7, 8)]:
        two = 2 * sum(RANK_PROBS_F[r] * ev._hand_value(*hand_from_cards([pair, r]),
                                                        False, 1, up) for r in RANKS)
        check(f"split {pair}v{up} == 2xsingle",
              abs(ev._split_value(pair, up) - two) < 1e-12)


def test_node_actions():
    print("node_actions (mid-hand solo evaluation):")
    ev = _neutral_ev()
    # For a 2-card non-pair hand, node_actions must reproduce evaluate's
    # stand/hit/double EVs exactly (it only drops the split branch).
    for cards, up in [([10, 6], 9), ([7, 4], 5), ([A, 6], 3)]:
        by_eval = {a.name: a.ev for a in ev.evaluate(cards, up)[0] if a.name != "split"}
        acts, _ = ev.node_actions(*hand_from_cards(cards), True, up)
        by_node = {a.name: a.ev for a in acts}
        check(f"node=eval {cards} v{up}",
              max(abs(by_eval[k] - by_node[k]) for k in by_node) < 1e-12)


def test_joint_split_hand():
    print("joint second-split-hand coupling:")
    # A busted/absent sibling must reduce the joint value to the solo value.
    model = MultiplierModel.empirical()
    sol = Solution.solve(model, GameConfig(), n_sets=40, seed=3)
    ev = sol.evaluator(1, SAMPLE_SET)
    ctx = ev._ctx(9)
    check("joint(None) stand == solo stand",
          all(abs(ev._joint_stand_value(t, 9, None) - ev._stand_value(t, 1, ctx)) < 1e-12
              for t in range(12, 22)))
    solo = {a.name: a.ev for a in ev.node_actions(16, False, False, 9)[0]}
    joint = {a.name: a.ev for a in ev.joint_node_actions(16, False, 9, None)[0]}
    check("joint(None) node == solo node",
          all(abs(solo[k] - joint[k]) < 1e-12 for k in joint))

    # A winning-capable sibling never lowers this hand's stand EV.
    sib20 = ev._sibling_carry(20)
    check("sibling never hurts stand EV",
          all(ev._joint_stand_value(t, 9, sib20) >= ev._joint_stand_value(t, 9, None) - 1e-12
              for t in range(12, 22)))

    # Flagship coupling: 17 vs dealer 9, base carry, low-tier set. A sibling
    # already at 20 (secured a 4x carry) makes standing right; a sibling at 18
    # leaves room to chase, so hitting the stiff 17 becomes optimal.
    ev6 = sol.evaluator(1, {"<=17": 2, "18": 2, "19": 3, "20": 4, "21": 5, "BJ": 6})
    best_hi = ev6.joint_node_actions(17, False, 9, 20)[1].name
    best_lo = ev6.joint_node_actions(17, False, 9, 18)[1].name
    check("17v9 stands behind a 20 sibling", best_hi == "stand")
    check("17v9 hits behind an 18 sibling", best_lo == "hit")


def test_carry_convergence():
    print("carry value iteration:")
    model = MultiplierModel.empirical()
    carry_values, gain, history = solve_carry_values(model, GameConfig(), n_sets=40, iters=30,
                                    seed=3)
    check("carry_values(1) == 0", carry_values[1] == 0.0)
    check("carry_values monotonic increasing", all(carry_values[a] < carry_values[b] for a, b in
          zip(sorted(carry_values)[:-1], sorted(carry_values)[1:])))
    check("converged (few iters)", len(history) <= 12)


def test_sim_consistency():
    print("simulator vs engine (per-round Bellman):")
    model = MultiplierModel.empirical()
    cfg = GameConfig()
    sol = Solution.solve(model, cfg, n_sets=40, seed=3)
    deals = _starting_deals()
    multiplier_in, revealed_set = 1, SAMPLE_SET
    ev = sol.evaluator(multiplier_in, revealed_set)
    exp = sum(p * ev.evaluate(c, u)[2] for c, u, p in deals)
    rng = random.Random(9)
    N, s = 60_000, 0.0
    ac = {"stand": 0, "hit": 0, "double": 0, "split": 0}
    for _ in range(N):
        r = _play_round(cfg, model, ev, multiplier_in, revealed_set, rng, ac)
        s += (r.returned - r.money_in) + sol.carry_values[r.new_carry]
    check(f"sim {s/N:.3f} ~ engine {exp:.3f}", abs(s / N - exp) < 0.03)


def test_auto_play_policy():
    print("auto-play policy:")
    from lbj_solver.engine import Action
    from lbj_solver.session import auto_action

    def node(actions, best_name, soft, total):
        best = next(a for a in actions if a.name == best_name)
        return {"actions": actions, "best": best, "soft": soft, "total": total}

    # Risk-free: solver says HIT on a hand that cannot bust -> auto, any margin.
    rf = node([Action("stand", -0.5), Action("hit", -0.4)], "hit", False, 8)
    a, r = auto_action(rf, carry=1, enabled=True, threshold=0.20)
    check("hard 8, best hit -> auto (risk-free)", a == "hit" and "risk-free" in r)
    soft = node([Action("stand", 0.1), Action("hit", 0.2)], "hit", True, 17)
    check("soft 17, best hit -> auto (cannot bust)",
          auto_action(soft, 1, True, 0.20)[0] == "hit")

    # High conviction: normalised margin clears the threshold (double can bust).
    hc = node([Action("double", 7.5), Action("hit", 5.5), Action("stand", 1.8)],
              "double", True, 15)  # margin 2.0 / carry 12 = 0.167
    check("Δ/carry 0.167 >= 0.15 -> auto double",
          auto_action(hc, 12, True, 0.15)[0] == "double")
    check("Δ/carry 0.167 <  0.20 -> ask",
          auto_action(hc, 12, True, 0.20)[0] is None)

    # Genuine close decision (bust possible, small margin) -> ask.
    close = node([Action("hit", 0.14), Action("stand", 0.03), Action("double", -0.31)],
                 "hit", False, 16)  # margin 0.11 / carry 1 < 0.20
    check("hard 16 v5, small margin -> ask", auto_action(close, 1, True, 0.20)[0] is None)

    # Auto disabled -> ask everything except a single legal action.
    check("auto disabled -> ask", auto_action(close, 1, False, 0.20)[0] is None)
    only = node([Action("stand", 0.0)], "stand", False, 20)
    check("single legal action -> auto even if disabled",
          auto_action(only, 1, False, 0.20)[0] == "stand")


_SESSION_SOL = None


def _session_sol():
    """A solved Solution shared across the session tests (solve once)."""
    global _SESSION_SOL
    if _SESSION_SOL is None:
        _SESSION_SOL = Solution.solve(MultiplierModel.empirical(), GameConfig(),
                                      n_sets=40, seed=3)
    return _SESSION_SOL


def _drive_round(sol, start_carry, revealed_set, cards, up, dealer,
                 action="stand", draw=10, auto=False):
    """Headless one-round driver. Returns the round-done summary."""
    from lbj_solver.session import Session
    s = Session(sol, start_carry=start_carry, auto=auto)
    summary, dealt = {}, []
    s.on_decision = lambda n: s.choose(action)
    s.on_card = lambda ctx: s.card(draw)
    s.on_dealer = lambda: (dealt.append(True), s.dealer(dealer))
    s.on_round_done = lambda summ: summary.update(summ)
    s.start_round(revealed_set)
    s.deal(cards, up)
    summary["_dealer_asked"] = bool(dealt)
    return summary


def test_session_round():
    print("session round + carry resolution:")
    sol = _session_sol()

    # Stand on 17, dealer 18 -> loss, carry dies to 1.
    loss = _drive_round(sol, 1, SAMPLE_SET, [10, 7], 10, dealer=18, action="stand")
    check("stand 17 loses to dealer 18", loss["new_carry"] == 1 and
          loss["outcomes"][0]["outcome"] == "loss")

    # Stand on 19, dealer 18 -> win; carry = the '19' bucket multiplier.
    win = _drive_round(sol, 1, SAMPLE_SET, [10, 9], 10, dealer=18, action="stand")
    check("win at 19 carries the 19-bucket mult",
          win["outcomes"][0]["outcome"] == "win" and
          win["new_carry"] == SAMPLE_SET["19"])

    # Hit a 16 and draw a ten -> bust; carry killed, dealer never asked.
    bust = _drive_round(sol, 5, SAMPLE_SET, [10, 6], 10, dealer=20,
                        action="hit", draw=10)
    check("all-bust kills carry to 1", bust["new_carry"] == 1)
    check("dealer not asked when all bust", bust["_dealer_asked"] is False)


def test_session_split():
    print("session split (two coupled hands):")
    from lbj_solver.session import Session
    sol = _session_sol()
    s = Session(sol, start_carry=1, auto=False)
    actions = iter(["split", "stand", "stand"])
    cards = iter([9, 9])       # each split hand gets a 9 -> 8,9 = 17
    summary = {}
    s.on_decision = lambda n: s.choose(next(actions))
    s.on_card = lambda ctx: s.card(next(cards))
    s.on_dealer = lambda: s.dealer(20)
    s.on_round_done = lambda summ: summary.update(summ)
    s.start_round(SAMPLE_SET)
    s.deal([8, 8], 9)          # split 8s
    check("split yields two hands", len(summary["outcomes"]) == 2)
    check("both 17s lose to dealer 20",
          all(o["outcome"] == "loss" for o in summary["outcomes"]) and
          summary["new_carry"] == 1)


def test_record_observed_set():
    print("observed-set recorder:")
    import csv
    import datetime
    import tempfile
    from lbj_solver.multipliers import BUCKETS, record_observed_set

    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.remove(path)                       # start from a non-existent file
    try:
        when = datetime.datetime(2026, 7, 20, 15, 30, 0)
        record_observed_set(SAMPLE_SET, path=path, now=when)
        record_observed_set(SAMPLE_SET, path=path, now=when)
        with open(path) as fh:
            rows = list(csv.reader(fh))
    finally:
        if os.path.exists(path):
            os.remove(path)
    check("header written once", rows[0] == ["timestamp", *BUCKETS])
    check("two samples appended (header + 2 rows)", len(rows) == 3)
    check("row = timestamp + bucket multipliers",
          rows[1] == [when.isoformat(timespec="seconds")] +
          [str(SAMPLE_SET[b]) for b in BUCKETS])


def test_observed_tier_counts():
    print("observed tier counts (filtering):")
    import datetime
    import tempfile
    from lbj_solver.multipliers import (observed_tier_counts, record_observed_set,
                                         tier_by_bj)
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.remove(path)
    now = datetime.datetime(2026, 7, 20, 15, 0, 0)
    try:
        # Three fresh BJ6 sets, one fresh BJ25, and one stale BJ12 (3h ago).
        for mins in (5, 10, 30):
            record_observed_set(tier_by_bj(6), path=path,
                                 now=now - datetime.timedelta(minutes=mins))
        record_observed_set(tier_by_bj(25), path=path,
                             now=now - datetime.timedelta(minutes=1))
        record_observed_set(tier_by_bj(12), path=path,
                             now=now - datetime.timedelta(hours=3))
        counts, total = observed_tier_counts(path=path, within_hours=2, now=now)
        check("stale sample excluded (2h window)", total == 4 and counts[12] == 0)
        check("fresh counts correct", counts[6] == 3 and counts[25] == 1)
        # last_n keeps only the most recent N of the in-window rows.
        counts2, total2 = observed_tier_counts(path=path, last_n=2, within_hours=2,
                                               now=now)
        check("last_n trims to most recent", total2 == 2 and counts2[25] == 1 and
              counts2[6] == 1)
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_overall_histogram():
    print("overall histogram (multi-file aggregation):")
    import datetime
    import tempfile
    from lbj_solver.multipliers import (new_session_file, overall_tier_counts,
                                         record_observed_set, tier_by_bj)
    directory = tempfile.mkdtemp()
    when = datetime.datetime(2026, 7, 20, 15, 0, 0)
    p1 = new_session_file(directory=directory, host="host A!", now=when, token="aaaa")
    p2 = new_session_file(directory=directory, host="hostB", now=when, token="bbbb")
    try:
        check("session files are unique per instance", p1 != p2)
        check("session file lives in the given dir", os.path.dirname(p1) == directory)
        check("hostname sanitised in filename", "host-A" in os.path.basename(p1))
        for _ in range(3):
            record_observed_set(tier_by_bj(6), path=p1, now=when)
        for _ in range(2):
            record_observed_set(tier_by_bj(25), path=p2, now=when)
        counts, total = overall_tier_counts(directory=directory, include_legacy=False,
                                            now=when)
        check("overall pools all session files",
              total == 5 and counts[6] == 3 and counts[25] == 2)
    finally:
        for p in (p1, p2):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(directory)


if __name__ == "__main__":
    for t in [test_cards, test_dealer, test_basic_strategy, test_house_edge,
              test_split_arithmetic, test_node_actions, test_joint_split_hand,
              test_carry_convergence, test_sim_consistency, test_auto_play_policy,
              test_session_round, test_session_split, test_record_observed_set,
              test_observed_tier_counts, test_overall_histogram]:
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
