"""TradingView import + match-check, and the census / option pricing rules."""
import numpy as np
import pandas as pd
import pytest

from kit.data import store, tradingview
from kit.ind import compute
from kit.method import census, options


def _fake_tv_export(synthetic_store, path, tamper=False):
    """What a TradingView export looks like: bar OPEN times as UNIX seconds, OHLC, then plot columns,
    with values as TradingView paints history (lookahead on the higher timeframe)."""
    get = lambda t: store.read(synthetic_store, t, "SYNC")
    x = compute(get("1h"), "1h", get, mode="tv")
    opn = x.ts - pd.Timedelta(hours=1)
    opn = opn.where(x.ts.dt.minute != 0, x.ts - pd.Timedelta(minutes=30))      # the 15:30-16:00 half bar
    df = pd.DataFrame({"time": (opn.dt.tz_convert("UTC") - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1), "open": x.open, "high": x.high,
                       "low": x.low, "close": x.close, "%K": x.st_k, "%D": x.st_d, "RSI": x.rsi_value,
                       "MACD": x.macd_line, "Signal": x.macd_signal, "Histogram": x.macd_hist, "Volume": x.volume})
    if tamper:
        df["RSI"] = df["RSI"] + 2.0
    df.to_csv(path, index=False)


def test_match_check_passes_on_true_values(synthetic_store, tmp_path):
    p = tmp_path / "BATS_SYNC, 60_ab12.csv"
    _fake_tv_export(synthetic_store, p)
    r = tradingview.match_check(p, synthetic_store)
    assert r["ticker"] == "SYNC" and r["tf"] == "1h" and r["warm_source"] == "store"
    st = {t["reading"]: t["status"] for t in r["table"]}
    assert st == {"st_k": "MATCH", "st_d": "MATCH", "rsi_value": "MATCH", "macd_line": "MATCH", "macd_signal": "MATCH",
                  "macd_hist": "MATCH"}, r["table"]


def test_match_check_catches_a_mismatch(synthetic_store, tmp_path):
    p = tmp_path / "BATS_SYNC, 60_cd34.csv"
    _fake_tv_export(synthetic_store, p, tamper=True)
    r = tradingview.match_check(p, synthetic_store)
    st = {t["reading"]: t["status"] for t in r["table"]}
    assert st["rsi_value"] == "CHECK" and r["worst"]["rsi_value"][0]["abs_diff"] == pytest.approx(2.0, abs=1e-3)


def test_import_tv(synthetic_store, tmp_path):
    p = tmp_path / "BATS_SYNC, 60_ef56.csv"
    _fake_tv_export(synthetic_store, p)
    r = tradingview.import_csv(p, tmp_path / "data")
    assert r["tf"] == "1h" and r["ticker"] == "SYNC" and set(r["indicator_columns"]) >= {"%K", "RSI", "MACD"}


def test_expiry_rule_is_fixed_at_entry():
    d = np.array(["2026-11-09", "2026-11-12", "2026-11-13"], dtype="datetime64[D]")     # Mon, Thu, Fri
    assert options.expiry_after(d, 3).astype(str).tolist() == ["2026-11-13", "2026-11-20", "2026-11-20"]


def test_black_scholes_sanity():
    c = options.bs(100, 100, 30 / 365, 0.3, True)
    assert 3.3 < float(c) < 3.8           # ~0.4 * S * sigma * sqrt(T) plus carry
    p = options.bs(100, 100, 30 / 365, 0.3, False)
    assert float(c) > float(p)


def test_zigzag_hand_series():
    hi = np.array([10, 11, 12, 11, 9, 8, 9, 11, 13, 12], float)
    lo = hi - 0.5
    atr = np.full_like(hi, 1.0)
    piv = census.zigzag(hi, lo, atr, 2.0)
    # bar 2 (high 12) confirms the low at bar 0; bar 4 confirms the high at bar 2; bar 7 confirms the low at bar 5.
    # The high at bar 8 (13) is never confirmed (price only gives back 1.5 ATR), so it is not a pivot yet.
    assert piv == [(0, -1), (2, 1), (5, -1)]


def test_legs_have_entry_known_expiry(synthetic_store):
    d = store.read(synthetic_store, "1D", "SYNA")
    h = store.read(synthetic_store, "1h", "SYNA")
    L = census.legs_for(h, d, "SYNA", "1h")
    assert len(L) > 20
    assert (L.expiry.dt.day_of_week == 4).all()
    # expiry depends only on the entry date and the leg size, never on the exit
    for k, n in census.EXPIRY_SESSIONS.items():
        x = L[L.k_atr == k]
        if len(x):
            exp = options.expiry_after(x.entry_ts.dt.tz_localize(None).dt.normalize().to_numpy().astype("datetime64[D]"), n)
            assert (x.expiry.to_numpy().astype("datetime64[D]") == exp).all()
    assert (L.mult > 0).all()
