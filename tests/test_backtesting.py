"""Regression tests for the original walk-forward backtest engine."""
import numpy as np
import pandas as pd
import pytest

from src.backtesting import BacktestConfig, run_backtest
from src.optimization import ConstraintSet


def test_backtest_charges_cost_as_nav_deduction_and_drifted_weights():
    dates = pd.bdate_range("2024-01-02", periods=80)
    asset_a = np.full(len(dates), 100.0)
    asset_b = np.full(len(dates), 100.0)
    for i in range(1, len(dates)):
        asset_a[i] = asset_a[i - 1] * 1.02
        asset_b[i] = asset_b[i - 1]
    prices = pd.DataFrame({"A": asset_a, "B": asset_b}, index=dates)

    cs = ConstraintSet.build(["A", "B"], {"A": "ALL", "B": "ALL"}, {"ALL": 1.0}, mode="global_only")
    weights = pd.Series({"A": 0.5, "B": 0.5})
    cfg = BacktestConfig(window=20, rebalance="monthly", cost_bps=100.0, slippage_bps=0.0,
                         strategies=("user_rebalanced",), periods_per_year=252)

    result = run_backtest(prices, weights, cs, rf_annual=0.0, cfg=cfg)
    assert not result.returns.empty
    gross_first = 0.5 * 0.02
    expected_first = (1.0 + gross_first) * (1.0 - 0.01) - 1.0
    assert result.turnover.iloc[0, 0] == pytest.approx(1.0)
    assert result.returns.iloc[0, 0] == pytest.approx(expected_first)

    # No rebalance between the first and second test observations. Asset A's
    # weight drifts upward after its 2% gain, so the next portfolio return
    # must use the drifted weight rather than the original 50%.
    drifted_a = 0.5 * 1.02 / (1.0 + gross_first)
    expected_second = drifted_a * 0.02
    assert result.turnover.iloc[1, 0] == pytest.approx(0.0)
    assert result.returns.iloc[1, 0] == pytest.approx(expected_second)


def test_backtest_rejects_invalid_weights_and_costs():
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = pd.DataFrame({"A": np.arange(100.0, 180.0), "B": np.arange(100.0, 180.0)}, index=dates)
    cs = ConstraintSet.build(["A", "B"], {"A": "ALL", "B": "ALL"}, {"ALL": 1.0}, mode="global_only")
    bad_weights = pd.Series({"A": 0.8, "B": 0.8})
    cfg = BacktestConfig(window=20, strategies=("user_rebalanced",))
    with pytest.raises(ValueError, match="weights"):
        run_backtest(prices, bad_weights, cs, 0.05, cfg)
    good_weights = pd.Series({"A": 0.5, "B": 0.5})
    with pytest.raises(ValueError, match="non-negative"):
        run_backtest(prices, good_weights, cs, 0.05,
                     BacktestConfig(window=20, cost_bps=-1.0, strategies=("user_rebalanced",)))



def test_backtest_does_not_run_infeasible_equal_weight_strategy():
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = pd.DataFrame({"A": np.linspace(100.0, 120.0, len(dates)),
                           "B": np.linspace(100.0, 110.0, len(dates))}, index=dates)
    cs = ConstraintSet(tickers=["A", "B"], market_of={"A": "ALL", "B": "ALL"},
                       market_budgets={"ALL": 1.0}, mode="global_only",
                       lb=np.array([0.6, 0.0]), ub=np.array([1.0, 1.0]))
    feasible_user_weights = pd.Series({"A": 0.6, "B": 0.4})
    cfg = BacktestConfig(window=20, strategies=("equal_weight",))
    with pytest.raises(RuntimeError, match="no valid feasible target"):
        run_backtest(prices, feasible_user_weights, cs, 0.0, cfg)



def test_backtest_ignores_unrelated_incomplete_price_columns():
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = pd.DataFrame({"A": np.linspace(100.0, 120.0, len(dates)),
                           "B": np.linspace(100.0, 110.0, len(dates))}, index=dates)
    cs = ConstraintSet.build(["A", "B"], {"A": "ALL", "B": "ALL"}, {"ALL": 1.0}, mode="global_only")
    weights = pd.Series({"A": 0.5, "B": 0.5})
    cfg = BacktestConfig(window=20, strategies=("user_rebalanced",))
    baseline = run_backtest(prices, weights, cs, 0.0, cfg)
    prices["UNRELATED"] = np.nan
    with_extra = run_backtest(prices, weights, cs, 0.0, cfg)
    pd.testing.assert_frame_equal(with_extra.returns, baseline.returns)


def test_backtest_rejects_nonpositive_prices():
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = pd.DataFrame({"A": np.linspace(100.0, 120.0, len(dates)),
                           "B": np.linspace(100.0, 110.0, len(dates))}, index=dates)
    prices.iloc[20, 0] = 0.0
    cs = ConstraintSet.build(["A", "B"], {"A": "ALL", "B": "ALL"}, {"ALL": 1.0}, mode="global_only")
    with pytest.raises(ValueError, match="strictly positive"):
        run_backtest(prices, pd.Series({"A": 0.5, "B": 0.5}), cs, 0.0,
                     BacktestConfig(window=20, strategies=("user_rebalanced",)))



def test_short_portfolio_loss_beyond_nav_stops_backtest():
    dates = pd.bdate_range("2024-01-02", periods=80)
    prices = pd.DataFrame({"A": 100.0, "B": 100.0}, index=dates)
    prices.loc[dates[22]:, "B"] = 400.0
    cs = ConstraintSet.build(["A", "B"], {"A": "ALL", "B": "ALL"}, {"ALL": 1.0},
                             mode="global_only", long_only=False, min_weight=-1.0)
    weights = pd.Series({"A": 1.5, "B": -0.5})
    cfg = BacktestConfig(window=20, strategies=("user_rebalanced",), cost_bps=0.0, slippage_bps=0.0)
    with pytest.raises(RuntimeError, match="NAV became non-positive"):
        run_backtest(prices, weights, cs, 0.0, cfg)
