"""The bar store: one Parquet file per ticker per timeframe, one row per bar.

Columns: ts (bar CLOSE time, tz America/New_York), open, high, low, close, volume.
Layout:  data/raw/1m/<TICKER>.parquet     minute bars as fetched (the cache fetch resumes from)
         data/raw/1D/<TICKER>.parquet     daily bars as fetched
         data/bars/<tf>/<TICKER>.parquet  built timeframes (3m, 15m, 1h, 4h, 1D, plus 2D, 1W, 1M)
Intraday bars are anchored at each asset's session open (kit.assets): US stocks use regular hours
09:30-16:00 New York, so 1h bars close 10:30, 11:30 ... 15:30, 16:00; CME futures run 18:00-17:00
New York; crypto runs 00:00-24:00 UTC.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import TZ
from ..ind.tf import is_intraday, minutes, norm_tf

COLS = ["ts", "open", "high", "low", "close", "volume"]
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
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(TZ).dt.as_unit("ns")
    return df.sort_values("ts").reset_index(drop=True)


def tickers(data_dir: Path, tf: str = "1h") -> list[str]:
    d = Path(data_dir) / "bars" / norm_tf(tf)
    return sorted(p.stem for p in d.glob("*.parquet")) if d.exists() else []


def _session(session):
    from ..assets import SESSIONS
    return session if session is not None and not isinstance(session, str) else SESSIONS[session or "us_equity"]


def in_session(df: pd.DataFrame, session=None) -> pd.DataFrame:
    """Keep minute bars whose close falls inside the session (US equity hours by default)."""
    ses = _session(session)
    return df[ses.in_session(df["ts"])].reset_index(drop=True)


def drop_unfinished(df: pd.DataFrame, session=None, now=None) -> pd.DataFrame:
    """Drop minute bars from a trading day whose session has not closed yet: its daily and 4h bars
    would be partial."""
    if df.empty:
        return df
    ses = _session(session)
    now = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz="UTC"))
    now = now.tz_localize("UTC") if now.tzinfo is None else now
    day = ses.trade_date(df["ts"]).reset_index(drop=True)
    days = pd.Series(day.unique())
    closed = dict(zip(days, (ses.session_close(days) <= now).to_numpy()))
    return df[day.map(closed).fillna(False).to_numpy(bool)].reset_index(drop=True)


def stamp_daily(day_ts, session=None) -> pd.Series:
    """Daily bars from a vendor -> stamped with their session's close (the kit's convention)."""
    ses = _session(session)
    t = pd.to_datetime(pd.Series(day_ts)).reset_index(drop=True)
    if t.dt.tz is not None:
        t = t.dt.tz_convert(TZ).dt.tz_localize(None)
    return ses.session_close(t.dt.normalize())


def rth(df: pd.DataFrame) -> pd.DataFrame:
    """Keep minute bars that close inside 09:31..16:00 New York (US equity regular hours)."""
    return in_session(df, "us_equity")


def _agg(df: pd.DataFrame, keys) -> pd.DataFrame:
    g = df.groupby(keys, sort=True)
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()})


def resample_intraday(m1: pd.DataFrame, tf: str, session=None) -> pd.DataFrame:
    """Finer bars -> N-minute bars anchored at the session open (close-time stamps)."""
    ses = _session(session)
    n = minutes(tf)
    df = in_session(m1, ses)
    day = ses.trade_date(df["ts"])
    mins = ses.minute_of_session(df["ts"])
    b = (mins - 1) // n
    out = _agg(df.assign(day=day.to_numpy(), b=b.to_numpy()), ["day", "b"]).reset_index()
    close_min = np.minimum((out["b"] + 1) * n, ses.length_min)
    out["ts"] = ses.session_start(out["day"]) + pd.to_timedelta(close_min, unit="m")
    return out[COLS]


def daily_from_minutes(m1: pd.DataFrame, session=None) -> pd.DataFrame:
    ses = _session(session)
    df = in_session(m1, ses)
    out = _agg(df.assign(day=ses.trade_date(df["ts"]).to_numpy()), ["day"]).reset_index()
    out["ts"] = ses.session_close(out["day"])
    return out[COLS]


def resample_daily(d1: pd.DataFrame, tf: str, session=None) -> pd.DataFrame:
    """Daily bars -> 2D / 1W / 1M / 3M, each stamped with its last day's close.
    2D pairs trading days counted from 2000-01-03 (TradingView's 2D anchor is unverified)."""
    ses = _session(session)
    tf = norm_tf(tf)
    day = ses.trade_date(d1["ts"]).reset_index(drop=True)
    if tf == "1D":
        return d1[COLS].copy()
    if tf == "2D":
        dd = day.values.astype("datetime64[D]")
        key = ((dd - np.datetime64("2000-01-03")).astype(int) if len(ses.weekdays) == 7
               else np.busday_count(np.datetime64("2000-01-03"), dd)) // 2
    elif tf == "1W":
        iso = day.dt.isocalendar()
        key = iso["year"].astype(int) * 100 + iso["week"].astype(int)
    elif tf == "1M":
        key = day.dt.year * 100 + day.dt.month
    elif tf == "3M":
        key = day.dt.year * 10 + (day.dt.month - 1) // 3
    else:
        raise ValueError(tf)
    df = d1.reset_index(drop=True).assign(k=np.asarray(key))
    out = _agg(df, ["k"])
    out["ts"] = df.groupby("k")["ts"].last()
    return out.reset_index(drop=True)[COLS]


def build_timeframes(data_dir: Path, ticker: str, tfs: list[str]) -> dict[str, int]:
    """From raw/1m (+ raw/1D when present) write bars/<tf>/<ticker> for tfs plus 2D, 1W and 1M,
    using the ticker's trading session (see kit.assets)."""
    from ..assets import lookup
    ses = lookup(data_dir, ticker).session
    m1 = read(data_dir, "1m", ticker, raw=True)
    d1raw = read(data_dir, "1D", ticker, raw=True)
    want = sorted({norm_tf(t) for t in tfs} | set(HTF_NEEDED), key=lambda t: (not is_intraday(t), minutes(t)))
    if m1 is None and d1raw is None:
        return {}
    d_from_m = daily_from_minutes(m1, ses) if m1 is not None and len(m1) else None
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
            out = resample_intraday(m1, tf, ses)
        else:
            out = resample_daily(daily, tf, ses)
        write(out, path(data_dir, tf, ticker))
        counts[tf] = len(out)
    return counts
