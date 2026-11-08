"""The bar store: one Parquet file per ticker per timeframe, one row per bar.

Columns: ts (bar CLOSE time, tz America/New_York), open, high, low, close, volume.
Layout:  data/raw/1m/<TICKER>.parquet     minute bars as fetched (the cache fetch resumes from)
         data/raw/1D/<TICKER>.parquet     daily bars as fetched
         data/bars/<tf>/<TICKER>.parquet  built timeframes (3m, 15m, 1h, 4h, 1D, plus 2D, 1W, 1M)
Intraday bars are regular hours only (09:30-16:00 ET) and anchored at 09:30, like TradingView
for US stocks: 1h bars close 10:30, 11:30 ... 15:30, 16:00; 4h bars close 13:30 and 16:00.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import TZ
from ..ind.tf import is_intraday, minutes, norm_tf

COLS = ["ts", "open", "high", "low", "close", "volume"]
SESSION_OPEN_MIN = 9 * 60 + 30
SESSION_LEN_MIN = 390
HTF_NEEDED = ["1D", "2D", "1W", "1M"]          # built alongside your timeframes so indicators can read them


def path(data_dir: Path, tf: str, ticker: str, raw: bool = False) -> Path:
    base = Path(data_dir) / ("raw" if raw else "bars") / norm_tf(tf)
    return base / f"{safe(ticker)}.parquet"


def safe(ticker: str) -> str:
    return ticker.replace(" ", "_").replace("/", "-").replace("$", "IDX_")


def write(df: pd.DataFrame, p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    df = df[COLS].sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(p)          # atomic: a crash never leaves a half-written file
    return p


def read(data_dir: Path, tf: str, ticker: str, raw: bool = False) -> pd.DataFrame | None:
    p = path(data_dir, tf, ticker, raw)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ)
    return df.sort_values("ts").reset_index(drop=True)


def tickers(data_dir: Path, tf: str = "1h") -> list[str]:
    d = Path(data_dir) / "bars" / norm_tf(tf)
    return sorted(p.stem for p in d.glob("*.parquet")) if d.exists() else []


def rth(df: pd.DataFrame) -> pd.DataFrame:
    """Keep minute bars that CLOSE inside 09:31..16:00 ET."""
    t = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    return df[(t > SESSION_OPEN_MIN) & (t <= SESSION_OPEN_MIN + SESSION_LEN_MIN)].reset_index(drop=True)


def _agg(df: pd.DataFrame, keys) -> pd.DataFrame:
    g = df.groupby(keys, sort=True)
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def resample_intraday(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """1-minute RTH bars -> N-minute bars anchored at 09:30 (close-time stamps)."""
    n = minutes(tf)
    df = rth(m1)
    day = df["ts"].dt.normalize()
    mins = df["ts"].dt.hour * 60 + df["ts"].dt.minute - SESSION_OPEN_MIN      # 1..390
    b = (mins - 1) // n
    out = _agg(df.assign(day=day, b=b), ["day", "b"]).reset_index()
    close_min = np.minimum((out["b"] + 1) * n, SESSION_LEN_MIN) + SESSION_OPEN_MIN
    out["ts"] = out["day"] + pd.to_timedelta(close_min, unit="m")
    return out[COLS]


def daily_from_minutes(m1: pd.DataFrame) -> pd.DataFrame:
    df = rth(m1)
    out = _agg(df.assign(day=df["ts"].dt.normalize()), ["day"]).reset_index()
    out["ts"] = out["day"] + pd.Timedelta(hours=16)
    return out[COLS]


def resample_daily(d1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Daily bars -> 2D / 1W / 1M / 3M. Each bar is stamped with its last day's 16:00 close.
    2D pairs trading days counted from 2000-01-03 (TradingView's 2D anchor is unverified)."""
    tf = norm_tf(tf)
    day = d1["ts"].dt.tz_localize(None).dt.normalize()
    if tf == "1D":
        return d1[COLS].copy()
    if tf == "2D":
        key = np.busday_count(np.datetime64("2000-01-03"), day.values.astype("datetime64[D]")) // 2
    elif tf == "1W":
        iso = day.dt.isocalendar()
        key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    elif tf == "1M":
        key = day.dt.year * 100 + day.dt.month
    elif tf == "3M":
        key = day.dt.year * 10 + (day.dt.month - 1) // 3
    else:
        raise ValueError(tf)
    df = d1.assign(k=np.asarray(key))
    out = _agg(df, ["k"])
    out["ts"] = df.groupby("k")["ts"].last()
    return out.reset_index(drop=True)[COLS]


def build_timeframes(data_dir: Path, ticker: str, tfs: list[str]) -> dict[str, int]:
    """From raw/1m (+ raw/1D when present) write bars/<tf>/<ticker> for tfs and the HTFs TM needs."""
    m1 = read(data_dir, "1m", ticker, raw=True)
    d1raw = read(data_dir, "1D", ticker, raw=True)
    want = sorted({norm_tf(t) for t in tfs} | set(HTF_NEEDED), key=lambda t: (not is_intraday(t), minutes(t)))
    if m1 is None and d1raw is None:
        return {}
    d_from_m = daily_from_minutes(m1) if m1 is not None and len(m1) else None
    if d1raw is not None and len(d1raw):
        daily = d1raw
        if d_from_m is not None:          # minute-built days fill any gap at the recent end
            daily = pd.concat([d1raw, d_from_m[d_from_m.ts > d1raw.ts.max()]], ignore_index=True)
    else:
        daily = d_from_m
    counts = {}
    for tf in want:
        if is_intraday(tf):
            if m1 is None or not len(m1):
                continue
            out = resample_intraday(m1, tf)
        else:
            out = resample_daily(daily, tf)
        write(out, path(data_dir, tf, ticker))
        counts[tf] = len(out)
    return counts
