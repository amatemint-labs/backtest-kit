# Outputs

A study writes `studies/<name>/report.html` and `studies/<name>/results/`. A complete example on
synthetic data is in [`examples/sample-study/`](../examples/sample-study/).

## The report

| Section | Contents |
|---|---|
| Header | Indicators and versions, halves (dates, months), holdout state, number of lift cells tested |
| Base rates | How often each label is true on an ordinary bar, per half |
| Scorecard (per label) | Held-out AUC; by grade: bars, fires per month, hit rate, lift, option results under the momentum trail (median multiple, % doubled, % 4x, % lost half) and % that broke first; lift by decile; readings that raise / lower the odds in both halves; group-removal importance; same-day labels add grades A+B by time of day |
| Look-alikes | Strengtheners and eliminators inside grades A–C, per half |
| Winner census | Legs per size and side; 1x / 3x / 5x / 10x counts by horizon; the biggest legs |
| Lift tables | States and combinations that raise or lower the odds in both halves |
| Your signals | Definitions; entries, per month, rate and lift for 1x / 3x, went-our-way-first, per half |
| Exhaustion | In-leg bars, "spent" base rate, held-out AUC, lift by decile, readings that say "spent" |
| Trade check | Pre-registration; entries vs all bars × exit rules × halves; distribution chart; tail concentration; by month; by ticker; best and worst 10; first 40 trades |
| Checklist | What to verify before believing a result |

## `results/trades.csv`

One row per trade per exit rule.

| Column | Meaning |
|---|---|
| `ticker`, `half` | Ticker; P1 or P2 |
| `side`, `entries`, `exit_rule` | call / put; which entries (grades or signal); momentum trail or trail + exhaustion |
| `entry_time`, `entry_price` | 1h bar close (New York time) and the underlying price |
| `strike`, `expiry`, `premium` | ATM strike, option expiry (fixed at entry), modelled premium per share |
| `exit_time`, `exit_price` | When and where the underlying exit happened |
| `exit_reason` | momentum trail · exhaustion · option expiry · data ended (censored) |
| `option_value_at_exit`, `multiple`, `return_pct` | Modelled option value, value ÷ premium, and % return |
| `hold_bars` | 1h bars held |
| `grade` | The bar's scorecard grade for the study's label (A–D) |

## `results/summary.json`

Every table in the report, machine-readable. `uv run kit report <name> --json` returns the headline
numbers; Claude Code reads both.

## Other files

| File | Contents |
|---|---|
| `results/bars.parquet` | Every 1h bar: readings, raw indicator outputs, labels, held-out scores and grades, signal entries |
| `results/legs.parquet` | Every census leg with its option pricing |
| `results/prereg_fingerprint.txt` | Fingerprint of the prereg used by the first trade-check run |
| `holdout_log.md` | When the sealed holdout was opened |
