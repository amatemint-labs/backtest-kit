# Port a Pine indicator into the kit

*When to use: translate one of the user's TradingView Pine Script indicators into a kit plug-in, prove it never looks ahead, and prove it matches their chart. Use when the user shares a .pine file or Pine code, asks to add their own indicator/tool, or wants a study to use a new reading.*

The finished product is ONE file, `plugins/indicators/<name>.py`, that passes
`uv run kit check-indicator <name>` and (once the user exports a chart) `uv run kit match-check`.
The worked example to copy from: `plugins/indicators/example_rsi_bands.pine` → `example_rsi_bands.py`.

## 1. Start the file
`uv run kit new-indicator <name> --from-pine <path/to/script.pine>` — copies the Pine next to the
plug-in and writes a template. Read the whole Pine script before writing anything.

## 2. Ask the user only what the code can't tell you (one question at a time)
- Which plots/outputs matter for their trading (you don't need to port colours, tables, labels).
- Which timeframe(s) they use it on, and any inputs they changed from the defaults.
Everything else comes from the code.

## 3. Translate — the mapping
| Pine | Kit (Python) |
|---|---|
| `close`, `high`, `low`, `open`, `volume` | `bars.close` etc. (oldest first, one row per bar) |
| `x[1]`, `x[n]` | `pine.shift(x, n)` — never a negative shift |
| `ta.sma/ema/rma/wma` | `pine.sma/ema/rma/wma` (same warm-up as Pine) |
| `ta.rsi`, `ta.stoch`, `ta.atr`, `ta.tr(true)` | `pine.rsi`, `pine.stoch(close, high, low, n)`, `pine.atr`, `pine.tr` |
| `ta.macd`, `ta.bb`, `ta.stdev`, `ta.vwap` | `pine.macd`, `pine.bb`, `pine.stdev`, `pine.vwap(bars.ts, high, low, close, volume)` |
| `ta.highest/lowest`, `ta.change`, `ta.roc`, `math.sum` | `pine.highest/lowest`, `pine.change`, `pine.roc`, `pine.rolling_sum` |
| `ta.crossover/crossunder`, `ta.rising/falling` | `pine.crossover/crossunder`, `pine.rising/falling` |
| `ta.barssince`, `ta.valuewhen` | `pine.barssince`, `pine.valuewhen` |
| `ta.pivothigh/pivotlow(src, L, R)` | `pine.pivothigh/pivotlow` — value appears R bars AFTER the pivot (as in Pine). Never move it back to the pivot bar: that is lookahead |
| `ta.supertrend(f, n)` | `pine.supertrend(high, low, close, f, n)` |
| `hl2`, `hlc3`, `ohlc4` | `pine.hl2(...)`, `pine.hlc3(...)`, `pine.ohlc4(...)` |
| `timeframe.period`, `timeframe.isdaily`, per-TF input tables | `ctx.tf` ("3m", "15m", "1h", "4h", "1D", ...) — put the per-timeframe tables in compute() |
| `request.security(sym, tf, expr)` (default lookahead_off) | `ctx.htf(tf, lambda b: {"v": ...})["v"]` |
| `request.security(..., lookahead=barmerge.lookahead_on)` | `ctx.htf(tf, fn, pine_lookahead_on=True)` — studies still get closed bars; only match-check reproduces TradingView's repaint |
| `request.security(..., expr[1], lookahead=barmerge.lookahead_on)` | `ctx.htf_prev(tf, fn)` |
| `var x = 0` / `x := ...` state that carries bar to bar | a plain loop over bars (wrap with `@numba.njit(cache=True)` if slow) — copy the Pine order of updates exactly |
| `na`, `nz(x)` | `np.nan`, `np.nan_to_num(x)`; comparisons with NaN are False, as in Pine |
| another indicator's output | `requires = ("macd",)` then `ctx.outputs["macd"]["macd_hist"]` |
| `plot(x, "Title")` | an output column + `tv_columns = {"col": ["Title"]}` |
| `alertcondition`, `plotshape` conditions | boolean output columns (signals can use them as `raw1h_<col>`) |
If a Pine built-in is missing from `kit.ind.pine`, add it there with a hand-checked test in
`tests/test_pine_more.py` (write the arithmetic in a comment), not inline in the plug-in.

## 4. Readings (what studies learn from)
In `readings()`, return the numbers and named states a trader would read off the chart: the value,
its change over 2–3 bars, distance to a level, and a STATE (e.g. zone + rising/falling via
`self.zones(...)`, `self.direction(...)`, `self.combine(...)`). Names must be unique across
indicators; states end in `STATE`.

## 5. Prove it — both halves, in this order
1. `uv run kit check-indicator <name>` — every line PASS. A lookahead FAIL means the code reads the
   future: look for negative shifts, centred windows, pivots used at the pivot bar, or a higher
   timeframe not going through `ctx.htf`.
2. `uv run kit match-check <export.csv> --indicator <name>` on the user's TradingView export (same
   timeframe, extended hours off). 98%+ of bars within tolerance = MATCH. If not, follow the
   check-indicator-match steps; record what you found in the plug-in's "Port notes".
3. Only then add it to a study: `indicators = ["stoch", "rsi", "macd", "<name>"]` in study.toml.

If the script is a commercial or licensed indicator, put the plug-in in a private folder listed under
`plugin_dirs` in `kit.toml` (outside the repository), never in `plugins/`.

## 6. Tell the user, in plain words
What was ported, what was left out (display-only parts), the check results, the match table, and
anything you had to decide (e.g. "Pine seeds this EMA differently in the first 50 bars").
Source every number: `[run: uv run kit check-indicator <name> --json]`.
