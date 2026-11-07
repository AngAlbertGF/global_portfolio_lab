"""Price normalisation to the base currency, common calendars, returns and annualisation.

Formulas (P = adjusted close in base currency, n periods per year: 252 daily / 52 weekly)
--------
simple return        r_t = P_t / P_{t-1} - 1
log return           g_t = ln(P_t / P_{t-1})
cumulative return    prod(1 + r_t) - 1
annual arith. mean   n * mean(r_t)
annual volatility    sqrt(n) * sd(r_t)   (sample sd, ddof = 1)
CAGR                 (P_end / P_start)^(1/T) - 1, T = actual elapsed days / 365.25

Portfolio returns used for statistics and Markowitz are *constant-weight*
(rebalanced each period): r_p,t = sum_i w_i r_i,t.  This is the convention under
which mu_p = w'mu and sigma_p^2 = w'Sigma w hold exactly in sample.  Buy-and-hold
(drifting weights) is available in the backtesting module.
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from .database import Database
from .fx import ConversionReport, conversion_detail, convert_to_base
from .i18n import t
from .validation import major_currency


def simple_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return (prices / prices.shift(1) - 1.0).iloc[1:]


def log_returns(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return np.log(prices / prices.shift(1)).iloc[1:]


def cumulative_return(r: pd.Series) -> float:
    return float(np.prod(1.0 + r.values) - 1.0)


def annualized_mean(r: pd.Series | pd.DataFrame, periods_per_year: int):
    return r.mean() * periods_per_year


def annualized_vol(r: pd.Series | pd.DataFrame, periods_per_year: int):
    return r.std(ddof=1) * np.sqrt(periods_per_year)


def cagr(start_value: float, end_value: float, start: pd.Timestamp, end: pd.Timestamp) -> float:
    years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    if years <= 0 or start_value <= 0:
        return float("nan")
    return float((end_value / start_value) ** (1.0 / years) - 1.0)


def wealth_index(r: pd.Series, start: float = 1.0) -> pd.Series:
    return start * (1.0 + r).cumprod()


def common_calendar(prices: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Keep only dates on which every column has an observation (no filling)."""
    union = len(prices.index)
    common = prices.dropna(how="any")
    return common, {"union_dates": union, "common_dates": len(common),
                    "dropped_dates": union - len(common),
                    "dropped_pct": 100.0 * (union - len(common)) / union if union else 0.0}


def to_frequency(prices: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Daily (unchanged) or weekly (last common observation of each Friday-ending week)."""
    if frequency == "weekly":
        return prices.resample("W-FRI").last().dropna(how="any")
    return prices


def load_base_currency_prices(db: Database, tickers: list[str], base_currency: str,
                              max_staleness_days: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (wide base-currency adjusted prices on the union of dates, conversion report)."""
    local = db.get_prices_wide(tickers, "adj_close")
    fx_info = db.get_fx_series_info()
    series: dict[str, pd.Series] = {}
    reports: list[ConversionReport] = []
    for tk in tickers:
        sec = db.get_security(tk) or {}
        ccy = sec.get("currency") or ""
        if tk not in local.columns or local[tk].dropna().empty:
            reports.append(ConversionReport(tk, ccy, major_currency(ccy)[0], 1.0, "-", None, 0, 0, 0, 0, 0, 0,
                                            [t("No stored price history.")]))
            continue
        if not ccy:
            reports.append(ConversionReport(tk, "", "", 1.0, "-", None, int(local[tk].notna().sum()), 0, 0, 0, 0, 0,
                                            [t("Trading currency unknown; cannot convert. Re-validate the ticker.")]))
            continue
        major, _ = major_currency(ccy)
        fx = None
        verified = None
        if major != base_currency:
            fx = db.get_fx(major, base_currency)
            row = fx_info[(fx_info["base_currency"] == major) & (fx_info["quote_currency"] == base_currency)] \
                if not fx_info.empty else fx_info
            verified = bool(row["direction_verified"].iloc[0]) if len(row) else None
        conv, rep = convert_to_base(local[tk], ccy, base_currency, fx, max_staleness_days, verified, tk)
        if verified is False and major != base_currency:
            rep.notes.append(t("FX quote direction NOT verified (inverse symbol unavailable or derived series)."))
        reports.append(rep)
        if not conv.empty:
            series[tk] = conv
    wide = pd.DataFrame(series).sort_index() if series else pd.DataFrame()
    report = pd.DataFrame([{**asdict(r), "notes": " ".join(r.notes)} for r in reports])
    return wide, report


def conversion_details(db: Database, tickers: list[str], base_currency: str, max_staleness_days: int = 3
                       ) -> dict[str, dict]:
    """For the currency-conversion page: per ticker the row-by-row conversion and where the rate came from."""
    local = db.get_prices_wide(tickers, "adj_close")
    info = db.get_fx_series_info()
    out: dict[str, dict] = {}
    for tk in tickers:
        sec = db.get_security(tk) or {}
        ccy = sec.get("currency") or ""
        if tk not in local.columns or not ccy:
            continue
        major, divisor = major_currency(ccy)
        fx, row = None, None
        if major != base_currency:
            fx = db.get_fx(major, base_currency)
            if not info.empty:
                m = info[(info["base_currency"] == major) & (info["quote_currency"] == base_currency)]
                row = m.iloc[0].to_dict() if len(m) else None
        out[tk] = {"currency": ccy, "major": major, "divisor": divisor,
                   "pair": f"{major}/{base_currency}" if major != base_currency else "",
                   "symbol": (row or {}).get("symbol") or (f"{major}{base_currency}=X" if major != base_currency else ""),
                   "verified": None if row is None else bool(row.get("direction_verified")),
                   "verification_detail": (row or {}).get("verification_detail") or "",
                   "detail": conversion_detail(local[tk], ccy, base_currency, fx, max_staleness_days),
                   "fx": fx}
    return out
