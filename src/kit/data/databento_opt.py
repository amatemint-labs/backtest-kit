"""OPTIONAL, PAID: Databento for deeper minute history (and, later, real option quotes).

Install the extra:  uv sync --extra databento
Store your key:     the kit reads DATABENTO_API_KEY from Keychain / environment / .env.
Use:                kit fetch --source databento --tickers SPY,NVDA --start 2023-04-01

Facts checked 2026-11-08 on databento.com (pay-as-you-go, new users get free credits):
  EQUS.MINI   US equities, schemas incl. ohlcv-1m, available from 2023-03-28
  OPRA.PILLAR US options, schemas incl. cbbo-1m / tcbbo / ohlcv-1m, available from 2013-04-01
UNVERIFIED here (no key was used to build this): the exact DataFrame layout of `to_df()` for
your client version and the cost of a given request. ALWAYS check the cost first:
`client.metadata.get_cost(...)` — this module prints it and asks before downloading.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..config import TZ
from . import secrets, store

DATASET = "EQUS.MINI"


def fetch_minutes(data_dir: Path, symbol: str, start: str, end: str | None = None, confirm=input, log=print) -> dict:
    try:
        import databento as db
    except ImportError as e:
        raise RuntimeError("Databento is optional: run `uv sync --extra databento` first.") from e
    key = secrets.get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError("No DATABENTO_API_KEY stored (Keychain, environment, or .env).")
    client = db.Historical(key)
    end = end or pd.Timestamp.now(tz="UTC").normalize().strftime("%Y-%m-%d")
    q = dict(dataset=DATASET, schema="ohlcv-1m", symbols=[symbol], start=start, end=end)
    cost = client.metadata.get_cost(**q)
    log(f"Databento quote for {symbol} {start}..{end}: ${cost:,.2f}")
    if cost > 0 and confirm(f"Download for ${cost:,.2f}? Type yes: ").strip().lower() != "yes":
        return {"symbol": symbol, "downloaded": 0, "cost_usd": cost, "skipped": True}
    df = client.timeseries.get_range(**q).to_df().reset_index()
    t = pd.to_datetime(df["ts_event"], utc=True) + pd.Timedelta(minutes=1)     # bar START -> close stamp
    out = pd.DataFrame({"ts": t.dt.tz_convert(TZ), "open": df["open"], "high": df["high"], "low": df["low"],
                        "close": df["close"], "volume": df["volume"]})
    out = store.rth(out)
    old = store.read(data_dir, "1m", symbol, raw=True)
    if old is not None:
        out = pd.concat([out, old], ignore_index=True)       # TradeStation rows win on overlap (kept last)
    store.write(out, store.path(data_dir, "1m", symbol, raw=True))
    return {"symbol": symbol, "downloaded": len(df), "cost_usd": cost}
