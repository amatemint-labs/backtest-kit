"""Pine Script v5 built-ins, re-implemented so the ports behave like TradingView.

Every function takes and returns float64 numpy arrays, one value per bar, oldest first.
NaN plays the role of Pine's `na`. Comparisons with NaN are False, as in Pine.

Warm-up (how the first values are seeded) is the usual source of small mismatches
against TradingView, so it is a named setting:
  ema(..., seed="sma")   -> first value is the simple average of the first `length` bars (default)
  ema(..., seed="first") -> first value is the first source value (the formula printed in
                            the Pine reference). `kit match-check --ema-seed first` tries it.
After a few hundred bars both seeds give the same numbers.
"""
from __future__ import annotations

import numpy as np
from numba import njit

SEED_SMA = 0
SEED_FIRST = 1


@njit(cache=True)
def _sma(x, n):
    out = np.full(x.shape[0], np.nan)
    for i in range(n - 1, x.shape[0]):
        s = 0.0
        ok = True
        for j in range(i - n + 1, i + 1):
            v = x[j]
            if np.isnan(v):
                ok = False
                break
            s += v
        if ok:
            out[i] = s / n
    return out


@njit(cache=True)
def _ewm(x, n, alpha, seed):
    """sum := na(sum[1]) ? seed_value : alpha*src + (1-alpha)*sum[1]  (Pine ta.ema / ta.rma)."""
    m = x.shape[0]
    out = np.full(m, np.nan)
    prev = np.nan
    for i in range(m):
        if np.isnan(prev):
            if seed == SEED_FIRST:
                v = x[i]
            else:
                v = np.nan
                if i >= n - 1:
                    s = 0.0
                    ok = True
                    for j in range(i - n + 1, i + 1):
                        if np.isnan(x[j]):
                            ok = False
                            break
                        s += x[j]
                    if ok:
                        v = s / n
        else:
            v = alpha * x[i] + (1.0 - alpha) * prev
        out[i] = v
        prev = v
    return out


def _arr(x) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(x, dtype=np.float64))


def sma(x, n: int) -> np.ndarray:
    return _sma(_arr(x), int(n))


def ema(x, n: int, seed: str = "sma") -> np.ndarray:
    return _ewm(_arr(x), int(n), 2.0 / (n + 1.0), SEED_FIRST if seed == "first" else SEED_SMA)


def rma(x, n: int) -> np.ndarray:
    """Wilder's average (ta.rma) — always SMA-seeded in Pine."""
    return _ewm(_arr(x), int(n), 1.0 / n, SEED_SMA)


@njit(cache=True)
def _roll_ext(x, n, want_max):
    out = np.full(x.shape[0], np.nan)
    for i in range(n - 1, x.shape[0]):
        best = np.nan
        for j in range(i - n + 1, i + 1):
            v = x[j]
            if np.isnan(v):
                continue
            if np.isnan(best) or (want_max and v > best) or ((not want_max) and v < best):
                best = v
        out[i] = best
    return out


def highest(x, n: int) -> np.ndarray:
    return _roll_ext(_arr(x), int(n), True)


def lowest(x, n: int) -> np.ndarray:
    return _roll_ext(_arr(x), int(n), False)


def stoch(close, high, low, n: int) -> np.ndarray:
    """ta.stoch: 100 * (close - lowest(low, n)) / (highest(high, n) - lowest(low, n)); 0/0 -> na."""
    c = _arr(close)
    hh, ll = highest(high, n), lowest(low, n)
    den = hh - ll
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 * (c - ll) / den
    out[~(den != 0)] = np.nan
    return out


def tr(high, low, close) -> np.ndarray:
    """ta.tr(true): on the first bar (no previous close) it is high - low."""
    h, l, c = _arr(high), _arr(low), _arr(close)
    pc = np.r_[np.nan, c[:-1]]
    out = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    return out


def shift(x, k: int = 1) -> np.ndarray:
    x = _arr(x)
    if k <= 0:
        return x.copy()
    return np.r_[np.full(k, np.nan), x[:-k]]


def crossover(a, b) -> np.ndarray:
    a, b = _arr(a), np.broadcast_to(_arr(b), np.shape(a))
    a1, b1 = shift(a), shift(b)
    return (a > b) & (a1 <= b1)


def crossunder(a, b) -> np.ndarray:
    a, b = _arr(a), np.broadcast_to(_arr(b), np.shape(a))
    a1, b1 = shift(a), shift(b)
    return (a < b) & (a1 >= b1)


@njit(cache=True)
def atr_trail(close, atr_val, factor):
    """An ATR trailing stop: trails price by `factor` x atr_val, flipping side when price crosses it."""
    n = close.shape[0]
    out = np.full(n, np.nan)
    for i in range(n):
        prev = out[i - 1] if i > 0 else np.nan
        c = close[i]
        if np.isnan(prev):
            out[i] = c
            continue
        p = prev
        c1 = close[i - 1]
        ls = c - factor * atr_val[i]
        ss = c + factor * atr_val[i]
        if c > p and c1 > p:
            v = np.nan if np.isnan(ls) else max(p, ls)   # math.max(x, na) = na in Pine
        elif c < p and c1 < p:
            v = np.nan if np.isnan(ss) else min(p, ss)
        elif c > p:
            v = ls
        else:
            v = ss
        out[i] = v
    return out


# ── more Pine built-ins, for translating your own scripts ─────────────────────
# Each mirrors the formula in the Pine v5 reference. Where Pine's warm-up differs from the
# obvious formula, the comment says so. Tested in tests/test_pine_more.py.

def hl2(high, low):
    return (_arr(high) + _arr(low)) / 2


def hlc3(high, low, close):
    return (_arr(high) + _arr(low) + _arr(close)) / 3


def ohlc4(open_, high, low, close):
    return (_arr(open_) + _arr(high) + _arr(low) + _arr(close)) / 4


def change(x, n: int = 1):
    """ta.change(x, n) = x - x[n]."""
    return _arr(x) - shift(x, n)


def roc(x, n: int):
    """ta.roc = 100 * (x - x[n]) / x[n]."""
    x = _arr(x)
    p = shift(x, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * (x - p) / p


def mom(x, n: int):
    return change(x, n)


def rolling_sum(x, n: int):
    """math.sum(x, n): na until n bars, na if any bar in the window is na."""
    return _sma(_arr(x), int(n)) * n


def wma(x, n: int):
    """ta.wma: weights n, n-1, ..., 1 (newest heaviest)."""
    x = _arr(x)
    out = np.full(x.shape[0], np.nan)
    w = np.arange(1, n + 1, dtype=float)
    if x.shape[0] >= n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = win @ w / w.sum()
    return out


def stdev(x, n: int, biased: bool = True):
    """ta.stdev (biased=True: divide by n, Pine's default)."""
    x = _arr(x)
    out = np.full(x.shape[0], np.nan)
    if x.shape[0] >= n:
        win = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = win.std(axis=1, ddof=0 if biased else 1)
    return out


def rsi(x, n: int):
    """ta.rsi: 100 - 100 / (1 + rma(gain, n) / rma(loss, n)); all-gain -> 100, all-loss -> 0."""
    ch = change(x)
    up = rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0.0)), n)
    dn = rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0.0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100.0 - 100.0 / (1.0 + up / dn)))
    out[np.isnan(up) | np.isnan(dn)] = np.nan
    return out


def atr(high, low, close, n: int):
    """ta.atr = rma(tr(true), n)."""
    return rma(tr(high, low, close), n)


def macd(x, fast: int = 12, slow: int = 26, signal: int = 9, seed: str = "sma"):
    """ta.macd -> (macd line, signal line, histogram)."""
    m = ema(x, fast, seed) - ema(x, slow, seed)
    s = ema(m, signal, seed)
    return m, s, m - s


def bb(x, n: int = 20, mult: float = 2.0):
    """ta.bb -> (basis, upper, lower) with an SMA basis and biased stdev."""
    b = sma(x, n)
    d = mult * stdev(x, n)
    return b, b + d, b - d


def rising(x, n: int):
    """ta.rising: x is greater than every one of its previous n values."""
    x = _arr(x)
    ok = np.ones(x.shape[0], bool)
    for k in range(1, n + 1):
        ok &= x > shift(x, k)
    return ok


def falling(x, n: int):
    x = _arr(x)
    ok = np.ones(x.shape[0], bool)
    for k in range(1, n + 1):
        ok &= x < shift(x, k)
    return ok


@njit(cache=True)
def _barssince(cond):
    out = np.full(cond.shape[0], np.nan)
    last = -1
    for i in range(cond.shape[0]):
        if cond[i]:
            last = i
        if last >= 0:
            out[i] = i - last
    return out


def barssince(cond):
    """ta.barssince: bars since cond was last true (0 on the bar it is true); na before the first time."""
    return _barssince(np.asarray(cond, bool))


@njit(cache=True)
def _valuewhen(cond, src, occ):
    out = np.full(cond.shape[0], np.nan)
    hist = np.full(occ + 1, np.nan)
    n_seen = 0
    for i in range(cond.shape[0]):
        if cond[i]:
            for k in range(occ, 0, -1):
                hist[k] = hist[k - 1]
            hist[0] = src[i]
            n_seen += 1
        if n_seen > occ:
            out[i] = hist[occ]
    return out


def valuewhen(cond, src, occurrence: int = 0):
    """ta.valuewhen: src on the most recent bar (occurrence 0) where cond was true, including this bar."""
    return _valuewhen(np.asarray(cond, bool), _arr(src), int(occurrence))


@njit(cache=True)
def _pivot(x, left, right, high):
    n = x.shape[0]
    out = np.full(n, np.nan)
    for i in range(left + right, n):
        c = i - right                     # the candidate pivot bar
        v = x[c]
        if np.isnan(v):
            continue
        ok = True
        for j in range(c - left, c + right + 1):
            if j == c:
                continue
            if np.isnan(x[j]) or (high and x[j] >= v and j > c) or (high and x[j] > v and j < c) \
                    or ((not high) and x[j] <= v and j > c) or ((not high) and x[j] < v and j < c):
                ok = False
                break
        if ok:
            out[i] = v                    # reported on the CONFIRMING bar, `right` bars later
    return out


def pivothigh(x, left: int, right: int):
    """ta.pivothigh(src, left, right): the pivot's value, reported `right` bars AFTER the pivot
    (that is when Pine knows it). Using it at the pivot bar itself would be lookahead."""
    return _pivot(_arr(x), int(left), int(right), True)


def pivotlow(x, left: int, right: int):
    return _pivot(_arr(x), int(left), int(right), False)


def vwap(ts, high, low, close, volume):
    """ta.vwap with the default anchor (resets each session); source hlc3."""
    import pandas as pd
    day = pd.DatetimeIndex(ts).normalize()
    src = hlc3(high, low, close)
    v = np.nan_to_num(_arr(volume))
    pv = pd.Series(src * v).groupby(day).cumsum().to_numpy()
    vv = pd.Series(v).groupby(day).cumsum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(vv > 0, pv / vv, np.nan)


@njit(cache=True)
def _supertrend(close, up0, lo0, atr_prev_na):
    n = close.shape[0]
    st = np.full(n, np.nan)
    dirn = np.zeros(n)
    up = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    for i in range(n):
        u, l_ = up0[i], lo0[i]
        pu = up[i - 1] if i > 0 and not np.isnan(up[i - 1]) else 0.0
        pl = lo[i - 1] if i > 0 and not np.isnan(lo[i - 1]) else 0.0
        c1 = close[i - 1] if i > 0 else np.nan
        lo[i] = l_ if (l_ > pl or c1 < pl) else pl
        up[i] = u if (u < pu or c1 > pu) else pu
        prev_st = st[i - 1] if i > 0 else np.nan
        if atr_prev_na[i]:
            d = 1.0
        elif prev_st == pu:
            d = -1.0 if close[i] > up[i] else 1.0
        else:
            d = 1.0 if close[i] < lo[i] else -1.0
        dirn[i] = d
        st[i] = lo[i] if d == -1.0 else up[i]
    return st, dirn


def supertrend(high, low, close, factor: float, atr_period: int):
    """ta.supertrend -> (supertrend line, direction). Direction -1 = up-trend, +1 = down-trend (Pine's convention)."""
    a = atr(high, low, close, atr_period)
    src = hl2(high, low)
    st, d = _supertrend(_arr(close), src + factor * a, src - factor * a, np.isnan(shift(a, 1)))
    st[np.isnan(a)] = np.nan
    return st, d
