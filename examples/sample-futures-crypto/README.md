# Sample study: a future and a coin

Everything in this folder was produced by `uv run kit examples` on synthetic data: SYNFUT, a made-up
futures contract that trades CME hours (18:00 to 17:00 New York) at $50 a point, and SYNCOIN, a made-up
coin that trades around the clock every day. The same pattern as the stock sample is planted in both:
some up-moves are preceded by heavy volume. None of the prices are real.

Futures and crypto are traded as the instruments themselves rather than as options, so the labels and
results are measured in daily ATRs and percent:

| File | Contents |
|---|---|
| `study.toml` | Settings, including `trade_as = "auto"` and the ATR-based labels |
| `prereg.md` | The pre-registration, written before the run |
| `report.html` | The report. Open it in a browser |
| `trades.csv` | Every trade: entry and exit, exit reason, points, return, move in ATRs, and dollars per contract for the future |
| `summary.json` | Every table in the report in machine-readable form |

Things to look for: hourly bars follow each market's own session (the future's trading day starts the
evening before; the coin's runs midnight to midnight UTC), the scorecard finds the planted pattern in
both halves, and `dollars_per_unit` in the trade log is the move in points times $50.
