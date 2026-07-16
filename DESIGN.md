# Lightning Blackjack — Optimal Strategy Engine (Design)

## Goal

Compute the **exact optimal playing strategy** for Evolution's Lightning Blackjack, and
validate its RTP (published ~99.56% under Lightning-optimal play) via simulation.

Standard basic strategy is **not** optimal here: the multiplier mechanic changes hand EV,
so plays like doubling 12 or splitting 10s can become correct when a large multiplier is in
effect. Finding those deviations is the whole point.

## Approach (why not the old DQN)

The old code learned a strategy with a DQN. That's the wrong tool: the model is fully known
(fixed dealer policy, known card odds, known payouts) and the state space is small and
enumerable. When that's true you **compute** the optimum with dynamic programming — exact,
verifiable, deterministic — rather than approximate it with RL. The old DQN/env is being
discarded; see "Discard / reuse" at the end.

---

## Confirmed game rules

- **Decks:** modeled as **infinite deck** (real game is 8-deck; we do not track cards out, so
  the only difference is the within-hand removal effect — negligible. Draws are iid.).
- **Dealer:** stands on **all 17s** (including soft 17).
- **Blackjack base pay:** 3:2 — but see multiplier interaction below.
- **Doubling:** allowed on **any** two-card total (no restriction). Draws exactly one card.
  Adds a second bet equal to B.
- **Splitting:** **one split only**, no re-split. **Split Aces get one card each.**
  **No double after split.**
- **Dealer peek:** peeks for blackjack on an **Ace upcard only**. On a **10/face upcard it
  does NOT peek** — you play the full hand (incl. double/split) and may lose that extra money
  to a dealer natural in hindsight.
- **Surrender:** none.
- **Insurance:** offered, but a separate side bet; **irrelevant to strategy** — ignore.
- **Six Card Charlie:** does **not** apply.

---

## The multiplier & carry mechanic (the core)

**Per round**, after the bet is placed and before cards are dealt, the game randomly draws a
**set of multipliers** — one per winning-total bucket — and **reveals it before you act**.
Multipliers are pure random (nothing to do with streaks). Observed per-bucket ranges
(Wizard of Odds):

| Winning total | Possible multipliers |
|---|---|
| 17 or less | 2 |
| 18 | 2, 3, 4 |
| 19 | 3, 4, 5, 6 |
| 20 | 4, 5, 6, 8 |
| 21 | 5, 6, 8, 10, 12 |
| Blackjack | 6, 8, 12, 15, 20, 25 |

**The multiplier is not paid on the hand that earns it — it carries forward.** When you win,
the multiplier for your **final hand value** (from this round's revealed set) attaches to your
bet amount B and applies to your **next** bet. The **current** hand's win instead pays at the
multiplier you **carried in** from your previous win (call it `M_in`).

- `M_in = 1` when you have no carry (first hand, or the previous round was a loss/push).
- A **base win** (`M_in = 1`) returns 2B for a 2B cost → **nets zero**.
- **Both a loss and a push kill the carried multiplier.**

**Carry sizing (deterministic — not a strategy variable):** you always bet **at least B** so the
full carried multiplier is used. Any excess above B is an ordinary bet at standard RTP
(no carried multiplier on the excess), so it's EV-neutral and irrelevant to decisions.
(Sub-B bets waste part of the carry; larger bets split into "B at `M_in`" + "excess at 1×".
This matters only for a faithful simulator.)

---

## Payout / reward model

Per hand, bet unit **B**, fee **B** (the **Lightning Fee is never returned and does not scale**
with double/split). `M_in` = carried-in multiplier.

| Outcome | Net result | Carry forward |
|---|---|---|
| Win | `+(M_in − 1)·B` (return `(M_in+1)·B`) | multiplier = `S[final total]` |
| Blackjack win, `M_in = 1` | `+0.5·B` (3:2 applies) | `S[BJ]` |
| Blackjack win, `M_in > 1` | `+(M_in − 1)·B` — **only the multiplier, no 1.5×** | `S[BJ]` |
| Push | `−B` (fee lost) | killed |
| Loss | `−2B` | killed |
| Double win | `+(M_in − 1)·2B` (return `(M_in+1)·2B`; 3B at risk) | `S[final total]` |
| Split | two independent hands, each pays `(M_in+1)·B` on win (3B at risk: 2 bets + 1 fee) | see open items |

`S[·]` = this round's revealed multiplier for the given final total.

---

## Key insight for the engine

Because the multiplier set is **revealed before you act**, the **optimal per-hand decision does
not need the multiplier distribution at all** — it is computed from the *actual revealed values*
(`M_in` and the set `S`) that round. The distribution is only needed for:
1. computing the overall **RTP** (averaging over all possible revealed sets), and
2. the **carry continuation value** (see refinements).

**Distribution status:** Evolution does not publish per-multiplier probabilities. The best
public data (Wizard of Odds) is a 19-hand sample; our own `lbj_env/multipliers_histogram.txt`
is 67 samples — the best estimate available. Use it. The published 99.56% RTP is an independent
constraint to sanity-check against.

---

## Proposed architecture

1. **Dealer distribution (precompute, once per upcard).** Under stand-on-soft-17 + infinite
   deck, compute the exact probability of each dealer final outcome {17,18,19,20,21,bust},
   plus natural-BJ handling per the peek rule (Ace peek; no peek on 10).

2. **Exact player EV via recursion + memoization.** For a state
   `(hand, dealer_upcard, M_in, revealed_set S)` compute `EV(stand/hit/double/split)` exactly
   and take the max → optimal action + EV.
   - **Stand:** win/push/loss probabilities from the dealer distribution; payoff from the table
     above, including carry-forward value.
   - **Hit:** expectation over the next card (iid infinite-deck odds), recursing.
   - **Double:** one card, forced stand, doubled stake.
   - **Split:** two independent single-card hands under the split constraints.

3. **Carry continuation value (refinement).** A win's payoff should include the expected future
   value of the multiplier it lets you carry. That's a scalar `V(M)` per carried multiplier,
   solvable by value iteration over carry states using the empirical distribution.
   **Start by approximating it (e.g. ignore / treat as constant) — it's second-order — then
   refine and measure the impact.**

4. **Strategy output.** Since the revealed set is seen each round, "the strategy" is a decision
   function `f(hand, upcard, M_in, S)`. Emit human-readable tables for canonical scenarios
   (e.g. per `M_in` level and representative sets) plus the solver callable.

5. **Simulator (validation).** Monte-Carlo full rounds under the computed strategy — including
   the carry mechanic — to confirm RTP ≈ 99.56% and cross-check the DP.

---

## Open modeling decisions

- **Carry continuation value:** include exactly, or approximate? (Second-order; decide after a
  first pass measures its size.)
- **Split + carry:** which final total's multiplier carries when you split into two hands (both
  win, one wins, etc.), and how the "capped at B" rule interacts with two bets. **Not confirmed
  — needs a rule check before the simulator is trusted.**
- **Double + carry cap:** carried multiplier is capped at B, but a double stakes 2B — confirm
  how the cap applies. (Simulator-level; does not affect the hit/stand/double decision itself.)
- **Within-round multiplier correlation:** are the per-bucket multipliers in a round's set drawn
  independently or correlated? Unknown. Irrelevant to per-hand decisions (set is revealed);
  affects only RTP simulation fidelity.

---

## Discard / reuse from the old code

**Discard:**
- The entire DQN approach (`dqn_agent.py`, `train.py`, `infer.py`).
- `multipliers.py`'s **6-tier tables** — they overshoot the real per-bucket ranges (e.g. tiers
  pay 18→5, 19→8, 20→10, 21→15, which exceed observed maxima) and encode a correlated-tier
  structure the real game does not appear to use.
- The old env (`lbj.py`, `hands.py`) — buggy (undefined `dealer_hand`, tuple+int split state,
  enum/int comparisons) and models the multiplier as paid-on-the-hand rather than carried.

**Reuse:**
- `lbj_env/multipliers_histogram.txt` — the empirical multiplier distribution (best available).
- `lbj_env/cards.py` — hand-total and soft-hand logic is correct and reusable.
</content>
