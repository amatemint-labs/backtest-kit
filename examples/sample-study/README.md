# Sample study

Everything in this folder was produced by `uv run kit examples` on the kit's synthetic dataset: five
made-up tickers (SYNA to SYNE) and a made-up market index (SYNSPY), one year of 1-minute bars, with a
single pattern planted in the data. Some up-moves are preceded by heavy volume; down-moves get no such
warning. None of the prices are real, so the numbers say nothing about markets. The folder exists to
show what a study produces.

| File | Contents |
|---|---|
| `study.toml` | Settings: the indicators (the three built-ins plus the example plug-in `rsi_bands`), three signals written as expressions, and one signal written as a plug-in |
| `prereg.md` | The pre-registration, written before the run: the idea, the entry and exit, the measure and the pass mark |
| `report.html` | The report. Open it in a browser |
| `trades.csv` | Every trade the trade check took, with entry and exit, option expiry and premium, exit reason and option multiple |
| `summary.json` | Every table in the report in machine-readable form |

A few things to look for in the report. The scorecard finds the planted pattern on the half of the
data it did not learn from: volume readings raise the odds of a winning call in both halves. The
`volume_surge` signal shows roughly three times the base rate in both halves, while
`overbought_fade` works in the first half and fails in the second, which is what an idea that does not
hold up looks like. The trade check compares each signal's entries with entering on every bar under
the same exit, and the tail-concentration table shows how much of the profit came from a handful of
days or tickers.
