---
name: explain-report
description: Explain a study's results in plain trader language — what held in both halves, the grades, the readings that matter, eliminators, exits, and the trade check — with the caveats that change the conclusion. Use when the user asks what a report means, whether something works, or to summarise a study.
---

# Explain a report

1. `uv run kit report <name> --json` for the headline numbers; read
   `studies/<name>/results/summary.json` for detail. (`kit report <name> --open` opens the page.)

2. **Answer first, in one or two sentences**: did the idea clear the pre-registered pass mark in
   BOTH halves? If the trade check was skipped, say why (usually an unfilled prereg).

3. **Then a short table per label** (C_1x = call legs that at least doubled, P_1x = puts, etc.):

   | | graded P1 | graded P2 |
   |---|---|---|
   | AUC (0.5 = coin flip) | | |
   | Grade A lift / fires per month | | |
   | Grade B lift / fires per month | | |

4. **What matters**, in trader words: the 3–5 readings whose weights agree in both halves
   ("1h stochastic below 20 and falling: ~1.4x the odds"), the group-removal table (which timeframe
   or group carries the signal), and the eliminators (what makes an A-grade setup break first).

5. **Signals** (if any): entries per month, lift per half, went-our-way-first — and whether it held
   in BOTH halves.

6. **Trade check**: the entries (grades or a signal) vs all bars, trail vs trail + exhaustion —
   median multiple, % doubled, % lost half, censored %; by month and by ticker; best and worst trades.
   Use `results/trades.csv` for questions about individual trades. Entries only matter if they beat all bars.

7. **Caveats that change the conclusion — say them, don't bury them:**
   - Option prices are MODELLED (no spread, constant IV) — ranking, not money.
   - Tail concentration: if the top 3 days or tickers carry most of the profit, say so.
   - Number of lift cells tested vs expected false hits.
   - Anything that held in only one half is not a finding.
   - `pct_censored` above ~10% → the win rate is a bounded estimate.

8. Every number gets a source tag: `[file: studies/<name>/results/summary.json]`. Anything you
   infer that the file doesn't say is **ASSUMED**.

9. Close with the one next step that would most change the user's confidence (often: a refute
   pass, real option quotes, or a forward test of ONE pre-registered idea).
