"""RSI hook (example) — plug-in signal. Needs the rsi_bands example indicator in the study:

    indicators = ["stoch", "rsi", "macd", "rsi_bands"]
    use_signals = ["rsi_hook"]

Plain words: on the 1h chart, RSI hooks back up over its lower band while yesterday's daily RSI
is not overbought and the 4h MACD histogram is not falling deeper below zero.
"""
from kit.signals import Signal


class RsiHook(Signal):
    name = "rsi_hook"
    side = "C"
    note = "1h RSI hooks up over its lower band; yesterday's daily RSI < 70; 4h MACD not bear widening"

    def when(self, df):
        return (df.raw1h_rb_hook_up.astype(bool)
                & (df.h1_rb_daily_rsi < 70)
                & (df.h4_MACD_STATE.astype(str) != "bear widening"))
