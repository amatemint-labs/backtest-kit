"""`kit study new|run` — one folder per study: study.toml (settings), prereg.md (the idea, written
BEFORE results), results/ (tables, parquet, summary.json) and report.html.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
import tomllib
from datetime import date
from itertools import combinations
from pathlib import Path

import warnings

import numpy as np
import pandas as pd

from .. import config
from ..data import store
from ..ind import DEFAULT_INDICATORS, versions
from ..ind.mtf import STUDY_MODES
from .. import signals as sigmod
from . import census, report, scorecard, snapshot, tradecheck

STUDY_TOML = """# Study settings. Decide these BEFORE looking at results; every run records them.
tickers = []              # empty = every ticker in your bar store except the market ticker
market = "{market}"
start = "{start}"
end = ""                  # empty = the latest bar you have
split = ""                # P1 = before this date, P2 = from it. Empty = the middle month of your data
holdout_start = ""        # e.g. "2026-08-01": bars from here are SEALED until `kit study run --open-holdout`
mode = "closed"           # higher-timeframe values: "closed" (last closed bar) or "forming" (as seen live)
labels = ["C_1x", "C_3x", "P_1x", "P_3x"]   # also available: "C_sameday1x", "P_sameday1x" (day-size legs that end the same session)
group_removal = true      # the slow part: refits once per reading group
min_state_n = 200         # a state must appear this often in EACH half to be shown in lift tables
indicators = ["stoch", "rsi", "macd"]      # add your own plug-ins by name (`kit indicators` lists them)

# Your entry signals (optional). Each is tested on every bar; see `kit columns {name}` for what you can use.
# [signals.stoch_hook]
# side = "C"
# when = "h1_stoch_k < 20 and h1_stoch_ch2 > 0 and h4_MACD_STATE == 'bull widening'"
# note = "1h stochastic turning up from oversold while 4h MACD momentum widens up"
"""

PREREG_MD = """# Pre-registration: {name}

Written {today}. Fill this in BEFORE running the trade check (`kit study run {name}` skips the
trade check until every line below is filled). Do not edit it after you have seen results:
append the verdict at the bottom instead. The kit records a fingerprint of everything above
"## Verdict" and flags the study as EXPLORATORY if it changes after a trade-check run.

idea: TODO — one sentence: what you think is true
entry: TODO — one line, e.g. "buy the ATM call at the 1h close when the C_1x grade is A or B"
exit: TODO — one line, e.g. "sell when price turns 0.75 day-ATR off its best point, or at expiry"
measure: TODO — e.g. "median option multiple and % doubled, graded entries vs all bars, each half"
pass_mark: TODO — e.g. "graded median multiple beats all bars by 20%+ in BOTH halves"

## Settings the kit reads (change only before running)
label: C_1x               # which grade picks the entries: C_1x, C_3x, P_1x, P_3x
grades: A, B              # entry grades
trail_k: 0.75             # momentum trail in day-ATR: 0.75 or 1.5
same_day: no              # yes = this week's option, closed by the session's last bar (day trades)
exhaustion: yes           # also run trail + exhaustion exit on the same entries
min_premium: 0.20         # skip entries whose modelled premium is below this ($ per share)
signal:                   # optional: a signal's name — entries are its first bars (then label/grades are ignored)

## Verdict (append after running; never edit above this line)
"""

SESSION = ("gap_open_atr", "from_open_atr", "vs_prev_high_atr", "vs_prev_low_atr", "day_range_pos", "day_range_atr",
           "up_from_20bar_low_atr", "down_from_20bar_high_atr", "bars_since_20bar_low", "bars_since_20bar_high")
LOCATION = ("vs_ema20_atr", "vs_ema50_atr", "vs_sma200_atr", "pos_in_20bar_range", "move5_atr", "volume_x")
GROUPS = {
    "market (daily + hourly)": lambda f: f.startswith(("mktD_", "mktH1_")),
    "daily chart": lambda f: f.startswith("D_"),
    "4h chart": lambda f: f.startswith("h4_"),
    "1h indicator readings": lambda f: f.startswith("h1_") and f[3:] not in LOCATION,
    "1h location (EMAs, range)": lambda f: f.startswith("h1_") and f[3:] in LOCATION and "volume" not in f,
    "lower timeframes (15m, 3m)": lambda f: f.startswith(("m15_", "m3_")),
    "session levels (open, prior day, 20-bar)": lambda f: f in SESSION,
    "volume": lambda f: "volume" in f,
    "time of day / weekday": lambda f: f in ("hour", "weekday"),
}

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)


def _rel(s: config.Settings, p) -> str:
    """Paths stored in results are relative to the kit folder — never this machine's absolute paths."""
    try:
        return str(Path(p).resolve().relative_to(Path(s.root).resolve()))
    except ValueError:
        return Path(p).name


def study_dir(s: config.Settings, name: str) -> Path:
    return s.studies_dir / name


def new(s: config.Settings, name: str) -> dict:
    d = study_dir(s, name)
    if (d / "prereg.md").exists():
        raise FileExistsError(f"study {name!r} already exists at {d}")
    d.mkdir(parents=True, exist_ok=True)
    (d / "study.toml").write_text(STUDY_TOML.replace("{market}", s.market).replace("{start}", s.start).replace("{name}", name))
    (d / "prereg.md").write_text(PREREG_MD.format(name=name, today=date.today().isoformat()))
    return {"study": name, "folder": str(d), "files": ["study.toml", "prereg.md"],
            "next": f"Edit {d / 'prereg.md'} (idea, entry, exit, measure, pass mark), then `kit study run {name}`."}


def load_cfg(s: config.Settings, name: str) -> dict:
    f = study_dir(s, name) / "study.toml"
    if not f.exists():
        raise FileNotFoundError(f"no study {name!r}; create it with `kit study new {name}`")
    return tomllib.loads(f.read_text())


def _build(args):
    data_dir, tk, market, mode, names = args
    try:
        return snapshot.build_intraday(Path(data_dir), tk, market, mode, names=names)
    except FileNotFoundError:
        return None


def _jsonable(x):
    if isinstance(x, pd.DataFrame):
        return json.loads(x.to_json(orient="records", date_format="iso"))
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, float) and np.isnan(x):
        return None
    return x


def run(s: config.Settings, name: str, open_holdout: bool = False, log=print, max_tickers: int | None = None) -> dict:
    t0 = time.time()
    cfg = load_cfg(s, name)
    d = study_dir(s, name)
    out_dir = d / "results"
    out_dir.mkdir(exist_ok=True)
    mode = cfg.get("mode", "closed")
    if mode not in STUDY_MODES:
        raise ValueError(f"study mode must be one of {STUDY_MODES} ('tv' repaints and is for match-check only)")
    market = cfg.get("market", s.market)
    tickers = cfg.get("tickers") or [t for t in store.tickers(s.data_dir, "1h") if t != market]
    if max_tickers:
        tickers = tickers[:max_tickers]
    if not tickers:
        raise FileNotFoundError("no 1h bars in your store yet. Run `kit fetch` (or `kit smoke` to try synthetic data).")
    log(f"study {name}: {len(tickers)} tickers, market {market}, higher timeframes '{mode}'")
    names = cfg.get("indicators") or DEFAULT_INDICATORS
    vers = versions(names)
    log(f"  indicators: {', '.join(vers.values())}")
    mkt = snapshot.market_feats(s.data_dir, market, "1h", mode, names)
    if mkt[0] is None:
        log(f"  note: no bars for market ticker {market}; market readings left out")
    nw = config.workers(s, len(tickers))
    args = [(str(s.data_dir), tk, mkt, mode, names) for tk in tickers]
    if nw > 1:
        with mp.get_context("spawn").Pool(nw) as pool:
            res = pool.map(_build, args, chunksize=1)
    else:
        res = [_build(a) for a in args]
    res = [r for r in res if r is not None]
    if not res:
        raise FileNotFoundError("no ticker had both 1h and 1D bars")
    log(f"  built {len(res)} tickers in {time.time() - t0:.0f}s")
    # stitch bars, keeping each ticker's exit rows pointing at the right global row
    parts, exr, legs, off = [], [], [], 0
    for r in res:
        b = r["bars"]
        parts.append(b)
        e = r["exit_rows"].copy()
        e["row"] = e["i"] + off
        exr.append(e)
        legs.append(r["legs"])
        off += len(b)
    D = pd.concat(parts, ignore_index=True)
    EX = pd.concat(exr, ignore_index=True)
    LEGS = pd.concat(legs, ignore_index=True)
    # time window, halves, sealed holdout
    start = pd.Timestamp(cfg.get("start") or s.start, tz=config.TZ)
    end = pd.Timestamp(cfg["end"], tz=config.TZ) + pd.Timedelta(days=1) if cfg.get("end") else D.ts.max() + pd.Timedelta(seconds=1)
    hold = cfg.get("holdout_start") or ""
    holdout_note = None
    if hold:
        h = pd.Timestamp(hold, tz=config.TZ)
        logf = d / "holdout_log.md"
        if open_holdout:
            prev = logf.read_text() if logf.exists() else ""
            with logf.open("a") as fh:
                fh.write(f"- holdout opened {pd.Timestamp.now(tz=config.TZ):%Y-%m-%d %H:%M} ET\n")
            holdout_note = "OPENED" + (" AGAIN — results on it are no longer a clean test" if prev.strip() else " (first time)")
        else:
            end = min(end, h)
            holdout_note = f"sealed from {hold}"
    keep = (D.ts >= start) & (D.ts < end)
    rowmap = np.full(len(D), -1)
    rowmap[keep.to_numpy()] = np.arange(int(keep.sum()))
    D = D[keep].reset_index(drop=True)
    EX["row"] = rowmap[EX.row.to_numpy()]
    EX = EX[EX.row >= 0].reset_index(drop=True)
    LEGS = LEGS[(LEGS.entry_ts >= start) & (LEGS.entry_ts < end)].reset_index(drop=True)
    split = pd.Timestamp(cfg["split"], tz=config.TZ) if cfg.get("split") else \
        (D.ts.min() + (D.ts.max() - D.ts.min()) / 2).normalize().replace(day=1)
    D["period"] = np.where(D.ts < split, "P1", "P2")
    EX["period"] = D.period.to_numpy()[EX.row.to_numpy()] if len(EX) else []
    months = {p: max((g.ts.max() - g.ts.min()).days / 30.4, 1e-9) for p, g in D.groupby("period")}
    log(f"  {len(D):,} bars, P1 {D.ts.min():%Y-%m-%d}..{split:%Y-%m-%d}, P2 ..{D.ts.max():%Y-%m-%d}")
    n_half = int(D.period.value_counts().min())
    mins = (min(1000, max(60, n_half // 20)), min(300, max(30, n_half // 60)))

    # ── census ──
    legs_in = LEGS
    summary = {"study": name, "title": cfg.get("title") or f"Study: {name}", "built": pd.Timestamp.now(tz=config.TZ).isoformat(), "versions": vers, "mode": mode,
               "tickers": sorted(D.ticker.unique().tolist()), "market": market if mkt[0] is not None else None,
               "bars": len(D), "split": str(split.date()), "periods": {p: {"from": str(g.ts.min()), "to": str(g.ts.max()), "bars": len(g), "months": round(months[p], 1)} for p, g in D.groupby("period")},
               "holdout": holdout_note, "label_definition": "a >=Nx option leg (1h zigzag, 0.75 or 1.5 day-ATR) starts within the next 0-3 bars",
               "census": {"summary": census.summary(legs_in), "winners_5x_10x_by_horizon": census.winners(legs_in),
                          "top_winners": legs_in.sort_values("gain", ascending=False).head(25)[
                              ["ticker", "tf", "k_atr", "side", "entry_ts", "exit_ts", "horizon", "S0", "S1", "move_atr", "mult", "expiry", "outlived_option"]]
                          if len(legs_in) else pd.DataFrame()}}
    LEGS.to_parquet(out_dir / "legs.parquet", index=False)

    NUM = [c for c in D.columns if c.startswith(("h1_", "h4_", "D_", "m15_", "m3_", "mktD_", "mktH1_")) and "STATE" not in c] + \
          list(SESSION) + ["hour", "weekday", "rv"]
    NUM = [c for c in NUM if c in D.columns]
    CAT = [c for c in D.columns if "STATE" in c]
    labels = [lab for lab in cfg.get("labels", ["C_1x", "C_3x", "P_1x", "P_3x"]) if lab in D.columns]
    summary["base_rates_pct"] = {lab: {h: round(100 * D[lab][D.period == h].mean(), 2) for h in ("P1", "P2")} for lab in labels}

    # ── lift tables ──
    min_n = int(cfg.get("min_state_n", 200))
    # named states on the base, 4h, daily and market charts, for 2- and 3-state combinations
    key_states = [c for p in ("h1_", "h4_", "D_", "mktD_") for c in CAT if c.startswith(p)][:8]
    combos = [[c] for c in CAT] + [list(x) for x in combinations(key_states, 2)] + [list(x) for x in combinations(key_states[:6], 3)]
    lifts, cells = {}, 0
    for lab in labels:
        tabs = []
        for keys in combos:
            t = scorecard.lift_table(D, keys, lab, min_n)
            cells += len(t)
            if len(t):
                tabs.append(t)
        T = pd.concat(tabs, ignore_index=True) if tabs else pd.DataFrame()
        lifts[lab] = {"raise": T.sort_values("weaker_lift", ascending=False).head(15) if len(T) else T,
                      "lower": T.sort_values("weaker_lift").head(10) if len(T) else T}
    summary["lift"] = lifts
    summary["lift_cells_tested"] = cells
    summary["lift_expected_false_at_5pct"] = round(0.05 * cells, 1)
    log(f"  lift tables: {cells:,} state cells tested")

    # ── scorecard ──
    cards = {}
    for lab in labels:
        side = lab[0]
        sc, qs, W = scorecard.crossfit(D, NUM, CAT, lab, mins=mins)
        g = scorecard.grade(D, sc, qs)
        D[f"score_{lab}"], D[f"grade_{lab}"] = sc, g
        a1 = scorecard.auc(sc[(D.period == "P1").to_numpy()], D[lab].to_numpy()[(D.period == "P1").to_numpy()])
        a2 = scorecard.auc(sc[(D.period == "P2").to_numpy()], D[lab].to_numpy()[(D.period == "P2").to_numpy()])
        pos, neg = scorecard.agree_weights(W)
        card = {"auc_graded_P1": round(a1, 3), "auc_graded_P2": round(a2, 3),
                "grades": scorecard.grade_table(D, g, lab, months), "deciles": scorecard.deciles(D, sc, lab),
                "raise_odds": pos, "lower_odds": neg}
        if cfg.get("group_removal", True):
            card["group_removal"] = scorecard.group_removal(D, NUM, CAT, lab, GROUPS, a1, a2, mins)
        base, good, bad = scorecard.lookalikes(D, g, side, NUM, CAT, min_n=max(30, mins[1] // 2))
        if "sameday" in lab:      # when in the day do the top grades fire, and how often do they work
            top = np.isin(g, scorecard.GRADES[:2])
            x = D[top].assign(_h=D.hour[top].round(1))
            t = x.groupby(["_h", "period"])[lab].agg(["size", "mean"]).unstack("period")
            card["by_hour_grades_AB"] = pd.DataFrame({
                "bar_close_hour": t.index,
                **{f"rate_{h}_pct": (100 * t[("mean", h)]).round(1).to_numpy() for h in ("P1", "P2") if ("mean", h) in t},
                **{f"bars_{h}": t[("size", h)].fillna(0).astype(int).to_numpy() for h in ("P1", "P2") if ("size", h) in t}})
        card["lookalikes"] = {"win_first_base_pct": {k: round(100 * v, 1) for k, v in base.items()}, "strengtheners": good, "eliminators": bad}
        cards[lab] = card
        log(f"  scorecard {lab}: held-out AUC P1 {a1:.3f}  P2 {a2:.3f}")
    summary["scorecard"] = cards

    # ── your signals ──
    sig_eval = {}
    sig_list = sigmod.load(cfg)
    if sig_list:
        sig_eval = sigmod.evaluate(D, sig_list)
        summary["signals"] = {"table": sigmod.describe(D, sig_eval, months),
                              "defined": [{"name": x.name, "side": x.side, "when": getattr(x, "expr", "(python) " + _rel(s, x.source)),
                                           "note": x.note} for x in sig_list]}
        for nm_, e in sig_eval.items():
            D[f"signal_{nm_}"] = e["entries"]
        log(f"  signals: {', '.join(sig_eval)}")

    # ── exhaustion + trade check ──
    xs, ex_tables = tradecheck.exhaustion_scores(D, EX, NUM, CAT, mins)
    summary["exhaustion"] = ex_tables
    pr_path = d / "prereg.md"
    pr = tradecheck.read_prereg(pr_path) if pr_path.exists() else {}
    probs = tradecheck.prereg_problems(pr) if pr else ["prereg.md is missing"]
    state_f = out_dir / "prereg_fingerprint.txt"
    if probs:
        summary["trade_check"] = {"skipped": True, "why": probs}
        log("  trade check SKIPPED — prereg.md is not complete: " + "; ".join(probs))
    else:
        if not pr.get("signal") and pr["label"] not in labels:
            summary["trade_check"] = {"skipped": True, "why": [f"label {pr['label']} not among study labels {labels}"]}
        else:
            tc = tradecheck.run(D, pr, xs, sig_eval)
            tc["trades"].to_csv(out_dir / "trades.csv", index=False)
            tc["trades_file"] = _rel(s, out_dir / "trades.csv")
            tc["n_trades"] = len(tc["trades"])
            tc["trades_preview"] = tc["trades"].head(40)
            del tc["trades"]
            first = state_f.read_text().strip() if state_f.exists() else ""
            if not first:
                state_f.write_text(pr["_sha256"])
                tc["status"] = "pre-registered (first run with this prereg)"
            elif first != pr["_sha256"]:
                tc["status"] = "EXPLORATORY — prereg.md changed after a trade-check run"
            else:
                tc["status"] = "pre-registered (re-run, prereg unchanged)"
            tc["prereg"] = {k: v for k, v in pr.items() if not k.startswith("_")}
            summary["trade_check"] = tc
            log(f"  trade check: {tc['status']}")

    keep_cols = [c for c in D.columns if not c.endswith(("_hold",))]
    D[keep_cols].to_parquet(out_dir / "bars.parquet", index=False)
    summary["seconds"] = round(time.time() - t0, 1)
    js = _jsonable(summary)
    (out_dir / "summary.json").write_text(json.dumps(js, indent=1, default=str))
    html = report.render(js)
    (d / "report.html").write_text(html)
    log(f"  done in {summary['seconds']}s -> {d / 'report.html'}")
    return {"study": name, "report": str(d / "report.html"), "summary_json": str(out_dir / "summary.json"),
            "bars": len(D), "tickers": len(summary["tickers"]),
            "auc": {lab: [cards[lab]["auc_graded_P1"], cards[lab]["auc_graded_P2"]] for lab in cards},
            "trade_check": "skipped" if summary["trade_check"].get("skipped") else summary["trade_check"].get("status"),
            "seconds": summary["seconds"]}
