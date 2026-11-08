"""Pine built-ins against hand-checked values, and the bundled indicators against independent
textbook implementations written with plain pandas (no shared code)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kit.ind import pine

FX = json.loads((Path(__file__).parent / "fixtures" / "hand_checked.json").read_text())


def _eq(got, exp):
    exp = np.array([np.nan if v is None else v for v in exp], float)
    np.testing.assert_allclose(np.asarray(got, float), exp, atol=1e-9, equal_nan=True)


def test_ema_rma_stoch_tr_hand_checked():
    _eq(pine.ema(FX["ema_sma_seed"]["x"], 3), FX["ema_sma_seed"]["expected"])
    _eq(pine.ema(FX["ema_first_seed"]["x"], 3, seed="first"), FX["ema_first_seed"]["expected"])
    _eq(pine.rma(FX["rma"]["x"], 2), FX["rma"]["expected"])
    s = FX["stoch"]
    _eq(pine.stoch(s["close"], s["high"], s["low"], s["length"]), s["expected"])
    t = FX["true_range"]
    _eq(pine.tr(t["high"], t["low"], t["close"]), t["expected"])


def test_crossover_rules():
    a = np.array([1.0, 3.0, 3.0, 1.0])
    assert pine.crossover(a, 2.0).tolist() == [False, True, False, False]
    assert pine.crossunder(a, 2.0).tolist() == [False, False, False, True]


def _bars(n=2000, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    h = c * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = c * (1 - np.abs(rng.normal(0, 0.004, n)))
    ts = pd.date_range("2024-01-02 10:30", periods=n, freq="1h", tz="America/New_York")
    return pd.DataFrame({"ts": ts, "open": c, "high": h, "low": l, "close": c, "volume": 1000.0})


def test_stochastic_matches_textbook():
    from kit.ind.builtin import Stochastic
    b = _bars()
    out = Stochastic().compute(b, None)
    ll, hh = b.low.rolling(14).min(), b.high.rolling(14).max()
    k = 100 * (b.close - ll) / (hh - ll)
    d = k.rolling(3).mean()
    np.testing.assert_allclose(out["st_k"], k, equal_nan=True, rtol=1e-12)
    np.testing.assert_allclose(out["st_d"], d, equal_nan=True, rtol=1e-12)


def test_rsi_matches_wilder_after_warmup():
    from kit.ind.builtin import Rsi
    b = _bars()
    got = Rsi().compute(b, None)["rsi_value"]
    ch = b.close.diff()
    up = ch.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    ref = 100 - 100 / (1 + up / dn)
    np.testing.assert_allclose(got[500:], ref.to_numpy()[500:], rtol=1e-6)        # seeds differ; converge


def test_macd_matches_textbook_after_warmup():
    from kit.ind import pine as P
    b = _bars()
    m, s, h = P.macd(b.close, 12, 26, 9)
    e12 = b.close.ewm(span=12, adjust=False).mean()
    e26 = b.close.ewm(span=26, adjust=False).mean()
    ref = e12 - e26
    sig = ref.ewm(span=9, adjust=False).mean()
    np.testing.assert_allclose(m[500:], ref.to_numpy()[500:], rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(h[500:], (ref - sig).to_numpy()[500:], rtol=1e-5, atol=1e-8)


def test_atr_trail_matches_reference():
    b = _bars(800, 5)
    c, h, l = b.close.to_numpy(), b.high.to_numpy(), b.low.to_numpy()
    atr = pine.ema(pine.tr(h, l, c), 10)
    got = pine.atr_trail(c, atr, 3.1)
    ref = []
    for i in range(len(c)):
        prev = ref[-1] if ref else float("nan")
        if np.isnan(prev):
            ref.append(c[i]); continue
        ls, ss = c[i] - 3.1 * atr[i], c[i] + 3.1 * atr[i]
        if c[i] > prev and c[i - 1] > prev:
            ref.append(max(prev, ls) if not np.isnan(ls) else float("nan"))
        elif c[i] < prev and c[i - 1] < prev:
            ref.append(min(prev, ss) if not np.isnan(ss) else float("nan"))
        else:
            ref.append(ls if c[i] > prev else ss)
    np.testing.assert_allclose(got, np.array(ref), equal_nan=True)


def test_bundled_indicators_on_the_store(synthetic_store):
    from kit.data import store
    from kit.ind import compute, readings
    get = lambda t: store.read(synthetic_store, t, "SYNA")
    x = compute(get("1h"), "1h", get)
    assert x.st_k.dropna().between(0, 100).all() and x.rsi_value.dropna().between(0, 100).all()
    assert x.macd_htf_hist_atr.notna().mean() > 0.5                       # the daily reading arrives
    r = readings(x)
    for c in ("stoch_k", "rsi", "macd_hist_atr", "STOCH_STATE", "RSI_STATE", "MACD_STATE", "MACD_HTF_STATE"):
        assert c in r
    assert set(pd.Series(r.MACD_STATE).unique()) <= {"bull widening", "bull narrowing", "bear widening", "bear narrowing", "nan"}
