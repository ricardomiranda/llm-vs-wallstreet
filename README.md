# llm-vs-wallstreet

version `0.33.0`.

This project helps me manage my securities portfolio. It works from real
brokerage data and uses large language models to answer one question above
all: should I sell? Wall Street analysts get paid to make that call; here a
language model makes it for the cost of a subscription.

## Quick sheet: see the latest recommendations

1. In OpenCode, run **`/evaluate-portfolio`**. It refreshes imported positions
   and delayed daily prices, reviews broker-reported losses, then checks
   concentration limits and reports eligible partial-sell estimates. It does
   not place orders.
2. To view the refreshed data in the dashboard, run:

   ```bash
   .venv/bin/python -m streamlit run scripts/dashboard.py
   ```

   Prices are delayed, not live. If sell estimates are withheld because a
   security has no confirmed price mapping or cash FX is missing, resolve the
   coverage issue, run `/update-prices`, then `/recommend-positions` again.
3. **Buy recommendations are separate.** Run **`/recommend-buys`** for a
   contribution-funded target-balancing review; it is not part of
   `/evaluate-portfolio`.

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

## Contributing work

Create a GitHub issue before starting each change. Use a short-lived branch
named with its issue number (for example `feat/42-price-refresh`), and include
that same issue in every commit subject (for example `Improve price refresh
handling (#42)`). Keep unrelated issues in separate branches and commits.

Open one pull request per issue and include `Closes #42` in its description;
GitHub will close the issue when the PR merges. Track issue progress on the
[Portfolio App Roadmap](https://github.com/users/ricardomiranda/projects/3)
board using its **Workflow status** field (Backlog, Ready, In progress, In
review, Done). The roadmap and automatic status sync are maintainer-specific;
the sync is skipped for pull requests from forks. Never commit brokerage
exports, portfolio databases, generated buy plans, credentials, or other local
portfolio data.

Run the Markdown documentation check locally with:

```bash
npx --yes markdownlint-cli2@0.18.1
```

The same check runs automatically on pushes and pull requests. The local
Node.js/npm toolchain is required to run it manually.

Automatic project status updates are optional maintainer automation for this
repository's roadmap board. To enable them, configure a repository Actions
secret named `GH_PROJECT_TOKEN` with the minimum GitHub Projects permissions
needed for that board. The workflow skips the update when the secret is absent
and does not run for fork pull requests.

## Data

Brokerage exports are private financial records. Supply your own supported
exports locally in `references/`; never upload them to issues, pull requests,
or the repository. The directory is ignored by Git except for its placeholder
file.

Timestamped DeGiro (`YYYYMMDD.degiro.xlsx`) and Interactive Brokers
(`YYYYMMDD.interactive-brokers.csv`) statements can be imported into a local
local SQLite portfolio database:

```bash
.venv/bin/python scripts/import_portfolio.py
```

Use `/update-positions` in OpenCode to check `references/` for new timestamped
statements, validate supported files, and import them into the database.

The importer stores a separate snapshot for each statement in
`output/portfolio.sqlite3`; it preserves older statement dates and refreshes a
snapshot if its source file is updated. The generated database is ignored by
Git because it contains private derived financial data. It records account
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

The default single-security concentration cap is 10%. Run
`.venv/bin/python scripts/recommend_positions.py` to receive an estimated
partial-sell quantity and EUR value for positions over their cap. A
security-specific `position_limits.max_portfolio_pct` overrides the default.
Recommendations are suppressed if any current security lacks a matched price
or any cash balance lacks EUR conversion; this avoids using an incomplete
portfolio value to calculate concentration. Sale estimates assume proceeds
remain as portfolio cash and exclude taxes, fees, and price movement; no orders
are placed.

Use `/recommend-buys` for a separate, contribution-funded target-balancing
review. It collects the contribution and cash budget, confirms each holding's
role before calculating role weights, requires complete price/FX coverage, and
produces staged estimates only; it does not place orders or modify portfolio
data.

Use `/review-losses` or run `.venv/bin/python scripts/review_losses.py` to flag
broker-reported unrealized losses for review. The default cost-basis review
threshold is 15% and can be changed with `--threshold-percent`. Separately,
the individual security report checks for a 20% decline from the highest
completed daily close in the trailing 12 months when at least 350 days of Yahoo
chart history are available. Both are review prompts, not automatic sell
signals or orders. Review whether dividends and other income materially affect
total return; statement P/L may omit dividend income. First-seen snapshot dates
are context only and do not establish the purchase date or holding period.

The dashboard's **Limits & review** tab includes broker-reported loss flags and
a 0–5 urgency score: 0 below the cost-basis review threshold, 1 at the
threshold, then one additional point for every 10 percentage points of loss,
capped at 5. The score measures loss severity only and is not a sell
recommendation.

The dashboard's on-demand **Individual security report** combines local
position and loss context with Yahoo Finance 52-week and trailing-12-month
rolling-peak price context, recent issuer-matched headlines when available, a
one-year price-only return, and a broad-market comparison. Headlines are
best-effort and should be checked against company filings and primary sources.
The risk-budget panel lets you
explicitly classify uncertain/speculative holdings, saves those choices to a
local database table, and compares their share of portfolio value with your
15% budget. Concentration-trim candidates and severe-loss flags are suggested
for consideration but never selected automatically. You can add speculative/high-
upside holdings you identify and positions you choose to keep despite a strong
sell suggestion.
Only your saved choices count toward this exposure budget; they are not automatic
risk classifications or a loss limit.

## Portfolio dashboard

Launch the local Streamlit dashboard with:

```bash
.venv/bin/python -m streamlit run scripts/dashboard.py
```

The dashboard reads `output/portfolio.sqlite3` locally and shows portfolio
valuation and price coverage, largest positions, searchable holdings, missing
prices, configured concentration limits, loss reviews, individual security
reports, saved buy plans, and snapshot history. Saving explicit risky-holding
classifications writes those labels to the local database; the saved buy plan is
kept separately in `output/portfolio_buy_plan.json`. Both remain local and are
not uploaded. Values use stored delayed daily prices and are not live quotes.

On the first day of each month, the dashboard reminds you to run
`/recommend-buys` for a contribution-funded target-balancing review. Refresh
prices before using it for numeric estimates. A completed plan saved in the
database's adjacent `<database-stem>_buy_plan.json` file appears in the
dashboard's **Buy plan** tab.

Change the default cap in the local database with:

```sql
UPDATE portfolio_settings
SET max_single_security_weight_pct = 8.0
WHERE singleton_id = 1;
```

For a security-specific cap, add a row to `position_limits` using the
security's `security_id`; its `max_portfolio_pct` takes precedence over the
default.

## Status

Early days. In place so far:

- Local import support for user-supplied brokerage statements
- Python 3.12 environment provisioning and dependency management
- Strict typing (`mypy --strict`) and a pre-commit gate
- Semantic versioning wired through `version.txt`, this README, and
  `.bumpversion.cfg`
- Trunk-based git workflow with helper commands

Still to come: parsers for each statement format, portfolio reconstruction,
the LLM analysis pipeline, and the scoreboard. `output/` will hold the
artifacts each analysis run produces.

## Repository layout

```text
references/   brokerage statements (input data)
output/       artifacts produced by analysis runs
scripts/      project Python: env bootstrap, version bump, pre-commit gate
Makefile      entry points: make venv, make check, make bump
mypy.ini      strict type-checking configuration
AGENTS.md     instructions for AI coding agents working in this repo
.opencode/    OpenCode command and agent instructions
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

This project's first-party code and documentation are licensed under the MIT
License. See [LICENSE](LICENSE). Third-party materials retain their own license
terms.

## Security and private data

Do not include broker exports, account identifiers, portfolio databases,
generated plans, credentials, or other private financial data in issues or pull
requests. See [SECURITY.md](SECURITY.md) for vulnerability reporting guidance.
