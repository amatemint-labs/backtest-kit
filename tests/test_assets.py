"""Futures and crypto: sessions, bar building, pricing, data sources, and no lookahead."""
import urllib.parse
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd
import pytest

from kit import assets
from kit.assets import SESSIONS, Instrument
from kit.data import alpaca, secrets, store, synthetic, tradestation, tradingview
from kit.data.tradestation import ReadOnlyViolation

NY = "America/New_York"


def ts(*s):
    return pd.Series(pd.to_datetime(list(s))).dt.tz_localize(NY)


# ── symbols → asset class ─────────────────────────────────────────────────────
@pytest.mark.parametrize("sym,asset,mult", [
    ("NVDA", "stock", 1), ("SPY", "stock", 1), ("BTC/USD", "crypto", 1), ("ETH-USD", "crypto", 1),
    ("@ES", "future", 50), ("ESZ26", "future", 50), ("ES.c.0", "future", 50), ("@MNQ", "future", 2),
    ("CLF27", "future", 1000), ("GC", "stock", 1),     # a bare root is ambiguous: needs @ or --asset future
])
def test_infer(sym, asset, mult):
    i = assets.infer(sym)
    assert (i.asset, i.multiplier) == (asset, mult)


def test_make_and_lookup(tmp_path):
    i = assets.make("GC", "future")
    assert i.multiplier == 100
    assets.save(tmp_path, i)
    assert assets.lookup(tmp_path, "GC") == i
    assert assets.make("MYCONTRACT", "future", 12.5).multiplier == 12.5


# ── sessions ──────────────────────────────────────────────────────────────────
def test_cme_trade_date_and_minute():
    ses = SESSIONS["cme_globex"]
    # Sunday 18:01 opens Monday's session; Monday 17:00 closes it; Monday 18:01 is Tuesday's
    t = ts("2026-03-01 18:01", "2026-03-02 17:00", "2026-03-02 18:01", "2026-03-06 17:00")
    assert list(ses.trade_date(t).dt.strftime("%a %m-%d")) == ["Mon 03-02", "Mon 03-02", "Tue 03-03", "Fri 03-06"]
    assert list(ses.minute_of_session(t)) == [1, 1380, 1, 1380]
    assert ses.in_session(ts("2026-03-02 17:30")).tolist() == [False]          # the daily break


def test_cme_session_across_dst():
    # US clocks moved forward on Sunday 2026-03-08 at 02:00, while CME was closed
    ses = SESSIONS["cme_globex"]
    t = ts("2026-03-08 18:01", "2026-03-09 17:00")
    assert list(ses.minute_of_session(t)) == [1, 1380]


def test_crypto_day_is_utc():
    ses = SESSIONS["crypto"]
    t = pd.Series(pd.to_datetime(["2026-07-04 00:01", "2026-07-05 00:00"])).dt.tz_localize("UTC").dt.tz_convert(NY)
    assert list(ses.trade_date(t).dt.strftime("%Y-%m-%d")) == ["2026-07-04", "2026-07-04"]
    assert ses.days_per_year == 365 and SESSIONS["us_equity"].days_per_year == 252


@pytest.fixture(scope="module")
def other_store(tmp_path_factory):
    d = tmp_path_factory.mktemp("other")
    for tk, (m1, inst) in synthetic.make_other("2026-02-23", "2026-03-20").items():
        assets.save(d, inst)
        store.write(m1, store.path(d, "1m", tk, raw=True))
        store.build_timeframes(d, tk, ["15m", "1h", "4h", "1D"])
    return d


def test_futures_bars_follow_the_cme_session(other_store):
    ses = SESSIONS["cme_globex"]
    h = store.read(other_store, "1h", "SYNFUT")
    days = ses.trade_date(h.ts)
    assert (h.groupby(days.to_numpy()).size() == 23).all()
    assert h.ts.iloc[0].strftime("%a %H:%M") == "Sun 19:00"                  # first bar of Monday's session
    four = store.read(other_store, "4h", "SYNFUT")
    assert sorted(set(four.ts.dt.strftime("%H:%M"))) == ["02:00", "06:00", "10:00", "14:00", "17:00", "22:00"]
    d1 = store.read(other_store, "1D", "SYNFUT")
    assert set(d1.ts.dt.strftime("%H:%M")) == {"17:00"} and set(d1.ts.dt.day_of_week) <= {0, 1, 2, 3, 4}
    # the daily bar's open is the Sunday/evening open, its close the 17:00 close
    m1 = store.read(other_store, "1m", "SYNFUT", raw=True)
    first = m1[ses.trade_date(m1.ts) == ses.trade_date(d1.ts.iloc[:1]).iloc[0]]
    assert d1.open.iloc[0] == first.open.iloc[0] and d1.close.iloc[0] == first.close.iloc[-1]


def test_crypto_bars_every_day(other_store):
    h = store.read(other_store, "1h", "SYNCOIN")
    d1 = store.read(other_store, "1D", "SYNCOIN")
    assert h.ts.dt.day_of_week.nunique() == 7
    assert set(d1.ts.dt.tz_convert("UTC").dt.strftime("%H:%M")) == {"00:00"}
    assert len(d1) == 26                                                      # 2026-02-23 .. 03-20, every day


def test_drop_unfinished_per_session():
    ses = SESSIONS["cme_globex"]
    df = pd.DataFrame({"ts": ts("2026-03-02 16:59", "2026-03-02 18:01", "2026-03-03 09:00"),
                       "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    now = pd.Timestamp("2026-03-03 10:00", tz=NY)
    kept = store.drop_unfinished(df, ses, now)
    assert list(kept.ts.dt.strftime("%m-%d %H:%M")) == ["03-02 16:59"]         # Tuesday's session is still open


# ── no lookahead on the new sessions ─────────────────────────────────────────
@pytest.mark.parametrize("tk", ["SYNFUT", "SYNCOIN"])
def test_no_lookahead_futures_crypto(other_store, tk):
    from kit.ind import compute
    from kit.method import snapshot
    bars = {tf: store.read(other_store, tf, tk) for tf in ("1h", "4h", "1D", "15m", "1W", "2D")}
    cut = bars["1h"].ts.iloc[len(bars["1h"]) * 2 // 3]
    rs = np.random.default_rng(3)
    pert = {}
    for tf, b in bars.items():
        b2 = b.copy()
        late = b2.ts > cut
        f = np.exp(rs.normal(0, 0.05, late.sum()))
        for c in ("open", "high", "low", "close"):
            b2.loc[late, c] = b2.loc[late, c] * f
        pert[tf] = b2
    a = snapshot.tf_feats(compute(bars["1h"], "1h", lambda tf: bars[tf]), "h1_")
    b = snapshot.tf_feats(compute(pert["1h"], "1h", lambda tf: pert[tf]), "h1_")
    early = a.ts <= cut
    num = [c for c in a.columns if c != "ts" and pd.api.types.is_numeric_dtype(a[c])]
    assert np.allclose(a.loc[early, num].to_numpy(float), b.loc[early, num].to_numpy(float), equal_nan=True)


# ── pricing the instrument itself ─────────────────────────────────────────────
def test_underlying_sim_and_trade_log():
    from kit.method import snapshot, tradecheck
    # long at 100, rallies to 110, then falls through the 0.75 x 4 = 3 point trail -> exit at 107
    c = np.array([100, 104, 108, 110, 109, 106, 105.0])
    F = pd.DataFrame({"ts": pd.date_range("2026-03-02 19:00", periods=7, freq="h", tz=NY), "open": np.r_[c[0], c[:-1]], "high": c,
                      "low": c, "close": c, "d_atr": 4.0, "date": pd.Timestamp("2026-03-03"), "ticker": "XF",
                      "period": "P1", "asset": "future", "multiplier": 50.0})
    F["low"] = F.close
    jend = np.full(7, 6)
    ret, hold, _, cens, jx, px, why = snapshot.sim(F, "C", 0.75, jend, None, 0.75, detail=True)
    assert px[0] == 107 and jx[0] == 5 and why[0] == 1 and not cens[0]
    assert ret[0] == pytest.approx(0.07)
    # the trade check turns that into points, ATRs and dollars per contract
    for side in ("C", "P"):
        r_, h_, _, cz = snapshot.sim(F, side, 0.75, jend, None, 0.75)
        F[f"{side}_t075_ret"], F[f"{side}_t075_hold"], F[f"{side}_t075_censored"] = r_, h_, cz
    F["grade_C_2atr"] = ["A", "D", "D", "D", "D", "D", "D"]
    pr = {"label": "C_2atr", "grades": "A", "trail_k": "0.75", "exhaustion": "no", "signal": "", "same_day": "no"}
    out = tradecheck.run(F, pr, {}, None, "underlying")
    t = out["trades"].iloc[0]
    assert (t.points, t.dollars_per_unit, t.r_atr, t.side) == (7.0, 350.0, 1.75, "long")
    assert t.exit_reason == "momentum trail"


def test_options_refused_for_futures(other_store):
    from kit.method import snapshot
    with pytest.raises(ValueError, match="options are modelled for stocks only"):
        snapshot.build_intraday(other_store, "SYNFUT", (None, None), "closed", trade_as="options")


def test_prereg_labels_follow_trade_as():
    from kit.method import tradecheck
    p = {"idea": "x", "entry": "x", "exit": "x", "measure": "x", "pass_mark": "x", "trail_k": "0.75", "label": "C_2atr"}
    assert tradecheck.prereg_problems(p, "underlying") == []
    assert any("label" in x for x in tradecheck.prereg_problems(p, "options"))


# ── data sources ──────────────────────────────────────────────────────────────
def test_alpaca_crypto_without_keys(tmp_path):
    secrets._MEMORY.clear()
    m1, _ = synthetic.make_other("2026-03-02", "2026-03-04")["SYNCOIN"]
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, "APCA-API-KEY-ID" in req.headers))
        q = dict(urllib.parse.parse_qsl(req.url.query.decode()))
        assert "feed" not in q and "adjustment" not in q
        lo, hi = pd.Timestamp(q["start"]), pd.Timestamp(q["end"])
        start = m1.ts.dt.tz_convert("UTC") - pd.Timedelta(minutes=1)
        x = m1[(start >= lo) & (start <= hi)]
        bars = [{"t": (r.ts - pd.Timedelta(minutes=1)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume} for r in x.itertuples()]
        return httpx.Response(200, json={"bars": {q["symbols"]: bars}, "next_page_token": None})

    cli = alpaca.Alpaca(transport=httpx.MockTransport(handler), sleep=lambda s: None, per_minute=100000, keys_required=False)
    now = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    r = alpaca.fetch_minutes(cli, tmp_path, "SYNCOIN", "2026-03-02", now=now, log=lambda x: None, asset="crypto")
    got = store.read(tmp_path, "1m", "SYNCOIN", raw=True)
    assert r["new_bars"] == len(m1) == len(got) == 3 * 1440
    assert all(meth == "GET" and path == alpaca.CRYPTO_BARS_PATH and not keyed for meth, path, keyed in seen)


@pytest.mark.parametrize("method,url", [
    ("POST", "https://data.alpaca.markets/v1beta3/crypto/us/bars"),
    ("GET", "https://data.alpaca.markets/v1beta3/crypto/us/orders"),
    ("GET", "https://paper-api.alpaca.markets/v2/orders"),
])
def test_alpaca_crypto_guard(method, url):
    with pytest.raises(ReadOnlyViolation):
        alpaca.check_request(method, url)


def test_tradestation_futures_stamps():
    ses = SESSIONS["cme_globex"]
    open_stamped = pd.DataFrame({"ts": ts("2026-03-01 18:00", "2026-03-01 18:01", "2026-03-02 16:59")})
    close_stamped = pd.DataFrame({"ts": ts("2026-03-01 18:01", "2026-03-02 16:59", "2026-03-02 17:00")})
    assert tradestation.detect_open_stamps(open_stamped, ses)
    assert not tradestation.detect_open_stamps(close_stamped, ses)
    daily = tradestation.parse_bars([{"TimeStamp": "2026-03-02T22:00:00Z", "Open": 1, "High": 2, "Low": 0.5, "Close": 1.5,
                                      "TotalVolume": 10}], "Daily", ses)
    assert daily.ts.iloc[0] == pd.Timestamp("2026-03-02 17:00", tz=NY)


def test_tradingview_futures_bars_end_at_the_session_close():
    raw = pd.DataFrame({"ts_raw": ts("2026-03-02 16:00", "2026-03-02 18:00")})
    out = tradingview.to_close_stamps(raw, "1h", SESSIONS["cme_globex"])
    assert list(out.ts.dt.strftime("%m-%d %H:%M")) == ["03-02 17:00", "03-02 19:00"]
    w = tradingview.to_close_stamps(pd.DataFrame({"ts_raw": ts("2026-03-02 00:00")}), "1W", SESSIONS["crypto"])
    assert w.ts.iloc[0].tz_convert("UTC") == pd.Timestamp("2026-03-09 00:00", tz="UTC")   # Sunday's UTC close
