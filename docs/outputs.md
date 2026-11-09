# Outputs

A study writes `studies/<name>/report.html` and `studies/<name>/results/`. A complete example on
synthetic data is in [`examples/sample-study/`](../examples/sample-study/) (stocks priced as options), and
one traded on the instruments themselves in [`examples/sample-futures-crypto/`](../examples/sample-futures-crypto/).

## The report

| Section | Contents |
|---|---|
| Header | Indicators and versions, halves (dates, months), holdout state, number of lift cells tested |
| Base rates | How often each label is true on an ordinary bar, per half |
| Scorecard (per label) | Held-out AUC; by grade: bars, fires per month, hit rate, lift, results under the momentum trail (options: median multiple, % doubled, % 4x, % lost half; instruments: median return, win rate, % gained 1 ATR, % lost ½ ATR) and % that broke first; lift by decile; readings that raise / lower the odds in both halves; group-removal importance; same-day labels add grades A+B by time of day |
| Look-alikes | Strengtheners and eliminators inside grades A–C, per half |
| Winner census | Legs per size and side; big winners by horizon (options: 1x / 3x / 5x / 10x; instruments: 1 / 2 / 4 / 8 ATR); the biggest legs |
| Lift tables | States and combinations that raise or lower the odds in both halves |
| Your signals | Definitions; entries, per month, rate and lift for each label tier, went-our-way-first, per half |
| Exhaustion | In-leg bars, "spent" base rate, held-out AUC, lift by decile, readings that say "spent" |
| Trade check | Pre-registration; entries vs all bars × exit rules × halves; distribution chart; tail concentration; by month; by ticker; best and worst 10; first 40 trades |
| Checklist | What to verify before believing a result |

## `results/trades.csv`

One row per trade per exit rule. The columns depend on how the study trades.

| Column | Meaning |
|---|---|
| `ticker`, `half` | Ticker; P1 or P2 |
| `side`, `entries`, `exit_rule` | call / put (or long / short); which entries (grades or signal); momentum trail or trail + exhaustion |
| `entry_time`, `entry_price` | 1h bar close (New York time) and the price |
| `exit_time`, `exit_price` | When and where the exit happened |
| `hold_bars` | 1h bars held |
| `grade` | The bar's scorecard grade for the study's label (A–D) |

Options (`trade_as = "options"`):

| Column | Meaning |
|---|---|
| `strike`, `expiry`, `premium` | ATM strike, option expiry (fixed at entry), modelled premium per share |
| `exit_reason` | momentum trail · exhaustion · option expiry · data ended (censored) |
| `option_value_at_exit`, `multiple`, `return_pct` | Modelled option value, value ÷ premium, and % return |

The instrument itself (`trade_as = "underlying"`; futures, crypto, or shares):

| Column | Meaning |
|---|---|
| `exit_reason` | momentum trail · exhaustion · time limit (5 trading days for the 0.75 trail, 10 for 1.5) · data ended (censored) |
| `points`, `return_pct`, `r_atr` | Move in price units (positive = profit), % return, and the move in daily ATRs |
| `dollars_per_unit` | Points × the contract multiplier: dollars per futures contract, or per share or coin |
| `asset` | stock, future or crypto |

## `results/summary.json`

Every table in the report, machine-readable. `uv run kit report <name> --json` returns the headline
numbers; an AI assistant reads both.

## Other files

| File | Contents |
|---|---|
| `results/bars.parquet` | Every 1h bar: readings, raw indicator outputs, labels, held-out scores and grades, signal entries |
| `results/legs.parquet` | Every census leg, priced as an option or as the instrument |
| `results/prereg_fingerprint.txt` | Fingerprint of the prereg used by the first trade-check run |
| `holdout_log.md` | When the sealed holdout was opened |
