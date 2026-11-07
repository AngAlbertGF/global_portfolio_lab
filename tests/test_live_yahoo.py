"""Optional LIVE integration test against Yahoo Finance (network required).

Skipped by default. Run with:  GPL_LIVE_TESTS=1 pytest tests/test_live_yahoo.py -v
It downloads real data into a temporary database; results depend on Yahoo's availability.
"""
import os

import pytest

from src.analysis import run_analysis
from src.config import AppSettings, load_markets
from src.data_service import DataService
from src.database import Database
from src.validation import Holding, Portfolio

pytestmark = pytest.mark.skipif(os.environ.get("GPL_LIVE_TESTS") != "1", reason="set GPL_LIVE_TESTS=1 to run")


def test_live_download_fx_and_analysis(tmp_path):
    from src.yahoo_client import YahooProvider

    s = AppSettings(data_dir=str(tmp_path), history_years=6)
    db = Database(tmp_path / "stock_prices.db")
    svc = DataService(db, YahooProvider(), load_markets(), s, cache_hours=0)
    items = [("AAPL", "USA"), ("WALMEX.MX", "MEXICO"), ("7203.T", "JAPAN"), ("PETR4.SA", "BRAZIL")]
    for t, m in items:
        assert svc.validate_ticker(t, m).accepted, t
    bad = svc.validate_ticker("ZZQXQ.MX", "MEXICO")  # NOT_FOUND normally; PROVIDER_ERROR if Yahoo throttles
    assert not bad.accepted and bad.status in ("NOT_FOUND", "NO_PRICE_DATA", "PROVIDER_ERROR")
    res = svc.update_many(items, "MXN")
    assert all(r.status in ("SUCCESS", "UP_TO_DATE") for r in res), [(r.symbol, r.status, r.messages) for r in res]
    n = db.table_counts()["daily_prices"]
    again = svc.update_many(items, "MXN")  # refresh: no duplicates
    assert db.table_counts()["daily_prices"] == n and all(r.inserted <= 2 for r in again)
    fx = db.get_fx_series_info()
    assert fx.set_index("base_currency").loc["USD", "direction_verified"] == 1
    p = Portfolio("live", "MXN", None, {"USA": 40, "MEXICO": 30, "JAPAN": 15, "BRAZIL": 15},
                  [Holding(t, m, 100.0) for t, m in items])
    b = run_analysis(db, p, s, load_markets(), (1, 5))
    assert b.horizons[1].status == "COMPLETE" and b.horizons[5].status == "COMPLETE"
    assert all(o.ok for o in b.horizons[5].optimized.values())
    assert db.integrity_check()["ok"]


def test_live_split_repair_and_logos(tmp_path):
    """1321.T (Nikkei 225 ETF) had a 100:1 split: the stored adjusted series must have no split-sized jumps."""
    from src.corporate_actions import split_like_jumps
    from src.logos import LogoService
    from src.yahoo_client import YahooProvider

    s = AppSettings(data_dir=str(tmp_path), history_years=3)
    db = Database(tmp_path / "stock_prices.db")
    svc = DataService(db, YahooProvider(), load_markets(), s, cache_hours=0)
    items = [("1321.T", "JAPAN"), ("NVDA", "USA"), ("WALMEX.MX", "MEXICO")]
    res = svc.update_many(items, "MXN")
    assert all(r.status in ("SUCCESS", "UP_TO_DATE") for r in res), [(r.symbol, r.status, r.messages) for r in res]
    px = db.get_price_history("1321.T")["adj_close"]
    assert split_like_jumps(px) == [], split_like_jumps(px)
    assert (px.pct_change().abs().dropna() < 0.3).all()
    logos = LogoService(db).ensure(["NVDA", "WALMEX.MX"])
    assert logos["NVDA"]["status"] == "OK" and logos["NVDA"]["primary_color"]
    assert logos["WALMEX.MX"]["status"] == "OK"
