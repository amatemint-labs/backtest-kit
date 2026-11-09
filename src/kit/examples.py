"""`kit examples`: rebuild examples/sample-study/ — a full study on the synthetic dataset, so anyone
can see what a report, a trade log and the results file look like before running on real data."""
from __future__ import annotations

import shutil
from dataclasses import replace

from . import config
from .data import synthetic

STUDY = """# Sample study on SYNTHETIC data (made-up tickers SYNA..SYNE, market SYNSPY). Numbers mean nothing about markets.
title = "Sample study (synthetic data)"
tickers = ["SYNA", "SYNB", "SYNC", "SYND", "SYNE"]
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
measure: median option multiple, % doubled and % lost half for signal entries vs all bars, in each half
pass_mark: signal median multiple at least 1.2x the all-bars median in both halves

## Settings the kit reads (change only before running)
label: C_1x
grades: A, B
trail_k: 0.75
exhaustion: yes
min_premium: 0.20
signal: volume_surge

## Verdict (append after running; never edit above this line)
"""

README = """# Sample study

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
"""


MULTI_STUDY = """# Sample study on SYNTHETIC data: a made-up future (SYNFUT, $50 a point, CME hours) and a made-up coin
# (SYNCOIN, trades around the clock). Numbers mean nothing about markets.
title = "Sample study: a future and a coin (synthetic data)"
tickers = ["SYNFUT", "SYNCOIN"]
market = "SYNSPY"
start = "2025-05-01"
end = ""
split = "2025-11-03"
holdout_start = ""
mode = "closed"
trade_as = "auto"          # futures and crypto -> traded as the instruments themselves
labels = ["C_2atr", "C_4atr", "P_2atr", "P_4atr"]
group_removal = true
min_state_n = 120

[signals.volume_surge]
side = "C"
when = "h1_volume_x > 2.0 and m15_volume_x > 1.5"
note = "heavy volume on the 1h and 15m bars"

[signals.overbought_fade]
side = "P"
when = "h1_stoch_k > 80 and h1_stoch_ch2 < 0 and h1_MACD_STATE == 'bull narrowing'"
note = "1h stochastic rolling over above 80 while 1h MACD momentum fades"
"""

MULTI_PREREG = """# Pre-registration: sample-futures-crypto (synthetic data)

idea: heavy volume on the 1h and 15m bars comes before up-moves in futures and crypto too
entry: buy the future or the coin at the 1h close on the first bar of each volume_surge signal
exit: sell when price turns 0.75 day-ATR off its best point since entry, or after 5 trading days
measure: median move in day-ATRs and win rate for signal entries vs all bars, in each half
pass_mark: signal median move at least +0.5 day-ATR and win rate above 55% in both halves

## Settings the kit reads (change only before running)
label: C_2atr
grades: A, B
trail_k: 0.75
exhaustion: yes
signal: volume_surge

## Verdict (append after running; never edit above this line)
"""

MULTI_README = """# Sample study: a future and a coin

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
"""

EXAMPLES = (("_example", "sample-study", STUDY, PREREG, README),
            ("_example_multi", "sample-futures-crypto", MULTI_STUDY, MULTI_PREREG, MULTI_README))


def build(s: config.Settings, log=print) -> dict:
    from .method import study
    ss = replace(s, data_dir=s.data_dir / "synthetic", market=synthetic.MARKET, start=synthetic.SMOKE_START)
    synthetic.ensure(ss.data_dir, s.timeframes, log=log)
    done = {}
    for name, folder, toml, prereg, readme in EXAMPLES:
        sd = s.studies_dir / name
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "study.toml").write_text(toml)
        (sd / "prereg.md").write_text(prereg)
        fp = sd / "results" / "prereg_fingerprint.txt"
        if fp.exists():
            fp.unlink()
        r = study.run(ss, name, log=log)
        out = s.root / "examples" / folder
        out.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sd / "study.toml", out / "study.toml")
        shutil.copyfile(sd / "prereg.md", out / "prereg.md")
        shutil.copyfile(sd / "report.html", out / "report.html")
        shutil.copyfile(sd / "results" / "summary.json", out / "summary.json")
        if (sd / "results" / "trades.csv").exists():
            shutil.copyfile(sd / "results" / "trades.csv", out / "trades.csv")
        (out / "README.md").write_text(readme)
        done[folder] = {"folder": str(out), "files": sorted(p.name for p in out.iterdir()), "study": r}
    return {"folder": done["sample-study"]["folder"], "files": done["sample-study"]["files"],
            "study": done["sample-study"]["study"], "examples": done}
