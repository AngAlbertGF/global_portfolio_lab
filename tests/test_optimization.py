import itertools

import numpy as np
import pandas as pd
import pytest

from src.frontier import build_frontier
from src.optimization import ConstraintSet, equal_weight, maximum_diversification, maximum_return, maximum_risk, \
    maximum_sharpe, minimum_cvar, minimum_variance, port_stats, risk_parity, run_all, target_volatility
from tests.conftest import random_cov, returns_frame

TICKERS = ["U1", "U2", "U3", "M1", "M2", "J1", "J2"]
MARKET = {"U1": "USA", "U2": "USA", "U3": "USA", "M1": "MEX", "M2": "MEX", "J1": "JPN", "J2": "JPN"}
BUDGET = {"USA": 0.5, "MEX": 0.3, "JPN": 0.2}


@pytest.fixture
def problem():
    rng = np.random.default_rng(5)
    mu = rng.uniform(0.02, 0.20, len(TICKERS))
    S = random_cov(len(TICKERS), 5)
    cs = ConstraintSet.build(TICKERS, MARKET, BUDGET)
    return mu, S, cs, 0.03


def random_feasible(cs, k=300, seed=0):
    rng = np.random.default_rng(seed)
    return [cs.feasible_start(rng) for _ in range(k)]


def assert_valid(res, cs):
    assert res.ok, res.status
    w = res.weights.values
    assert abs(w.sum() - 1) < 1e-8
    assert w.min() >= cs.lb.min() - 1e-9
    if cs.mode == "fixed_markets":
        for m, g in cs.groups.items():
            assert abs(w[g].sum() - cs.market_budgets[m]) < 1e-8


def test_min_variance_invariants(problem):
    mu, S, cs, rf = problem
    res = minimum_variance(mu, S, cs, rf)
    assert_valid(res, cs)
    v = res.volatility ** 2
    assert res.weights.values @ S @ res.weights.values == pytest.approx(v)
    for w in random_feasible(cs):
        assert v <= w @ S @ w + 1e-10


def test_min_variance_matches_closed_form_when_unconstrained():
    S = random_cov(4, 9)
    cs = ConstraintSet.build(list("ABCD"), dict(zip("ABCD", "XXXX")), {"X": 1.0}, "global_only", long_only=False,
                             min_weight=-10)
    res = minimum_variance(np.zeros(4), S, cs, 0.0)
    inv = np.linalg.solve(S, np.ones(4))
    assert np.allclose(res.weights.values, inv / inv.sum(), atol=1e-6)


def test_max_sharpe_beats_feasible_portfolios(problem):
    mu, S, cs, rf = problem
    res = maximum_sharpe(mu, S, cs, rf)
    assert_valid(res, cs)
    assert res.certification.startswith("global")
    for w in random_feasible(cs, seed=1):
        _, _, sr = port_stats(w, mu, S, rf)
        assert sr <= res.sharpe + 1e-7


def test_max_return_concentrates_per_market(problem):
    mu, S, cs, rf = problem
    res = maximum_return(mu, S, cs, rf)
    assert_valid(res, cs)
    expected = sum(BUDGET[m] * mu[g].max() for m, g in cs.groups.items())
    assert res.expected_return == pytest.approx(expected)
    capped = ConstraintSet.build(TICKERS, MARKET, BUDGET, max_weight=0.25)
    res2 = maximum_return(mu, S, capped, rf)
    assert_valid(res2, capped) and res2.weights.max() <= 0.25 + 1e-9


def test_max_risk_exact_by_enumeration(problem):
    mu, S, cs, rf = problem
    res = maximum_risk(mu, S, cs, rf)
    assert_valid(res, cs)
    assert res.certification.startswith("exact")
    best = 0
    for combo in itertools.product(*[cs.groups[m] for m in cs.markets]):
        w = np.zeros(len(TICKERS))
        for i, m in zip(combo, cs.markets):
            w[i] = BUDGET[m]
        best = max(best, w @ S @ w)
    assert res.volatility ** 2 == pytest.approx(best)
    for w in random_feasible(cs, seed=2):
        assert w @ S @ w <= best + 1e-12


def test_max_risk_with_caps_is_labelled_approximate(problem):
    mu, S, _, rf = problem
    cs = ConstraintSet.build(TICKERS, MARKET, BUDGET, max_weight=0.3)
    res = maximum_risk(mu, S, cs, rf, n_starts=10)
    assert_valid(res, cs)
    assert "approximate" in res.certification


def test_infeasible_caps_detected(problem):
    mu, S, _, rf = problem
    cs = ConstraintSet.build(TICKERS, MARKET, BUDGET, max_weight=0.1)  # USA 3 x 10% < 50%
    res = minimum_variance(mu, S, cs, rf)
    assert not res.ok and res.certification == "infeasible"


def test_global_only_mode_moves_market_budgets(problem):
    mu, S, _, rf = problem
    cs = ConstraintSet.build(TICKERS, MARKET, BUDGET, "global_only")
    res = maximum_return(mu, S, cs, rf)
    assert res.ok and res.expected_return == pytest.approx(mu.max())
    fixed = maximum_return(mu, S, ConstraintSet.build(TICKERS, MARKET, BUDGET), rf)
    assert res.expected_return >= fixed.expected_return


def test_short_selling_mode_respects_bounds(problem):
    mu, S, _, rf = problem
    cs = ConstraintSet.build(TICKERS, MARKET, BUDGET, long_only=False, min_weight=-0.1)
    res = maximum_sharpe(mu, S, cs, rf)
    assert_valid(res, cs)
    assert res.weights.min() >= -0.1 - 1e-8
    lo = maximum_sharpe(mu, S, ConstraintSet.build(TICKERS, MARKET, BUDGET), rf)
    assert res.sharpe >= lo.sharpe - 1e-7  # larger feasible set cannot reduce the optimum


def test_frontier_feasibility_and_ordering(problem):
    mu, S, cs, rf = problem
    fr = build_frontier(pd.Series(mu, index=TICKERS), pd.DataFrame(S, index=TICKERS, columns=TICKERS), cs, rf, 30)
    assert fr.points["ok"].all()
    for t, w in fr.weights.iterrows():
        assert cs.is_feasible(w.values)
        assert w.values @ mu == pytest.approx(t, abs=1e-6)
    assert fr.r_min <= fr.gmv.expected_return <= fr.r_max
    eff = fr.efficient
    assert np.all(np.diff(eff["volatility"].values) >= -1e-7)
    assert eff["volatility"].min() >= fr.gmv.volatility - 1e-9
    assert fr.efficient["expected_return"].min() >= fr.gmv.expected_return - 1e-9


def test_run_all_constraint_residuals_and_equal_weight(problem):
    mu, S, cs, rf = problem
    user = pd.Series(np.zeros(len(TICKERS)), index=TICKERS)
    for m, g in cs.groups.items():
        user.iloc[g] = BUDGET[m] / len(g)
    R = returns_frame(n=len(TICKERS))
    R.columns = TICKERS
    out = run_all(pd.Series(mu, index=TICKERS), pd.DataFrame(S, index=TICKERS, columns=TICKERS), cs, rf, user, R)
    for k, res in out.items():
        assert_valid(res, cs)
        assert res.residuals["market_max_abs"] < 1e-8
    ew = equal_weight(mu, S, cs, rf)
    assert np.allclose(ew.weights.values, user.values)
    assert out["min_variance"].volatility <= min(r.volatility for r in out.values()) + 1e-9


def test_min_cvar_and_diversification_and_target_vol(problem):
    mu, S, cs, rf = problem
    R = returns_frame(T=500, n=len(TICKERS)).values
    cv = minimum_cvar(R, mu, S, cs, rf)
    assert_valid(cv, cs)
    def cvar(w):
        loss = -(R @ w)
        q = np.quantile(loss, 0.95)
        return loss[loss >= q].mean()
    for w in random_feasible(cs, k=100, seed=3):
        assert cvar(cv.weights.values) <= cvar(w) + 2e-3  # LP optimum vs discrete tail estimator
    md = maximum_diversification(mu, S, cs, rf)
    assert_valid(md, cs)
    gmv = minimum_variance(mu, S, cs, rf)
    tv = target_volatility(mu, S, cs, rf, gmv.volatility * 1.2, gmv.volatility)
    assert_valid(tv, cs) and tv.volatility <= gmv.volatility * 1.2 + 1e-6
    assert not target_volatility(mu, S, cs, rf, gmv.volatility * 0.5, gmv.volatility).ok


def test_max_sharpe_when_no_portfolio_beats_rf(problem):
    _, S, cs, _ = problem
    mu = np.full(len(TICKERS), 0.01)
    mu[0] = 0.02
    res = maximum_sharpe(mu, S, cs, rf=0.10)
    assert res.ok and "approximate" in res.certification and res.sharpe < 0



def test_risk_parity_equalizes_percentage_variance_contributions():
    tickers = ["A", "B", "C"]
    market = {ticker: "ALL" for ticker in tickers}
    cs = ConstraintSet.build(tickers, market, {"ALL": 1.0}, mode="global_only")
    cov = np.diag([0.01, 0.04, 0.09])
    mu = np.array([0.05, 0.06, 0.07])
    res = risk_parity(mu, cov, cs, rf=0.02)
    assert_valid(res, cs)
    w = res.weights.values
    rc = w * (cov @ w)
    shares = rc / (w @ cov @ w)
    assert shares == pytest.approx(np.full(3, 1 / 3), abs=1e-6)
    assert w == pytest.approx(np.array([6, 3, 2]) / 11, abs=1e-6)


def test_risk_parity_does_not_report_fallback_as_optimisation_success(problem, monkeypatch):
    import src.optimization as optimisation
    from types import SimpleNamespace

    mu, cov, cs, rf = problem

    def forced_failure(fun, x0, **kwargs):
        return SimpleNamespace(success=False, x=np.asarray(x0), message="forced failure")

    monkeypatch.setattr(optimisation, "minimize", forced_failure)
    res = optimisation.risk_parity(mu, cov, cs, rf)
    assert not res.ok
    assert not res.solver_success
    assert res.certification == "failed"
    assert any("fallback" in note.lower() for note in res.notes)
