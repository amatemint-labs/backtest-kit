"""The graded scorecard (method steps 6-8).

Each number is cut into ~8 bins at the LEARNING half's quantiles, plus a "missing" bin; named
states are bins of their own. An L2-penalised logistic regression gives each bin one weight
(an odds multiplier, all else equal). Learn on half P1 and score P2, then swap, so every bar is
scored by a model that never saw it. Grade cut-offs come from the learning half:
top 1% = A, top 5% = B, top 15% = C, the rest D.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize
from scipy.stats import rankdata

GRADES = ["A (top 1%)", "B (top 5%)", "C (top 15%)", "D (rest)"]


def fit_spec(X: pd.DataFrame, num: list[str], cat: list[str], nb: int = 8, min_num: int = 1000, min_cat: int = 300) -> dict:
    spec = {}
    for c in num:
        v = X[c].to_numpy(float)
        v = v[np.isfinite(v)]
        if len(v) < min_num:
            continue
        e = np.unique(np.quantile(v, np.linspace(0, 1, nb + 1)[1:-1]))
        if len(e):
            spec[c] = ("num", e)
    for c in cat:
        vc = X[c].astype(str).value_counts()
        keep = [x for x in vc[vc >= min_cat].index if x != "nan"]
        if keep:
            spec[c] = ("cat", keep)
    return spec


def encode(X: pd.DataFrame, spec: dict):
    n = len(X)
    rr, cc, names = [], [], []
    off = 0
    for c, (kind, e) in spec.items():
        if kind == "num":
            v = X[c].to_numpy(float)
            nb = len(e) + 1
            b = np.where(np.isfinite(v), np.searchsorted(e, v, side="right"), nb)
            lo, hi = np.r_[-np.inf, e], np.r_[e, np.inf]
            names += [(c, f"{lo[j]:.3g}..{hi[j]:.3g}") for j in range(nb)] + [(c, "missing")]
            rr.append(np.arange(n)); cc.append(off + b); off += nb + 1
        else:
            m = {k: j for j, k in enumerate(e)}
            b = X[c].astype(str).map(m).to_numpy()
            ok = pd.notna(b)
            names += [(c, str(k)) for k in e]
            rr.append(np.arange(n)[ok]); cc.append(off + b[ok].astype(int)); off += len(e)
    if not rr:
        return sparse.csr_matrix((n, 0)), names
    r, c_ = np.concatenate(rr), np.concatenate(cc)
    return sparse.csr_matrix((np.ones(len(r)), (r, c_)), shape=(n, off)), names


def fit_lr(M, y, lam: float = 30.0) -> np.ndarray:
    y = np.asarray(y, float)
    p = M.shape[1]
    MT = M.T.tocsr()

    def f(w):
        z = M @ w[1:] + w[0]
        pz = 1 / (1 + np.exp(-z))
        loss = np.sum(np.logaddexp(0, z) - y * z) + 0.5 * lam * np.sum(w[1:] ** 2)
        g = np.empty_like(w)
        r = pz - y
        g[0] = r.sum()
        g[1:] = MT @ r + lam * w[1:]
        return loss, g
    w0 = np.zeros(p + 1)
    m = min(max(y.mean(), 1e-5), 1 - 1e-5)
    w0[0] = np.log(m / (1 - m))
    return minimize(f, w0, jac=True, method="L-BFGS-B", options={"maxiter": 400}).x


def auc(s, y) -> float:
    s, y = np.asarray(s, float), np.asarray(y, bool)
    ok = np.isfinite(s)
    s, y = s[ok], y[ok]
    n1 = y.sum(); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(s)
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def crossfit(D: pd.DataFrame, num, cat, lab: str, lam: float = 30.0, drop=None, mins=(1000, 300)):
    """Held-out score for every row, per-graded-half train quantiles, and both weight vectors."""
    num = [f for f in num if not (drop and drop(f))]
    cat = [f for f in cat if not (drop and drop(f))]
    score = np.full(len(D), np.nan)
    qs, W = {}, {}
    for tr, te in (("P1", "P2"), ("P2", "P1")):
        mtr, mte = (D.period == tr).to_numpy(), (D.period == te).to_numpy()
        if mtr.sum() == 0 or mte.sum() == 0:
            continue
        spec = fit_spec(D[mtr], num, cat, min_num=mins[0], min_cat=mins[1])
        Mtr, names = encode(D[mtr], spec)
        w = fit_lr(Mtr, D[lab].to_numpy()[mtr], lam)
        s_tr = Mtr @ w[1:] + w[0]
        Mte, _ = encode(D[mte], spec)
        score[mte] = Mte @ w[1:] + w[0]
        qs[te] = np.quantile(s_tr, [0.85, 0.95, 0.99])
        W[tr] = (names, w[1:], np.asarray(Mtr.mean(axis=0)).ravel())
    return score, qs, W


def grade(D: pd.DataFrame, score: np.ndarray, qs: dict) -> np.ndarray:
    g = np.full(len(D), GRADES[3], dtype=object)
    for te, q in qs.items():
        m = (D.period == te).to_numpy()
        g[m & (score >= q[0])] = GRADES[2]
        g[m & (score >= q[1])] = GRADES[1]
        g[m & (score >= q[2])] = GRADES[0]
    return g


def agree_weights(W: dict, top: int = 15, min_share: float = 0.01):
    if "P1" not in W or "P2" not in W:
        return pd.DataFrame(), pd.DataFrame()
    t = []
    for h in ("P1", "P2"):
        n, w, s = W[h]
        x = pd.DataFrame({"reading": [a for a, _ in n], "bin": [b for _, b in n], f"w_{h}": w, f"share_{h}": s})
        x["ord"] = x.groupby("reading").cumcount().astype(str)
        isc = x.reading.str.contains("STATE")
        x.loc[isc, "ord"] = x.loc[isc, "bin"]
        t.append(x)
    m = t[0].merge(t[1], on=["reading", "ord"], suffixes=("", "_P2edges"))
    m = m[(m.share_P1 >= min_share) & (m.share_P2 >= min_share) & (np.sign(m.w_P1) == np.sign(m.w_P2))].copy()
    m["weakest"] = np.minimum(m.w_P1.abs(), m.w_P2.abs()) * np.sign(m.w_P1)
    m["odds_x_learned_P1"] = np.exp(m.w_P1).round(2)
    m["odds_x_learned_P2"] = np.exp(m.w_P2).round(2)
    m = m.rename(columns={"bin": "bin (P1 edges)", "bin_P2edges": "bin (P2 edges)"})
    cols = ["reading", "bin (P1 edges)", "bin (P2 edges)", "odds_x_learned_P1", "odds_x_learned_P2"]
    return (m.sort_values("weakest", ascending=False)[cols].head(top).reset_index(drop=True),
            m.sort_values("weakest")[cols].head(top).reset_index(drop=True))


def grade_table(D: pd.DataFrame, g: np.ndarray, lab: str, months: dict) -> pd.DataFrame:
    rows = []
    for te in ("P1", "P2"):
        m = (D.period == te).to_numpy()
        if not m.any():
            continue
        base = D[lab].to_numpy()[m].mean()
        for b in GRADES + ["ALL"]:
            mm = m if b == "ALL" else m & (g == b)
            if mm.sum() == 0:
                continue
            hit = D[lab].to_numpy()[mm]
            r = {"graded_half": te, "grade": b, "bars": int(mm.sum()),
                 "per_month": round(mm.sum() / max(months.get(te, 1), 1e-9), 1),
                 "hit_rate_pct": round(100 * hit.mean(), 2),
                 "lift": round(hit.mean() / base, 2) if base > 0 else None}
            # what an ATM option bought on these bars did under the momentum-trail exit (descriptive)
            side = lab[0]
            for nm in (("sd075",) if "sameday" in lab else ("t075", "t150")):
                col = f"{side}_{nm}_mult"
                if col not in D:
                    continue
                mu = D[col].to_numpy()[mm]
                mu = mu[np.isfinite(mu)]
                if len(mu):
                    r[f"{nm}_median_mult"] = round(float(np.median(mu)), 2)
                    r[f"{nm}_pct_doubled"] = round(100 * float((mu >= 2).mean()), 1)
                    r[f"{nm}_pct_4x"] = round(100 * float((mu >= 4).mean()), 1)
                    r[f"{nm}_pct_lost_half"] = round(100 * float((mu <= 0.5).mean()), 1)
            if f"{side}_first" in D:
                r["broke_first_pct"] = round(100 * float((D[f"{side}_first"].to_numpy()[mm] == -1).mean()), 1)
            rows.append(r)
    return pd.DataFrame(rows)


def deciles(D: pd.DataFrame, s: np.ndarray, lab: str) -> pd.DataFrame:
    out = {}
    for te in ("P1", "P2"):
        m = (D.period == te).to_numpy() & np.isfinite(s)
        if m.sum() < 20:
            continue
        y = D[lab].to_numpy()[m]
        dec = np.ceil(rankdata(s[m]) / m.sum() * 10).astype(int).clip(1, 10)
        base = y.mean()
        out[te] = [round(y[dec == k].mean() / base, 2) if base > 0 and (dec == k).any() else None for k in range(1, 11)]
    t = pd.DataFrame(out, index=[f"decile {k}" for k in range(1, 11)]).T
    t.index.name = "graded_half"
    return t.reset_index()


def group_removal(D, num, cat, lab, groups: dict, a1: float, a2: float, mins) -> pd.DataFrame:
    rows = []
    for gname, fn in groups.items():
        if not any(fn(f) for f in num + cat):
            continue
        s2, _, _ = crossfit(D, num, cat, lab, drop=fn, mins=mins)
        b1 = auc(s2[(D.period == "P1").to_numpy()], D[lab].to_numpy()[(D.period == "P1").to_numpy()])
        b2 = auc(s2[(D.period == "P2").to_numpy()], D[lab].to_numpy()[(D.period == "P2").to_numpy()])
        rows.append({"group removed": gname, "AUC lost (graded P1)": round(a1 - b1, 4), "AUC lost (graded P2)": round(a2 - b2, 4)})
    return pd.DataFrame(rows).sort_values("AUC lost (graded P2)", ascending=False) if rows else pd.DataFrame()


def lookalikes(D: pd.DataFrame, g: np.ndarray, side: str, num, cat, min_n: int = 150, top: int = 12):
    """Inside grades A-C (held out): which readings separate 'went our way first' from 'broke first',
    in BOTH halves. Readings that lower the win-first rate in both halves are the ELIMINATORS."""
    first = D[f"{side}_first"].to_numpy()
    m = np.isin(g, GRADES[:3]) & (first != 0)
    X = D[m].copy()
    if X.empty:
        return {}, pd.DataFrame(), pd.DataFrame()
    X["win"] = first[m] == 1
    base = X.groupby("period").win.mean()
    if not {"P1", "P2"} <= set(base.index):
        return base.to_dict(), pd.DataFrame(), pd.DataFrame()
    out = []
    for c in num + cat:
        if c in num:
            try:
                cut = pd.qcut(X[c], 5, duplicates="drop")
                X["_b"] = cut.map(lambda iv: f"{iv.left:.3g}..{iv.right:.3g}" if pd.notna(iv) else "nan").astype(str)
            except (ValueError, TypeError):
                continue
        else:
            X["_b"] = X[c].astype(str)
        t = X.groupby(["_b", "period"]).win.agg(["size", "mean"]).unstack("period")
        if ("size", "P1") not in t or ("size", "P2") not in t:
            continue
        for b_, r in t.iterrows():
            n1, n2 = r[("size", "P1")], r[("size", "P2")]
            if not (n1 >= min_n and n2 >= min_n) or b_ == "nan":
                continue
            l1, l2 = r[("mean", "P1")] / base["P1"], r[("mean", "P2")] / base["P2"]
            out.append((c, b_, int(n1 + n2), round(100 * r[("mean", "P1")], 1), round(100 * r[("mean", "P2")], 1), round(l1, 2), round(l2, 2)))
    T = pd.DataFrame(out, columns=["reading", "bin", "n", "win_first_P1_pct", "win_first_P2_pct", "x_P1", "x_P2"])
    if T.empty:
        return base.to_dict(), T, T
    T["weakest"] = np.where((T.x_P1 >= 1) & (T.x_P2 >= 1), np.minimum(T.x_P1, T.x_P2),
                            np.where((T.x_P1 < 1) & (T.x_P2 < 1), np.maximum(T.x_P1, T.x_P2), 1))
    good = T[T.weakest > 1].sort_values("weakest", ascending=False).head(top).drop(columns="weakest")
    bad = T[T.weakest < 1].sort_values("weakest").head(top).drop(columns="weakest")
    return base.to_dict(), good.reset_index(drop=True), bad.reset_index(drop=True)


def lift_table(D: pd.DataFrame, keys: list[str], lab: str, min_n: int = 200) -> pd.DataFrame:
    """Rate of the label per state, per half, and lift vs that half's base. Kept only when the state
    was seen >= min_n times in EACH half; ranked by the weaker half's lift."""
    X = D[keys + ["period", lab]].copy()
    for k in keys:
        X[k] = X[k].astype(str)
    X = X[~(X[keys] == "nan").any(axis=1)]
    g = X.groupby(keys + ["period"], observed=True)[lab].agg(["size", "mean"]).unstack("period")
    if ("size", "P1") not in g or ("size", "P2") not in g:
        return pd.DataFrame()
    base = D.groupby("period")[lab].mean()
    g = g[(g[("size", "P1")] >= min_n) & (g[("size", "P2")] >= min_n)]
    if g.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "state": [" + ".join(f"{k}={v}" for k, v in zip(keys, (i if isinstance(i, tuple) else (i,)))) for i in g.index],
        "n": (g[("size", "P1")] + g[("size", "P2")]).astype(int).to_numpy(),
        "rate_P1_pct": (100 * g[("mean", "P1")]).round(2).to_numpy(), "rate_P2_pct": (100 * g[("mean", "P2")]).round(2).to_numpy(),
        "lift_P1": (g[("mean", "P1")] / base["P1"]).round(2).to_numpy(), "lift_P2": (g[("mean", "P2")] / base["P2"]).round(2).to_numpy(),
    })
    up = (out.lift_P1 >= 1) & (out.lift_P2 >= 1)
    dn = (out.lift_P1 < 1) & (out.lift_P2 < 1)
    # the halves disagree -> 1.0 (no lift we can trust)
    out["weaker_lift"] = np.where(up, out[["lift_P1", "lift_P2"]].min(axis=1),
                                  np.where(dn, out[["lift_P1", "lift_P2"]].max(axis=1), 1.0))
    return out
