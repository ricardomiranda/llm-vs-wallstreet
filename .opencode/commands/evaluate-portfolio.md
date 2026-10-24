---
description: Refresh portfolio statements and prices, review losses and issuer context, then check concentration limits
model: github-copilot/gpt-6-luna
---

# Evaluate portfolio

Run a complete portfolio review by invoking the existing commands in order: `/update-positions`, `/update-prices`, `/review-losses`, then `/recommend-positions`. Execute each command workflow before moving to the next so every analysis uses the freshest imported positions and stored prices. Do not merely print the command names, skip a blocked step, or imply later steps used fresh data when an earlier update failed.

## Workflow

1. Read `AGENTS.md`, check the working tree, and verify `output/portfolio.sqlite3` exists. Never stage or commit that database. If it is missing or has no imported snapshots, stop and ask the user to run `/update-positions`.
2. Invoke `/update-positions`. This checks for new supported statements and imports valid new files. Preserve historical snapshots and source files. If nothing new is present, proceed using existing snapshots. If statements are malformed or unsupported, report the problem; do not claim they were imported. If the command cannot establish that the database contains usable snapshots, stop.

3. Invoke `/update-prices`. Summarize latest price dates and source-price coverage. Identify unmapped or unfetched securities. Verify SQLite integrity and inspect `current_portfolio_value_eur` and `current_security_values_eur`. If the database is missing, unreadable, or integrity fails, stop further analysis and report the blocker.

4. Invoke `/review-losses` at its default 20% review threshold. Explain the 0–5 severity score, broker P/L and cost basis, currency, statement date, and first-seen snapshot date for every loss position. Report positions missing valid cost basis or P/L as not assessed. First-seen is not a purchase date; broker P/L may exclude dividends. If the user supplies a threshold after `/evaluate-portfolio`, pass it with `--threshold-percent` instead of the default.

   The dashboard loss-review table has a minimum current EUR position-value filter, defaulting to positions above €70. This is only an attention filter; do not imply smaller speculative positions are protected from total loss or that larger positions should automatically be sold.

5. For every position flagged at or above the loss threshold, use the stored Yahoo Finance mapping to fetch on-demand chart and issuer-news context via the project’s `security_research.fetch_market_context` function, following the report behavior in `scripts/dashboard.py`. Include latest chart date and price, 52-week range, approximate one-year price-only return versus SPY when available, drawdown from the yearly high, and provider dividend estimates when returned. Include issuer-related dated headlines from the last 120 days, emphasizing relevant earnings, guidance, M&A, regulatory, or legal items when returned. State when no headlines or metadata are available, distinguish price return from total return, and verify event claims using primary company or regulatory sources where possible. For urgency 4/5 or 5/5, read at least three full, relevant articles or primary-source publications before drawing an evidence-based conclusion about possible causes or thesis changes, except when the current position is explicitly saved as the user's risk investment or its latest stored EUR value is below €10 (exactly €10 is not exempt). Determine value from the latest stored EUR position value. Prefer primary issuer/regulatory sources plus independent reputable reporting; do not count snippets, duplicate syndications, or price-move commentary as separate confirmations. Cite each with publisher/date and summarize what it establishes. If three suitable sources cannot be accessed, disclose the number read and that confirmation remains incomplete; urgency is not a sell signal. After researching each security, append a sourced note to the selected database using `.venv/bin/python scripts/record_security_research.py --database <path>` with JSON fields specified by `/review-losses`. Store only actually inspected sources and their true full-text-read status; preserve prior notes.

   Present sourced facts separately from analysis and unknowns. Discuss sector/market context and issuer fundamentals only to the extent supported by sources. The original investment thesis was not supplied unless explicitly present in user-provided context; say so when unknown. Headline categories are keyword-based and search results are incomplete; never claim full event coverage or treat an ambiguous headline alone as proof of an event. Treat the loss threshold as a review prompt, not a sell rule. The user's usual one-year holding period is a preference, not proof of time held or a requirement to wait if the thesis materially changes.

6. Invoke `/recommend-positions` only after `/update-prices` has completed. If it reports missing price coverage or unconverted cash, do not present partial-sell recommendations; report the coverage issue and request corrected mappings/provider data followed by `/update-prices`. For eligible candidates, report current and target weight, estimated quantity and EUR proceeds, price date, and whether the limit is the default or security-specific. These are concentration-control suggestions, not trading instructions.

7. Only after all evaluation steps finish successfully, record the completion time in the selected portfolio database using UTC:

   ```bash
   .venv/bin/python scripts/record_evaluation.py
   ```

   This creates or updates the database's singleton evaluation timestamp. If the dashboard is configured to use a non-default database, pass it with `--database <path>`. Never update the timestamp for a partial run or a run stopped by an error.

8. State the portfolio's priced value and data freshness, then clearly separate:
    - broker-reported loss review flags;
    - price/news context and analysis;
    - concentration trim estimates;
    - missing or stale information;
    - newly recorded notes and prior saved research history for each researched security.

   Do not classify a position as uncertain/risky based on concentration or loss. The 15% uncertainty exposure budget counts only the user's explicit saved classifications; if this information is unavailable, do not state that the budget is within or over limit. No orders are placed.

## Safety and data limits

- The invoked command workflows run project scripts with `.venv/bin/python`.
- Prices are delayed daily closes, not live quotes. Show actual stored dates, including stale prices retained when a fetch fails.
- Price mapping and news search are best-effort. Do not guess ambiguous symbols or imply complete price/news/event coverage.
- Preserve both source price/currency and EUR conversion/FX date; do not remove historical price observations.
- Broker statement P/L can omit distributions and statement dates can differ by account. Consider total return, especially for dividend-oriented positions.
- Missing cost basis/P&L means not assessed, never zero loss.
- Do not modify saved risk classifications, position limits, or trade data as part of this evaluation. Database changes are limited to importing valid new source statements, appending price/FX data through existing workflows, recording evaluation completion, and appending sourced research notes.
- Do not execute trades or change source statement files.
