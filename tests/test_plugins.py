"""Plug-in indicators: discovery, the higher-timeframe helpers, scaffolding, and — most important —
check-indicator catching a plug-in that reads the future."""
import os
import textwrap

import numpy as np
import pandas as pd
import pytest

from kit import config, plugin
from kit.check import check_indicator
from kit.data import store, synthetic


@pytest.fixture(scope="module")
def kit_settings(tmp_path_factory):
    root = tmp_path_factory.mktemp("kitroot")
    s = config.Settings(root=root, data_dir=root / "data", studies_dir=root / "studies")
    synthetic.ensure(s.data_dir / "synthetic", s.timeframes, log=lambda m: None)
    return s


@pytest.fixture
def extra_plugins(tmp_path):
    """A temporary plug-in folder (KIT_PLUGINS) — cleaned up after the test."""
    d = tmp_path / "myplugins"
    (d / "indicators").mkdir(parents=True)
    old = os.environ.get("KIT_PLUGINS")
    os.environ["KIT_PLUGINS"] = str(d)
    yield d / "indicators"
    if old is None:
        os.environ.pop("KIT_PLUGINS", None)
    else:
        os.environ["KIT_PLUGINS"] = old
    plugin.registry(refresh=True)


def test_registry_has_bundled_and_example():
    reg = plugin.registry(refresh=True)
    assert {"stoch", "rsi", "macd", "rsi_bands"} <= set(reg)


def test_requires_runs_dependencies_first(extra_plugins):
    (extra_plugins / "dep.py").write_text(textwrap.dedent('''
        from kit.plugin import Indicator

        class MacdSign(Indicator):
            name = "macd_sign"
            version = "uses macd outputs"
            requires = ("macd",)
            def compute(self, bars, ctx):
                return {"ms_sign": (ctx.outputs["macd"]["macd_hist"] > 0).astype(float)}
    '''))
    plugin.registry(refresh=True)
    assert [i.name for i in plugin.resolve(["macd_sign"])] == ["macd", "macd_sign"]


def test_example_plugin_is_safe(kit_settings):
    r = check_indicator(kit_settings, "rsi_bands", ("1h", "1D"), log=lambda m: None)
    assert r["passed"], r["checks"]


def test_a_plugin_that_reads_the_future_fails(kit_settings, extra_plugins):
    (extra_plugins / "cheat.py").write_text(textwrap.dedent('''
        from kit.ind import pine
        from kit.plugin import Indicator
        import numpy as np

        class Cheat(Indicator):
            name = "cheat"
            version = "reads tomorrow"
            def compute(self, bars, ctx):
                c = bars.close.to_numpy(float)
                nxt = np.r_[c[1:], np.nan]            # the next bar's close: lookahead
                return {"cheat_next_up": (nxt > c).astype(float)}
    '''))
    plugin.registry(refresh=True)
    r = check_indicator(kit_settings, "cheat", ("1h",), log=lambda m: None)
    look = [c for c in r["checks"] if c["name"].startswith("no lookahead")]
    assert look and not look[0]["pass"] and "cheat_next_up" in look[0]["detail"]
    assert not r["passed"]


def test_a_repainting_higher_timeframe_fails(kit_settings, extra_plugins):
    """Reading the daily bar a 1h bar sits in (TradingView's lookahead_on) instead of the last closed one."""
    (extra_plugins / "repaint.py").write_text(textwrap.dedent('''
        from kit.ind import mtf
        from kit.plugin import Indicator

        class Repaint(Indicator):
            name = "repaint"
            version = "uses the unfinished daily bar"
            def compute(self, bars, ctx):
                d = ctx.bars("1D")
                k = mtf.idx_containing(mtf.as_ns(bars.ts), mtf.as_ns(d.ts))
                return {"rp_daily_close": mtf.take(d.close.to_numpy(float), k)}
    '''))
    plugin.registry(refresh=True)
    r = check_indicator(kit_settings, "repaint", ("1h",), log=lambda m: None)
    assert not r["passed"]


def test_broken_plugin_does_not_break_the_others(extra_plugins):
    (extra_plugins / "broken.py").write_text("this is not python(\n")
    reg = plugin.registry(refresh=True)
    assert "macd" in reg and any("broken.py" in f for f in plugin.registry.errors)


def test_htf_prev_is_yesterdays_daily_value(kit_settings):
    from kit.plugin import Context
    d = kit_settings.data_dir / "synthetic"
    h1, d1 = store.read(d, "1h", "SYNA"), store.read(d, "1D", "SYNA")
    ctx = Context("1h", h1.ts, "closed", "sma", lambda tf: d1 if tf == "1D" else None, {})
    prev = ctx.htf_prev("1D", lambda b: {"c": b.close})["c"]
    closed = ctx.htf("1D", lambda b: {"c": b.close})["c"]
    i = int(np.flatnonzero((h1.ts.dt.hour == 11).to_numpy())[30])          # an 11:30 bar
    day = h1.ts.iloc[i].normalize()
    y = d1[d1.ts.dt.normalize() < day].close.iloc[-1]
    assert prev[i] == pytest.approx(y) and closed[i] == pytest.approx(y)
    j = int(np.flatnonzero((h1.ts.dt.hour == 16).to_numpy())[30])          # the 16:00 bar
    today = d1[d1.ts.dt.normalize() == h1.ts.iloc[j].normalize()].close.iloc[0]
    assert closed[j] == pytest.approx(today)      # the daily bar closed at 16:00 too
    assert prev[j] != pytest.approx(today)        # Pine's expr[1] idiom still shows yesterday


def test_scaffolded_indicator_loads_and_passes(kit_settings, extra_plugins, tmp_path):
    from kit.scaffold import new_indicator
    s = config.Settings(root=tmp_path / "root", data_dir=kit_settings.data_dir, studies_dir=tmp_path / "st")
    r = new_indicator(s, "my_tool")
    src = open(r["file"]).read()
    (extra_plugins / "my_tool.py").write_text(src)
    plugin.registry(refresh=True)
    res = check_indicator(kit_settings, "my_tool", ("1h",), log=lambda m: None)
    assert res["passed"], res["checks"]


@pytest.mark.parametrize("name", ["stoch", "rsi", "macd"])
def test_bundled_indicators_pass_the_same_check(kit_settings, name):
    r = check_indicator(kit_settings, name, ("1h",), log=lambda m: None)
    assert r["passed"], [c for c in r["checks"] if not c["pass"]]
