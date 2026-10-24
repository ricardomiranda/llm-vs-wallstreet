"""Local Streamlit dashboard for exploring portfolio positions and limits."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import TypeAlias
from urllib.parse import quote

import pandas as pd
import streamlit as st

from import_portfolio import DEFAULT_DATABASE
from review_losses import (
    DEFAULT_LOSS_THRESHOLD_PERCENT,
    LossReview,
    load_loss_reviews,
)
from security_research import MarketContext, fetch_market_context
from update_prices import PRICE_SCHEMA


Row: TypeAlias = dict[str, str | int | float | None]
RISK_BUDGET_PERCENT = 15.0
EVALUATION_REMINDER_INTERVAL = timedelta(hours=24)
URGENCY_CELL_STYLES = {
    0: "background-color: #e2f0d9; color: #202124",
    1: "background-color: #fff2cc; color: #202124",
    2: "background-color: #fce4d6; color: #202124",
    3: "background-color: #f4b183; color: #202124",
    4: "background-color: #e06666; color: #ffffff",
    5: "background-color: #c00000; color: #ffffff",
}


def urgency_background_style(value: object) -> str:
    """Return a severity color for one loss-review urgency cell."""
    if isinstance(value, int):
        return URGENCY_CELL_STYLES.get(value, "")
    return ""


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


def load_last_evaluation(database: Path) -> datetime | None:
    """Read the last successful portfolio evaluation time, if recorded."""
    with closing(connect_readonly(database)) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='portfolio_evaluation_status'"
        ).fetchone()
        if table_exists is None:
            return None
        row = connection.execute(
            "SELECT completed_at FROM portfolio_evaluation_status "
            "WHERE singleton_id = 1"
        ).fetchone()
    if row is None or not isinstance(row[0], str):
        return None
    try:
        completed_at = datetime.fromisoformat(row[0])
    except ValueError:
        return None
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    return completed_at.astimezone(timezone.utc)


def evaluation_reminder_due(
    last_evaluation: datetime | None, now: datetime | None = None
) -> bool:
    """Return whether no evaluation exists or its age exceeds 24 hours."""
    if last_evaluation is None:
        return True
    current_time = now or datetime.now(timezone.utc)
    return current_time.astimezone(timezone.utc) - last_evaluation > \
        EVALUATION_REMINDER_INTERVAL


def risk_widget_key(database: Path, security_id: str) -> str:
    """Build a Streamlit state key scoped to the selected database."""
    path_digest = hashlib.sha256(str(database.resolve()).encode()).hexdigest()[:12]
    return f"risk-choice-v2-{path_digest}-{security_id}"


def load_dashboard_data(
    database: Path,
) -> tuple[dict[str, object], list[Row], list[Row], list[Row], list[Row]]:
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

        risk_rows: list[Row] = []
        if "portfolio_risk_classifications" in objects:
            cursor = connection.execute(
                """SELECT security_id, risk_accepted
                   FROM portfolio_risk_classifications
                   WHERE risk_accepted = 1"""
            )
            risk_rows = [
                {"security_id": row[0], "risk_accepted": row[1]}
                for row in cursor.fetchall()
            ]

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
    return summary, holdings, limit_rows, snapshots, risk_rows


def risk_budget_selection(
    database: Path, holdings: list[Row], saved_risk_ids: set[str],
    widget_state: dict[str, bool],
) -> set[str]:
    """Calculate exposure only from saved labels and current explicit opt-ins."""
    selected_ids: set[str] = set(saved_risk_ids)
    for holding in holdings:
        security_id = str(holding["security_id"])
        is_saved = security_id in saved_risk_ids
        is_checked = bool(widget_state.get(security_id, is_saved))
        if is_checked:
            selected_ids.add(security_id)
        else:
            selected_ids.discard(security_id)
    return selected_ids


def load_suggested_risk_candidates(database: Path) -> dict[str, list[str]]:
    """Suggest explicit risk-budget candidates from partial-sell estimates."""
    reasons: dict[str, list[str]] = {}
    with closing(connect_readonly(database)) as connection:
        objects = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view'"
            )
        }
        if "partial_sell_recommendations" in objects:
            recommendations = connection.execute(
                """SELECT security_id, target_weight_pct
                   FROM partial_sell_recommendations"""
            ).fetchall()
            for security_id, target_weight in recommendations:
                reasons.setdefault(security_id, []).append(
                    f"Concentration trim estimate exists (configured cap {target_weight:.1f}%)."
                )
        loss_reviews, _ = load_loss_reviews(
            connection, DEFAULT_LOSS_THRESHOLD_PERCENT
        )
        for review in loss_reviews:
            if review.urgency_score >= 4:
                reasons.setdefault(review.security_id, []).append(
                    f"Severe reported drawdown ({review.loss_percent:.1f}%; "
                    f"loss-review urgency {review.urgency_score}/5)."
                )
    return reasons


def format_eur(value: object) -> str:
    """Format an optional numeric value as euros."""
    if not isinstance(value, (float, int)):
        return "—"
    return f"€{value:,.2f}"


@st.cache_data(ttl=900, show_spinner=False)
def cached_market_context(
    symbol: str, description: str, provider_symbol: str
) -> MarketContext:
    """Cache external market lookups briefly to avoid repeat API requests."""
    return fetch_market_context(symbol, description, provider_symbol)


def render_security_report(
    holding: Row, database: Path, loss_threshold: float
) -> None:
    """Render portfolio facts and best-effort external context for one security."""
    security_id = str(holding["security_id"])
    matching_review: LossReview | None = next(
        (
            review for review in load_loss_reviews_from_database(
                database, loss_threshold
            )
            if review.security_id == security_id
        ),
        None,
    )
    market_context: MarketContext | None = None
    provider_symbol: str | None = None
    with connect_readonly(database) as connection:
        mapping = connection.execute(
            "SELECT provider_symbol FROM security_price_symbols "
            "WHERE security_id = ? AND provider = ?",
            (security_id, "Yahoo Finance"),
        ).fetchone()
        if mapping is not None:
            provider_symbol = str(mapping[0])
    if provider_symbol:
        with st.spinner("Gathering recent market context and headlines…"):
            market_context = cached_market_context(
                str(holding["symbol"]),
                str(holding["description"]),
                provider_symbol,
            )

    position_value = (
        float(position_value_raw)
        if isinstance(
            (position_value_raw := holding.get("position_value_eur")),
            (int, float),
        )
        else None
    )
    portfolio_value: float | None = None
    if position_value is not None:
        with connect_readonly(database) as connection:
            portfolio_row = connection.execute(
                "SELECT priced_portfolio_value_eur FROM current_portfolio_value_eur"
            ).fetchone()
        if (
            portfolio_row is not None
            and isinstance(portfolio_row[0], (int, float))
            and portfolio_row[0] > 0
        ):
            portfolio_value = float(portfolio_row[0])
    position_weight = (
        100.0 * position_value / portfolio_value
        if position_value is not None and portfolio_value is not None
        else None
    )

    st.markdown(f"### {holding['symbol']} — {holding['description']}")
    st.caption(
        f"Security ID: {security_id} · Broker(s): {holding['brokers']} · "
        f"Current quantity: {holding['quantity']}"
    )
    if position_value is not None and position_weight is not None:
        st.caption(
            f"Current position value: {format_eur(position_value)} "
            f"({position_weight:.2f}% of {format_eur(portfolio_value)} priced portfolio value)."
        )
    with connect_readonly(database) as connection:
        risk_table_exists = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name='portfolio_risk_classifications'"""
        ).fetchone() is not None
        saved_risk_row = (
            connection.execute(
                "SELECT risk_accepted FROM portfolio_risk_classifications "
                "WHERE security_id = ?",
                (security_id,),
            ).fetchone()
            if risk_table_exists else None
        )
    saved_as_risky = saved_risk_row is not None and bool(saved_risk_row[0])
    risk_action = "Remove from my 15% uncertain-investment budget" if saved_as_risky \
        else "I consider this an uncertain investment — add to my 15% budget"
    if st.button(risk_action, key=f"detail-risk-toggle-{security_id}"):
        try:
            with sqlite3.connect(database) as writable_connection:
                writable_connection.execute(
                    """CREATE TABLE IF NOT EXISTS portfolio_risk_classifications (
                           security_id TEXT PRIMARY KEY,
                           risk_accepted INTEGER NOT NULL
                               CHECK (risk_accepted IN (0, 1)),
                           updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                       )"""
                )
                if saved_as_risky:
                    writable_connection.execute(
                        "DELETE FROM portfolio_risk_classifications WHERE security_id = ?",
                        (security_id,),
                    )
                else:
                    writable_connection.execute(
                        """INSERT INTO portfolio_risk_classifications(
                               security_id, risk_accepted
                           ) VALUES (?, 1)
                           ON CONFLICT(security_id) DO UPDATE SET
                               risk_accepted = 1,
                               updated_at = CURRENT_TIMESTAMP""",
                        (security_id,),
                    )
            st.rerun()
        except sqlite3.Error as exc:
            st.error(f"Could not update the risk-budget selection: {exc}")
    st.caption(
        "This is your explicit uncertainty classification. A loss score or report "
        "suggestion does not add a security automatically."
    )
    if matching_review is not None:
        st.metric(
            "Loss urgency (0–5)",
            f"{matching_review.urgency_score}/5",
            f"{matching_review.loss_percent:.2f}% unrealized P/L "
            f"({matching_review.currency})",
        )
        st.caption(
            "This score reflects reported loss severity only. It does not assess "
            "business quality, dividend-adjusted return, or whether you should sell."
        )
        st.write(
            f"Broker-reported cost basis: {matching_review.cost_basis:,.2f} "
            f"{matching_review.currency}; unrealized P/L: "
            f"{matching_review.unrealized_pl:,.2f} {matching_review.currency}. "
            f"Statement date: {matching_review.statement_date}."
        )
        st.caption(
            f"First observed {matching_review.days_since_first_seen} days before this "
            "statement; that is not necessarily the purchase date."
        )
    else:
        st.info(
            "No usable cost-basis/unrealized-P&L record was available in the latest "
            "statement for this security, so the loss score is not assessed."
        )

    if market_context is None:
        st.info(
            "No confirmed Yahoo Finance mapping is stored for this security; "
            "external market context was not fetched."
        )
        return

    st.markdown("#### Situation assessment")
    assessment_lines: list[str] = []
    if (
        market_context.one_year_return_percent is not None
        and market_context.benchmark_one_year_return_percent is not None
    ):
        relative_return = (
            market_context.one_year_return_percent
            - market_context.benchmark_one_year_return_percent
        )
        direction = "underperformed" if relative_return < 0 else "outperformed"
        assessment_lines.append(
            f"- **Market performance:** {holding['symbol']} had an approximate "
            f"one-year price return of {market_context.one_year_return_percent:+.1f}% "
            f"versus {market_context.benchmark_symbol} at "
            f"{market_context.benchmark_one_year_return_percent:+.1f}%—"
            f"{direction} by {abs(relative_return):.1f} percentage points. "
            "These are price-only returns and exclude dividends."
        )
    if matching_review is not None:
        assessment_lines.append(
            f"- **Position result:** the latest broker statement reports "
            f"{matching_review.loss_percent:.1f}% unrealized P/L against "
            f"{matching_review.cost_basis:,.2f} {matching_review.currency} cost "
            f"basis (urgency {matching_review.urgency_score}/5). Broker P/L may "
            "not include distributions."
        )
    if market_context.drawdown_from_year_high_percent is not None:
        assessment_lines.append(
            f"- **Trading context:** the latest close is "
            f"{abs(market_context.drawdown_from_year_high_percent):.1f}% "
            "below the highest close in the fetched one-year window. This is a "
            "price-range statistic, not a valuation measure."
        )
    if market_context.dividend_yield_percent is not None:
        assessment_lines.append(
            f"- **Income context:** provider-reported dividend yield is "
            f"{market_context.dividend_yield_percent:.2f}%; verify the current "
            "declared dividend, payout coverage, debt, and payment history."
        )
    else:
        assessment_lines.append(
            "- **Income context:** no provider dividend-yield estimate was returned. "
            "Confirm distributions from company records if this is an income holding."
        )
    event_types = sorted({item.event_type for item in market_context.news})
    if event_types:
        assessment_lines.append(
            "- **Recent headline categories found:** " + ", ".join(event_types) + ". "
            "The headlines below are search results, not verification that a material "
            "event occurred."
        )
    else:
        assessment_lines.append(
            "- **Recent news:** no issuer-matched headlines were returned; this does "
            "not establish that there are no material developments."
        )
    st.markdown("\n".join(assessment_lines))
    st.markdown(
        "**Review questions:** Has the original investment thesis changed? Are any "
        "earnings, regulatory, competitive, or M&A developments material to future "
        "cash flows? For dividend holdings, is the distribution supported by cash "
        "flow and balance-sheet capacity? Your usual one-year horizon is a preference, "
        "not proof that a loss will recover."
    )

    st.markdown("#### Market context (Yahoo Finance)")
    market_columns = st.columns(4)
    market_columns[0].metric(
        "Latest close",
        f"{market_context.latest_close:,.4f} {market_context.currency}"
        if market_context.latest_close is not None and market_context.currency
        else "Unavailable",
        help=f"Price date: {market_context.price_date or 'unavailable'}; delayed daily data, not live.",
    )
    market_columns[1].metric(
        "52-week range",
        f"{market_context.year_low:,.2f}–{market_context.year_high:,.2f} "
        f"{market_context.currency}"
        if market_context.year_low is not None
        and market_context.year_high is not None
        and market_context.currency
        else "Unavailable",
    )
    market_columns[2].metric(
        "From 52-week high",
        f"{market_context.drawdown_from_year_high_percent:.1f}%"
        if market_context.drawdown_from_year_high_percent is not None else "Unavailable",
    )
    market_columns[3].metric(
        "Provider dividend yield",
        f"{market_context.dividend_yield_percent:.2f}%"
        if market_context.dividend_yield_percent is not None else "Unavailable",
        help="Provider trailing estimate, not a promise or forecast of future dividends.",
    )
    comparison_columns = st.columns(2)
    comparison_columns[0].metric(
        "Approx. 1-year price return",
        f"{market_context.one_year_return_percent:+.2f}%"
        if market_context.one_year_return_percent is not None else "Unavailable",
        help="Price-only return from the first available close around one year ago; excludes dividends.",
    )
    comparison_columns[1].metric(
        f"{market_context.benchmark_symbol} price return",
        f"{market_context.benchmark_one_year_return_percent:+.2f}%"
        if market_context.benchmark_one_year_return_percent is not None else "Unavailable",
        help="Broad-market comparison, price return only; not matched by region or sector.",
    )
    if (
        market_context.one_year_return_percent is not None
        and market_context.benchmark_one_year_return_percent is not None
    ):
        relative_return = (
            market_context.one_year_return_percent
            - market_context.benchmark_one_year_return_percent
        )
        st.caption(
            f"Relative price return versus {market_context.benchmark_symbol}: "
            f"{relative_return:+.2f} percentage points. This comparison does not "
            "explain the cause of underperformance."
        )
    if market_context.chart_error:
        st.caption(f"Price-context lookup issue: {market_context.chart_error}")
    if market_context.market_cap is not None:
        st.caption(f"Provider market capitalization: {market_context.market_cap:,.0f} {market_context.currency or ''}")
    if market_context.trailing_annual_dividend_rate is not None:
        st.caption(
            "Provider trailing annual dividend rate: "
            f"{market_context.trailing_annual_dividend_rate:,.4f} "
            f"{market_context.currency or ''}; past dividends can change or stop."
        )

    st.markdown("#### Recent issuer-related headlines")
    if market_context.news:
        for item in market_context.news:
            published = item.published_at or "Date unavailable"
            st.markdown(
                f"- **{item.event_type} · {published} · {item.publisher}:** "
                f"[{item.title}]({item.url})"
            )
    else:
        st.info("No issuer-matched recent headlines were returned by Yahoo Finance.")
    if market_context.news_error:
        st.caption(f"Headline lookup issue: {market_context.news_error}")
    if market_context.news:
        st.caption(
            "Use the risk-budget checklist below to classify this security if you "
            "consider it uncertain. Reports and suggested actions never add holdings "
            "to your risk budget automatically."
        )
    st.caption(
        "Recent-news search does not guarantee coverage of earnings, M&A, regulatory "
        "actions, lawsuits, or other material events. Headline classification is "
        "keyword-based; verify company announcements and filings before relying on it."
    )


def load_loss_reviews_from_database(
    database: Path, threshold_percent: float
) -> list[LossReview]:
    """Load current loss-review rows using the shared report calculation."""
    with connect_readonly(database) as connection:
        reviews, _ = load_loss_reviews(connection, threshold_percent)
    return list(reviews)


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
    active_database = str(database.resolve())
    previous_database = st.session_state.get("active-dashboard-database")
    if previous_database != active_database:
        for state_key in list(st.session_state):
            if isinstance(state_key, str) and state_key.startswith("risk-choice-v2-"):
                del st.session_state[state_key]
        st.session_state["active-dashboard-database"] = active_database
    try:
        summary, holdings, alerts, snapshots, risk_rows = load_dashboard_data(database)
    except (sqlite3.Error, RuntimeError) as exc:
        st.error(f"Could not read the portfolio database: {exc}")
        return
    if not snapshots:
        st.info("No snapshots found. Run `scripts/import_portfolio.py` to get started.")
        return

    last_evaluation = load_last_evaluation(database)
    if evaluation_reminder_due(last_evaluation):
        if last_evaluation is None:
            reminder_detail = "No completed portfolio evaluation is recorded yet."
        else:
            reminder_detail = (
                "Your last portfolio evaluation was more than 24 hours ago "
                f"({last_evaluation.astimezone().strftime('%Y-%m-%d %H:%M %Z')})."
            )
        st.warning(
            f"{reminder_detail} "
            "Run `/evaluate-portfolio` to refresh your review and recommendations."
        )

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
                        "Security": str(row["description"]),
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
        st.subheader("Risk budget")
        st.caption(
            "Your 15% tolerance is an exposure budget in holdings you consider "
            "uncertain; it is not a loss limit. Mark the positions you want counted "
            "as risky; loss severity alone does not classify them."
        )
        risk_by_id = {
            str(row["security_id"]): bool(row["risk_accepted"])
            for row in risk_rows
        }
        risk_options = {
            f"{row['symbol']} — {row['description']} ({row['security_id']})":
                str(row["security_id"])
            for row in holdings
        }
        suggested_risk_reasons = load_suggested_risk_candidates(database)
        suggested_ids = set(suggested_risk_reasons)
        proposed_ids = set(risk_by_id)
        suggestions_to_add = suggested_ids - proposed_ids
        risk_controls: dict[str, bool] = {}
        st.info(
            f"Suggested for your review: {len(suggested_ids)} holding(s) based on "
            "an existing concentration trim estimate. A suggested trim is not "
            "automatically an uncertain investment. Add speculative/high-upside "
            "holdings you personally identify, and any holding you keep despite a "
            "strong suggestion to sell."
        )
        if suggested_ids:
            suggestion_rows = [
                {
                    "Symbol": next(
                        str(row["symbol"]) for row in holdings
                        if row["security_id"] == security_id
                    ),
                    "Review reason": "; ".join(reasons),
                }
                for security_id, reasons in suggested_risk_reasons.items()
            ]
            st.dataframe(
                pd.DataFrame(suggestion_rows),
                width="stretch",
                hide_index=True,
            )
        st.caption(
            f"Checking all suggested candidates would add {len(suggestions_to_add)} "
            "holding(s) to your saved classifications. Fine-tune any selection below."
        )
        with st.expander("Select holdings included in the 15% risk budget", expanded=False):
            control_columns = st.columns(3)
            for index, (label, security_id) in enumerate(risk_options.items()):
                suggested = security_id in suggested_ids
                previously_selected = risk_by_id.get(security_id, False)
                widget_key = risk_widget_key(database, security_id)
                reason = "; ".join(suggested_risk_reasons.get(security_id, []))
                checkbox_label = (
                    f"{label} — suggested for review: {reason}"
                    if suggested else label
                )
                control = control_columns[index % len(control_columns)].checkbox(
                    checkbox_label,
                    value=previously_selected,
                    key=widget_key,
                )
                risk_controls[security_id] = control
        selected_risky_ids = risk_budget_selection(
            database, holdings, set(risk_by_id), risk_controls
        )
        if st.button("Save risk classifications", key="save-risk-classifications"):
            try:
                with sqlite3.connect(database) as writable_connection:
                    writable_connection.execute(
                        """CREATE TABLE IF NOT EXISTS portfolio_risk_classifications (
                               security_id TEXT PRIMARY KEY,
                               risk_accepted INTEGER NOT NULL
                                   CHECK (risk_accepted IN (0, 1)),
                               updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                           )"""
                    )
                    writable_connection.executemany(
                        """INSERT INTO portfolio_risk_classifications(
                               security_id, risk_accepted
                           ) VALUES (?, ?)
                           ON CONFLICT(security_id) DO UPDATE SET
                               risk_accepted = excluded.risk_accepted,
                               updated_at = CURRENT_TIMESTAMP""",
                        [
                            (security_id, int(selected))
                            for security_id, selected in risk_controls.items()
                            if selected
                        ],
                    )
                    writable_connection.executemany(
                        "DELETE FROM portfolio_risk_classifications WHERE security_id = ?",
                        [
                            (security_id,)
                            for security_id, selected in risk_controls.items()
                            if not selected
                        ],
                    )
                st.success("Risk classifications saved to the local SQLite database.")
                st.rerun()
            except sqlite3.Error as exc:
                st.error(f"Could not save risk classifications: {exc}")
        elif suggestions_to_add:
            st.caption(
                "Suggested candidates are shown for consideration, not selected. "
                "Tick only the positions you personally regard as uncertain, then "
                "save your classifications."
            )

        risky_value = sum(
            float(row["position_value_eur"])
            for row in holdings
            if row["security_id"] in selected_risky_ids
            and isinstance(row["position_value_eur"], (int, float))
        )
        portfolio_value = summary.get("priced_portfolio_value_eur")
        risky_weight = (
            100.0 * risky_value / float(portfolio_value)
            if isinstance(portfolio_value, (int, float)) and portfolio_value > 0
            else None
        )
        selected_risk_rows = [
            {
                "Symbol": row["symbol"],
                "Description": row["description"],
                "Position (EUR)": row["position_value_eur"],
                "Portfolio share (%)": (
                    100.0 * float(row["position_value_eur"]) / float(portfolio_value)
                    if isinstance(row["position_value_eur"], (int, float))
                    and isinstance(portfolio_value, (int, float))
                    and portfolio_value > 0
                    else None
                ),
            }
            for row in holdings
            if str(row["security_id"]) in selected_risky_ids
        ]
        if selected_risk_rows:
            st.dataframe(
                pd.DataFrame(selected_risk_rows),
                width="stretch",
                hide_index=True,
                column_config={
                    "Position (EUR)": st.column_config.NumberColumn(format="€%.2f"),
                    "Portfolio share (%)": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
        else:
            st.caption("No holdings are currently selected for the risk budget.")
        risk_columns = st.columns(3)
        risk_columns[0].metric("Selected uncertain exposure", format_eur(risky_value))
        risk_columns[1].metric(
            "Share of portfolio",
            f"{risky_weight:.2f}%" if risky_weight is not None else "—",
        )
        risk_columns[2].metric("Exposure budget", f"{RISK_BUDGET_PERCENT:.0f}%")
        if risky_weight is None:
            st.info("Portfolio value is unavailable, so the risk budget cannot be measured.")
        elif risky_weight > RISK_BUDGET_PERCENT:
            st.warning(
                f"Selected uncertain exposure is {risky_weight:.2f}%, over the "
                f"{RISK_BUDGET_PERCENT:.0f}% budget."
            )
        else:
            st.success(
                f"Selected uncertain exposure is {risky_weight:.2f}%, within the "
                f"{RISK_BUDGET_PERCENT:.0f}% budget."
            )
        if unpriced_count:
            st.caption(
                "Unpriced holdings count as €0, so the measured exposure share may be understated."
            )

        st.subheader("Loss review and urgency")
        loss_threshold = st.slider(
            "Loss review threshold (%)",
            min_value=5.0,
            max_value=50.0,
            value=DEFAULT_LOSS_THRESHOLD_PERCENT,
            step=5.0,
            help="A review trigger based on broker-reported unrealized loss and cost basis; not a sell rule.",
        )
        with connect_readonly(database) as connection:
            loss_reviews, unavailable_losses = load_loss_reviews(
                connection, loss_threshold
            )
        st.caption(
            "Urgency score: 0 = below the review threshold; 1 = threshold reached; "
            "each additional 10 percentage points of loss adds one point, capped at 5. "
            "This measures loss severity only—not whether you should sell—and does "
            "not account for dividend income."
        )
        st.caption(
            "A one-year holding period can be your normal preference, not a hard rule. "
            "First-seen snapshot dates are not purchase dates; consider an earlier "
            "review if the investment thesis materially changes."
        )
        if loss_reviews:
            review_count = sum(review.urgency_score > 0 for review in loss_reviews)
            st.warning(
                f"{review_count} holding(s) meet or exceed the loss review trigger. "
                "Review total return (including dividends), the original investment "
                "thesis, and material business changes. Reported P/L may exclude "
                "dividends; first-seen dates are not purchase dates."
            )
            loss_rows = [
                {
                    "Urgency (0–5)": review.urgency_score,
                    "Symbol": review.symbol,
                    "Description": review.description,
                    "Broker": review.broker,
                    "Loss %": review.loss_percent,
                    "Unrealized P/L": review.unrealized_pl,
                    "Cost basis": review.cost_basis,
                    "Currency": review.currency,
                    "Statement date": review.statement_date,
                    "First seen": review.first_seen_date,
                    "Days observed": review.days_since_first_seen,
                }
                for review in sorted(
                    loss_reviews,
                    key=lambda item: (item.urgency_score, item.loss_percent),
                    reverse=True,
                )
            ]
            st.dataframe(
                pd.DataFrame(loss_rows).style.map(
                    urgency_background_style,
                    subset=["Urgency (0–5)"],
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    "Urgency (0–5)": st.column_config.NumberColumn(format="%d/5"),
                    "Loss %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Unrealized P/L": st.column_config.NumberColumn(format="%.2f"),
                    "Cost basis": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        else:
            st.success("No holdings cross the selected loss-review threshold.")
        unavailable_count = sum(unavailable_losses.values())
        if unavailable_count:
            unavailable_summary = ", ".join(
                f"{broker}: {count}"
                for broker, count in sorted(unavailable_losses.items())
            )
            st.info(
                f"Loss review unavailable for {unavailable_count} position(s) "
                f"because cost basis or unrealized P/L is missing ({unavailable_summary})."
            )

        st.subheader("Individual security report")
        report_options = {
            f"{row['symbol']} — {row['description']} ({row['security_id']})": row
            for row in holdings
        }
        selected_report_label = st.selectbox(
            "Choose a security",
            options=["Select a security", *report_options],
            key="individual_security_report",
        )
        if selected_report_label != "Select a security":
            selected_holding = report_options[selected_report_label]
            render_security_report(selected_holding, database, loss_threshold)

        st.subheader("Concentration review")
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
        else:
            with connect_readonly(database) as connection:
                cursor = connection.execute(
                    """SELECT symbol, description, current_quantity,
                              price_date, price_eur, position_value_eur,
                              portfolio_value_eur, current_weight_pct,
                              target_weight_pct, recommended_sell_quantity,
                              recommended_sell_value_eur
                       FROM partial_sell_recommendations
                       ORDER BY current_weight_pct DESC"""
                )
                recommendation_columns = [
                    column[0] for column in cursor.description or []
                ]
                recommendations = [
                    dict(zip(recommendation_columns, row, strict=True))
                    for row in cursor.fetchall()
                ]
            if recommendations:
                st.warning(
                    "Rule-based partial-sale estimates—not personalized investment "
                    "advice or trade instructions. Unpriced holdings are valued at €0."
                )
                st.dataframe(
                    pd.DataFrame(recommendations),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "current_quantity": st.column_config.NumberColumn(
                            "Current quantity", format="%.6g"
                        ),
                        "price_eur": st.column_config.NumberColumn(
                            "Price (EUR)", format="€%.4f"
                        ),
                        "position_value_eur": st.column_config.NumberColumn(
                            "Position value (EUR)", format="€%.2f"
                        ),
                        "portfolio_value_eur": st.column_config.NumberColumn(
                            "Portfolio value (EUR)", format="€%.2f"
                        ),
                        "current_weight_pct": st.column_config.NumberColumn(
                            "Current weight", format="%.2f%%"
                        ),
                        "target_weight_pct": st.column_config.NumberColumn(
                            "Maximum weight", format="%.2f%%"
                        ),
                        "recommended_sell_quantity": st.column_config.NumberColumn(
                            "Estimated quantity to sell", format="%.6g"
                        ),
                        "recommended_sell_value_eur": st.column_config.NumberColumn(
                            "Estimated value to sell (EUR)", format="€%.2f"
                        ),
                    },
                )
            else:
                st.success("No positions currently exceed their configured maximum weights.")

        if alerts:
            st.subheader("Configured position-limit alerts")
            st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)

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
