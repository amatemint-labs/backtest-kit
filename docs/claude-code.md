# Working with Claude Code

Backtest Kit is designed to be operated conversationally. Open [Claude Code](https://claude.com/claude-code)
in the repository folder; it reads `CLAUDE.md` (research rules, setup steps, code map) and the guides
in `.claude/skills/`:

| Guide | Used when you… |
|---|---|
| `port-pine-indicator` | hand over a Pine script or describe an indicator |
| `add-signal` | describe a setup in words |
| `run-study` | want to test an idea (it writes the pre-registration with you first) |
| `check-indicator-match` | share a TradingView export |
| `explain-report` | ask what a report means |

Every command supports `--json`, so Claude reads exact numbers and cites the command or file each
one came from.

## First session

> Read CLAUDE.md and README.md. Run `uv run kit doctor --json` and tell me in plain words what is ready and what is missing. Then run `uv run kit smoke` and show me the PASS/FAIL table. Don't fetch anything or change settings yet — ask me first.

## Useful prompts

- "Port my Pine script ~/Downloads/my_tool.pine into the kit, prove it has no lookahead, and tell me what you couldn't port."
- "Add a signal: 1h stochastic turns up from under 20 while the daily MACD histogram is positive. Calls."
- "Show me the sample study and walk me through the trade log."
- "Help me write the prereg for this idea: … Then run the study."
- "Explain the first-look report. What held in both halves, and what are the eliminators?"
- "Refute this result: be a skeptic whose only job is to break it."

## Permissions

To stop Claude Code asking before every read-only command, add rules such as
`"Bash(uv run kit doctor:*)"`, `"Bash(uv run kit report:*)"`, `"Bash(uv run kit study:*)"` to
`permissions.allow` in `.claude/settings.local.json`, and keep `kit fetch` and `kit login` under
`ask`. The repository does not ship permission settings; that choice is yours.

## Sharing results

`report.html` is a single self-contained file — open it in a browser, attach it, or ask Claude to
publish it as a private page if your Claude plan supports artifacts.
