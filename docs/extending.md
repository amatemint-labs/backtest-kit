# Extending: your own indicators and signals

## Indicators

An indicator is one Python file with one class that subclasses `kit.plugin.Indicator`. The kit
discovers files in:

- `plugins/indicators/` in the repository (examples ship here), and
- any folder listed in `kit.toml` as `plugin_dirs = ["~/path/to/my-plugins"]` (or the `KIT_PLUGINS`
  environment variable) — each such folder holds `indicators/` and `signals/`. Use this to keep
  licensed or private indicators in a separate private repository.

```python
from kit.ind import pine
from kit.plugin import Indicator

class MyTool(Indicator):
    name = "my_tool"                      # how studies and commands refer to it
    version = "My Tool v1 (2026-11-08)"    # printed on every report
    requires = ()                         # e.g. ("macd",) → ctx.outputs["macd"]["macd_hist"]
    tv_columns = {"mt_line": ["My Line"]} # output column → TradingView plot title(s)
    sparse = set()                        # outputs that are empty except on event bars

    def compute(self, bars, ctx):
        """bars: this timeframe's OHLCV (column `ts` = close time), oldest first.
        Return {column: array}, one value per bar."""
        n = 21 if ctx.tf == "1D" else 14
        return {"mt_line": pine.ema(bars.close, n)}

    def readings(self, out, bars):
        """What studies learn from: numbers, and named states whose names end in STATE."""
        x = out["mt_line"].to_numpy(float)
        c = bars.close.to_numpy(float)
        return {"mt_dist_pct": 100 * (c - x) / x,
                "MT_STATE": self.combine(self.zones(c - x, [0], ["below", "above"]), self.direction(x, 3))}
```

Helpers on `Indicator`: `zones(x, edges, labels)`, `direction(x, bars_back)`, `combine(*parts)`.

### Workflow

```bash
uv run kit new-indicator my_tool --from-pine ~/Downloads/my_tool.pine   # template + copy of the Pine source
uv run kit check-indicator my_tool                                      # must print SAFE TO STUDY WITH
uv run kit match-check export.csv --indicator my_tool                   # vs your TradingView chart
```

Then add it to a study: `indicators = ["stoch", "rsi", "macd", "my_tool"]`.

### What `check-indicator` proves

| Check | Pass condition |
|---|---|
| runs | computes on 1h, 15m, 4h and 1D, one row per bar |
| no lookahead | at three cut points, outputs at or before the cut are identical when every later price is raised 50%, lowered 40%, or scrambled |
| coverage *(advisory)* | outputs are filled late in the sample (event-only columns go in `sparse`) |
| readings | names are unique; states have a reasonable number of categories |

### Pine → kit mapping

| Pine | Kit |
|---|---|
| `close`, `high`, `low`, `open`, `volume` | `bars.close`, … |
| `x[n]` | `pine.shift(x, n)` (never a negative shift) |
| `ta.sma / ema / rma / wma` | `pine.sma / ema / rma / wma` — same warm-up as Pine |
| `ta.rsi`, `ta.stoch`, `ta.atr`, `ta.tr(true)` | `pine.rsi`, `pine.stoch(close, high, low, n)`, `pine.atr`, `pine.tr` |
| `ta.macd`, `ta.bb`, `ta.stdev`, `ta.vwap` | `pine.macd`, `pine.bb`, `pine.stdev`, `pine.vwap(bars.ts, h, l, c, v)` |
| `ta.highest / lowest`, `ta.change`, `ta.roc`, `math.sum` | `pine.highest / lowest`, `pine.change`, `pine.roc`, `pine.rolling_sum` |
| `ta.crossover / crossunder`, `ta.rising / falling` | `pine.crossover / crossunder`, `pine.rising / falling` |
| `ta.barssince`, `ta.valuewhen` | `pine.barssince`, `pine.valuewhen` |
| `ta.pivothigh / pivotlow(src, L, R)` | `pine.pivothigh / pivotlow` — reported *R* bars after the pivot, as in Pine |
| `ta.supertrend(f, n)` | `pine.supertrend(high, low, close, f, n)` |
| `hl2`, `hlc3`, `ohlc4` | `pine.hl2`, `pine.hlc3`, `pine.ohlc4` |
| `timeframe.period`, per-timeframe settings | `ctx.tf` |
| `request.security(sym, tf, expr)` | `ctx.htf(tf, fn)` |
| `request.security(..., lookahead=barmerge.lookahead_on)` | `ctx.htf(tf, fn, pine_lookahead_on=True)` — studies still see closed bars |
| `request.security(..., expr[1], lookahead=barmerge.lookahead_on)` | `ctx.htf_prev(tf, fn)` |
| `var` state carried bar to bar | a loop over bars (`@numba.njit(cache=True)` if slow), same update order as Pine |
| `na`, `nz(x)` | `np.nan`, `np.nan_to_num(x)`; comparisons with NaN are False, as in Pine |
| `plot(x, "Title")` | an output column + `tv_columns = {"col": ["Title"]}` |
| `alertcondition` / `plotshape` conditions | boolean output columns (signals see them as `raw1h_<col>`) |

A worked example: [`plugins/indicators/example_rsi_bands.pine`](../plugins/indicators/example_rsi_bands.pine)
→ [`example_rsi_bands.py`](../plugins/indicators/example_rsi_bands.py).

## Signals

A signal is an entry rule evaluated on every 1h bar. An **entry** is the first bar of each run of
fires, so a condition true for six bars in a row is one trade.

### In `study.toml` (expressions)

```toml
[signals.stoch_turn_up]
side = "C"                                   # C = calls, P = puts
when = "h1_STOCH_STATE == '<20 rising' and h4_MACD_STATE.str.startswith('bull')"
note = "1h stochastic turning up from below 20 while 4h MACD momentum is bullish"
```

Expressions use `and` / `or` / `not`, comparisons, quoted state names and `.str.startswith(...)`.
Unknown column names fail with suggestions.

### As a file (for anything that needs history)

```python
from kit.signals import Signal

class CrossAfterFlip(Signal):
    name = "cross_after_flip"
    side = "C"
    note = "stochastic buy cross within 3 bars of the 1h MACD histogram turning positive"

    def when(self, df):
        pos = df.raw1h_macd_hist > 0
        flip = pos & ~pos.groupby(df.ticker).shift(1, fill_value=False)
        recent = flip.groupby(df.ticker).transform(lambda s: s.rolling(4, min_periods=1).max())
        return df.raw1h_st_cross_up & (recent > 0)
```

Put it in `plugins/signals/` (or a `plugin_dirs` folder) and opt in per study:
`use_signals = ["cross_after_flip"]`. Scaffold with `uv run kit new-signal <name>`.

### What a signal can use

`uv run kit columns <study>` lists every column with example values.

| Prefix | Contents |
|---|---|
| `h1_`, `h4_`, `D_`, `m15_`, `m3_` | Readings per timeframe (higher timeframes = last closed bar) |
| `mktD_`, `mktH1_` | The market ticker's readings |
| `raw1h_`, `raw4h_`, `rawD_` | Every indicator output as computed, including events (`raw1h_st_cross_up`) |
| *(none)* | Session readings (`gap_open_atr`, `from_open_atr`, `vs_prev_high_atr`, `day_range_pos`, …), `hour`, `weekday`, `close`, `ticker` |

Rows are sorted by ticker, then time; use `df.groupby("ticker")` for anything that looks back.

### What you get

Per signal and half: entries, entries per month, % of bars firing, the rate and lift of a winning
leg starting right there (1x and 3x), and how often price went 0.75 day-ATR its way first. To test a
signal as trades, name it in `prereg.md` (`signal: stoch_turn_up`).
