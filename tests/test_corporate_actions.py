"""Splits, reverse splits and dividends: repair of provider errors and re-download on a basis change."""
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src import corporate_actions as ca
from src.config import AppSettings, load_markets
from src.data_service import DataService
from src.database import Database
from src.yahoo_client import SecurityMetadata, TickerNotFound

COLS = ["open", "high", "low", "close", "adj_close", "volume"]


def _frame(close, idx, adj=None, splits=None, dividends=None):
    close = np.asarray(close, float)
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                       "adj_close": close if adj is None else adj, "volume": 1000.0}, index=idx)
    df.index.name = "date"
    df["splits"] = 0.0 if splits is None else splits
    df["dividends"] = 0.0 if dividends is None else dividends
    return df


def test_block_off_by_100_after_split_is_rescaled():
    """1321.T pattern (Oct 2026): two post-split sessions divided by 100 a second time."""
    idx = pd.bdate_range("2026-09-28", periods=8)
    close = [690.0, 696.2, 718.1, 710.4, 7.279, 7.351, 729.7, 719.5]
    sp = np.zeros(8)
    sp[4] = 100.0
    out, rep = ca.repair_frame(_frame(close, idx, splits=sp))
    assert out["close"].round(1).tolist() == [690.0, 696.2, 718.1, 710.4, 727.9, 735.1, 729.7, 719.5]
    assert [r.kind for r in rep.repairs] == ["SCALE_BLOCK"] and rep.repairs[0].factor == pytest.approx(100)
    assert out["adj_close"].pct_change().abs().max() < 0.05
    assert ca.split_like_jumps(out["adj_close"]) == []


def test_history_left_on_presplit_basis_is_divided():
    idx = pd.bdate_range("2024-01-01", periods=6)
    close = [67800.0, 68000.0, 68200.0, 682.5, 685.0, 690.0]   # 100:1 split on the 4th day, history not adjusted
    sp = np.zeros(6)
    sp[3] = 100.0
    out, rep = ca.repair_frame(_frame(close, idx, splits=sp))
    assert out["close"].iloc[:3].tolist() == pytest.approx([678.0, 680.0, 682.0])
    assert rep.repairs[0].kind == "PRESPLIT_UNADJUSTED"


def test_reverse_split_block_is_repaired():
    idx = pd.bdate_range("2024-01-01", periods=7)
    close = [5.0, 5.1, 51.0, 52.0, 5.3, 5.2, 5.25]               # 1:10 reverse-split applied to two rows only
    sp = np.zeros(7)
    sp[2] = 0.1
    out, rep = ca.repair_frame(_frame(close, idx, splits=sp))
    assert out["close"].tolist() == pytest.approx([5.0, 5.1, 5.1, 5.2, 5.3, 5.2, 5.25])
    assert rep.repairs[0].factor == pytest.approx(0.1)


def test_negative_adjusted_close_recomputed_from_rebased_dividends():
    idx = pd.bdate_range("2025-07-01", periods=6)
    close = np.array([416.4, 417.5, 407.7, 409.3, 410.4, 408.8])
    adj = np.array([-318.3, -319.2, -311.7, 404.6, 405.7, 404.1])     # Yahoo: dividend on the pre-split basis
    dv = np.zeros(6)
    dv[3] = 723.0                                                      # should be 7.23 after the later 100:1 split
    df = _frame(close, idx, adj=adj, dividends=dv)
    df.loc[pd.Timestamp("2026-10-05")] = [7.3, 7.3, 7.3, 7.3, 7.3, 1.0, 100.0, 0.0]   # the split itself, later
    df = df.sort_index()
    assert ca.check_adjusted(df.iloc[:6])
    out, rep = ca.repair_frame(df)
    kinds = [r.kind for r in rep.repairs]
    assert "DIVIDEND_REBASED" in kinds and "ADJ_RECOMPUTED" in kinds
    a = out["adj_close"].iloc[:6]
    assert (a > 0).all()
    f = 1 - 7.23 / 407.7
    assert a.iloc[2] == pytest.approx(407.7 * f) and a.iloc[3] == pytest.approx(409.3)
    assert ca.check_adjusted(out) == []


class SplittingProvider:
    """Yahoo-like: a 100:1 split on SPLIT_DAY; once it has happened the WHOLE history is served split-adjusted."""
    name = "fake"
    SPLIT_DAY = pd.Timestamp("2026-10-05")

    def __init__(self):
        self.asof = None
        idx = pd.bdate_range("2012-01-02", "2026-10-30")
        rng = np.random.default_rng(5)
        self.true_price = pd.Series(70000 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx)))), index=idx)

    def fetch_history(self, ticker, start, end_exclusive):
        if ticker != "SPLT":
            raise TickerNotFound(ticker)
        px = self.true_price[self.true_price.index < pd.Timestamp(self.asof)]
        if pd.Timestamp(self.asof) > self.SPLIT_DAY:
            px = px.where(px.index >= self.SPLIT_DAY, px / 100.0)       # retroactive adjustment of old rows
            px = px.where(px.index < self.SPLIT_DAY, px / 100.0)        # post-split prices are 1/100
        df = _frame(px.values, px.index)
        if pd.Timestamp(self.asof) > self.SPLIT_DAY and self.SPLIT_DAY in df.index:
            df.loc[self.SPLIT_DAY, "splits"] = 100.0
        m = (df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end_exclusive))
        return df.loc[m]

    def fetch_metadata(self, ticker):
        return SecurityMetadata(ticker, "Split Co", "TSE", "JPY", "Asia/Tokyo", "EQUITY")


def _svc(db, prov, when):
    s = AppSettings(history_years=5)
    return DataService(db, prov, load_markets(), s, now=lambda: when, cache_hours=0)


def test_split_after_incremental_download_triggers_full_rebase(tmp_path):
    db, prov = Database(tmp_path / "x.db"), SplittingProvider()
    prov.asof = "2026-09-30"
    first = _svc(db, prov, datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
    assert first.validate_ticker("SPLT", "JAPAN").accepted
    first.update_ticker("SPLT", "JAPAN")
    assert db.get_price_history("SPLT")["adj_close"].iloc[-1] > 10000          # pre-split basis
    prov.asof = "2026-10-20"
    res = _svc(db, prov, datetime(2026, 10, 20, 12, tzinfo=timezone.utc)).update_ticker("SPLT", "JAPAN")
    assert res.rebased and res.status == "SUCCESS", res.messages
    assert "100:1" in " ".join(res.messages)
    h = db.get_price_history("SPLT")["adj_close"]
    assert h.pct_change().abs().max() < 0.1                                     # no -99% day
    assert h.iloc[0] < 10000 and db.integrity_check()["duplicate_price_keys"] == 0
    assert (db.get_actions("SPLT", "SPLIT")["value"] == 100).all()


def test_corrupted_stored_history_is_rebased_on_next_update(tmp_path):
    db, prov = Database(tmp_path / "y.db"), SplittingProvider()
    prov.asof = "2026-10-20"
    svc = _svc(db, prov, datetime(2026, 10, 20, 12, tzinfo=timezone.utc))
    svc.validate_ticker("SPLT", "JAPAN")
    svc.update_ticker("SPLT", "JAPAN")
    good = db.get_price_history("SPLT")
    bad = good.copy()
    bad.loc[bad.index < "2025-01-01", ["open", "high", "low", "close", "adj_close"]] *= 100   # an old-basis block
    db.upsert_prices("SPLT", bad)
    assert ca.split_like_jumps(db.get_price_history("SPLT")["adj_close"])
    res = svc.update_ticker("SPLT", "JAPAN")
    assert res.rebased
    assert ca.split_like_jumps(db.get_price_history("SPLT")["adj_close"]) == []


def test_dividend_basis_change_is_detected(tmp_path):
    db, prov = Database(tmp_path / "z.db"), SplittingProvider()
    prov.asof = "2026-09-01"
    svc = _svc(db, prov, datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
    svc.update_ticker("SPLT", "JAPAN")
    orig = prov.fetch_history

    def with_dividend(ticker, start, end_exclusive):
        df = orig(ticker, start, end_exclusive)
        df["adj_close"] = df["close"] * np.where(df.index < pd.Timestamp("2026-09-02"), 0.98, 1.0)
        return df
    prov.fetch_history = with_dividend
    prov.asof = "2026-09-10"
    res = _svc(db, prov, datetime(2026, 9, 10, 12, tzinfo=timezone.utc)).update_ticker("SPLT", "JAPAN")
    assert res.rebased
    h = db.get_price_history("SPLT")
    assert (h.loc[h.index < "2026-09-02", "adj_close"] / h.loc[h.index < "2026-09-02", "close"]).round(6).eq(0.98).all()


def test_analysis_warns_on_remaining_extreme_returns(demo_env):
    from src.analysis import run_analysis
    from src.synthetic import demo_portfolio
    database, s = demo_env
    import shutil
    db2 = Database(database.path.parent / "corrupt.db")
    shutil.copy2(database.path, db2.path)
    h = db2.get_price_history("DEMO-US2")
    h.loc[h.index >= "2026-06-01", ["open", "high", "low", "close", "adj_close"]] /= 50
    db2.upsert_prices("DEMO-US2", h)
    b = run_analysis(db2, demo_portfolio(), s, load_markets(), (1,))
    assert any("Extreme period returns" in w and "DEMO-US2" in w for w in b.horizons[1].warnings)
