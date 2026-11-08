"""FREE data source: Alpaca Market Data API (Basic plan), READ-ONLY.

What it gives (checked 2026-11-08 on docs.alpaca.markets and alpaca.markets/data):
  * free with an Alpaca account (paper accounts get the Basic plan too), API key in headers
  * historical 1-minute US stock bars "Since 2016" from the all-exchange SIP feed, as long as the
    request ends at least 15 minutes ago (free plan) — fine for backtests
  * 200 API calls per minute; up to 10,000 bars per request (pages via next_page_token)
  * options: only "indicative" (not real exchange) data on the free plan, from Feb 2024; no
    historical bid/ask — the kit does not use it
How to get keys: sign up at alpaca.markets -> Paper Trading dashboard -> "API Keys" -> generate.
Then `uv run kit login alpaca` (the keys are stored in Keychain) and `uv run kit fetch --source alpaca`.

This module can only send GET requests to data.alpaca.markets/v2/stocks/bars. Anything else raises
ReadOnlyViolation before it leaves the machine (the trading API is never contacted).
"""
from __future__ import annotations

import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx
import pandas as pd

from ..config import TZ
from . import secrets, store
from .tradestation import ReadOnlyViolation

DATA = "https://data.alpaca.markets"
BARS_PATH = "/v2/stocks/bars"


def check_request(method: str, url: str) -> None:
    u = urllib.parse.urlparse(url)
    if method.upper() != "GET" or f"{u.scheme}://{u.netloc}" != DATA or u.path != BARS_PATH:
        raise ReadOnlyViolation(f"refused {method} {u.netloc}{u.path}: this kit only reads Alpaca stock bars")


class Alpaca:
    def __init__(self, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep,
                 per_minute: int = 150, log: Callable[[str], None] = lambda m: None):
        kid, sec = secrets.get("ALPACA_KEY_ID"), secrets.get("ALPACA_SECRET_KEY")
        if not (kid and sec):
            raise PermissionError("No Alpaca keys stored. Run `kit login alpaca` (free account, Paper Trading -> API Keys).")
        self.headers = {"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec}
        self.http = httpx.Client(transport=transport, timeout=60.0)
        self.sleep, self.gap, self.log, self._last = sleep, 60.0 / per_minute, log, 0.0

    def get_bars(self, symbol: str, start: datetime, end: datetime, adjustment: str = "split") -> pd.DataFrame:
        url = DATA + BARS_PATH
        check_request("GET", url)
        params = {"symbols": symbol, "timeframe": "1Min", "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 10000, "adjustment": adjustment,
                  "feed": "sip", "sort": "asc"}
        rows, token, delay = [], None, 2.0
        while True:
            if token:
                params["page_token"] = token
            wait = self._last + self.gap - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            r = self.http.get(url, params=params, headers=self.headers)
            if r.status_code == 429 or r.status_code >= 500:
                self.log(f"Alpaca said slow down (HTTP {r.status_code}); waiting {delay:.0f}s")
                self.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            if r.status_code in (401, 403):
                raise PermissionError(f"Alpaca refused the keys (HTTP {r.status_code}). Run `kit login alpaca` again.")
            if r.status_code != 200:
                raise RuntimeError(f"Alpaca bars failed: HTTP {r.status_code} {r.text[:200]}")
            js = r.json()
            rows += (js.get("bars") or {}).get(symbol, [])
            token = js.get("next_page_token")
            if not token:
                break
        if not rows:
            return pd.DataFrame(columns=store.COLS)
        df = pd.DataFrame(rows)
        # Alpaca stamps a bar at its START; the kit stores CLOSE times
        ts = pd.to_datetime(df["t"], utc=True) + pd.Timedelta(minutes=1)
        out = pd.DataFrame({"ts": ts.dt.tz_convert(TZ), "open": df["o"], "high": df["h"], "low": df["l"],
                            "close": df["c"], "volume": df["v"]})
        return store.rth(out)


def fetch_minutes(cli: Alpaca, data_dir: Path, symbol: str, start: str, now: datetime | None = None,
                  window_days: int = 30, log: Callable[[str], None] = print) -> dict:
    """1-minute bars from `start` until 20 minutes ago into raw/1m/<symbol>; resumes like the TradeStation fetch."""
    now = now or datetime.now(timezone.utc)
    end_all = now - timedelta(minutes=20)              # the free plan needs SIP requests to end 15+ minutes ago
    p = store.path(data_dir, "1m", symbol, raw=True)
    cache = store.read(data_dir, "1m", symbol, raw=True)
    start_dt = pd.Timestamp(start, tz="UTC").to_pydatetime()
    jobs = [(start_dt, end_all)] if cache is None or cache.empty else []
    if cache is not None and len(cache):
        first, last = cache.ts.min().tz_convert("UTC").to_pydatetime(), cache.ts.max().tz_convert("UTC").to_pydatetime()
        if first - start_dt > timedelta(days=3):
            jobs.append((start_dt, first - timedelta(minutes=1)))
        jobs.append((last, end_all))
    before = 0 if cache is None else len(cache)
    for lo, hi in jobs:
        cur = lo
        while cur < hi:
            nxt = min(hi, cur + timedelta(days=window_days))
            df = cli.get_bars(symbol, cur, nxt)
            now_et = pd.Timestamp(now).tz_convert(TZ)
            if now_et.hour * 60 + now_et.minute < 16 * 60 + 5:
                df = df[df["ts"] < now_et.normalize()]        # never store an unfinished session
            if len(df):
                cache = df if cache is None or cache.empty else pd.concat([cache, df], ignore_index=True)
                store.write(cache, p)
                cache = store.read(data_dir, "1m", symbol, raw=True)
                log(f"  {symbol}: {cur:%Y-%m-%d} .. {nxt:%Y-%m-%d}  +{len(df):,} bars")
            cur = nxt
    cache = store.read(data_dir, "1m", symbol, raw=True)
    got = (0 if cache is None else len(cache)) - before
    return {"symbol": symbol, "new_bars": got, "first": str(cache.ts.min()) if cache is not None and len(cache) else None,
            "last": str(cache.ts.max()) if cache is not None and len(cache) else None}
