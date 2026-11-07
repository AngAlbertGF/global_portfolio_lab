"""Reconstructed history for recently listed holdings (IPOs)."""
import numpy as np
import pandas as pd

from src.analysis import incomplete_reasons, run_analysis
from src.backfill import reconstruct, reconstruct_frame
from src.config import AppSettings, database_path, load_markets, save_settings
from src.database import Database
from src.synthetic import build_demo_database, demo_portfolio
from tests.conftest import FIXED_NOW
from tests.test_app_ui import _app


def _factor_data(n=1000, beta=1.2, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    f = pd.Series(rng.normal(0.0005, 0.01, n), index=idx, name="F")
    y = 0.0001 + beta * (f - 0.0001) + rng.normal(0, 0.015, n)
    return idx, f, pd.Series(y, index=idx, name="IPO")


def test_reconstruct_keeps_real_values_and_adds_no_return():
    idx, f, y_true = _factor_data()
    y = y_true.copy()
    y.iloc[:700] = np.nan                                  # listed 300 periods before the end
    F = f.to_frame()
    rf = 0.0001
    out, rec = reconstruct(y, F, rf, 252, salt="t")
    assert out.iloc[700:].equals(y_true.iloc[700:])        # real returns untouched
    assert out.notna().all() and rec.n_filled == 700 and rec.n_real == 300
    assert abs(rec.betas["F"] - 1.2) < 0.15 and rec.r2 > 0.2
    implied = rf + rec.betas["F"] * (f.iloc[:700] - rf)
    assert abs(out.iloc[:700].mean() - implied.mean()) < 1e-12   # residuals add risk, never return
    resid_sd = (out.iloc[:700] - implied).std()
    assert 0.8 < resid_sd / 0.015 < 1.2                    # own risk preserved
    out2, _ = reconstruct(y, F, rf, 252, salt="t")
    assert out2.equals(out)                                # reproducible


def test_fit_mask_never_uses_later_data():
    idx, f, y_true = _factor_data(seed=5)
    y = y_true.copy()
    y.iloc[:600] = np.nan
    rets = pd.DataFrame({"IPO": y, "L1": f})
    fit = pd.Series(idx <= idx[699], index=idx)            # training ends 100 periods after listing
    out_a, info_a = reconstruct_frame(rets, ["IPO"], ["L1"], {"IPO": "X", "L1": "X"}, pd.Series({"L1": 1.0}),
                                      0.0, 252, fit_mask=fit)
    rets_b = rets.copy()
    rets_b.loc[idx[700]:, "IPO"] = rets_b.loc[idx[700]:, "IPO"] * 5 + 0.05   # change the "future"
    out_b, info_b = reconstruct_frame(rets_b, ["IPO"], ["L1"], {"IPO": "X", "L1": "X"}, pd.Series({"L1": 1.0}),
                                      0.0, 252, fit_mask=fit)
    assert info_a["IPO"].n_real == 100
    assert out_a["IPO"].iloc[:600].equals(out_b["IPO"].iloc[:600])


def test_reconstructed_mode_completes_horizons_and_leaves_others_unchanged(demo_env):
    database, s0 = demo_env
    p = demo_portfolio()
    mk = load_markets()
    s = AppSettings(**{**s0.to_dict(), "analysis_mode": "strict", "cov_estimator": "sample"})
    strict = run_analysis(database, p, s, mk, (10,)).horizons[10]
    assert strict.status == "INCOMPLETE" and strict.excluded == ["DEMO-US3"]
    s.analysis_mode = "reconstructed"
    rec = run_analysis(database, p, s, mk, (1, 10)).horizons
    r = rec[10]
    assert r.status == "COMPLETE" and r.mode == "reconstructed" and r.universe == p.tickers
    info = r.reconstructed["DEMO-US3"]
    assert 0.4 < info.share_filled < 0.7 and info.n_real > 900
    assert rec[1].reconstructed == {}                       # nothing to reconstruct on 1 year
    s.analysis_mode = "common_universe"
    cu = run_analysis(database, p, s, mk, (10,)).horizons[10]
    others = [tk for tk in p.tickers if tk != "DEMO-US3"]
    # other holdings: only real returns on the common calendar (no value of theirs is estimated)...
    real = (r.prices[others] / r.prices[others].shift(1) - 1).iloc[1:]
    assert np.allclose(r.returns[others].values, real.values, atol=1e-12)
    # ...so their estimates differ from the analysis without DEMO-US3 only through the dates DEMO-US3 did not trade
    assert np.max(np.abs(r.mu[others] - cu.mu[others])) < 0.01
    assert np.max(np.abs(np.sqrt(np.diag(r.cov.loc[others, others])) - np.sqrt(np.diag(cu.cov.loc[others, others])))) < 0.01
    assert np.linalg.eigvalsh(r.cov.values).min() > -1e-12
    assert all(o.ok for o in r.optimized.values())


def test_too_few_real_days_is_explained(tmp_path):
    s = AppSettings(data_dir=str(tmp_path), use_demo_database=True, benchmark_ticker="^DEMO-IDX",
                    analysis_mode="reconstructed")
    db = Database(tmp_path / "demo.db")
    build_demo_database(db, s, load_markets(), now=lambda: FIXED_NOW)
    last = db.get_date_range("DEMO-US3")[1]
    keep_from = (pd.Timestamp(last) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    with db.transaction() as conn:
        conn.execute("DELETE FROM daily_prices WHERE ticker = 'DEMO-US3' AND date < ?", (keep_from,))
    b = run_analysis(db, demo_portfolio(), s, load_markets(), (1,))
    r = b.horizons[1]
    assert r.status == "INCOMPLETE" and "DEMO-US3" in r.too_short
    kinds = [o["kind"] for o in incomplete_reasons(r, b, demo_portfolio().tickers)]
    assert kinds == ["too_short"]


def test_reconstruct_button_and_lab_with_a_recent_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("GPL_DATA_DIR", str(tmp_path))
    s = AppSettings(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"), use_demo_database=True,
                    benchmark_ticker="^DEMO-IDX", selected_horizon=1)
    save_settings(s)
    db = Database(database_path(s))
    build_demo_database(db, s, load_markets(), now=lambda: FIXED_NOW)
    with db.transaction() as conn:   # DEMO-US3 becomes a listing of September 2025
        conn.execute("DELETE FROM daily_prices WHERE ticker = 'DEMO-US3' AND date < '2025-09-01'")
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.session_state["stats_h"] = 3
    at.switch_page("views/05_portfolio_statistics.py").run()
    assert at.session_state["analysis"].horizons[3].status == "INCOMPLETE"
    btn = next(b for b in at.button if b.label.startswith("Reconstruct the short history of DEMO-US3"))
    btn.click().run()
    assert not at.exception, [e.value for e in at.exception]
    b = at.session_state["analysis"]
    assert all(b.horizons[h].status == "COMPLETE" for h in (1, 3, 5, 10, 15))
    assert b.horizons[3].reconstructed["DEMO-US3"].first_real >= pd.Timestamp("2025-09-01")
    assert any("Reconstructed history" in w.value for w in at.warning)
    for page in ("01_dashboard", "07_optimized_portfolios", "08_risk_analysis", "12_currency", "10_reports"):
        at.switch_page(f"views/{page}.py").run()
        assert not at.exception, (page, [e.value for e in at.exception])
    at.switch_page("views/09_backtesting.py").run()
    assert not at.exception, [e.value for e in at.exception]
    next(b_ for b_ in at.button if b_.label == "Train, forecast and test").click().run()
    assert not at.exception, [e.value for e in at.exception]
    lab = at.session_state["lab"]
    assert lab is not None and "DEMO-US3" in at.session_state["lab_recon"]
    assert lab.train_returns.index[0] < pd.Timestamp("2020-01-01")       # long history used for training
    assert lab.test_returns.index[0] > at.session_state["lab_recon"]["DEMO-US3"].first_real
