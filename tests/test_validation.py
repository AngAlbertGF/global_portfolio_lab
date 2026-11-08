import pandas as pd
import pytest

from src.validation import Holding, Portfolio, check_ticker_syntax, clean_price_frame, global_weights, \
    market_consistency_warnings, normalize_ticker, validate_holdings, validate_market_allocations


def make(allocs, holdings):
    return Portfolio(market_allocations=allocs, holdings=[Holding(*h) for h in holdings])


def test_market_allocations_sum_to_100():
    assert validate_market_allocations({"USA": 50, "MEXICO": 20, "BRAZIL": 10, "JAPAN": 10, "AUSTRALIA": 5,
                                        "INDIA": 5}).ok
    v = validate_market_allocations({"USA": 60, "MEXICO": 30})
    assert not v.ok and abs(v.details["remaining"] - 10) < 1e-12
    assert any("unallocated" in e for e in v.errors)
    assert not validate_market_allocations({"USA": 120, "MEXICO": -20}).ok
    assert not validate_market_allocations({"USA": 0.0}).ok  # at least one positive market
    # floating-point tolerance: thirds sum to 100 within tolerance
    assert validate_market_allocations({"A": 100 / 3, "B": 100 / 3, "C": 100 / 3}).ok


def test_within_market_weights_sum_to_100():
    p = make({"USA": 80, "MEXICO": 20}, [("NVDA", "USA", 25), ("AAPL", "USA", 70), ("WALMEX.MX", "MEXICO", 100)])
    v = validate_holdings(p)
    assert not v.ok and any("USA" in e and "95" in e for e in v.errors)
    p.holdings[1].within_pct = 75
    assert validate_holdings(p).ok


def test_global_weight_conversion_matches_spec_example():
    p = make({"USA": 80, "MEXICO": 20}, [("NVDA", "USA", 25), ("AAPL", "USA", 75), ("WALMEX.MX", "MEXICO", 100)])
    w = global_weights(p)
    assert w["NVDA"] == pytest.approx(0.20)
    assert w.sum() == pytest.approx(1.0, abs=1e-15)


def test_duplicates_negative_and_empty_markets_rejected():
    p = make({"USA": 100}, [("AAPL", "USA", 50), ("AAPL", "USA", 50)])
    assert any("more than once" in e for e in validate_holdings(p).errors)
    p = make({"USA": 100}, [("AAPL", "USA", 120), ("MSFT", "USA", -20)])
    assert any("negative" in e for e in validate_holdings(p, long_only=True).errors)
    p = make({"USA": 50, "MEXICO": 50}, [("AAPL", "USA", 100)])
    assert any("no securities" in e for e in validate_holdings(p).errors)


def test_ticker_normalization_preserves_suffix_and_rejects_names():
    assert normalize_ticker("  walmex.mx \n") == "WALMEX.MX"
    assert check_ticker_syntax("WALMEX.MX") is None
    assert check_ticker_syntax("Walmart de Mexico".upper()) is not None
    assert check_ticker_syntax("") is not None


def test_currency_and_suffix_conflicts_warn(markets):
    w = market_consistency_warnings("VALE", "USD", markets["BRAZIL"])
    assert any("suffix" in x for x in w) and any("USD" in x for x in w)
    assert market_consistency_warnings("PETR4.SA", "BRL", markets["BRAZIL"]) == []
    assert market_consistency_warnings("BARC.L", "GBp", markets["UK"]) == []  # pence is GBP


def test_clean_price_frame_never_fabricates():
    idx = pd.bdate_range("2024-01-01", periods=5)
    df = pd.DataFrame({"open": 1, "high": [2, 2, 1, 2, 2], "low": [1, 1, 2, 1, 1], "close": [10, None, 11, 0, 12],
                       "adj_close": [10, 10.5, 11, 0, 12], "volume": 1}, index=idx)
    out, rep = clean_price_frame(df)
    assert len(out) == 3 and rep.dropped_missing_close == 1 and rep.dropped_nonpositive == 1
    assert rep.high_below_low == 1
    assert set(out.index) <= set(df.index)



def test_clean_price_frame_drops_infinite_prices():
    idx = pd.bdate_range("2024-01-01", periods=4)
    df = pd.DataFrame({"close": [10.0, float("inf"), 11.0, 12.0],
                       "adj_close": [10.0, 10.5, float("inf"), 12.0],
                       "high": [11.0] * 4, "low": [9.0] * 4}, index=idx)
    out, rep = clean_price_frame(df)
    assert list(out.index) == [idx[0], idx[3]]
    assert rep.dropped_missing_close == 2
    assert np.isfinite(out[["close", "adj_close"]].to_numpy()).all()
