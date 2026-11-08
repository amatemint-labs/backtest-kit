# Changelog

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
