"""The kit must never be able to trade. Two layers: (1) nothing in the code mentions an order
endpoint or the Trade scope; (2) every request passes a guard that only lets market-data GETs
(and the OAuth token POST) through."""
import re
from pathlib import Path

import pytest

from kit import config
from kit.data import tradestation as ts

ROOT = Path(__file__).resolve().parents[1]
# Paths TradeStation documents for placing, changing or cancelling orders (API v3 spec).
BANNED = [r"orderexecution", r"ordergroups?", r"orderconfirm", r"ordergroupconfirm", r"/orders\b", r"activationtriggers",
          r"placeorder", r"cancelorder", r"replaceorder"]


def _code_files():
    for base in ("src", ".claude"):
        for p in (ROOT / base).rglob("*"):
            if p.is_file() and p.suffix in (".py", ".md", ".toml", ".json"):
                yield p
    for p in ROOT.glob("*.md"):
        yield p
    for p in ROOT.glob("*.toml"):
        yield p


def test_no_order_endpoints_anywhere_in_the_code():
    hits = []
    for p in _code_files():
        text = p.read_text(errors="ignore").lower()
        for pat in BANNED:
            for m in re.finditer(pat, text):
                hits.append(f"{p.relative_to(ROOT)}: {m.group(0)}")
    assert not hits, "order-endpoint text found:\n" + "\n".join(hits)


def test_only_one_post_and_no_put_delete_patch_in_code():
    src = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    assert not re.search(r"\.(put|delete|patch)\(\s*(url|API|f\"https)", src)
    posts = re.findall(r"self\.http\.post\(", src)
    assert len(posts) == 1, "the only POST must be the OAuth token exchange"


def test_scopes_are_market_data_only():
    scopes = config.Settings(root=ROOT, data_dir=ROOT, studies_dir=ROOT).ts_scopes.split()
    assert "Trade" not in scopes and "OptionSpreads" not in scopes and "MarketData" in scopes


@pytest.mark.parametrize("method,url", [
    ("POST", ts.API + "/v3/marketdata/barcharts/SPY"),
    ("PUT", ts.API + "/v3/marketdata/barcharts/SPY"),
    ("DELETE", ts.API + "/v3/marketdata/barcharts/SPY"),
    ("GET", ts.API + "/v3/brokerage/accounts"),
    ("GET", ts.API + "/v3/brokerage/accounts/123/positions"),
    ("GET", ts.API + "/v3/" + "order" + "execution/routes"),
    ("POST", ts.API + "/v3/" + "order" + "execution/" + "orders"),
    ("GET", "https://evil.example.com/v3/marketdata/barcharts/SPY"),
    ("POST", ts.SIGNIN + "/authorize"),
])
def test_guard_refuses(method, url):
    with pytest.raises(ts.ReadOnlyViolation):
        ts.check_request(method, url)


@pytest.mark.parametrize("method,url", [
    ("GET", ts.API + "/v3/marketdata/barcharts/SPY"),
    ("GET", ts.API + "/v3/marketdata/options/expirations/SPY"),
    ("GET", ts.API + "/v3/marketdata/stream/options/chains/SPY"),
    ("POST", ts.TOKEN_URL),
])
def test_guard_allows_reads(method, url):
    ts.check_request(method, url)


def test_client_get_cannot_reach_non_market_paths():
    import httpx
    sent = []
    client = ts.TradeStation(config.Settings(root=ROOT, data_dir=ROOT, studies_dir=ROOT),
                             transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={})))
    with pytest.raises(ts.ReadOnlyViolation):
        client.get("/v3/brokerage/accounts")
    assert sent == []      # refused before anything was sent


def test_login_refuses_trading_scopes():
    from dataclasses import replace
    s = replace(config.Settings(root=ROOT, data_dir=ROOT, studies_dir=ROOT), ts_scopes="openid offline_access MarketData Trade")
    from kit.data import secrets
    secrets.put("TS_CLIENT_ID", "x"); secrets.put("TS_CLIENT_SECRET", "y")
    with pytest.raises(ts.ReadOnlyViolation):
        ts.login(s, open_browser=lambda u: pytest.fail("browser must not open"))
