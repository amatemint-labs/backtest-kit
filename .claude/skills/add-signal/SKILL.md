---
name: add-signal
description: Turn a setup the user describes in words ("stochastic turning up from under 20 while the 4h is still bullish") into a kit signal and measure it on every bar. Use when the user describes an entry, a setup, a pattern they trade, or asks "how often does X work".
---

# Add a signal

1. **Restate the setup in one line and confirm it**: side (calls or puts), timeframe, each condition
   as a number or a named state. Ask about anything ambiguous ("turning up" = rising over 2 bars?).

2. **Find the columns**: `uv run kit columns <study> --json` (or `uv run kit columns` for a sample).
   Prefixes: `h1_`, `h4_`, `D_`, `m15_`, `m3_` = readings per timeframe (higher ones are the last
   CLOSED bar); `mktD_`, `mktH1_` = the market ticker; `raw1h_`, `raw4h_`, `rawD_` = raw indicator
   outputs and events (e.g. `raw1h_st_cross_up`, `raw1h_macd_hist`); plus `gap_open_atr`,
   `from_open_atr`, `vs_prev_high_atr`, `day_range_pos`, `hour`, `weekday`. If a reading the user
   needs doesn't exist, it is an indicator job (port-pine-indicator), not a signal job.

3. **Write it** — prefer an expression in the study's `study.toml`:
   ```toml
   [signals.stoch_turn_up]
   side = "C"
   when = "h1_STOCH_STATE == '<20 rising' and h4_MACD_STATE.str.startswith('bull')"
   note = "1h stochastic turning up from below 20 while 4h MACD momentum is bullish"
   ```
   Expressions use `and`/`or`/`not`, comparisons, and quoted state names. For anything that needs
   history across bars (e.g. "within 3 bars of the MACD histogram turning positive"), use
   `uv run kit new-signal <name> --note "..."` and write `when(df)` with `df.groupby("ticker")`;
   then add the name to `use_signals = [...]` in study.toml.

4. **Run the study**: `uv run kit study run <name> --json`. The Signals section shows, per half:
   entries and entries per month, how much more often a winning option leg started right there
   (lift vs any bar), and how often price went its way first. It is descriptive — no money claims.

5. **Only with a pre-registration**, test it as trades: set `signal: <name>` in `prereg.md` (with the
   idea, entry, exit, measure, pass mark filled in BEFORE running), run again, and read the trade
   check: signal entries vs ALL bars on the same exits, both halves, plus `results/trades.csv`.

6. **Report honestly**: a signal that holds in only one half is not a finding. Say how many signals
   were tried in this study — every extra one raises the chance that a good-looking one is luck.
