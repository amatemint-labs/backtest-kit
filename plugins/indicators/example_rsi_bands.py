"""RSI Bands (example) — plug-in indicator, ported line by line from example_rsi_bands.pine.

Port notes (Pine line -> Python):
  len = timeframe.isdaily ? 21 : rsiLen     -> `length = 21 if ctx.tf == "1D" else 14`
  ta.rsi / ta.sma / ta.stdev                -> pine.rsi / pine.sma / pine.stdev (same formulas, same warm-up)
  request.security("D", ta.rsi(close,14)[1], lookahead_on)
                                            -> ctx.htf_prev("1D", ...)   (yesterday's daily value; never looks ahead)
  ta.crossover(r, lower)                    -> pine.crossover(r, lower)
  plot titles "RSI", "Upper", "Lower", "Daily RSI" -> tv_columns, so `kit match-check` can compare them.
Proved with: uv run kit check-indicator rsi_bands
"""
import numpy as np

from kit.ind import pine
from kit.plugin import Indicator


class RsiBands(Indicator):
    name = "rsi_bands"
    version = "RSI Bands (example) v1"
    tv_columns = {"rb_rsi": ["RSI"], "rb_upper": ["Upper"], "rb_lower": ["Lower"], "rb_daily_rsi": ["Daily RSI"]}

    def compute(self, bars, ctx):
        length = 21 if ctx.tf == "1D" else 14
        r = pine.rsi(bars.close, length)
        basis = pine.sma(r, 20)
        dev = 2.0 * pine.stdev(r, 20)
        upper, lower = basis + dev, basis - dev
        with np.errstate(divide="ignore", invalid="ignore"):
            pctb = (r - lower) / (upper - lower)
        daily = ctx.htf_prev("1D", lambda d: {"rsi": pine.rsi(d.close, 14)})["rsi"]
        return {"rb_rsi": r, "rb_upper": upper, "rb_lower": lower, "rb_pctb": pctb,
                "rb_daily_rsi": daily, "rb_hook_up": pine.crossover(r, lower)}

    def readings(self, out, bars):
        r = out["rb_rsi"].to_numpy(float)
        return {                       # reading names must be unique across indicators, hence the rb_ prefix
            "rb_rsi": r,
            "rb_rsi_ch3": r - pine.shift(r, 3),
            "rb_pctb": out["rb_pctb"].to_numpy(float),
            "rb_daily_rsi": out["rb_daily_rsi"].to_numpy(float),
            "RB_STATE": self.combine(self.zones(r, [30, 70], ["oversold", "middle", "overbought"]), self.direction(r, 2)),
        }
