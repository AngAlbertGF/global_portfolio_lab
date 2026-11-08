"""Regression tests for defects found in the quantitative audit."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import src.optimization as optimization
from src.backtesting import BacktestConfig, run_backtest
from src.optimization import ConstraintSet, make_result, minimum_cvar, maximum_risk, risk_parity
from src.statistics import asset_statistics, check_covariance, cagr, max_drawdown, portfolio_statistics, port_stats


def test_asset_cagr_includes_the_period_before_first_return():
    idx = pd.bdate_range("2024-01-02", periods=2)
    returns = pd.DataFrame({"A": [0.10, 0.10]}, index=idx)
    weights = pd.Series({"A": 1.0})
    cov = pd.DataFrame([[0.04]], index=["A"], columns=["A"])
    mu = pd.Series({"A": 0.10})

    actual = asset_statistics(returns, weights, cov, mu, 0.0, 252, pd.DataFrame()).loc["A", "annual_cagr"]
    start = idx[0] - (idx[1] - idx[0])
    expected = cagr(1.0, 1.21, start, idx[-1])
    assert actual == pytest.approx(expected)


def test_max_drawdown_peak_date_can_be_initial_capital_date():
    idx = pd.bdate_range("2024-01-02", periods=2)
    r = pd.Series([-0.10, -0.10], index=idx)

    drawdown, peak, trough = max_drawdown(r)

    assert drawdown == pytest.approx(-0.19)
    assert peak == idx[0] - (idx[1] - idx[0])
    assert trough == idx[-1]


def test_benchmark_alpha_is_jensen_alpha_after_risk_free_adjustment():
    n = 252
    rf_annual = 0.06
    rf_period = (1.0 + rf_annual) ** (1.0 / n) - 1.0
    idx = pd.bdate_range("2024-01-02", periods=30)
    benchmark = pd.Series(np.linspace(-0.01, 0.015, len(idx)), index=idx)
    alpha_period, beta = 0.0003, 1.4
    portfolio = pd.Series(rf_period + alpha_period + beta * (benchmark - rf_period), index=idx)

    stats = portfolio_statistics(portfolio, rf_annual, n, benchmark)

    assert stats["beta"] == pytest.approx(beta)
    assert stats["alpha_annual_arith"] == pytest.approx(alpha_period * n)


def test_covariance_check_marks_asymmetric_matrix_unusable():
    covariance = pd.DataFrame([[1.0, 0.10], [0.30, 1.0]], index=["A", "B"], columns=["A", "B"])

    check = check_covariance(covariance, n_obs=100)

    assert check["psd"] is True  # symmetric part is positive definite
    assert check["symmetric"] is False


def test_portfolio_variance_is_not_clamped_to_zero_when_covariance_is_invalid():
    weights = np.array([1.0, 0.0])
    mu = np.array([0.10, 0.05])
    covariance = np.array([[-0.01, 0.0], [0.0, 0.04]])

    _, volatility, sharpe = port_stats(weights, mu, covariance, rf=0.0)

    assert np.isnan(volatility)
    assert sharpe is None


def test_risk_parity_solver_failure_is_not_reported_as_success(monkeypatch):
    tickers = ["A", "B"]
    cs = ConstraintSet.build(tickers, {"A": "M", "B": "M"}, {"M": 1.0})
    covariance = np.array([[0.04, 0.01], [0.01, 0.09]])

    def failed_minimize(_fun, x0, **_kwargs):
        return SimpleNamespace(x=np.asarray(x0), success=False, message="forced solver failure")

    monkeypatch.setattr(optimization, "minimize", failed_minimize)
    result = risk_parity(np.array([0.08, 0.10]), covariance, cs, rf=0.0)

    assert not result.ok
    assert not result.solver_success
    assert result.certification == "failed"
    assert any("fallback" in note.lower() for note in result.notes)


def test_maximum_risk_solver_failure_is_not_reported_as_success(monkeypatch):
    tickers = ["A", "B"]
    cs = ConstraintSet.build(tickers, {"A": "M", "B": "M"}, {"M": 1.0},
                             mode="global_only", long_only=False, min_weight=-0.10)
    covariance = np.array([[0.04, 0.01], [0.01, 0.09]])

    def failed_minimize(_fun, x0, **_kwargs):
        return SimpleNamespace(x=np.asarray(x0), success=False, message="forced solver failure")

    monkeypatch.setattr(optimization, "minimize", failed_minimize)
    result = maximum_risk(np.array([0.08, 0.10]), covariance, cs, rf=0.0, n_starts=3)

    assert not result.ok
    assert not result.solver_success
    assert result.certification == "failed"


@pytest.mark.parametrize("level", [0.0, 1.0, -0.1, 1.1, np.nan])
def test_minimum_cvar_rejects_invalid_confidence_levels(level):
    cs = ConstraintSet.build(["A", "B"], {"A": "M", "B": "M"}, {"M": 1.0})
    scenarios = np.zeros((5, 2))

    with pytest.raises(ValueError, match="confidence level"):
        minimum_cvar(scenarios, np.zeros(2), np.eye(2), cs, 0.0, level=level)


def test_walk_forward_backtest_charges_one_way_turnover_not_gross_two_sided():
    idx = pd.bdate_range("2024-01-01", periods=120)
    prices = pd.DataFrame({
        "A": 100.0 * (1.01 ** np.arange(len(idx))),
        "B": np.full(len(idx), 100.0),
    }, index=idx)
    tickers = ["A", "B"]
    cs = ConstraintSet.build(tickers, {"A": "M", "B": "M"}, {"M": 1.0}, mode="global_only")
    target = np.array([0.5, 0.5])
    cfg = BacktestConfig(window=20, rebalance="monthly", cost_bps=100.0, slippage_bps=0.0,
                         strategies=("user_rebalanced",), periods_per_year=252)

    result = run_backtest(prices, pd.Series(target, index=tickers), cs, rf_annual=0.0, cfg=cfg)

    rets = (prices / prices.shift(1) - 1.0).iloc[1:]
    period_end = rets.index.to_series().resample("ME").last().dropna()
    positions = rets.index.get_indexer(pd.DatetimeIndex(period_end.values))
    decisions = sorted({p + 1 for p in positions if cfg.window <= p + 1 < len(rets)})
    assert len(decisions) >= 2
    first_pos, second_pos = decisions[:2]
    holdings_before_second = target * np.prod(1.0 + rets.iloc[first_pos:second_pos].values, axis=0)
    drifted = holdings_before_second / holdings_before_second.sum()
    expected_one_way = 0.5 * np.abs(target - drifted).sum()
    second_date = rets.index[second_pos]

    assert result.turnover.loc[second_date, "user_rebalanced"] == pytest.approx(expected_one_way)
