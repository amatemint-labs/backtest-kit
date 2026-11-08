"""Indicators: the bundled Stochastic / RSI / MACD, plus any plug-ins in plugins/indicators/.
`compute()` runs a list of them on one timeframe; `readings()` turns their outputs into the graded
readings a study learns from."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from . import tf as tfmod
from .mtf import MODES, STUDY_MODES

DEFAULT_INDICATORS = ["stoch", "rsi", "macd"]


def versions(names: list[str] | None = None) -> dict[str, str]:
    from ..plugin import resolve
    return {i.name: i.version or "(no version set)" for i in resolve(names or DEFAULT_INDICATORS)}


def compute(bars: pd.DataFrame, tf: str, get_bars: Callable[[str], pd.DataFrame | None],
            mode: str = "closed", ema_seed: str = "sma", indicators: list[str] | None = None) -> pd.DataFrame:
    """Run indicators on one timeframe. `bars` = that timeframe's OHLC with `ts` (close time);
    `get_bars(tf)` returns another timeframe's bars. Output columns are recorded in .attrs['columns']."""
    from ..plugin import Context, resolve
    tf = tfmod.norm_tf(tf)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    bars = bars.reset_index(drop=True)
    base = bars[["ts", "open", "high", "low", "close", "volume"]].copy()
    outputs: dict[str, pd.DataFrame] = {}
    cols: dict[str, list[str]] = {}
    taken = set(base.columns)
    for ind in resolve(indicators or DEFAULT_INDICATORS):
        ctx = Context(tf, bars["ts"], mode, ema_seed, get_bars, {r: outputs[r] for r in ind.requires})
        r = ind.compute(bars, ctx)
        df = pd.DataFrame({k: np.asarray(v) for k, v in r.items()}, index=bars.index) if isinstance(r, dict) \
            else r.set_axis(bars.index)
        if len(df) != len(bars):
            raise ValueError(f"indicator {ind.name!r} returned {len(df)} rows for {len(bars)} bars")
        clash = taken & set(df.columns)
        if clash:
            raise ValueError(f"indicator {ind.name!r} output columns {sorted(clash)} are already used")
        taken |= set(df.columns)
        outputs[ind.name] = df
        cols[ind.name] = list(df.columns)
    out = pd.concat([base, *outputs.values()], axis=1)
    out.attrs["columns"] = cols
    return out


def readings(frame: pd.DataFrame, indicators: list[str] | None = None) -> pd.DataFrame:
    """The graded readings of each indicator (names unique across indicators)."""
    from ..plugin import resolve
    cols = frame.attrs.get("columns", {})
    out = {}
    bars = frame[["ts", "open", "high", "low", "close", "volume"]]
    for ind in resolve(indicators or DEFAULT_INDICATORS):
        sub = frame[cols.get(ind.name, [])]
        for k, v in ind.readings(sub, bars).items():
            if k in out:
                raise ValueError(f"reading name {k!r} from {ind.name!r} is already used by another indicator")
            out[k] = np.asarray(v)
    return pd.DataFrame(out, index=frame.index)
