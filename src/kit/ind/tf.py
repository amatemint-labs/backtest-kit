"""Timeframe names and lengths."""
from __future__ import annotations

TF_SECONDS = {
    "1m": 60, "2m": 120, "3m": 180, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1D": 86400, "2D": 172800, "3D": 259200,
    "1W": 604800, "1M": 2592000, "3M": 7776000,
}
INTRADAY = {k for k, v in TF_SECONDS.items() if v < 86400}
ALIASES = {"60": "1h", "240": "4h", "120": "2h", "D": "1D", "W": "1W", "M": "1M", "1d": "1D", "1w": "1W",
           "h1": "1h", "h4": "4h", "d": "1D", "3": "3m", "15": "15m", "5": "5m", "30": "30m", "10": "10m", "1": "1m"}
# A conventional "one step up" timeframe, for indicators that read a higher timeframe.
NEXT_TF = {"1m": "15m", "3m": "15m", "5m": "1h", "10m": "1h", "15m": "1h", "30m": "4h", "1h": "1D", "2h": "1D",
           "4h": "1D", "1D": "1W", "2D": "1W", "1W": "1M"}


def norm_tf(tf: str) -> str:
    tf = str(tf).strip()
    if tf in TF_SECONDS:
        return tf
    if tf in ALIASES:
        return ALIASES[tf]
    if tf.lower() in ALIASES:
        return ALIASES[tf.lower()]
    raise ValueError(f"unknown timeframe {tf!r}; use one of {sorted(TF_SECONDS, key=TF_SECONDS.get)}")


def seconds(tf: str) -> int:
    return TF_SECONDS[norm_tf(tf)]


def minutes(tf: str) -> int:
    return seconds(tf) // 60


def is_intraday(tf: str) -> bool:
    return seconds(tf) < 86400


def next_tf(tf: str) -> str | None:
    return NEXT_TF.get(norm_tf(tf))
