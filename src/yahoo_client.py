"""Market-data provider layer: Yahoo Finance via yfinance, behind a small interface.

The rest of the application depends only on :class:`PriceProvider`, so tests
use a deterministic fake and another data vendor can be added later.

Provider conventions (yfinance 1.x, verified in development, Oct 2026)
---------------------------------------------------------------------
* ``history(start, end)``: ``start`` inclusive, ``end`` **exclusive**.
* ``actions=True`` returns dividends and splits; ``repair=True`` lets yfinance fix known Yahoo
  adjustment errors.  The application then applies its own checks (src/corporate_actions.py),
  because Yahoo errors remain after that (e.g. 1321.T after its 100:1 split in Oct 2026).
* ``auto_adjust=False`` is passed explicitly so that both ``Close`` (raw) and
  ``Adj Close`` (split- and dividend-adjusted) are returned; recent yfinance
  versions default to ``auto_adjust=True``, which would silently drop raw closes.
* Timestamps are midnight in the *exchange* timezone.  They are converted to
  calendar dates by dropping the timezone (wall-clock date), never by
  converting to UTC, which would shift Asian sessions to the previous day.
* An in-progress session can appear as a row with NaN prices; such rows are
  discarded by data validation, never filled.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import pandas as pd

from .config import PROVIDER_NAME

logger = logging.getLogger("gpl.provider")

COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
              "Volume": "volume"}
ACTION_MAP = {"Dividends": "dividends", "Stock Splits": "splits"}   # corporate actions (kept, not stored as prices)


class ProviderError(Exception):
    """Temporary / infrastructure failure (network, rate limit, 5xx). Retry later."""


class TickerNotFound(Exception):
    """The provider does not recognise the symbol (invalid or delisted without data)."""


class NoDataInRange(Exception):
    """Symbol exists but the provider has no observations in the requested window."""


@dataclass
class SecurityMetadata:
    ticker: str
    name: str | None
    exchange: str | None
    currency: str | None
    timezone: str | None
    quote_type: str | None


class PriceProvider(Protocol):
    name: str

    def fetch_history(self, ticker: str, start: date, end_exclusive: date) -> pd.DataFrame: ...

    def fetch_metadata(self, ticker: str) -> SecurityMetadata: ...


def normalize_history_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Map provider columns to the schema and index by exchange-local calendar date."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=list(COLUMN_MAP.values()))
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):  # yf.download style
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={**COLUMN_MAP, **ACTION_MAP})
    missing = [c for c in ("close", "adj_close") if c not in df.columns]
    if missing:
        raise ProviderError(f"Provider response lacks columns {missing}; adjusted prices unavailable.")
    for c in COLUMN_MAP.values():
        if c not in df.columns:
            df[c] = pd.NA
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)  # keep the exchange wall-clock date
    df.index = idx.normalize()
    df.index.name = "date"
    keep = list(COLUMN_MAP.values()) + [c for c in ACTION_MAP.values() if c in df.columns]
    df = df[keep].apply(pd.to_numeric, errors="coerce")
    return df[~df.index.duplicated(keep="last")].sort_index()


def _classify(exc: Exception) -> Exception:
    name = type(exc).__name__
    text = str(exc)
    if name in ("YFRateLimitError",) or "Too Many Requests" in text or "429" in text:
        return ProviderError(f"Rate limited by provider: {text[:200]}")
    if name in ("YFTickerMissingError", "YFTzMissingError") or "404" in text or "Invalid ISIN" in text \
            or ("possibly delisted" in text and "no timezone" in text):
        return TickerNotFound(text[:200])
    if name == "YFPricesMissingError" or "Data doesn't exist" in text or "no price data found" in text \
            or "No data found" in text:
        return NoDataInRange(text[:200])
    return ProviderError(f"{name}: {text[:200]}")


class YahooProvider:
    """yfinance-backed provider with retry/backoff for temporary failures only."""

    name = PROVIDER_NAME

    def __init__(self, max_retries: int = 3, backoff_seconds: float = 1.5, timeout: int = 20):
        import yfinance as yf  # imported lazily so tests never need network

        self._yf = yf
        try:
            yf.config.debug.hide_exceptions = False  # we need exceptions to classify failures
        except Exception:  # older yfinance
            pass
        self.max_retries = max_retries
        self.backoff = backoff_seconds
        self.timeout = timeout

    def _with_retry(self, fn, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - classified below
                err = _classify(exc)
                if not isinstance(err, ProviderError):
                    raise err from exc
                last = err
                logger.warning("event=provider_retry attempt=%s error=%s", attempt, err)
                if attempt < self.max_retries:
                    time.sleep(self.backoff * 2 ** (attempt - 1))
        raise last  # type: ignore[misc]

    def fetch_history(self, ticker: str, start: date, end_exclusive: date) -> pd.DataFrame:
        def _call() -> pd.DataFrame:
            t = self._yf.Ticker(ticker)
            kw = dict(start=start.isoformat(), end=end_exclusive.isoformat(), interval="1d", auto_adjust=False,
                      actions=True, timeout=self.timeout)
            try:  # yfinance's own repair fixes many bad split/dividend adjustments; it needs extra requests
                return t.history(repair=True, **kw)
            except Exception as exc:  # noqa: BLE001
                if isinstance(_classify(exc), (TickerNotFound, NoDataInRange)):
                    raise
                return t.history(**kw)
        try:
            raw = self._with_retry(_call)
        except NoDataInRange:
            return normalize_history_frame(pd.DataFrame())
        return normalize_history_frame(raw)

    def fetch_metadata(self, ticker: str) -> SecurityMetadata:
        """Currency/exchange/timezone/name, tolerant of Yahoo's throttled quote endpoints.

        Order: price-history metadata (chart endpoint, which keeps working when the crumb-protected
        quote endpoints return 401/429) -> ``fast_info`` -> ``info`` (only if the name is still missing).
        """
        t = self._yf.Ticker(ticker)
        meta: dict[str, Any] = {}
        first_error: Exception | None = None
        try:  # chart endpoint: currency, exchange, timezone, names and instrument type in one call
            t.history(period="5d", interval="1d", auto_adjust=False, actions=False, timeout=self.timeout)
            hm = t.history_metadata or {}
            meta = {"currency": hm.get("currency"), "exchange": hm.get("fullExchangeName") or hm.get("exchangeName"),
                    "timezone": hm.get("exchangeTimezoneName"), "name": hm.get("longName") or hm.get("shortName"),
                    "quote_type": hm.get("instrumentType")}
        except Exception as exc:  # noqa: BLE001
            first_error = exc
            if isinstance(_classify(exc), (TickerNotFound, NoDataInRange)):
                raise TickerNotFound(f"No data found for {ticker}: {str(exc)[:150]}") from exc
        if not meta.get("currency"):
            try:
                fi = t.fast_info
                meta.update({"currency": fi.get("currency"), "exchange": meta.get("exchange") or fi.get("exchange"),
                             "timezone": meta.get("timezone") or fi.get("timezone")})
            except Exception as exc:  # noqa: BLE001
                first_error = first_error or exc
        if not meta.get("currency"):
            err = _classify(first_error) if first_error else TickerNotFound(f"No metadata for {ticker}")
            if isinstance(first_error, KeyError):
                err = TickerNotFound(f"No metadata for {ticker}")
            raise err
        info: dict[str, Any] = {}
        if not meta.get("name"):
            try:
                info = t.info or {}  # single attempt: names are optional and this endpoint is often throttled
            except Exception:  # noqa: BLE001
                info = {}
        return SecurityMetadata(
            ticker=ticker,
            name=meta.get("name") or info.get("longName") or info.get("shortName"),
            exchange=info.get("fullExchangeName") or meta.get("exchange") or info.get("exchange"),
            currency=meta.get("currency"),
            timezone=meta.get("timezone") or info.get("exchangeTimezoneName"),
            quote_type=meta.get("quote_type") or info.get("quoteType"),
        )


# ---------------------------------------------------------------------------
# Session completeness: only completed sessions are stored.
# ---------------------------------------------------------------------------
def last_completed_session_end_exclusive(tz_name: str, close_time: str, now: datetime | None = None,
                                         grace_minutes: int = 45) -> date:
    """Exclusive end date for a download that excludes an unfinished session.

    If the exchange-local clock is past ``close + grace``, today's session is
    complete and the exclusive end is tomorrow; otherwise it is today.
    """
    from zoneinfo import ZoneInfo

    local_now = (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo(tz_name))
    hh, mm = (int(x) for x in close_time.split(":"))
    cutoff = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(minutes=grace_minutes)
    today = local_now.date()
    return today + timedelta(days=1) if local_now >= cutoff else today
