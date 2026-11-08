"""Bundled indicators: classic, public formulas with TradingView's built-in default settings.

They use the same plug-in interface as your own tools (see kit/plugin.py and
plugins/indicators/example_rsi_bands.py) and serve as defaults and as examples of good readings.
"""
from __future__ import annotations

import numpy as np

from ..plugin import Indicator
from . import pine
from .tf import next_tf


class Stochastic(Indicator):
    """Stochastic oscillator, TradingView 'Stoch' defaults: %K length 14, smoothing 1, %D 3."""
    name = "stoch"
    version = "Stochastic 14/1/3"
    tv_columns = {"st_k": ["%K", "K"], "st_d": ["%D", "D"]}

    def compute(self, bars, ctx):
        k = pine.sma(pine.stoch(bars.close, bars.high, bars.low, 14), 1)
        d = pine.sma(k, 3)
        return {"st_k": k, "st_d": d, "st_cross_up": pine.crossover(k, d), "st_cross_down": pine.crossunder(k, d)}

    def readings(self, out, bars):
        k = out["st_k"].to_numpy(float)
        return {"stoch_k": k, "stoch_d": out["st_d"].to_numpy(float), "stoch_ch2": k - pine.shift(k, 2),
                "STOCH_STATE": self.combine(self.zones(k, [20, 40, 60, 80], ["<20", "20-40", "40-60", "60-80", ">80"]),
                                            self.direction(k, 2))}


class Rsi(Indicator):
    """Relative Strength Index, TradingView 'RSI' default length 14."""
    name = "rsi"
    version = "RSI 14"
    tv_columns = {"rsi_value": ["RSI"]}

    def compute(self, bars, ctx):
        return {"rsi_value": pine.rsi(bars.close, 14)}

    def readings(self, out, bars):
        r = out["rsi_value"].to_numpy(float)
        return {"rsi": r, "rsi_ch3": r - pine.shift(r, 3),
                "RSI_STATE": self.combine(self.zones(r, [30, 50, 70], ["oversold", "weak", "strong", "overbought"]),
                                          self.direction(r, 2))}


class Macd(Indicator):
    """MACD 12/26/9 (TradingView defaults), plus the histogram of the next higher timeframe
    (1h reads daily, 15m reads 1h, ...) from its last CLOSED bar — an example of ctx.htf()."""
    name = "macd"
    version = "MACD 12/26/9 + higher-timeframe histogram"
    tv_columns = {"macd_line": ["MACD"], "macd_signal": ["Signal"], "macd_hist": ["Histogram"]}

    def compute(self, bars, ctx):
        m, s, h = pine.macd(bars.close, 12, 26, 9, ctx.ema_seed)
        atr = pine.atr(bars.high, bars.low, bars.close, 14)
        with np.errstate(divide="ignore", invalid="ignore"):
            h_atr = h / atr

        def higher(b):
            hh = pine.macd(b.close, 12, 26, 9, ctx.ema_seed)[2]
            with np.errstate(divide="ignore", invalid="ignore"):
                return {"h": hh / pine.atr(b.high, b.low, b.close, 14)}
        htf = next_tf(ctx.tf)
        hh_atr = ctx.htf(htf, higher)["h"] if htf else np.full(len(bars), np.nan)
        return {"macd_line": m, "macd_signal": s, "macd_hist": h, "macd_hist_atr": h_atr, "macd_htf_hist_atr": hh_atr}

    def readings(self, out, bars):
        h = out["macd_hist_atr"].to_numpy(float)
        hh = out["macd_htf_hist_atr"].to_numpy(float)
        ch3 = np.abs(h) - np.abs(pine.shift(h, 3))
        side = np.where(h > 0, "bull", "bear").astype(object)
        state = self.combine(side, np.where(ch3 > 0, "widening", "narrowing"))
        state[np.isnan(h)] = "nan"
        hstate = np.where(hh > 0, "bull", "bear").astype(object)
        hstate[np.isnan(hh)] = "nan"
        return {"macd_hist_atr": h, "macd_hist_ch3": h - pine.shift(h, 3), "macd_htf_hist_atr": hh,
                "MACD_STATE": state, "MACD_HTF_STATE": hstate}


ALL = [Stochastic(), Rsi(), Macd()]
DEFAULT = [i.name for i in ALL]
