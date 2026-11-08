"""Modelled option prices (Black-Scholes). This is the DEFAULT pricing and it flatters results:
no bid/ask spread, constant IV, and 0DTE IV behaves very differently. Use it to RANK setups
against each other; decide on money only with real quotes.

IV  = max(30%, 1.15 x 20-day realized vol of daily closes), clipped at 300%, known at entry.
r   = 4%. Strike = the entry price (at the money).
Expiry is chosen by a rule known AT ENTRY (never by where the move ended):
    the first Friday at least N trading sessions after the entry date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

R = 0.04
IV_FLOOR, IV_MULT, IV_CAP = 0.30, 1.15, 3.0


def bs(S, K, T, sigma, call):
    S, K, T, sigma = (np.asarray(x, float) for x in (S, K, T, sigma))
    T = np.maximum(T, 1e-7)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (R + 0.5 * sigma * sigma) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    c = S * norm.cdf(d1) - K * np.exp(-R * T) * norm.cdf(d2)
    p = K * np.exp(-R * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return np.where(call, c, p)


def iv_from_rv(rv) -> np.ndarray:
    rv = np.asarray(rv, float)
    return np.clip(np.maximum(IV_FLOOR, IV_MULT * np.nan_to_num(rv, nan=IV_FLOOR)), IV_FLOOR, IV_CAP)


def expiry_after(dates, sessions: int) -> np.ndarray:
    """First Friday on or after (entry date + `sessions` trading days). dates: datetime64[D] array."""
    d = np.asarray(dates, dtype="datetime64[D]")
    later = np.busday_offset(d, sessions, roll="forward")
    wd = (later.astype("datetime64[D]").view("int64") - 4) % 7      # 1970-01-01 was a Thursday
    to_fri = (4 - wd) % 7
    return later + to_fri.astype("timedelta64[D]")


def day_fraction_left(ts: pd.Series) -> np.ndarray:
    """Share of the 09:30-16:00 session still to come at each timestamp (0 at the close)."""
    m = ts.dt.hour * 60 + ts.dt.minute
    return np.clip((16 * 60 - m.to_numpy()) / 390.0, 0, 1)


def years_to_expiry(dates, frac_left, expiry) -> np.ndarray:
    d = np.asarray(dates, dtype="datetime64[D]")
    e = np.asarray(expiry, dtype="datetime64[D]")
    return (np.busday_count(d, e) + np.asarray(frac_left, float) + 0.02) / 252.0


def multiple(S0, S1, T0, T1, iv, call):
    """Option value at exit / premium paid. ATM strike = S0."""
    p0 = bs(S0, S0, T0, iv, call)
    p1 = bs(S1, S0, T1, iv, call)
    with np.errstate(divide="ignore", invalid="ignore"):
        return p1 / p0, p0
