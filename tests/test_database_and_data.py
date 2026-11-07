"""Database integrity and download pipeline with a mocked (synthetic) provider."""
import sqlite3

import pandas as pd
import pytest

from src.database import Database
from src.synthetic import SyntheticProvider
from src.validation import Holding, Portfolio


def test_initialize_new_database(tmp_path):
    db = Database(tmp_path / "sub dir ñ" / "stock_prices.db")  # spaces and non-ASCII in path
    counts = db.table_counts()
    assert counts["daily_prices"] == 0
    assert db.integrity_check()["schema_version"] == 3
    Database(db.path)  # re-initialising is idempotent


def test_duplicate_prevention_and_upsert(db):
    idx = pd.bdate_range("2024-01-01", periods=5)
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.0, "adj_close": [1, 2, 3, 4, 5.0],
                       "volume": 10}, index=idx)
    db.upsert_security({"ticker": "X", "market_id": "USA", "currency": "USD"})
    assert db.upsert_prices("X", df) == (5, 0)
    df2 = df.copy()
    df2["adj_close"] = df2["adj_close"] * 1.01  # provider revision
    assert db.upsert_prices("X", df2) == (0, 5)
    assert db.get_date_range("X")[2] == 5
    assert db.get_price_history("X")["adj_close"].iloc[0] == pytest.approx(1.01)
    with sqlite3.connect(db.path) as c, pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO daily_prices (ticker, date, close, adj_close) VALUES ('X', ?, 1, 1)",
                  (idx[0].strftime("%Y-%m-%d"),))
    assert db.integrity_check()["duplicate_price_keys"] == 0


def test_download_and_cache_then_refresh_without_duplicates(make_service, db):
    svc = make_service()
    assert svc.validate_ticker("DEMO-US1", "USA").status == "VALID"
    r1 = svc.update_ticker("DEMO-US1", "USA")
    assert r1.status == "SUCCESS" and r1.inserted > 3000
    n1 = db.get_date_range("DEMO-US1")[2]
    r2 = svc.update_ticker("DEMO-US1", "USA")
    assert r2.inserted == 0 and r2.updated > 0 and r2.status == "UP_TO_DATE"
    assert db.get_date_range("DEMO-US1")[2] == n1
    assert db.integrity_check()["ok"]


def test_cache_avoids_network(make_service):
    prov = SyntheticProvider()
    svc = make_service(prov, cache_hours=12)
    svc.validate_ticker("DEMO-US2", "USA")
    svc.update_ticker("DEMO-US2", "USA")
    calls = len(prov.calls)
    res = svc.update_ticker("DEMO-US2", "USA")
    assert res.status == "UP_TO_DATE" and len(prov.calls) == calls


def test_recent_listing_backfill_checked_once(make_service, db):
    prov = SyntheticProvider()
    svc = make_service(prov)
    svc.update_ticker("DEMO-US3", "USA")  # listed 2022 -> shorter than 15 years
    plan = svc.plan_requests("DEMO-US3", svc.markets["USA"])
    assert [k for _, _, k in plan] == ["refresh"]  # history before listing is not re-requested


def test_invalid_ticker_and_provider_error_distinguished(make_service):
    svc = make_service(SyntheticProvider(fail_tickers={"DEMO-US1"}))
    assert svc.validate_ticker("NOTREAL.MX", "MEXICO").status == "NOT_FOUND"
    assert svc.validate_ticker("DEMO-US1", "USA").status == "PROVIDER_ERROR"
    assert svc.validate_ticker("two words", "USA").status == "INVALID_SYNTAX"


def test_empty_provider_response(make_service, db):
    svc = make_service(SyntheticProvider(empty_tickers={"DEMO-MX1.MX"}))
    res = svc.update_ticker("DEMO-MX1.MX", "MEXICO")
    assert db.get_date_range("DEMO-MX1.MX")[2] == 0
    assert "no rows" in " ".join(res.messages)
    assert (db.get_download_log()["download_status"] == "NO_DATA").any()


def test_failed_refresh_keeps_existing_data(make_service, db):
    make_service().update_ticker("DEMO-JP1.T", "JAPAN")
    n = db.get_date_range("DEMO-JP1.T")[2]
    res = make_service(SyntheticProvider(fail_tickers={"DEMO-JP1.T"})).update_ticker("DEMO-JP1.T", "JAPAN")
    assert res.status == "FAILED"
    assert db.get_date_range("DEMO-JP1.T")[2] == n
    assert "DEMO-JP1.T" in db.failed_tickers()


def test_currency_mismatch_warning(make_service):
    v = make_service().validate_ticker("DEMO-US1", "BRAZIL")
    assert v.accepted and any("USD" in w for w in v.warnings)


def test_fx_download_verified_and_inverted_series_rejected(make_service, db):
    ok = make_service().update_fx("USD", "MXN")
    assert ok.status == "SUCCESS"
    info = db.get_fx_series_info("USD", "MXN")
    assert bool(info["direction_verified"].iloc[0])
    bad = make_service(SyntheticProvider(invert_fx={"JPYMXN=X"})).update_fx("JPY", "MXN")
    assert bad.status == "FAILED" and db.get_fx_range("JPY", "MXN")[2] == 0


def test_backup_restore_and_portfolio_persistence(db):
    p = Portfolio("Test", "MXN", 1000.0, {"USA": 100.0}, [Holding("AAPL", "USA", 100.0)])
    pid = db.save_portfolio(p)
    backup = db.backup()
    db.delete_portfolio(pid)
    assert db.load_portfolio(pid) is None
    db.restore(backup)
    loaded = db.load_portfolio(pid)
    assert loaded.name == "Test" and loaded.holdings[0].ticker == "AAPL"
    reopened = Database(db.path)  # persistence across sessions
    assert reopened.list_portfolios()["portfolio_name"].tolist() == ["Test"]
