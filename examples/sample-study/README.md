# Sample study (synthetic data)

Everything in this folder was produced by `uv run kit examples` on the kit's **made-up** dataset
(tickers SYNA–SYNE and a market proxy SYNSPY, one year of 1-minute bars with one planted pattern:
heavy volume before some up-moves). **Nothing here is a real price or says anything about markets** —
it shows what a study produces, so you know what to expect from your own.

| File | What it is |
|---|---|
| `study.toml` | The settings: indicators (3 bundled + the example plug-in `rsi_bands`), three expression signals, one plug-in signal |
| `prereg.md` | The pre-registration: the idea, the one-line entry and exit, the measure and the pass mark — written before running |
| `report.html` | The one-page report: census, scorecards, lift tables, look-alikes, your signals, exhaustion, the trade check and its trades |
| `trades.csv` | Every trade the trade check took: entry/exit time and price, option expiry and premium, exit reason, option multiple |
| `summary.json` | Every table in the report, machine-readable (what Claude reads with `kit report sample-study --json`) |

Open `report.html` in a browser. Things worth noticing:
- **The scorecard finds the planted pattern** ("volume_x" bins raise the call odds in both halves) — that is
  the kit proving it can find a real effect on time it never learned from.
- **Signals**: `volume_surge` shows ~3x lift in both halves (the planted tell); `stoch_turn_up` and
  `overbought_fade` show what an ordinary idea looks like on data with no such edge.
- **The trade check** compares the signal's entries with ALL bars on the same exits; even a real tell does
  not automatically make money once priced as an option — that is the point of pricing it.
- **Tail concentration**: how much of the profit came from the top 3 days / tickers.
