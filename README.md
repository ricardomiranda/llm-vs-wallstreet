# llm-vs-wallstreet

version `0.11.0`.

This project helps me manage my securities portfolio. It works from real
brokerage data and uses large language models to answer one question above
all: should I sell? Wall Street analysts get paid to make that call; here a
language model makes it for the cost of a subscription.

## The idea

- **Long-term vision, not day trading.** The horizon is years, not minutes.
  Nothing here is about timing the market day to day.
- **Ground truth, not backtests on paper.** The analysis runs on real
  brokerage statements: actual positions, actual prices, actual cash.
- **The LLM is the analyst.** It ingests the statements, reconstructs the
  portfolio, and flags positions worth revisiting — because of news,
  market conditions, geopolitical tensions, or technical analysis that
  points to overvalued securities.
- **Explicit, dated calls.** Output artifacts record every recommendation
  so future runs can check it against what actually happened.

## Data

Brokerage statements live in `references/`:

| File | Source | Content |
| --- | --- | --- |
| `20260417.degiro.xlsx` | DeGiro | Portfolio snapshot ("Carteira"): product, ticker/ISIN, quantity, price, value, value in EUR |
| `20260515.interactive-brokers.csv` | Interactive Brokers (Ireland) | Activity statement, May 15 2026: account activity, positions, and statement fields in CSV form |

Statements are personal financial records. Do not commit anything that adds
identifying information beyond what is already tracked.

Timestamped DeGiro (`YYYYMMDD.degiro.xlsx`) and Interactive Brokers
(`YYYYMMDD.interactive-brokers.csv`) statements can be imported into a local
SQLite portfolio database:

```bash
.venv/bin/python scripts/import_portfolio.py
```

Use `/update-positions` in OpenCode to check `references/` for new timestamped
statements, validate supported files, and import them into the database.

The importer stores a separate snapshot for each statement in
`output/portfolio.sqlite3`; it preserves older statement dates and refreshes a
snapshot if its source file is updated. The generated database is ignored by
Git because it contains derived personal financial data. It records account
totals, positions, cash balances, and available FX rates. Position-limit rules
can be added to `position_limits`; `position_limit_alerts` exposes limit
breaches for dashboard use. Statement dates come from the filename (and are
checked against the IB statement period when available).

Delayed daily market prices and EUR valuations can be refreshed with
`/update-prices` in OpenCode or directly:

```bash
.venv/bin/python scripts/update_prices.py
```

The updater stores the original quoted price and currency, price date, EUR
conversion, FX rate and date, and provider mapping in local price history.
Yahoo Finance provides best-effort daily closes and Frankfurter provides daily
ECB reference rates. These are not live quotes; unmatched securities are
reported rather than guessed. `current_security_values_eur` and
`current_portfolio_value_eur` provide EUR-converted position and portfolio
values from the latest stored prices.

## Status

Early days. In place so far:

- Two reference statements (DeGiro, Interactive Brokers)
- Python 3.12 environment provisioning and dependency management
- Strict typing (`mypy --strict`) and a pre-commit gate
- Semantic versioning wired through `version.txt`, this README, and
  `.bumpversion.cfg`
- Trunk-based git workflow with helper commands

Still to come: parsers for each statement format, portfolio reconstruction,
the LLM analysis pipeline, and the scoreboard. `output/` will hold the
artifacts each analysis run produces.

## Repository layout

```
references/   brokerage statements (input data)
output/       artifacts produced by analysis runs
scripts/      project Python: env bootstrap, version bump, pre-commit gate
Makefile      entry points: make venv, make check, make bump
mypy.ini      strict type-checking configuration
AGENTS.md     instructions for AI coding agents working in this repo
.opencode/    opencode commands and vendored skills
```

## Getting started

Requires Python 3.12 and the system package `python3.12-venv`
(`sudo apt install python3.12-venv`).

```bash
make venv    # provision .venv and install requirements-dev.txt
make check   # mypy --strict + pre-commit gate
```

All project Python runs inside `.venv/` — either through the `Makefile` or
via `.venv/bin/python` directly. The venv is disposable and git-ignored.

## Versioning

Semantic versioning, bumped on every change that reaches `main` — including
docs-only edits. Bump with:

```bash
make bump PART=patch   # or minor, or major
```

`version.txt`, the version line in this README, and `current_version` in
`.bumpversion.cfg` are updated together by that command; they are never
edited by hand.

## Workflow

Trunk-based: short-lived branches off the latest `main`, merged through pull
requests, deleted once merged. No force-pushes, no history rewrites. The
`.opencode/commands/` directory documents the exact procedures
(`/commit-work`, `/new-pr`, `/sync-main`) used to keep the trunk releasable.

## License

TBD.
