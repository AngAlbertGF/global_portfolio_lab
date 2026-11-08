"""Predictive backtesting lab: no look-ahead, exact money accounting, forecasts and what-if helpers."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest_lab import (STRATEGIES, LabConfig, contribution_flows, decision_dates, entry_date_sensitivity,
                              forecast_paths, fx_shock_returns, kupiec, renormalized_without, replay, run_lab, xirr)
from src.optimization import ConstraintSet
from src.synthetic import demo_portfolio
from src.validation import global_weights


@pytest.fixture(scope="module")
def setup(demo_bundle):
    p = demo_portfolio()
    mkt = {h.ticker: h.market_id for h in p.holdings}
    cs = ConstraintSet.build(p.tickers, mkt, {m: a / 100 for m, a in p.market_allocations.items()})
    prices = demo_bundle.prices_base[p.tickers].dropna(how="any")
    return p, cs, prices


def _cfg(**kw):
    base = dict(train_start=date(2022, 6, 1), train_end=date(2025, 12, 31), test_start=date(2026, 1, 1),
                test_end=date(2026, 10, 23), strategies=("user", "min_variance", "max_sharpe", "risk_parity"),
                capital=1_000_000.0, contribution=10_000.0, rebalance="monthly", n_paths=400)
    base.update(kw)
    return LabConfig(**base)


def test_money_accounting_is_exact(setup):
    p, cs, prices = setup
    res = run_lab(prices, global_weights(p), cs, _cfg(), {tk: not tk.endswith(".MX") for tk in p.tickers})
    assert all(r.ok for r in res.runs.values())
    n_months = len(set(res.test_returns.index.to_period("M")))
    for r in res.runs.values():
        z = r.realized
        assert z["invested"] == pytest.approx(1_000_000 + 10_000 * (n_months - 1))
        # final value = money invested + what every security made - costs
        assert z["final_value"] == pytest.approx(z["invested"] + r.contrib_money.sum() - z["costs"], rel=1e-9)
        assert z["costs"] > 0 and 0 <= r.forecast["realized_percentile"] <= 1
        assert 0 <= r.forecast["kupiec_p"] <= 1
        assert r.weights_path.sum(axis=1).round(9).eq(1).all()


def test_no_look_ahead_in_training_and_forecast(setup):
    p, cs, prices = setup
    cfg = _cfg(contribution=0.0)
    a = run_lab(prices, global_weights(p), cs, cfg)
    future = prices.copy()
    future.loc[future.index > "2025-12-31"] *= np.linspace(1, 3, (future.index > "2025-12-31").sum())[:, None]
    b = run_lab(future, global_weights(p), cs, cfg)
    for k in a.runs:
        assert np.allclose(a.runs[k].train_weights.values, b.runs[k].train_weights.values, atol=1e-9)
        assert np.allclose(a.runs[k].forecast["bands"].values, b.runs[k].forecast["bands"].values)
        assert a.runs[k].realized["final_value"] != pytest.approx(b.runs[k].realized["final_value"])


def test_walk_forward_uses_only_past_data(setup):
    p, cs, prices = setup
    cfg = _cfg(mode="walk_forward", strategies=("min_variance",), contribution=0.0)
    a = run_lab(prices, global_weights(p), cs, cfg)
    d = a.runs["min_variance"].decisions.index
    assert len(d) >= 9                                 # first day + monthly decisions
    cut = prices.loc[:d[3]]                            # data up to the 4th decision date only
    b = run_lab(cut, global_weights(p), cs, _cfg(mode="walk_forward", strategies=("min_variance",),
                                                 contribution=0.0, test_end=d[3].date()))
    assert np.allclose(a.runs["min_variance"].decisions.loc[d[3]].values,
                       b.runs["min_variance"].decisions.loc[d[3]].values, atol=1e-6)


def test_buy_and_hold_lets_weights_drift(setup):
    p, cs, prices = setup
    res = run_lab(prices, global_weights(p), cs, _cfg(rebalance="none", strategies=("user",), contribution=0.0))
    w = res.runs["user"].weights_path
    assert len(res.runs["user"].decisions) == 1 and not np.allclose(w.iloc[0].values, w.iloc[-1].values)


def test_all_strategies_run(setup):
    p, cs, prices = setup
    res = run_lab(prices, global_weights(p), cs, _cfg(strategies=tuple(STRATEGIES), contribution=0.0))
    assert {k for k, r in res.runs.items() if r.ok} == set(STRATEGIES)
    for r in res.runs.values():
        assert cs.is_feasible(r.train_weights.values, tol=1e-6)


def test_helpers():
    idx = pd.bdate_range("2026-01-01", "2026-03-31")
    fl = contribution_flows(idx, 500.0)
    assert fl.sum() == 1000.0 and fl.loc["2026-02-02"] == 500.0 and fl.iloc[0] == 0
    assert decision_dates(idx, "monthly")[:3] == [idx[0], pd.Timestamp("2026-02-02"), pd.Timestamp("2026-03-02")]
    assert xirr([pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-01")], [-100, 110]) == pytest.approx(0.1, abs=2e-3)
    assert kupiec(5, 100) > 0.9 and kupiec(20, 100) < 0.01
    R = pd.DataFrame({"A": [0.01, 0.02], "B": [0.0, 0.0]}, index=idx[:2])
    sh = fx_shock_returns(R, {"A": True, "B": False}, -0.10)
    assert np.prod(1 + sh["A"]) / np.prod(1 + R["A"]) == pytest.approx(0.9) and sh["B"].eq(0).all()
    assert replay(R, np.array([1.0, 0.0]), 100.0).iloc[-1] == pytest.approx(100 * 1.01 * 1.02)
    w = pd.Series({"A": 0.3, "B": 0.2, "C": 0.5})
    out = renormalized_without(w, {"A": "X", "B": "X", "C": "Y"}, ["B"])
    assert out.sum() == pytest.approx(1.0) and out["A"] == pytest.approx(0.5) and out["B"] == 0
    paths = forecast_paths(np.zeros(50), 0.0, 0.0, 10, 1000.0, np.r_[0, 0, 0, 0, 0, 100, 0, 0, 0, 0], "normal", 5, 5, 1)
    assert np.allclose(paths[:, -1], 1100.0)
    ed = entry_date_sensitivity(pd.DataFrame({"A": 0.001}, index=idx), {"x": np.array([1.0])}, 100.0)
    assert len(ed) == 3 and ed["x"].is_monotonic_decreasing



def test_missing_benchmark_returns_are_not_filled_with_zero(setup):
    p, cs, prices = setup
    cfg = _cfg(strategies=("user",), contribution=0.0)
    complete = run_lab(prices, global_weights(p), cs, cfg, benchmark_prices=prices.iloc[:, 0])
    assert complete.benchmark is not None

    incomplete_benchmark = prices.iloc[:, 0].copy()
    missing_date = prices.loc[prices.index >= "2026-01-01"].index[5]
    incomplete_benchmark.loc[missing_date] = np.nan
    incomplete = run_lab(prices, global_weights(p), cs, cfg, benchmark_prices=incomplete_benchmark)
    assert incomplete.benchmark is None
    assert any("Benchmark omitted" in note for note in incomplete.notes)



def test_backtest_annualization_uses_actual_pre_test_price_date(setup):
    p, cs, prices = setup
    cfg = _cfg(strategies=("user",), contribution=0.0)
    res = run_lab(prices, global_weights(p), cs, cfg)
    first_test_return_date = res.test_returns.index[0]
    first_pos = prices.index.get_loc(first_test_return_date)
    assert first_pos > 0
    actual_start = prices.index[first_pos - 1]
    expected_years = (res.test_returns.index[-1] - actual_start).days / 365.25
    assert res.runs["user"].realized["years"] == pytest.approx(expected_years)
