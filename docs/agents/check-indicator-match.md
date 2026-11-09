# Check indicator match

*When to use: prove the kit's Python indicators (bundled or plug-ins) match the user's TradingView charts, using a TradingView "Export chart data" CSV. Use when the user shares an export, asks whether an indicator matches, or before trusting any study on a new indicator or timeframe.*

1. **Find the export.** Usually in `~/Downloads`, named like `BATS_NVDA, 60_xxxxx.csv`. If there
   isn't one: put the indicators on a chart, extended hours OFF, scroll back for history, chart
   menu → Export chart data (TradingView Plus or higher).

2. **See what's inside**: `uv run kit import-tv "<file>" --json` → ticker, timeframe, bars, and the
   plot columns it found. `uv run kit indicators --json` shows which kit indicator declares which
   TradingView plot titles (`tradingview_columns`).

3. **Compare**: `uv run kit match-check "<file>" --json` (all indicators whose declared columns are
   in the export), or `--indicator <name>` for one.
   - If a reading says "not in export", map it: `--map <port_column>="<TV plot title>"`.
   - If the ticker/timeframe guess is wrong: `--ticker NVDA --tf 1h`.

4. **Read the table back**: per output, % of bars within tolerance (default ±0.5; `--tol` to change)
   and the worst differences. MATCH = 98%+ within tolerance.

5. **If CHECK**, diagnose in this order (one change at a time, re-run after each):
   1. Session: for stocks the kit uses regular hours, so re-export with extended hours OFF. Futures use
      the full CME session (18:00–17:00 New York) and crypto the UTC day; if the ticker's asset class was
      guessed wrong, pass `--asset future` or `--asset crypto`.
   2. Warm-up: `warm_source` = "csv" means no fetched history; early-row mismatches are expected →
      fetch the ticker (`kit fetch --tickers X`) and re-run.
   3. EMA seeding: try `--ema-seed first`.
   4. Higher-timeframe reads: do the worst bars cluster at day / week boundaries? Check that the plug-in
      uses the right helper for its `request.security` pattern (see [port-pine-indicator.md](port-pine-indicator.md)).
   5. Different inputs on the chart than in the plug-in.
   Report what you tried and the numbers before and after. Never tune a parameter to force a match
   without saying which Pine line it contradicts.

6. Source every number: `[run: uv run kit match-check "<file>" --json]`.
