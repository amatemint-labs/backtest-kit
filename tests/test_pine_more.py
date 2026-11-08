"""The extra Pine built-ins, each against values worked out by hand (comments show the arithmetic)."""
import numpy as np
import pandas as pd
import pytest

from kit.ind import pine

nan = np.nan


def eq(got, exp):
    np.testing.assert_allclose(np.asarray(got, float), np.asarray(exp, float), atol=1e-9, equal_nan=True)


def test_wma_stdev_change_roc():
    eq(pine.wma([1, 2, 3], 3), [nan, nan, 14 / 6])                  # (1*1 + 2*2 + 3*3) / 6
    eq(pine.stdev([1, 2, 3, 4], 2), [nan, 0.5, 0.5, 0.5])           # population stdev of two values 1 apart
    eq(pine.change([5, 7, 4]), [nan, 2, -3])
    eq(pine.roc([100, 110, 99], 1), [nan, 10, -10])


def test_rsi_by_hand():
    # closes 10,11,10,11, length 2. gains [-,1,0,1], losses [-,0,1,0].
    # bar 3: rma seeds = SMA of 2 -> gain 0.5, loss 0.5 -> RSI 50.
    # bar 4: gain 0.5*1 + 0.5*0.5 = 0.75, loss 0.5*0 + 0.5*0.5 = 0.25 -> RS 3 -> 100 - 100/4 = 75.
    eq(pine.rsi([10, 11, 10, 11], 2), [nan, nan, 50, 75])
    eq(pine.rsi([1, 2, 3, 4], 2)[-1:], [100])                       # all gains


def test_macd_bb_shapes():
    x = np.linspace(1, 50, 60)
    m, s, h = pine.macd(x, 3, 6, 2)
    eq(h[-5:], (m - s)[-5:])
    b, u, l = pine.bb(np.array([1, 2, 3, 4.0]), 2, 2)
    eq(b, [nan, 1.5, 2.5, 3.5])
    eq(u - b, [nan, 1, 1, 1])                                        # 2 x stdev 0.5


def test_barssince_valuewhen():
    c = [False, True, False, False, True]
    eq(pine.barssince(c), [nan, 0, 1, 2, 0])
    c2 = [False, True, False, True, False]
    eq(pine.valuewhen(c2, [1, 2, 3, 4, 5], 0), [nan, 2, 2, 4, 4])
    eq(pine.valuewhen(c2, [1, 2, 3, 4, 5], 1), [nan, nan, nan, 2, 2])


def test_pivots_are_reported_when_confirmed_not_when_they_happen():
    x = [1, 3, 2, 1, 0]
    # bar 1 (value 3) is a 1-left / 1-right pivot high, but Pine only knows that at bar 2.
    eq(pine.pivothigh(x, 1, 1), [nan, nan, 3, nan, nan])
    eq(pine.pivotlow([3, 1, 2, 3, 4], 1, 1), [nan, nan, 1, nan, nan])


def test_vwap_resets_each_session():
    ts = pd.DatetimeIndex(["2026-11-05 10:00", "2026-11-05 11:00", "2026-11-06 10:00"], tz="America/New_York")
    h = l = c = np.array([10.0, 20.0, 30.0])
    v = np.array([1.0, 3.0, 5.0])
    eq(pine.vwap(ts, h, l, c, v), [10, (10 + 60) / 4, 30])


def test_rising_falling_and_supertrend_direction():
    x = np.arange(10.0)
    assert pine.rising(x, 3)[-1] and not pine.falling(x, 3)[-1]
    n = 200
    c = np.r_[np.linspace(100, 150, n // 2), np.linspace(150, 100, n // 2)]
    st, d = pine.supertrend(c + 0.5, c - 0.5, c, 3, 10)
    assert d[n // 2 - 5] == -1 and d[-5] == 1                         # -1 = up-trend in Pine's convention
