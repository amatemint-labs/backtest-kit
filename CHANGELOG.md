# Changelog

## 1.1.0 — 2026-11-09

Futures and crypto, and instructions that work with any AI assistant.

**Asset classes**
- Stocks, CME futures and crypto, each on its own session: 09:30–16:00 New York for stocks,
  18:00–17:00 New York for futures (the evening belongs to the next trading day), and 00:00–24:00 UTC
  every day for crypto. Intraday bars are anchored at each session's open.
- `kit fetch --asset` and `--multiplier`; the asset class is guessed from the symbol (`BTC/USD`, `@ES`,
  `ESZ26`, `ES.c.0`) and recorded in `data/meta/`. Dollars per point are filled in for common CME contracts.
- New `trade_as` study setting: `auto` (default) prices stocks as options and trades futures, crypto or
  mixed studies as the instruments themselves; `underlying` trades shares too.
- Trading the instrument: labels `C_2atr` / `C_4atr` / `P_2atr` / `P_4atr` (moves of 2 or 4 daily ATRs);
  results as return, move in ATRs and, for futures, dollars per contract; a 5- or 10-trading-day time
  limit in place of option expiry.

**Data**
- Alpaca crypto bars (`/v1beta3/crypto/us/bars`), which need no API key.
- TradeStation futures (`@ES`, `ESZ26`) with session-aware daily stamps and open-stamp detection.
- Databento CME futures (`GLBX.MDP3`), continuous (`ES.c.0`) or single contracts.
- TradingView import and match-check follow the ticker's session; `--asset` on both.

**AI assistants**
- `AGENTS.md` holds the instructions for any assistant (Codex, Cursor, Copilot, Gemini CLI, Aider,
  Claude Code). The task guides moved to `docs/agents/` as plain Markdown; `CLAUDE.md` and
  `.claude/skills/` now point at them.

**Examples and checks**
- Synthetic future (SYNFUT, $50 a point) and coin (SYNCOIN) alongside the synthetic stocks.
- `examples/sample-futures-crypto/`: a full study traded on the instruments.
- `kit smoke` adds three checks: futures and crypto sessions, a study on the future and the coin, and
  futures dollars per contract. New tests cover sessions across daylight-saving changes, bar building,
  no lookahead on the new sessions, pricing, and the new data clients.

**Fixes**
- A worker error during `kit study run` could hang the run instead of reporting it.
- Bars stored with different timestamp precisions could not be joined.

Stock results are unchanged from 1.0.0: the stock sample study produces the same trades and numbers.

## 1.0.0 — 2026-11-08

First public release.

**Data**
- 1-minute and daily bars from Alpaca (free plan), the TradeStation API, or Databento (optional); resumable,
  rate-limited downloads; 3m / 15m / 1h / 4h / 1D (+2D, 1W, 1M) bars stamped at their close.
- TradingView "Export chart data" import and bar-by-bar indicator match-check.
- Daily option-chain snapshots (real quotes going forward); optional localhost webhook log for forward tests.

**Indicators**
- Plug-in interface for your own indicators, with Pine-faithful built-ins and non-repainting
  higher-timeframe helpers; `check-indicator` proves a plug-in never reads the future.
- Bundled Stochastic, RSI and MACD; a worked Pine → Python example plug-in and signal.

**Method**
- Winner census (ATR-zigzag legs priced as options, expiry fixed at entry), graded per-bar snapshot with
  point-in-time joins, lift tables, cross-fitted scorecard with A/B/C grades, look-alikes and eliminators,
  exhaustion model, signals, and a pre-registered trade check with same-day variant.

**Outputs**
- One-page HTML report, `trades.csv` with exit reasons, `summary.json`; sample study on synthetic data.

**Safety**
- Read-only guards on every data source; secrets in the macOS Keychain; tests for no-lookahead,
  no order endpoints and no machine paths in shipped files.
