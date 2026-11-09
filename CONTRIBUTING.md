# Contributing

Thanks for your interest in Backtest Kit. People use it to decide which trading ideas deserve real
money, so a few rules apply to every change.

## Setup

```bash
uv sync
uv run pytest            # about a minute; must pass
uv run kit smoke         # end-to-end self-test
```

## Ground rules

1. **Read-only.** No code may place, change or cancel orders, request trading scopes, or contact
   a non-market-data endpoint. `tests/test_no_orders.py` enforces this; do not weaken it.
2. **No lookahead.** A reading at bar *t* may use only bars closed by *t*. New indicators must pass
   `uv run kit check-indicator <name>`; changes to joins or simulation must keep
   `tests/test_no_lookahead.py` green.
3. **Hand-checked numbers.** New numerical functions (e.g. a Pine built-in) come with a test whose
   expected values are worked out by hand in a comment, or compared with an independent implementation.
4. **Both halves.** New result tables report P1 and P2 separately.
5. **No machine paths or private data** in committed files (`tests/test_repo_clean.py`). Never commit
   anything under `data/` or `studies/*/results/`.
6. **Licensing.** Only contribute indicators you have the right to publish. Ports of commercial
   indicators belong in a private plug-in folder (`plugin_dirs`), not in this repository.

## Pull requests

- One topic per PR, with a short description of what changed and how you verified it.
- Run `uv run pytest` and `uv run kit smoke`; regenerate `examples/sample-study/` with
  `uv run kit examples` if outputs change.
- Update the relevant page in `docs/` when behaviour changes.
