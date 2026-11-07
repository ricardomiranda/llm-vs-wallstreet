"""Best-effort Yahoo Finance market context and issuer-relevant headlines."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any


YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
USER_AGENT = "Mozilla/5.0 (compatible; portfolio-security-review/1.0)"
STOP_WORDS = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "LTD", "LIMITED",
    "PLC", "HOLDINGS", "GROUP", "CLASS", "THE", "COMPANY", "CO",
    "INTERNATIONAL", "TECHNOLOGIES", "TECHNOLOGY", "INDUSTRIES",
}
ROLLING_PEAK_LOOKBACK_DAYS = 365
ROLLING_PEAK_MINIMUM_COVERAGE_DAYS = 350
ROLLING_PEAK_REVIEW_DRAWDOWN_PERCENT = -20.0


@dataclass(frozen=True)
class NewsItem:
    """Issuer-related news headline and source metadata."""

    title: str
    publisher: str
    url: str
    published_at: str | None
    event_type: str


@dataclass(frozen=True)
class MarketContext:
    """Latest Yahoo chart context and filtered issuer headlines."""

    provider_symbol: str
    issuer_name: str | None
    exchange: str | None
    currency: str | None
    latest_close: float | None
    price_date: str | None
    year_high: float | None
    year_low: float | None
    one_year_return_percent: float | None
    drawdown_from_year_high_percent: float | None
    rolling_peak_price: float | None
    rolling_peak_date: str | None
    rolling_peak_drawdown_percent: float | None
    rolling_peak_coverage_start: str | None
    rolling_peak_coverage_end: str | None
    rolling_peak_review_triggered: bool | None
    benchmark_symbol: str
    benchmark_one_year_return_percent: float | None
    market_cap: float | None
    dividend_yield_percent: float | None
    trailing_annual_dividend_rate: float | None
    news: tuple[NewsItem, ...]
    chart_error: str | None
    news_error: str | None


@dataclass(frozen=True)
class RollingPeakReview:
    """Rolling peak drawdown and whether enough history supports its trigger."""

    peak_price: float | None
    peak_date: str | None
    drawdown_percent: float | None
    coverage_start: str | None
    coverage_end: str | None
    review_triggered: bool | None


def calculate_rolling_peak_review(
    observations: list[tuple[str, float]], today: date
) -> RollingPeakReview:
    """Assess the latest close against the highest close in a covered 12-month window."""
    window_start = (today - timedelta(days=ROLLING_PEAK_LOOKBACK_DAYS)).isoformat()
    window = sorted(
        [
            (observed_date, close)
            for observed_date, close in observations
            if window_start <= observed_date < today.isoformat() and close > 0
        ],
        key=lambda observation: observation[0],
    )
    if not window:
        return RollingPeakReview(None, None, None, None, None, None)

    latest_date, latest_close = window[-1]
    peak_date, peak_price = max(window, key=lambda observation: observation[1])
    drawdown = 100.0 * (latest_close / peak_price - 1.0)
    coverage_start = window[0][0]
    coverage_end = latest_date
    coverage_days = (
        date.fromisoformat(coverage_end)
        - date.fromisoformat(coverage_start)
    ).days
    sufficiently_covered = coverage_days >= ROLLING_PEAK_MINIMUM_COVERAGE_DAYS
    triggered = (
        drawdown <= ROLLING_PEAK_REVIEW_DRAWDOWN_PERCENT + 1e-9
        if sufficiently_covered else None
    )
    return RollingPeakReview(
        peak_price,
        peak_date,
        drawdown,
        coverage_start,
        coverage_end,
        triggered,
    )


def _get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload: object = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected response format")
    return payload


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _date_from_timestamp(value: object) -> str | None:
    timestamp = _number(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def _parse_published_date(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return _date_from_timestamp(value)
    if isinstance(value, str):
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _headline_is_relevant(
    title: str, symbol: str, description: str, issuer_name: str | None
) -> bool:
    normalized_title = " ".join(re.findall(r"[A-Z0-9]+", title.upper()))
    identifiers = {token for token in re.findall(r"[A-Z0-9]+", symbol.upper()) if len(token) > 2}
    company_terms = {
        token for token in re.findall(r"[A-Z0-9]+", description.upper())
        if len(token) > 3 and token not in STOP_WORDS
    }
    if issuer_name:
        company_terms.update(
            token for token in re.findall(r"[A-Z0-9]+", issuer_name.upper())
            if len(token) > 3 and token not in STOP_WORDS
        )
    return any(token in normalized_title for token in identifiers | company_terms)


def _load_chart_context(provider_symbol: str) -> tuple[
    dict[str, object], str | None
]:
    today = datetime.now(timezone.utc).date()
    period_start = today - timedelta(days=ROLLING_PEAK_LOOKBACK_DAYS + 5)
    parameters = urllib.parse.urlencode(
        {
            "period1": int(datetime.combine(
                period_start, datetime.min.time(), timezone.utc
            ).timestamp()),
            "period2": int(datetime.combine(
                today, datetime.min.time(), timezone.utc
            ).timestamp()),
            "interval": "1d",
        }
    )
    url = f"{YAHOO_CHART_URL}/{urllib.parse.quote(provider_symbol, safe='')}?{parameters}"
    payload = _get_json(url)
    chart = payload.get("chart")
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise RuntimeError("No chart data returned")
    result = results[0]
    meta = result.get("meta")
    metadata = meta if isinstance(meta, dict) else {}
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    quote_groups = indicators.get("quote") if isinstance(indicators, dict) else None
    quotes = quote_groups[0] if isinstance(quote_groups, list) and quote_groups else {}
    closes = quotes.get("close") if isinstance(quotes, dict) else None
    observations: list[tuple[str, float]] = []
    if isinstance(timestamps, list) and isinstance(closes, list):
        for timestamp, close in zip(timestamps, closes, strict=False):
            parsed_date = _date_from_timestamp(timestamp)
            parsed_close = _number(close)
            if (
                parsed_date is not None
                and parsed_date < today.isoformat()
                and parsed_close is not None
                and parsed_close > 0
            ):
                observations.append((parsed_date, parsed_close))
    observations.sort(key=lambda observation: observation[0])
    prices = [observation[1] for observation in observations]
    one_year_start_date = (today - timedelta(days=365)).isoformat()
    one_year_observations = [
        observation for observation in observations
        if observation[0] >= one_year_start_date
    ]
    latest_close = prices[-1] if prices else _number(metadata.get("regularMarketPrice"))
    year_high = max(prices) if prices else _number(metadata.get("fiftyTwoWeekHigh"))
    year_low = min(prices) if prices else _number(metadata.get("fiftyTwoWeekLow"))
    drawdown = (
        100.0 * (latest_close / year_high - 1.0)
        if latest_close is not None and year_high is not None and year_high > 0
        else None
    )
    one_year_return = (
        100.0 * (one_year_observations[-1][1] / one_year_observations[0][1] - 1.0)
        if len(one_year_observations) >= 2 and one_year_observations[0][1] > 0
        else None
    )
    rolling_peak = calculate_rolling_peak_review(observations, today)
    dividend_yield = _number(metadata.get("dividendYield"))
    if dividend_yield is not None:
        dividend_yield *= 100.0
    market_data: dict[str, object] = {
        "issuer_name": metadata.get("longName") or metadata.get("shortName"),
        "exchange": metadata.get("fullExchangeName") or metadata.get("exchangeName"),
        "currency": metadata.get("currency"),
        "latest_close": latest_close,
        "price_date": observations[-1][0] if observations else None,
        "year_high": year_high,
        "year_low": year_low,
        "one_year_return_percent": one_year_return,
        "drawdown_from_year_high_percent": drawdown,
        "rolling_peak_price": rolling_peak.peak_price,
        "rolling_peak_date": rolling_peak.peak_date,
        "rolling_peak_drawdown_percent": rolling_peak.drawdown_percent,
        "rolling_peak_coverage_start": rolling_peak.coverage_start,
        "rolling_peak_coverage_end": rolling_peak.coverage_end,
        "rolling_peak_review_triggered": rolling_peak.review_triggered,
        "market_cap": _number(metadata.get("marketCap")),
        "dividend_yield_percent": dividend_yield,
        "trailing_annual_dividend_rate": _number(
            metadata.get("trailingAnnualDividendRate")
        ),
    }
    return market_data, None


def _fetch_news(
    symbol: str,
    description: str,
    provider_symbol: str,
    issuer_name: str | None,
) -> tuple[tuple[NewsItem, ...], str | None]:
    search_terms = list(dict.fromkeys(
        (provider_symbol, symbol, issuer_name or "", description)
    ))
    headlines: dict[str, NewsItem] = {}
    minimum_date = (datetime.now(timezone.utc).date() - timedelta(days=120)).isoformat()
    try:
        for term in search_terms:
            query = urllib.parse.urlencode(
                {"q": term, "quotesCount": 0, "newsCount": 12}
            )
            payload = _get_json(f"{YAHOO_SEARCH_URL}?{query}")
            news_rows = payload.get("news")
            if not isinstance(news_rows, list):
                continue
            for row in news_rows:
                if not isinstance(row, dict):
                    continue
                title = row.get("title")
                if not isinstance(title, str) or not _headline_is_relevant(
                    title, symbol, description, issuer_name
                ):
                    continue
                link = row.get("link")
                if not isinstance(link, str) or not link.startswith("https://"):
                    canonical = row.get("canonicalUrl")
                    link = canonical.get("url") if isinstance(canonical, dict) else None
                if not isinstance(link, str) or not link.startswith("https://"):
                    continue
                publisher = row.get("publisher")
                published = _parse_published_date(
                    row.get("providerPublishTime") or row.get("publishedAt")
                )
                if published is not None and published < minimum_date:
                    continue
                title_lower = title.casefold()
                event_type = (
                    "Merger / acquisition"
                    if any(term in title_lower for term in (
                        "merger", "acquisition", "acquire", "takeover", "buyout", "deal"
                    ))
                    else "Earnings / outlook"
                    if any(term in title_lower for term in (
                        "earnings", "revenue", "guidance", "forecast", "outlook", "results"
                    ))
                    else "Regulatory / legal"
                    if any(term in title_lower for term in (
                        "regulator", "regulatory", "lawsuit", "sec probe", "antitrust",
                        "investigation", "approval", "fda", "court"
                    ))
                    else "Dividend"
                    if "dividend" in title_lower
                    else "Company news"
                )
                headlines[link] = NewsItem(
                    title=title,
                    publisher=publisher if isinstance(publisher, str) else "Yahoo Finance",
                    url=link,
                    published_at=published,
                    event_type=event_type,
                )
        ordered = sorted(
            headlines.values(),
            key=lambda item: item.published_at or "",
            reverse=True,
        )
        return tuple(ordered[:8]), None
    except RuntimeError as exc:
        return tuple(headlines.values()), str(exc)


def fetch_market_context(
    symbol: str, description: str, provider_symbol: str
) -> MarketContext:
    """Fetch one-year price context and recent issuer-relevant headlines."""
    market_data: dict[str, object] = {}
    chart_error: str | None = None
    try:
        market_data, chart_error = _load_chart_context(provider_symbol)
    except RuntimeError as exc:
        chart_error = str(exc)
    issuer_name_value = market_data.get("issuer_name")
    issuer_name = issuer_name_value if isinstance(issuer_name_value, str) else None
    news, news_error = _fetch_news(
        symbol, description, provider_symbol, issuer_name
    )
    benchmark_return: float | None = None
    if provider_symbol.upper() != "SPY":
        try:
            benchmark, _ = _load_chart_context("SPY")
            benchmark_return = _number(benchmark.get("one_year_return_percent"))
        except RuntimeError:
            benchmark_return = None
    exchange = market_data.get("exchange")
    currency = market_data.get("currency")
    price_date = market_data.get("price_date")
    rolling_peak_date = market_data.get("rolling_peak_date")
    rolling_peak_coverage_start = market_data.get("rolling_peak_coverage_start")
    rolling_peak_coverage_end = market_data.get("rolling_peak_coverage_end")
    rolling_peak_review_triggered = market_data.get(
        "rolling_peak_review_triggered"
    )
    return MarketContext(
        provider_symbol=provider_symbol,
        issuer_name=issuer_name,
        exchange=exchange if isinstance(exchange, str) else None,
        currency=currency if isinstance(currency, str) else None,
        latest_close=_number(market_data.get("latest_close")),
        price_date=price_date if isinstance(price_date, str) else None,
        year_high=_number(market_data.get("year_high")),
        year_low=_number(market_data.get("year_low")),
        one_year_return_percent=_number(market_data.get("one_year_return_percent")),
        drawdown_from_year_high_percent=_number(
            market_data.get("drawdown_from_year_high_percent")
        ),
        rolling_peak_price=_number(market_data.get("rolling_peak_price")),
        rolling_peak_date=(rolling_peak_date if isinstance(rolling_peak_date, str) else None),
        rolling_peak_drawdown_percent=_number(
            market_data.get("rolling_peak_drawdown_percent")
        ),
        rolling_peak_coverage_start=(
            rolling_peak_coverage_start
            if isinstance(rolling_peak_coverage_start, str) else None
        ),
        rolling_peak_coverage_end=(
            rolling_peak_coverage_end
            if isinstance(rolling_peak_coverage_end, str) else None
        ),
        rolling_peak_review_triggered=(
            rolling_peak_review_triggered
            if isinstance(rolling_peak_review_triggered, bool)
            else None
        ),
        benchmark_symbol="SPY",
        benchmark_one_year_return_percent=benchmark_return,
        market_cap=_number(market_data.get("market_cap")),
        dividend_yield_percent=_number(market_data.get("dividend_yield_percent")),
        trailing_annual_dividend_rate=_number(
            market_data.get("trailing_annual_dividend_rate")
        ),
        news=news,
        chart_error=chart_error,
        news_error=news_error,
    )
