# Data sources

| Source | Cost | Asset classes | 1-minute history | Commands |
|---|---|---|---|---|
| **Alpaca Market Data (Basic)** | Free; crypto needs no account | Stocks, crypto | Stocks: all-exchange (SIP) bars since 2016, requests must end ≥ 15 minutes ago, 200 calls/min. Crypto: 24/7 bars, depth not documented | `kit login alpaca`, `kit fetch --source alpaca` |
| **TradeStation API** | Free API; funded account required | Stocks, futures | ≤ 57,600 bars per request, ≤ 3 calendar years per minute request; depth depends on account | `kit login tradestation`, `kit fetch` |
| **Databento** *(optional)* | Pay as you go (credit for new accounts) | Stocks, futures | US equities (EQUS.MINI) from 2023-03-28; CME futures (GLBX.MDP3) from 2010-06-06 | `uv sync --extra databento`, `kit fetch --source databento` |
| **TradingView export** | Plus plan or higher | Anything on a chart | What the chart shows (10K–40K bars by plan) | `kit import-tv`, `kit match-check` |

## Asset classes and sessions

`kit fetch` decides each symbol's asset class, records it in `data/meta/<symbol>.json`, and every later
step reads it from there:

| Asset | Recognised from | Session | Trading day | Daily bar stamped |
|---|---|---|---|---|
| Stock / ETF | anything else | 09:30–16:00 New York | calendar date | 16:00 New York |
| Future | `@ES`, `ESZ26`, `ES.c.0` | 18:00–17:00 New York | the evening session belongs to the next day | 17:00 New York |
| Crypto | `BTC/USD`, `ETH-USD` | 00:00–24:00 UTC, 7 days | UTC date | 00:00 UTC |

Override the guess with `--asset stock|future|crypto`. Futures multipliers (dollars per point) are
filled in for common CME contracts (ES 50, MES 5, NQ 20, MNQ 2, YM 5, RTY 50, CL 1,000, GC 100,
SI 5,000, NG 10,000, ZN and ZB 1,000, 6E 125,000, and others); pass `--multiplier` for anything else.
A bare root such as `GC` is read as a stock ticker, so write `@GC` or add `--asset future`.

Intraday bars are anchored at each session's open, so futures 1-hour bars close at 19:00, 20:00 …
17:00 New York and 4-hour bars at 22:00, 02:00, 06:00, 10:00, 14:00 and 17:00. Holidays and early
closes are not modelled separately: a short session simply has fewer bars.

Facts above were checked against each provider's documentation on 2026-11-08; providers change
their terms — check before relying on them.

**Free sources evaluated and not built in:** Polygon / Massive Basic (free, 5 calls/min, 2 years);
Schwab Trader API (free with an account, ~48 days of 1-minute bars, 7-day sign-in); Interactive
Brokers (funded account and data subscriptions; no expired options); Tiingo (free, IEX-only intraday,
50 requests/hour); Yahoo via `yfinance` (unofficial; 1-minute bars for the last ~30 days).
**No free source provides historical option bid/ask.**

## Alpaca (free)

Crypto needs no account:

```bash
uv run kit fetch --source alpaca --tickers BTC/USD,ETH/USD,SOL/USD --start 2023-01-01
```

For stocks:

1. Sign up at [alpaca.markets](https://alpaca.markets) (no deposit needed).
2. In the Paper Trading dashboard, generate **API Keys**.
3. `uv run kit login alpaca` — paste the Key ID and Secret (hidden input; stored in the Keychain).
4. `uv run kit fetch --source alpaca --tickers SPY,QQQ --start 2022-01-01`

The kit only calls `GET https://data.alpaca.markets/v2/stocks/bars` (SIP feed, split-adjusted) and
`GET https://data.alpaca.markets/v1beta3/crypto/us/bars`; every other host and path is refused before a
request leaves the machine. Crypto minutes without trades arrive with zero volume, priced from quotes.

## TradeStation

**Getting an API key** (per TradeStation's pages, 2026-11-08):
- Existing customers: email ClientExperience@tradestation.com to request a key
  ([API FAQ](https://api.tradestation.com/docs/faq)). Ask for the default localhost callback
  (`http://localhost:3000` is on their default list).
- New accounts: TradeStation's [Trading API page](https://www.tradestation.com/platforms-and-tools/trading-api/)
  describes opening and funding an account (minimum $10,000), after which a key is issued. No subscription cost.

Then `uv run kit login tradestation`: it asks once for the key and secret (hidden, stored in the
Keychain) and opens your browser — you sign in on TradeStation's own page; the kit never sees your
password. Scopes requested: `openid offline_access MarketData` only. Trading scopes are refused even
if added to `kit.toml`.

`kit fetch` walks back in ~120-day windows, halves a window that hits the 57,600-bar limit, waits on
HTTP 429 (honouring `X-RateLimit-Reset`), saves after every window, and resumes from where it stopped.

Futures use TradeStation's symbols: `@ES` for the continuous contract or `ESZ26` for one expiry
(`uv run kit fetch --tickers @ES,@NQ`). TradeStation no longer offers crypto.

## Databento (optional, paid)

```bash
uv sync --extra databento
uv run kit fetch --source databento --tickers SPY --start 2023-04-01
uv run kit fetch --source databento --tickers ES.c.0,NQ.c.0 --start 2019-01-01
```

Store `DATABENTO_API_KEY` in the Keychain or `.env` first. The kit prints the cost and asks for
"yes" before downloading. Futures come from CME Globex (`GLBX.MDP3`); a symbol of the form
`ROOT.RULE.RANK` is a continuous contract (`ES.c.0` = front month by calendar, `ES.v.0` = by volume,
`ES.n.0` = by open interest), anything else is read as one contract (`ESZ6`). Databento's continuous
prices are not back-adjusted, so each roll appears as a jump in price.

## TradingView export

1. Put the indicators you want to check on a chart at the timeframe you want (start with 1h).
2. For stocks, turn **extended hours off** (the kit uses regular hours). Futures and crypto use their
   full sessions; add `--asset future` or `--asset crypto` if the export's file name hides the symbol.
3. Scroll back so plenty of history is loaded.
4. Chart menu → **Export chart data…** → choose a time format → Export.
   The file "includes time, OHLC data, and any plots".
5. `uv run kit match-check <file>.csv` (map a column by hand with `--map rsi_value="RSI"`).

If the same ticker has been fetched, match-check uses that longer history to warm the indicators up;
otherwise it skips the first 300 bars of the export.

## Option chain snapshots (real quotes, going forward)

`uv run kit snapshot-options --tickers SPY,QQQ` reads TradeStation's option-chain stream for the
nearest expirations and saves bid, ask, last, volume, open interest and greeks to
`data/options_snapshots/<date>/`. Run it daily (e.g. from `cron`) to build a real-quote history.

## Forward-test log (optional)

`uv run kit webhook-log` appends TradingView alert webhooks to `data/forward/alerts.jsonl`. It listens
on `127.0.0.1` only, so TradingView cannot reach it unless you deliberately put a tunnel in front of
it. TradingView sends webhooks only to ports 80/443 on a public address, from four fixed IPs, and
requires two-factor authentication ([TradingView help](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)).
Every request must carry the secret path printed at start-up.

## To confirm with your account

| Item | What is known | How you will see it |
|---|---|---|
| TradeStation minute history depth through the API | ≤ 57,600 bars and ≤ 3 calendar years per request; desktop help mentions 10+ years | `kit fetch` reports "history ended before your start date" |
| TradeStation minute bar stamps (open or close time) | Docs say UTC RFC 3339 | `kit fetch` detects open-stamped bars and shifts them (`shifted_open_stamps`) |
| TradeStation market-data entitlements for the API | Not documented | Delayed or refused bars → ask TradeStation |
| Option chains with `MarketData` scope alone | Not documented | `kit snapshot-options` fails clearly |
| TradeStation refresh-token rotation interval | Docs say 30 and 40 minutes in different places | New refresh tokens are saved automatically |
| Alpaca bar timestamps mark the bar **start** | Assumed from docs; tested against a mock | Compare one day with TradingView |
| Alpaca free-plan terms for personal backtesting | Not reviewed | Read Alpaca's terms |
| TradingView export time format and plot titles | UNIX seconds or ISO; titles = plot names | `kit import-tv` lists them |
| TradingView 2D bar alignment | Kit pairs trading days from 2000-01-03 | `kit match-check` on an indicator that reads 2D |
| Pine EMA warm-up seeding | SMA seed assumed; affects only early bars | `kit match-check --ema-seed first` |
| Databento cost and data layout | Untested without a key | Cost shown before download |
| TradeStation futures bar stamps and daily-bar time | Not documented; treated like stock bars | `shifted_open_stamps` in the fetch result; compare one day with TradingView |
| Alpaca crypto history depth and keyless rate limit | Not documented | `first` in the fetch result |
| TradingView futures and crypto bar anchoring | Futures day starts 18:00 New York (documented); hourly anchoring and crypto daily bars assumed | `kit match-check` |

## Troubleshooting

- **`kit doctor` says Python FAIL** — run commands as `uv run kit …`; uv picks Python 3.12.
- **TradeStation sign-in rejects the callback URL** — your key must allow `http://localhost:3000`, or set
  `ts_redirect_port` in `kit.toml` to another allowed port (3001, 8080, 31022).
- **`kit fetch` pauses** — the provider asked it to slow down; it waits and continues, and resumes if stopped.
- **`match-check` says CHECK** — read the worst bars it prints. Usual causes: extended hours on the chart,
  a different session, short warm-up (fetch more history), or EMA seeding (`--ema-seed first`).
