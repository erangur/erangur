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


if __name__ == "__main__":
    for t in [test_cards, test_dealer, test_basic_strategy, test_house_edge,
              test_split_arithmetic, test_node_actions, test_joint_split_hand,
              test_carry_convergence, test_sim_consistency]:
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
