---
description: Identify positions above configured portfolio-weight limits and estimate partial sells
model: github-copilot/gpt-6-luna
---

# Recommend position trims

Review the latest EUR-valued positions and identify any single-security weight above its configured maximum. Report a partial-sell estimate to return each excess position to its cap.

## Workflow

1. Read `AGENTS.md` and verify the local database exists.
2. Run `.venv/bin/python scripts/recommend_positions.py`.
3. If the script reports incomplete prices or unconverted cash, do not issue a sell recommendation. Report the missing coverage and ask for `/update-prices` to be rerun after mappings/provider data are addressed.
4. For each eligible recommendation, explain current weight, target weight, estimated quantity to sell, estimated EUR proceeds, price date, and the configured limit source (default or security-specific). In the dashboard's individual security report, put the recommendation rationale digest first. Include relevant saved research findings and source reading status, and explicitly state whether the research changed the assessment and why. Search headlines are not full-article research unless the source was actually read.
5. Make clear these are concentration-control suggestions, not instructions or placed orders. Do not execute trades.

## Limits

- Default maximum weight: 10% per security.
- A non-null `position_limits.max_portfolio_pct` overrides the default for that security.
- Recommendations require complete current security-price and cash FX coverage. If coverage is incomplete, suppress recommendations rather than calculate weights from a partial portfolio.
- This workflow generates concentration-based partial-sell estimates only; it does not generate buy recommendations or make a thesis-based decision to sell. Loss urgency alone is not a sell signal.
- Estimates use the latest stored daily price, assume sale proceeds remain in the portfolio as cash, and do not include fees, taxes, slippage, or price changes before execution.
- Never stage or commit `output/portfolio.sqlite3`.
