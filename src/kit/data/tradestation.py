"""TradeStation API v3 — READ-ONLY market data client.

This module can only send GET requests to the market-data paths in READ_ONLY_PATHS, plus the
one POST that OAuth needs (the token endpoint on signin.tradestation.com). Any other method or
path raises ReadOnlyViolation before a byte leaves the machine. tests/test_no_orders.py also
fails the build if order-execution paths appear anywhere in the code.

Sources (checked 2026-11-08):
  auth   https://api.tradestation.com/docs/fundamentals/authentication/auth-code
  scopes https://api.tradestation.com/docs/fundamentals/authentication/scopes
  bars   https://api.tradestation.com/docs/specification (GetBars)
         https://api.tradestation.com/docs/fundamentals/rate-limiting/historical-bar
  limits https://api.tradestation.com/docs/fundamentals/rate-limiting/rate-limiting-overview
"""
from __future__ import annotations

import json
import secrets as pysecrets
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Iterator

import httpx
import numpy as np
import pandas as pd

from ..config import TZ, Settings
from . import secrets, store

API = "https://api.tradestation.com"
SIGNIN = "https://signin.tradestation.com"
AUTHORIZE_URL = SIGNIN + "/authorize"
TOKEN_URL = SIGNIN + "/oauth/token"
AUDIENCE = "https://api.tradestation.com"
READ_ONLY_PATHS = (
    "/v3/marketdata/barcharts/",
    "/v3/marketdata/options/expirations/",
    "/v3/marketdata/options/strikes/",
    "/v3/marketdata/stream/options/chains/",
    "/v3/marketdata/symbols/",
)
MAX_BARS_PER_REQUEST = 57_600   # "A single intraday bars request can return a maximum of 57,600 bars"


class ReadOnlyViolation(RuntimeError):
    pass


class NotLoggedIn(RuntimeError):
    pass


def check_request(method: str, url: str) -> None:
    """The guard every request goes through."""
    u = urllib.parse.urlparse(url)
    origin = f"{u.scheme}://{u.netloc}"
    if method.upper() == "POST" and origin == SIGNIN and u.path == "/oauth/token":
        return
    if method.upper() != "GET":
        raise ReadOnlyViolation(f"refused {method} {u.path}: this kit only reads market data")
    if origin not in (API, "https://sim-api.tradestation.com"):
        raise ReadOnlyViolation(f"refused request to {origin}")
    if not u.path.startswith(READ_ONLY_PATHS):
        raise ReadOnlyViolation(f"refused {u.path}: not a market-data path this kit allows")


class TradeStation:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = lambda m: None):
        self.s = settings
        self.http = httpx.Client(transport=transport, timeout=60.0)
        self.sleep = sleep
        self.log = log
        self._access: str | None = None
        self._expires = 0.0
        self._last_call = 0.0

    # ── auth ──────────────────────────────────────────────────────────────
    def _post_token(self, data: dict) -> dict:
        check_request("POST", TOKEN_URL)
        r = self.http.post(TOKEN_URL, data=data, headers={"content-type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            # never echo the body: it can contain token material
            raise NotLoggedIn(f"TradeStation sign-in refused the request (HTTP {r.status_code}). Run `kit login tradestation` again.")
        return r.json()

    def access_token(self) -> str:
        if self._access and time.time() < self._expires - 60:
            return self._access
        cid, csec, rt = (secrets.get(n) for n in ("TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_REFRESH_TOKEN"))
        if not (cid and csec and rt):
            raise NotLoggedIn("Not signed in to TradeStation yet. Run `kit login tradestation`.")
        tok = self._post_token({"grant_type": "refresh_token", "client_id": cid, "client_secret": csec, "refresh_token": rt})
        if tok.get("refresh_token") and tok["refresh_token"] != rt:      # rotating refresh tokens
            secrets.put("TS_REFRESH_TOKEN", tok["refresh_token"])
        self._access = tok["access_token"]
        self._expires = time.time() + float(tok.get("expires_in", 1200))
        return self._access

    # ── requests ──────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        gap = 60.0 / max(1, self.s.ts_requests_per_minute)
        wait = self._last_call + gap - time.monotonic()
        if wait > 0:
            self.sleep(wait)
        self._last_call = time.monotonic()

    def get(self, path: str, params: dict | None = None) -> dict:
        url = API + path
        check_request("GET", url)
        delay = 2.0
        for attempt in range(8):
            self._throttle()
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {self.access_token()}"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and attempt == 0:
                self._access = None
                continue
            if r.status_code == 429 or r.status_code >= 500:
                reset = r.headers.get("X-RateLimit-Reset") or r.headers.get("Retry-After")
                wait = delay
                try:
                    v = float(reset)
                    wait = v - time.time() if v > 1e9 else v       # epoch seconds or seconds-to-wait
                except (TypeError, ValueError):
                    pass
                wait = float(min(max(wait, 1.0), 120.0))
                self.log(f"TradeStation said slow down (HTTP {r.status_code}); waiting {wait:.0f}s")
                self.sleep(wait)
                delay = min(delay * 2, 120.0)
                continue
            raise RuntimeError(f"TradeStation GET {path} failed: HTTP {r.status_code} {r.text[:200]}")
        raise RuntimeError(f"TradeStation GET {path}: still throttled after 8 tries; run `kit fetch` again later (it resumes)")

    def stream(self, path: str, params: dict | None = None, max_seconds: float = 15.0) -> Iterator[dict]:
        """Read a TradeStation HTTP stream (one JSON object per line) until EndSnapshot or timeout."""
        url = API + path
        check_request("GET", url)
        self._throttle()
        t0 = time.monotonic()
        with self.http.stream("GET", url, params=params, headers={"Authorization": f"Bearer {self.access_token()}"}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"TradeStation stream {path} failed: HTTP {r.status_code}")
            for line in r.iter_lines():
                if line.strip():
                    obj = json.loads(line)
                    if obj.get("StreamStatus") == "EndSnapshot":
                        return
                    if "Heartbeat" in obj or "Error" in obj:
                        if "Error" in obj:
                            raise RuntimeError(f"TradeStation stream error: {obj.get('Message', obj['Error'])}")
                        continue
                    yield obj
                if time.monotonic() - t0 > max_seconds:
                    return

    # ── bars ──────────────────────────────────────────────────────────────
    def bars(self, symbol: str, unit: str = "Minute", interval: int = 1,
             firstdate: datetime | None = None, lastdate: datetime | None = None, barsback: int | None = None) -> pd.DataFrame:
        p: dict = {"unit": unit, "interval": interval}
        if barsback:
            p["barsback"] = barsback
        if firstdate:
            p["firstdate"] = firstdate.strftime("%Y-%m-%dT%H:%M:%SZ")
        if lastdate:
            p["lastdate"] = lastdate.strftime("%Y-%m-%dT%H:%M:%SZ")
        js = self.get("/v3/marketdata/barcharts/" + urllib.parse.quote(symbol, safe=""), p)
        return parse_bars(js.get("Bars", []), unit)


def parse_bars(rows: list[dict], unit: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=store.COLS)
    df = pd.DataFrame(rows)
    ts = pd.to_datetime(df["TimeStamp"], utc=True).dt.tz_convert(TZ)
    out = pd.DataFrame({
        "ts": ts,
        "open": pd.to_numeric(df["Open"]), "high": pd.to_numeric(df["High"]),
        "low": pd.to_numeric(df["Low"]), "close": pd.to_numeric(df["Close"]),
        "volume": pd.to_numeric(df.get("TotalVolume", 0)),
    })
    if unit != "Minute":                      # daily+: stamp the session close (16:00 ET) of that date
        out["ts"] = out["ts"].dt.normalize() + pd.Timedelta(hours=16)
    return out.sort_values("ts").reset_index(drop=True)


def detect_open_stamps(m1: pd.DataFrame) -> bool:
    """True if minute bars look stamped at their OPEN (a 09:30 bar exists, no 16:00 bar).
    The kit stores CLOSE times; TradeStation's convention is checked on your data, not assumed."""
    if m1.empty:
        return False
    hm = m1["ts"].dt.hour * 60 + m1["ts"].dt.minute
    return bool((hm == 570).any() and not (hm == 960).any())


# ── fetch with resume ─────────────────────────────────────────────────────────
def fetch_minutes(ts: TradeStation, data_dir: Path, symbol: str, start: str, now: datetime | None = None,
                  window_days: int = 120, log: Callable[[str], None] = print) -> dict:
    """Pull 1-minute bars from `start` to now into raw/1m/<symbol>.parquet. Resumes: only missing
    stretches are requested, and each window is saved as soon as it arrives."""
    now = now or datetime.now(timezone.utc)
    p = store.path(data_dir, "1m", symbol, raw=True)
    cache = store.read(data_dir, "1m", symbol, raw=True)
    start_dt = pd.Timestamp(start, tz="UTC").to_pydatetime()
    jobs = []
    if cache is None or cache.empty:
        jobs.append((start_dt, now))
    else:
        first = cache.ts.min().tz_convert("UTC").to_pydatetime()
        last = cache.ts.max().tz_convert("UTC").to_pydatetime()
        if first - start_dt > timedelta(days=3):
            jobs.append((start_dt, first - timedelta(minutes=1)))
        jobs.append((last + timedelta(minutes=1), now))
    got, requests, earliest_hit, shifted = 0, 0, False, False
    for lo, hi in jobs:
        # newest window first, walking back, so a short history stops early instead of erroring
        cur_hi = hi
        win = timedelta(days=window_days)
        while cur_hi > lo:
            cur_lo = max(lo, cur_hi - win)
            df = ts.bars(symbol, "Minute", 1, firstdate=cur_lo, lastdate=cur_hi)
            requests += 1
            if len(df) >= MAX_BARS_PER_REQUEST and win > timedelta(days=5):
                win = win / 2          # window too big for one request: halve and redo
                continue
            if df.empty:
                if cur_hi < now - timedelta(days=7):
                    earliest_hit = True      # no data this far back: TradeStation's history ends here
                    break
            else:
                if detect_open_stamps(df):
                    df["ts"] = df["ts"] + pd.Timedelta(minutes=1)
                    shifted = True
                # never store a session that has not finished: its daily/4h bars would be partial
                now_et = pd.Timestamp(now).tz_convert(TZ)
                if now_et.hour * 60 + now_et.minute < 16 * 60 + 5:
                    df = df[df["ts"] < now_et.normalize()]
                if df.empty:
                    cur_hi = cur_lo - timedelta(minutes=1)
                    continue
                cache = df if cache is None or cache.empty else pd.concat([cache, df], ignore_index=True)
                store.write(cache, p)
                got += len(df)
                log(f"  {symbol}: {cur_lo:%Y-%m-%d} .. {cur_hi:%Y-%m-%d}  +{len(df):,} bars")
            cur_hi = cur_lo - timedelta(minutes=1)
    cache = store.read(data_dir, "1m", symbol, raw=True)
    return {"symbol": symbol, "new_bars": got, "requests": requests,
            "first": str(cache.ts.min()) if cache is not None and len(cache) else None,
            "last": str(cache.ts.max()) if cache is not None and len(cache) else None,
            "history_ended_early": earliest_hit, "shifted_open_stamps": shifted}


def fetch_daily(ts: TradeStation, data_dir: Path, symbol: str, start: str) -> int:
    df = ts.bars(symbol, "Daily", 1, firstdate=pd.Timestamp(start, tz="UTC").to_pydatetime(),
                 lastdate=datetime.now(timezone.utc))
    if df.empty:
        return 0
    store.write(df, store.path(data_dir, "1D", symbol, raw=True))
    return len(df)


# ── option chain snapshots (forward-only real-quote history) ──────────────────
def snapshot_options(ts: TradeStation, data_dir: Path, underlying: str, n_expirations: int = 4,
                     strike_proximity: int = 5, max_seconds: float = 15.0) -> dict:
    exp = ts.get("/v3/marketdata/options/expirations/" + urllib.parse.quote(underlying, safe=""))
    dates = [e.get("Date") for e in exp.get("Expirations", []) if e.get("Date")][:n_expirations]
    rows = []
    stamp = pd.Timestamp.now(tz=TZ)
    for d in dates:
        exp_param = pd.Timestamp(d).strftime("%m-%d-%Y")
        for obj in ts.stream("/v3/marketdata/stream/options/chains/" + urllib.parse.quote(underlying, safe=""),
                             {"expiration": exp_param, "strikeProximity": strike_proximity}, max_seconds):
            row = {"snapshot_ts": stamp, "underlying": underlying, "expiration": d}
            legs = obj.get("Legs") or [{}]
            leg = legs[0]
            row.update({"symbol": leg.get("Symbol"), "strike": leg.get("StrikePrice"), "type": leg.get("OptionType")})
            for k, v in obj.items():
                if isinstance(v, (int, float, str)) and k not in row:
                    row[k.lower()] = v
            rows.append(row)
    out = pd.DataFrame(rows)
    p = Path(data_dir) / "options_snapshots" / stamp.strftime("%Y-%m-%d") / f"{store.safe(underlying)}_{stamp:%H%M}.parquet"
    if len(out):
        p.parent.mkdir(parents=True, exist_ok=True)
        for c in out.columns:
            if c not in ("snapshot_ts",) and not pd.api.types.is_numeric_dtype(out[c]):
                num = pd.to_numeric(out[c], errors="coerce")
                if num.notna().sum() == out[c].notna().sum():
                    out[c] = num
        out.to_parquet(p, index=False)
    return {"underlying": underlying, "expirations": len(dates), "contracts": len(out), "file": str(p) if len(out) else None}


# ── browser login (authorization code flow, localhost callback) ───────────────
def login(settings: Settings, open_browser: Callable[[str], bool] = webbrowser.open, timeout: float = 300.0,
          transport: httpx.BaseTransport | None = None) -> dict:
    cid, csec = secrets.get("TS_CLIENT_ID"), secrets.get("TS_CLIENT_SECRET")
    if not (cid and csec):
        raise NotLoggedIn("No TradeStation API key stored. Run `kit login tradestation` and enter the key when asked.")
    bad = {"Trade", "OptionSpreads", "Matrix"} & set(settings.ts_scopes.split())
    if bad:
        raise ReadOnlyViolation(f"refusing to request trading scopes {sorted(bad)}: this kit reads market data only")
    port = settings.ts_redirect_port
    redirect = f"http://localhost:{port}"
    state = pysecrets.token_urlsafe(24)
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                got["code"] = q["code"][0]
                msg = "Signed in. You can close this tab and go back to the terminal."
            else:
                got["error"] = q.get("error_description", q.get("error", ["sign-in did not complete"]))[0]
                msg = "Sign-in did not complete: " + got["error"]
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='font-family:system-ui'><h3>{msg}</h3></body></html>".encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), Handler)       # loopback only; closed right after
    th = threading.Thread(target=srv.handle_request, daemon=True)
    th.start()
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": cid, "audience": AUDIENCE, "redirect_uri": redirect,
        "scope": settings.ts_scopes, "state": state})
    open_browser(url)
    th.join(timeout)
    srv.server_close()
    if "code" not in got:
        raise NotLoggedIn(got.get("error", "Timed out waiting for the browser sign-in."))
    client = TradeStation(settings, transport=transport)
    tok = client._post_token({"grant_type": "authorization_code", "client_id": cid, "client_secret": csec,
                              "code": got["code"], "redirect_uri": redirect})
    if not tok.get("refresh_token"):
        raise NotLoggedIn("TradeStation returned no refresh token. Check that the key allows the offline_access scope.")
    where = secrets.put("TS_REFRESH_TOKEN", tok["refresh_token"])
    return {"signed_in": True, "refresh_token_saved_in": where, "scopes": settings.ts_scopes}
