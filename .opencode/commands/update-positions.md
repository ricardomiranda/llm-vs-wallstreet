---
description: Check references for new timestamped brokerage statements and import them into the local portfolio database
model: github-copilot/gpt-6-luna
---

# Update positions

Check `references/` for new supported timestamped brokerage statement files. If any are found, import them into the local SQLite portfolio database so they can be used in future portfolio analysis and recommendations.

## Workflow

1. Check the working tree and read `AGENTS.md` for project rules.
2. Run the check using the project virtual environment:

   ```bash
   .venv/bin/python scripts/import_portfolio.py --check
   ```

3. If no new supported files are reported, tell the user there is nothing to update and stop.
4. If new files are reported, verify their broker and date from the filename. Inspect the files sufficiently to confirm they are valid statements for the supported broker formats before importing.
5. Run the importer:

   ```bash
   .venv/bin/python scripts/import_portfolio.py
   ```

6. Verify the import output and SQLite integrity. Report the imported filenames, snapshot dates, brokers, and number of positions per snapshot. Mention parse failures or unsupported filenames without modifying or deleting the source files.

## Important

- Keep historical statement files and snapshots; do not delete or overwrite older dates.
- The importer refreshes a database snapshot if the same source filename is edited. Report that behavior if it occurs.
- The generated database is local and Git-ignored because it contains derived personal financial data. Never stage or commit it.
- Filenames must follow `YYYYMMDD.degiro.xlsx` or `YYYYMMDD.interactive-brokers.csv`.
- Do not make investment recommendations solely from detecting or importing files; this command updates position data for later analysis.
