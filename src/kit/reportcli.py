"""`kit report <study>`: the study's results in plain words (reads results/summary.json)."""
from __future__ import annotations

import json

from . import config


def fx(v) -> str:
    return "n/a (no bars)" if v is None else f"{v}x"


def explain(s: config.Settings, name: str) -> tuple[dict, list[str]]:
    d = s.studies_dir / name
    f = d / "results" / "summary.json"
    if not f.exists():
        raise FileNotFoundError(f"no results for {name!r} yet; run `kit study run {name}`")
    S = json.loads(f.read_text())
    L = [f"Study {name} — {len(S['tickers'])} tickers, {S['bars']:,} 1h bars, split {S['split']}, higher timeframes '{S['mode']}'",
         f"Holdout: {S.get('holdout') or 'none set'}.  Option prices are MODELLED (no spread).", ""]
    out = {"study": name, "report": str(d / "report.html"), "labels": {}}
    for lab, c in S.get("scorecard", {}).items():
        g = {(r["graded_half"], r["grade"]): r for r in c["grades"]}
        a = [g.get((h, "A (top 1%)"), {}).get("lift") for h in ("P1", "P2")]
        b = [g.get((h, "B (top 5%)"), {}).get("lift") for h in ("P1", "P2")]
        top = [f"{r['reading']} {r['bin (P1 edges)']} (x{r['odds_x_learned_P1']}/x{r['odds_x_learned_P2']})" for r in c["raise_odds"][:3]]
        elim = [f"{r['reading']} = {r['bin']} (win-first x{r['x_P1']}/x{r['x_P2']})" for r in c["lookalikes"].get("eliminators", [])[:3]]
        L += [f"{lab}: held-out AUC {c['auc_graded_P1']} / {c['auc_graded_P2']} (0.5 = coin flip).",
              f"   Grade A hit rate is {fx(a[0])} / {fx(a[1])} the base rate; grade B {fx(b[0])} / {fx(b[1])} (graded P1 / P2).",
              f"   Strongest readings that agree in both halves: {'; '.join(top) or 'none'}.",
              f"   Eliminators inside A-C: {'; '.join(elim) or 'none passed the count/agreement bar'}."]
        out["labels"][lab] = {"auc": [c["auc_graded_P1"], c["auc_graded_P2"]], "lift_A": a, "lift_B": b, "top": top, "eliminators": elim}
    tc = S.get("trade_check", {})
    L.append("")
    if tc.get("skipped"):
        L.append("Trade check: skipped — " + "; ".join(tc.get("why", [])))
    else:
        L.append(f"Trade check ({tc.get('status')}): entries {tc['entries']}, trail {tc['trail_k']} day-ATR, "
                 f"{tc.get('n_trades', 0):,} trades in {tc.get('trades_file')}.")
        for r in tc["table"]:
            if r.get("trades"):
                L.append(f"   {r['half']} {r['entries']:>14} | {r['exit']:<19} | {r['trades']:>6} trades, median x{r['median_mult']}, "
                         f"doubled {r['pct_doubled']}%, lost half {r['pct_lost_half']}%, censored {r['pct_censored']}%")
        t = tc.get("tail_concentration", {})
        if t:
            L.append(f"   Top 3 days carry {t.get('profit_share_top3_days_pct')}% of these entries' profit; top 3 tickers {t.get('profit_share_top3_tickers_pct')}%.")
    sg = (S.get("signals") or {}).get("table", [])
    if sg:
        L += ["", "Your signals (entries per month; lift = how much more often a winning leg started right there):"]
        for r in sg:
            lifts = ", ".join(f"{k[:-5]} x{v}" for k, v in r.items() if k.endswith("_lift") and v is not None)
            L.append(f"   {r['signal']:>18} {r['half']}: {r['entries']} entries ({r['per_month']}/mo), {lifts or 'no lift data'}, "
                     f"went our way first {r.get('went_our_way_first_pct')}%")
    out["signals"] = sg
    L += ["", f"{S.get('lift_cells_tested', 0):,} lift cells were tested (~{S.get('lift_expected_false_at_5pct', 0)} false hits expected by luck).",
          f"Full page: {d / 'report.html'}"]
    out["trade_check"] = tc
    return out, L
