"""Exhaustion exit score and the trade check (method steps 9-10).

Exhaustion: for every bar inside a >=1x leg, the label is "spent" = less than 0.25 day-ATR left
to the leg's best price. The same scorecard machinery learns which readings mark it (one half ->
the other). A bar's exhaustion flag is ON when its held-out score is in the top 20% of the
learning half's in-leg bars.

Trade check: on the SAME entries, compare
  (1) momentum trail: exit when price turns k x day-ATR off its best point since entry, and
  (2) trail + exhaustion: also exit when the exhaustion flag is on and the trade is in profit.
Entries graded A/B (per the prereg) versus ALL bars — a grade is worth something only if it
beats the plain baseline. Options are modelled (Black-Scholes, no spread).
A complete prereg.md is REQUIRED before this runs.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

from . import census, scorecard, snapshot

REQUIRED = ("idea", "entry", "exit", "measure", "pass_mark")
DEFAULTS = {"label": "C_1x", "grades": "A, B", "trail_k": "0.75", "exhaustion": "yes", "min_premium": "0.20", "signal": "",
            "same_day": "no"}

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


class PreregMissing(RuntimeError):
    pass


def read_prereg(path: Path) -> dict:
    if not path.exists():
        raise PreregMissing(f"{path} does not exist. Run `kit study new <name>` and fill it in first.")
    text = path.read_text()
    head = re.split(r"^## Verdict", text, maxsplit=1, flags=re.M)[0]
    out = {"_sha256": hashlib.sha256(head.encode()).hexdigest()[:16]}
    for line in head.splitlines():
        m = re.match(r"^\s*([a-z_]+)\s*:\s*(.*)$", line)
        if m:
            val = re.split(r"\s{2,}#", m.group(2))[0].strip()
            out[m.group(1)] = val
    for k, v in DEFAULTS.items():
        out.setdefault(k, v)
    return out


def valid_labels(trade_as: str = "options") -> list[str]:
    (t1, _), (t2, _) = census.TIERS["options" if trade_as == "options" else "underlying"]
    return [f"{s}_{t}" for s in ("C", "P") for t in (t1, t2)] + [f"C_sameday{t1}", f"P_sameday{t1}"]


def prereg_problems(p: dict, trade_as: str = "options") -> list[str]:
    probs = []
    for k in REQUIRED:
        v = p.get(k, "")
        if not v or v.upper().startswith("TODO"):
            probs.append(f"`{k}:` is not filled in")
    labs = valid_labels(trade_as)
    if not p.get("signal") and p.get("label") not in labs:
        probs.append(f"`label:` must be one of {', '.join(labs)}")
    try:
        if float(p.get("trail_k")) not in census.INTRADAY_K:
            probs.append(f"`trail_k:` must be one of {census.INTRADAY_K}")
    except (TypeError, ValueError):
        probs.append("`trail_k:` must be a number")
    return probs


def exhaustion_scores(D: pd.DataFrame, EX: pd.DataFrame, num, cat, mins) -> tuple[dict, dict]:
    """Returns {(side, k): held-out score - threshold for every bar} and a summary table per model."""
    xs, tables = {}, {}
    if EX.empty:
        return xs, tables
    X = D.iloc[EX.row.to_numpy()].reset_index(drop=True)
    X = pd.concat([X, EX[["side", "k", "remaining_atr", "bars_in"]].reset_index(drop=True)], axis=1)
    X["spent"] = X.remaining_atr < 0.25
    for side in ("C", "P"):
        for k in census.INTRADAY_K:
            Xs = X[(X.side == side) & (X.k == k)].reset_index(drop=True)
            if Xs.period.nunique() < 2 or Xs.spent.nunique() < 2:
                continue
            s, qs, W = scorecard.crossfit(Xs, num, cat, "spent", mins=mins)
            a = {h: scorecard.auc(s[(Xs.period == h).to_numpy()], Xs.spent.to_numpy()[(Xs.period == h).to_numpy()]) for h in ("P1", "P2")}
            pos, neg = scorecard.agree_weights(W, top=10)
            dec = scorecard.deciles(Xs.assign(spent=Xs.spent), s, "spent")
            col = np.full(len(D), np.nan)
            for tr, te in (("P1", "P2"), ("P2", "P1")):
                mtr = (Xs.period == tr).to_numpy()
                spec = scorecard.fit_spec(Xs[mtr], num, cat, min_num=mins[0], min_cat=mins[1])
                Mtr, _ = scorecard.encode(Xs[mtr], spec)
                w = scorecard.fit_lr(Mtr, Xs.spent.to_numpy()[mtr])
                thr = np.quantile(Mtr @ w[1:] + w[0], 0.80)
                mte = (D.period == te).to_numpy()
                Mte, _ = scorecard.encode(D[mte], spec)
                col[mte] = Mte @ w[1:] + w[0] - thr
            xs[(side, k)] = col
            tables[f"{side}_{k}"] = {
                "in_leg_bars": len(Xs), "spent_base_pct": {h: round(100 * Xs.spent[Xs.period == h].mean(), 1) for h in ("P1", "P2")},
                "auc": {h: round(v, 3) for h, v in a.items()}, "spent_lift_by_decile": dec,
                "says_spent": pos, "says_more_left": neg}
    return xs, tables


def _stats(mu: np.ndarray, hold: np.ndarray, cens: np.ndarray) -> dict:
    ok = np.isfinite(mu)
    m = mu[ok]
    if len(m) == 0:
        return {"trades": 0}
    return {"trades": int(len(m)), "median_mult": round(float(np.median(m)), 2), "mean_mult_cap20": round(float(np.mean(np.clip(m, 0, 20))), 2),
            "pct_doubled": round(100 * float((m >= 2).mean()), 1), "pct_4x": round(100 * float((m >= 4).mean()), 1),
            "pct_lost_half": round(100 * float((m <= 0.5).mean()), 1), "median_hold_bars": round(float(np.nanmedian(hold[ok])), 1),
            "pct_censored": round(100 * float(cens[ok].mean()), 1)}


def _stats_underlying(ret: np.ndarray, r_atr: np.ndarray, hold: np.ndarray, cens: np.ndarray) -> dict:
    ok = np.isfinite(ret)
    r, a = ret[ok], r_atr[ok]
    if len(r) == 0:
        return {"trades": 0}
    return {"trades": int(len(r)), "median_return_pct": round(100 * float(np.median(r)), 2),
            "mean_return_pct": round(100 * float(np.mean(r)), 2), "win_rate_pct": round(100 * float((r > 0).mean()), 1),
            "median_r_atr": round(float(np.nanmedian(a)), 2), "pct_gained_1atr": round(100 * float((a >= 1).mean()), 1),
            "pct_lost_half_atr": round(100 * float((a <= -0.5).mean()), 1), "median_hold_bars": round(float(np.nanmedian(hold[ok])), 1),
            "pct_censored": round(100 * float(cens[ok].mean()), 1)}


def _tail(sub: pd.DataFrame) -> dict:
    """How much of the profit came from the top 3 days / top 3 tickers. `pnl` is per-trade profit
    in units that add up (options: premiums won; underlying: day-ATRs won)."""
    if sub.empty:
        return {}
    pnl = sub["pnl"]
    tot = pnl[pnl > 0].sum()
    if tot <= 0:
        return {"profit_share_top3_days_pct": None, "profit_share_top3_tickers_pct": None}
    byday = pnl.groupby(sub["date"]).sum().sort_values(ascending=False)
    bytk = pnl.groupby(sub["ticker"]).sum().sort_values(ascending=False)
    rest = sub[~sub["date"].isin(byday.index[:3])]
    return {"profit_share_top3_days_pct": round(100 * byday.head(3).clip(lower=0).sum() / tot, 1),
            "profit_share_top3_tickers_pct": round(100 * bytk.head(3).clip(lower=0).sum() / tot, 1),
            "median_pnl_without_top3_days": round(float(rest["pnl"].median()), 2) if len(rest) else None}


def entry_selection(D: pd.DataFrame, prereg: dict, sig_eval: dict | None) -> tuple[np.ndarray, str, str]:
    """Which bars are entries: a signal's entries (prereg `signal:`), else the grades of a label."""
    name = (prereg.get("signal") or "").strip()
    if name:
        if not sig_eval or name not in sig_eval:
            raise KeyError(f"prereg names signal {name!r}, but the study has no such signal ({sorted(sig_eval or {})})")
        e = sig_eval[name]
        return e["entries"], e["side"], f"signal {name}"
    lab = prereg["label"]
    grades = [g.strip().upper() for g in prereg["grades"].split(",") if g.strip()]
    gcol = D[f"grade_{lab}"].astype(str).str[0].to_numpy()
    m = np.isin(gcol, grades)
    tk = D.ticker.to_numpy()
    prev = np.r_[False, m[:-1]] & (tk == np.r_[None, tk[:-1]])
    return m & ~prev, lab[0], f"{lab} grades {'+'.join(grades)}"     # first bar of each run = one trade


def _agg(g, under: bool) -> pd.DataFrame:
    if under:
        return g.agg(trades=("return_pct", "size"), median_return_pct=("return_pct", "median"),
                     win_rate_pct=("return_pct", lambda m: 100 * (m > 0).mean()),
                     atr_won=("r_atr", "sum")).reset_index()
    return g.agg(trades=("multiple", "size"), median_mult=("multiple", "median"),
                 pct_doubled=("multiple", lambda m: 100 * (m >= 2).mean()),
                 units_won=("multiple", lambda m: (m - 1).clip(lower=-1).sum())).reset_index()


def _monthly(T: pd.DataFrame, under: bool = False) -> pd.DataFrame:
    if T.empty:
        return pd.DataFrame()
    return _agg(T.groupby([T.entry_time.str[:7].rename("month"), "exit_rule"]), under).round(2)


def _by_ticker(T: pd.DataFrame, under: bool = False) -> pd.DataFrame:
    if T.empty:
        return pd.DataFrame()
    out = _agg(T[T.exit_rule == "momentum trail"].groupby("ticker"), under)
    return out.sort_values("atr_won" if under else "units_won", ascending=False).round(2)


def run(D: pd.DataFrame, prereg: dict, xs: dict, sig_eval: dict | None = None, trade_as: str = "options") -> dict:
    """trade_as "options": each entry buys an at-the-money option (stocks only).
    trade_as "underlying": each entry buys (C) or sells short (P) the instrument itself; results are
    returns, moves in day-ATR and, for futures, dollars per contract."""
    from . import snapshot
    from .options import bs, years_to_expiry
    under = trade_as != "options"
    pay = "ret" if under else "mult"
    sel, side, who = entry_selection(D, prereg, sig_eval)
    k = float(prereg["trail_k"])
    same_day = str(prereg.get("same_day", "no")).lower().startswith("y") or "sameday" in str(prereg.get("label", "") if not prereg.get("signal") else "")
    if same_day:
        k = 0.75
    min_prem = float(prereg.get("min_premium", 0.2))
    nm = "sd075" if same_day else f"t{int(k * 100):03d}"
    base_mult = D[f"{side}_{nm}_{pay}"].to_numpy()
    base_hold = D[f"{side}_{nm}_hold"].to_numpy()
    base_cens = D[f"{side}_{nm}_censored"].to_numpy().astype(bool)
    use_ex = prereg.get("exhaustion", "yes").lower().startswith("y") and (side, k) in xs
    rules = ["momentum trail"] + (["trail + exhaustion"] if use_ex else [])
    res = {r: {c: np.full(len(D), np.nan) for c in ("mult", "hold", "j", "px", "why")} | {"cens": np.zeros(len(D), bool)} for r in rules}
    prem = np.full(len(D), np.nan)
    expiry = np.full(len(D), np.datetime64("NaT", "D"), dtype="datetime64[D]")
    for tk, g in D.groupby("ticker", sort=False):
        idx = g.index.to_numpy()
        if not sel[idx].any():
            continue
        F = g.reset_index(drop=True)
        if same_day:
            e_, j_ = snapshot.day_windows(F, trade_as)
            exp, jend = {k: e_}, {k: j_}
        else:
            exp, jend = snapshot.trade_windows(F, trade_as)
        if not under:
            expiry[idx] = exp[k]
            T0 = years_to_expiry(F.date.to_numpy().astype("datetime64[D]"), F.frac.to_numpy(), exp[k])
            prem[idx] = bs(F.close, F.close, T0, F.iv, side == "C")
        for r in rules:
            kw = {"xs": xs[(side, k)][idx], "xthr": 0.0} if r == "trail + exhaustion" else {}
            m, hd, _, cz, jx, sx, why = snapshot.sim(F, side, k, jend[k], exp[k], 0.75, detail=True, **kw)
            R = res[r]
            R["mult"][idx], R["hold"][idx], R["cens"][idx] = m, hd, cz
            R["j"][idx] = np.where(jx >= 0, idx[np.clip(jx, 0, len(idx) - 1)], -1)
            R["px"][idx], R["why"][idx] = sx, why
    ok_prem = np.ones(len(D), bool) if under else prem >= min_prem
    close, datr = D.close.to_numpy(float), D.d_atr.to_numpy(float)
    to_atr = close / np.where(datr > 0, datr, np.nan)          # fractional return -> move in day-ATR

    def stats(mu, hold, cens, m):
        if under:
            return _stats_underlying(mu[m], (mu * to_atr)[m], hold[m], cens[m])
        return _stats(mu[m], hold[m], cens[m])
    rows = []
    for te in ("P1", "P2"):
        mh = (D.period == te).to_numpy()
        ent = sel & mh & ok_prem
        for r in rules:
            row = {"half": te, "entries": who, "exit": r}
            row.update(stats(res[r]["mult"], res[r]["hold"], res[r]["cens"], ent))
            rows.append(row)
        row = {"half": te, "entries": "all bars (baseline)", "exit": "momentum trail"}
        row.update(stats(base_mult, base_hold, base_cens, mh))
        rows.append(row)
    # the trade log: one row per entry per exit rule
    ent = np.flatnonzero(sel & ok_prem)
    gcol = f"grade_{prereg.get('label') or f'{side}_' + census.TIERS['options' if not under else 'underlying'][0][0]}"
    logs = []
    for r in rules:
        R = res[r]
        j = R["j"][ent].astype(int)
        okj = j >= 0
        e, j = ent[okj], j[okj]
        base = {
            "ticker": D.ticker.to_numpy()[e], "half": D.period.to_numpy()[e],
            "side": ("long" if side == "C" else "short") if under else ("call" if side == "C" else "put"),
            "entries": who, "exit_rule": r,
            "entry_time": D.ts.iloc[e].astype(str).str[:16].to_numpy(), "entry_price": D.close.to_numpy()[e].round(4)}
        if under:
            reasons = snapshot.EXIT_REASONS_UNDERLYING
            sign = 1.0 if side == "C" else -1.0
            pts = sign * (R["px"][e] - close[e])
            mult_ = D["multiplier"].to_numpy(float)[e] if "multiplier" in D else np.ones(len(e))
            extra = {"exit_time": D.ts.iloc[j].astype(str).str[:16].to_numpy(), "exit_price": R["px"][e].round(4),
                     "exit_reason": [reasons.get(int(w), "?") for w in R["why"][e]],
                     "points": pts.round(4), "return_pct": (100 * R["mult"][e]).round(2),
                     "r_atr": (R["mult"][e] * to_atr[e]).round(2),
                     "dollars_per_unit": (pts * mult_).round(2)}
            if "asset" in D:
                extra["asset"] = D["asset"].to_numpy()[e]
        else:
            extra = {"strike": D.close.to_numpy()[e].round(4), "expiry": pd.to_datetime(expiry[e]).strftime("%Y-%m-%d"),
                     "premium": prem[e].round(4), "exit_time": D.ts.iloc[j].astype(str).str[:16].to_numpy(),
                     "exit_price": R["px"][e].round(4),
                     "exit_reason": [snapshot.EXIT_REASONS.get(int(w), "?") for w in R["why"][e]],
                     "option_value_at_exit": (R["mult"][e] * prem[e]).round(4), "multiple": R["mult"][e].round(3),
                     "return_pct": (100 * (R["mult"][e] - 1)).round(1)}
        extra |= {"hold_bars": R["hold"][e].astype(int),
                  "grade": D[gcol].astype(str).str[0].to_numpy()[e] if gcol in D else ""}
        logs.append(pd.DataFrame(base | extra))
    T = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame()
    mt = res["momentum trail"]["mult"][sel & ok_prem]
    pnl = mt * to_atr[sel & ok_prem] if under else np.clip(mt - 1, -1, None)
    sub = D.loc[sel & ok_prem, ["date", "ticker"]].assign(pnl=pnl)
    tt = T[T.exit_rule == "momentum trail"] if len(T) else T
    key = "r_atr" if under else "multiple"
    return {"label": prereg.get("label"), "signal": prereg.get("signal") or None, "entries": who, "side": side,
            "same_day": same_day,
            "trail_k": k, "grades": [g.strip() for g in prereg.get("grades", "").split(",")],
            "trade_as": trade_as,
            "min_premium": None if under else min_prem,
            "dropped_tiny_premium": 0 if under else int((~ok_prem & sel & np.isfinite(prem)).sum()),
            "exhaustion_compared": use_ex, "table": pd.DataFrame(rows), "trades": T,
            "monthly": _monthly(T, under), "by_ticker": _by_ticker(T, under),
            "best": tt.sort_values(key, ascending=False).head(10) if len(tt) else tt,
            "worst": tt.sort_values(key).head(10) if len(tt) else tt,
            "tail_concentration": _tail(sub.dropna()),
            "result_key": key,
            "multiples_trail": [round(float(x), 3) for x in tt[key].dropna()] if len(tt) else []}
