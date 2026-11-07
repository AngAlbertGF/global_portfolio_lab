"""Deterministic SYNTHETIC data provider -- for tests and the offline demo database only.

Everything produced here is illustrative and is labelled SYNTHETIC in the database
(provider column) and in the UI.  It is never mixed into the real database: the demo
uses a separate file (demo_synthetic.db).
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .yahoo_client import ProviderError, SecurityMetadata, TickerNotFound

SYNTHETIC_PROVIDER = "SYNTHETIC (illustrative data, NOT market prices)"

# ticker -> (name, currency, listing date, annual drift, annual vol, market beta)
DEMO_UNIVERSE: dict[str, tuple[str, str, str, float, float, float]] = {
    "DEMO-US1": ("Synthetic US Tech", "USD", "2005-01-03", 0.14, 0.30, 1.2),
    "DEMO-US2": ("Synthetic US Staples", "USD", "2005-01-03", 0.07, 0.16, 0.6),
    "DEMO-US3": ("Synthetic US Recent IPO", "USD", "2022-06-01", 0.10, 0.40, 1.4),
    "DEMO-MX1.MX": ("Synthetic Mexico Retail", "MXN", "2005-01-03", 0.09, 0.22, 0.8),
    "DEMO-MX2.MX": ("Synthetic Mexico Telecom", "MXN", "2005-01-03", 0.05, 0.25, 0.9),
    "DEMO-JP1.T": ("Synthetic Japan Autos", "JPY", "2005-01-03", 0.06, 0.24, 0.9),
    "DEMO-BR1.SA": ("Synthetic Brazil Energy", "BRL", "2005-01-03", 0.11, 0.38, 1.1),
    "DEMO-UK1.L": ("Synthetic UK Bank (pence)", "GBp", "2005-01-03", 0.04, 0.28, 1.0),
    "^DEMO-IDX": ("Synthetic Global Index", "USD", "2005-01-03", 0.08, 0.16, 1.0),
}
CCY_USD_VALUE = {"USD": (1.0, 0.0, 0.0), "MXN": (1 / 13.0, -0.03, 0.12), "JPY": (1 / 100.0, -0.01, 0.10),
                 "BRL": (1 / 2.2, -0.06, 0.16), "GBP": (1.55, -0.01, 0.09), "EUR": (1.30, 0.0, 0.08)}
HISTORY_START = date(2009, 1, 2)
HISTORY_END = date(2026, 10, 23)


def _seed(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _calendar(key: str) -> pd.DatetimeIndex:
    days = pd.bdate_range(HISTORY_START, HISTORY_END)
    rng = np.random.default_rng(_seed("cal" + key))
    keep = rng.random(len(days)) > 0.025  # market-specific "holidays"
    return days[keep]


def _market_factor() -> pd.Series:
    days = pd.bdate_range(HISTORY_START, HISTORY_END)
    rng = np.random.default_rng(_seed("market"))
    return pd.Series(rng.standard_t(5, len(days)) * 0.16 / np.sqrt(252) / np.sqrt(5 / 3), index=days)


def synthetic_prices(ticker: str) -> pd.DataFrame:
    name, ccy, listed, mu, vol, beta = DEMO_UNIVERSE[ticker]
    days = _calendar(ccy + ticker[-3:])
    days = days[days >= pd.Timestamp(listed)]
    f = _market_factor().reindex(days).fillna(0.0)
    rng = np.random.default_rng(_seed(ticker))
    idio_vol = np.sqrt(max(vol ** 2 - (beta * 0.16) ** 2, 0.0025)) / np.sqrt(252)
    r = mu / 252 + beta * f.values + rng.normal(0, idio_vol, len(days))
    close = 100.0 * np.exp(np.cumsum(np.log1p(r)))
    if ccy == "GBp":
        close *= 3.0  # pence-sized numbers
    div_yield = 0.02
    adj = close * np.exp((np.arange(len(days)) - len(days)) * div_yield / 252)  # dividend-style adjustment
    noise = rng.uniform(0.002, 0.012, len(days))
    return pd.DataFrame({"open": close * (1 - noise / 2), "high": close * (1 + noise), "low": close * (1 - noise),
                         "close": close, "adj_close": adj, "volume": rng.integers(1e5, 5e6, len(days))},
                        index=pd.DatetimeIndex(days, name="date"))


def _usd_value(ccy: str) -> pd.Series:
    days = pd.bdate_range(HISTORY_START, HISTORY_END)
    level, drift, vol = CCY_USD_VALUE[ccy]
    if vol == 0:
        return pd.Series(level, index=days)
    rng = np.random.default_rng(_seed("fx" + ccy))
    path = level * np.exp(np.cumsum(drift / 252 + rng.normal(0, vol / np.sqrt(252), len(days))))
    return pd.Series(path, index=days)


def synthetic_fx(from_ccy: str, to_ccy: str) -> pd.Series:
    """Rate = to_ccy per 1 from_ccy, internally consistent across pairs."""
    return (_usd_value(from_ccy) / _usd_value(to_ccy)).rename(f"{from_ccy}{to_ccy}")


class SyntheticProvider:
    """Implements the PriceProvider protocol with deterministic synthetic data.

    ``fail_tickers``  -> raise ProviderError (simulate outages)
    ``empty_tickers`` -> return empty frames (simulate empty responses)
    """

    name = SYNTHETIC_PROVIDER

    def __init__(self, fail_tickers: set[str] | None = None, empty_tickers: set[str] | None = None,
                 invert_fx: set[str] | None = None):
        self.fail = fail_tickers or set()
        self.empty = empty_tickers or set()
        self.invert_fx = invert_fx or set()
        self.calls: list[tuple[str, date, date]] = []

    def fetch_history(self, ticker: str, start: date, end_exclusive: date) -> pd.DataFrame:
        self.calls.append((ticker, start, end_exclusive))
        if ticker in self.fail:
            raise ProviderError(f"Simulated outage for {ticker}")
        cols = ["open", "high", "low", "close", "adj_close", "volume"]
        if ticker in self.empty:
            return pd.DataFrame(columns=cols)
        if ticker.endswith("=X") and len(ticker) == 8:
            a, b = ticker[:3], ticker[3:6]
            if a not in CCY_USD_VALUE or b not in CCY_USD_VALUE:
                raise TickerNotFound(f"No synthetic FX for {ticker}")
            s = synthetic_fx(a, b)
            if ticker in self.invert_fx:
                s = 1 / s
            df = pd.DataFrame({c: s.values for c in cols[:5]}, index=s.index)
            df["volume"] = 0.0
        elif ticker in DEMO_UNIVERSE:
            df = synthetic_prices(ticker)
        else:
            raise TickerNotFound(f"Unknown synthetic symbol {ticker}")
        mask = (df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end_exclusive))
        out = df.loc[mask, cols]
        out.index.name = "date"
        return out

    def fetch_metadata(self, ticker: str) -> SecurityMetadata:
        if ticker in self.fail:
            raise ProviderError(f"Simulated outage for {ticker}")
        if ticker not in DEMO_UNIVERSE:
            raise TickerNotFound(f"Unknown synthetic symbol {ticker}")
        name, ccy, *_ = DEMO_UNIVERSE[ticker]
        exch = {"USD": "SYNTH-US", "MXN": "SYNTH-MX", "JPY": "SYNTH-JP", "BRL": "SYNTH-BR", "GBp": "SYNTH-UK"}[ccy]
        return SecurityMetadata(ticker, name, exch, ccy, "UTC", "INDEX" if ticker.startswith("^") else "EQUITY")


DEMO_MARKET_OF = {"DEMO-US1": "USA", "DEMO-US2": "USA", "DEMO-US3": "USA", "DEMO-MX1.MX": "MEXICO",
                  "DEMO-MX2.MX": "MEXICO", "DEMO-JP1.T": "JAPAN", "DEMO-BR1.SA": "BRAZIL", "DEMO-UK1.L": "UK",
                  "^DEMO-IDX": "USA"}


def demo_portfolio():
    from .validation import Holding, Portfolio
    return Portfolio(
        name="SYNTHETIC demo portfolio", base_currency="MXN", total_capital=1_000_000.0,
        market_allocations={"USA": 50.0, "MEXICO": 20.0, "JAPAN": 10.0, "BRAZIL": 10.0, "UK": 10.0},
        holdings=[Holding("DEMO-US1", "USA", 50.0), Holding("DEMO-US2", "USA", 30.0), Holding("DEMO-US3", "USA", 20.0),
                  Holding("DEMO-MX1.MX", "MEXICO", 60.0), Holding("DEMO-MX2.MX", "MEXICO", 40.0),
                  Holding("DEMO-JP1.T", "JAPAN", 100.0), Holding("DEMO-BR1.SA", "BRAZIL", 100.0),
                  Holding("DEMO-UK1.L", "UK", 100.0)])


def build_demo_database(db, settings, markets, now=None) -> list:
    """Populate a (separate) database through the real DataService pipeline using synthetic data."""
    from datetime import datetime, timezone

    from .data_service import DataService

    now = now or (lambda: datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
    svc = DataService(db, SyntheticProvider(), markets, settings, now=now, cache_hours=0)
    results = []
    for t, m in DEMO_MARKET_OF.items():
        v = svc.validate_ticker(t, m, force_remote=True)
        results.append(v)
    results += svc.update_many(list(DEMO_MARKET_OF.items()), settings.base_currency)
    from .logos import LogoService
    LogoService(db, offline=True).ensure(list(DEMO_MARKET_OF))   # labelled synthetic tiles, no network
    db.set_meta("database_kind", "SYNTHETIC_DEMO")
    return results
