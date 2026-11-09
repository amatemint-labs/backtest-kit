"""Per-bar snapshot (method steps 1, 4, 5): graded readings on every timeframe plus the
market, labels from the leg census, and the momentum-trail simulation used by the trade check.

Point-in-time rules:
  * every bar is stamped with its CLOSE time; a reading at bar t uses bars closed by t
  * HIGHER timeframes (4h, 1D, market 1D) join STRICTLY BEFORE t (the 16:00 daily bar is not
    used by the 16:00 1h bar) — the as-of rule
  * the same or LOWER timeframes (15m, 3m, market 1h) join at or before t (they closed by t)
  * inside an indicator, a higher timeframe read through ctx.htf follows `mode` (kit.ind.mtf)
Labels may look forward (that is what a label is). Readings never do; tests/test_no_lookahead.py
shifts future prices and checks that no reading changes.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ..data import store
from ..ind import compute as compute_ind
from ..ind import readings as ind_readings
from ..ind import pine
from . import census, options

INTRADAY_PREFIX = {"1h": "h1_", "4h": "h4_", "1D": "D_", "15m": "m15_", "3m": "m3_"}

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


def tf_feats(d: pd.DataFrame, p: str, names: list[str] | None = None) -> pd.DataFrame:
    """Graded readings for one timeframe: generic location / volume readings plus each indicator's
    own readings (see Indicator.readings), all prefixed with p (e.g. 'h1_')."""
    c, h, l = d.close.to_numpy(float), d.high.to_numpy(float), d.low.to_numpy(float)
    a = pine.rma(pine.tr(h, l, c), 14)
    a = np.where(a > 0, a, np.nan)
    cols = {}
    e20, e50, s200 = pine.ema(c, 20), pine.ema(c, 50), pine.sma(c, 200)
    cols["vs_ema20_atr"] = (c - e20) / a
    cols["vs_ema50_atr"] = (c - e50) / a
    cols["vs_sma200_atr"] = (c - s200) / a
    hi20, lo20 = pine.highest(h, 20), pine.lowest(l, 20)
    rng = hi20 - lo20
    cols["pos_in_20bar_range"] = np.where(rng > 0, (c - lo20) / np.where(rng > 0, rng, 1), np.nan)
    cols["move5_atr"] = (c - pine.shift(c, 5)) / a
    v = d.volume.to_numpy(float)
    vm = pine.sma(v, 20)
    cols["volume_x"] = np.where(vm > 0, v / np.where(vm > 0, vm, 1), np.nan)
    r = ind_readings(d, names)
    clash = set(cols) & set(r.columns)
    if clash:
        raise ValueError(f"reading names {sorted(clash)} clash with the kit's own location readings; rename them")
    for k in r.columns:
        cols[k] = r[k].to_numpy()
    o = pd.DataFrame({p + k: v for k, v in cols.items()}, index=d.index)
    o.insert(0, "ts", d.ts.to_numpy())
    return o


def _asof(left: pd.DataFrame, right: pd.DataFrame, strict: bool) -> pd.DataFrame:
    left, right = left.assign(ts=left.ts.dt.as_unit("ns")), right.assign(ts=right.ts.dt.as_unit("ns"))
    return pd.merge_asof(left.sort_values("ts"), right.sort_values("ts"), on="ts", direction="backward",
                         allow_exact_matches=not strict)


def indicators(data_dir, ticker: str, tfs: list[str], mode: str, names: list[str] | None = None) -> dict[str, pd.DataFrame]:
    cache: dict[str, pd.DataFrame | None] = {}

    def get(tf):
        if tf not in cache:
            cache[tf] = store.read(data_dir, tf, ticker)
        return cache[tf]
    out = {}
    for tf in tfs:
        b = get(tf)
        if b is None or len(b) < 50:
            continue
        out[tf] = compute_ind(b, tf, get, mode=mode, indicators=names)
    return out


MARKET_KEEP = ("vs_ema50", "pos_in", "move5")
RAW_PREFIX = {"1h": "raw1h_", "4h": "raw4h_", "1D": "rawD_"}


def raw_frame(d: pd.DataFrame, p: str) -> pd.DataFrame:
    """Every indicator output as computed (events, levels, labels), for signals. Not scorecard inputs."""
    cols = [c for c in d.columns if c not in ("ts", "open", "high", "low", "close", "volume")]
    o = pd.DataFrame({p + c: d[c].to_numpy() for c in cols}, index=d.index)
    o.insert(0, "ts", d.ts.to_numpy())
    return o


def market_feats(data_dir, market: str, base_tf: str, mode: str, names: list[str] | None = None) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """The market ticker's readings: every indicator reading plus a few location readings."""
    ind = indicators(data_dir, market, sorted({"1D", base_tf}), mode, names)
    d = h = None

    def keep(f, p):
        own = set(ind_readings(ind[next(iter(ind))], names).columns) if ind else set()
        return f[[c for c in f if c == "ts" or c[len(p):] in own or any(k in c for k in MARKET_KEEP)]]
    if "1D" in ind:
        d = keep(tf_feats(ind["1D"], "mktD_", names), "mktD_")
    if base_tf != "1D" and base_tf in ind:
        h = keep(tf_feats(ind[base_tf], "mktH1_", names), "mktH1_")
    return d, h


# ── simulation: exits that follow momentum ────────────────────────────────────
EXIT_REASONS = {1: "momentum trail", 2: "exhaustion", 3: "option expiry", 4: "data ended (censored)"}
EXIT_REASONS_UNDERLYING = {**EXIT_REASONS, 3: "time limit"}
# For shares, futures and crypto the trail's time limit, in trading days (options use the expiry instead)
HOLD_DAYS = {0.75: 5, 1.5: 10}

def sim(F: pd.DataFrame, side: str, k: float, jend: np.ndarray, expiry: np.ndarray, first_k: float,
        xs: np.ndarray | None = None, xthr: float = 0.0, detail: bool = False):
    """Enter at each bar's close. Exit when price turns k x day-ATR off its best point since entry,
    when an exhaustion score xs[j] >= xthr while in profit (optional), or at the option's expiry.
    Returns the payoff (option multiple; or, with expiry=None, the position's fractional return),
    hold (bars), first-move flag (+1 our way first, -1 against first, 0 neither),
    and censored (data ended before the trade did). With detail=True also the exit bar index, the
    underlying exit price and the exit reason (see EXIT_REASONS)."""
    c, h, l, o, atr = (F[x].to_numpy(float) for x in ("close", "high", "low", "open", "d_atr"))
    n = len(F)
    call = side == "C"
    Sx = np.full(n, np.nan)
    jx = np.full(n, -1)
    fp = np.zeros(n, np.int8)
    cens = np.zeros(n, bool)
    why = np.zeros(n, np.int8)
    for i in range(n):
        a = atr[i]
        if not (a > 0) or min(jend[i], n - 1) <= i:     # no later bar to exit on
            continue
        e = min(jend[i], n - 1)
        best = c[i]
        px, jj = c[e], e
        rs = 4 if jend[i] >= n else 3
        cens[i] = jend[i] >= n            # the option outlives the data: result is censored
        for j in range(i + 1, e + 1):
            if call:
                if fp[i] == 0:
                    if l[j] <= c[i] - first_k * a:
                        fp[i] = -1
                    elif h[j] >= c[i] + first_k * a:
                        fp[i] = 1
                lev = best - k * a
                if l[j] <= lev:
                    px, jj = min(o[j], lev), j
                    cens[i] = False
                    rs = 1
                    break
                if xs is not None and xs[j] >= xthr and c[j] > c[i]:
                    px, jj = c[j], j
                    cens[i] = False
                    rs = 2
                    break
                best = max(best, h[j])
            else:
                if fp[i] == 0:
                    if h[j] >= c[i] + first_k * a:
                        fp[i] = -1
                    elif l[j] <= c[i] - first_k * a:
                        fp[i] = 1
                lev = best + k * a
                if h[j] >= lev:
                    px, jj = max(o[j], lev), j
                    cens[i] = False
                    rs = 1
                    break
                if xs is not None and xs[j] >= xthr and c[j] < c[i]:
                    px, jj = c[j], j
                    cens[i] = False
                    rs = 2
                    break
                best = min(best, l[j])
        Sx[i], jx[i], why[i] = px, jj, rs
    ok = jx >= 0
    mult = np.full(n, np.nan)
    if expiry is None:                       # shares, futures, crypto: the trade's own return
        sign = 1.0 if call else -1.0
        mult[ok] = sign * (Sx[ok] - c[ok]) / c[ok]
        hold = np.where(ok, jx - np.arange(n), np.nan)
        if detail:
            return mult, hold, fp, cens, jx, Sx, why
        return mult, hold, fp, cens
    dts = F.date.to_numpy().astype("datetime64[D]")
    fr = F.frac.to_numpy(float)
    iv = F.iv.to_numpy(float)
    exp = np.asarray(expiry).astype("datetime64[D]")
    if ok.any():
        T0 = options.years_to_expiry(dts[ok], fr[ok], exp[ok])
        jo = jx[ok]
        T1 = options.years_to_expiry(dts[jo], fr[jo], exp[ok])
        m, _ = options.multiple(c[ok], Sx[ok], T0, T1, iv[ok], call)
        mult[ok] = m
    hold = np.where(ok, jx - np.arange(n), np.nan)
    if detail:
        return mult, hold, fp, cens, jx, Sx, why
    return mult, hold, fp, cens


def trade_windows(F: pd.DataFrame, trade_as: str = "options") -> tuple[dict, dict]:
    """Per trail size k: (options) the expiry for an entry at each bar, fixed at entry, or
    (underlying) None; and the last bar index the trade may run to. Past the data -> n (censored)."""
    n = len(F)
    dts = F.date.to_numpy().astype("datetime64[D]")
    if trade_as != "options":
        days = np.unique(dts)
        di = np.searchsorted(days, dts)
        jend, exp = {}, {}
        for k, h in HOLD_DAYS.items():
            target = di + h
            last = np.searchsorted(dts, days[np.minimum(target, len(days) - 1)], side="right") - 1
            jend[k] = np.where(target >= len(days), n, last)
            exp[k] = None
        return exp, jend
    exp = {k: options.expiry_after(dts, census.EXPIRY_SESSIONS[k]) for k in census.INTRADAY_K}
    jend = {k: np.searchsorted(dts, exp[k], side="right") - 1 for k in exp}
    for k in exp:
        jend[k] = np.where(exp[k] > dts[-1], n, jend[k])
    return exp, jend


def day_windows(F: pd.DataFrame, trade_as: str = "options") -> tuple[np.ndarray | None, np.ndarray]:
    """Same-day trades: closed by the session's last bar; options use this week's expiry (the Friday
    on/after the entry date)."""
    dts = F.date.to_numpy().astype("datetime64[D]")
    jend = np.searchsorted(dts, dts, side="right") - 1
    if trade_as != "options":
        return None, jend
    wd = (dts.view("int64") - 4) % 7                    # 0 = Monday (1970-01-01 was a Thursday)
    return dts + ((4 - wd) % 7).astype("timedelta64[D]"), jend


# ── per-ticker build ──────────────────────────────────────────────────────────
def build_intraday(data_dir, ticker: str, market: tuple, mode: str, label_ahead: int = 3,
                   names: list[str] | None = None, trade_as: str = "options") -> dict | None:
    """Base timeframe 1h. Returns {'bars': per-bar frame, 'legs': legs (1h and 1D), 'exit_rows': ...}.
    trade_as: "options" (at-the-money options; stocks only) or "underlying" (the instrument itself)."""
    from ..assets import lookup
    inst = lookup(data_dir, ticker)
    ses = inst.session
    if trade_as == "options" and inst.asset != "stock":
        raise ValueError(f"{ticker} is a {inst.asset}; options are modelled for stocks only — set trade_as = \"underlying\"")
    tfs = ["1h", "4h", "1D", "15m", "3m"]
    ind = indicators(data_dir, ticker, tfs, mode, names)
    if "1h" not in ind or "1D" not in ind:
        return None
    h1 = ind["1h"]
    F = tf_feats(h1, "h1_", names)
    for x in ("open", "high", "low", "close", "volume"):
        F[x] = h1[x].to_numpy(float)
    F["date"] = ses.trade_date(F.ts).to_numpy()
    daily = store.read(data_dir, "1D", ticker)
    ctx = census.daily_context(daily, ses)
    F = F.merge(ctx[["date", "prev_atr", "prev_rv", "prev_high", "prev_low", "prev_close"]], on="date", how="left")
    F = F.rename(columns={"prev_atr": "d_atr", "prev_rv": "rv"})
    A = F.d_atr
    g = F.groupby("date")
    dopen = g.open.transform("first")
    dhi, dlo = g.high.cummax(), g.low.cummin()
    F["gap_open_atr"] = (dopen - F.prev_close) / A
    F["from_open_atr"] = (F.close - dopen) / A
    F["vs_prev_high_atr"] = (F.close - F.prev_high) / A
    F["vs_prev_low_atr"] = (F.close - F.prev_low) / A
    F["day_range_pos"] = (F.close - dlo) / (dhi - dlo).replace(0, np.nan)
    F["day_range_atr"] = (dhi - dlo) / A
    F["up_from_20bar_low_atr"] = (F.close - F.low.rolling(20).min()) / A
    F["down_from_20bar_high_atr"] = (F.high.rolling(20).max() - F.close) / A
    F["bars_since_20bar_low"] = 19 - F.low.rolling(20).apply(np.argmin, raw=True)
    F["bars_since_20bar_high"] = 19 - F.high.rolling(20).apply(np.argmax, raw=True)
    local = F.ts.dt.tz_convert(ses.tz)
    F["hour"] = local.dt.hour + local.dt.minute / 60
    F["weekday"] = pd.to_datetime(F.date).dt.day_of_week
    F = F.drop(columns=["prev_high", "prev_low", "prev_close"])
    for tf, strict in (("4h", True), ("1D", True), ("15m", False), ("3m", False)):
        if tf in ind:
            F = _asof(F, tf_feats(ind[tf], INTRADAY_PREFIX[tf], names), strict)
    F = _asof(F, raw_frame(h1, RAW_PREFIX["1h"]), False)
    for tf in ("4h", "1D"):
        if tf in ind:
            F = _asof(F, raw_frame(ind[tf], RAW_PREFIX[tf]), True)
    mD, mH = market
    if mD is not None:
        F = _asof(F, mD, True)
    if mH is not None:
        F = _asof(F, mH, False)
    F = F.reset_index(drop=True)
    F["ticker"] = ticker
    F["asset"] = inst.asset
    F["multiplier"] = inst.multiplier
    n = len(F)
    if trade_as == "options":
        F["frac"] = options.day_fraction_left(F.ts)
        F["iv"] = options.iv_from_rv(F.rv)
    exp, jend = trade_windows(F, trade_as)
    exp_day, jend_day = day_windows(F, trade_as)
    pay = "mult" if trade_as == "options" else "ret"
    (t1, v1), (t2, v2) = census.TIERS["options" if trade_as == "options" else "underlying"]
    # legs
    legs_h = census.legs_for(h1[["ts", "open", "high", "low", "close", "volume"]], daily, ticker, "1h", inst, trade_as)
    legs_d = census.legs_for(daily, daily, ticker, "1D", inst, trade_as)
    # labels: a leg of at least tier-1 / tier-2 size starts within the next 0..label_ahead bars
    for side in ("C", "P"):
        Ls = legs_h[legs_h.side == side] if len(legs_h) else legs_h
        best = np.zeros(n)
        l1 = np.zeros(n, bool)
        l3 = np.zeros(n, bool)
        for si, gi in zip(Ls.entry_i.to_numpy() if len(Ls) else [], Ls["size"].to_numpy() if len(Ls) else []):
            lo_ = max(0, si - label_ahead)
            best[lo_:si + 1] = np.maximum(best[lo_:si + 1], gi)
            if gi >= v1:
                l1[lo_:si + 1] = True
            if gi >= v2:
                l3[lo_:si + 1] = True
        F[f"{side}_{t1}"], F[f"{side}_{t2}"], F[f"{side}_bestsize"] = l1, l3, best
        for k in census.INTRADAY_K:
            m, hd, fp, cz = sim(F, side, k, jend[k], exp[k], first_k=0.75)
            nm = f"t{int(k * 100):03d}"
            F[f"{side}_{nm}_{pay}"], F[f"{side}_{nm}_hold"], F[f"{side}_{nm}_censored"] = m, hd, cz
            if k == 0.75:
                F[f"{side}_first"] = fp
        # same-day: a day-size (0.75 ATR) leg of at least tier-1 size that starts within 0-2 bars AND ends
        # the same session; closed by the session's last bar (options: this week's expiry)
        sd = np.zeros(n, bool)
        if len(Ls):
            for si, gi, kk, hz in zip(Ls.entry_i.to_numpy(), Ls["size"].to_numpy(), Ls.k_atr.to_numpy(), Ls.horizon.to_numpy()):
                if kk == 0.75 and hz == "same-day" and gi >= v1:
                    sd[max(0, si - 2):si + 1] = True
        F[f"{side}_sameday{t1}"] = sd
        m, hd, _, cz = sim(F, side, 0.75, jend_day, exp_day, first_k=0.75)
        F[f"{side}_sd075_{pay}"], F[f"{side}_sd075_hold"], F[f"{side}_sd075_censored"] = m, hd, cz
    # exit rows: every bar inside a tier-1 leg, and how much was left to the leg's best price
    ex = []
    hi, lo, cl, atr = F.high.to_numpy(), F.low.to_numpy(), F.close.to_numpy(), F.d_atr.to_numpy()
    for r in legs_h[legs_h["size"] >= v1].itertuples() if len(legs_h) else []:
        si, bi = int(r.entry_i), int(r.exit_i)
        if bi <= si + 1:
            continue
        e = si + (np.argmax(hi[si:bi + 1]) if r.side == "C" else np.argmin(lo[si:bi + 1]))
        top = hi[e] if r.side == "C" else lo[e]
        for i in range(si + 1, bi + 1):
            rem = (top - cl[i]) / atr[i] if r.side == "C" else (cl[i] - top) / atr[i]
            ex.append((ticker, i, r.side, r.k_atr, rem, r.size, i - si))
    EX = pd.DataFrame(ex, columns=["ticker", "i", "side", "k", "remaining_atr", "leg_size", "bars_in"])
    return {"bars": F, "legs": pd.concat([legs_h, legs_d], ignore_index=True), "exit_rows": EX}
