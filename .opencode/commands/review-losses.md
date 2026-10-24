---
description: Flag broker-reported position losses for review without recommending automatic sales
model: github-copilot/gpt-6-luna
---

# Review portfolio securities

Create an individual security report from portfolio facts and current external context: broker-reported basis/P&L, stored market prices, 52-week range, dividend estimates, dated issuer headlines, and merger/regulatory/earnings items when the source returns them. Explain source and freshness. Separate sourced facts from analysis and unknowns. Never claim full event coverage from search results.

The report should discuss market/sector conditions, issuer fundamentals and material news such as mergers, earnings, guidance, regulatory actions or litigation when verifiable. Relate these to the original holding thesis if known; otherwise say it was not provided. Treat loss thresholds as review prompts, not sell rules. The user's usual holding period is at least one year, but it is a preference, not an absolute requirement when the thesis materially changes.

Risk tolerance: the user accepts up to 15% of total portfolio value in investments they personally regard as uncertain/speculative, potentially for high upside. This is a portfolio exposure budget, not a 15% loss limit. In the dashboard, suggest concentration trim candidates and severe loss-review flags for review, but do not automatically call them risky: concentration, loss severity, and uncertainty are different. Invite the user to add speculative/high-upside holdings they identify, and any holding they choose to retain despite a strong sell suggestion. Only explicit saved user classifications count toward the 15% budget. Never classify holdings as risky automatically.

Individual reports fetch Yahoo Finance chart and search data on demand. Include one-year price-only return versus SPY when available, issuer-related dated headlines from the last 120 days, dividend-provider context, cost basis, broker unrealized P/L, current portfolio weight, and existing urgency score. Headline tagging is keyword-based; do not state an M&A, regulatory or legal event as fact from an ambiguous headline alone. Distinguish price decline from total return, especially for dividend-oriented holdings.

## Workflow

1. Read `AGENTS.md` and verify `output/portfolio.sqlite3` contains imported snapshots. If not, ask the user to run `/update-positions` first.
2. Run the report in the project virtual environment:

   ```bash
   .venv/bin/python scripts/review_losses.py
   ```

   To use a different threshold, for example 15%:

   ```bash
   .venv/bin/python scripts/review_losses.py --threshold-percent 15
   ```

3. In the dashboard's **Limits & review → Loss review and urgency**, use the **Minimum current position value to show (EUR)** filter to focus the table on larger current positions; it defaults to positions above €70 and can be lowered or raised. This only filters the table, not the underlying loss analysis or individual security reports. Choose any security in **Individual security report** to see broker facts, price context, dividend context, and dated issuer headlines. The report fetches public Yahoo Finance chart/search data on demand.
4. For each flagged position, explain its 0–5 urgency score, broker-reported P/L and cost basis, currency, statement date, and first-seen snapshot date. First-seen is not a purchase date and must not be treated as proof that the position has been held for a year.
5. Review total return including dividends, the original investment thesis, company/fund fundamentals, and relevant M&A, earnings, regulatory or legal developments. Clearly state when these sources return no information. Let the user decide; do not turn a score or headline into a sell instruction.

## Limits

- The default 20% threshold is a configurable review trigger, not a universal risk limit.
- Urgency score is 0 below threshold; 1 at threshold; each additional 10 percentage points of loss adds one, capped at 5. It measures loss severity only and does not determine whether to sell.
- Use broker-reported unrealized P/L and cost basis; do not treat a price decline alone as a sell signal.
- Broker statement P/L may exclude dividends and may use different reporting dates across accounts. Call this out, especially for income holdings such as AT&T.
- Positions lacking cost basis or unrealized P/L are listed as not assessed, not treated as having zero loss.
- The dashboard's position-value filter is an attention aid based on latest EUR-marked position value, not a loss-risk threshold. A low-value speculative position can still lose all its value; a higher value is not proof it should be sold.
- Historical snapshot dates show only when a position first appears in available statements; they do not establish its actual purchase date or one-year holding period.
- External headlines and price metadata are best-effort, may be stale or incomplete, and must be verified against primary company/regulatory sources. Dividend yield is historical/provider-reported and dividends may change or stop.
- Never state that the 15% risk budget is within or exceeded unless the user has explicitly selected the risky holdings in the dashboard. The selection is currently session-only.
- No orders are placed and no database values are changed.
