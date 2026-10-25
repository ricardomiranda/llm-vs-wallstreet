---
description: Flag broker-reported position losses for review without recommending automatic sales
model: github-copilot/gpt-6-luna
---

# Review portfolio securities

Create an individual security report from portfolio facts and current external context: broker-reported basis/P&L, stored market prices, 52-week range, dividend estimates, dated issuer headlines, and merger/regulatory/earnings items when the source returns them. Explain source and freshness. Separate sourced facts from analysis and unknowns. Never claim full event coverage from search results.

Write a useful, balanced issuer report, not merely a chart-and-headline digest. Separate **sourced facts**, **analysis**, and **unknowns/limitations**. Discuss the market and sector outlook, issuer fundamentals, and material news such as M&A, earnings, guidance, regulation, or litigation when supported by sources. Explain the competitive landscape with relevant competitors or substitutes and the specific competitive dimensions (capability, price/bundling, distribution, switching costs, or adoption) where evidence is available. Discuss geopolitical, regulatory, and legal exposure, but distinguish documented current events from plausible forward-looking risks; do not claim they caused a price decline without evidence. If no issuer-specific constraint or causal link was found, say so. Translate evidence into balanced long-term thesis supports, risks, and observable future indicators that could strengthen or weaken the outlook. Relate these to the original investment thesis if known; otherwise explicitly say it was not provided. Do not make unsupported forecasts or fill missing evidence with generic market claims. Treat loss thresholds as review prompts, not sell rules. The user's usual holding period is at least one year, but it is a preference, not an absolute requirement when the thesis materially changes.

Risk tolerance: the user accepts up to 15% of total portfolio value in investments they personally regard as uncertain/speculative, potentially for high upside. This is a portfolio exposure budget, not a 15% loss limit. In the dashboard, suggest concentration trim candidates and severe loss-review flags for review, but do not automatically call them risky: concentration, loss severity, and uncertainty are different. Invite the user to add speculative/high-upside holdings they identify, and any holding they choose to retain despite a strong sell suggestion. Only explicit saved user classifications count toward the 15% budget. Never classify holdings as risky automatically.

Individual reports fetch Yahoo Finance chart and search data on demand. Include one-year price-only return versus SPY when available, issuer-related dated headlines from the last 120 days, dividend-provider context, cost basis, broker unrealized P/L, current portfolio weight, and existing urgency score. Headline tagging is keyword-based; do not state an M&A, regulatory or legal event as fact from an ambiguous headline alone. Distinguish price decline from total return, especially for dividend-oriented holdings.

For any position with urgency **4/5 or 5/5**, read at least **three full, relevant articles or primary-source publications** before drawing an evidence-based conclusion about what may be contributing to the loss or whether the original thesis needs reassessment, unless either exception applies: the current position is explicitly saved as the user's risk investment in the portfolio risk classifications, or its latest stored EUR position value is **below €10**. A value of exactly €10 does not qualify for the size exception. Determine size from the latest stored EUR position value, not cost basis or original investment. Apply either exception independently. Prefer issuer filings/releases and regulator documents for primary facts, supplemented by independent reputable reporting or analysis. Do not count search-result snippets, duplicate syndications of the same release, or articles that merely repeat a price move as three independent confirmations. Cite/link each item with publisher and date; summarize what each independently establishes and note disagreement or limits. If three suitable full-text sources cannot be accessed, say how many were reviewed and that confirmation is incomplete; do not imply the threshold alone recommends selling. This extra research supports a review, not a buy/sell instruction.

After reviewing a security's news, persist a dated research note in the selected portfolio database so its findings remain available in later reports. Save a concise but decision-useful synthesis: material sourced facts and provenance, market/sector and competitive context, documented versus prospective geopolitical/regulatory issues, balanced long-term thesis supports and risks, observable indicators to monitor, unresolved limitations, and urgency/current EUR position value where available. Include dated citations for sources actually consulted and mark whether each full text was read. Explicitly record whether the research changed the assessment and why; distinguish this judgment from rule-based concentration trim estimates. A list of headlines or chart statistics alone is not an adequate note. Do not store search snippets as full-text reviews or invent findings or citation details. Append a new note per review; preserve prior research history.

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
5. For urgency 4/5 and 5/5, read and cite at least three full, relevant articles or primary-source publications when available, except for explicitly user-saved risk investments or positions whose latest stored EUR value is below €10. A position valued exactly €10 is not exempt by size. Use the source-independence and incomplete-coverage rules above. For other urgency scores, use available report context without this minimum.
6. Review total return including dividends, the original investment thesis, company/fund fundamentals, competitive positioning, market/sector context, and relevant M&A, earnings, regulatory, legal, and geopolitical developments. Separate sourced facts from analysis and unknowns. Explain the long-term implications conditionally and identify evidence that could confirm or weaken the thesis. Clearly state when no relevant sources or metadata are available, when primary-source verification fails, or when an apparent risk is only prospective rather than a documented current constraint. Let the user decide; do not turn a score, headline, or plausible risk into a sell instruction.
7. Save a note for each researched security using the project virtual environment and the database selected in the dashboard:

   ```bash
   .venv/bin/python scripts/record_security_research.py --database <path> <<'JSON'
   {
     "security_id": "stable portfolio security ID",
     "symbol": "ticker",
     "description": "issuer or fund name",
     "urgency_score": 4,
     "position_value_eur": 123.45,
     "summary": "Concise sourced synthesis, separating facts from interpretation.",
     "recommendation_impact": "Research did not change the concentration trim estimate; it remains a rule-based limit check, not a trade instruction.",
     "findings": ["Sourced factual finding"],
     "limitations": ["Unresolved question or unavailable evidence"],
     "sources": [
       {
         "title": "Filing or article title",
         "publisher": "Publisher or issuing organization",
         "url": "https://...",
         "published_at": "YYYY-MM-DD",
         "full_text_read": true
       }
     ]
   }
   JSON
   ```

   Use `null` for unknown urgency, position value, or publication date. Include only sources actually inspected and their true reading status. Save inconclusive reviews too, with limitations. The dashboard shows entries under **Saved research history**; do not overwrite or delete older notes.

## Limits

- The default 20% threshold is a configurable review trigger, not a universal risk limit.
- Urgency score is 0 below threshold; 1 at threshold; each additional 10 percentage points of loss adds one, capped at 5. It measures loss severity only and does not determine whether to sell.
- Use broker-reported unrealized P/L and cost basis; do not treat a price decline alone as a sell signal.
- Broker statement P/L may exclude dividends and may use different reporting dates across accounts. Call this out, especially for income holdings such as AT&T.
- Positions lacking cost basis or unrealized P/L are listed as not assessed, not treated as having zero loss.
- The dashboard's position-value filter is an attention aid based on latest EUR-marked position value, not a loss-risk threshold. A low-value speculative position can still lose all its value; a higher value is not proof it should be sold.
- Historical snapshot dates show only when a position first appears in available statements; they do not establish its actual purchase date or one-year holding period.
- External headlines and price metadata are best-effort, may be stale or incomplete, and must be verified against primary company/regulatory sources. Dividend yield is historical/provider-reported and dividends may change or stop.
- Never state that the 15% risk budget is within or exceeded unless the user has explicitly selected and saved the risky holdings in the dashboard. Only saved classifications count; a current unsaved widget selection does not.
- No orders are placed. Database changes are limited to appending the sourced research notes described above; do not alter position, classification, limit, or historical research data.
