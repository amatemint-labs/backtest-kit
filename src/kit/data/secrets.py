"""Secrets: macOS Keychain first, a gitignored .env file second. Values are never printed.

Names: TS_CLIENT_ID, TS_CLIENT_SECRET, TS_REFRESH_TOKEN, DATABENTO_API_KEY.
Order of lookup: environment variable -> Keychain (service "backtest-kit") -> .env at the repo root.
KIT_SECRETS=memory switches to an in-process store (tests only).
"""
from __future__ import annotations

import os
from pathlib import Path

SERVICE = "backtest-kit"
NAMES = ("TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_REFRESH_TOKEN", "DATABENTO_API_KEY")
_MEMORY: dict[str, str] = {}


def _memory() -> bool:
    return os.environ.get("KIT_SECRETS") == "memory"


def _envfile() -> Path:
    from ..config import repo_root
    return repo_root() / ".env"


def _read_envfile() -> dict[str, str]:
    p = _envfile()
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _keyring():
    try:
        import keyring
        kr = keyring.get_keyring()
        if "fail" in type(kr).__module__.lower() or "null" in type(kr).__name__.lower():
            return None
        return keyring
    except Exception:
        return None


def get(name: str) -> str | None:
    if _memory():
        return _MEMORY.get(name)
    v = os.environ.get(name)
    if v:
        return v
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(SERVICE, name)
            if v:
                return v
        except Exception:
            pass
    return _read_envfile().get(name) or None


def where(name: str) -> str:
    """Where a secret is stored ('environment', 'keychain', '.env', or 'missing') — never the value."""
    if _memory():
        return "memory" if name in _MEMORY else "missing"
    if os.environ.get(name):
        return "environment"
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password(SERVICE, name):
                return "keychain"
        except Exception:
            pass
    return ".env" if _read_envfile().get(name) else "missing"


def put(name: str, value: str) -> str:
    """Store a secret. Returns where it went. Keychain if available, else .env (mode 600)."""
    if _memory():
        _MEMORY[name] = value
        return "memory"
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            return "keychain"
        except Exception:
            pass
    p = _envfile()
    cur = _read_envfile()
    cur[name] = value
    p.write_text("".join(f"{k}={v}\n" for k, v in cur.items()))
    os.chmod(p, 0o600)
    return ".env"


def delete(name: str) -> None:
    if _memory():
        _MEMORY.pop(name, None)
        return
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    cur = _read_envfile()
    if name in cur:
        cur.pop(name)
        _envfile().write_text("".join(f"{k}={v}\n" for k, v in cur.items()))
