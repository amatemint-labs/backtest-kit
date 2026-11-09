# The method

Backtest Kit starts from the moves that paid rather than from a rule. It lists every swing that would
have made money on an option, describes what the charts looked like just before each one, measures
how often those same conditions appeared without a winner following, and grades everything on a
period the model did not learn from. Trades are simulated last, with exits that follow momentum:
stocks as at-the-money options, futures and crypto as the instruments themselves.

## Pipeline

| # | Stage | Produces | Safeguard |
|---|---|---|---|
| 1 | Bars | 1-minute bars → 3m, 15m, 1h, 4h, 1D (+2D, 1W, 1M) per ticker | Every bar stamped with its **close** time (New York); each asset on its own session |
| 2 | Indicators | Bundled + plug-in indicators on every timeframe | Higher timeframes only from bars closed by *t* |
| 3 | Census | Every swing leg, priced as an at-the-money option or measured on the instrument | Expiry chosen by a rule known at entry |
| 4 | Labels | Per 1h bar: does a winning leg start within 0–3 bars? | Labels may look forward; readings may not |
| 5 | Snapshot | Graded readings per timeframe + market + session | As-of joins; higher timeframes strictly before *t* |
| 6 | Lift tables | Rate of winners per state, per half | Shown only if frequent in **both** halves |
| 7 | Scorecard | A weight per graded reading; A/B/C grade per bar | Learn on one half, grade the other, swap |
| 8 | Look-alikes | What separates graded winners from graded breaks | Both halves |
| 9 | Exhaustion | Probability a move is nearly spent | Same cross-fitting |
| 10 | Trade check | Results for entries vs all bars, two exits | Requires a pre-registration |

## 1. Bars and time

Each ticker trades on its asset class's session, and intraday bars are anchored at the session open:

| Asset | Session | 1h bars close at | 4h bars close at | Daily bar stamped |
|---|---|---|---|---|
| Stock / ETF | 09:30–16:00 New York | 10:30, 11:30 … 15:30, 16:00 | 13:30, 16:00 | 16:00 New York |
| CME future | 18:00–17:00 New York; the evening belongs to the next trading day | 19:00, 20:00 … 16:00, 17:00 | 22:00, 02:00, 06:00, 10:00, 14:00, 17:00 | 17:00 New York |
| Crypto | 00:00–24:00 UTC, every day | every hour | every 4 hours from 00:00 UTC | 00:00 UTC |

- Weekly bars are stamped with their last day's close; months likewise.
- A session that has not finished is never stored.
- Annualised volatility uses 252 trading days a year, or 365 for crypto.

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
Low → high legs are call (or long) trades, high → low legs are put (or short) trades. Entry is the close
of the turn bar, exit the close of the next turn bar. It is a hindsight list of what was available —
not a rule.

How a study prices trades is set by `trade_as` in `study.toml`. The default, `auto`, prices stocks as
options and trades everything else (futures, crypto, or any mix) as the instrument itself.
`underlying` also works for stocks, as shares. Options are modelled for US stocks only.

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

**The instrument itself:** a leg's size is its move in daily ATRs (the previous session's ATR(14)), and
the census also records the % return and, for futures, the move in dollars per contract (points ×
multiplier). The daily-leg expiries above do not apply.

## 4. Labels

| Label | Meaning |
|---|---|
| `C_1x`, `P_1x` | A call / put leg (any size) whose option gained ≥ 1x starts within the next 0–3 bars |
| `C_3x`, `P_3x` | Same, ≥ 3x |
| `C_sameday1x`, `P_sameday1x` | A day-size leg that starts within 0–2 bars, ends the same session, and gains ≥ 1x |
| `C_2atr`, `P_2atr` | Traded as the instrument: an up / down leg of at least 2 daily ATRs starts within the next 0–3 bars |
| `C_4atr`, `P_4atr` | Same, ≥ 4 daily ATRs |
| `C_sameday2atr`, `P_sameday2atr` | A day-size leg of ≥ 2 ATRs that starts within 0–2 bars and ends the same session |

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

Reported per graded half: AUC; per grade — bars, fires per month, hit rate, lift, and what a trade
taken on those bars did under the momentum-trail exits (options: median multiple, % doubled, % 4x,
% lost half; the instrument: median return, win rate, % that gained a full ATR, % that lost half of
one; both: % that broke first); lift by score decile; the weights that agree in sign and size
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
  - *momentum trail* — exit when price turns *k* × day-ATR off its best point since entry, or at the
    option's expiry; on the instrument itself, after 5 trading days (k = 0.75) or 10 (k = 1.5);
  - *trail + exhaustion* — also exit when the exhaustion flag is on and the trade is in profit.
- **Same-day variant** (`same_day: yes`): closed by the session's last bar (options: this week's expiry).
- **Baseline:** the same exit on **every** bar. Entries are worth something only if they beat it.
- **Reported per half:** trades; options: median and mean (capped) multiple, % doubled, % 4x, % lost
  half; the instrument: median and mean return, win rate, median move in ATRs, % that gained a full
  ATR, % that lost half of one; both: median hold and % censored. Then tail concentration (profit share
  of the top 3 days and tickers; median without the top 3 days); results by month and by ticker; the
  10 best and worst trades; and every trade in `results/trades.csv`. Option entries whose modelled
  premium is under `min_premium` are dropped.
- **Costs:** none. Options have no spread; trades on the instrument have no commission, slippage,
  futures roll or crypto funding.

## Validation

Every result is reported for both halves of the history (`split` in `study.toml`), and a result
that holds in only one of them should be treated as noise. You can also seal the most recent stretch
of data with `holdout_start`; it stays out of every run until you pass `--open-holdout`, and the kit
logs each time you do.

Write the idea and its pass mark in `prereg.md` before running the trade check. The kit records a
fingerprint of the file, and a result produced after the file was edited is labelled exploratory.

Keep count of how many ideas you test. Out of 600 combinations, about 30 will clear a 5% significance
bar by chance alone, so the lift tables report how many combinations they examined.

Exit rules are always compared on the same entries, and trades that were still open when the data
ended are reported as censored rather than counted as wins or losses. A backtest that survives all of
this has earned a small live test, not a large one.
