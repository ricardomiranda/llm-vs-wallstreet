"""Local Streamlit dashboard for exploring portfolio positions and limits."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypeAlias
from urllib.parse import quote

import pandas as pd
import streamlit as st

from import_portfolio import DEFAULT_DATABASE
from update_prices import PRICE_SCHEMA


Row: TypeAlias = dict[str, str | int | float | None]


st.set_page_config(
    page_title="Portfolio Desk",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def connect_readonly(database: Path) -> sqlite3.Connection:
    """Open an existing portfolio database without allowing writes."""
    encoded_path = quote(str(database.resolve()), safe="/:")
    return sqlite3.connect(f"file:{encoded_path}?mode=ro", uri=True)


def load_dashboard_data(database: Path) -> tuple[dict[str, object], list[Row], list[Row], list[Row]]:
    """Load the summary, holdings, limits, and statement history."""
    with closing(connect_readonly(database)) as connection:
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if "snapshots" not in objects:
            raise RuntimeError("The database has no imported portfolio snapshots")
        summary: dict[str, object] = {
            "priced_positions_eur": None,
            "cash_value_eur": None,
            "priced_portfolio_value_eur": None,
            "priced_security_count": 0,
            "unpriced_security_count": 0,
            "latest_price_date": None,
            "unconverted_cash_count": 0,
            "total_security_count": 0,
        }
        if "current_portfolio_value_eur" in objects:
            cursor = connection.execute("SELECT * FROM current_portfolio_value_eur")
            columns = [column[0] for column in cursor.description or []]
            values = cursor.fetchone()
            if values is not None:
                summary.update(dict(zip(columns, values, strict=True)))

        snapshot_stats = connection.execute(
            """WITH ranked AS (
                   SELECT id, account_id, as_of_date,
                          ROW_NUMBER() OVER (
                              PARTITION BY account_id
                              ORDER BY as_of_date DESC, id DESC
                          ) AS snapshot_rank
                   FROM snapshots
               )
               SELECT MAX(as_of_date), COUNT(*)
               FROM ranked WHERE snapshot_rank = 1"""
        ).fetchone()
        summary["latest_snapshot_date"] = snapshot_stats[0] if snapshot_stats else None
        summary["account_count"] = snapshot_stats[1] if snapshot_stats else 0

        if "current_security_values_eur" in objects:
            value_fields = "v.price_date, v.original_price, v.original_currency, " \
                "v.fx_date, v.eur_per_original_unit, v.price_eur, " \
                "v.position_value_eur"
            value_join = "LEFT JOIN current_security_values_eur AS v " \
                "ON v.security_id = p.security_id"
        else:
            value_fields = "NULL, NULL, NULL, NULL, NULL, NULL, NULL"
            value_join = ""
        holdings_query = f"""WITH ranked AS (
                SELECT id, account_id, as_of_date,
                       ROW_NUMBER() OVER (
                           PARTITION BY account_id
                           ORDER BY as_of_date DESC, id DESC
                       ) AS snapshot_rank
                FROM snapshots
            ), current_positions AS (
                SELECT p.security_id,
                       COALESCE(MAX(CASE WHEN p.symbol != p.security_id
                                         THEN p.symbol END), MAX(p.symbol)) AS symbol,
                       MAX(p.description) AS description,
                       SUM(p.quantity) AS quantity,
                       GROUP_CONCAT(DISTINCT p.currency) AS statement_currencies,
                       GROUP_CONCAT(DISTINCT a.broker) AS brokers
                FROM positions AS p
                JOIN ranked AS r ON r.id = p.snapshot_id AND r.snapshot_rank = 1
                JOIN accounts AS a ON a.id = r.account_id
                GROUP BY p.security_id
            )
            SELECT p.security_id, p.symbol, p.description, p.quantity,
                   p.statement_currencies, p.brokers, {value_fields},
                   l.max_portfolio_pct, l.notes
            FROM current_positions AS p
            {value_join}
            LEFT JOIN position_limits AS l ON l.security_id = p.security_id
            ORDER BY COALESCE(v.position_value_eur, 0) DESC, p.symbol"""
        cursor = connection.execute(holdings_query)
        holdings = [dict(zip((item[0] for item in cursor.description or []), row, strict=True))
                    for row in cursor.fetchall()]

        limit_rows: list[Row] = []
        if "position_limits" in objects and "position_limit_alerts" in objects:
            cursor = connection.execute(
                """SELECT security_id, symbol, description, portfolio_pct,
                          max_portfolio_pct, market_value_base, base_currency,
                          exceeds_max_value, exceeds_max_portfolio_pct
                   FROM position_limit_alerts
                   WHERE snapshot_id IN (
                       SELECT id FROM (
                           SELECT id,
                                  ROW_NUMBER() OVER (
                                      PARTITION BY account_id
                                      ORDER BY as_of_date DESC, id DESC
                                  ) AS snapshot_rank
                           FROM snapshots
                       ) WHERE snapshot_rank = 1
                   )
                   ORDER BY portfolio_pct DESC"""
            )
            limit_rows = [
                dict(zip((item[0] for item in cursor.description or []), row, strict=True))
                for row in cursor.fetchall()
            ]

        cursor = connection.execute(
            """SELECT a.broker, s.as_of_date, s.source_file,
                      s.base_currency, s.total_value_base,
                      COUNT(p.security_id) AS position_count
               FROM snapshots AS s
               JOIN accounts AS a ON a.id = s.account_id
               LEFT JOIN positions AS p ON p.snapshot_id = s.id
               GROUP BY s.id
               ORDER BY s.as_of_date DESC, a.broker"""
        )
        snapshots = [
            dict(zip((item[0] for item in cursor.description or []), row, strict=True))
            for row in cursor.fetchall()
        ]
    return summary, holdings, limit_rows, snapshots


def format_eur(value: object) -> str:
    """Format an optional numeric value as euros."""
    if not isinstance(value, (float, int)):
        return "—"
    return f"€{value:,.2f}"


def main() -> None:
    """Render the portfolio dashboard."""
    st.markdown(
        """<style>
        .stApp { background: #f5f7fb; }
        [data-testid="stMetric"] { background: white; border: 1px solid #e4e9f1;
            padding: 16px 18px; border-radius: 14px; }
        .hero { padding: 10px 0 2px 0; }
        </style>""",
        unsafe_allow_html=True,
    )
    st.markdown('<div class="hero">', unsafe_allow_html=True)
    st.title("Portfolio Desk")
    st.caption("A local view of your positions, valuations, and price coverage.")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.sidebar:
        st.header("Data source")
        database_text = st.text_input("SQLite database", value=str(DEFAULT_DATABASE))
        st.caption("This dashboard reads the database locally and never uploads it.")
        st.divider()
        st.markdown("**Refresh data first**")
        st.code(
            ".venv/bin/python scripts/import_portfolio.py\n"
            ".venv/bin/python scripts/update_prices.py",
            language="bash",
        )

    database = Path(database_text).expanduser()
    if not database.is_file():
        st.warning(f"Portfolio database not found: `{database}`")
        st.info("Import brokerage statements with `scripts/import_portfolio.py` first.")
        return
    try:
        summary, holdings, alerts, snapshots = load_dashboard_data(database)
    except (sqlite3.Error, RuntimeError) as exc:
        st.error(f"Could not read the portfolio database: {exc}")
        return
    if not snapshots:
        st.info("No snapshots found. Run `scripts/import_portfolio.py` to get started.")
        return

    security_count = len(holdings)
    priced_count_value = summary.get("priced_security_count", 0)
    unpriced_count_value = summary.get("unpriced_security_count", security_count)
    priced_count = (
        int(priced_count_value)
        if isinstance(priced_count_value, (int, float)) else 0
    )
    unpriced_count = (
        int(unpriced_count_value)
        if isinstance(unpriced_count_value, (int, float)) else security_count
    )
    unpriced_count = max(unpriced_count, security_count - priced_count)
    coverage = priced_count / security_count if security_count else 0.0
    coverage_text = f"{priced_count}/{security_count} securities"
    latest_price_date = summary.get("latest_price_date") or "No prices"
    latest_snapshot = summary.get("latest_snapshot_date") or "—"

    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Portfolio value (unpriced = €0)",
        format_eur(summary.get("priced_portfolio_value_eur")),
        help="Unpriced positions are valued at €0; this is partial when coverage is below 100%.",
    )
    metric_columns[1].metric("Price coverage", f"{coverage:.0%}", coverage_text)
    metric_columns[2].metric("Latest daily close", str(latest_price_date))
    metric_columns[3].metric("Latest statement", str(latest_snapshot))
    if unpriced_count:
        st.warning(
            f"{unpriced_count} holding(s) are missing a confirmed price. "
            "They count as €0 toward recommendations, and weights are partial; "
            "prices are delayed daily closes, not live quotes."
        )
        if unpriced_count / security_count < 0.02:
            st.info(
                f"Unpriced share is {100.0 * unpriced_count / security_count:.2f}% "
                "(<2%); recommendation calculations proceed with these holdings valued at €0."
            )

    overview_tab, holdings_tab, limits_tab, snapshots_tab = st.tabs(
        ["Overview", "Holdings", "Limits & review", "Snapshots"]
    )
    with overview_tab:
        left, right = st.columns([1.5, 1])
        with left:
            st.subheader("Largest priced positions")
            priced_holdings = [
                row for row in holdings
                if isinstance(row.get("position_value_eur"), (int, float))
            ][:12]
            if priced_holdings:
                chart_rows = [
                    {
                        "Security": str(row["symbol"]),
                        "EUR value": float(row["position_value_eur"] or 0),
                    }
                    for row in reversed(priced_holdings)
                ]
                st.bar_chart(pd.DataFrame(chart_rows).set_index("Security"), horizontal=True)
            else:
                st.info("No matched prices yet. Run the price updater to populate this chart.")
        with right:
            st.subheader("Portfolio pulse")
            st.metric("Priced securities", f"{priced_count} / {security_count}")
            st.metric("Priced positions", format_eur(summary.get("priced_positions_eur")))
            st.metric("Cash in EUR", format_eur(summary.get("cash_value_eur")))
            st.progress(coverage, text="Daily price coverage")
            st.caption("Valuation dates are shown in the Holdings tab.")

        st.subheader("Holdings needing a price")
        missing = [row for row in holdings if row.get("price_date") is None]
        if missing:
            st.dataframe(
                pd.DataFrame([
                    {"Symbol": row["symbol"], "Security ID": row["security_id"],
                     "Description": row["description"], "Broker": row["brokers"]}
                    for row in missing
                ]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.success("Every current holding has a matched price.")

    with holdings_tab:
        st.subheader("Current holdings")
        search = st.text_input("Search symbol, identifier, or description")
        broker_options = sorted({str(row["brokers"] or "") for row in holdings})
        selected_broker = st.selectbox("Broker", ["All brokers", *broker_options])
        filtered = [
            row for row in holdings
            if (selected_broker == "All brokers" or selected_broker in str(row["brokers"]))
            and search.casefold() in " ".join(
                str(row.get(field) or "")
                for field in ("symbol", "security_id", "description")
            ).casefold()
        ]
        display_rows = [
            {
                "Symbol": row["symbol"],
                "Description": row["description"],
                "Quantity": row["quantity"],
                "Statement CCY": row["statement_currencies"],
                "Price": row["original_price"],
                "Price CCY": row["original_currency"],
                "Price date": row["price_date"],
                "FX date": row["fx_date"],
                "EUR / unit": row["eur_per_original_unit"],
                "Price EUR": row["price_eur"],
                "Position EUR": row["position_value_eur"],
            }
            for row in filtered
        ]
        st.dataframe(
            pd.DataFrame(display_rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Quantity": st.column_config.NumberColumn(format="%.6g"),
                "Price": st.column_config.NumberColumn(format="%.4f"),
                "EUR / unit": st.column_config.NumberColumn(format="%.6f"),
                "Price EUR": st.column_config.NumberColumn(format="€%.4f"),
                "Position EUR": st.column_config.NumberColumn(format="€%.2f"),
            },
        )
        st.caption(f"Showing {len(filtered)} of {security_count} current securities.")

    with limits_tab:
        st.subheader("Rule-based review flags")
        st.caption(
            "These are configurable concentration thresholds, not investment advice. "
            "Unpriced holdings count as €0; recommendation alerts are suppressed "
            "when 2% or more of current securities are unpriced."
        )
        total_count = security_count
        unmapped_pct = 100.0 * unpriced_count / total_count if total_count else 100.0
        if unpriced_count and unmapped_pct >= 2.0:
            st.info(
                f"{unpriced_count} of {total_count} securities ({unmapped_pct:.2f}%) "
                "are unpriced. Recommendations require less than 2%."
            )
        elif alerts:
            st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)
        else:
            st.success("No configured position limits are currently breached.")

        st.subheader("Configured security limits")
        configured = [
            {
                "Symbol": row["symbol"],
                "Security ID": row["security_id"],
                "Max portfolio %": row["max_portfolio_pct"],
                "Notes": row["notes"],
            }
            for row in holdings if row.get("max_portfolio_pct") is not None
        ]
        if configured:
            st.dataframe(pd.DataFrame(configured), width="stretch", hide_index=True)
        else:
            st.write("No security-specific limits configured. The default limit is 10%.")

    with snapshots_tab:
        st.subheader("Imported statement history")
        st.dataframe(pd.DataFrame(snapshots), width="stretch", hide_index=True)
        st.caption(
            "Historical statements are preserved; the table shows each imported snapshot by broker and date."
        )

    st.divider()
    st.caption(
        "Market prices are delayed daily closes. Values reflect the most recently imported "
        "positions and stored prices and are not real-time valuations or recommendations."
    )


if __name__ == "__main__":
    main()
