# Run a study

*When to use: run a backtest study with the kit — create it, write the pre-registration with the user, run it, and summarise the results honestly. Use when the user asks to test an idea, run a study, check a setup, or "see if X works".*

1. **Check the ground.** `uv run kit doctor --json`. If there are no 1h bars, stop and say what
   is missing (usually `kit fetch`). Don't fetch without asking — it can take a while.

2. **Create it** (skip if it exists): `uv run kit study new <short-name> --json`.

3. **Write the pre-registration WITH the user, before any result exists.** Open
   `studies/<name>/prereg.md` and fill the five lines in their words:
   - `idea:` one sentence — what they think is true
   - `entry:` one line — e.g. "buy the ATM call at the 1h close when the C_1x grade is A or B"
     (futures/crypto: "buy ES at the 1h close when the C_2atr grade is A or B")
   - `exit:` one line — momentum trail 0.75 or 1.5 day-ATR (± exhaustion), never a fixed hold/target unless that IS the question
   - `measure:` what will be compared (graded entries vs all bars, each half)
   - `pass_mark:` the bar it must clear in BOTH halves
   Then the settings block: `label`, `grades`, `trail_k` (0.75 or 1.5), `exhaustion`, `min_premium`
   (options only) — or `signal: <name>` to trade one of the study's signals instead of the scorecard grades.
   Labels depend on how the study trades: options use `C_1x`, `C_3x`, `P_1x`, `P_3x`; the instrument
   itself (futures, crypto, or shares) uses `C_2atr`, `C_4atr`, `P_2atr`, `P_4atr`. C = calls or long, P = puts or short.
   Read it back and get a yes. Do not edit above "## Verdict" after the run.

4. **Settings in `study.toml`** — confirm with the user: tickers (empty = all fetched), `split`
   (P1/P2 boundary), `holdout_start` (seal the most recent months for a final test),
   `mode` ("closed" default; "forming" = as seen live). Never "tv".
   `trade_as`: "auto" (options when every ticker is a stock, otherwise the instrument itself),
   "options" (stocks only), or "underlying". The study log names each ticker's asset class (recorded by
   `kit fetch` in `data/meta/`); if one is wrong, re-fetch it with `--asset stock|future|crypto`.
   `indicators` (add the user's plug-ins by name; `uv run kit indicators` lists them — each must pass
   `kit check-indicator` first), `[signals.*]` expressions and `use_signals` (see [add-signal.md](add-signal.md)).

5. **Run**: `uv run kit study run <name> --json` (progress goes to stderr). Large universes take minutes.

6. **Report back** using [explain-report.md](explain-report.md). The trade log is `studies/<name>/results/trades.csv`
   (one row per trade: entry/exit time and price, exit reason, and either expiry, premium and option multiple, or
   points, return, move in ATR and dollars per contract). Lead with: did it pass the pass mark in BOTH halves?
   Then the caveats that matter: modelled prices or missing costs, censored share, tail concentration, how many
   cells were tested. Source every number: `[file: studies/<name>/results/summary.json]`.

7. **Offer a refute pass** before the user believes it: a separate step whose only job is to break the result.

8. Append the user's verdict under "## Verdict" in `prereg.md` (date + one paragraph), only when they give it.
