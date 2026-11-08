"""Plug-in indicators: how your own tools join the kit.

An indicator is one Python file in `plugins/indicators/` with one class that subclasses
`Indicator`. The kit finds it by itself; `uv run kit indicators` lists everything it found and
`uv run kit check-indicator <name>` proves it never looks into the future.

    from kit.plugin import Indicator
    from kit.ind import pine

    class MyRsi(Indicator):
        name = "myrsi"                         # what studies and commands call it
        version = "My RSI v1 (2026-11-08)"      # printed on every report
        tv_columns = {"rsi_value": ["RSI"]}    # output column -> TradingView plot title(s)

        def compute(self, bars, ctx):
            p = 14 if ctx.tf == "1D" else 21   # per-timeframe parameters live here
            return {"rsi_value": pine.rsi(bars.close, p)}

        def readings(self, out, bars):         # what a study learns from (optional)
            r = out["rsi_value"]
            return {"rsi": r, "rsi_ch3": r - pine.shift(r, 3),
                    "RSI_STATE": self.zones(r, [30, 70], ["oversold", "middle", "overbought"])}

Rules the checks enforce:
  * compute() may only use `bars` (this timeframe, oldest first, up to and including each bar)
    and `ctx`. A higher timeframe comes through `ctx.htf(...)`, which hands back only CLOSED bars
    in studies. Never use future rows (no `shift(-1)`, no centred windows).
  * Output column names and reading names must be unique across indicators.
  * Reading names ending in "STATE" are treated as named states (categories); the rest are numbers.
"""
from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .ind import mtf


class Context:
    """What compute() may look at besides its own bars."""

    def __init__(self, tf: str, ts: pd.Series, mode: str, ema_seed: str,
                 get_bars: Callable[[str], pd.DataFrame | None], outputs: dict[str, pd.DataFrame]):
        self.tf = tf
        self.ts = ts
        self.mode = mode
        self.ema_seed = ema_seed
        self._get = get_bars
        self.outputs = outputs           # outputs of the indicators named in `requires`

    def bars(self, tf: str) -> pd.DataFrame:
        """Raw bars of another timeframe. Prefer htf(); if you use this, join with as-of rules yourself."""
        b = self._get(tf)
        if b is None or b.empty:
            raise FileNotFoundError(f"no {tf} bars for this ticker (run `kit fetch` / `kit build`)")
        return b

    def _place(self, tf, fn, which):
        hb = self.bars(tf)
        vals = fn(hb)
        vals = dict(vals.items()) if isinstance(vals, (dict, pd.DataFrame)) else {"value": vals}
        s, h = mtf.as_ns(self.ts), mtf.as_ns(hb["ts"])
        if which == "closed":
            k = mtf.idx_closed(s, h)
        elif which == "containing":
            k = mtf.idx_containing(s, h)
        else:                                   # previous of the containing bar = always closed
            k = mtf.idx_containing(s, h)
            k = np.where(k >= 0, k - 1, np.searchsorted(h, s, side="left") - 1)
        return {c: mtf.take(np.asarray(v, float), k) for c, v in vals.items()}

    def htf(self, tf: str, fn: Callable[[pd.DataFrame], dict | pd.DataFrame], pine_lookahead_on: bool = False) -> dict[str, np.ndarray]:
        """A higher timeframe. fn gets that timeframe's own bars and returns {name: array}.

        Pine  request.security(sym, tf, expr)                         -> ctx.htf(tf, fn)
              (lookahead_off, the default: the last CLOSED higher bar; identical in studies and on TradingView history)
        Pine  request.security(sym, tf, expr, lookahead=barmerge.lookahead_on)
                                                                       -> ctx.htf(tf, fn, pine_lookahead_on=True)
              (repaints on TradingView history. Studies still get the last CLOSED bar; only match-check sees the repaint.)
        Pine  request.security(sym, tf, expr[1], lookahead=barmerge.lookahead_on)   (the classic no-repaint idiom)
                                                                       -> ctx.htf_prev(tf, fn)
        """
        return self._place(tf, fn, "containing" if (pine_lookahead_on and self.mode == "tv") else "closed")

    def htf_prev(self, tf: str, fn: Callable[[pd.DataFrame], dict | pd.DataFrame]) -> dict[str, np.ndarray]:
        """Pine's `expr[1]` + lookahead_on idiom: the PREVIOUS higher bar to the one this bar sits in."""
        return self._place(tf, fn, "prev")


class Indicator:
    name: str = ""
    version: str = ""
    requires: tuple[str, ...] = ()
    tv_columns: dict[str, list[str]] = {}
    sparse: set[str] = set()              # outputs that are empty except on event bars (e.g. arrow levels)
    source: str = ""                      # filled in by the registry: where the code lives

    def compute(self, bars: pd.DataFrame, ctx: Context) -> dict | pd.DataFrame:
        raise NotImplementedError

    def readings(self, out: pd.DataFrame, bars: pd.DataFrame) -> dict:
        """Default: every numeric output column is a reading."""
        return {c: out[c].to_numpy() for c in out.columns if pd.api.types.is_numeric_dtype(out[c])}

    # helpers for graded states
    @staticmethod
    def zones(x, edges, labels) -> np.ndarray:
        """Cut a series into named zones, e.g. edges [30, 70] -> ['low', 'mid', 'high']. NaN -> 'nan'."""
        x = np.asarray(x, float)
        b = np.searchsorted(np.asarray(edges, float), x, side="right")
        out = np.array(labels, dtype=object)[np.clip(b, 0, len(labels) - 1)]
        out[np.isnan(x)] = "nan"
        return out

    @staticmethod
    def direction(x, bars_back: int = 2, up: str = "rising", down: str = "falling") -> np.ndarray:
        x = np.asarray(x, float)
        prev = np.r_[np.full(bars_back, np.nan), x[:-bars_back]]
        return np.where(x - prev > 0, up, down).astype(object)

    @staticmethod
    def combine(*parts) -> np.ndarray:
        out = np.asarray(parts[0], dtype=object).astype(str)
        for p in parts[1:]:
            out = np.char.add(np.char.add(out, " "), np.asarray(p, dtype=object).astype(str))
        out = out.astype(object)
        out[np.char.startswith(np.asarray(parts[0], dtype=object).astype(str), "nan")] = "nan"
        return out


# ── registry ──────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Indicator] | None = None


def plugin_dirs() -> list[Path]:
    from .config import repo_root
    from .config import load
    dirs = [repo_root() / "plugins" / "indicators"]
    extra = [p for p in os.environ.get("KIT_PLUGINS", "").split(os.pathsep) if p]
    try:
        extra += list(load().plugin_dirs or [])
    except Exception:
        pass
    for p in dict.fromkeys(extra):
        dirs.append(Path(p).expanduser() / "indicators")
    return dirs


def _load_file(path: Path) -> list[Indicator]:
    modname = f"kit_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    found = []
    for _, cls in inspect.getmembers(mod, inspect.isclass):
        if issubclass(cls, Indicator) and cls is not Indicator and cls.__module__ == modname and cls.name:
            inst = cls()
            inst.source = str(path)
            found.append(inst)
    return found


def registry(refresh: bool = False) -> dict[str, Indicator]:
    global _REGISTRY
    if _REGISTRY is not None and not refresh:
        return _REGISTRY
    from .ind import builtin
    reg: dict[str, Indicator] = {}
    for ind in builtin.ALL:
        ind.source = "built-in: " + inspect.getsourcefile(type(ind))
        reg[ind.name] = ind
    errors = {}
    for d in plugin_dirs():
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                for ind in _load_file(f):
                    if ind.name in reg:
                        errors[str(f)] = f"name {ind.name!r} is already used by {reg[ind.name].source}"
                        continue
                    reg[ind.name] = ind
            except Exception as e:      # a broken plug-in must not stop the others
                errors[str(f)] = f"{type(e).__name__}: {e}"
    _REGISTRY = reg
    registry.errors = errors
    return reg


registry.errors = {}


def resolve(names: list[str]) -> list[Indicator]:
    """Indicators in dependency order (requires first)."""
    reg = registry()
    out, seen = [], set()

    def add(n, chain=()):
        if n in seen:
            return
        if n not in reg:
            raise KeyError(f"no indicator named {n!r}. Known: {', '.join(sorted(reg))}"
                           + (f". Plug-ins that failed to load: {registry.errors}" if registry.errors else ""))
        if n in chain:
            raise ValueError(f"indicator dependency loop: {' -> '.join(chain + (n,))}")
        for r in reg[n].requires:
            add(r, chain + (n,))
        seen.add(n)
        out.append(reg[n])
    for n in names:
        add(n)
    return out
