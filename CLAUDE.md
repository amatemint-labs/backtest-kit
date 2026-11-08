# CLAUDE.md — backtest kit

A local, read-only backtesting kit for a discretionary options trader: their own TradingView
indicators and setups (ported as plug-ins), price history from TradeStation or a free Alpaca
account, every idea measured on every bar and priced as options. Three indicators come bundled
(Stochastic, RSI, MACD); everything else is the user's own plug-ins.
Everything runs on the user's Mac. You drive it through one command line: `uv run kit <command>`.
Always add `--json` when you need to read a result; show the plain summary when the user asks.

## Fresh setup on a new Mac (do this first on a new clone)
Run these from the repository root, one at a time, and report each result in plain words:

1. `uv --version` — if missing: `brew install uv` (if Homebrew is missing too, point the user to
   https://brew.sh and stop; installing Homebrew needs their password, so they run it themselves).
2. `uv sync` — installs Python 3.12 and every package into `.venv` (about 30 seconds; needs internet).
3. `uv run kit doctor` — every line should be OK or TODO; FAIL lines must be fixed first.
4. `uv run kit smoke` — the whole pipeline on synthetic data; every check must say PASS (about a minute).
5. `uv run pytest` — the full test suite (about a minute).
6. Optional: `cp kit.toml.example kit.toml` and set the user's tickers and start date.

Then tell the user what is ready and what needs them: the TradeStation API key and sign-in
(`uv run kit login tradestation` — they type the key and sign in themselves in the browser),
and a TradingView export for `uv run kit match-check`. Nothing touches a broker account until then.

## Who you are working with
A trader, not a programmer. Lead with the answer in plain words. Use tables for numbers.
Never bury a caveat that changes the conclusion — put it first. Ask before anything that
downloads a lot, spends money (Databento), changes settings, or opens a sealed holdout.

## Research rules (non-negotiable)
1. **Every number carries its source**: the command or file that produced it
   (e.g. `[run: uv run kit study run first-look --json]`, `[file: studies/first-look/results/summary.json]`).
   An unsourced claim is an assumption and must be labelled **ASSUMED**.
2. **Readings at bar t use only data closed by t.** Higher timeframes come from the last
   closed bar (`mode = "closed"`) or the bar as it was forming live (`mode = "forming"`).
   Never use `tv` mode in a study — it repaints; it exists only for `kit match-check`.
3. **No fixed holds or fixed targets** unless that is the question. Write the entry and the
   exit in ONE line in `prereg.md` before any trade check. The kit refuses the trade check
   until `prereg.md` is complete.
4. **Every result is shown for both halves** (P1 and P2), with counts and fires per month.
   Something that only works in one half is not a result.
5. **Option results are priced as options**, with the expiry rule fixed at entry. Results
   from `kit` are MODELLED (Black-Scholes, no spread) — say so every time you quote one.
6. **Before believing a result, run a refute pass**: a fresh session (or a clearly separated
   step) whose only job is to break it — lookahead, censoring, tail concentration (top 3 days
   / tickers), Simpson's paradox (break down by setup type), tiny premiums, one-regime effects.

## Traps that void analyses
- Two units never mix: underlying R (move ÷ stop distance) and option multiple (value ÷ premium).
- Trades still open at the end are **censored**, not wins or losses — quote `pct_censored`.
- Count the tests. The report prints how many lift cells were tested and how many would look
  significant by luck. Mining more does not fix that; one pre-registered forward test does.
- A grade is worth something only if it beats **all bars** on the same exits.

## The user's own indicators and signals (the kit is built for this)
The bundled Stochastic / RSI / MACD are just three plug-ins. The user will bring their own
tools and setups, and you are the translator. Two kinds of extension, each with a guide in `.claude/skills/`:
- **An indicator** (a Pine script or a formula) → one file in `plugins/indicators/`, following
  `port-pine-indicator`. Start with `uv run kit new-indicator <name> --from-pine <file>`. It is not
  usable until `uv run kit check-indicator <name>` passes (no lookahead, coverage, readings), and not
  trusted until `uv run kit match-check <export> --indicator <name>` matches their chart.
  Worked example: `plugins/indicators/example_rsi_bands.pine` → `example_rsi_bands.py`.
- **A signal** (a setup in words) → an expression in the study's `study.toml` (`[signals.<name>]`),
  or a file in `plugins/signals/` for anything that needs history, following `add-signal`.
  `uv run kit columns <study>` lists what a signal can use.
Rules: never let a plug-in read the future (no negative shifts, no centred windows, higher timeframes
only through `ctx.htf` / `ctx.htf_prev`, pivots only where Pine reports them). If a Pine built-in is
missing, add it to `src/kit/ind/pine.py` with a hand-checked test rather than inline. Keep each
plug-in's "Port notes" docstring current — it is how the next session knows what was decided.

## How to do common jobs
- **Health check**: `uv run kit doctor --json`, then `uv run kit smoke --json`.
- **Get data**: `uv run kit login tradestation` (the user types the key and signs in in the
  browser — never ask them to paste a password, key or token into the chat), then
  `uv run kit fetch --tickers ...`. Fetch resumes; re-run after any interruption.
- **Prove the indicators**: `.claude/skills/check-indicator-match` → `uv run kit match-check <csv> --json`.
- **Run a study**: `.claude/skills/run-study` (prereg first, then `kit study run`).
- **Explain results**: `.claude/skills/explain-report` → `uv run kit report <name> --json`.
  Trade-by-trade detail is in `studies/<name>/results/trades.csv`.
- **Show what a study looks like**: `examples/sample-study/` (synthetic data); rebuild with `uv run kit examples`.
- **Free data**: `uv run kit login alpaca` then `uv run kit fetch --source alpaca` (free Alpaca account;
  1-minute bars since 2016). TradeStation stays the default when the user has API access.

## Never
- Never call, add or suggest code for any broker endpoint that places, changes or cancels
  orders, and never request the `Trade` scope. The guard in `src/kit/data/tradestation.py`
  and `tests/test_no_orders.py` enforce this; do not weaken them.
- Never print, log, or commit secrets. Secrets live in Keychain (fallback `.env`, git-ignored).
- Never open a network port to the internet. `kit webhook-log` listens on 127.0.0.1 only;
  exposing it is the user's deliberate choice with a tunnel they set up.
- Never edit `prereg.md` above the "## Verdict" line after a trade check has run. Append the
  verdict below it instead.
- Never present a modelled option result as money made.
- Never commit anything under `data/` or `studies/*/results/` — that is the user's private data.

## Code map
`plugins/indicators/`, `plugins/signals/` the user's own tools (examples included) ·
`src/kit/plugin.py` the Indicator interface + registry · `src/kit/signals.py` signals · `src/kit/check.py` check-indicator ·
`src/kit/ind/` indicators (pine.py = Pine built-ins; builtin.py = Stochastic, RSI, MACD; mtf.py = higher-timeframe modes) ·
Private or licensed indicators live outside the repository in a folder listed under `plugin_dirs` in `kit.toml` — never copy them into it ·
`src/kit/data/` store, TradeStation (read-only), Alpaca (free, read-only), TradingView import/match-check, synthetic data, optional Databento ·
`src/kit/method/` census, snapshot, scorecard, tradecheck, study, report · `tests/` (`uv run pytest`).
If you change an indicator, run `uv run pytest` and a `kit match-check` against a TradingView export before trusting it.
