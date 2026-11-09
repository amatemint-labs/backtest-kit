# Working with an AI assistant

Backtest Kit is designed to be operated conversationally, by whichever coding assistant you use. The
assistant runs `uv run kit …` commands in the repository, reads their `--json` output, and follows
the project's written instructions:

- [`AGENTS.md`](../AGENTS.md): setup steps, research rules, asset classes, common jobs, and what the
  assistant must never do.
- [`docs/agents/`](agents/): one step-by-step guide per task.

| Guide | Used when you… |
|---|---|
| [port-pine-indicator](agents/port-pine-indicator.md) | hand over a Pine script or describe an indicator |
| [add-signal](agents/add-signal.md) | describe a setup in words |
| [run-study](agents/run-study.md) | want to test an idea (it writes the pre-registration with you first) |
| [check-indicator-match](agents/check-indicator-match.md) | share a TradingView export |
| [explain-report](agents/explain-report.md) | ask what a report means |

## Setting up your assistant

| Assistant | What it reads | Anything to do |
|---|---|---|
| Codex (CLI, IDE or cloud) | `AGENTS.md` | Nothing |
| Cursor | `AGENTS.md` | Nothing |
| GitHub Copilot coding agent | `AGENTS.md` | Nothing |
| Claude Code | `CLAUDE.md`, which imports `AGENTS.md`; the guides are also registered as skills in `.claude/skills/` | Nothing |
| Gemini CLI | `GEMINI.md` by default | Add `"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}` to `.gemini/settings.json`, or start with "Read AGENTS.md" |
| Aider | Files you add | `aider --read AGENTS.md` |
| Anything else | — | Start the session with "Read AGENTS.md and follow it" |

A chat assistant with no access to your terminal can still help: run a command with `--json` yourself
and paste the output, or attach `studies/<name>/results/summary.json`, along with `AGENTS.md` and the
guide for the task.

## First session

> Read AGENTS.md and README.md. Run `uv run kit doctor --json` and tell me in plain words what is ready and what is missing. Then run `uv run kit smoke` and show me the PASS/FAIL table. Don't fetch anything or change settings yet — ask me first.

## Useful prompts

- "Port my Pine script ~/Downloads/my_tool.pine into the kit, prove it has no lookahead, and tell me what you couldn't port."
- "Add a signal: 1h stochastic turns up from under 20 while the daily MACD histogram is positive. Calls."
- "Fetch two years of BTC/USD and ETH/USD and run the volume study on them."
- "Fetch @ES and @NQ from TradeStation and tell me how the futures sessions were built."
- "Show me the sample studies and walk me through both trade logs."
- "Help me write the prereg for this idea: … Then run the study."
- "Explain the first-look report. What held in both halves, and what are the eliminators?"
- "Refute this result: be a skeptic whose only job is to break it."

## Permissions

Most assistants ask before running a shell command. Read-only commands such as `kit doctor`,
`kit report`, `kit columns` and `kit study run` are safe to allow permanently; keep `kit fetch` and
`kit login` on ask, since they download data or store keys. The repository ships no permission
settings; that choice is yours.

## Sharing results

`report.html` is a single self-contained file: open it in a browser, attach it to a message, or host it
wherever you share documents.
