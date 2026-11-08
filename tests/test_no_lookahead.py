"""No reading may use the future. Scramble every price after a cut; readings at or before the cut
must not change. The 'tv' (TradingView replica) mode is shown to FAIL this — proof the test bites."""
import shutil

import numpy as np
import pandas as pd
import pytest

from kit.data import store, synthetic
from kit.ind import compute
from kit.method import snapshot


def _perturbed_copy(src, dst, cut):
    """Copy the raw minute bars, scramble everything after `cut`, rebuild all timeframes."""
    rng = np.random.default_rng(11)
    for tk in synthetic.TICKERS:
        m1 = store.read(src, "1m", tk, raw=True)
        late = m1.ts > cut
        f = np.exp(rng.normal(0, 0.08, late.sum()))
        for c in ("open", "high", "low", "close"):
            m1.loc[late, c] = m1.loc[late, c] * f
        m1.loc[late, "high"] = m1.loc[late, ["open", "high", "low", "close"]].max(axis=1)
        m1.loc[late, "low"] = m1.loc[late, ["open", "high", "low", "close"]].min(axis=1)
        m1.loc[late, "volume"] = m1.loc[late, "volume"] * rng.uniform(0.2, 5, late.sum())
        store.write(m1, store.path(dst, "1m", tk, raw=True))
        store.build_timeframes(dst, tk, ["3m", "15m", "1h", "4h", "1D"])


@pytest.fixture(scope="module")
def pair(synthetic_store, tmp_path_factory):
    cut = pd.Timestamp("2026-01-14 12:30", tz="America/New_York")     # a 1h bar close, mid-session
    dst = tmp_path_factory.mktemp("perturbed")
    _perturbed_copy(synthetic_store, dst, cut)
    return synthetic_store, dst, cut


def _ind(d, tk, tf, mode):
    get = lambda t: store.read(d, t, tk)
    return compute(get(tf), tf, get, mode=mode)


@pytest.mark.parametrize("tf", ["1h", "15m", "4h", "1D"])
@pytest.mark.parametrize("mode", ["closed", "forming"])
def test_indicators_ignore_the_future(pair, tf, mode):
    a_dir, b_dir, cut = pair
    a, b = _ind(a_dir, "SYNA", tf, mode), _ind(b_dir, "SYNA", tf, mode)
    early = (a.ts <= cut).to_numpy()
    assert early.sum() > 50
    num = [c for c in a.columns if c != "ts" and pd.api.types.is_numeric_dtype(a[c])]
    for c in num:
        np.testing.assert_allclose(a.loc[early, c].to_numpy(float), b.loc[early, c].to_numpy(float), equal_nan=True, err_msg=c)


REPAINT_PLUGIN = """
from kit.ind import pine
from kit.plugin import Indicator

class DailyCloseLookaheadOn(Indicator):
    name = "daily_close_la"
    version = "request.security('D', close, lookahead_on)"
    def compute(self, bars, ctx):
        return {"dla_close": ctx.htf("1D", lambda d: {"c": d.close}, pine_lookahead_on=True)["c"]}
"""


def test_tv_mode_does_look_ahead_so_the_test_bites(pair, tmp_path, monkeypatch):
    """A Pine-style lookahead_on read: studies get closed bars (no change), TradingView-replica mode repaints."""
    from kit import plugin
    (tmp_path / "indicators").mkdir()
    (tmp_path / "indicators" / "dla.py").write_text(REPAINT_PLUGIN)
    monkeypatch.setenv("KIT_PLUGINS", str(tmp_path))
    plugin.registry(refresh=True)
    a_dir, b_dir, cut = pair
    try:
        def run(d, mode):
            get = lambda t: store.read(d, t, "SYNA")
            return compute(get("1h"), "1h", get, mode=mode, indicators=["daily_close_la"])
        early = None
        for mode, should_change in (("closed", False), ("tv", True)):
            a, b = run(a_dir, mode), run(b_dir, mode)
            early = (a.ts <= cut).to_numpy()
            diff = np.nanmax(np.abs(a.loc[early, "dla_close"].to_numpy() - b.loc[early, "dla_close"].to_numpy()))
            assert (diff > 0.01) == should_change, (mode, diff)
    finally:
        monkeypatch.delenv("KIT_PLUGINS")
        plugin.registry(refresh=True)


def test_snapshot_readings_ignore_the_future(pair):
    a_dir, b_dir, cut = pair
    mk_a = snapshot.market_feats(a_dir, synthetic.MARKET, "1h", "closed")
    mk_b = snapshot.market_feats(b_dir, synthetic.MARKET, "1h", "closed")
    A = snapshot.build_intraday(a_dir, "SYNB", mk_a, "closed")["bars"]
    B = snapshot.build_intraday(b_dir, "SYNB", mk_b, "closed")["bars"]
    early = (A.ts <= cut).to_numpy()
    readings = [c for c in A.columns if c.startswith(("h1_", "h4_", "D_", "m15_", "m3_", "mktD_", "mktH1_"))] + \
               ["gap_open_atr", "from_open_atr", "vs_prev_high_atr", "day_range_pos", "d_atr", "rv", "iv"]
    assert len(readings) > 60
    for c in readings:
        x, y = A.loc[early, c].to_numpy(), B.loc[early, c].to_numpy()
        if pd.api.types.is_numeric_dtype(A[c]):
            np.testing.assert_allclose(x.astype(float), y.astype(float), equal_nan=True, err_msg=c)
        else:
            assert (x.astype(str) == y.astype(str)).all(), c
