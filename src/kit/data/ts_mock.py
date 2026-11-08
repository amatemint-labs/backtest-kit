"""A stand-in for TradeStation's API, for `kit smoke` and the tests. It answers in the response
shapes TradeStation documents (GetBars `{"Bars": [...]}` with string prices and UTC `TimeStamp`;
option expirations; the chain stream as one JSON object per line). It is NOT a recording of a
live account — nobody's credentials were used to build it.
"""
from __future__ import annotations

import json
import urllib.parse

import httpx
import pandas as pd


class MockTradeStation:
    def __init__(self, minutes: dict[str, pd.DataFrame] | None = None, throttle_first: int = 0):
        self.minutes = minutes or {}
        self.requests: list[tuple[str, str]] = []
        self.throttle_left = throttle_first

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append((req.method, req.url.path))
        if req.url.host == "signin.tradestation.com" and req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "mock-access", "token_type": "Bearer", "expires_in": 1200,
                                             "refresh_token": "mock-refresh", "scope": "openid offline_access MarketData"})
        if self.throttle_left > 0:
            self.throttle_left -= 1
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"Error": "TooManyRequests"})
        p = req.url.path
        q = dict(urllib.parse.parse_qsl(req.url.query.decode()))
        if p.startswith("/v3/marketdata/barcharts/"):
            sym = urllib.parse.unquote(p.rsplit("/", 1)[1])
            df = self.minutes.get(sym)
            if df is None:
                return httpx.Response(404, json={"Error": "NotFound", "Message": f"{sym} not found"})
            ts = df.ts.dt.tz_convert("UTC")
            lo = pd.Timestamp(q["firstdate"]) if "firstdate" in q else ts.min()
            hi = pd.Timestamp(q["lastdate"]) if "lastdate" in q else ts.max()
            lo = lo.tz_localize("UTC") if lo.tzinfo is None else lo
            hi = hi.tz_localize("UTC") if hi.tzinfo is None else hi
            x = df[(ts >= lo) & (ts <= hi)]
            if q.get("unit", "Minute") == "Daily":
                g = x.assign(d=x.ts.dt.normalize()).groupby("d")
                x = pd.DataFrame({"ts": g.ts.last(), "open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                                  "close": g.close.last(), "volume": g.volume.sum()})
            bars = [{"High": f"{r.high:.4f}", "Low": f"{r.low:.4f}", "Open": f"{r.open:.4f}", "Close": f"{r.close:.4f}",
                     "TimeStamp": r.ts.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "TotalVolume": str(int(r.volume)),
                     "BarStatus": "Closed", "IsRealtime": False, "IsEndOfHistory": False} for r in x.itertuples()]
            return httpx.Response(200, json={"Bars": bars})
        if p.startswith("/v3/marketdata/options/expirations/"):
            return httpx.Response(200, json={"Expirations": [{"Date": "2026-11-13T00:00:00Z", "Type": "Weekly"},
                                                             {"Date": "2026-11-20T00:00:00Z", "Type": "Monthly"}]})
        if p.startswith("/v3/marketdata/stream/options/chains/"):
            und = urllib.parse.unquote(p.rsplit("/", 1)[1])
            lines = []
            for k, strike in enumerate((95, 100, 105)):
                for cp in ("C", "P"):
                    lines.append({"Delta": "0.5", "ImpliedVolatility": "0.32", "Bid": f"{2 + k / 10:.2f}", "Ask": f"{2.1 + k / 10:.2f}",
                                  "Last": "2.05", "Volume": "120", "DailyOpenInterest": "900", "Side": "Call" if cp == "C" else "Put",
                                  "Legs": [{"Symbol": f"{und} 261113{cp}{strike}", "StrikePrice": str(strike),
                                            "Expiration": "2026-11-13T00:00:00Z", "OptionType": "Call" if cp == "C" else "Put"}]})
            lines.append({"Heartbeat": 1, "Timestamp": "2026-11-08T15:00:00Z"})
            lines.append({"StreamStatus": "EndSnapshot"})
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
        return httpx.Response(404, json={"Error": "NotFound"})
