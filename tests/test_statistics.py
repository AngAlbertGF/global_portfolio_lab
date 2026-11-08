import numpy as np
import pandas as pd
import pytest

from src.statistics import asset_statistics, block_bootstrap_ci, check_covariance, cov_to_corr, estimate_cov, estimate_mu, \
    ewma_weights, historical_var_cvar, ledoit_wolf, max_drawdown, portfolio_statistics, rf_markowitz, rf_per_period, \
    risk_decomposition
from tests.conftest import returns_frame


def test_covariance_and_portfolio_variance_quadratic_form():
    R = returns_frame()
    cov, info = estimate_cov(R, "sample", 252)
    assert np.allclose(cov.values, R.cov().values * 252)
    w = np.array([0.1, 0.2, 0.3, 0.25, 0.15])
    rp = R.values @ w
    assert w @ cov.values @ w == pytest.approx(np.var(rp, ddof=1) * 252, rel=1e-10)
    assert np.sqrt(w @ cov.values @ w) == pytest.approx(np.std(rp, ddof=1) * np.sqrt(252), rel=1e-10)


def test_sharpe_consistency_between_history_and_markowitz():
    R = returns_frame()
    w = pd.Series([0.2] * 5, index=R.columns)
    r = R @ w
    stats = portfolio_statistics(r, 0.065, 252)
    rf_d = (1.065) ** (1 / 252) - 1
    manual = (r.mean() - rf_d) / r.std(ddof=1) * np.sqrt(252)
    assert stats["sharpe_annual"] == pytest.approx(manual)
    mu = estimate_mu(R, "arithmetic", 252)
    cov, _ = estimate_cov(R, "sample", 252)
    sr_mk = (w @ mu - rf_markowitz(0.065, 252)) / np.sqrt(w @ cov @ w)
    assert sr_mk == pytest.approx(manual, rel=1e-10)
    assert rf_per_period(0.065, 252) == pytest.approx(rf_d)


def test_ledoit_wolf_matches_sklearn():
    sk = pytest.importorskip("sklearn.covariance")
    X = returns_frame(T=300, n=8).values
    S, delta = ledoit_wolf(X)
    ref = sk.LedoitWolf().fit(X)
    assert delta == pytest.approx(ref.shrinkage_, rel=1e-8)
    assert np.allclose(S, ref.covariance_, rtol=1e-8)


def test_estimators_shapes_and_psd():
    R = returns_frame()
    for m in ("arithmetic", "geometric", "ewma"):
        assert estimate_mu(R, m, 252).shape == (5,)
    for c in ("sample", "ledoit_wolf", "ewma"):
        cov, info = estimate_cov(R, c, 252)
        assert check_covariance(cov, len(R))["psd"]
    with pytest.raises(ValueError):
        estimate_mu(R, "user", 252, user={"A0": 0.1})


def test_singular_covariance_detected():
    R = returns_frame(T=4, n=6)
    cov, _ = estimate_cov(R, "sample", 252)
    chk = check_covariance(cov, 4)
    assert any("singular" in w for w in chk["warnings"])


def test_drawdown_var_cvar_known_values():
    r = pd.Series([0.10, -0.50, 0.20, 0.0], index=pd.bdate_range("2024-01-01", periods=4))
    mdd, peak, trough = max_drawdown(r)
    assert mdd == pytest.approx(-0.5)
    x = pd.Series(np.arange(1, 101) / 100 - 0.5)  # -0.49..0.50
    var, cvar = historical_var_cvar(x, 0.95)
    assert var == pytest.approx(-np.quantile(x, 0.05))
    assert cvar >= var


def test_euler_decomposition_sums_to_volatility():
    R = returns_frame()
    cov, _ = estimate_cov(R, "sample", 252)
    w = pd.Series([0.1, 0.2, 0.3, 0.25, 0.15], index=R.columns)
    rd = risk_decomposition(w, cov)
    sigma = np.sqrt(w.values @ cov.values @ w.values)
    assert rd["component_vol_contribution"].sum() == pytest.approx(sigma)
    assert rd["variance_contribution_pct"].sum() == pytest.approx(1.0)
    assert np.allclose(np.diag(cov_to_corr(cov)), 1.0)


def test_synthetic_dataset_reproduces_known_statistics():
    rng = np.random.default_rng(42)
    mu_d, sd_d = 0.0004, 0.01
    r = pd.Series(rng.normal(mu_d, sd_d, 200_000), index=pd.bdate_range("1900-01-01", periods=200_000))
    s = portfolio_statistics(r, 0.0, 252)
    assert s["annual_arithmetic_return"] == pytest.approx(mu_d * 252, abs=3 * sd_d * 252 / np.sqrt(200_000))
    assert s["annual_volatility"] == pytest.approx(sd_d * np.sqrt(252), rel=0.01)
    assert abs(s["skewness"]) < 0.03 and abs(s["excess_kurtosis"]) < 0.06
    assert s["var_95"] == pytest.approx(-(mu_d - 1.6449 * sd_d), rel=0.02)


def test_bootstrap_ci_contains_point_estimate():
    R = returns_frame(T=800)
    ci = block_bootstrap_ci(R.mean(axis=1), 0.05, 252, n_boot=200)
    assert (ci["ci_low"] <= ci["estimate"]).all() and (ci["estimate"] <= ci["ci_high"]).all()



def test_estimator_inputs_fail_fast():
    with pytest.raises(ValueError):
        rf_per_period(-1.0, 252)
    with pytest.raises(ValueError):
        rf_per_period(0.05, 0)
    with pytest.raises(ValueError):
        ewma_weights(0, 0.97)
    with pytest.raises(ValueError):
        ewma_weights(10, 1.01)
    with pytest.raises(ValueError):
        estimate_cov(pd.DataFrame({"A": [0.01, np.nan]}), "sample", 252)
    with pytest.raises(ValueError):
        estimate_mu(pd.DataFrame({"A": []}), "arithmetic", 252)
    with pytest.raises(ValueError):
        historical_var_cvar(pd.Series([0.01, -0.01]), 1.0)


def test_asset_cagr_counts_the_first_return_interval():
    idx = pd.bdate_range("2024-01-02", periods=3)
    returns = pd.DataFrame({"A": [0.10, 0.10, 0.10]}, index=idx)
    weights = pd.Series({"A": 1.0})
    cov = pd.DataFrame([[0.01]], index=["A"], columns=["A"])
    mu = pd.Series({"A": 0.10})
    meta = pd.DataFrame(index=["A"])
    got = asset_statistics(returns, weights, cov, mu, 0.0, 252, meta).loc["A", "annual_cagr"]
    start = idx[0] - (idx[1] - idx[0])
    expected = (1.1 ** 3) ** (365.25 / (idx[-1] - start).days) - 1
    assert got == pytest.approx(expected)



def test_cagr_uses_actual_pre_sample_price_date_for_irregular_intervals():
    idx = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-15"])
    period_start = pd.Timestamp("2024-01-05")
    r = pd.Series([0.10, 0.10, 0.10], index=idx)
    stats = portfolio_statistics(r, 0.0, 252, period_start=period_start)
    expected = (1.1 ** 3) ** (365.25 / (idx[-1] - period_start).days) - 1
    assert stats["annual_geometric_return_cagr"] == pytest.approx(expected)

    returns = pd.DataFrame({"A": r})
    weights = pd.Series({"A": 1.0})
    cov = pd.DataFrame([[0.01]], index=["A"], columns=["A"])
    mu = pd.Series({"A": 0.10})
    got = asset_statistics(returns, weights, cov, mu, 0.0, 252,
                           pd.DataFrame(index=["A"]), period_start=period_start).loc["A", "annual_cagr"]
    assert got == pytest.approx(expected)


def test_covariance_and_bootstrap_reject_invalid_annualization_and_blocks():
    with pytest.raises(ValueError, match="periods_per_year"):
        estimate_cov(pd.DataFrame({"A": [0.01, -0.01]}), "sample", 0)
    with pytest.raises(ValueError, match="block"):
        block_bootstrap_ci(pd.Series([0.01, -0.01, 0.02]), 0.05, 252, block=0)



def test_user_expected_returns_reject_nonfinite_values():
    returns = pd.DataFrame({"A": [0.01, -0.01], "B": [0.02, -0.02]})
    with pytest.raises(ValueError, match="finite numeric"):
        estimate_mu(returns, "user", 252, user={"A": 0.05, "B": np.inf})
    with pytest.raises(ValueError, match="square, and finite"):
        check_covariance(pd.DataFrame([[0.1, 0.0], [0.0, np.nan]]), 100)



def test_max_drawdown_does_not_mislabel_initial_peak_date():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    r = pd.Series([-0.20, 0.10], index=idx)
    mdd, peak, trough = max_drawdown(r)
    assert mdd == pytest.approx(-0.20)
    assert peak is None  # the NAV=1 peak occurred before the first observed return date
    assert trough == idx[0]
