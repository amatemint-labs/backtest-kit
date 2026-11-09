"""The winner census (method step 3): every swing leg, priced as an at-the-money option.

A leg is found with an ATR zigzag: it ends when price turns k x ATR off its best point.
Low->high legs are CALL trades, high->low legs are PUT trades. Entry = close of the turn bar,
exit = close of the next turn bar. It is a hindsight list of what was available — not a rule.

  intraday legs: 1h bars, k = 0.75 and 1.5 x the PREVIOUS session's daily ATR(14)
  daily legs:    1D bars, k = 2, 4, 8 x daily ATR(14)

Each leg's option expiry comes from the leg SIZE you are looking for (known at entry), never
from where the leg ended: see EXPIRY_SESSIONS. If a leg outlives its option, the option is
valued at expiry (intrinsic) and the row is flagged `outlived_option`.

Naming: "1x" = the option gained 1x its cost (+100%, doubled); "3x" = +300%; "5x" = +500%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..ind import pine
from . import options

INTRADAY_K = (0.75, 1.5)
DAILY_K = (2.0, 4.0, 8.0)
# first Friday at least N sessions after entry
EXPIRY_SESSIONS = {0.75: 3, 1.5: 8, 2.0: 21, 4.0: 42, 8.0: 63}
HORIZONS = ["same-day", "overnight", "2-5 days", "1-4 weeks", "1-3 months", "3 months+"]


def zigzag(hi: np.ndarray, lo: np.ndarray, atr: np.ndarray, k: float) -> list[tuple[int, int]]:
    """Alternating pivots [(bar index, +1 high | -1 low)]; a reversal is k x ATR off the extreme."""
    piv: list[tuple[int, int]] = []
    n = len(hi)
    mode = 0
    i0 = 0
    while i0 < n and not (np.isfinite(hi[i0]) and np.isfinite(lo[i0]) and np.isfinite(atr[i0])):
        i0 += 1
    if i0 >= n:
        return piv
    mx = mn = i0
    for i in range(i0 + 1, n):
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i])):
            continue
        if mode == 1:
            if hi[i] >= hi[mx]:
                mx = i
                continue
        elif mode == -1:
            if lo[i] <= lo[mn]:
                mn = i
                continue
        else:
            if hi[i] >= hi[mx]:
                mx = i
            if lo[i] <= lo[mn]:
                mn = i
        if mode == 0:
            a = atr[mx] if np.isfinite(atr[mx]) else atr[i]
            if hi[mx] - lo[i] >= k * a and mx < i:
                piv.append((mx, 1)); mode = -1; mn = i; continue
            a = atr[mn] if np.isfinite(atr[mn]) else atr[i]
            if hi[i] - lo[mn] >= k * a and mn < i:
                piv.append((mn, -1)); mode = 1; mx = i; continue
        elif mode == 1:
            if np.isfinite(atr[mx]) and hi[mx] - lo[i] >= k * atr[mx]:
                piv.append((mx, 1)); mode = -1; mn = i
        else:
            if np.isfinite(atr[mn]) and hi[i] - lo[mn] >= k * atr[mn]:
                piv.append((mn, -1)); mode = 1; mx = i
    return piv


# How a leg's size is measured, and the two label tiers built from it.
#   options:    the at-the-money option's gain (1x = doubled)
#   underlying: the move in daily ATRs (shares, futures contracts, crypto)
TIERS = {"options": (("1x", 1.0), ("3x", 3.0)), "underlying": (("2atr", 2.0), ("4atr", 4.0))}
WINNER_LEVELS = {"options": (1, 3, 5, 10), "underlying": (1, 2, 4, 8)}


def _sessions():
    from ..assets import SESSIONS
    return SESSIONS


def daily_context(daily: pd.DataFrame, session=None) -> pd.DataFrame:
    """Per trading day: ATR(14), 20-day realized vol, EMA50 slope — all from PRIOR days (shift 1)."""
    ses = session or _sessions()["us_equity"]
    d = daily[["ts", "high", "low", "close"]].copy().reset_index(drop=True)
    d["date"] = ses.trade_date(d.ts).to_numpy()
    tr = pine.tr(d.high, d.low, d.close)
    d["atr"] = pd.Series(tr).rolling(14, min_periods=10).mean().to_numpy()
    d["rv"] = np.log(d.close).diff().rolling(20).std().to_numpy() * np.sqrt(ses.days_per_year)
    e50 = d.close.ewm(span=50, adjust=False).mean()
    d["e50_slope"] = (e50 - e50.shift(10)).to_numpy()
    prev = d[["date"]].copy()
    for c in ("atr", "rv", "e50_slope", "high", "low", "close"):
        prev["prev_" + c] = d[c].shift(1).to_numpy()
    prev["atr_today"] = d["atr"].to_numpy()
    prev["rv_today"] = d["rv"].to_numpy()
    return prev


def horizon(sessions: np.ndarray) -> np.ndarray:
    s = np.asarray(sessions)
    return np.select([s == 0, s == 1, s <= 5, s <= 21, s <= 63], HORIZONS[:5], HORIZONS[5])


def _price(legs: pd.DataFrame, bars: pd.DataFrame, close: np.ndarray, dates: np.ndarray) -> pd.DataFrame:
    call = (legs.side == "C").to_numpy()
    ed = legs.entry_date.to_numpy().astype("datetime64[D]")
    exp = np.empty(len(legs), dtype="datetime64[D]")
    ks = legs.k_atr.to_numpy(float)
    for k in np.unique(ks):
        m = ks == k
        exp[m] = options.expiry_after(ed[m], EXPIRY_SESSIONS.get(float(k), 21))
    # if the leg outlives the option, exit at the last bar on/before expiry
    xi = legs.exit_i.to_numpy().copy()
    last_ok = np.searchsorted(dates, exp, side="right") - 1
    outlived = xi > last_ok
    xi = np.where(outlived, np.maximum(last_ok, legs.entry_i.to_numpy()), xi)
    S0 = legs.S0.to_numpy()
    S1 = close[xi]
    fr_e = options.day_fraction_left(legs.entry_ts)
    x_ts = bars.ts.iloc[xi].reset_index(drop=True)
    fr_x = options.day_fraction_left(x_ts)
    T0 = options.years_to_expiry(ed, fr_e, exp)
    T1 = options.years_to_expiry(dates[xi], fr_x, exp)
    mult, p0 = options.multiple(S0, S1, T0, T1, legs.iv.to_numpy(), call)
    touch, _ = options.multiple(S0, legs.extreme.to_numpy(), T0, T1, legs.iv.to_numpy(), call)
    legs = legs.copy()
    legs["expiry"] = pd.to_datetime(exp)
    legs["sessions_to_expiry"] = np.busday_count(ed, exp)
    legs["outlived_option"] = outlived
    legs["premium"] = p0
    legs["mult"] = mult
    legs["mult_at_best"] = touch
    legs["gain"] = mult - 1
    legs["size"] = legs["gain"]
    legs["tier"] = np.select([legs.gain >= 10, legs.gain >= 5, legs.gain >= 3, legs.gain >= 1], ["10x+", "5-10x", "3-5x", "1-3x"], "<1x")
    return legs


def _underlying(legs: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    legs = legs.copy()
    sign = np.where(legs.side == "C", 1.0, -1.0)
    legs["points"] = sign * (legs.S1 - legs.S0)
    legs["return_pct"] = 100 * legs.points / legs.S0
    legs["dollars_per_unit"] = legs.points * multiplier
    legs["size"] = (legs.S1 - legs.S0).abs() / legs.atr
    legs["tier"] = np.select([legs["size"] >= 8, legs["size"] >= 4, legs["size"] >= 2, legs["size"] >= 1],
                             ["8+ ATR", "4-8 ATR", "2-4 ATR", "1-2 ATR"], "<1 ATR")
    return legs


def legs_for(bars: pd.DataFrame, daily: pd.DataFrame, ticker: str, tf: str, inst=None, trade_as: str = "options") -> pd.DataFrame:
    """All legs for one ticker on one timeframe ('1h' intraday or '1D'), valued per `trade_as`."""
    from ..assets import Instrument
    inst = inst or Instrument(ticker, "stock")
    ses = inst.session
    bars = bars.reset_index(drop=True)
    ctx = daily_context(daily, ses)
    date = ses.trade_date(bars.ts).reset_index(drop=True)
    m = pd.DataFrame({"date": date}).merge(ctx, on="date", how="left")
    intraday = tf != "1D"
    atr = (m.prev_atr if intraday else m.atr_today).to_numpy(float)
    rv = (m.prev_rv if intraday else m.rv_today).to_numpy(float)
    slope = m.prev_e50_slope.to_numpy(float)
    hi, lo, c = (bars[x].to_numpy(float) for x in ("high", "low", "close"))
    dates = date.to_numpy().astype("datetime64[D]")
    day_idx = np.searchsorted(np.unique(dates), dates)
    rows = []
    for k in (INTRADAY_K if intraday else DAILY_K):
        P = zigzag(hi, lo, atr, k)
        for (a, ta), (b, _) in zip(P[:-1], P[1:]):
            if b <= a or not (np.isfinite(c[a]) and np.isfinite(atr[a])):
                continue
            side = "C" if ta == -1 else "P"
            rows.append((ticker, tf, k, side, a, b, c[a], hi[b] if side == "C" else lo[b], atr[a], rv[a], slope[a]))
    cols = ["ticker", "tf", "k_atr", "side", "entry_i", "exit_i", "S0", "extreme", "atr", "rv", "e50_slope"]
    L = pd.DataFrame(rows, columns=cols)
    if L.empty:
        return L
    L["entry_ts"] = pd.to_datetime(bars.ts.iloc[L.entry_i].reset_index(drop=True))
    L["exit_ts"] = pd.to_datetime(bars.ts.iloc[L.exit_i].reset_index(drop=True))
    L["entry_date"] = pd.to_datetime(dates[L.entry_i])
    L["S1"] = c[L.exit_i]
    L["bars"] = L.exit_i - L.entry_i
    L["iv"] = options.iv_from_rv(L.rv)
    if trade_as == "options":
        L = _price(L, bars, c, dates)
    else:
        L = _underlying(L, inst.multiplier)
    sess = day_idx[L.exit_i] - day_idx[L.entry_i]
    L["sessions"] = sess
    L["horizon"] = horizon(sess)
    L["move_atr"] = (L.S1 - L.S0).abs() / L.atr
    L["move_pct"] = L.S1 / L.S0 - 1
    L["asset"] = inst.asset
    L["trend"] = np.where(np.sign(L.e50_slope) == np.where(L.side == "C", 1, -1), "with", "against")
    return L.drop(columns=["e50_slope", "entry_date"])


def winners(legs: pd.DataFrame, trade_as: str = "options") -> pd.DataFrame:
    """Count of legs reaching each size level (option gain, or move in ATR), by horizon and side."""
    if legs.empty:
        return pd.DataFrame()
    unit = "x" if trade_as == "options" else " ATR"
    sides = {"C": "calls", "P": "puts"} if trade_as == "options" else {"C": "long", "P": "short"}
    out = []
    for h in HORIZONS:
        for side in ("C", "P"):
            x = legs[(legs.horizon == h) & (legs.side == side)]
            r = {"horizon": h, "side": sides[side], "legs": len(x)}
            for g in WINNER_LEVELS[trade_as]:
                r[f">={g}{unit}"] = int((x["size"] >= g).sum())
            out.append(r)
    return pd.DataFrame(out)


def summary(legs: pd.DataFrame, trade_as: str = "options") -> pd.DataFrame:
    if legs.empty:
        return pd.DataFrame()
    g = legs.groupby(["tf", "k_atr", "side"])
    s = g.size().rename("legs").to_frame()
    if trade_as == "options":
        s["pct_1x+"] = (100 * g.apply(lambda x: (x.gain >= 1).mean(), include_groups=False)).round(1)
        s["pct_3x+"] = (100 * g.apply(lambda x: (x.gain >= 3).mean(), include_groups=False)).round(1)
        s["median_mult"] = g["mult"].median().round(2)
        s["pct_outlived_option"] = (100 * g["outlived_option"].mean()).round(1)
    else:
        s["pct_2atr+"] = (100 * g.apply(lambda x: (x["size"] >= 2).mean(), include_groups=False)).round(1)
        s["pct_4atr+"] = (100 * g.apply(lambda x: (x["size"] >= 4).mean(), include_groups=False)).round(1)
        s["median_move_atr"] = g["size"].median().round(2)
        s["median_return_pct"] = g["return_pct"].median().round(2)
    s["median_sessions"] = g["sessions"].median()
    return s.reset_index()
