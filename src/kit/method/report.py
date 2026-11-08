"""One-page HTML report per study (no internet needed to open it)."""
from __future__ import annotations

import html

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--muted:#6b6862;--line:#e4e0d8;--card:#fff;--accent:#2f5d50;--warn:#8a5a00;--warnbg:#fff6e0;--up:#2f6b3a;--dn:#8b3a3a}
@media (prefers-color-scheme: dark){:root{--bg:#141413;--fg:#ece9e2;--muted:#9c978d;--line:#2d2c29;--card:#1c1b19;--accent:#8fc1ae;--warn:#f0c36b;--warnbg:#2a2312;--up:#8fd19e;--dn:#e39a9a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:20px 0 6px}p,li{color:var(--fg)}.muted{color:var(--muted);font-size:13px}
.warn{background:var(--warnbg);border-left:3px solid var(--warn);padding:10px 14px;margin:14px 0;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 12px}.kpi b{display:block;font-size:20px}
.tw{overflow-x:auto;margin:6px 0 14px}table{border-collapse:collapse;font-size:13px;min-width:50%}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;white-space:nowrap}th{color:var(--muted);font-weight:600;text-align:right}
td:first-child,th:first-child{text-align:left}td.t{text-align:left;white-space:normal;max-width:520px}
.bar{fill:var(--accent)}.axis{fill:var(--muted);font-size:11px}svg{max-width:100%;height:auto}
.up{color:var(--up);font-weight:600}.dn{color:var(--dn);font-weight:600}nav a{margin-right:12px;color:var(--accent)}
"""


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return html.escape(str(v))


def table(rows, lift_cols=(), max_rows=60) -> str:
    if not rows:
        return '<p class="muted">Nothing met the minimum counts.</p>'
    cols = list(rows[0].keys())
    h = ["<div class='tw'><table><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in cols) + "</tr>"]
    for r in rows[:max_rows]:
        cells = []
        for c in cols:
            v = r.get(c)
            cls = ""
            if c in lift_cols and isinstance(v, (int, float)):
                cls = "up" if v >= 1.2 else "dn" if v <= 0.83 else ""
            if isinstance(v, str) and len(v) > 30:
                cls = (cls + " t").strip()
            cells.append(f"<td class='{cls}'>{_fmt(v)}</td>")
        h.append("<tr>" + "".join(cells) + "</tr>")
    h.append("</table></div>")
    return "".join(h)


def histogram(mults, title="Option multiple at exit (1.0 = break-even)") -> str:
    """Inline SVG bar chart of trade outcomes."""
    import math
    edges = [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, math.inf]
    labels = ["<0.25", "0.25-0.5", "0.5-0.75", "0.75-1", "1-1.5", "1.5-2", "2-3", "3-5", "5+"]
    counts = [0] * len(labels)
    for m in mults:
        if m is None or (isinstance(m, float) and math.isnan(m)):
            continue
        for i in range(len(labels)):
            if edges[i] <= m < edges[i + 1]:
                counts[i] += 1
                break
    tot = max(sum(counts), 1)
    W, H, pad = 640, 200, 30
    bw = (W - 2 * pad) / len(labels)
    mx = max(counts) or 1
    bars = []
    for i, c in enumerate(counts):
        h = (H - 2 * pad) * c / mx
        x = pad + i * bw
        bars.append(f"<rect class='bar' x='{x + 4:.1f}' y='{H - pad - h:.1f}' width='{bw - 8:.1f}' height='{h:.1f}' rx='2'>"
                    f"<title>{labels[i]}: {c} trades ({100 * c / tot:.1f}%)</title></rect>"
                    f"<text class='axis' x='{x + bw / 2:.1f}' y='{H - pad + 14}' text-anchor='middle'>{labels[i]}</text>"
                    f"<text class='axis' x='{x + bw / 2:.1f}' y='{H - pad - h - 4:.1f}' text-anchor='middle'>{100 * c / tot:.0f}%</text>")
    return (f"<p class='muted'>{html.escape(title)}</p><svg viewBox='0 0 {W} {H}' role='img' aria-label='{html.escape(title)}'>"
            + "".join(bars) + "</svg>")


def render(S: dict) -> str:
    e = html.escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Study {e(S['study'])}</title><style>{CSS}</style></head><body><main>"]
    out.append(f"<h1>Study: {e(S['study'])}</h1><p class='muted'>Built {e(S['built'][:16])} · "
               + " · ".join(e(v) for v in S["versions"].values()) + f" · higher timeframes: <b>{e(S['mode'])}</b></p>")
    labs = list(S.get("scorecard", {}).keys())
    out.append("<nav>" + "".join(f"<a href='#{l}'>{l}</a>" for l in labs) + "<a href='#census'>census</a><a href='#lift'>lift</a><a href='#exit'>exits</a><a href='#signals'>signals</a><a href='#trade'>trade check</a><a href='#check'>checklist</a></nav>")
    P = S["periods"]
    out.append("<div class='grid'>"
               f"<div class='kpi'><span class='muted'>Tickers</span><b>{len(S['tickers'])}</b></div>"
               f"<div class='kpi'><span class='muted'>1h bars</span><b>{S['bars']:,}</b></div>"
               + "".join(f"<div class='kpi'><span class='muted'>Half {p}</span><b>{v['months']} mo</b><span class='muted'>{v['from'][:10]} → {v['to'][:10]}</span></div>" for p, v in P.items())
               + f"<div class='kpi'><span class='muted'>Holdout</span><b>{e(S.get('holdout') or 'none set')}</b></div></div>")
    out.append("<div class='warn'><b>Read before believing anything here.</b> Option results are <b>modelled</b> "
               "(Black-Scholes, no bid/ask spread, constant IV) — good for ranking setups, not for deciding money. "
               f"The lift tables tested <b>{S.get('lift_cells_tested', 0):,}</b> state cells; about "
               f"<b>{S.get('lift_expected_false_at_5pct', 0):,}</b> would look 'significant' at 5% by luck alone. "
               "Only what holds in BOTH halves is shown, and even that is a candidate until a pre-registered forward test.</div>")
    out.append(f"<p class='muted'>Label: {e(S['label_definition'])}. '1x' = the option gained 1x its cost (doubled); '3x' = +300%.</p>")
    br = S.get("base_rates_pct", {})
    out.append("<h3>Base rates (how often a label is true on an ordinary bar)</h3>" +
               table([{"label": k, "P1 %": v.get("P1"), "P2 %": v.get("P2")} for k, v in br.items()]))
    for lab in labs:
        c = S["scorecard"][lab]
        out.append(f"<h2 id='{lab}'>Scorecard — {lab}</h2><p>Held-out ranking quality (AUC; 0.5 = coin flip): "
                   f"graded P1 <b>{_fmt(c['auc_graded_P1'])}</b>, graded P2 <b>{_fmt(c['auc_graded_P2'])}</b>. "
                   "Each half is graded by a model that learned only on the other half.</p>")
        out.append("<h3>By grade</h3>" + table(c["grades"], lift_cols=("lift",)))
        out.append("<h3>Lift by score decile (10 = highest score)</h3>" + table(c["deciles"], lift_cols=tuple(f"decile {k}" for k in range(1, 11))))
        out.append("<h3>Readings that RAISE the odds in both halves</h3><p class='muted'>Odds multiplier for that bin, all else equal, learned on each half.</p>" + table(c["raise_odds"]))
        out.append("<h3>Readings that LOWER the odds in both halves</h3>" + table(c["lower_odds"]))
        if c.get("by_hour_grades_AB"):
            out.append("<h3>Grades A+B by time of day</h3>" + table(c["by_hour_grades_AB"]))
        if c.get("group_removal"):
            out.append("<h3>What each group of readings adds</h3><p class='muted'>Held-out AUC lost when the group is removed; bigger = matters more.</p>" + table(c["group_removal"]))
        la = c.get("lookalikes", {})
        out.append(f"<h3>Look-alikes inside grades A–C</h3><p class='muted'>Base 'went 0.75 day-ATR our way first': "
                   + ", ".join(f"{k} {v}%" for k, v in la.get("win_first_base_pct", {}).items())
                   + ". Eliminators lower that rate in BOTH halves.</p>")
        out.append("<h3>Strengtheners</h3>" + table(la.get("strengtheners", []), lift_cols=("x_P1", "x_P2")))
        out.append("<h3>Eliminators</h3>" + table(la.get("eliminators", []), lift_cols=("x_P1", "x_P2")))
    cz = S.get("census", {})
    out.append("<h2 id='census'>Winner census</h2><p class='muted'>Every ATR-zigzag swing leg, priced as an ATM option "
               "with the expiry fixed at entry (first Friday ≥3 sessions out for 0.75 ATR legs, ≥8 for 1.5, ≥21/42/63 for 2/4/8 ATR daily legs).</p>")
    out.append(table(cz.get("summary", [])))
    out.append("<h3>5x / 10x winners by horizon</h3>" + table(cz.get("winners_5x_10x_by_horizon", [])))
    out.append("<h3>Biggest legs</h3>" + table(cz.get("top_winners", [])))
    out.append("<h2 id='lift'>Lift tables</h2><p class='muted'>Rate of the label in each state ÷ the base rate, per half. "
               "Shown only if seen often enough in each half; ranked by the weaker half.</p>")
    for lab, t in S.get("lift", {}).items():
        out.append(f"<h3>{lab}: raises</h3>" + table(t["raise"], lift_cols=("lift_P1", "lift_P2", "weaker_lift")))
        out.append(f"<h3>{lab}: lowers</h3>" + table(t["lower"], lift_cols=("lift_P1", "lift_P2", "weaker_lift")))
    sg = S.get("signals")
    out.append("<h2 id='signals'>Your signals</h2>")
    if sg:
        out.append("<p class='muted'>An entry = the first bar of each run of fires. Rate = how often a winning option leg started "
                   "within the next 0-3 bars; lift = that ÷ any bar's rate, per half. Descriptive only — results in money terms "
                   "come from a pre-registered trade check.</p>" + table(sg.get("defined", [])))
        out.append(table(sg.get("table", []), lift_cols=tuple(c for c in (sg["table"][0].keys() if sg.get("table") else []) if c.endswith("_lift"))))
    else:
        out.append("<p class='muted'>None defined. Add <code>[signals.&lt;name&gt;]</code> to study.toml or a file in plugins/signals/.</p>")
    out.append("<h2 id='exit'>Exhaustion (is the move spent?)</h2><p class='muted'>Bars inside ≥1x legs; 'spent' = less than 0.25 day-ATR left to the leg's best price.</p>")
    for k, t in S.get("exhaustion", {}).items():
        out.append(f"<h3>{e(k.replace('_', ' trail '))} day-ATR</h3><p>In-leg bars {t['in_leg_bars']:,}; spent base {t['spent_base_pct']}; "
                   f"held-out AUC {t['auc']}</p>" + table(t["spent_lift_by_decile"]) + "<p class='muted'>Says spent:</p>" + table(t["says_spent"]))
    tc = S.get("trade_check", {})
    out.append("<h2 id='trade'>Trade check</h2>")
    if tc.get("skipped"):
        out.append("<div class='warn'>Skipped: " + "; ".join(e(x) for x in tc.get("why", [])) + "</div>")
    else:
        pr = tc.get("prereg", {})
        out.append(f"<p><b>{e(tc.get('status', ''))}</b></p><ul>" + "".join(f"<li><b>{k}:</b> {e(str(pr.get(k, '')))}</li>" for k in ("idea", "entry", "exit", "measure", "pass_mark")) + "</ul>")
        out.append(f"<p class='muted'>Entries: {e(tc['entries'])}; trail {tc['trail_k']} day-ATR; "
                   f"{tc['dropped_tiny_premium']} entries dropped for premium under ${tc['min_premium']}. "
                   f"{tc.get('n_trades', 0):,} trades logged in <code>results/trades.csv</code>.</p>")
        out.append(table(tc["table"]))
        prev = tc.get("trades_preview") or []
        out.append("<h3>Distribution</h3>" + histogram(tc.get("multiples_trail", [])))
        out.append("<h3>Tail concentration (momentum trail exit)</h3>" + table([tc.get("tail_concentration", {})]))
        out.append("<h3>By month</h3><p class='muted'>units_won = sum of (multiple − 1) with 1 unit of premium per trade.</p>"
                   + table(tc.get("monthly", []), max_rows=80))
        out.append("<h3>By ticker (momentum trail)</h3>" + table(tc.get("by_ticker", []), max_rows=40))
        cols = ["ticker", "half", "entry_time", "entry_price", "premium", "exit_time", "exit_price", "exit_reason", "multiple", "hold_bars", "grade"]
        out.append("<h3>Best 10 trades</h3>" + table([{c: r.get(c) for c in cols} for r in tc.get("best", [])]))
        out.append("<h3>Worst 10 trades</h3>" + table([{c: r.get(c) for c in cols} for r in tc.get("worst", [])]))
        out.append("<h3>Trade log (first 40)</h3>" + table([{c: r.get(c) for c in ["exit_rule"] + cols} for r in prev], max_rows=40))
    out.append("<h2 id='check'>Checklist before believing a result</h2><ul>"
               "<li>Held in both halves, with enough cases in each</li><li>No reading used anything from after its bar's close</li>"
               "<li>Priced as an option; premium not tiny; spread considered (real quotes!)</li><li>Compared against all bars and against the same entries</li>"
               "<li>Censored share and tail concentration reported</li><li>Pre-registered, or labelled exploratory</li>"
               "<li>A refute pass (a fresh session whose only job is to break it) found nothing fatal</li></ul>")
    out.append(f"<p class='muted'>Run time {S.get('seconds')}s. Source: results/summary.json in this study folder.</p></main></body></html>")
    return "".join(out)
