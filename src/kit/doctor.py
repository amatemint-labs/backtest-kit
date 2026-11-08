"""`kit doctor`: what is ready, what is missing, and the plain-words fix for each."""
from __future__ import annotations

import importlib
import os
import shutil
import socket
import sys

from . import config


def _c(name, status, detail, fix=None):
    return {"name": name, "status": status, "detail": detail, **({"fix": fix} if fix else {})}


def run(s: config.Settings, online: bool = True) -> dict:
    checks = []
    v = sys.version_info
    checks.append(_c("Python", "ok" if (3, 11) <= v[:2] < (3, 14) else "fail", f"{v.major}.{v.minor}.{v.micro}",
                     "Run commands through `uv run kit ...` so uv picks Python 3.12 for you."))
    checks.append(_c("uv", "ok" if shutil.which("uv") else "warn", shutil.which("uv") or "not on PATH",
                     "Install uv: `brew install uv` (or see https://docs.astral.sh/uv/)."))
    missing = []
    for m in ("numpy", "pandas", "scipy", "pyarrow", "numba", "httpx", "keyring"):
        try:
            importlib.import_module(m)
        except Exception:
            missing.append(m)
    checks.append(_c("Python packages", "fail" if missing else "ok", "missing: " + ", ".join(missing) if missing else "all installed",
                     "Run `uv sync` in the kit folder."))
    try:
        from .ind import pine
        import numpy as np
        ok = abs(pine.ema(np.arange(10.0), 3)[-1] - 8.0) < 1e-9
        checks.append(_c("Fast indicator engine (numba)", "ok" if ok else "fail", "compiles and computes" if ok else "wrong result"))
    except Exception as e:
        checks.append(_c("Fast indicator engine (numba)", "fail", str(e)[:120], "Run `uv sync`; numba needs Python 3.11-3.13."))
    try:
        s.data_dir.mkdir(parents=True, exist_ok=True)
        t = s.data_dir / ".write_test"
        t.write_text("x")
        t.unlink()
        checks.append(_c("Data folder", "ok", str(s.data_dir)))
    except Exception as e:
        checks.append(_c("Data folder", "fail", f"{s.data_dir}: {e}", "Set data_dir in kit.toml to a folder you can write."))
    from .data import secrets
    kr = secrets._keyring()
    checks.append(_c("macOS Keychain", "ok" if kr else "warn", "available" if kr else "not available — secrets would go to .env (gitignored)"))
    w_id, w_sec, w_rt = (secrets.where(n) for n in ("TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_REFRESH_TOKEN"))
    have_key = w_id != "missing" and w_sec != "missing"
    checks.append(_c("TradeStation API key", "ok" if have_key else "warn",
                     f"stored in {w_id}" if have_key else "not stored yet",
                     "Ask TradeStation for API access (README: 'Getting a TradeStation API key'), then run `kit login tradestation`."))
    checks.append(_c("TradeStation sign-in", "ok" if w_rt != "missing" else "warn",
                     f"refresh token in {w_rt}" if w_rt != "missing" else "not signed in yet", "Run `kit login tradestation`."))
    reach = None
    if online:
        try:
            with socket.create_connection(("api.tradestation.com", 443), timeout=5):
                reach = True
        except OSError:
            reach = False
        checks.append(_c("TradeStation reachable", "ok" if reach else "warn", "api.tradestation.com:443 answers" if reach else "no connection",
                         "Check your internet connection or firewall."))
        if reach and have_key and w_rt != "missing":
            from .data import tradestation
            try:
                tradestation.TradeStation(s).access_token()
                checks.append(_c("TradeStation login still valid", "ok", "token refresh worked"))
            except Exception as e:
                checks.append(_c("TradeStation login still valid", "warn", str(e)[:160], "Run `kit login tradestation` again."))
    from .data import store
    counts = {tf: len(store.tickers(s.data_dir, tf)) for tf in ("3m", "15m", "1h", "4h", "1D")}
    have = sum(counts.values()) > 0
    checks.append(_c("Bar data", "ok" if have else "warn", ", ".join(f"{tf}: {n} tickers" for tf, n in counts.items()),
                     "Run `kit fetch` after signing in (or `kit smoke` to try made-up data)."))
    mk = store.read(s.data_dir, "1D", s.market) is not None
    checks.append(_c(f"Market ticker ({s.market})", "ok" if mk else "warn", "present" if mk else "no daily bars",
                     f"`kit fetch --tickers {s.market}`"))
    tv = list((s.data_dir / "tv").glob("*/*.parquet")) if (s.data_dir / "tv").exists() else []
    checks.append(_c("TradingView exports", "ok" if tv else "info", f"{len(tv)} imported" if tv else "none yet (needed for `kit match-check`)",
                     "Export chart data from TradingView (Plus plan or higher) and run `kit match-check <file.csv>`."))
    studies = sorted(p.parent.name for p in s.studies_dir.glob("*/study.toml") if not p.parent.name.startswith("_"))
    checks.append(_c("Studies", "info", ", ".join(studies) or "none yet", "`kit study new <name>`"))
    ready_smoke = all(c["status"] != "fail" for c in checks)
    return {"checks": checks, "ready_for_smoke": ready_smoke, "ready_for_fetch": ready_smoke and have_key and w_rt != "missing",
            "data_dir": str(s.data_dir), "kit_root": str(s.root), "cpu_count": os.cpu_count()}
