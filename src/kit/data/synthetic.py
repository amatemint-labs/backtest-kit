"""A made-up market for `kit smoke` and the tests. Deterministic (fixed seed), no real tickers.

What is in it: a market proxy (SYNSPY) and five names (SYNA..SYNE) with 1-minute regular-hours
bars, beta to the market, volatility clustering, and ONE planted pattern: before some up-moves,
volume surges for ~1-2 hours (down-moves get no warning). The smoke test checks that the
scorecard finds that pattern on the half of time it did not learn from. Nothing here is a
real price; nothing learned here says anything about markets.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import TZ
from . import store

TICKERS = ["SYNSPY", "SYNA", "SYNB", "SYNC", "SYND", "SYNE"]
MARKET = "SYNSPY"
START, END = "2024-05-01", "2026-04-30"
SPLIT = "2025-05-01"


def _days(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end, tz=TZ)


def make_minutes(start: str = START, end: str = END, seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    days = _days(start, end)
    nd, nm = len(days), 390
    n = nd * nm
    # minute-bar close times 09:31..16:00, built in New York wall time (DST-safe)
    ts = pd.DatetimeIndex(np.repeat(days.tz_localize(None).values, nm)
                          + np.tile(pd.to_timedelta(np.arange(1, nm + 1) + 570, unit="m").values, nd)).tz_localize(TZ)
    # intraday volume shape (U) and per-day volatility regime (AR(1) in log)
    u = np.linspace(-1, 1, nm)
    vshape = 0.6 + 1.2 * u ** 2
    lv = np.zeros(nd)
    for d in range(1, nd):
        lv[d] = 0.92 * lv[d - 1] + 0.18 * rng.standard_normal()
    dayvol = np.exp(lv)
    sig_min = 0.18 / np.sqrt(252 * nm)
    mkt = rng.standard_normal(n) * sig_min * np.repeat(dayvol, nm)
    out = {}
    for t_i, tk in enumerate(TICKERS):
        if tk == MARKET:
            r = mkt.copy()
            beta, p0, vol0 = 1.0, 500.0, 5e5
        else:
            beta = 0.8 + 0.25 * t_i
            idio_vol = (0.25 + 0.08 * t_i) / np.sqrt(252 * nm)
            r = beta * mkt + rng.standard_normal(n) * idio_vol * np.repeat(dayvol, nm)
            p0, vol0 = 40.0 + 30 * t_i, 2e5
        drift = np.zeros(n)
        volx = np.ones(n)
        if tk != MARKET:
            # planted events: roughly every 6 trading days
            n_ev = nd // 6
            starts = np.sort(rng.choice(np.arange(5 * nm, n - 3 * nm), size=n_ev, replace=False))
            sd = np.std(r)
            for s in starts:
                up = rng.random() < 0.6
                length = int(rng.integers(nm // 2, int(1.5 * nm)))
                total = (2.5 + 2.0 * rng.random()) * sd * np.sqrt(nm)      # ~1.5-3 daily ATR
                drift[s:s + length] += (1 if up else -1) * total / length
                if up:     # the tell: heavy volume for 60-120 minutes before the up-move only
                    w = int(rng.integers(60, 121))
                    volx[max(0, s - w):s] *= 4.0
        r = r + drift
        close = p0 * np.exp(np.cumsum(r))
        openp = np.r_[p0, close[:-1]] * (1 + rng.standard_normal(n) * 0.1 * sig_min)
        wick = np.abs(rng.standard_normal(n)) * np.abs(r).mean() * close
        high = np.maximum(openp, close) + 0.5 * wick
        low = np.minimum(openp, close) - 0.5 * wick
        vol = (vol0 * np.tile(vshape, nd) * np.repeat(dayvol, nm) * volx
               * np.exp(0.4 * rng.standard_normal(n))).round()
        out[tk] = pd.DataFrame({"ts": ts, "open": openp, "high": high, "low": low, "close": close, "volume": vol})
    return out


def build(data_dir: Path, tfs: list[str], start: str = START, end: str = END, seed: int = 7) -> dict:
    """Write synthetic raw minute bars and every timeframe into data_dir."""
    data_dir = Path(data_dir)
    counts = {}
    for tk, m1 in make_minutes(start, end, seed).items():
        store.write(m1, store.path(data_dir, "1m", tk, raw=True))
        counts[tk] = store.build_timeframes(data_dir, tk, tfs)
    return counts


SMOKE_START, SMOKE_END = "2025-05-01", "2026-04-30"


def ensure(data_dir: Path, tfs: list[str], log=print) -> Path:
    """The one-year synthetic store used by smoke, check-indicator and examples (built once)."""
    import shutil
    data_dir = Path(data_dir)
    marker = data_dir / ".smoke_v1"
    if not marker.exists():
        log("building synthetic data (one-time, ~10s) ...")
        if data_dir.exists():
            shutil.rmtree(data_dir)
        build(data_dir, tfs, start=SMOKE_START, end=SMOKE_END)
        marker.write_text("synthetic v1\n")
    return data_dir
