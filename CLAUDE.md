# CLAUDE.md

The instructions for every AI assistant live in AGENTS.md, imported here so Claude Code reads them too:

@AGENTS.md

## Claude Code specifics
- The task guides in `docs/agents/` are also registered as Claude Code skills in `.claude/skills/`;
  each skill simply points at its guide, so there is one copy to keep current.
- To skip approval prompts for read-only commands, the user can add rules such as
  `"Bash(uv run kit report:*)"` to `permissions.allow` in `.claude/settings.local.json`. Keep
  `kit fetch` and `kit login` under `ask`. The repository ships no permission settings.
