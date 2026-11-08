"""Signals (entries = first bar of a run, clear errors, describe) and the free Alpaca source (mocked)."""
import json
import urllib.parse
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd
import pytest

from kit import signals
from kit.data import alpaca, secrets, store
from kit.data.tradestation import ReadOnlyViolation


def _frame():
    return pd.DataFrame({
        "ticker": ["A"] * 5 + ["B"] * 3,
        "period": ["P1"] * 4 + ["P2"] * 4,
        "h1_stoch_k": [10, 12, 50, 15, 11, 10, 12, 60],
        "C_1x": [True, False, False, True, False, True, False, False],
        "C_3x": [False] * 8,
        "C_first": [1, 0, -1, 1, 0, 1, -1, 0],
    })


def test_entries_are_the_first_bar_of_each_run_per_ticker():
    D = _frame()
    ev = signals.evaluate(D, [signals.ExprSignal("low", "C", "h1_stoch_k < 20")])["low"]
    #            A: 10 12 50 15 11 | B: 10 12 60
    assert ev["fires"].tolist() == [True, True, False, True, True, True, True, False]
    assert ev["entries"].tolist() == [True, False, False, True, False, True, False, False]   # B starts a new run


def test_unknown_column_gives_suggestions():
    with pytest.raises(KeyError, match="h1_stoch_k"):
        signals.evaluate(_frame(), [signals.ExprSignal("x", "C", "h1_stoch_kk < 20")])


def test_describe_counts_and_lift():
    D = _frame()
    ev = signals.evaluate(D, [signals.ExprSignal("low", "C", "h1_stoch_k < 20")])
    t = signals.describe(D, ev, {"P1": 1.0, "P2": 1.0})
    p1 = t[t.half == "P1"].iloc[0]
    assert p1.entries == 2 and p1.C_1x_rate_pct == 100.0 and p1.C_1x_lift == 2.0      # base P1 = 2/4


def test_plugin_signals_are_opt_in():
    assert all(s.source == "study.toml" for s in signals.load({}))           # example plug-in not loaded by default
    loaded = signals.load({"use_signals": ["rsi_hook"]})
    assert [s.name for s in loaded] == ["rsi_hook"]
    with pytest.raises(KeyError):
        signals.load({"use_signals": ["does_not_exist"]})


# ── Alpaca (free) ─────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def alpaca_keys():
    secrets._MEMORY.clear()
    secrets.put("ALPACA_KEY_ID", "k")
    secrets.put("ALPACA_SECRET_KEY", "s")
    yield
    secrets._MEMORY.clear()


def _mock(minutes: pd.DataFrame, page=500, throttle=1):
    state = {"n": 0, "throttle": throttle, "seen": []}

    def handler(req: httpx.Request):
        state["seen"].append((req.method, str(req.url.host), req.url.path))
        assert req.headers["APCA-API-KEY-ID"] == "k"
        if state["throttle"]:
            state["throttle"] -= 1
            return httpx.Response(429)
        q = dict(urllib.parse.parse_qsl(req.url.query.decode()))
        lo, hi = pd.Timestamp(q["start"]), pd.Timestamp(q["end"])
        start_ts = minutes.ts.dt.tz_convert("UTC") - pd.Timedelta(minutes=1)          # Alpaca stamps bar starts
        x = minutes[(start_ts >= lo) & (start_ts <= hi)]
        off = int(q.get("page_token", 0))
        chunk = x.iloc[off:off + page]
        bars = [{"t": (r.ts - pd.Timedelta(minutes=1)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": int(r.volume), "n": 10, "vw": r.close}
                for r in chunk.itertuples()]
        nxt = str(off + page) if off + page < len(x) else None
        return httpx.Response(200, json={"bars": {q["symbols"]: bars}, "next_page_token": nxt})
    return httpx.MockTransport(handler), state


def test_alpaca_fetch_pages_shifts_and_resumes(tmp_path):
    from kit.data import synthetic
    m = synthetic.make_minutes("2026-04-01", "2026-04-30")["SYNB"]
    m = m[m.ts >= pd.Timestamp("2026-04-02", tz="America/New_York")].reset_index(drop=True)
    tr, st = _mock(m)
    cli = alpaca.Alpaca(transport=tr, sleep=lambda s: None, per_minute=100000)
    now = datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc)
    r = alpaca.fetch_minutes(cli, tmp_path, "SYNB", "2026-04-01", now=now, window_days=10, log=lambda x: None)
    got = store.read(tmp_path, "1m", "SYNB", raw=True)
    assert len(got) == len(m) and r["new_bars"] == len(m)
    assert (got.ts.values == m.ts.values).all()            # start stamps were shifted to close stamps
    r2 = alpaca.fetch_minutes(cli, tmp_path, "SYNB", "2026-04-01", now=now, window_days=10, log=lambda x: None)
    assert r2["new_bars"] == 0
    assert all(meth == "GET" and host == "data.alpaca.markets" and path == "/v2/stocks/bars" for meth, host, path in st["seen"])


@pytest.mark.parametrize("method,url", [
    ("POST", "https://data.alpaca.markets/v2/stocks/bars"),
    ("GET", "https://paper-api.alpaca.markets/v2/account"),
    ("GET", "https://api.alpaca.markets/v2/positions"),
    ("GET", "https://data.alpaca.markets/v2/stocks/quotes"),
])
def test_alpaca_guard_refuses(method, url):
    with pytest.raises(ReadOnlyViolation):
        alpaca.check_request(method, url)


def test_alpaca_needs_keys():
    secrets._MEMORY.clear()
    with pytest.raises(PermissionError):
        alpaca.Alpaca()
