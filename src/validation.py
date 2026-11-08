"""Portfolio model, input validation and price data-quality checks."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import ALLOCATION_TOLERANCE_PCT, MINOR_CURRENCY_UNITS, MarketConfig
from .i18n import t

TICKER_PATTERN = re.compile(r"^[A-Z0-9\^][A-Z0-9.\-=&^]{0,24}$")


@dataclass
class Holding:
    ticker: str
    market_id: str
    within_pct: float                 # % of its market's allocation
    name: str = ""
    exchange: str = ""
    currency: str = ""
    validation_status: str = "UNVALIDATED"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Portfolio:
    name: str = "My portfolio"
    base_currency: str = "MXN"
    total_capital: float | None = None
    market_allocations: dict[str, float] = field(default_factory=dict)  # % of capital
    holdings: list[Holding] = field(default_factory=list)
    portfolio_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Portfolio":
        holdings = [Holding(**h) for h in data.get("holdings", [])]
        return cls(name=data.get("name", "My portfolio"), base_currency=data.get("base_currency", "MXN"),
                   total_capital=data.get("total_capital"),
                   market_allocations={k: float(v) for k, v in data.get("market_allocations", {}).items()},
                   holdings=holdings, portfolio_id=data.get("portfolio_id"))

    @property
    def active_markets(self) -> list[str]:
        return [m for m, a in self.market_allocations.items() if a > 0]

    @property
    def tickers(self) -> list[str]:
        return [h.ticker for h in self.holdings]


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def normalize_ticker(raw: str) -> str:
    """Strip surrounding whitespace and upper-case. Never maps one symbol to another."""
    return (raw or "").strip().upper()


def check_ticker_syntax(ticker: str) -> str | None:
    if not ticker:
        return t("Ticker is empty.")
    if any(c.isspace() for c in ticker):
        return t("'{ticker}' contains internal whitespace. Enter one exact Yahoo symbol (e.g. WALMEX.MX), not a "
                 "company name.", ticker=ticker)
    if not TICKER_PATTERN.match(ticker):
        return t("'{ticker}' is not a valid Yahoo Finance symbol format.", ticker=ticker)
    return None


def major_currency(currency: str | None) -> tuple[str, float]:
    """Return (major currency, divisor) e.g. 'GBp' -> ('GBP', 100)."""
    if not currency:
        return "", 1.0
    if currency in MINOR_CURRENCY_UNITS:
        return MINOR_CURRENCY_UNITS[currency]
    return currency.upper(), 1.0


def market_consistency_warnings(ticker: str, currency: str | None, market: MarketConfig) -> list[str]:
    warnings: list[str] = []
    suffix = "." + ticker.rsplit(".", 1)[1] if "." in ticker else ""
    if market.ticker_suffixes:
        if suffix not in market.ticker_suffixes:
            warnings.append(t("{ticker}: suffix '{suffix}' is not a {market} convention ({expected}).",
                              ticker=ticker, suffix=suffix or t("none"), market=t(market.name),
                              expected=market.suffix_text()))
    elif suffix and suffix not in (".",):
        warnings.append(t("{ticker}: {market} listings normally have no exchange suffix.", ticker=ticker,
                          market=t(market.name)))
    if currency:
        major, _ = major_currency(currency)
        if major and major != market.currency:
            warnings.append(t("{ticker}: trades in {currency}, but {market} uses {market_ccy}. Conversion will "
                              "use the security's own currency ({major}).", ticker=ticker, currency=currency,
                              market=t(market.name), market_ccy=market.currency, major=major))
    return warnings


def validate_market_allocations(allocations: dict[str, float],
                                tol: float = ALLOCATION_TOLERANCE_PCT) -> ValidationResult:
    errors, warnings = [], []
    for m, a in allocations.items():
        if a is None or not np.isfinite(a):
            errors.append(t("{market}: allocation is not a number.", market=m))
        elif a < 0 or a > 100:
            errors.append(t("{market}: allocation {value}% is outside [0%, 100%].", market=m, value=f"{a:.4f}"))
    total = float(sum(a for a in allocations.values() if a is not None and np.isfinite(a)))
    positive = [m for m, a in allocations.items() if a and a > 0]
    if not positive:
        errors.append(t("At least one market must have a positive allocation."))
    remaining = 100.0 - total
    if abs(remaining) > tol:
        if remaining > 0:
            errors.append(t("Allocations sum to {total}%; {remaining}% of capital is unallocated.",
                            total=f"{total:.4f}", remaining=f"{remaining:.4f}"))
        else:
            errors.append(t("Allocations sum to {total}%; reduce by {excess}%.", total=f"{total:.4f}",
                            excess=f"{-remaining:.4f}"))
    return ValidationResult(not errors, errors, warnings, {"total": total, "remaining": remaining,
                                                           "active_markets": positive})


def validate_holdings(portfolio: Portfolio, long_only: bool = True,
                      tol: float = ALLOCATION_TOLERANCE_PCT) -> ValidationResult:
    errors, warnings = [], []
    alloc = validate_market_allocations(portfolio.market_allocations, tol)
    errors += alloc.errors
    seen: set[str] = set()
    for h in portfolio.holdings:
        if h.ticker in seen:
            errors.append(t("{ticker} is selected more than once. Each listing may appear only once.",
                            ticker=h.ticker))
        seen.add(h.ticker)
        syntax = check_ticker_syntax(h.ticker)
        if syntax:
            errors.append(syntax)
        if h.within_pct is None or not np.isfinite(h.within_pct):
            errors.append(t("{ticker}: within-market weight is not a number.", ticker=h.ticker))
        elif long_only and h.within_pct < 0:
            errors.append(t("{ticker}: negative weight is not allowed in long-only mode.", ticker=h.ticker))
        if h.validation_status in ("INVALID", "NOT_FOUND"):
            errors.append(t("{ticker}: ticker could not be validated ({status}).", ticker=h.ticker,
                            status=h.validation_status))
        if h.market_id not in portfolio.market_allocations or portfolio.market_allocations.get(h.market_id, 0) <= 0:
            errors.append(t("{ticker} belongs to {market}, which has 0% allocation. Remove it or allocate capital.",
                            ticker=h.ticker, market=h.market_id))
    sums: dict[str, float] = {}
    for m in alloc.details["active_markets"]:
        members = [h for h in portfolio.holdings if h.market_id == m]
        if not members:
            errors.append(t("{market} has a {value}% allocation but no securities.", market=m,
                            value=f"{portfolio.market_allocations[m]:.2f}"))
            continue
        s = float(sum(h.within_pct for h in members))
        sums[m] = s
        if abs(s - 100.0) > tol:
            errors.append(t("{market}: within-market weights sum to {value}% (must be 100%).", market=m,
                            value=f"{s:.4f}"))
    if portfolio.total_capital is not None and portfolio.total_capital <= 0:
        errors.append(t("Total capital must be positive (or left empty)."))
    w = global_weights(portfolio) if not errors else pd.Series(dtype=float)
    if not w.empty and abs(w.sum() - 1.0) > 1e-9:
        errors.append(t("Global weights sum to {value}, not 1.", value=f"{w.sum():.10f}"))
    return ValidationResult(not errors, errors, warnings, {"market_sums": sums, "global_weights": w})


def global_weights(portfolio: Portfolio) -> pd.Series:
    """w_i = A_m * a_{i|m}, both converted from percentages to fractions."""
    data = {h.ticker: portfolio.market_allocations.get(h.market_id, 0.0) / 100.0 * h.within_pct / 100.0
            for h in portfolio.holdings}
    return pd.Series(data, dtype=float)


def market_of(portfolio: Portfolio) -> dict[str, str]:
    return {h.ticker: h.market_id for h in portfolio.holdings}


def equal_weight_within_markets(portfolio: Portfolio) -> None:
    for m in portfolio.market_allocations:
        members = [h for h in portfolio.holdings if h.market_id == m]
        for h in members:
            h.within_pct = 100.0 / len(members)


# ---------------------------------------------------------------------------
# Price data quality
# ---------------------------------------------------------------------------
@dataclass
class PriceQualityReport:
    rows_in: int
    rows_valid: int
    dropped_missing_close: int
    dropped_nonpositive: int
    high_below_low: int
    extreme_moves: int
    issues: list[str]


def clean_price_frame(df: pd.DataFrame, extreme_threshold: float = 0.5) -> tuple[pd.DataFrame, PriceQualityReport]:
    """Drop observations that cannot be used (missing/zero/negative adjusted close).

    Rows are never invented.  Suspicious-but-possible values (high<low, >50%
    daily moves) are kept and flagged so the user can inspect them.
    """
    rows_in = len(df)
    issues: list[str] = []
    out = df.copy()
    out["adj_close"] = pd.to_numeric(out["adj_close"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    finite = np.isfinite(out["adj_close"].to_numpy(dtype=float)) & np.isfinite(
        out["close"].to_numpy(dtype=float))
    missing = out["adj_close"].isna() | out["close"].isna() | ~finite
    out = out[~missing]
    nonpos = (out["adj_close"] <= 0) | (out["close"] <= 0)
    out = out[~nonpos]
    hl = 0
    if {"high", "low"} <= set(out.columns):
        hl = int(((out["high"] < out["low"]) & out["high"].notna() & out["low"].notna()).sum())
    moves = out["adj_close"].pct_change().abs()
    extreme = int((moves > extreme_threshold).sum())
    if missing.sum():
        issues.append(t("{n} rows without a close/adjusted close were discarded.", n=int(missing.sum())))
    if nonpos.sum():
        issues.append(t("{n} rows with zero/negative prices were discarded.", n=int(nonpos.sum())))
    if hl:
        issues.append(t("{n} rows have high < low (kept, flagged).", n=hl))
    if extreme:
        issues.append(t("{n} daily moves exceed {threshold} (kept, flagged; check splits/units).", n=extreme,
                        threshold=f"{extreme_threshold:.0%}"))
    return out, PriceQualityReport(rows_in, len(out), int(missing.sum()), int(nonpos.sum()), hl, extreme, issues)
