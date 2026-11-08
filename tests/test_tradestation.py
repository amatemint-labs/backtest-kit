"""TradeStation client against recorded-shape mock responses (no network, no real account)."""
import json
import socket
import threading
import urllib.parse
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest

from kit import config
from kit.data import secrets, store, tradestation as ts
from kit.data.ts_mock import MockTradeStation

FX = Path(__file__).parent / "fixtures" / "tradestation"


@pytest.fixture
def settings(tmp_path):
    s = config.Settings(root=tmp_path, data_dir=tmp_path / "data", studies_dir=tmp_path / "studies")
    return replace(s, ts_requests_per_minute=100000)


@pytest.fixture(autouse=True)
def creds():
    secrets._MEMORY.clear()
    for n, v in (("TS_CLIENT_ID", "id"), ("TS_CLIENT_SECRET", "sec"), ("TS_REFRESH_TOKEN", "rt-1")):
        secrets.put(n, v)
    yield
    secrets._MEMORY.clear()


def test_parse_recorded_barchart_response():
    js = json.loads((FX / "barcharts_minute.json").read_text())
    df = ts.parse_bars(js["Bars"], "Minute")
    assert list(df.columns) == store.COLS
    assert df.ts.iloc[0] == pd.Timestamp("2026-11-06 09:31", tz="America/New_York")   # 14:31Z = 09:31 ET
    assert df.close.iloc[-1] == pytest.approx(497.05) and df.volume.iloc[0] == 812345
    assert not ts.detect_open_stamps(df)


def test_parse_daily_stamps_session_close():
    js = json.loads((FX / "barcharts_daily.json").read_text())
    df = ts.parse_bars(js["Bars"], "Daily")
    assert (df.ts.dt.hour == 16).all() and df.ts.iloc[0].date().isoformat() == "2026-11-05"


def test_open_stamped_minutes_are_detected():
    t = pd.date_range("2026-11-06 09:30", "2026-11-06 15:59", freq="1min", tz="America/New_York")
    df = pd.DataFrame({"ts": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1})
    assert ts.detect_open_stamps(df)


def _minutes(days=12):
    from kit.data import synthetic
    m = synthetic.make_minutes("2026-04-01", "2026-04-30")["SYNA"]
    return m[m.ts >= pd.Timestamp("2026-04-02", tz="America/New_York")].reset_index(drop=True)


def test_fetch_resumes_and_backs_off(settings):
    m1 = _minutes()
    mock = MockTradeStation({"SYNA": m1}, throttle_first=2)
    slept = []
    cli = ts.TradeStation(settings, transport=mock.transport(), sleep=slept.append)
    now = datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc)
    r = ts.fetch_minutes(cli, settings.data_dir, "SYNA", "2026-04-01", now=now, window_days=7, log=lambda m: None)
    got = store.read(settings.data_dir, "1m", "SYNA", raw=True)
    assert len(got) == len(m1) and r["new_bars"] == len(m1)
    assert any(x >= 1 for x in slept), "a 429 must make the client wait"
    n_req = len(mock.requests)
    r2 = ts.fetch_minutes(cli, settings.data_dir, "SYNA", "2026-04-01", now=now, window_days=7, log=lambda m: None)
    assert r2["new_bars"] == 0 and len(mock.requests) - n_req <= 2     # only the stretch after the last bar
    # simulate a crash halfway: drop the newest week, fetch again -> only that week comes back
    store.write(got[got.ts < pd.Timestamp("2026-04-23", tz="America/New_York")], store.path(settings.data_dir, "1m", "SYNA", raw=True))
    r3 = ts.fetch_minutes(cli, settings.data_dir, "SYNA", "2026-04-01", now=now, window_days=7, log=lambda m: None)
    assert len(store.read(settings.data_dir, "1m", "SYNA", raw=True)) == len(m1) and 0 < r3["new_bars"] < len(m1)
    assert all(m == "GET" or p == "/oauth/token" for m, p in mock.requests)


def test_unfinished_session_is_not_stored(settings):
    m1 = _minutes()
    mock = MockTradeStation({"SYNA": m1})
    cli = ts.TradeStation(settings, transport=mock.transport(), sleep=lambda x: None)
    now = datetime(2026, 4, 30, 17, 0, tzinfo=timezone.utc)    # 13:00 ET on the 30th: session still open
    ts.fetch_minutes(cli, settings.data_dir, "SYNA", "2026-04-01", now=now, window_days=40, log=lambda m: None)
    got = store.read(settings.data_dir, "1m", "SYNA", raw=True)
    assert got.ts.max() < pd.Timestamp("2026-04-30", tz="America/New_York")


def test_rotating_refresh_token_is_saved(settings):
    def handler(req):
        return httpx.Response(200, json={"access_token": "a", "expires_in": 1200, "refresh_token": "rt-2"})
    cli = ts.TradeStation(settings, transport=httpx.MockTransport(handler))
    assert cli.access_token() == "a"
    assert secrets.get("TS_REFRESH_TOKEN") == "rt-2"


def test_snapshot_options_from_stream(settings):
    mock = MockTradeStation({})
    cli = ts.TradeStation(settings, transport=mock.transport(), sleep=lambda x: None)
    r = ts.snapshot_options(cli, settings.data_dir, "SYNA", n_expirations=1)
    assert r["contracts"] == 6
    df = pd.read_parquet(r["file"])
    assert {"symbol", "strike", "bid", "ask"} <= set(df.columns)
    assert pd.api.types.is_numeric_dtype(df["bid"])


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_browser_login_flow_stores_refresh_token(settings):
    secrets.delete("TS_REFRESH_TOKEN")
    s = replace(settings, ts_redirect_port=_free_port())
    seen = {}

    def fake_browser(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        seen.update(q)
        # what TradeStation does after the user signs in: redirect to localhost with a code
        threading.Timer(0.2, lambda: urllib.request.urlopen(f"{q['redirect_uri']}/?code=abc&state={q['state']}").read()).start()
        return True

    def token(req):
        body = dict(urllib.parse.parse_qsl(req.content.decode()))
        assert body["grant_type"] == "authorization_code" and body["code"] == "abc"
        return httpx.Response(200, json={"access_token": "a", "expires_in": 1200, "refresh_token": "rt-new"})

    r = ts.login(s, open_browser=fake_browser, timeout=10, transport=httpx.MockTransport(token))
    assert r["signed_in"] and secrets.get("TS_REFRESH_TOKEN") == "rt-new"
    assert seen["scope"] == "openid offline_access MarketData" and seen["audience"] == "https://api.tradestation.com"
    assert seen["redirect_uri"] == f"http://localhost:{s.ts_redirect_port}"
