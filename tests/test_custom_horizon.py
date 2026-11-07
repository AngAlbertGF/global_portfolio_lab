"""User-chosen analysis window next to the fixed horizons."""
import pickle
from datetime import date

import pandas as pd

from src import i18n
from src.analysis import incomplete_reasons, run_analysis
from src.config import AppSettings, load_markets
from src.horizons import CustomHorizon, sheet_prefix, tag
from src.reporting import build_tables
from src.synthetic import demo_portfolio
from tests.test_app_ui import _app, app_env  # noqa: F401  (fixture)


def test_custom_horizon_is_a_distinct_number_with_its_own_label():
    ch = CustomHorizon("2026-06-01", "2026-10-30")
    assert abs(float(ch) - 151 / 365.25) < 1e-12 and ch != 1 and ch not in {1: 0, 3: 0}
    assert ch == CustomHorizon(pd.Timestamp("2026-06-01"), "2026-10-30") and len({ch, 1, 3}) == 3
    assert pickle.loads(pickle.dumps(ch)) == ch
    assert tag(ch) == "custom" and sheet_prefix(ch) == "custom_" and sheet_prefix(5) == "h5y_" and tag(5) == "5y"
    i18n.set_language("es")
    try:
        assert i18n.years(ch) == "5 meses (2026-06-01 a 2026-10-30)"
        assert i18n.t("**Horizon {period}, {label}.** Sample {start} to {end}: {n} {freq} return observations "
                      "({years} years), {k} securities.", h=ch, label="x", start="a", end="b", n=1, freq="f",
                      years=1, k=1).startswith("**Horizonte de 5 meses")
    finally:
        i18n.set_language("en")
    assert i18n.years(CustomHorizon("2026-10-01", "2026-10-30"), short=True) == "29 days"
    assert i18n.years(CustomHorizon("2021-01-01", "2026-07-01"), short=True) == "5.5 years"


def test_custom_window_in_the_engine(demo_env):
    database, s0 = demo_env
    p, mk = demo_portfolio(), load_markets()
    s = AppSettings(**{**s0.to_dict(), "analysis_mode": "strict"})
    inside = CustomHorizon("2023-01-01", "2024-06-30")       # every holding trades in this window
    before = CustomHorizon("2015-01-01", "2020-12-31")       # DEMO-US3 listed in 2022
    b = run_analysis(database, p, s, mk, (1, inside, before))
    r = b.horizons[inside]
    assert r.status == "COMPLETE" and r.end <= pd.Timestamp("2024-06-30") and r.start >= pd.Timestamp("2023-01-01")
    assert r.returns.index.max() <= pd.Timestamp("2024-06-30") and 300 < r.n_obs < 400
    assert all(o.ok for o in r.optimized.values())
    assert b.horizons[before].status == "INCOMPLETE" and b.horizons[before].excluded == ["DEMO-US3"]
    ct = b.comparison_table()
    assert list(ct["horizon"])[1] == "18 months" and "custom_info" in build_tables(b)
    s.analysis_mode = "reconstructed"
    rb = run_analysis(database, p, s, mk, (CustomHorizon("2018-01-01", "2023-12-31"),))
    assert next(iter(rb.horizons.values())).status == "COMPLETE"


def test_short_window_reason_and_minimum(demo_env):
    database, s0 = demo_env
    p, mk = demo_portfolio(), load_markets()
    two_months = CustomHorizon("2026-08-20", "2026-10-23")
    s = AppSettings(**{**s0.to_dict(), "analysis_mode": "strict", "min_observations": 100})
    b = run_analysis(database, p, s, mk, (two_months,))
    r = b.horizons[two_months]
    assert r.status == "INSUFFICIENT_OBSERVATIONS"
    assert [o["kind"] for o in incomplete_reasons(r, b, p.tickers, 100)] == ["short_window"]
    s.min_observations = 20
    r2 = run_analysis(database, p, s, mk, (two_months,)).horizons[two_months]
    assert r2.status == "COMPLETE" and any("Short window" in w for w in r2.warnings)


def test_custom_window_in_the_interface(app_env):
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.session_state["stats_h"] = 0                            # "Custom"
    at.switch_page("views/05_portfolio_statistics.py").run()
    assert not at.exception, [e.value for e in at.exception]
    b = at.session_state["analysis"]
    ch = next(k for k in b.horizons if isinstance(k, CustomHorizon))
    assert b.horizons[ch].status == "COMPLETE"                # default: since every holding trades
    at.date_input(key="stats_h_crange").set_value((date(2024, 1, 1), date(2025, 6, 30))).run()
    assert not at.exception, [e.value for e in at.exception]
    b = at.session_state["analysis"]
    ch = next(k for k in b.horizons if isinstance(k, CustomHorizon))
    assert (ch.start, ch.end) == (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-06-30"))
    assert b.horizons[ch].status == "COMPLETE" and 1 in b.horizons and 15 in b.horizons
    for page in ("01_dashboard", "12_currency", "06_efficient_frontier", "07_optimized_portfolios", "08_risk_analysis"):
        at.switch_page(f"views/{page}.py").run()
        assert not at.exception, (page, [e.value for e in at.exception])
    at.switch_page("views/10_reports.py").run()
    next(b_ for b_ in at.button if b_.label == "Build HTML report").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert "2024-01-01" in at.session_state["html_rep"] or "2024-01-02" in at.session_state["html_rep"]
