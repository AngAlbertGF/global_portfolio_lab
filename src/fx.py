"""Exchange-rate symbols, direction verification, alignment and conversion.

Quote convention used throughout
--------------------------------
A stored series (base_currency=F, quote_currency=B) holds ``rate`` = units of B
per 1 unit of F.  Yahoo's six-letter symbol ``FFFBBB=X`` is *expected* to be
quoted that way (``USDMXN=X`` ~ 18.7 MXN per USD), but the expectation is
**verified**, not assumed: the inverse symbol ``BBBFFF=X`` is downloaded for a
recent window and the product of the two must be ~1 on common dates.

Conversion (price levels, *before* returns are computed)::

    P_base(t) = P_local(t) / minor_unit_divisor * FX_{local->base}(t)

so base-currency simple returns automatically include the cross term:
1 + r_base = (1 + r_local)(1 + r_fx).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .i18n import t
from .validation import major_currency

logger = logging.getLogger("gpl.fx")

DIRECTION_TOLERANCE = 0.02  # |median(direct * inverse) - 1| must be below 2 %


def fx_symbol(from_ccy: str, to_ccy: str) -> str:
    return f"{from_ccy}{to_ccy}=X"


@dataclass
class DirectionCheck:
    verified: bool
    detail: str
    median_product: float | None = None
    n_common: int = 0


def verify_direction(direct: pd.Series, inverse: pd.Series, from_ccy: str, to_ccy: str) -> DirectionCheck:
    """Check that `direct` is quoted as to_ccy per from_ccy using its inverse series."""
    d, i = direct.dropna(), inverse.dropna()
    common = d.index.intersection(i.index)
    if len(common) < 3:
        return DirectionCheck(False, f"Inverse {fx_symbol(to_ccy, from_ccy)} had too few common dates "
                                     f"({len(common)}); direction NOT verified (assumed {to_ccy} per {from_ccy}).",
                              None, len(common))
    prod = float(np.median(d.loc[common].values * i.loc[common].values))
    ok = abs(prod - 1.0) < DIRECTION_TOLERANCE
    detail = (f"{fx_symbol(from_ccy, to_ccy)} x {fx_symbol(to_ccy, from_ccy)} median product = {prod:.5f} on "
              f"{len(common)} dates -> {'VERIFIED' if ok else 'FAILED'}: rate = {to_ccy} per 1 {from_ccy}.")
    return DirectionCheck(ok, detail, prod, len(common))


@dataclass
class ConversionReport:
    ticker: str
    trading_currency: str
    major_currency: str
    unit_divisor: float
    fx_pair: str
    fx_direction_verified: bool | None
    n_local: int
    n_converted: int
    n_fx_same_day: int
    n_fx_carried: int
    n_dropped_no_fx: int
    max_fx_staleness_days: int
    notes: list[str] = field(default_factory=list)


def convert_to_base(prices_local: pd.Series, trading_currency: str, base_currency: str,
                    fx: pd.Series | None, max_staleness_days: int = 3,
                    direction_verified: bool | None = None, ticker: str = "") -> tuple[pd.Series, ConversionReport]:
    """Convert a local-currency price series to the base currency.

    For each stock observation date d the FX rate observed on d is used; if
    none exists (FX holiday / asynchronous calendars), the most recent rate
    observed at most ``max_staleness_days`` calendar days earlier is used and
    counted as *carried*.  Observations with no admissible FX rate are
    dropped -- stock prices are never invented.
    """
    major, divisor = major_currency(trading_currency)
    s = prices_local.dropna().astype(float) / divisor
    s.index = pd.DatetimeIndex(s.index)
    notes: list[str] = []
    if divisor != 1.0:
        notes.append(t("Prices quoted in {ccy}; divided by {divisor} to obtain {major}.", ccy=trading_currency,
                       divisor=f"{divisor:g}", major=major))
    if major == base_currency:
        rep = ConversionReport(ticker, trading_currency, major, divisor, "none (same currency)", None, len(s), len(s),
                               len(s), 0, 0, 0, notes)
        return s, rep
    pair = f"{major}{base_currency}"
    if fx is None or fx.dropna().empty:
        notes.append(t("No FX series {pair} available; security cannot be converted.", pair=pair))
        return pd.Series(dtype=float), ConversionReport(ticker, trading_currency, major, divisor, pair,
                                                        direction_verified, len(s), 0, 0, 0, len(s), 0, notes)
    f = fx.dropna().sort_index()
    f.index = pd.DatetimeIndex(f.index)
    left = pd.DataFrame({"date": s.index, "price": s.values}).sort_values("date")
    right = pd.DataFrame({"fx_date": f.index, "rate": f.values}).sort_values("fx_date")
    left["date"] = left["date"].astype("datetime64[ns]")
    right["fx_date"] = right["fx_date"].astype("datetime64[ns]")
    merged = pd.merge_asof(left, right, left_on="date", right_on="fx_date", direction="backward",
                           tolerance=pd.Timedelta(days=max_staleness_days))
    ok = merged["rate"].notna()
    same = ok & (merged["date"] == merged["fx_date"])
    stale_days = (merged.loc[ok, "date"] - merged.loc[ok, "fx_date"]).dt.days
    out = pd.Series((merged.loc[ok, "price"] * merged.loc[ok, "rate"]).values,
                    index=pd.DatetimeIndex(merged.loc[ok, "date"]), name=ticker)
    n_drop = int((~ok).sum())
    if n_drop:
        notes.append(t("{n} observations dropped: no {pair} rate within {days} days.", n=n_drop, pair=pair,
                       days=max_staleness_days))
    rep = ConversionReport(ticker, trading_currency, major, divisor, pair, direction_verified, len(s), int(ok.sum()),
                           int(same.sum()), int(ok.sum() - same.sum()), n_drop,
                           int(stale_days.max()) if len(stale_days) else 0, notes)
    return out, rep


def conversion_detail(prices_local: pd.Series, trading_currency: str, base_currency: str,
                      fx: pd.Series | None, max_staleness_days: int = 3) -> pd.DataFrame:
    """Row-by-row record of every conversion (same rule as ``convert_to_base``):

    date | price_local | divisor | price_major | fx_date | fx_rate | price_base | carried_days
    ``fx_date`` is the date of the rate actually used (the same day, or up to ``max_staleness_days`` earlier).
    Rows without an admissible rate have NaN in fx/price_base (they are dropped by the analysis).
    """
    major, divisor = major_currency(trading_currency)
    s = prices_local.dropna().astype(float)
    s.index = pd.DatetimeIndex(s.index)
    left = pd.DataFrame({"date": s.index.astype("datetime64[ns]"), "price_local": s.values})
    left["divisor"] = divisor
    left["price_major"] = left["price_local"] / divisor
    if major == base_currency:
        left["fx_date"] = left["date"]
        left["fx_rate"] = 1.0
    elif fx is None or fx.dropna().empty:
        left["fx_date"] = pd.NaT
        left["fx_rate"] = np.nan
    else:
        f = fx.dropna().sort_index()
        right = pd.DataFrame({"fx_date": pd.DatetimeIndex(f.index).astype("datetime64[ns]"), "fx_rate": f.values})
        left = pd.merge_asof(left.sort_values("date"), right.sort_values("fx_date"), left_on="date",
                             right_on="fx_date", direction="backward",
                             tolerance=pd.Timedelta(days=max_staleness_days))
    left["price_base"] = left["price_major"] * left["fx_rate"]
    left["carried_days"] = (left["date"] - left["fx_date"]).dt.days
    return left.set_index("date")


def triangulate(usd_to_base: pd.Series, usd_to_foreign: pd.Series) -> pd.Series:
    """foreign->base = (base per USD) / (foreign per USD), on common dates only."""
    common = usd_to_base.dropna().index.intersection(usd_to_foreign.dropna().index)
    return (usd_to_base.loc[common] / usd_to_foreign.loc[common]).rename("triangulated")


def stale_fx_flags(fx: pd.Series, max_gap_days: int = 5, as_of: date | None = None) -> list[str]:
    """Human-readable flags for long gaps and a stale last observation."""
    flags: list[str] = []
    s = fx.dropna().sort_index()
    if s.empty:
        return [t("No observations.")]
    gaps = pd.Series(s.index[1:] - s.index[:-1], index=s.index[1:]).dt.days
    long = gaps[gaps > max_gap_days]
    if len(long):
        flags.append(t("{n} gaps longer than {days} days (largest {largest} days, ending {end}).", n=len(long),
                       days=max_gap_days, largest=int(long.max()), end=long.idxmax().date()))
    as_of = as_of or date.today()
    if (as_of - s.index[-1].date()) > timedelta(days=max_gap_days):
        flags.append(t("Last observation {date} is more than {days} days old.", date=s.index[-1].date(),
                       days=max_gap_days))
    return flags
