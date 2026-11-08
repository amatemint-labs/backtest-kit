"""Where things live and the settings you can change (kit.toml at the repo root, optional)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

TZ = "America/New_York"


def repo_root() -> Path:
    env = os.environ.get("KIT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / "pyproject.toml").exists() and (p / "src" / "kit").exists():
            return p
    return Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    root: Path
    data_dir: Path
    studies_dir: Path
    tickers: list[str] = field(default_factory=lambda: ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])
    market: str = "SPY"
    start: str = "2024-05-01"
    timeframes: list[str] = field(default_factory=lambda: ["3m", "15m", "1h", "4h", "1D"])
    session: str = "rth"               # regular hours 09:30-16:00 ET only
    ts_redirect_port: int = 3000       # one of TradeStation's default localhost callbacks
    ts_scopes: str = "openid offline_access MarketData"
    ts_window_days: int = 120          # calendar days per minute-bar request (<= 57,600 bars each)
    ts_requests_per_minute: int = 80   # stays under 500 bar requests / 5 minutes
    workers: int = 0                   # 0 = auto (cores - 2, at most 8)
    plugin_dirs: list[str] = field(default_factory=list)   # extra folders holding indicators/ and signals/

    @property
    def bars_dir(self) -> Path:
        return self.data_dir / "bars"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


def load(root: Path | None = None) -> Settings:
    root = root or repo_root()
    cfg = {}
    f = root / "kit.toml"
    if f.exists():
        cfg = tomllib.loads(f.read_text())
    data_dir = Path(os.environ.get("KIT_DATA", cfg.get("data_dir", root / "data"))).expanduser()
    s = Settings(root=root, data_dir=data_dir, studies_dir=root / "studies")
    for k, v in cfg.items():
        if hasattr(s, k) and k not in ("root", "data_dir", "studies_dir"):
            setattr(s, k, v)
    return s


def workers(s: Settings, n_jobs: int) -> int:
    w = s.workers or max(1, min(8, (os.cpu_count() or 4) - 2))
    return max(1, min(w, n_jobs))
