---
description: Identify positions above configured portfolio-weight limits and estimate partial sells
model: github-copilot/gpt-6-luna
---

# Recommend position trims

Review the latest EUR-valued positions and identify any single-security weight above its configured maximum. Report a partial-sell estimate to return each excess position to its cap.

## Workflow

1. Read `AGENTS.md` and verify the local database exists.
2. Run `.venv/bin/python scripts/recommend_positions.py`.
3. If the database has any missing/unpriced current security or unconverted cash, do not issue a partial-coverage sell recommendation, even if the script prints estimates using a partial denominator. Report the missing coverage and ask for corrected mappings/provider data followed by `/update-prices` and a fresh `/recommend-positions` run.
4. For each eligible recommendation, explain current weight, target weight, estimated quantity to sell, estimated EUR proceeds, price date, and the configured limit source (default or security-specific). In the dashboard's individual security report, put the concentration-control rationale first and keep it distinct from a thesis-based sell case. Include the latest saved research digest and relevant prior findings/source reading status. Digests should be comprehensive and paragraph-separated, generally 4–8 substantive paragraphs and about four times longer than a brief prior note; cover relevant evidence for and against a possible sell case, including issuer-specific management/governance, financial/business quality, competition, operational, macro/sector, and legal/regulatory/geopolitical factors. State the user's individual holding 20%-from-peak review trigger separately from broker-loss urgency; it is a review prompt, not a trade instruction. End by stating whether reading changed the business/thesis assessment and why, and separately that reading does not change the mechanically calculated loss-urgency score. Include up to five targeted user questions only if answers to a specific documented unknown could materially change or personalize the assessment; explain why they matter and do not ask generic exit questions. Search headlines are not full-article research unless the source was actually read.
5. Make clear these are concentration-control suggestions, not instructions or placed orders. Do not execute trades.

## Limits

- Default maximum weight: 10% per security.
- A non-null `position_limits.max_portfolio_pct` overrides the default for that security.
- Recommendations require complete current security-price and cash FX coverage. If coverage is incomplete, suppress recommendations rather than calculate weights from a partial portfolio.
- This workflow generates concentration-based partial-sell estimates only; it does not make a thesis-based decision to sell. Use `/recommend-buys` for a separate contribution-funded buying and target-balancing review. Loss urgency alone is not a sell signal.
- Estimates use the latest stored daily price, assume sale proceeds remain in the portfolio as cash, and do not include fees, taxes, slippage, or price changes before execution.
- Never stage or commit `output/portfolio.sqlite3`.
