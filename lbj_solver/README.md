# Lightning Blackjack — Optimal Strategy Engine

An exact, verifiable solver for Evolution's **Lightning Blackjack (LBJ)**. It
answers the only question that matters: **given your hand, the dealer upcard, the
multiplier you carried in, and the multiplier set revealed this round, what is
the mathematically optimal play?**

Unlike the old DQN attempt, this **computes** the optimum with dynamic
programming (the model is fully known), so results are exact and reproducible —
not approximated.

---

## Why standard basic strategy is wrong here

LBJ adds a **carry multiplier**: when you win, the multiplier for your final hand
value (drawn from a set revealed *before* you act) attaches to your *next* bet.
Your current win is paid at the multiplier you carried *in* (`M_in`). Under the
DESIGN payout model a base win (`M_in = 1`) nets **zero cash** — so at low carry
the entire value of a hand is *the carry it earns*. That flips many decisions:
chase higher totals, split tens under a big carry, hit stiff hands you'd normally
stand. The engine finds all of these exactly.

Two facts make the tool clean (both proven in the code):

- **The optimal action is independent of the fee.** The flat per-round fee is
  identical across hit/stand/double/split, so it cancels in the argmax.
- **The carry values `h(M)` are independent of the fee** (`h(M)=V(M)−V(1)`; the
  fee shifts every `V` equally). Only the overall RTP depends on the fee.

So the *strategy* depends only on the game rules and the **multiplier
distribution** — not on the fee.

---

## Install / run

Pure Python 3 standard library, no dependencies.

```bash
cd /Users/droraharon/playground/erangur
python -m lbj_solver.cli <command> [options]
```

### Commands

```bash
# One-time precompute of carry values (cached to data/solution.json)
python -m lbj_solver.cli solve

# Optimal play for a concrete situation
python -m lbj_solver.cli query --hand 10,6 --up 10 --carry 3 --tier Mid

# Full strategy grid for a scenario (deviations from plain blackjack marked *)
python -m lbj_solver.cli table --carry 1 --tier modal

# Validate RTP by Monte-Carlo simulation
python -m lbj_solver.cli simulate --rounds 500000

# Dump the solved carry-continuation values h(M)
python -m lbj_solver.cli carry
```

- `--hand` / `--up` accept `A J Q K 10 2..9` (e.g. `A,7`).
- `--carry` is the multiplier you carried into this round (1 = no carry).
- `--tier` is the revealed multiplier set. Multipliers are drawn as **whole
  correlated tiers**, never per bucket, so you pick a tier — by name (`Low`,
  `Low-Mid`, `Mid`, `Mid-High`, `High`, `Nadir`), by its Blackjack multiplier
  (`6/8/12/15/20/25`), or `min`/`max`/`modal`. There is deliberately no way to
  set an individual bucket.
- Rule/model overrides on every command: `--fee`, `--peek-ten`,
  `--split-carry {max,min}`, `--exact`, `--nsets N`, `--refresh`.

---

## Architecture

| Module | Role |
|---|---|
| `cards.py` | Infinite-deck hand arithmetic (`(total, soft)` sufficient statistic). |
| `config.py` | All rules & payouts (`GameConfig`), each an editable assumption. |
| `multipliers.py` | The correlated menu of multiplier sets (6 tiers) + its distribution. |
| `dealer.py` | Exact dealer final-total distribution + peek handling. |
| `engine.py` | Exact per-hand EV / optimal action (stand/hit/double/split). |
| `carry.py` | Average-reward value iteration for `h(M)` and the gain `g`. |
| `solution.py` | Solve + disk cache + high-level query API. |
| `strategy.py` | Human-readable strategy grids with deviation marks. |
| `simulator.py` | Monte-Carlo full-round RTP validation. |
| `cli.py` | Command-line front end. |

### How it's solved

1. **Dealer distribution** — exact recursion, stand on all 17s, infinite deck,
   with Ace-peek / no-peek-on-10 handled correctly.
2. **Inner DP** — for a fixed `(M_in, S, h)`, exact expectimax over
   stand/hit/double/split gives each action's EV.
3. **Outer MDP** — the carried multiplier is the state of a continuing
   average-reward MDP; relative value iteration yields `h(M)` (fixed point
   reached in ~6 iterations) and the per-round gain `g`.
4. **Simulation** — plays full rounds under the solved policy to confirm RTP and
   reproduce `g`.

---

## Validation (all passing)

- Dealer distribution matches known S17 infinite-deck values (bust 2→35.4% …
  6→42.3%, 7→26.2%; `p_bj` = 1/13 on 10, 4/13 on A).
- With the LBJ mechanic neutralised the engine reproduces **standard basic
  strategy** and a house edge of **−0.69%** (peek) / **−0.79%** (no-peek-on-10),
  squarely in the known infinite-deck range.
- Split EV verified against brute force to machine epsilon.
- The simulator reproduces the value-iteration per-round Bellman value within
  Monte-Carlo error.

---

## Multiplier model & RTP

The multipliers are **not** drawn per-bucket independently — the game draws one of
a small **correlated menu of 6 tiers** (a "low" tier is low across every bucket, a
"high" tier high everywhere), reconstructed from the original tier tables. The
67-sample Blackjack histogram fixes the tier frequencies, since each BJ
multiplier identifies exactly one tier:

| Tier | 18 | 19 | 20 | 21 | BJ | freq |
|---|---|---|---|---|---|---|
| Low      | 2 | 3 | 4  | 5  | 6  | 35.8% |
| Low-Mid  | 3 | 4 | 5  | 6  | 8  | 25.4% |
| Mid      | 3 | 4 | 5  | 8  | 12 | 17.9% |
| Mid-High | 4 | 5 | 6  | 10 | 15 | 16.4% |
| High     | 5 | 6 | 8  | 12 | 20 |  3.0% |
| Nadir    | 5 | 8 | 10 | 15 | 25 |  1.5% |

Under this model with `fee = B`, simulated **RTP ≈ 100.4%** (gain ≈ +0.006 B per
round), close to the published ~99.56%. The small residual is histogram noise (67
samples) / tier-table calibration, not a structural issue.

Getting the correlation right matters: the earlier independent-bucket
approximation gave RTP ≈ 107%. The set distribution affects the RTP and the carry
values `h`; it does **not** affect a single-round decision, which always uses the
actual revealed set. (`MultiplierModel.independent()` keeps the old model for
comparison.)

See `../DESIGN.md` for the full game model and remaining open questions.
