---
description: Build a staged, contribution-funded buy plan toward confirmed portfolio role targets
model: github-copilot/gpt-6-luna
---

# Recommend buys and gradual target balancing

Prepare a personalized, staged buy plan using the user's new contributions to move toward their portfolio role targets. This produces research-based estimates only: never place orders, edit positions, classify holdings, change limits, or change risk flags.

## Intake — ask before calculating

Use any answers supplied in `$ARGUMENTS`, then ask only for missing material inputs. Do not make up amounts, schedules, classifications, or personal constraints. The user has confirmed this role-target framework, subject to confirming each holding's role:

- 55% broad diversified market funds;
- 25% dependable dividend-growth companies;
- 15% other individual growth companies;
- 5% higher-uncertainty / special situations.

Broad diversified funds must be ETFs/funds, not individual companies. Keep this role framework separate from the database's explicit uncertain-investment classifications: neither a role nor a loss/concentration flag automatically determines uncertainty. Do not classify any holding silently. Present proposed role assignments with evidence and ask for confirmation before reporting actual role weights or a numeric allocation by role. Treat pension funds, real estate, and Bitcoin as outside these target percentages unless the user explicitly includes them.

Ask the user for the monthly contribution amount, contribution currency, and start date/cadence if not specified. Ask whether existing cash is available for investing and whether reinvested dividends are included in the stated contribution budget or should be treated separately. Do not infer investable cash from a negative or stale net cash balance. Ask for any exclusions, regional/sector preferences, minimum purchase size, fractional-share availability, and whether recommendations should be limited to current holdings or can include new securities. Confirm these constraints before sizing if their absence could change the recommendation.

The user has requested a gradual path funded by contributions first, using existing saved per-security limits with the default 10% maximum, and requires ETFs/funds for the broad-fund role. The user is open to both existing holdings and newly researched securities, permits fractional-share estimates, wants existing cash considered alongside contributions, and has no fixed completion deadline. Still ask how much cash is actually available, the monthly contribution amount/currency/first date, and whether dividends are included in that monthly budget or should be treated as a separate reinvested flow. Do not infer investable cash from the database balance. Use a flexible monthly review schedule rather than inventing a finish date.

## Data workflow

1. Read `AGENTS.md`; inspect the working tree; verify `output/portfolio.sqlite3` exists and contains usable imported snapshots. Never stage or commit that database.
2. Require a fresh `/update-prices` run before numeric buy estimates. Inspect SQLite integrity, `current_portfolio_value_eur`, `current_security_values_eur`, current cash balances, source prices/currencies, EUR conversions, and FX dates. Stop numeric allocation sizing if the database is missing/unreadable, integrity fails, any non-exempt price is stale, or cash is unconverted. Do not compute target deficits or weights on a partial denominator.
   - **Confirmed zero-value delisted-security exception:** a current holding may be treated as EUR 0 for scenario valuation, despite having no active provider mapping/price, only when (a) the user explicitly confirms both that it is delisted and that its scenario value is zero, and (b) the security identity is unambiguous. Record the security ID, quantity, and user-confirmed zero-value assumption. Exclude this one holding from the provider-priced count, include its zero in the scenario valuation, and disclose it separately as a user-valued exception—not as a fetched, priced, or verified zero. Never insert a synthetic price, alter the database, or infer this exception from delisting, a stale quote, a loss flag, or a small position alone. If the user has not confirmed zero, or any other current holding is unmapped/unpriced, stale, or otherwise uncovered, stop sizing and request corrected provider data followed by `/update-prices`.
3. Report current coverage/freshness and data used. Prices are delayed daily closes, not live quotes. Preserve the distinction between quoted price/currency and EUR converted price/FX date. Do not modify saved position limits, risk classifications, snapshots, cash, or trades.
4. Load current holdings, identifiers, quantities, current EUR values/weights, position limits, existing explicit risk flags, and saved research notes. Treat existing risk flags as user classifications only for the uncertainty budget, not as role assignments. Display prior saved research history and source-reading status for candidates; do not confuse headline search with full-text research.
5. Determine role weights only from user-confirmed classifications. If one or more material holdings remain unclassified, show confirmed classified coverage and unresolved value separately; do not state the target gap as definitive or claim the targets are achieved. Ask the user to confirm proposed assignments rather than filling gaps by inference. Funds and special situations should be described according to documented mandate/structure and evidence.

## Candidate research and staged allocation

For each bucket with a confirmed shortfall, identify suitable buy candidates supported by current evidence. Explain the fit to the specific role, valuation/fundamental considerations, risks, diversification effect, costs/fees for funds, and relevant issuer or fund events. Prefer primary issuer/regulatory/fund-provider sources and reputable independent reporting; cite publisher, date, and URL. Verify material facts when possible. State when source access or evidence is incomplete. Do not recommend a security solely because its price or broker P/L has fallen, and do not describe averaging down as a rationale by itself.

Allocate only the user-approved monthly amount and any cash explicitly confirmed available for investment. Show a staged plan with the proposed monthly EUR amount/percentage for each underweight bucket, asset, and first review/update point. A clear default when no horizon is supplied is to allocate new money among confirmed bucket deficits in proportion to their percentage-point shortfalls, then apply user preferences, diversification, and per-security limits; explain the arithmetic and show alternatives only when they materially change results. Do not recommend buys to an already-at/above-target bucket unless the user explicitly requests it or its proposed role is changed with approval.

For each security-level candidate report current weight, confirmed role and role target, proposed monthly allocation, estimated quantity/fractional-share assumption, estimated EUR amount, source price and currency, EUR price, price date, FX date/rate where relevant, configured security cap (security-specific or default 10%), and how the allocation respects the cap. The cap is a screening limit, not an objective to reach. Do not suggest buying more if the proposed purchase would exceed the cap; redirect only with a clearly stated, user-approved role allocation, not by silently reclassifying it. Include fees, tax, spreads, and price movement as exclusions from estimates.

Show progress as a contribution-led scenario, not a promise: estimate how the planned allocations could affect role weights after the specified contribution period, and name the assumptions (static prices/holdings, no withdrawals, no returns unless explicitly modeled). Re-evaluate using fresh prices and updated contributions before each later installment. If there is insufficient confirmed role data, do not provide precise target-balancing quantities; give the missing classifications and questions first.

## Report format

1. Data freshness, priced portfolio value, provider-priced and scenario-valued coverage (including any user-confirmed zero-value delisted-security exception), and available/confirmed investable cash.
2. Intake assumptions and any unanswered investor preferences.
3. Confirmed role weights versus 55/25/15/5 targets, including unclassified/excluded value and method.
4. Candidate-by-candidate rationale, source facts, risks, price/FX dates, limits, and proposed monthly amounts/quantities.
5. A gradual contribution schedule and next review checkpoint, with the effect and limitations.
6. Saved research history used and any unresolved information.

State that these are estimates, not trading instructions; no orders are placed. Never alter database contents as part of this command.

## Save the plan for the dashboard

After presenting the completed plan, save a local JSON copy next to the selected database, named `<database-stem>_buy_plan.json` (for the default database, `output/portfolio_buy_plan.json`). Do not write into or modify the portfolio database. Use this versioned structure so the dashboard can render the saved results:

```json
{
  "schema_version": 1,
  "prepared_at": "ISO-8601 timestamp",
  "summary": "Brief description of the plan and data freshness.",
  "budget": {
    "monthly_amount": 500,
    "currency": "EUR",
    "available_cash_eur": 1000,
    "first_date": "YYYY-MM-DD"
  },
  "roles": [
    {
      "role": "Broad diversified market funds",
      "current_weight_pct": 45,
      "target_weight_pct": 55,
      "gap_pct": 10,
      "confirmed_value_eur": 4500
    }
  ],
  "candidates": [
    {
      "symbol": "FUND",
      "description": "Fund name",
      "role": "Broad diversified market funds",
      "proposed_monthly_eur": 100,
      "estimated_quantity": 1.25,
      "current_weight_pct": 4,
      "security_cap_pct": 10,
      "source_price": 80,
      "source_currency": "EUR",
      "price_eur": 80,
      "price_date": "YYYY-MM-DD",
      "fx_date": "YYYY-MM-DD",
      "rationale": "Evidence-based fit and valuation context.",
      "risks": "Material risks and limitations.",
      "sources": [
        {
          "publisher": "Fund provider",
          "title": "Source title",
          "published_at": "YYYY-MM-DD",
          "url": "https://example.com/source"
        }
      ]
    }
  ],
  "assumptions": ["Static prices; fees and taxes excluded."],
  "next_review": "Refresh prices before the next monthly contribution."
}
```

Only save plans after the user has confirmed the classifications, budget, and material constraints. Preserve the rationale, cited source details, prices and their dates, and limitations. Saving or displaying a plan must not be described as placing or scheduling an order.
