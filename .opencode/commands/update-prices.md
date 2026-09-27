---
description: Fetch delayed daily security prices and convert portfolio positions to EUR
model: github-copilot/gpt-6-luna
---

# Update prices

Fetch the latest available daily close for securities in the local portfolio database, preserve each source price and currency, and store its EUR-converted price and the FX rate used.

## Workflow

1. Read `AGENTS.md` and check the working tree. Do not stage or commit the local database.
2. Confirm that `output/portfolio.sqlite3` exists and has imported portfolio snapshots. If not, tell the user to run `/update-positions` first.
3. Run the price updater in the project virtual environment:

   ```bash
   .venv/bin/python scripts/update_prices.py
   ```

4. The updater uses Yahoo Finance's public chart/search endpoints for daily closes and Frankfurter's daily ECB reference rates for conversion. Report price dates, original price/currency, EUR price, and any securities that could not be mapped or fetched.
5. Verify SQLite integrity and summarize the EUR values with:

   ```sql
   SELECT * FROM current_portfolio_value_eur;
   SELECT symbol, quantity, original_price, original_currency, price_date,
          fx_date, eur_per_original_unit, price_eur, position_value_eur
   FROM current_security_values_eur
   ORDER BY position_value_eur DESC;
   ```

## Important

- Prices are delayed daily data, not live quotes. Report each stored price date and do not present it as a real-time valuation.
- Yahoo symbol search is best-effort. Never guess an ambiguous mapping; report unmapped securities for review.
- Store both original quoted price/currency and EUR price, including FX rate and FX date. Do not overwrite price history for earlier dates.
- The local database contains derived personal financial data and is Git-ignored. Never stage or commit it.
- Price/value updates are not investment recommendations.
