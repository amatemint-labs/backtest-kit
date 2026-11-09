"""Asset classes and their trading sessions.

Every bar in the store is stamped with its close time in America/New_York, whatever the asset.
A Session says how those instants map to trading days and intraday buckets:

    us_equity   09:30-16:00 New York, Monday-Friday
    cme_globex  18:00-17:00 New York (the evening session belongs to the next trade date),
                Sunday evening through Friday afternoon
    crypto      00:00-24:00 UTC, every day

An Instrument is a symbol plus its asset class (stock, future, crypto), session, and for
futures the dollar value of one point.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

STORE_TZ = "America/New_York"


@dataclass(frozen=True)
class Session:
    name: str
    tz: str
    open_min: int          # session start, minutes after local midnight (of the day it starts on)
    length_min: int        # minutes from open to close
    starts_previous_day: bool
    weekdays: tuple        # trade-date weekdays (0 = Monday)

    def _local(self, ts: pd.Series) -> pd.Series:
        return pd.to_datetime(ts).dt.tz_convert(self.tz)

    def _shifted(self, ts) -> pd.Series:
        """Close-stamped bar -> an instant inside the bar, moved so its local date is the trade date."""
        loc = self._local(pd.Series(ts)) - pd.Timedelta(minutes=1)
        if self.starts_previous_day:
            loc = loc + pd.Timedelta(minutes=1440 - self.open_min)
        return loc

    def trade_date(self, ts) -> pd.Series:
        """The trading day each close-stamped timestamp belongs to (naive midnight)."""
        return self._shifted(ts).dt.tz_localize(None).dt.normalize()

    def session_start(self, day: pd.Series) -> pd.Series:
        """Session start (tz-aware, store tz) for naive trade dates."""
        d = pd.to_datetime(day)
        start = d + pd.to_timedelta(self.open_min, unit="m")
        if self.starts_previous_day:
            start = start - pd.Timedelta(days=1)
        return start.dt.tz_localize(self.tz, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert(STORE_TZ)

    def session_close(self, day: pd.Series) -> pd.Series:
        return self.session_start(day) + pd.to_timedelta(self.length_min, unit="m")

    def minute_of_session(self, ts) -> pd.Series:
        """1..length_min for a close-stamped bar inside the session; <=0 or >length outside it."""
        s = pd.Series(pd.to_datetime(ts)).reset_index(drop=True)
        start = self.session_start(self.trade_date(s))
        mins = (s.dt.tz_convert(STORE_TZ) - start).dt.total_seconds() // 60
        return mins.fillna(-1).astype(int)

    def in_session(self, ts) -> np.ndarray:
        s = pd.Series(pd.to_datetime(ts)).reset_index(drop=True)
        m = self.minute_of_session(s).to_numpy()
        wd = self.trade_date(s).dt.day_of_week.to_numpy()
        return (m >= 1) & (m <= self.length_min) & np.isin(wd, self.weekdays)

    def fraction_left(self, ts) -> np.ndarray:
        """Share of the session still to come at each close-stamped timestamp."""
        m = self.minute_of_session(ts).to_numpy(float)
        return np.clip((self.length_min - m) / self.length_min, 0, 1)

    @property
    def days_per_year(self) -> int:
        return 365 if len(self.weekdays) == 7 else 252


SESSIONS = {
    "us_equity": Session("us_equity", "America/New_York", 9 * 60 + 30, 390, False, (0, 1, 2, 3, 4)),
    "cme_globex": Session("cme_globex", "America/New_York", 18 * 60, 23 * 60, True, (0, 1, 2, 3, 4)),
    "crypto": Session("crypto", "UTC", 0, 24 * 60, False, (0, 1, 2, 3, 4, 5, 6)),
}
ASSET_SESSION = {"stock": "us_equity", "future": "cme_globex", "crypto": "crypto"}

# Dollar value of a one-point move for common CME contracts (CME contract specifications).
FUTURES_MULTIPLIER = {
    "ES": 50, "MES": 5, "NQ": 20, "MNQ": 2, "YM": 5, "MYM": 0.5, "RTY": 50, "M2K": 5,
    "CL": 1000, "MCL": 100, "GC": 100, "MGC": 10, "SI": 5000, "NG": 10000,
    "ZB": 1000, "ZN": 1000, "ZF": 1000, "6E": 125000,
}
CRYPTO_BASES = {"BTC", "ETH", "SOL", "LTC", "BCH", "DOGE", "AVAX", "LINK", "XRP", "ADA", "DOT", "UNI", "AAVE", "SHIB", "XTZ"}


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset: str              # "stock", "future" or "crypto"
    multiplier: float = 1.0

    @property
    def session(self) -> Session:
        return SESSIONS[ASSET_SESSION[self.asset]]


def futures_root(symbol: str) -> str | None:
    s = symbol.upper().lstrip("@").replace("/", "")
    s = s.split(".")[0]                                   # Databento continuous: ES.c.0
    m = re.match(r"^([A-Z0-9]{1,3}?)(?:[FGHJKMNQUVXZ]\d{1,2})?$", s)
    root = m.group(1) if m else s
    for cand in (s, root):
        if cand in FUTURES_MULTIPLIER:
            return cand
    return None


def infer(symbol: str) -> Instrument:
    """Best guess from the symbol alone: BTC/USD -> crypto, @ES / ESZ26 / ES.c.0 -> future, else stock."""
    s = symbol.upper()
    base = re.split(r"[/\-_]", s)[0]
    if "/" in s or (base in CRYPTO_BASES and (s.endswith("USD") or s.endswith("USDT") or "-" in s or "_" in s)):
        return Instrument(symbol, "crypto")
    root = futures_root(s) if (s.startswith("@") or ".C." in s or re.match(r"^[A-Z0-9]{1,3}[FGHJKMNQUVXZ]\d{1,2}$", s)) else None
    if root:
        return Instrument(symbol, "future", float(FUTURES_MULTIPLIER[root]))
    return Instrument(symbol, "stock")


def _meta_path(data_dir: Path, symbol: str) -> Path:
    from .data.store import safe
    return Path(data_dir) / "meta" / f"{safe(symbol)}.json"


def save(data_dir: Path, inst: Instrument) -> None:
    p = _meta_path(data_dir, inst.symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(inst)))


def lookup(data_dir: Path, symbol: str) -> Instrument:
    """The instrument recorded when the symbol was fetched; otherwise inferred from the symbol."""
    p = _meta_path(data_dir, symbol)
    if p.exists():
        d = json.loads(p.read_text())
        return Instrument(d["symbol"], d["asset"], float(d.get("multiplier", 1.0)))
    return infer(symbol)


def make(symbol: str, asset: str | None = None, multiplier: float | None = None) -> Instrument:
    if asset in (None, "", "auto"):
        inst = infer(symbol)
    else:
        if asset not in ASSET_SESSION:
            raise ValueError(f"asset must be one of {sorted(ASSET_SESSION)}")
        root = futures_root(symbol) if asset == "future" else None
        inst = Instrument(symbol, asset, float(FUTURES_MULTIPLIER.get(root, 1.0)) if asset == "future" else 1.0)
    if multiplier:
        inst = Instrument(inst.symbol, inst.asset, float(multiplier))
    return inst
