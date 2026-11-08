import numpy as np
import pandas as pd
import pytest

from src.fx import convert_to_base, triangulate, verify_direction
from src.returns import annualized_mean, annualized_vol, cagr, common_calendar, cumulative_return, log_returns, \
    simple_returns, to_frequency


def test_simple_and_log_returns():
    p = pd.Series([100.0, 110.0, 99.0], index=pd.bdate_range("2024-01-01", periods=3))
    r = simple_returns(p)
    assert r.tolist() == pytest.approx([0.10, -0.10])
    g = log_returns(p)
    assert g.tolist() == pytest.approx([np.log(1.1), np.log(0.9)])
    assert cumulative_return(r) == pytest.approx(99 / 100 - 1)
    assert g.sum() == pytest.approx(np.log(99 / 100))  # log returns are time-additive


def test_annualization():
    r = pd.Series([0.001, -0.002, 0.003, 0.0])
    assert annualized_mean(r, 252) == pytest.approx(252 * r.mean())
    assert annualized_vol(r, 252) == pytest.approx(np.sqrt(252) * r.std(ddof=1))
    assert cagr(100, 121, pd.Timestamp("2020-01-01"), pd.Timestamp("2022-01-01")) == pytest.approx(
        1.21 ** (1 / (731 / 365.25)) - 1)


def test_currency_conversion_known_values_and_cross_term():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    px = pd.Series([100.0, 110.0], index=idx)               # +10% in USD
    fx = pd.Series([17.0, 18.7], index=idx)                 # MXN per USD, +10%
    out, rep = convert_to_base(px, "USD", "MXN", fx)
    assert out.tolist() == pytest.approx([1700.0, 2057.0])
    r = out.iloc[1] / out.iloc[0] - 1
    assert r == pytest.approx((1.1) * (1.1) - 1)            # 21%, not 20%: cross term included
    assert rep.n_fx_same_day == 2 and rep.n_dropped_no_fx == 0


def test_minor_currency_units_pence():
    idx = pd.to_datetime(["2024-01-02"])
    out, rep = convert_to_base(pd.Series([250.0], index=idx), "GBp", "MXN", pd.Series([22.0], index=idx))
    assert out.iloc[0] == pytest.approx(2.5 * 22.0) and rep.unit_divisor == 100


def test_fx_alignment_carry_limit_and_drop():
    stock_idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-15"])
    fx = pd.Series([10.0, 11.0], index=pd.to_datetime(["2024-01-02", "2024-01-05"]))
    out, rep = convert_to_base(pd.Series([1.0, 1.0, 1.0, 1.0], index=stock_idx), "USD", "MXN", fx,
                               max_staleness_days=3)
    # 01-03 uses 01-02 rate (1 day old); 01-08 uses 01-05 (3 days); 01-15 has no rate within 3 days -> dropped
    assert out.tolist() == pytest.approx([10.0, 10.0, 11.0])
    assert rep.n_fx_carried == 2 and rep.n_dropped_no_fx == 1 and rep.max_fx_staleness_days == 3


def test_same_currency_no_conversion():
    idx = pd.bdate_range("2024-01-01", periods=3)
    out, rep = convert_to_base(pd.Series([1.0, 2.0, 3.0], index=idx), "MXN", "MXN", None)
    assert out.tolist() == [1.0, 2.0, 3.0] and rep.fx_pair.startswith("none")


def test_fx_direction_verification():
    idx = pd.bdate_range("2024-01-01", periods=10)
    direct = pd.Series(np.linspace(17, 18, 10), index=idx)
    assert verify_direction(direct, 1 / direct, "USD", "MXN").verified
    assert not verify_direction(direct, direct, "USD", "MXN").verified   # inverse quoted the "wrong" way
    assert not verify_direction(direct, pd.Series(dtype=float), "USD", "MXN").verified
    tri = triangulate(pd.Series([18.0], index=idx[:1]), pd.Series([5.0], index=idx[:1]))
    assert tri.iloc[0] == pytest.approx(3.6)  # BRL->MXN = (MXN/USD)/(BRL/USD)


def test_common_calendar_no_filling():
    idx = pd.bdate_range("2024-01-01", periods=5)
    prices = pd.DataFrame({"A": [1, 2, 3, 4, 5.0], "B": [1, np.nan, 3, np.nan, 5.0]}, index=idx)
    common, rep = common_calendar(prices)
    assert list(common.index) == [idx[0], idx[2], idx[4]]
    assert rep["dropped_dates"] == 2
    assert not common.isna().any().any()
    w = to_frequency(prices.dropna(), "weekly")
    assert len(w) >= 1 and not w.isna().any().any()



def test_currency_conversion_rejects_nonfinite_prices_and_fx():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    px = pd.Series([100.0, np.inf, 120.0], index=idx)
    fx = pd.Series([17.0, 18.0, np.inf], index=idx)
    out, report = convert_to_base(px, "USD", "MXN", fx, max_staleness_days=0)
    assert list(out.index) == [idx[0]]
    assert out.iloc[0] == pytest.approx(1700.0)
    assert report.n_local == 2
    assert report.n_converted == 1
    assert report.n_dropped_no_fx == 1


def test_fx_triangulation_rejects_zero_and_infinite_rates():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    a = pd.Series([18.0, np.inf, 19.0], index=idx)
    b = pd.Series([5.0, 4.0, 0.0], index=idx)
    out = triangulate(a, b)
    assert list(out.index) == [idx[0]]
    assert out.iloc[0] == pytest.approx(3.6)
