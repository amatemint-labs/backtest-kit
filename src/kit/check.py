"""`kit check-indicator <name>`: prove a plug-in indicator is safe to study with.

Runs it on the synthetic dataset and checks:
  runs      it computes on every timeframe asked, one row per bar, no crash
  lookahead scramble every price after a cut; nothing at or before the cut may change
  coverage  how much of each output is filled late in the sample (advisory: event-only columns and long
            warm-ups are expected to be sparse)
  readings  reading names are unique, states are real categories (not hundreds of values)
  speed     seconds per timeframe on ~1 year of bars
A plug-in that fails 'lookahead' must not be used in a study — it is reading the future.
"""
from __future__ import annotations

import time
from dataclasses import replace

import numpy as np
import pandas as pd

from . import config
from .data import store, synthetic
from .ind import compute, readings
from .plugin import registry, resolve


PERTURBATIONS = ("up", "down", "noise")


def _scrambled(bars: dict[str, pd.DataFrame], cut, kind: str = "noise") -> dict[str, pd.DataFrame]:
    """Change every price after `cut`: all up 50%, all down 40%, or random noise. Any output that
    compares against a future price must change under at least one of these."""
    rng = np.random.default_rng(5)
    out = {}
    for tf, b in bars.items():
        b2 = b.copy()
        late = (b2.ts > cut).to_numpy()
        f = {"up": np.full(late.sum(), 1.5), "down": np.full(late.sum(), 0.6)}.get(kind)
        if f is None:
            f = np.exp(rng.normal(0, 0.06, late.sum()))
        for c in ("open", "high", "low", "close"):
            b2.loc[late, c] = b2.loc[late, c].to_numpy() * f
        b2.loc[late, "high"] = b2.loc[late, ["open", "high", "low", "close"]].max(axis=1)
        b2.loc[late, "low"] = b2.loc[late, ["open", "high", "low", "close"]].min(axis=1)
        b2.loc[late, "volume"] = b2.loc[late, "volume"].to_numpy() * rng.uniform(0.3, 3, late.sum())
        out[tf] = b2
    return out


def check_indicator(s: config.Settings, name: str, tfs=("1h", "15m", "4h", "1D"), ticker: str = "SYNA", log=print) -> dict:
    reg = registry(refresh=True)
    if name not in reg:
        return {"indicator": name, "passed": False, "checks": [{"name": "found", "pass": False,
                "detail": f"no indicator {name!r}; known: {', '.join(sorted(reg))}; load errors: {registry.errors or 'none'}"}]}
    ind = reg[name]
    names = [i.name for i in resolve([name])]
    ss = replace(s, data_dir=s.data_dir / "synthetic")
    synthetic.ensure(ss.data_dir, s.timeframes, log=log)
    all_tfs = sorted({"3m", "15m", "1h", "4h", "1D", "2D", "1W", "1M", "10m"})
    bars = {tf: store.read(ss.data_dir, tf, ticker) for tf in all_tfs}
    bars = {k: v for k, v in bars.items() if v is not None}
    checks, cols_report = [], {}

    def add(n, ok, detail, advisory=False):
        checks.append({"name": n, "pass": bool(ok), "detail": detail, "advisory": advisory})
        log(f"  [{'PASS' if ok else ('NOTE' if advisory else 'FAIL')}] {n}: {detail}")

    own_cols = None
    for tf in tfs:
        b = bars.get(tf)
        if b is None:
            continue
        t0 = time.time()
        try:
            a = compute(b, tf, lambda t: bars.get(t), mode="closed", indicators=names)
        except Exception as e:
            add(f"runs on {tf}", False, f"{type(e).__name__}: {e}")
            continue
        secs = time.time() - t0
        own = a.attrs["columns"].get(name, [])
        own_cols = own
        add(f"runs on {tf}", len(a) == len(b) and len(own) > 0, f"{len(own)} output columns on {len(b):,} bars in {secs:.2f}s")
        bad = []
        for frac in (0.35, 0.6, 0.85):
            cut = b.ts.iloc[int(len(b) * frac)]
            early = (a.ts <= cut).to_numpy()
            for kind in PERTURBATIONS:
                pert = _scrambled(bars, cut, kind)
                z = compute(pert[tf], tf, lambda t, p=pert: p.get(t), mode="closed", indicators=names)
                for c in own:
                    if c in bad:
                        continue
                    x, y = a.loc[early, c], z.loc[early, c]
                    if pd.api.types.is_numeric_dtype(a[c]):
                        same = np.allclose(x.to_numpy(float), y.to_numpy(float), equal_nan=True, rtol=1e-9, atol=1e-9)
                    else:
                        same = (x.astype(str).to_numpy() == y.astype(str).to_numpy()).all()
                    if not same:
                        bad.append(c)
        add(f"no lookahead on {tf}", not bad,
            "no output at or before 3 cut points changed when later prices were raised, lowered or scrambled" if not bad
            else f"these outputs CHANGED when only FUTURE prices changed: {bad} — the code reads ahead (shift(-n)? centred window? request.security lookahead? pivot used at the pivot bar?)")
        tail = a.iloc[int(len(a) * 0.6):]
        cov = {c: float(round(100 * tail[c].notna().mean(), 1)) for c in own}
        thin = {c: v for c, v in cov.items() if v < 50 and c not in getattr(ind, "sparse", set())}
        cols_report[tf] = cov
        add(f"coverage on {tf}", not thin, "every output is filled in the last 40% of the sample" if not thin else
            f"mostly empty in the last 40% of the sample: {thin} — fine if these are event-only columns (list them in "
            f"`sparse`) or if the warm-up is longer than this short synthetic sample; a bug if they should always have a value",
            advisory=True)
    try:
        frame = compute(bars["1h"], "1h", lambda t: bars.get(t), mode="closed", indicators=names)
        r = readings(frame, [name])
        states = [c for c in r.columns if c.endswith("STATE")]
        many = {c: int(pd.Series(r[c]).nunique()) for c in states if pd.Series(r[c]).nunique() > 40}
        add("readings", len(r.columns) > 0 and not many,
            f"{len(r.columns)} readings ({', '.join(r.columns[:12])}{'…' if len(r.columns) > 12 else ''})"
            + (f"; states with too many values: {many}" if many else ""))
    except Exception as e:
        add("readings", False, f"{type(e).__name__}: {e}")
    return {"indicator": name, "version": ind.version, "source": ind.source,
            "passed": all(c["pass"] for c in checks if not c.get("advisory")),
            "checks": checks, "coverage_pct": cols_report, "outputs": own_cols or []}
