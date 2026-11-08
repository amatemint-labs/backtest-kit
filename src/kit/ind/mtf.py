"""How a higher-timeframe (HTF) value reaches a lower-timeframe bar.

Three modes. All bar timestamps are bar CLOSE times.

  "closed"  (default, for studies) — the last HTF bar that had closed by this bar's close.
            No lookahead. A 1h bar at 11:30 sees YESTERDAY's daily value.
  "forming" (studies, optional)    — the HTF bar still forming, as a trader saw it live at
            this bar's close (its close so far = this bar's close). No lookahead. Only True
            Momentum supports it, because its HTF part depends on the close alone.
  "tv"      (match-check ONLY)     — what TradingView paints on HISTORY with
            `lookahead_on`: the FINISHED HTF bar is shown on every lower bar inside it.
            That is lookahead. Use it to prove the ports match TradingView charts, never in a study.
"""
from __future__ import annotations

import numpy as np

MODES = ("closed", "forming", "tv")
STUDY_MODES = ("closed", "forming")


def idx_closed(src_ts: np.ndarray, htf_ts: np.ndarray) -> np.ndarray:
    """Index of the last HTF bar with close <= src close (-1 if none)."""
    return np.searchsorted(htf_ts, src_ts, side="right") - 1


def idx_containing(src_ts: np.ndarray, htf_ts: np.ndarray) -> np.ndarray:
    """Index of the HTF bar whose period contains the src bar (first HTF close >= src close)."""
    k = np.searchsorted(htf_ts, src_ts, side="left")
    k = k.astype(np.int64)
    k[k >= len(htf_ts)] = -1
    return k


def take(values: np.ndarray, idx: np.ndarray) -> np.ndarray:
    out = np.full(idx.shape[0], np.nan)
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out


def as_ns(ts) -> np.ndarray:
    """Timestamps (tz-aware Series/Index) -> int64 nanoseconds UTC, for searchsorted."""
    import pandas as pd
    t = pd.DatetimeIndex(ts)
    if t.tz is None:
        raise ValueError("timestamps must be timezone-aware (America/New_York)")
    return t.tz_convert("UTC").as_unit("ns").asi8      # pandas 3 may store "us"; always compare in ns
