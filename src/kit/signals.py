"""Signals: your own entry rules, tested on every bar of every ticker.

Two ways to write one.

1. An expression in the study's study.toml (fastest; an AI assistant can write these from a sentence):

       [signals.stoch_hook]
       side = "C"                     # C = call (long), P = put (short)
       when = "h1_stoch_k < 20 and h1_stoch_ch2 > 0 and h4_MACD_STATE == 'bull widening'"
       note = "1h stochastic turning up from oversold while 4h MACD momentum is widening up"

2. A Python file in plugins/signals/ for anything an expression can't say (opt in per study with
   `use_signals = ["cross_after_flip"]` in study.toml):

       from kit.signals import Signal

       class CrossAfterFlip(Signal):
           name = "cross_after_flip"
           side = "C"
           note = "stochastic buy cross within 3 bars of the 1h MACD histogram turning positive"
           def when(self, df):
               pos = df.raw1h_macd_hist > 0
               flip = pos & ~pos.groupby(df.ticker).shift(1, fill_value=False)
               recent = flip.groupby(df.ticker).transform(lambda s: s.rolling(4, min_periods=1).max())
               return df.raw1h_st_cross_up & (recent > 0)

What a signal can look at — one row per 1h bar, everything known at that bar's close:
  h1_*, h4_*, D_*, m15_*, m3_*   graded readings per timeframe (`kit columns <study>` lists them)
  mktD_*, mktH1_*                 the market ticker's readings
  raw1h_*, raw4h_*, rawD_*        every indicator output as computed (events like raw1h_st_cross_up)
  gap_open_atr, from_open_atr, vs_prev_high_atr, day_range_pos, hour, weekday, close, ...
Higher timeframes are already the last CLOSED bar, so a signal cannot peek. Use `df.groupby("ticker")`
for anything that looks back across rows (rows are sorted by ticker, then time).

A signal "fires" on every bar where `when` is true; an ENTRY is the first bar of each run of fires
(so a condition true for 6 bars in a row is one trade, not six).
"""
from __future__ import annotations

import difflib
import importlib.util
import inspect
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd


class Signal:
    name: str = ""
    side: str = "C"
    note: str = ""
    source: str = ""

    def when(self, df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


class ExprSignal(Signal):
    def __init__(self, name: str, side: str, expr: str, note: str = ""):
        self.name, self.side, self.expr, self.note = name, side, expr, note
        self.source = "study.toml"

    def when(self, df):
        bare = re.sub(r"(['\"]).*?\1", " ", self.expr)          # ignore words inside quoted text
        cols = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", bare)) - {"and", "or", "not", "True", "False", "abs", "nan", "in", "str", "contains", "startswith"}
        missing = sorted(c for c in cols if c not in df.columns and not c.isupper())
        if missing:
            hints = {c: difflib.get_close_matches(c, df.columns, n=3) for c in missing}
            raise KeyError(f"signal {self.name!r} uses unknown columns: " + "; ".join(f"{c} (did you mean {h})" for c, h in hints.items()))
        return df.eval(self.expr, engine="python")


def _plugin_dirs() -> list[Path]:
    from .plugin import plugin_dirs
    return [d.parent / "signals" for d in plugin_dirs()]


def load(cfg: dict) -> list[Signal]:
    out: list[Signal] = []
    for name, spec in (cfg.get("signals") or {}).items():
        side = str(spec.get("side", "C")).upper()[:1]
        if side not in ("C", "P"):
            raise ValueError(f"signal {name!r}: side must be 'C' (call) or 'P' (put)")
        if not spec.get("when"):
            raise ValueError(f"signal {name!r}: needs a `when = \"...\"` expression")
        out.append(ExprSignal(name, side, spec["when"], spec.get("note", "")))
    wanted = list(cfg.get("use_signals") or [])   # plug-in signals are opt-in per study
    found_names = set()
    for d in _plugin_dirs():
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            modname = f"kit_signal_{f.stem}"
            spec_ = importlib.util.spec_from_file_location(modname, f)
            mod = importlib.util.module_from_spec(spec_)
            sys.modules[modname] = mod
            spec_.loader.exec_module(mod)
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, Signal) and cls not in (Signal, ExprSignal) and cls.__module__ == modname and cls.name:
                    if cls.name not in wanted:
                        continue
                    found_names.add(cls.name)
                    s = cls()
                    s.source = str(f)
                    out.append(s)
    missing = [w for w in wanted if w not in found_names]
    if missing:
        raise KeyError(f"use_signals lists {missing}, but no file in plugins/signals/ defines them")
    names = [s.name for s in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"signal names used twice: {sorted(dup)}")
    return out


def evaluate(D: pd.DataFrame, signals: list[Signal]) -> dict[str, dict]:
    """{name: {'fires': bool array, 'entries': bool array (first bar of each run), 'side': 'C'|'P'}}"""
    res = {}
    for s in signals:
        m = np.asarray(pd.Series(s.when(D)).fillna(False).astype(bool))
        if m.shape[0] != len(D):
            raise ValueError(f"signal {s.name!r} returned {m.shape[0]} rows for {len(D)} bars")
        prev = np.r_[False, m[:-1]] & (D.ticker.to_numpy() == np.r_[None, D.ticker.to_numpy()[:-1]])
        res[s.name] = {"fires": m, "entries": m & ~prev, "side": s.side, "note": s.note, "source": s.source}
    return res


def describe(D: pd.DataFrame, ev: dict, months: dict, tiers=("1x", "3x")) -> pd.DataFrame:
    """Per signal and half: entries, per month, and how often a winning leg started right there vs any bar."""
    rows = []
    for name, e in ev.items():
        side = e["side"]
        for h in ("P1", "P2"):
            mh = (D.period == h).to_numpy()
            ent = e["entries"] & mh
            names = {"C": "calls", "P": "puts"} if tiers[0] == "1x" else {"C": "long", "P": "short"}
            r = {"signal": name, "side": names[side], "half": h, "entries": int(ent.sum()),
                 "per_month": round(ent.sum() / max(months.get(h, 1), 1e-9), 1), "bars_firing_pct": round(100 * (e["fires"] & mh).mean(), 2)}
            for lab in (f"{side}_{tiers[0]}", f"{side}_{tiers[1]}"):
                if lab in D:
                    base = D[lab].to_numpy()[mh].mean()
                    hit = D[lab].to_numpy()[ent].mean() if ent.any() else np.nan
                    r[f"{lab}_rate_pct"] = round(100 * hit, 2) if ent.any() else None
                    r[f"{lab}_lift"] = round(hit / base, 2) if ent.any() and base > 0 else None
            f = D[f"{side}_first"].to_numpy()[ent] if f"{side}_first" in D else np.array([])
            decided = f[f != 0]
            r["went_our_way_first_pct"] = round(100 * (decided == 1).mean(), 1) if len(decided) else None
            rows.append(r)
    return pd.DataFrame(rows)
