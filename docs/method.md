# The method

Backtest Kit follows a **winners-first** method: list every move that paid, describe what the charts
looked like before it, measure how often those same looks appear without a winner following, and
grade only on time the model never saw. Trades are simulated last, priced as options, with exits
that follow momentum.

## Pipeline

| # | Stage | Produces | The rule that keeps it honest |
|---|---|---|---|
| 1 | Bars | 1-minute bars → 3m, 15m, 1h, 4h, 1D (+2D, 1W, 1M) per ticker | Every bar stamped with its **close** time (New York); regular hours only |
| 2 | Indicators | Bundled + plug-in indicators on every timeframe | Higher timeframes only from bars closed by *t* |
| 3 | Census | Every swing leg, priced as an at-the-money option | Expiry chosen by a rule known at entry |
| 4 | Labels | Per 1h bar: does a winning leg start within 0–3 bars? | Labels may look forward; readings may not |
| 5 | Snapshot | Graded readings per timeframe + market + session | As-of joins; higher timeframes strictly before *t* |
| 6 | Lift tables | Rate of winners per state, per half | Shown only if frequent in **both** halves |
| 7 | Scorecard | A weight per graded reading; A/B/C grade per bar | Learn on one half, grade the other, swap |
| 8 | Look-alikes | What separates graded winners from graded breaks | Both halves |
| 9 | Exhaustion | Probability a move is nearly spent | Same cross-fitting |
| 10 | Trade check | Option results for entries vs all bars, two exits | Requires a pre-registration |

## 1. Bars and time

- Intraday bars are regular hours (09:30–16:00 ET), anchored at 09:30 like TradingView for US
  stocks: 1h bars close at 10:30, 11:30, …, 15:30 and 16:00; 4h bars close at 13:30 and 16:00.
- Daily bars are stamped 16:00 of their date; weekly bars with their last day's 16:00.
- A session that has not finished is never stored.

## 2. Indicators and higher timeframes

Each indicator runs on each timeframe's own bars. When an indicator reads a higher timeframe
(through `ctx.htf`), the value placed on a lower bar depends on the **mode**:

| Mode | A 1h bar at 11:30 sees… | Use |
|---|---|---|
| `closed` (default) | the last higher-timeframe bar that had closed (yesterday's daily bar) | studies |
| `forming` | the higher bar as it looked live at that moment, for indicators that support it | studies |
| `tv` | the **finished** higher bar — what TradingView paints on history with `lookahead_on` | `match-check` only |

Studies refuse `tv` mode.

## 3. Census: every swing leg

A leg is found with an ATR zigzag: it ends when price turns *k* × ATR off its best point.
Low → high legs are call trades, high → low legs are put trades. Entry is the close of the turn bar,
exit the close of the next turn bar. It is a hindsight list of what was available — not a rule.

| Leg size | Bars | *k* | Option expiry (fixed at entry) |
|---|---|---|---|
| Day-size | 1h | 0.75 × previous session's daily ATR(14) | first Friday ≥ 3 sessions out |
| Multi-day swing | 1h | 1.5 × daily ATR | first Friday ≥ 8 sessions out |
| Swing / position | 1D | 2 / 4 / 8 × ATR(14) | first Friday ≥ 21 / 42 / 63 sessions out |

If a leg outlives its option, the option is valued at expiry and flagged `outlived_option`.
Horizons: same-day, overnight, 2–5 days, 1–4 weeks, 1–3 months, 3 months+.

**Option pricing (modelled):** Black-Scholes, strike = entry price, IV = max(30%, 1.15 × 20-day
realized volatility of daily closes, known at entry), capped at 300%, r = 4%, no spread.
**Naming:** "1x" = the option gained 1× its cost (+100%, doubled); "3x" = +300%; "5x" = +500%.

## 4. Labels

| Label | Meaning |
|---|---|
| `C_1x`, `P_1x` | A call / put leg (any size) whose option gained ≥ 1x starts within the next 0–3 bars |
| `C_3x`, `P_3x` | Same, ≥ 3x |
| `C_sameday1x`, `P_sameday1x` | A day-size leg that starts within 0–2 bars, ends the same session, and gains ≥ 1x |

## 5. Snapshot readings

For each timeframe (`h1_`, `h4_`, `D_`, `m15_`, `m3_`) and the market ticker (`mktD_`, `mktH1_`):

- every indicator's readings (numbers and named `…_STATE` categories), and
- location: distance from EMA 20 / 50 and SMA 200 in ATR, position in the 20-bar range, 5-bar move in
  ATR, volume vs its 20-bar average.

Plus session readings on the 1h base: gap from the prior close, move from the open, distance to the
prior day's high and low, position in the day's range, bars since the 20-bar high and low, hour, weekday.

**Joins:** higher timeframes (4h, 1D, market 1D) join **strictly before** the 1h bar's close; the
same or lower timeframes (15m, 3m, market 1h) join at or before it.

## 6. Lift tables

Lift = how often a winner starts in a state ÷ how often one starts on any bar, computed **separately
for each half**. States and 2–3-state combinations are shown only if seen at least `min_state_n`
times in each half, ranked by the weaker half. The report states how many cells were tested and how
many would look significant at 5% by luck alone.

## 7. Scorecard

1. Each numeric reading is cut into ~8 bins at the **learning half's** quantiles, plus a "missing"
   bin; each named state is its own bin.
2. An L2-penalised logistic regression fits one weight per bin (an odds multiplier, all else equal).
3. Learn on P1 → score P2; learn on P2 → score P1. Every bar is scored by a model that never saw it.
4. Grade cut-offs from the learning half: **A** = top 1%, **B** = top 5%, **C** = top 15%.

Reported per graded half: AUC; per grade — bars, fires per month, hit rate, lift, and what an ATM
option bought on those bars did under the momentum-trail exits (median multiple, % doubled, % 4x,
% lost half, % that broke first); lift by score decile; the weights that agree in sign and size
in both halves; and a group-removal test (refit without one group of readings — market, daily, 4h,
1h indicators, 1h location, lower timeframes, session levels, volume, time — and measure the AUC lost).

## 8. Look-alikes and eliminators

Inside grades A–C, split bars into "went 0.75 day-ATR our way first" vs "went 0.75 day-ATR against
first". For each reading, compare the win-first rate across its quintiles in each half. Readings
that raise it in both halves are **strengtheners**; readings that lower it in both are **eliminators**.

## 9. Exhaustion

For every bar inside a ≥ 1x leg, the label is "spent" = less than 0.25 day-ATR left to the leg's
best price. The same cross-fitted scorecard learns which readings mark it. A bar's exhaustion flag is
on when its held-out score is in the top 20% of the learning half's in-leg bars.

## 10. Trade check

Requires `prereg.md` with `idea`, `entry`, `exit`, `measure` and `pass_mark` filled in.

- **Entries:** the first bar of each run of grade-A/B bars for a label, or the first bar of each run
  of a signal (`signal:` in the prereg).
- **Exits**, on the same entries:
  - *momentum trail* — exit when price turns *k* × day-ATR off its best point since entry (or at expiry);
  - *trail + exhaustion* — also exit when the exhaustion flag is on and the trade is in profit.
- **Same-day variant** (`same_day: yes`): this week's option, closed by the session's last bar.
- **Baseline:** the same exit on **every** bar. Entries are worth something only if they beat it.
- **Reported per half:** trades, median and mean (capped) multiple, % doubled, % 4x, % lost half,
  median hold, % censored; tail concentration (profit share of the top 3 days and tickers; median
  without the top 3 days); results by month and by ticker; the 10 best and worst trades; and every
  trade in `results/trades.csv`. Entries whose modelled premium is under `min_premium` are dropped.

## Validation discipline

- **Two halves of time.** Everything must hold in both (`split` in `study.toml`).
- **Sealed holdout.** `holdout_start` keeps the final stretch untouched; `--open-holdout` opens it
  and logs the event; opening it twice is flagged.
- **Pre-registration.** Write the idea and its pass mark before running; the kit fingerprints the
  prereg and labels later edits as exploratory.
- **Count your tests.** Scan 600 combinations and about 30 will look like winners at 5% by luck.
- **Compare like with like.** Exit rules are compared on the same entries.
- **Report what is still open.** Censored trades are neither wins nor losses.
- **Last gate: small live size.** A backtest earns a small live test, nothing more.
