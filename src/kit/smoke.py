"""`kit smoke`: the whole pipeline on made-up data, with checks. Needs no account and no internet.

Synthetic bars go to <data>/synthetic (never mixed with your real bars); the smoke studies live
in studies/_smoke (stocks, priced as options) and studies/_smoke_multi (a future and a coin, traded
directly). Checks: indicator ranges, no-lookahead, read-only guard, the TradeStation fetcher against
the mock API (including a throttled reply), a full study, the planted pattern found out of sample,
the trade check, the HTML report, and the futures and crypto sessions and pricing.
"""
from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

SMOKE_TOML = """tickers = ["SYNA", "SYNB", "SYNC", "SYND", "SYNE"]
market = "SYNSPY"
start = "2025-05-01"
end = ""
split = "2025-11-03"
holdout_start = ""
mode = "closed"
labels = ["C_1x", "P_1x"]
group_removal = true
min_state_n = 120

[signals.volume_surge]
side = "C"
when = "h1_volume_x > 2.0 and m15_volume_x > 1.5"
note = "heavy volume on the 1h and 15m bars (the planted tell)"
"""
PREREG = """# Pre-registration: _smoke (synthetic data — written by `kit smoke`)

idea: heavy volume before up-moves marks call entries (it was planted in the synthetic data)
entry: buy the ATM call at the 1h close when the C_1x grade is A or B
exit: sell when price turns 0.75 day-ATR off its best point, or at expiry
measure: median option multiple and % doubled, graded entries vs all bars, each half
pass_mark: none — this only proves the pipeline runs

## Settings the kit reads (change only before running)
label: C_1x
grades: A, B
trail_k: 0.75
exhaustion: yes
min_premium: 0.20

## Verdict (append after running; never edit above this line)
"""

MULTI_TOML = """tickers = ["SYNFUT", "SYNCOIN"]
market = "SYNSPY"
start = "2025-05-01"
end = ""
split = "2025-11-03"
holdout_start = ""
mode = "closed"
trade_as = "auto"
labels = ["C_2atr", "P_2atr"]
group_removal = false
min_state_n = 120

[signals.volume_surge]
side = "C"
when = "h1_volume_x > 2.0 and m15_volume_x > 1.5"
note = "heavy volume on the 1h and 15m bars (the planted tell)"
"""
MULTI_PREREG = """# Pre-registration: _smoke_multi (synthetic data — written by `kit smoke`)

idea: heavy volume before up-moves marks long entries in a future and a coin
entry: buy at the 1h close on the first bar of each volume_surge signal
exit: sell when price turns 0.75 day-ATR off its best point, or after 5 trading days
measure: median move in day-ATR and win rate, signal entries vs all bars, each half
pass_mark: none — this only proves the pipeline runs

## Settings the kit reads (change only before running)
label: C_2atr
grades: A, B
trail_k: 0.75
exhaustion: yes
signal: volume_surge

## Verdict (append after running; never edit above this line)
"""


def run(s: config.Settings, log=print) -> dict:
    from .data import store, synthetic, tradestation
    from .data.ts_mock import MockTradeStation
    from .ind import compute
    from .method import snapshot, study
    t0 = time.time()
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})
        log(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    ss = replace(s, data_dir=s.data_dir / "synthetic", market=synthetic.MARKET, start="2025-05-01")
    synthetic.ensure(ss.data_dir, s.timeframes, log=log)
    counts = {tk: {"1h": len(store.read(ss.data_dir, "1h", tk))} for tk in synthetic.TICKERS}
    check("synthetic data", all(c.get("1h", 0) > 1000 for c in counts.values()), f"{len(counts)} tickers, 1h bars: {counts['SYNA'].get('1h')}")

    # indicators in range
    get = lambda tf: store.read(ss.data_dir, tf, "SYNA")
    ind = compute(get("1h"), "1h", get)
    rng_ok = ind.st_k.dropna().between(0, 100).all() and ind.rsi_value.dropna().between(0, 100).all() and np.isfinite(ind.macd_hist.dropna()).all()
    check("indicator ranges", rng_ok and ind.macd_htf_hist_atr.notna().mean() > 0.5, f"Stochastic, RSI, MACD computed on {len(ind):,} 1h bars")

    # no lookahead: scramble everything after a cut; readings before the cut must not move
    bars = {tf: get(tf) for tf in ("1h", "4h", "1D", "15m", "1W", "2D")}
    cut = bars["1h"].ts.iloc[len(bars["1h"]) // 2]
    rs = np.random.default_rng(1)
    pert = {}
    for tf, b in bars.items():
        b2 = b.copy()
        late = b2.ts > cut
        f = np.exp(rs.normal(0, 0.05, late.sum()))
        for c in ("open", "high", "low", "close"):
            b2.loc[late, c] = b2.loc[late, c] * f
        pert[tf] = b2
    a = snapshot.tf_feats(compute(bars["1h"], "1h", lambda tf: bars[tf]), "h1_")
    b = snapshot.tf_feats(compute(pert["1h"], "1h", lambda tf: pert[tf]), "h1_")
    early = a.ts <= cut
    num = [c for c in a.columns if c != "ts" and pd.api.types.is_numeric_dtype(a[c])]
    same = np.allclose(a.loc[early, num].to_numpy(float), b.loc[early, num].to_numpy(float), equal_nan=True)
    check("no lookahead (closed mode)", same, f"{len(num)} readings unchanged on {int(early.sum()):,} bars when later prices are scrambled")

    # read-only guard
    refused = 0
    for method, path in (("POST", "/v3/marketdata/barcharts/SPY"), ("GET", "/v3/brokerage/accounts"), ("DELETE", "/v3/marketdata/barcharts/SPY")):
        try:
            tradestation.check_request(method, tradestation.API + path)
        except tradestation.ReadOnlyViolation:
            refused += 1
    check("read-only guard", refused == 3, "anything but market-data reads is refused before it leaves the machine")

    # fetcher against the mock API (one 429 on purpose)
    import os
    prev = os.environ.get("KIT_SECRETS")
    os.environ["KIT_SECRETS"] = "memory"
    from .data import secrets
    for n, v in (("TS_CLIENT_ID", "mock-id"), ("TS_CLIENT_SECRET", "mock-secret"), ("TS_REFRESH_TOKEN", "mock-refresh")):
        secrets.put(n, v)
    tmp = Path(tempfile.mkdtemp())
    try:
        m1 = store.read(ss.data_dir, "1m", "SYNB", raw=True)
        m1 = m1[m1.ts >= pd.Timestamp("2026-04-02", tz=config.TZ)]
        mock = MockTradeStation({"SYNB": m1}, throttle_first=1)
        cli = tradestation.TradeStation(replace(ss, ts_requests_per_minute=100000), transport=mock.transport(), sleep=lambda x: None)
        now = datetime(2026, 5, 1, 21, 0, tzinfo=timezone.utc)
        r1 = tradestation.fetch_minutes(cli, tmp, "SYNB", "2026-04-01", now=now, window_days=10, log=lambda m: None)
        r2 = tradestation.fetch_minutes(cli, tmp, "SYNB", "2026-04-01", now=now, window_days=10, log=lambda m: None)
        got = store.read(tmp, "1m", "SYNB", raw=True)
        ok = got is not None and len(got) == len(m1) and r2["new_bars"] == 0 and all(m == "GET" or "/oauth/token" in p for m, p in mock.requests)
        check("TradeStation fetcher (mock API)", ok, f"{r1['new_bars']:,} bars in {r1['requests']} requests after a throttle; re-run fetched {r2['new_bars']} (resume works)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if prev is None:
            os.environ.pop("KIT_SECRETS", None)
        else:
            os.environ["KIT_SECRETS"] = prev

    # full study
    sd = s.studies_dir / "_smoke"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "study.toml").write_text(SMOKE_TOML)
    (sd / "prereg.md").write_text(PREREG)
    fp = sd / "results" / "prereg_fingerprint.txt"
    if fp.exists():
        fp.unlink()
    r = study.run(ss, "_smoke", log=lambda m: log("  " + m))
    import json
    S = json.loads((sd / "results" / "summary.json").read_text())
    a1, a2 = r["auc"]["C_1x"]
    check("scorecard held out", a1 > 0.55 and a2 > 0.55, f"C_1x AUC {a1} / {a2} on halves the model never saw")
    gr = {g["group removed"]: g for g in S["scorecard"]["C_1x"].get("group_removal", [])}
    vol = gr.get("volume", {})
    raise_vol = any("volume_x" in x["reading"] for x in S["scorecard"]["C_1x"]["raise_odds"][:5])
    found = raise_vol and (vol.get("AUC lost (graded P1)", 0) > 0) and (vol.get("AUC lost (graded P2)", 0) > 0)
    check("planted pattern found", found, "heavy volume raises the call odds in both halves, and removing volume costs AUC in both")
    tc = S.get("trade_check", {})
    check("trade check (pre-registered)", not tc.get("skipped") and len(tc.get("table", [])) >= 4, tc.get("status", tc.get("why")))
    sg = {(x["signal"], x["half"]): x for x in S.get("signals", {}).get("table", [])}
    l1, l2 = (sg.get(("volume_surge", h), {}).get("C_1x_lift") for h in ("P1", "P2"))
    check("signal from study.toml", (l1 or 0) > 1.2 and (l2 or 0) > 1.2, f"volume_surge: call-leg lift x{l1} / x{l2} in the two halves")
    tf_ = sd / "results" / "trades.csv"
    nt = len(pd.read_csv(tf_)) if tf_.exists() else 0
    check("trade log", nt > 50, f"{nt:,} trades written to {tf_.name} (entry, exit, reason, option multiple)")
    rep = Path(r["report"])
    check("HTML report", rep.exists() and rep.stat().st_size > 5000, str(rep))

    # futures and crypto: sessions, a study traded on the instruments themselves, dollars per contract
    fut, coin = store.read(ss.data_dir, "1h", synthetic.FUTURE), store.read(ss.data_dir, "1h", synthetic.COIN)
    from .assets import lookup
    fdays = lookup(ss.data_dir, synthetic.FUTURE).session.trade_date(fut.ts)
    cdays = lookup(ss.data_dir, synthetic.COIN).session.trade_date(coin.ts)
    per_f, per_c = fut.groupby(fdays.to_numpy()).size(), coin.groupby(cdays.to_numpy()).size()
    last_f = fut.ts.dt.strftime("%H:%M").groupby(fdays.to_numpy()).last()
    ok = (per_f == 23).all() and (last_f == "17:00").all() and (per_c == 24).all() and coin.ts.dt.day_of_week.nunique() == 7
    check("futures and crypto sessions", ok, f"{synthetic.FUTURE}: 23 hourly bars per trading day, last at 17:00 New York; "
          f"{synthetic.COIN}: 24 per UTC day, 7 days a week")
    md = s.studies_dir / "_smoke_multi"
    md.mkdir(parents=True, exist_ok=True)
    (md / "study.toml").write_text(MULTI_TOML)
    (md / "prereg.md").write_text(MULTI_PREREG)
    fp = md / "results" / "prereg_fingerprint.txt"
    if fp.exists():
        fp.unlink()
    rm = study.run(ss, "_smoke_multi", log=lambda m: log("  " + m))
    M = json.loads((md / "results" / "summary.json").read_text())
    b1, b2 = rm["auc"]["C_2atr"]
    check("future + coin study", M.get("trade_as") == "underlying" and b1 > 0.55 and b2 > 0.55,
          f"traded as the instruments; C_2atr AUC {b1} / {b2} on held-out halves")
    T = pd.read_csv(md / "results" / "trades.csv") if (md / "results" / "trades.csv").exists() else pd.DataFrame()
    tf_rows = T[T.ticker == synthetic.FUTURE] if len(T) else T
    dollars_ok = len(tf_rows) > 10 and np.allclose(tf_rows.dollars_per_unit, tf_rows.points * 50, atol=0.02)
    check("futures dollars per contract", dollars_ok and (T.ticker == synthetic.COIN).sum() > 10,
          f"{len(T):,} trades; {synthetic.FUTURE} P&L = points x $50 on every row")
    return {"passed": all(c["pass"] for c in checks), "checks": checks, "report": str(rep), "seconds": round(time.time() - t0, 1)}
