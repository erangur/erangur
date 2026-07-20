# Lightning Blackjack — Optimal Strategy Engine

An exact, verifiable solver for Evolution's **Lightning Blackjack (LBJ)**. It
answers the only question that matters: **given your hand, the dealer upcard, the
multiplier you carried in, and the multiplier set revealed this round, what is
the mathematically optimal play?**

It **computes** the optimum with dynamic programming (the model is fully known),
so results are exact and reproducible — not approximated.

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
# Graphical interactive session (tkinter, stdlib — no dependencies). Same
# continuous carry-tracking flow as the wizard, but you click the set, hand,
# upcard, action and dealer result. Trivial and high-conviction decisions are
# auto-played for you, and a Reset/Bust button starts a fresh session anytime.
python -m lbj_solver.cli gui        # or: python -m lbj_solver.gui

# One-time precompute of carry values (cached to data/solution.json)
python -m lbj_solver.cli solve

# Interactive, continuous session. Asks the starting carry ONCE, then each
# round: the revealed set, your hand, the upcard; it suggests the optimal play,
# asks what you actually did and which card came (splits played out hand by
# hand), asks the dealer's result, then carries the earned multiplier straight
# into the next round. Ctrl-D to quit.
python -m lbj_solver.cli wizard

# Optimal play for a concrete situation
python -m lbj_solver.cli query --hand 10,6 --up 10 --carry 3 --tier 12

# Omit ONE of --up/--carry/--tier to sweep it (>=2 of the three required)
python -m lbj_solver.cli query --hand 10,6 --carry 1 --tier 6   # -> up 2-6 STAND, 7-A HIT

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
  correlated sets**, never per bucket, so you pick a set by its **Blackjack
  multiplier** (`6/8/12/15/20/25`) or `min`/`max`/`modal`. There is deliberately
  no way to set an individual bucket. (Or just run `wizard` and pick from a menu.)
- Rule/model overrides on every command: `--fee`, `--peek-ten`,
  `--split-carry {max,min}`, `--exact`, `--nsets N`, `--refresh`.

When you split, the wizard plays hand 1 first, then hand 2 — and hand 2's advice
accounts for hand 1's final total (the carry combines the two hands, so a first
hand that already secured a big multiplier changes the second hand's play).

---

## GUI & auto-play

`python -m lbj_solver.cli gui` opens a tkinter window that runs the same
continuous session as the wizard — pick the revealed set, enter your hand and
the dealer upcard, click your action and the card that came, enter the dealer's
result, and the earned multiplier carries into the next round. A **Reset / Bust**
button drops the carry back to the starting value and begins fresh at any time.

To keep you from clicking through obvious spots, the GUI (and the shared
`session.py` controller) **auto-plays decisions that aren't real choices**. A node
is auto-played when any of:

- it has only one legal action;
- **risk-free** — the solver's pick is *hit* on a hand that cannot bust (a soft
  hand, or a hard total ≤ 11); this covers the "small total, no carry → hit" case;
- **high conviction** — the best action beats the second-best by a margin that,
  divided by the current carry, clears a threshold (default `0.20`). Normalising
  by the carry keeps a genuine "ask" zone at every carry level (a fixed absolute
  margin would collapse to always-auto once the carry is large). This is what
  auto-fires the aggressive chases a big carry makes clearly correct — e.g.
  **doubling a soft 15 vs a 10 under a large carry**.

Auto-play can be toggled off, and the conviction threshold is a live slider —
slide it to `0` to auto-play the solver's top action almost everywhere, or up to
`1` to be asked about nearly everything. Every auto-played move is written to the
history log with the reason, so nothing happens silently.

The set and dealer-upcard inputs are card-style buttons; the player hand can be
typed (`10,6`) or built with the same buttons.

---

## Collecting the multiplier histogram

The real multiplier-set distribution is only approximately known (67 samples).
The GUI can help refine it: tick **Store each round's set** and every revealed
set is logged with a timestamp.

To let many people on many machines pool their observations without git
conflicts, **each running instance writes its own file** under
`data/histograms/`, uniquely named `session_<host>_<timestamp>_<token>.csv`.
Commit and push yours; when others pull, their files just appear alongside —
**Show histogram** pools every file into the *overall* view. So the flow is
simply *play → push → pull → richer distribution*.

**Show histogram** plots two overlaid series as relative frequency per tier:

- **blue — All sessions**: every `data/histograms/*.csv` pooled (the shared,
  ever-growing distribution);
- **red — This session**: only *this* instance's file, restricted to the last
  `N` games (pickable) played within the last 2 hours — so you can see whether
  you're currently running hot or cold versus the pooled baseline.

(The pooled samples are raw material for a future data-driven set distribution;
today they only feed the chart. The legacy single-file `observed_sets.csv` is
still folded into the overall view locally.)

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
| `session.py` | UI-agnostic continuous-session controller + auto-play policy. |
| `gui.py` | Tkinter graphical front end (uses `session.py`). |
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
