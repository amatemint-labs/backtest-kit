# AGENTS.md — Backtest Kit

Instructions for any AI coding assistant working in this repository (Claude Code, Codex, Cursor,
Gemini CLI, GitHub Copilot, Aider and others). Humans: see README.md.

Backtest Kit is a local, read-only research tool for discretionary traders. A trader brings their
own TradingView indicators and setups (ported as plug-ins) and price history for stocks, futures or
crypto. The kit measures each idea on every bar of that history, prices stocks as at-the-money
options or trades the instrument itself, and grades everything on a stretch of data the model never
learned from. Three indicators come bundled (Stochastic, RSI, MACD); everything else is the user's.

Everything runs on the user's computer. You drive it through one command line: `uv run kit <command>`.
Add `--json` whenever you need to read a result; show the plain summary when the user asks.

## Fresh setup on a new machine
Run these from the repository root, one at a time, and report each result in plain words:

1. `uv --version` — if missing, point the user to https://docs.astral.sh/uv/ (on a Mac,
   `brew install uv`). Installing a package manager may need their password, so they run it themselves.
2. `uv sync` — installs Python 3.12 and every package into `.venv` (about 30 seconds; needs internet).
3. `uv run kit doctor` — every line should be OK or TODO; FAIL lines must be fixed first.
4. `uv run kit smoke` — the whole pipeline on synthetic stocks, a future and a coin; every check must PASS.
5. `uv run pytest` — the full test suite.
6. Optional: `cp kit.toml.example kit.toml` and set the user's tickers and start date.

Then tell the user what is ready and what needs them: a data source (see "Get data" below) and a
TradingView export for `uv run kit match-check`. Nothing contacts a broker until then.

## Who you are working with
A trader, not a programmer. Lead with the answer in plain words. Use tables for numbers. Never
bury a caveat that changes the conclusion; put it first. Ask before anything that downloads a lot,
spends money (Databento), changes settings, or opens a sealed holdout.

## Task guides
Plain markdown in `docs/agents/`. Read the matching one before starting the task:

| Guide | Use it when the user… |
|---|---|
| [port-pine-indicator.md](docs/agents/port-pine-indicator.md) | shares a Pine script or describes an indicator |
| [add-signal.md](docs/agents/add-signal.md) | describes a setup in words |
| [run-study.md](docs/agents/run-study.md) | wants to test an idea |
| [check-indicator-match.md](docs/agents/check-indicator-match.md) | shares a TradingView export |
| [explain-report.md](docs/agents/explain-report.md) | asks what a report means |

## Research rules (non-negotiable)
1. **Every number carries its source**: the command or file that produced it
   (e.g. `[run: uv run kit study run first-look --json]`, `[file: studies/first-look/results/summary.json]`).
   An unsourced claim is an assumption and must be labelled **ASSUMED**.
2. **Readings at bar t use only data closed by t.** Higher timeframes come from the last closed bar
   (`mode = "closed"`) or the bar as it was forming live (`mode = "forming"`). Never use `tv` mode in
   a study; it repaints and exists only for `kit match-check`.
3. **No fixed holds or fixed targets** unless that is the question. Write the entry and the exit in
   one line each in `prereg.md` before any trade check. The kit refuses the trade check until
   `prereg.md` is complete.
4. **Every result is shown for both halves** (P1 and P2), with counts and fires per month. Something
   that only works in one half is not a result.
5. **Say how results are priced, every time you quote one.** Options are MODELLED (Black-Scholes, no
   spread, constant volatility, expiry fixed at entry). Futures, crypto and shares traded directly
   have no commission, spread, slippage, roll or funding costs.
6. **Before believing a result, run a refute pass**: a fresh session (or a clearly separated step)
   whose only job is to break it — lookahead, censoring, tail concentration (top 3 days / tickers),
   Simpson's paradox (break down by setup type), tiny premiums, one-regime effects.

## Asset classes
| Asset | Session the kit uses | Trading day | Priced as | Labels |
|---|---|---|---|---|
| Stock / ETF | 09:30–16:00 New York | the calendar date | at-the-money options (or the shares) | `C_1x` `C_3x` `P_1x` `P_3x` |
| CME future | 18:00–17:00 New York | evening session belongs to the next day | the contract; dollars = points × multiplier | `C_2atr` `C_4atr` `P_2atr` `P_4atr` |
| Crypto | 00:00–24:00 UTC, every day | the UTC date | the coin itself | `C_2atr` `C_4atr` `P_2atr` `P_4atr` |

`kit fetch` guesses the asset class from the symbol (BTC/USD is crypto; @ES, ESZ26 and ES.c.0 are
futures) and records it in `data/meta/`. Pass `--asset` when the guess is wrong. A study's
`trade_as = "auto"` prices stocks as options and everything else as the instrument; a study that
mixes asset classes trades the instruments themselves.

## Traps that void analyses
- Units never mix: option multiple (value ÷ premium), move in day-ATR, and return %. Report each in its own column.
- Trades still open at the end are **censored**, not wins or losses — quote `pct_censored`.
- Count the tests. The report prints how many lift cells were tested and how many would look
  significant by luck. Mining more does not fix that; one pre-registered forward test does.
- A grade is worth something only if it beats **all bars** on the same exits.
- Continuous futures from Databento are not back-adjusted: a contract roll appears as a price gap.

## The user's own indicators and signals
The bundled Stochastic, RSI and MACD are just three plug-ins. The user brings their own tools and
setups, and you are the translator:
- **An indicator** (a Pine script or a formula) → one file in `plugins/indicators/`, following
  `docs/agents/port-pine-indicator.md`. Start with `uv run kit new-indicator <name> --from-pine <file>`.
  It is not usable until `uv run kit check-indicator <name>` passes, and not trusted until
  `uv run kit match-check <export> --indicator <name>` matches their chart.
  Worked example: `plugins/indicators/example_rsi_bands.pine` → `example_rsi_bands.py`.
- **A signal** (a setup in words) → an expression in the study's `study.toml` (`[signals.<name>]`),
  or a file in `plugins/signals/` for anything that needs history, following `docs/agents/add-signal.md`.
  `uv run kit columns <study>` lists what a signal can use.

Never let a plug-in read the future: no negative shifts, no centred windows, higher timeframes only
through `ctx.htf` / `ctx.htf_prev`, pivots only where Pine reports them. If a Pine built-in is
missing, add it to `src/kit/ind/pine.py` with a hand-checked test rather than inline. Keep each
plug-in's "Port notes" docstring current; it is how the next session knows what was decided.

## Common jobs
- **Health check**: `uv run kit doctor --json`, then `uv run kit smoke --json`.
- **Get data** (fetch resumes; re-run after any interruption):
  - Stocks, free: `uv run kit login alpaca`, then `uv run kit fetch --source alpaca --tickers SPY,NVDA`.
  - Crypto, free, no key: `uv run kit fetch --source alpaca --tickers BTC/USD,ETH/USD`.
  - Stocks and futures with a TradeStation account: `uv run kit login tradestation`, then
    `uv run kit fetch --tickers NVDA,@ES`.
  - Deeper stock or futures history (paid, asks before spending): `uv sync --extra databento`, then
    `uv run kit fetch --source databento --tickers ES.c.0`.
  The user types keys and signs in themselves; never ask them to paste a password, key or token into the chat.
- **Prove the indicators**: `docs/agents/check-indicator-match.md` → `uv run kit match-check <csv> --json`.
- **Run a study**: `docs/agents/run-study.md` (prereg first, then `kit study run`).
- **Explain results**: `docs/agents/explain-report.md` → `uv run kit report <name> --json`.
  Trade-by-trade detail is in `studies/<name>/results/trades.csv`.
- **Show what a study looks like**: `examples/sample-study/` (stocks as options) and
  `examples/sample-futures-crypto/` (a future and a coin); rebuild both with `uv run kit examples`.

## Never
- Never call, add or suggest code for any broker endpoint that places, changes or cancels orders,
  and never request a trading scope. The guards in `src/kit/data/tradestation.py` and
  `src/kit/data/alpaca.py`, and `tests/test_no_orders.py`, enforce this; do not weaken them.
- Never print, log, or commit secrets. Secrets live in the system keychain (fallback `.env`, git-ignored).
- Never open a network port to the internet. `kit webhook-log` listens on 127.0.0.1 only.
- Never edit `prereg.md` above the "## Verdict" line after a trade check has run. Append below it.
- Never present a modelled result as money made.
- Never commit anything under `data/` or `studies/*/results/`; that is the user's private data.

## Code map
`plugins/indicators/`, `plugins/signals/` the user's own tools (examples included) ·
`src/kit/plugin.py` the Indicator interface and registry · `src/kit/signals.py` signals ·
`src/kit/check.py` check-indicator · `src/kit/assets.py` asset classes, sessions, futures multipliers ·
`src/kit/ind/` indicators (pine.py = Pine built-ins; builtin.py = Stochastic, RSI, MACD; mtf.py = higher-timeframe modes) ·
`src/kit/data/` bar store, TradeStation and Alpaca (read-only), TradingView import and match-check, synthetic data, optional Databento ·
`src/kit/method/` census, snapshot, scorecard, tradecheck, study, report · `tests/` (`uv run pytest`).
Private or licensed indicators live outside the repository in a folder listed under `plugin_dirs` in
`kit.toml`; never copy them into it. If you change an indicator, run `uv run pytest` and a
`kit match-check` against a TradingView export before trusting it.
