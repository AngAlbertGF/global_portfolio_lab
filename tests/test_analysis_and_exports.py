"""Horizon logic, overlapping histories, and export consistency."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.analysis import run_analysis
from src.config import AppSettings, load_markets
from src.reporting import build_tables, config_snapshot, html_report, pdf_report, to_csv_zip_bytes, to_excel_bytes
from src.synthetic import demo_portfolio


def test_every_horizon_reports_dates_and_status(demo_bundle):
    assert set(demo_bundle.horizons) == {1, 3, 5, 10, 15}
    for h, r in demo_bundle.horizons.items():
        assert r.status in {"COMPLETE", "INCOMPLETE"}
        if r.analyzable:
            assert r.start is not None and r.end is not None and r.n_obs == len(r.returns)
            assert r.returns.index.min() == r.start


def test_overlapping_history_marks_long_horizons_incomplete(demo_bundle):
    # DEMO-US3 is listed in 2022: 1y and 3y complete, 5y+ incomplete in strict mode; nothing extrapolated
    assert demo_bundle.horizons[1].status == "COMPLETE"
    assert demo_bundle.horizons[3].status == "COMPLETE"
    for h in (5, 10, 15):
        r = demo_bundle.horizons[h]
        assert r.status == "INCOMPLETE" and "DEMO-US3" in r.excluded and not r.user_stats


def test_common_universe_and_available_history_are_labelled(demo_env):
    db, s = demo_env
    s1 = AppSettings(**{**s.to_dict(), "analysis_mode": "common_universe"})
    b = run_analysis(db, demo_portfolio(), s1, load_markets())
    r = b.horizons[10]
    assert r.status == "COMPLETE" and "DEMO-US3" not in r.universe and "DEMO-US3" in r.excluded
    assert sum(r.market_budgets.values()) == pytest.approx(1.0)
    assert any("COMMON-UNIVERSE" in w for w in r.warnings)
    s2 = AppSettings(**{**s.to_dict(), "analysis_mode": "available_history"})
    r2 = run_analysis(db, demo_portfolio(), s2, load_markets()).horizons[15]
    assert r2.status == "COMPLETE" and r2.actual_years < 5 and any("AVAILABLE-HISTORY" in w for w in r2.warnings)


def test_minimum_observation_requirement(demo_env):
    db, s = demo_env
    s3 = AppSettings(**{**s.to_dict(), "min_observations": 5000})
    b = run_analysis(db, demo_portfolio(), s3, load_markets())
    assert b.horizons[1].status == "INSUFFICIENT_OBSERVATIONS"


def test_fixed_market_constraints_hold_in_analysis(demo_bundle):
    r = demo_bundle.horizons[3]
    for k, o in r.optimized.items():
        assert o.ok, k
        sums = o.weights.groupby(lambda t: r.constraints.market_of[t]).sum()
        for m, b in r.market_budgets.items():
            assert sums[m] == pytest.approx(b, abs=1e-8)


def test_portfolio_returns_consistent_with_quadratic_form(demo_bundle):
    r = demo_bundle.horizons[3]
    w = r.weights_user.values
    assert r.user_stats["annual_volatility"] ** 2 == pytest.approx(w @ r.cov.values @ w, rel=1e-10)
    assert r.optimized["user"].expected_return == pytest.approx(r.user_stats["annual_arithmetic_return"], rel=1e-10)


def test_exports_match_displayed_values(demo_bundle, demo_env):
    db, _ = demo_env
    tables = build_tables(demo_bundle, db)
    cfg = config_snapshot(demo_bundle)
    xlsx = to_excel_bytes(tables, cfg)
    stats = pd.read_excel(io.BytesIO(xlsx), sheet_name="h3y_user_stats").set_index("statistic")["value"]
    assert float(stats["sharpe_annual"]) == pytest.approx(demo_bundle.horizons[3].user_stats["sharpe_annual"])
    opt = pd.read_excel(io.BytesIO(xlsx), sheet_name="h3y_optimized_weights").set_index("ticker")
    assert np.allclose(opt["Maximum Sharpe"].values,
                       demo_bundle.horizons[3].optimized["max_sharpe"].weights.reindex(opt.index).values)
    with zipfile.ZipFile(io.BytesIO(to_csv_zip_bytes(tables, cfg))) as z:
        names = z.namelist()
        assert "analysis_configuration.json" in names and "h3y_frontier_points.csv" in names
        assert "returns_base_ccy_common.csv" in names and "download_log.csv" in names
    html = html_report(demo_bundle, 3)
    assert "Executive summary" in html and "Limitations and conclusions" in html
    assert pdf_report(demo_bundle, 3)[:4] == b"%PDF"
    assert "risk_free_annual" in cfg and "data_cutoff" in cfg


def test_backtest_no_lookahead(demo_bundle):
    from src.backtesting import BacktestConfig, run_backtest
    r = demo_bundle.horizons[3]
    prices = demo_bundle.prices_base.dropna(how="any")
    cfg = BacktestConfig(window=126, rebalance="quarterly", strategies=("user_rebalanced", "min_variance"))
    bt = run_backtest(prices, r.weights_user, r.constraints, 0.065, cfg)
    assert not bt.returns.empty and list(bt.returns.columns) == ["user_rebalanced", "min_variance"]
    # decision weights computed on data strictly before the decision date: truncating the future must not
    # change the first rebalance weights
    first = bt.weights_at_rebalance["min_variance"].index[0]
    cut = prices.loc[:first]
    bt2 = run_backtest(cut, r.weights_user, r.constraints, 0.065, cfg)
    if not bt2.returns.empty:
        assert np.allclose(bt2.weights_at_rebalance["min_variance"].loc[first].values,
                           bt.weights_at_rebalance["min_variance"].loc[first].values, atol=1e-6)


def test_html_report_stays_light_while_screen_is_dark(demo_bundle):
    from src import charts
    charts.set_dark(True)
    try:
        html = html_report(demo_bundle, 3)
        assert charts.is_dark()                          # screen mode restored after the export
    finally:
        charts.set_dark(False)
    assert charts.TOKENS["light"]["ink"] in html
    assert charts.TOKENS["dark"]["surface"] not in html
