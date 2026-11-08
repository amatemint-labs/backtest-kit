"""`kit examples`: rebuild examples/sample-study/ — a full study on the synthetic dataset, so anyone
can see what a report, a trade log and the results file look like before running on real data."""
from __future__ import annotations

import shutil
from dataclasses import replace

from . import config
from .data import synthetic

STUDY = """# Sample study on SYNTHETIC data (made-up tickers SYNA..SYNE, market SYNSPY). Numbers mean nothing about markets.
tickers = []
market = "SYNSPY"
start = "2025-05-01"
end = ""
split = "2025-11-03"
holdout_start = ""
mode = "closed"
labels = ["C_1x", "C_3x", "P_1x", "P_3x"]
group_removal = true
min_state_n = 120
indicators = ["stoch", "rsi", "macd", "rsi_bands"]      # the three bundled indicators + the example plug-in
use_signals = ["rsi_hook"]                               # plug-in signal from plugins/signals/example_rsi_hook.py

[signals.volume_surge]
side = "C"
when = "h1_volume_x > 2.0 and m15_volume_x > 1.5"
note = "heavy volume on the 1h and 15m bars"

[signals.stoch_turn_up]
side = "C"
when = "h1_STOCH_STATE == '<20 rising' and h4_MACD_STATE != 'bear widening'"
note = "1h stochastic turning up from below 20, 4h MACD not falling harder"

[signals.overbought_fade]
side = "P"
when = "h1_stoch_k > 80 and h1_stoch_ch2 < 0 and h1_MACD_STATE == 'bull narrowing'"
note = "1h stochastic rolling over above 80 while 1h MACD momentum fades"
"""

PREREG = """# Pre-registration: sample-study (synthetic data)

idea: heavy volume on the 1h and 15m bars comes before up-moves worth buying calls for
entry: buy the ATM call at the 1h close on the first bar of each volume_surge signal
exit: sell when price turns 0.75 day-ATR off its best point since entry, or at expiry
measure: median option multiple, % doubled, % lost half — signal entries vs all bars, each half
pass_mark: signal median multiple at least 1.2x the all-bars median in BOTH halves

## Settings the kit reads (change only before running)
label: C_1x
grades: A, B
trail_k: 0.75
exhaustion: yes
min_premium: 0.20
signal: volume_surge

## Verdict (append after running; never edit above this line)
"""

README = """# Sample study (synthetic data)

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
"""


def build(s: config.Settings, log=print) -> dict:
    from .method import study
    ss = replace(s, data_dir=s.data_dir / "synthetic", market=synthetic.MARKET, start=synthetic.SMOKE_START)
    synthetic.ensure(ss.data_dir, s.timeframes, log=log)
    name = "_example"
    sd = s.studies_dir / name
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "study.toml").write_text(STUDY)
    (sd / "prereg.md").write_text(PREREG)
    fp = sd / "results" / "prereg_fingerprint.txt"
    if fp.exists():
        fp.unlink()
    r = study.run(ss, name, log=log)
    out = s.root / "examples" / "sample-study"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sd / "study.toml", out / "study.toml")
    shutil.copyfile(sd / "prereg.md", out / "prereg.md")
    shutil.copyfile(sd / "report.html", out / "report.html")
    shutil.copyfile(sd / "results" / "summary.json", out / "summary.json")
    if (sd / "results" / "trades.csv").exists():
        shutil.copyfile(sd / "results" / "trades.csv", out / "trades.csv")
    (out / "README.md").write_text(README)
    return {"folder": str(out), "files": sorted(p.name for p in out.iterdir()), "study": r}
