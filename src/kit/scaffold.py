"""`kit new-indicator` / `kit new-signal`: start a plug-in file from a template."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import config

INDICATOR = '''"""{title} — plug-in indicator.

Ported from: {pine_ref}
Port notes (fill in as you go — which Pine lines map to which Python lines, and anything you had
to decide, e.g. warm-up, session, how a higher timeframe is read):
  -
Prove it before trusting it:
  uv run kit check-indicator {name}          # runs, no lookahead, coverage, readings
  uv run kit match-check <export.csv> --indicator {name}   # vs your TradingView chart
"""
import numpy as np

from kit.ind import pine            # Pine built-ins: ema, sma, rma, wma, rsi, stoch, atr, macd, bb, vwap,
                                    # crossover, crossunder, highest, lowest, pivothigh, barssince, valuewhen, ...
from kit.plugin import Indicator


class {cls}(Indicator):
    name = "{name}"
    version = "{title} v1 ({today})"
    requires = ()                               # e.g. ("macd",) to use its outputs via ctx.outputs["macd"]
    tv_columns = {{"{prefix}_line": ["{title}"]}}  # output column -> TradingView plot title(s) for match-check

    def compute(self, bars, ctx):
        """bars: this timeframe's OHLCV (oldest first). Return {{column: array}}, one value per bar.
        ctx.tf = timeframe ("1h", "1D", ...); ctx.htf("1D", fn) = a higher timeframe, closed bars only."""
        length = 21 if ctx.tf == "1D" else 14       # per-timeframe parameters go here
        line = pine.ema(bars.close, length)
        return {{"{prefix}_line": line}}

    def readings(self, out, bars):
        """What a study learns from: numbers, plus named states (names ending in STATE)."""
        x = out["{prefix}_line"].to_numpy(float)
        close = bars.close.to_numpy(float)
        return {{
            "{prefix}_dist_pct": 100 * (close - x) / x,
            "{prefix}_slope3": x - pine.shift(x, 3),
            "{PREFIX}_STATE": self.combine(np.where(close > x, "above", "below"), self.direction(x, 3)),
        }}
'''

SIGNAL = '''"""{title} — plug-in signal (opt in per study: add "{name}" to `use_signals` in study.toml).

Plain words: {note}
"""
from kit.signals import Signal


class {cls}(Signal):
    name = "{name}"
    side = "C"            # C = calls (long), P = puts (short)
    note = "{note}"

    def when(self, df):
        """df: one row per 1h bar, all tickers, sorted by ticker then time; everything known at the bar's close.
        Return a True/False series. Use df.groupby("ticker") for anything that looks back across rows."""
        return (df.h1_stoch_k < 20) & (df.h1_stoch_ch2 > 0)
'''


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    if not s or s[0].isdigit():
        raise ValueError("use a name that starts with a letter, e.g. my_rsi")
    return s


def new_indicator(s: config.Settings, name: str, pine: str | None = None) -> dict:
    from datetime import date
    slug = _slug(name)
    d = s.root / "plugins" / "indicators"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{slug}.py"
    if f.exists():
        raise FileExistsError(f"{f} already exists")
    pine_ref = "(not from Pine)"
    if pine:
        src = Path(pine).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"no Pine file at {src}")
        dst = d / f"{slug}.pine"
        shutil.copyfile(src, dst)
        pine_ref = f"plugins/indicators/{slug}.pine (copied from {src.name})"
    prefix = slug[:6]
    f.write_text(INDICATOR.format(name=slug, cls="".join(w.title() for w in slug.split("_")), title=name.replace("_", " ").title(),
                                  pine_ref=pine_ref, prefix=prefix, PREFIX=prefix.upper(), today=date.today().isoformat()))
    return {"file": str(f), "pine": pine_ref,
            "next": (f"Port the Pine logic into {f.name} (ask Claude: 'port {pine_ref.split()[0]} into {f.name}'), "
                     f"then `uv run kit check-indicator {slug}`.")}


def new_signal(s: config.Settings, name: str, note: str = "describe the setup in one line") -> dict:
    slug = _slug(name)
    d = s.root / "plugins" / "signals"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{slug}.py"
    if f.exists():
        raise FileExistsError(f"{f} already exists")
    f.write_text(SIGNAL.format(name=slug, cls="".join(w.title() for w in slug.split("_")), title=name.replace("_", " ").title(), note=note))
    return {"file": str(f), "next": f"Edit when() in {f.name}, add \"{slug}\" to use_signals in a study.toml, then `kit study run`."}
