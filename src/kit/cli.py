"""`kit` — one command line for the whole kit. Every command prints a plain summary; add --json
for a machine-readable result (what an AI assistant reads). Progress messages go to stderr with --json."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import config


def _emit(args, result: dict, lines: list[str], ok: bool = True) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, **result}, indent=1, default=str))
    else:
        print("\n".join(lines))
    return 0 if ok else 1


def _log(args):
    if getattr(args, "json", False):
        return lambda m: print(m, file=sys.stderr, flush=True)
    return lambda m: print(m, flush=True)


def _tickers(args, s) -> list[str]:
    if getattr(args, "tickers", None):
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    return list(dict.fromkeys([*s.tickers, s.market]))


# ── doctor ────────────────────────────────────────────────────────────────────
def cmd_doctor(args) -> int:
    from .doctor import run
    res = run(config.load(), online=not args.offline)
    lines = ["kit doctor — what is ready and what is missing", ""]
    for c in res["checks"]:
        mark = {"ok": "OK  ", "warn": "TODO", "fail": "FAIL", "info": "    "}[c["status"]]
        lines.append(f"  [{mark}] {c['name']}: {c['detail']}")
        if c.get("fix") and c["status"] != "ok":
            lines.append(f"         -> {c['fix']}")
    lines += ["", "Ready to run `kit smoke`." if res["ready_for_smoke"] else "Fix the FAIL lines above first.",
              "Ready to fetch real data." if res["ready_for_fetch"] else "For TradeStation data, finish the TODO lines above. Crypto from Alpaca needs no login: `kit fetch --source alpaca --tickers BTC/USD`."]
    return _emit(args, res, lines, res["ready_for_smoke"])


# ── smoke ─────────────────────────────────────────────────────────────────────
def cmd_smoke(args) -> int:
    from .smoke import run
    res = run(config.load(), log=_log(args))
    lines = ["", "kit smoke — end-to-end check on made-up data", ""]
    for c in res["checks"]:
        lines.append(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")
    lines += ["", f"{'ALL PASSED' if res['passed'] else 'SOME CHECKS FAILED'} in {res['seconds']}s. Report: {res.get('report')}"]
    return _emit(args, res, lines, res["passed"])


# ── TradeStation ──────────────────────────────────────────────────────────────
def cmd_login(args) -> int:
    import getpass
    from .data import secrets, tradestation
    s = config.load()
    if args.broker == "alpaca":
        if args.json or not sys.stdin.isatty():
            return _emit(args, {"error": "needs a terminal"}, ["Run `kit login alpaca` in a terminal."], False)
        print("Your Alpaca API key (free account -> Paper Trading -> API Keys). Typing is hidden; nothing is shown or logged.")
        kid = getpass.getpass("  API Key ID: ").strip()
        sec = getpass.getpass("  Secret Key: ").strip()
        if not kid or not sec:
            return _emit(args, {"error": "empty key"}, ["Nothing entered; stopped."], False)
        w = secrets.put("ALPACA_KEY_ID", kid)
        secrets.put("ALPACA_SECRET_KEY", sec)
        return _emit(args, {"saved_in": w}, [f"Alpaca keys saved in {w}. Next: `uv run kit fetch --source alpaca --tickers SPY`."])
    if args.reset_key:
        for n in ("TS_CLIENT_ID", "TS_CLIENT_SECRET", "TS_REFRESH_TOKEN"):
            secrets.delete(n)
    if not secrets.get("TS_CLIENT_ID") or not secrets.get("TS_CLIENT_SECRET"):
        if args.json or not sys.stdin.isatty():
            return _emit(args, {"error": "no API key stored"}, ["No TradeStation API key stored. Run `kit login tradestation` in a terminal."], False)
        print("Your TradeStation API key (from TradeStation's email). Typing is hidden; nothing is shown or logged.")
        print("This is the API key and secret — NOT your TradeStation password. You sign in with your password in the browser.")
        cid = getpass.getpass("  API key (client id): ").strip()
        csec = getpass.getpass("  API secret: ").strip()
        if not cid or not csec:
            return _emit(args, {"error": "empty key"}, ["Nothing entered; stopped."], False)
        w1 = secrets.put("TS_CLIENT_ID", cid)
        secrets.put("TS_CLIENT_SECRET", csec)
        print(f"  saved in {w1}.")
    print(f"Opening your browser to sign in to TradeStation (callback http://localhost:{s.ts_redirect_port}) ...", file=sys.stderr)
    try:
        res = tradestation.login(s)
    except (tradestation.NotLoggedIn, tradestation.ReadOnlyViolation) as e:
        return _emit(args, {"error": str(e)}, [f"Sign-in failed: {e}"], False)
    return _emit(args, res, [f"Signed in. Refresh token saved in {res['refresh_token_saved_in']}. Scopes: {res['scopes']} (market data only — no trading)."])


SOURCE_ASSETS = {"alpaca": ("stock", "crypto"), "tradestation": ("stock", "future"), "databento": ("stock", "future")}


def cmd_fetch(args) -> int:
    from . import assets
    from .data import store, tradestation
    s = config.load()
    log = _log(args)
    insts = {tk: assets.make(tk, args.asset, args.multiplier) for tk in _tickers(args, s)}
    bad = [f"{tk} ({i.asset})" for tk, i in insts.items() if i.asset not in SOURCE_ASSETS[args.source]]
    if bad:
        msg = (f"{args.source} does not carry {', '.join(bad)}. Sources: alpaca = stocks + crypto, "
               "tradestation = stocks + futures (@ES), databento = stocks + futures (ES.c.0). "
               "If the guess is wrong, pass --asset stock|future|crypto.")
        return _emit(args, {"error": msg}, [msg], False)
    for i in insts.values():
        assets.save(s.data_dir, i)
        if i.asset != "stock":
            log(f"{i.symbol}: {i.asset}, session {i.session.name}" + (f", ${i.multiplier:g} per point" if i.asset == "future" else ""))
    if args.source == "alpaca":
        from .data import alpaca
        try:
            cli = alpaca.Alpaca(log=log, keys_required=any(i.asset == "stock" for i in insts.values()))
        except PermissionError as e:
            return _emit(args, {"error": str(e)}, [str(e)], False)
        out = []
        for tk in insts:
            log(f"{tk}:")
            r = alpaca.fetch_minutes(cli, s.data_dir, tk, args.start or s.start, log=log, asset=insts[tk].asset)
            if not args.no_build:
                r["built"] = store.build_timeframes(s.data_dir, tk, s.timeframes)
            out.append(r)
        return _emit(args, {"fetched": out}, ["kit fetch (Alpaca, free) — done (it resumes)"] +
                     [f"  {r['symbol']}: +{r['new_bars']:,} minute bars ({(r['first'] or '')[:10]} .. {(r['last'] or '')[:10]})" for r in out])
    if args.source == "databento":
        from .data import databento_opt
        out = []
        for tk in insts:
            r = databento_opt.fetch_minutes(s.data_dir, tk, args.start or s.start, log=log, asset=insts[tk].asset)
            if not args.no_build:
                r["built"] = store.build_timeframes(s.data_dir, tk, s.timeframes)
            out.append(r)
        return _emit(args, {"fetched": out}, ["kit fetch (Databento) — done"] + [f"  {r['symbol']}: {r['downloaded']:,} bars, ${r['cost_usd']:,.2f}" for r in out])
    ts = tradestation.TradeStation(s, log=log)
    out, lines = [], []
    try:
        for tk in insts:
            log(f"{tk}:")
            r = {"ticker": tk}
            ses = insts[tk].session
            if not args.daily_only:
                r["minutes"] = tradestation.fetch_minutes(ts, s.data_dir, tk, args.start or s.start, window_days=s.ts_window_days,
                                                          log=log, session=ses)
            r["daily_bars"] = tradestation.fetch_daily(ts, s.data_dir, tk, args.daily_start or "2015-01-01", session=ses)
            if not args.no_build:
                r["built"] = store.build_timeframes(s.data_dir, tk, s.timeframes)
            out.append(r)
            m = r.get("minutes", {})
            lines.append(f"  {tk}: +{m.get('new_bars', 0):,} minute bars ({m.get('first', '')[:10]} .. {m.get('last', '')[:10]}), "
                         f"{r['daily_bars']:,} daily bars" + (" — TradeStation's minute history ended before your start date" if m.get("history_ended_early") else ""))
    except tradestation.NotLoggedIn as e:
        return _emit(args, {"error": str(e), "done": out}, [str(e)], False)
    return _emit(args, {"fetched": out}, ["kit fetch — done (it resumes, so run it again any time)", *lines])


def cmd_build(args) -> int:
    from .data import store
    s = config.load()
    res = {tk: store.build_timeframes(s.data_dir, tk, s.timeframes) for tk in _tickers(args, s)}
    return _emit(args, {"built": res}, ["Built timeframes:"] + [f"  {k}: {v}" for k, v in res.items()])


def cmd_snapshot_options(args) -> int:
    from .data import tradestation
    s = config.load()
    ts = tradestation.TradeStation(s, log=_log(args))
    out = []
    try:
        for tk in _tickers(args, s):
            out.append(tradestation.snapshot_options(ts, s.data_dir, tk, args.expirations, args.strikes))
    except tradestation.NotLoggedIn as e:
        return _emit(args, {"error": str(e)}, [str(e)], False)
    return _emit(args, {"snapshots": out}, ["Option chain snapshots saved (real quotes, from today forward):"] +
                 [f"  {r['underlying']}: {r['contracts']} contracts over {r['expirations']} expirations" for r in out])


# ── TradingView ───────────────────────────────────────────────────────────────
def cmd_import_tv(args) -> int:
    from .data import tradingview
    r = tradingview.import_csv(Path(args.csv), config.load().data_dir, args.ticker, args.tf, args.asset)
    return _emit(args, r, [f"Imported {r['bars']:,} {r['tf']} bars of {r['ticker']} ({r['first'][:10]} .. {r['last'][:10]}).",
                           f"Indicator columns found: {', '.join(r['indicator_columns']) or 'none — add the indicators to the chart before exporting'}"])


def cmd_match_check(args) -> int:
    from .data import tradingview
    mp = dict(x.split("=", 1) for x in (args.map or []))
    r = tradingview.match_check(Path(args.csv), config.load().data_dir, args.ticker, args.tf, mp, args.warmup, args.ema_seed,
                                indicators=args.indicator, tolerance=args.tol, asset=args.asset)
    lines = [f"kit match-check — {r['ticker']} {r['tf']}, {r['bars_in_export']:,} bars, warm-up from {r['warm_source']}", ""]
    for t in r["table"]:
        if t.get("bars"):
            lines.append(f"  {t['status']:5s} {t['reading']:9s} vs '{t['tv_column']}': {t['pct_within_tol']}% within ±{t['tolerance']} "
                         f"over {t['bars']:,} bars (median diff {t['median_abs_diff']}, worst {t['max_abs_diff']})")
        else:
            lines.append(f"  ----  {t['reading']:9s}: {t['status']}")
    for k, w in r["worst"].items():
        lines.append(f"\n  worst {k}:")
        lines += [f"    {x['ts'][:16]}  TV {x['tradingview']:>9}  port {x['port']:>9}  diff {x['abs_diff']}" for x in w[:5]]
    ok = all(t["status"] in ("MATCH", "not in export") for t in r["table"])
    return _emit(args, r, lines, ok)


def cmd_webhook_log(args) -> int:
    from .data import webhook
    webhook.serve(config.load().data_dir, port=args.port, host=args.host, log=_log(args))
    return 0


# ── your own tools ──
def cmd_indicators(args) -> int:
    from .plugin import registry
    reg = registry(refresh=True)
    rows = [{"name": n, "version": i.version, "requires": list(i.requires), "tradingview_columns": i.tv_columns,
             "source": i.source} for n, i in reg.items()]
    lines = ["Indicators the kit can use (add yours in plugins/indicators/):", ""]
    lines += [f"  {r['name']:<12} {r['version']:<48} {r['source'].split('/')[-1]}" for r in rows]
    if registry.errors:
        lines += ["", "Plug-ins that FAILED to load:"] + [f"  {f}: {e}" for f, e in registry.errors.items()]
    return _emit(args, {"indicators": rows, "load_errors": registry.errors}, lines, not registry.errors)


def cmd_check_indicator(args) -> int:
    from .check import check_indicator
    tfs = [t.strip() for t in args.tf.split(",")] if args.tf else ["1h", "15m", "4h", "1D"]
    r = check_indicator(config.load(), args.name, tuple(tfs), log=_log(args))
    lines = ["", f"kit check-indicator {args.name} — {r.get('version', '')}", ""] + \
            [f"  [{'PASS' if c['pass'] else ('NOTE' if c.get('advisory') else 'FAIL')}] {c['name']}: {c['detail']}" for c in r["checks"]] + \
            ["", "SAFE TO STUDY WITH." if r["passed"] else "NOT SAFE YET — fix the FAIL lines (a lookahead FAIL means it reads the future)."]
    return _emit(args, r, lines, r["passed"])


def cmd_new_indicator(args) -> int:
    from .scaffold import new_indicator
    r = new_indicator(config.load(), args.name, args.from_pine)
    return _emit(args, r, [f"Created {r['file']}", r["next"]])


def cmd_new_signal(args) -> int:
    from .scaffold import new_signal
    r = new_signal(config.load(), args.name, args.note or "describe the setup in one line")
    return _emit(args, r, [f"Created {r['file']}", r["next"]])


def cmd_columns(args) -> int:
    """What signals can use: every column of the per-bar table, with types and example values."""
    import pandas as pd
    from dataclasses import replace
    from .data import synthetic
    from .method import snapshot, study
    s = config.load()
    f = s.studies_dir / args.name / "results" / "bars.parquet" if args.name else None
    if f is not None and f.exists():
        D = pd.read_parquet(f)
        src = str(f)
    else:
        cfg = study.load_cfg(s, args.name) if args.name else {}
        names = cfg.get("indicators") or None
        ss = replace(s, data_dir=s.data_dir / "synthetic")
        synthetic.ensure(ss.data_dir, s.timeframes, log=_log(args))
        mk = snapshot.market_feats(ss.data_dir, synthetic.MARKET, "1h", "closed", names)
        D = snapshot.build_intraday(ss.data_dir, "SYNA", mk, "closed", names=names)["bars"]
        src = "synthetic sample (run the study for your real columns)"
    rows = []
    for c in D.columns:
        x = D[c]
        if pd.api.types.is_bool_dtype(x):
            kind, ex = "true/false", f"{100 * x.mean():.1f}% true"
        elif pd.api.types.is_numeric_dtype(x):
            kind, ex = "number", f"{x.min():.3g} .. {x.max():.3g}" if x.notna().any() else "empty"
        else:
            vals = x.astype(str).value_counts().index[:6].tolist()
            kind, ex = "state", " | ".join(vals)
        rows.append({"column": c, "kind": kind, "values": ex})
    groups = {}
    for r in rows:
        key = r["column"].split("_")[0] + "_" if "_" in r["column"] else "other"
        groups.setdefault(key, []).append(r)
    lines = [f"Columns a signal can use ({src}):"]
    for g, rs in groups.items():
        lines.append("")
        lines += [f"  {r['column']:<34} {r['kind']:<10} {r['values']}" for r in rs]
    return _emit(args, {"source": src, "columns": rows}, lines)


def cmd_examples(args) -> int:
    from .examples import build
    r = build(config.load(), log=_log(args))
    return _emit(args, r, [f"Sample study written to {e['folder']}: {', '.join(e['files'])}" for e in r["examples"].values()])


# ── method ────────────────────────────────────────────────────────────────────
def cmd_census(args) -> int:
    import pandas as pd
    from .data import store
    from .method import census
    s = config.load()
    legs = []
    for tk in _tickers(args, s):
        d = store.read(s.data_dir, "1D", tk)
        if d is None:
            continue
        legs.append(census.legs_for(d, d, tk, "1D"))
        h = store.read(s.data_dir, "1h", tk)
        if h is not None:
            legs.append(census.legs_for(h, d, tk, "1h"))
    if not legs:
        return _emit(args, {"error": "no bars"}, ["No bars found. Run `kit fetch` (or `kit smoke`) first."], False)
    L = pd.concat(legs, ignore_index=True)
    L = L[L.entry_ts >= pd.Timestamp(args.start or s.start, tz=config.TZ)]
    p = s.data_dir / "census" / "legs.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    L.to_parquet(p, index=False)
    sm, w = census.summary(L), census.winners(L)
    res = {"legs": len(L), "file": str(p), "summary": json.loads(sm.to_json(orient="records")), "winners": json.loads(w.to_json(orient="records"))}
    return _emit(args, res, [f"{len(L):,} legs saved to {p}", "", sm.to_string(index=False), "", "Winners by horizon (option gain):", w.to_string(index=False)])


def cmd_study(args) -> int:
    from .method import study
    s = config.load()
    if args.action == "new":
        r = study.new(s, args.name)
        return _emit(args, r, [f"Created {r['folder']}", r["next"]])
    r = study.run(s, args.name, open_holdout=args.open_holdout, log=_log(args), max_tickers=args.max_tickers)
    lines = [f"Study {r['study']}: {r['bars']:,} bars, {r['tickers']} tickers, {r['seconds']}s",
             *[f"  {k}: held-out AUC {v[0]} (graded P1) / {v[1]} (graded P2)" for k, v in r["auc"].items()],
             f"  trade check: {r['trade_check']}", f"  report: {r['report']}"]
    return _emit(args, r, lines)


def cmd_report(args) -> int:
    from .reportcli import explain
    r, lines = explain(config.load(), args.name)
    if args.open:
        import webbrowser
        webbrowser.open(Path(r["report"]).as_uri())
    return _emit(args, r, lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kit", description="Local, read-only backtesting kit. Start with `kit doctor`, then `kit smoke`.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("doctor", cmd_doctor, "check what is ready and what is missing")
    sp.add_argument("--offline", action="store_true", help="skip network checks")
    add("smoke", cmd_smoke, "end-to-end run on bundled synthetic data (no account needed)")
    sp = add("login", cmd_login, "sign in to TradeStation in your browser (read-only market data)")
    sp.add_argument("broker", choices=["tradestation", "alpaca"])
    sp.add_argument("--reset-key", action="store_true", help="forget the stored API key and sign-in first")
    sp = add("fetch", cmd_fetch, "download bars (stocks, futures, crypto); resumes where it stopped")
    sp.add_argument("--tickers", help="comma list; default = tickers in kit.toml")
    sp.add_argument("--start", help="first date for minute bars (default kit.toml start)")
    sp.add_argument("--daily-start", help="first date for daily bars (default 2015-01-01)")
    sp.add_argument("--daily-only", action="store_true")
    sp.add_argument("--no-build", action="store_true", help="do not rebuild 3m/15m/1h/4h/1D afterwards")
    sp.add_argument("--source", choices=["tradestation", "alpaca", "databento"], default="tradestation",
                    help="alpaca = FREE (stocks need a free account; crypto needs no key); databento = OPTIONAL paid vendor (asks before spending)")
    sp.add_argument("--asset", choices=["auto", "stock", "future", "crypto"], default="auto",
                    help="asset class; auto guesses from the symbol (BTC/USD = crypto, @ES / ESZ26 / ES.c.0 = future)")
    sp.add_argument("--multiplier", type=float, help="futures: dollars per point (known roots like ES, NQ, CL, GC are filled in)")
    sp = add("build", cmd_build, "rebuild timeframes from downloaded minute/daily bars")
    sp.add_argument("--tickers")
    sp = add("snapshot-options", cmd_snapshot_options, "save today's option chains (real quotes from now on)")
    sp.add_argument("--tickers")
    sp.add_argument("--expirations", type=int, default=4)
    sp.add_argument("--strikes", type=int, default=5, help="strikes each side of the money")
    sp = add("import-tv", cmd_import_tv, "load a TradingView 'Export chart data' CSV")
    sp.add_argument("csv")
    sp.add_argument("--ticker")
    sp.add_argument("--tf", help="timeframe (inferred from bar spacing if left out)")
    sp.add_argument("--asset", choices=["auto", "stock", "future", "crypto"], default="auto", help="sets the session used for bar times")
    sp = add("match-check", cmd_match_check, "compare the Python ports with your TradingView values bar by bar")
    sp.add_argument("csv")
    sp.add_argument("--ticker")
    sp.add_argument("--tf")
    sp.add_argument("--map", action="append", help="port_column=TV column title, e.g. rsi_value='RSI'")
    sp.add_argument("--warmup", type=int, default=300, help="bars skipped when warming up from the CSV alone")
    sp.add_argument("--ema-seed", choices=["sma", "first"], default="sma")
    sp.add_argument("--indicator", action="append", help="which indicator(s) to compare (default: all whose columns are in the export)")
    sp.add_argument("--tol", type=float, default=0.5, help="allowed difference per bar (default 0.5)")
    sp.add_argument("--asset", choices=["auto", "stock", "future", "crypto"], default="auto", help="sets the session used for bar times")
    sp = add("webhook-log", cmd_webhook_log, "OPTIONAL: log TradingView alert webhooks to a local file (this Mac only by default)")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--host", default="127.0.0.1", help="leave as 127.0.0.1 unless you know why")
    add("indicators", cmd_indicators, "list every indicator the kit can use (bundled + your plug-ins)")
    sp = add("check-indicator", cmd_check_indicator, "prove a plug-in indicator never looks into the future")
    sp.add_argument("name")
    sp.add_argument("--tf", help="comma list of timeframes (default 1h,15m,4h,1D)")
    sp = add("new-indicator", cmd_new_indicator, "start a plug-in indicator file (optionally from a Pine script)")
    sp.add_argument("name")
    sp.add_argument("--from-pine", help="path to the .pine file to port (copied next to the plug-in)")
    sp = add("new-signal", cmd_new_signal, "start a plug-in signal file")
    sp.add_argument("name")
    sp.add_argument("--note", help="the setup in one line")
    sp = add("columns", cmd_columns, "list the columns a signal can use (for a study, or a synthetic sample)")
    sp.add_argument("name", nargs="?")
    add("examples", cmd_examples, "rebuild the sample studies in examples/ (report, trades, results) on synthetic data")
    sp = add("census", cmd_census, "every swing leg priced as an option; winners by horizon")
    sp.add_argument("--tickers")
    sp.add_argument("--start")
    sp = add("study", cmd_study, "`study new <name>` or `study run <name>`")
    sp.add_argument("action", choices=["new", "run"])
    sp.add_argument("name")
    sp.add_argument("--open-holdout", action="store_true", help="include the sealed holdout (logged; do this once)")
    sp.add_argument("--max-tickers", type=int)
    sp = add("report", cmd_report, "summarise a study's results in plain words")
    sp.add_argument("name")
    sp.add_argument("--open", action="store_true", help="open the HTML report in your browser")
    args = p.parse_args(argv)
    t0 = time.time()
    try:
        return args.fn(args)
    except (FileNotFoundError, FileExistsError, ValueError, KeyError) as e:
        return _emit(args, {"error": str(e)}, [f"Stopped: {e}"], False)
    finally:
        if not getattr(args, "json", False) and time.time() - t0 > 5:
            print(f"({time.time() - t0:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
