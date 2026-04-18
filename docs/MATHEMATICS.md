# Complete Mathematics of the Polymarket Quant Trading Engine

This document covers every mathematical formula, model, and decision rule in the system,
with full derivations, parameter values, and an exhaustive study guide.

---

## Table of Contents

1. [Probability & Market Model](#1-probability--market-model)
2. [NLP Impact Scoring](#2-nlp-impact-scoring)
3. [Temporal Decay](#3-temporal-decay)
4. [Edge Estimation (Price Adjustment)](#4-edge-estimation-price-adjustment)
5. [Expected Value & Slippage](#5-expected-value--slippage)
6. [Position Sizing — Fractional Kelly](#6-position-sizing--fractional-kelly)
7. [Momentum Signal Generation](#7-momentum-signal-generation)
8. [Ensemble Voting (Multi-Strategy Combination)](#8-ensemble-voting-multi-strategy-combination)
9. [Dynamic Allocator with Drawdown Scaling](#9-dynamic-allocator-with-drawdown-scaling)
10. [Slippage Model (Market Impact)](#10-slippage-model-market-impact)
11. [Smart Order Routing](#11-smart-order-routing)
12. [Risk Management Rules](#12-risk-management-rules)
13. [Portfolio Drawdown](#13-portfolio-drawdown)
14. [Calibration — Brier Score & ECE](#14-calibration--brier-score--ece)
15. [Full Signal Flow — End-to-End Equation Chain](#15-full-signal-flow--end-to-end-equation-chain)
16. [What Mathematics to Study](#16-what-mathematics-to-study)

---

## 1. Probability & Market Model

### What a Prediction Market Price Means

A prediction market trades binary contracts. The YES price `p_market` is the
market-implied probability that the event resolves YES.

```
p_market ∈ (0, 1)
```

If `p_market = 0.35`, the crowd believes a 35% chance the event happens.

**Edge definition:** We have edge if our estimate `p_true ≠ p_market`. The raw edge is:

```
edge_raw = |p_true − p_market|
```

If we think `p_true = 0.50` but `p_market = 0.35`, we buy YES with `edge_raw = 0.15`
(we believe the market underprices the event by 15 cents per dollar).

### Boundary Constraints

Prices are bounded away from the extremes to avoid division issues and degenerate bets:

```
p_true = clamp(p_market + adjustment, 0.02, 0.98)
```

Hard boundaries: no trade can push the implied probability below 2% or above 98%.

---

## 2. NLP Impact Scoring

### Composite Impact Formula

Every news headline is scored by a weighted linear combination of five signals:

```
Impact = w₁·R(source) + w₂·|S|·C_s + w₃·E + w₄·N + w₅·V
```

Where:

| Symbol | Meaning | Value |
|--------|---------|-------|
| `R(source)` | Source reliability prior | 0.50–0.88 |
| `S` | Sentiment polarity (VADER compound) | [−1, +1] |
| `C_s` | Sentiment confidence = `|S|` | [0, 1] |
| `E` | Max entity importance across NER labels | [0, 1] |
| `N` | Novelty score (de-duplication signal) | [0, 1] |
| `V` | Velocity score (how fast story is spreading) | [0, 1] |

**Weights:**

```
w = (w₁, w₂, w₃, w₄, w₅) = (0.20, 0.20, 0.20, 0.25, 0.15)
```

Sum of weights = 1.0 (proper convex combination).

Novelty gets the highest individual weight (0.25) because a true novel event has
pricing alpha; already-priced-in news has near-zero alpha regardless of how loud it is.

**Source reliability priors (R):**

```
gnews    → 0.88
gdelt    → 0.85
newsapi  → 0.85
rss      → 0.80
twitter  → 0.65
telegram → 0.60
reddit   → 0.50
```

These are subjective Bayesian priors over each platform's historical signal-to-noise ratio.

**Entity importance weights (E):**

The NER labels are assigned static importance values based on market-moving potential:

```
LAW → 0.90   (legislation, court rulings)
EVENT → 0.85  (discrete named events)
ORG → 0.80    (company announcements)
MONEY → 0.80  (financial figures)
PERSON → 0.75
GPE → 0.70    (geopolitical entities)
PERCENT → 0.70
NORP → 0.65   (nationalities, parties)
PRODUCT → 0.60
FAC, LOC → 0.50
WORK_OF_ART → 0.40
default → 0.30
```

`E = max(importance_i)` — take the single most market-relevant entity.

**Final clamping:**

```
Impact = clamp(Impact, 0.0, 1.0)
```

---

## 3. Temporal Decay

### Exponential Relevance Decay

News becomes less actionable as time passes — the market prices it in within minutes.
We model this with exponential decay:

```
Relevance(t) = Impact · exp(−λ · t_min)
```

Where:
- `t_min` = age of the news article in **minutes**
- `λ = 0.05` per minute (decay constant)

**Half-life:** The time at which relevance drops to 50% of its peak value:

```
t½ = ln(2) / λ = 0.693 / 0.05 ≈ 13.9 minutes
```

So after ~14 minutes, a news item is half as actionable. After ~28 minutes, a quarter.

**Derivation of half-life:**

```
0.5 = exp(−λ · t½)
ln(0.5) = −λ · t½
t½ = −ln(0.5) / λ = ln(2) / λ
```

This is the standard radioactive decay / first-order reaction formula applied to
information decay in efficient markets.

---

## 4. Edge Estimation (Price Adjustment)

### Raw Adjustment Magnitude

The LLM classifier outputs three scores for each signal:
- `materiality` ∈ [0, 1] — how much this news should move the market
- `confidence` ∈ [0, 1] — how certain the direction is
- `novelty_score` ∈ [0, 1] — how un-priced-in this news is

These combine into a raw adjustment magnitude:

```
raw = α·materiality + β·confidence + γ·novelty_score
```

**Parameters (from config):**

```
α = 0.40   (EDGE_ALPHA)
β = 0.30   (EDGE_BETA)
γ = 0.30   (EDGE_GAMMA)
```

This is a weighted dot product. Total weight = 1.0 when materiality = confidence = novelty = 1.

### Asymmetric Boundary Correction (Room)

A market trading at `p_market = 0.90` cannot be pushed much further YES. We scale
the adjustment by the remaining "room" in the direction of the trade:

```
For direction = YES:  room = max(0, 0.95 − p_market)
For direction = NO:   room = max(0, p_market − 0.05)
```

The 0.95 and 0.05 bounds are soft limits — we never push a price above 95% or below 5%.

### Sigmoid-like Dampening

Large `raw` values would produce outsized price moves. We apply a sigmoid-like
transformation that saturates the adjustment:

```
scaled = room · (1 − exp(−2 · raw))
```

This is `room × (1 − e^{−2x})` where `x = raw`.

**Properties:**
- As `raw → 0`: `scaled → 0` (no signal = no adjustment)
- As `raw → ∞`: `scaled → room` (strong signal saturates at room limit)
- The factor 2 in `exp(-2·raw)` controls how quickly saturation occurs

**Derivative (sensitivity):**

```
d(scaled)/d(raw) = room · 2 · exp(−2 · raw)
```

At `raw = 0`: slope = `2·room` (linear for small signals).
At `raw = 1`: slope ≈ `0.27·room` (nearly saturated).

### Hard Cap

Even after saturation, we impose an absolute maximum:

```
scaled = min(scaled, EDGE_MAX_ADJUSTMENT)   where EDGE_MAX_ADJUSTMENT = 0.12
```

No single LLM signal can move our estimate by more than 12 percentage points.
This prevents hallucination-driven overconfidence from producing catastrophic bets.

### Signed Price Adjustment

```
adjustment = sign · scaled

where sign = +1 (YES), −1 (NO)
```

### True Probability Estimate

```
p_true = clamp(p_market + adjustment, 0.02, 0.98)
```

### Complete Formula (compact)

```
raw      = 0.40·materiality + 0.30·confidence + 0.30·novelty
room     = 0.95 − p_market   [YES]  or  p_market − 0.05  [NO]
scaled   = room · (1 − e^{−2·raw}),  capped at 0.12
p_true   = clamp(p_market ± scaled, 0.02, 0.98)
```

---

## 5. Expected Value & Slippage

### Gross Expected Value

For a binary prediction market, buying YES at `p_market` when you believe `p_true`:

```
EV_gross = p_true − p_market        [for YES bet]
EV_gross = p_market − p_true        [for NO bet]
```

This is the expected profit per dollar wagered, assuming the market converges to
your true probability estimate by resolution.

**Mathematical derivation:**

A YES contract pays $1 if YES, $0 if NO.
Cost: `p_market` per contract.
Expected payout: `p_true · 1 + (1 − p_true) · 0 = p_true`
Expected profit per dollar: `p_true − p_market`

### Net Expected Value (after slippage)

```
EV_net = EV_gross − slippage_estimate
```

### Trade Acceptance Gate

A signal is only acted on if all of these hold:

```
EV_net       ≥ EDGE_THRESHOLD         (0.03, i.e. ≥3 cents per dollar)
novelty_score ≥ MIN_NOVELTY            (0.20)
confidence   ≥ MIN_CONFIDENCE          (0.55)
liquidity_score ≥ MIN_LIQUIDITY_SCORE  (0.20)
spread       ≤ MAX_SPREAD_FRACTION     (0.08, i.e. ≤8%)
```

All five conditions must hold simultaneously (logical AND).

---

## 6. Position Sizing — Fractional Kelly

### The Kelly Criterion (Background)

The Kelly criterion maximizes the long-run expected log-growth of a bankroll.
For a binary bet with edge `e` and win probability `p`:

```
f* = p/q − b/a   (original Kelly fraction)
```

Where `q = 1 − p`, `a = payout`, `b = loss`. For a prediction market where
the payout is `1/p_market − 1` per dollar wagered:

```
f* = (p_true − p_market) / (1 − p_market)   [YES bet]
```

Full Kelly is aggressive and leads to large variance. We use **fractional Kelly**:

```
f = SIZING_K · f*   where SIZING_K = 0.25
```

A 25% Kelly multiplier is a standard conservative choice in quantitative finance.

### Simplified Implementation

The system uses a simplified fractional Kelly that avoids needing the full payout ratio:

```
size = min(MAX_BET_USD, SIZING_K · EV · confidence · BANKROLL_USD)
```

Where:
- `SIZING_K = 0.25`
- `EV = EV_net` (edge after slippage)
- `BANKROLL_USD = 1000` (reference bankroll for sizing)
- `MAX_BET_USD = 25` (hard cap per trade)
- Floor: `max(1.0, size)` — minimum $1 trade

**Example:** `EV = 0.08`, `confidence = 0.70`:

```
size = min(25, 0.25 × 0.08 × 0.70 × 1000)
     = min(25, 14.0)
     = $14.00
```

### Why Multiply by Confidence?

Standard Kelly doesn't include a confidence term — it's already embedded in `p_true`.
Here confidence acts as a **shrinkage factor**: signals with lower LLM confidence
produce smaller positions even if their edge estimate is high. This is a form of
Bayesian shrinkage toward zero for uncertain signals.

---

## 7. Momentum Signal Generation

### BTC 5-Minute Return

The momentum signal measures the price return of BTC over the last 5 minutes:

```
r₅ = (P_current − P_{t−5min}) / P_{t−5min}
```

Where:
- `P_current` = latest BTC/USD price from CoinGecko
- `P_{t−5min}` = newest price recorded ≥5 minutes ago (lookback anchor)

This is a **simple arithmetic return** (not log return). For small moves the
difference is negligible: `ln(1 + r) ≈ r` for `|r| < 0.10`.

### Threshold Gate

```
|r₅| ≥ MOMENTUM_THRESHOLD = 0.02  (2%)
```

Only moves of ≥2% in 5 minutes generate a signal.

### Confidence Scaling

Confidence scales linearly from the threshold to a saturation point at 5%:

```
raw_conf = (|r₅| − 0.02) / (0.05 − 0.02)
         = (|r₅| − 0.02) / 0.03

confidence = clamp(raw_conf × 0.85, 0.30, 0.85)
```

| Momentum | raw_conf | Confidence |
|----------|----------|------------|
| 2%       | 0.00     | 0.30 (floor) |
| 3%       | 0.33     | 0.28 → clamped to 0.30 |
| 3.5%     | 0.50     | 0.425 |
| 5%       | 1.00     | 0.85 (ceiling) |
| 8%       | 2.00     | 0.85 (ceiling) |

**Design intent:** A 2% move is borderline. A 5%+ move in 5 minutes is a genuine
macro shock with high confidence.

### Edge Estimate

```
expected_edge = min(|r₅| × 0.40, 0.08)
```

The factor 0.40 is a conservative dampening: we assume only 40% of the BTC
price move translates into edge on correlated prediction markets. Hard cap at 8%.

**Example:** `|r₅| = 0.04` (4% BTC move):

```
expected_edge = min(0.04 × 0.40, 0.08) = min(0.016, 0.08) = 0.016
```

### Direction Rule

```
direction = YES  if r₅ > 0  (BTC rising → bullish correlated markets)
direction = NO   if r₅ < 0  (BTC falling → bearish correlated markets)
```

### Signal TTL (Time-to-Live)

Momentum signals expire after 3 minutes:

```
valid = (t_now − t_signal) ≤ 180 seconds
```

After 180 seconds, the signal is deleted from the buffer on the next read.

---

## 8. Ensemble Voting (Multi-Strategy Combination)

### Weighted Directional Vote

Given a list of `AlphaSignal` objects (one per strategy), we compute a
strategy-weighted vote on direction:

```
YES_score = Σ  w(s) · confidence(s)    [for all s where direction = YES]
NO_score  = Σ  w(s) · confidence(s)    [for all s where direction = NO]
```

**Strategy weights:**

```
w(news)     = 0.60
w(momentum) = 0.40
```

These weights reflect news signals having longer-horizon reliability, while
momentum is higher frequency and noisier.

**Direction decision:**

```
direction = YES    if YES_score > NO_score
direction = NO     if NO_score  > YES_score
direction = max_confidence_signal.direction   [tie-break]
```

The tie-break selects the strategy whose signal has the highest individual confidence.

### Weighted Average Confidence & Edge

Only the winning-direction signals contribute:

```
w_conf = Σ w(s)·confidence(s) / Σ w(s)     [over winning-direction signals]
w_edge = Σ w(s)·expected_edge(s) / Σ w(s)  [over winning-direction signals]
```

This is a **weighted arithmetic mean** restricted to signals that agree with the
final direction.

### Size Multiplier (Agreement-Based Scaling)

```
multiplier = 1.0   if all strategies agree AND more than one strategy present
           = 0.6   if only one strategy present (single source)
           = 0.4   if strategies disagree (directional conflict)
```

Conflict detection:

```
conflict = len({s.direction for s in deduped}) > 1
```

If news says YES and momentum says NO, we still trade the winning direction but
at only 40% of normal size.

### Deduplication (per strategy)

If multiple signals exist for the same strategy (shouldn't happen but handled),
keep the one with highest confidence:

```
best(strategy) = argmax_{s: s.strategy = strategy} s.confidence
```

---

## 9. Dynamic Allocator with Drawdown Scaling

### Full Sizing Formula

```
base        = K · edge · confidence · B
sized       = base · multiplier
dd_scalar   = max(0, 1 − drawdown × 2)
dd_scaled   = sized · dd_scalar
final       = clamp(dd_scaled, 1.0, MAX_BET)
```

Where:
- `K = SIZING_K = 0.25`
- `B = BANKROLL_USD = 1000`
- `edge = AggregatedSignal.expected_edge`
- `confidence = AggregatedSignal.confidence`
- `multiplier = AggregatedSignal.size_multiplier ∈ {0.4, 0.6, 1.0}`
- `drawdown ∈ [0, 1]` — current portfolio max drawdown fraction
- `MAX_BET = 25`

### Drawdown Scalar Analysis

```
dd_scalar(d) = max(0, 1 − 2d)
```

| Drawdown | dd_scalar | Effect |
|----------|-----------|--------|
| 0%       | 1.00      | Full size |
| 10%      | 0.80      | 20% reduction |
| 25%      | 0.50      | Half size |
| 50%      | 0.00      | Zero (but $1 floor applies) |
| 75%      | 0.00      | Zero (but $1 floor applies) |

This is a **linear interpolation** from 1.0 (no drawdown) to 0.0 (50% drawdown).
The system never fully stops trading due to the `max(1.0, ...)` floor.

**Why linear drawdown scaling?**

Linear is the simplest adaptive position sizing that:
1. Preserves capital proportionally during losing streaks
2. Automatically recovers position sizes as drawdown recovers
3. Never goes fully to zero (maintains market presence)

More sophisticated alternatives include convex scaling (`(1−d)²`) or exponential
(`exp(−k·d)`), but linear is interpretable and sufficient here.

### Worked Example

```
edge = 0.06, confidence = 0.72, multiplier = 0.6, drawdown = 0.15

base      = 0.25 × 0.06 × 0.72 × 1000  = 10.80
sized     = 10.80 × 0.6                 = 6.48
dd_scalar = max(0, 1 − 0.15 × 2)       = 0.70
dd_scaled = 6.48 × 0.70                = 4.54
final     = clamp(4.54, 1.0, 25.0)     = $4.54
```

---

## 10. Slippage Model (Market Impact)

### Linear Market Impact Formula

```
slippage = (order_size / book_depth_usd) × spread
```

Where:
- `order_size` — our trade size in USD
- `book_depth_usd` — USD available on the relevant order book side
- `spread` — bid-ask spread as a fraction of mid price

**Range:** `clamp(slippage, 0.0, 0.20)` — never estimate >20% slippage.

### Derivation Intuition

This is a simplified **linear price impact model**. It says: if our order consumes
`order_size / book_depth_usd` fraction of available liquidity, we pay a proportional
fraction of the spread as extra cost.

**Example:**
- Order size: $20
- Book depth: $500
- Spread: 4% (0.04)

```
slippage = (20/500) × 0.04 = 0.04 × 0.04 = 0.0016 = 0.16%
```

Our order is tiny relative to the book, so slippage is negligible.

**Example (thin market):**
- Order size: $20
- Book depth: $50
- Spread: 6%

```
slippage = (20/50) × 0.06 = 0.40 × 0.06 = 0.024 = 2.4%
```

This would likely cause the trade to be rejected since EV_net = EV_gross − 2.4%
would fall below the 3% threshold for most signals.

### Relationship to EV

The slippage model feeds directly into the edge calculation:

```
EV_net = EV_gross − slippage
EV_net ≥ 0.03  required to trade
```

---

## 11. Smart Order Routing

### Routing Decision Rules

The smart router selects execution aggressiveness based on two inputs:
- `spread` — bid-ask spread fraction
- `momentum` — BTC 5-minute return (proxy for market urgency)

```
if spread > 0.08:
    strategy = "reject"        (spread too wide, don't trade)
elif |momentum| > 0.03:
    strategy = "aggressive"    (momentum urgency overrides spread)
elif spread < 0.02:
    strategy = "aggressive"    (tight spread, safe to take liquidity)
else:
    strategy = "passive"       (post limit orders, 2–8% spread)
```

This is a **decision tree** (not a statistical model). The thresholds are:

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Reject    | spread > 8% | Cost exceeds any realistic edge |
| Aggressive| spread < 2% | Cheap to take; costs negligible |
| Aggressive| \|momentum\| > 3% | Race condition: must act fast |
| Passive   | 2–8% spread | Post limit, improve on mid |

**Why 8% reject threshold?**

Given `EDGE_THRESHOLD = 3%`, and typical EV is 3–12%, a spread of 8% would
consume most or all of the edge via slippage. The router rejects early to avoid
wasted LLM classification effort.

---

## 12. Risk Management Rules

### Rule 1: Daily Loss Cap (Hard Stop)

```
|min(0, daily_PnL)| < DAILY_LOSS_LIMIT_USD = $100
```

If cumulative realized losses today exceed $100, all trading halts. This is a
**value-at-risk style hard stop** — not probabilistic, just a hard dollar limit.

### Rule 2: Max Concurrent Positions

```
|open_positions| < MAX_CONCURRENT_POSITIONS = 5
```

Never hold more than 5 open positions simultaneously. This limits correlated
drawdown if many positions move against us at once.

### Rule 3: Per-Category Exposure

```
category_exposure[cat] + new_bet ≤ MAX_EXPOSURE_PER_CATEGORY_USD = $60
```

Total USD at risk in any single category (politics, crypto, macro, etc.) capped
at $60. This limits **concentration risk** — the portfolio cannot be dominated
by a single theme.

**Example:** If we have $45 in crypto positions, the next crypto trade must be
≤$15 to stay under the cap.

### Rule 4: Consecutive Loss Cooldown

After `CONSECUTIVE_LOSS_COOLDOWN = 3` consecutive losing trades:

```
cooldown_until = t_now + COOLDOWN_MINUTES × 60
             = t_now + 30 × 60  (30 minutes)
```

No trades are executed during this window. The consecutive loss counter resets
on any winning trade:

```
consecutive_losses = 0   if pnl ≥ 0
consecutive_losses += 1  if pnl < 0
```

**Mathematical motivation:** Consecutive losses are a signal that the model's
assumptions may be temporarily invalid (regime change, data quality issue, etc.).
The cooldown is a **stopping rule** to prevent runaway losses.

### Rule 5: Per-Market 10-Minute Cooldown

```
time_since_last_signal(market_id) ≥ 600 seconds
```

The same market cannot generate a signal more than once per 10 minutes.
This prevents duplicate signals from the same news story being amplified
by the feed into multiple trades on the same market.

---

## 13. Portfolio Drawdown

### Max Drawdown Calculation

Max drawdown measures the peak-to-trough decline in portfolio value:

```
max_drawdown = max over all t: (peak_value(t) − current_value(t)) / peak_value(t)
```

Where `peak_value(t) = max_{s ≤ t} portfolio_value(s)`.

**As a fraction:** `max_drawdown ∈ [0, 1]`.

### Running Maximum

In code, this is maintained as a running maximum:

```
peak = max(peak, current_value)
drawdown = (peak − current_value) / peak
max_drawdown_ever = max(max_drawdown_ever, drawdown)
```

### Safety Guard Threshold

```
live_trading_allowed = max_drawdown ≤ 0.20
```

If the portfolio has ever lost more than 20% from its peak, switching to LIVE
mode is blocked. This protects against enabling real-money trading on a
poorly-performing strategy.

---

## 14. Calibration — Brier Score & ECE

### Brier Score (Proper Scoring Rule)

The Brier score measures the mean squared error of probability forecasts:

```
BS = (1/N) Σᵢ (p̂ᵢ − oᵢ)²
```

Where:
- `p̂ᵢ` = predicted probability of YES for trade `i`
- `oᵢ ∈ {0, 1}` = actual outcome (1 = YES resolved, 0 = NO resolved)
- `N` = number of resolved trades

**Range:** `BS ∈ [0, 1]`. Lower is better.
- Perfect calibration + perfect accuracy: BS = 0
- Random (always predict 0.5): BS = 0.25
- Perfectly wrong: BS = 1.0

**Why Brier score?** It is a **proper scoring rule**: a forecaster maximizes their
expected score only by reporting their true beliefs. It cannot be gamed by
always predicting 0.5 or 1.0.

### Expected Calibration Error (ECE)

ECE measures whether predicted probabilities match empirical frequencies.
We bin predictions into confidence buckets `B_k = [k/10, (k+1)/10)` for `k ∈ {5,6,7,8,9}`:

```
ECE = Σₖ (|Bₖ| / N) · |acc(Bₖ) − conf(Bₖ)|
```

Where:
- `|Bₖ|` = number of predictions falling in bucket k
- `acc(Bₖ)` = fraction correct in bucket k (empirical accuracy)
- `conf(Bₖ)` = mean predicted confidence in bucket k

**Interpretation:** A perfectly calibrated model has ECE = 0. A model that
predicts 70% confidence but is only right 55% of the time is overconfident;
its ECE contribution from that bucket = `(n_k/N) × |0.55 − 0.70|`.

### Calibration Error per Bucket

```
calibration_error(k) = conf(Bₖ) − acc(Bₖ)
```

Positive = **overconfident** (predicts higher probability than achieved accuracy).
Negative = **underconfident** (predictions are conservative).

### Performance Thresholds

```
accuracy ≥ 0.65 → "Strong edge" — consider size increase
accuracy ≥ 0.55 → "Moderate edge" — hold current sizing
accuracy ≥ 0.48 → "Weak edge" — review model
accuracy < 0.48 → "Negative edge" — PAUSE live trading
```

The 55% threshold corresponds to a minimum Brier skill score above a random baseline.

---

## 15. Full Signal Flow — End-to-End Equation Chain

Here is the complete mathematical chain from raw news to trade size:

```
Step 1: NLP Enrichment
  Impact = 0.20·R + 0.20·|S|·C_s + 0.20·E + 0.25·N + 0.15·V
  Relevance = Impact · exp(−0.05 · t_min)

Step 2: LLM Classification
  confidence ∈ [0, 1],  materiality ∈ [0, 1],  novelty_score ∈ [0, 1]
  direction ∈ {YES, NO, NEUTRAL}

Step 3: Edge Estimation
  raw      = 0.40·materiality + 0.30·confidence + 0.30·novelty_score
  room     = 0.95 − p_market   [YES]  or  p_market − 0.05  [NO]
  adj      = sign · min(room · (1 − e^{−2·raw}), 0.12)
  p_true   = clamp(p_market + adj, 0.02, 0.98)
  EV_gross = |p_true − p_market|

Step 4: Slippage
  slippage = clamp((size / depth) · spread, 0, 0.20)
  EV_net   = EV_gross − slippage

Step 5: Gate Check (all must pass)
  EV_net ≥ 0.03
  novelty_score ≥ 0.20
  confidence ≥ 0.55
  liquidity_score ≥ 0.20
  spread ≤ 0.08

Step 6: News Alpha Signal
  AlphaSignal(direction, confidence, expected_edge = EV_net, strategy = "news")

Step 7: Momentum Alpha Signal (concurrent, BTC)
  r₅       = (P_now − P_{t-5min}) / P_{t-5min}
  conf_mom = clamp((|r₅| − 0.02) / 0.03 × 0.85, 0.30, 0.85)   [if |r₅| ≥ 0.02]
  edge_mom = min(|r₅| × 0.40, 0.08)

Step 8: Ensemble Combination
  YES_score = Σ w(s)·conf(s)  [YES signals]   w(news)=0.6, w(mom)=0.4
  NO_score  = Σ w(s)·conf(s)  [NO signals]
  direction = argmax(YES_score, NO_score)
  w_conf    = weighted mean confidence [winning direction]
  w_edge    = weighted mean edge       [winning direction]
  multiplier ∈ {1.0 (agree), 0.6 (single), 0.4 (conflict)}

Step 9: Dynamic Allocation
  base      = 0.25 · w_edge · w_conf · 1000
  sized     = base · multiplier
  dd_scalar = max(0, 1 − 2·drawdown)
  final     = clamp(sized · dd_scalar, 1.0, 25.0)

Step 10: Routing
  strategy ∈ {aggressive, passive, reject}   based on spread and momentum

Step 11: Risk Gates (all must pass)
  daily_loss < $100
  open_positions < 5
  category_exposure + final ≤ $60
  not in cooldown
  market cooldown ≥ 10 minutes
```

---

## 16. What Mathematics to Study

The system draws from seven mathematical domains. Below is a structured study
guide from foundations to advanced topics, with the specific concepts each domain
covers in this system.

---

### Domain 1: Probability Theory (Essential)

**What it powers:** Everything. `p_market`, `p_true`, EV, Kelly, calibration.

**Study path:**

1. **Fundamentals**
   - Sample spaces, events, axioms of probability (Kolmogorov)
   - Conditional probability: `P(A|B) = P(A∩B) / P(B)`
   - Bayes' theorem: `P(H|E) = P(E|H)·P(H) / P(E)`
   - Law of total expectation

2. **Random Variables**
   - Discrete and continuous distributions
   - Bernoulli distribution: `X ~ Bern(p)` — the model for a binary market
   - Expected value: `E[X] = Σ x·P(X=x)`
   - Variance and standard deviation

3. **Information & Entropy**
   - Shannon entropy: `H(p) = −p·log(p) − (1−p)·log(1−p)`
   - Kullback-Leibler divergence: `DKL(P||Q) = Σ P(x)·log(P(x)/Q(x))`
   - This underpins why proper scoring rules (Brier, log-loss) work

4. **Bayesian Statistics**
   - Prior, likelihood, posterior
   - Beta distribution (conjugate prior for Bernoulli)
   - Bayesian updating: how source reliability priors work

**Books:**
- *Introduction to Probability* — Bertsekas & Tsitsiklis (free PDF)
- *Thinking in Bets* — Annie Duke (intuition)
- *Probability Theory: The Logic of Science* — E.T. Jaynes (advanced)

---

### Domain 2: Information Theory (Important)

**What it powers:** Novelty scoring, proper scoring rules, entropy-based signal detection.

1. **Proper Scoring Rules**
   - Brier score, log-loss (cross-entropy), spherical score
   - Proof that proper scoring rules incentivize honest reporting
   - Skill score: `SS = 1 − BS/BS_ref`

2. **KL Divergence & Information Gain**
   - `IG(market) = DKL(p_true || p_market)`
   - When `p_true = p_market`, information gain = 0 → no edge

3. **Entropy of a Prediction Market**
   - A market at `p = 0.5` has maximum entropy (most uncertain)
   - A market at `p = 0.05` is nearly resolved — small moves have large log-odds impact

**Books:**
- *Elements of Information Theory* — Cover & Thomas
- *Information Theory, Inference, and Learning Algorithms* — MacKay (free)

---

### Domain 3: Financial Mathematics (Core)

**What it powers:** Kelly criterion, EV, position sizing, drawdown.

1. **Expected Value & Arbitrage**
   - Law of one price
   - Risk-neutral pricing
   - No-arbitrage conditions in prediction markets

2. **Kelly Criterion**
   - Derivation: maximize `E[log(wealth)]` subject to fractional betting
   - Full Kelly formula: `f* = p/q − 1/(R−1)` where R is odds
   - Fractional Kelly (quarter Kelly = this system)
   - Overbetting and the ruin problem
   - **Proof of optimality:** Kelly maximizes long-run geometric growth rate

3. **Drawdown Mathematics**
   - Maximum drawdown definition and running calculation
   - Expected maximum drawdown for random walk: `E[MDD] ≈ σ√(2T·ln(T))`
   - Calmar ratio: `CAGR / max_drawdown`

4. **Sharpe Ratio**
   - `Sharpe = (R_portfolio − R_risk_free) / σ_portfolio`
   - Annualization: multiply by `√252` (trading days) or `√(periods/year)`

5. **Market Microstructure**
   - Bid-ask spread mechanics
   - Adverse selection: why market makers quote a spread
   - Effective spread vs quoted spread
   - Price impact models (linear, square-root, logarithmic)

**Books:**
- *Fortune's Formula* — Poundstone (Kelly story, intuition)
- *Options, Futures, and Other Derivatives* — Hull (market microstructure chapter)
- *Quantitative Trading* — Ernest Chan
- *Algorithmic Trading* — Weissman

---

### Domain 4: Calculus & Analysis (Required for Derivations)

**What it powers:** Sigmoid dampening, exponential decay, gradient of loss functions.

1. **Differential Calculus**
   - Derivatives and chain rule
   - `d/dx [e^{-ax}] = -a·e^{-ax}`
   - `d/dx [1 - e^{-ax}] = a·e^{-ax}` — used in the adjustment formula
   - Concavity and saturation behavior of the adjustment function

2. **Exponential & Logarithmic Functions**
   - `exp(x) = eˣ` and its properties
   - Half-life formula: `t½ = ln(2)/λ` — temporal decay
   - Log-sum-exp for numerical stability

3. **Optimization**
   - Unconstrained optimization (Kelly criterion derivation)
   - Constrained optimization (position sizing with caps)
   - Lagrange multipliers (portfolio optimization)

4. **Numerical Analysis**
   - Floating-point precision
   - Numerical stability of `1 - exp(-x)` for small x vs `x` approximation

**Books:**
- *Calculus* — Stewart or Spivak
- *Mathematics for Machine Learning* — Deisenroth (free PDF)

---

### Domain 5: Statistics & Machine Learning (For Calibration & NLP)

**What it powers:** VADER sentiment, calibration curves, ECE, Brier decomposition.

1. **Frequentist Statistics**
   - Confidence intervals, p-values, hypothesis testing
   - Law of large numbers — why calibration requires N ≥ 10 trades

2. **Regression & Prediction**
   - Linear regression (impact score is a linear model)
   - Logistic regression (sigmoid = 1/(1+e^{-x}), related to the price adjustment)
   - Calibration of classifiers (Platt scaling, isotonic regression)

3. **Natural Language Processing (NLP)**
   - Bag of words, TF-IDF
   - VADER: rule-based sentiment using a lexicon + grammatical rules
     (negation, emphasis, emoticons, punctuation)
   - Named Entity Recognition (NER): Conditional Random Fields, spaCy's neural NER
   - Sentence embeddings: word2vec, sentence-transformers (used in market matching)
   - Cosine similarity: `cos(u,v) = u·v / (|u|·|v|)` — how matcher ranks markets

4. **Proper Scoring Rules (revisit)**
   - Brier decomposition: `BS = Uncertainty − Resolution + Reliability`
   - Each component has economic meaning for trading systems

5. **Calibration Plots**
   - Reliability diagrams
   - Expected Calibration Error (ECE) calculation
   - Temperature scaling for post-hoc LLM calibration

**Books:**
- *The Elements of Statistical Learning* — Hastie, Tibshirani, Friedman (free PDF)
- *Speech and Language Processing* — Jurafsky & Martin (free PDF)
- *Probabilistic Machine Learning* — Kevin Murphy (free PDF)

---

### Domain 6: Time Series Analysis (For Momentum)

**What it powers:** 5-minute rolling return, signal TTL, price buffering.

1. **Returns Computation**
   - Arithmetic return: `r_t = (P_t − P_{t-1}) / P_{t-1}`
   - Log return: `r_t = ln(P_t / P_{t-1})`
   - Why log returns are additive: `Σ log returns = total log return`

2. **Rolling Windows**
   - Rolling mean, rolling variance
   - Exponential moving average (EMA) — alternative to fixed window
   - Look-ahead bias (only use data available at decision time — this system does)

3. **Momentum Strategies**
   - Time-series momentum (TSMOM): `sign(r_{t-k,t})`
   - Cross-sectional momentum (not used here, but important in broader finance)
   - Momentum decay: why signals have TTL
   - Mean reversion vs trend continuation

4. **Stationarity**
   - Augmented Dickey-Fuller test
   - Why raw prices are non-stationary but returns are (approximately)
   - Cointegration: relevant for BTC ↔ prediction market relationship

5. **Autocorrelation**
   - ACF, PACF
   - Why consecutive losses trigger cooldowns (autocorrelation in model errors)

**Books:**
- *Time Series Analysis and Its Applications* — Shumway & Stoffer (free PDF)
- *Advances in Financial Machine Learning* — Marcos Lopez de Prado

---

### Domain 7: Combinatorics & Decision Theory (For Routing & Risk Rules)

**What it powers:** Routing rules, risk management conditions, ensemble logic.

1. **Decision Trees**
   - Binary classification of routing decisions
   - Optimal stopping rules (when to reject a signal)

2. **Game Theory (light)**
   - Market makers' optimal spread (Kyle model)
   - Adverse selection in prediction markets
   - Signaling: does our order move the price?

3. **Risk Theory**
   - Ruin probability: `P(ruin) = exp(−2·θ·x)` for Brownian motion
   - Gambler's ruin as discrete analog
   - Why the consecutive loss cooldown is a heuristic stopping rule

4. **Combinatorial Auctions**
   - How CLOB (central limit order book) markets clear
   - Price-time priority in limit order books

**Books:**
- *An Introduction to Decision Theory* — Peterson
- *Market Microstructure Theory* — Maureen O'Hara

---

### Recommended Learning Order

```
Level 0 (Prerequisite): Algebra, basic statistics, logarithms
  ↓
Level 1 (Core): Probability Theory → Expected Value → Kelly Criterion
  ↓
Level 2 (Model-specific): Calculus → Exponential functions → Optimization
  ↓
Level 3 (System-wide): Time Series → NLP basics → Market Microstructure
  ↓
Level 4 (Advanced): Information Theory → Bayesian Statistics → Proper Scoring Rules
  ↓
Level 5 (Expert): Stochastic Processes → Optimal Stopping → Market Design
```

---

### Summary of All Formulas (Quick Reference)

| Formula | Location | Equation |
|---------|----------|----------|
| NLP Impact | `nlp_processor.py` | `0.20R + 0.20\|S\|C + 0.20E + 0.25N + 0.15V` |
| Temporal Decay | `nlp_processor.py` | `Impact · e^{−0.05·t_{min}}` |
| Half-life | derived | `t½ = ln2/0.05 ≈ 13.9 min` |
| Raw Adjustment | `edge_model.py` | `0.40·mat + 0.30·conf + 0.30·nov` |
| Boundary Room | `edge_model.py` | `0.95 − p` (YES) or `p − 0.05` (NO) |
| Sigmoid Dampening | `edge_model.py` | `room·(1 − e^{−2·raw})`, capped 0.12 |
| True Probability | `edge_model.py` | `clamp(p_market ± adj, 0.02, 0.98)` |
| Gross EV | `edge_model.py` | `\|p_true − p_market\|` |
| Net EV | `edge_model.py` | `EV_gross − slippage` |
| Fractional Kelly | `edge_model.py` | `min(25, 0.25·EV·conf·1000)` |
| BTC 5m Return | `momentum_alpha.py` | `(P_now − P_{−5min})/P_{−5min}` |
| Momentum Confidence | `momentum_alpha.py` | `clamp((|r|−0.02)/0.03·0.85, 0.30, 0.85)` |
| Momentum Edge | `momentum_alpha.py` | `min(\|r\|·0.40, 0.08)` |
| Ensemble Vote | `ensemble.py` | `Σ w(s)·conf(s)` per direction |
| Weighted Avg | `ensemble.py` | `Σ w(s)·x(s) / Σ w(s)` |
| Allocator Base | `allocator.py` | `0.25·edge·conf·1000` |
| Drawdown Scalar | `allocator.py` | `max(0, 1 − 2·drawdown)` |
| Final Size | `allocator.py` | `clamp(base·mult·scalar, 1, 25)` |
| Slippage | `slippage_model.py` | `clamp((size/depth)·spread, 0, 0.20)` |
| Brier Score | `calibrator.py` | `(1/N)Σ(p̂ᵢ − oᵢ)²` |
| ECE | `calibrator.py` | `Σ (n_k/N)·\|acc_k − conf_k\|` |
| Max Drawdown | `portfolio/_paper.py` | `(peak − current)/peak` |
