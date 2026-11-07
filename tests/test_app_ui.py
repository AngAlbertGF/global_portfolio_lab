"""Acceptance tests driving the real Streamlit app headlessly (synthetic demo database, no network)."""
import os
from pathlib import Path

import pytest

from src.config import AppSettings, database_path, load_markets, save_settings
from src.database import Database
from src.synthetic import build_demo_database, demo_portfolio
from tests.conftest import FIXED_NOW

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["01_dashboard", "02_portfolio_builder", "03_market_explorer", "04_historical_database",
         "05_portfolio_statistics", "06_efficient_frontier", "07_optimized_portfolios", "08_risk_analysis",
         "09_backtesting", "10_reports", "11_settings", "12_currency"]


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GPL_DATA_DIR", str(tmp_path))
    s = AppSettings(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"), use_demo_database=True,
                    benchmark_ticker="^DEMO-IDX", selected_horizon=3)
    save_settings(s)
    build_demo_database(Database(database_path(s)), s, load_markets(), now=lambda: FIXED_NOW)
    return tmp_path


def _app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    return at


def test_every_page_renders_without_exceptions(app_env):
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    for page in PAGES:
        at.switch_page(f"views/{page}.py")
        at.run()
        assert not at.exception, (page, [e.value for e in at.exception])


def test_build_portfolio_through_interface(app_env):
    """Allocate, add exact tickers, confirm and download: no source-code editing."""
    at = _app()
    at.switch_page("views/02_portfolio_builder.py")
    at.run()
    at.multiselect[0].set_value(["USA", "MEXICO"]).run()
    next(b for b in at.button if b.label == "Equal-weight").click().run()
    assert at.session_state["portfolio"].market_allocations == {"USA": 50.0, "MEXICO": 50.0}
    next(b for b in at.button if b.label == "Continue to step 2").click().run()
    for market, ticker in (("USA", "DEMO-US1"), ("MEXICO", "DEMO-MX1.MX")):
        at.text_input(key=f"tk_{market}").set_value(ticker)
        at.number_input(key=f"pc_{market}").set_value(100.0)
        idx = ["USA", "MEXICO"].index(market)
        [b for b in at.button if b.label == "Validate and add"][idx].click().run()
        assert not at.exception
    p = at.session_state["portfolio"]
    assert p.tickers == ["DEMO-US1", "DEMO-MX1.MX"]
    next(b for b in at.button if b.label == "Continue to confirmation").click().run()
    next(b for b in at.button if b.label == "Confirm and download").click().run()
    assert not at.exception
    res = at.session_state["last_download_results"]
    assert set(res["status"]) <= {"SUCCESS", "UP_TO_DATE"}
    at.switch_page("views/05_portfolio_statistics.py")
    at.run()
    assert not at.exception
    bundle = at.session_state["analysis"]
    assert bundle.horizons[15].status == "COMPLETE"  # both holdings have the full synthetic history
    # persistence across sessions: the saved portfolio and its history are reused by a new session
    db = Database(Path(os.environ["GPL_DATA_DIR"]) / "demo_synthetic.db")
    assert "My portfolio" in db.list_portfolios()["portfolio_name"].tolist()
    at2 = _app()
    at2.switch_page("views/02_portfolio_builder.py")
    at2.run()
    assert not at2.exception


def test_interactive_controls_run(app_env):
    """Buttons and forms on analysis pages execute without exceptions."""
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.switch_page("views/08_risk_analysis.py").run()
    for label in ("Bootstrap 95% confidence intervals (1,000 circular block resamples)", "Run 200 perturbations",
                  "Simulate 5,000 paths"):
        next(b for b in at.button if b.label == label).click().run()
        assert not at.exception, (label, [e.value for e in at.exception])
    at.switch_page("views/09_backtesting.py").run()
    next(b for b in at.button if b.label == "Train, forecast and test").click().run()
    lab = at.session_state["lab"]
    assert not at.exception, [e.value for e in at.exception]
    assert len(lab.runs) == 5 and all(r.ok for r in lab.runs.values())
    assert str(lab.train_returns.index[-1].date()) <= "2025-12-31" < str(lab.test_returns.index[0].date())
    at.slider[0].set_value(-20).run()                       # what-if: currency shock
    at.multiselect(key="lab_drop").set_value(["DEMO-US1"]).run()
    assert not at.exception, [e.value for e in at.exception]
    at.switch_page("views/10_reports.py").run()
    for label in ("Build HTML report", "Build PDF report"):
        next(b for b in at.button if b.label == label).click().run()
        assert not at.exception
    assert at.session_state["pdf_rep"][:4] == b"%PDF"
    at.switch_page("views/07_optimized_portfolios.py").run()
    next(b for b in at.button if b.label == "Solve target-volatility portfolio").click().run()
    assert not at.exception
    at.switch_page("views/03_market_explorer.py").run()
    at.text_input[0].set_value("DEMO-JP1.T")
    at.selectbox[0].set_value("JAPAN")
    next(b for b in at.button if b.label == "Look up").click().run()
    assert not at.exception and at.session_state["lookup"].accepted
    at.switch_page("views/04_historical_database.py").run()
    next(b for b in at.button if b.label == "Check database integrity").click().run()
    next(b for b in at.button if b.label == "Back up now").click().run()
    assert not at.exception
    at.switch_page("views/11_settings.py").run()
    next(b for b in at.button if b.label == "Save settings").click().run()
    assert not at.exception


def test_strict_mode_switch_to_labelled_mode(app_env):
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.switch_page("views/05_portfolio_statistics.py").run()
    assert at.session_state["analysis"].horizons[10].status == "INCOMPLETE"
    at.radio[0].set_value("common_universe").run()
    assert not at.exception
    r = at.session_state["analysis"].horizons[10]
    assert r.status == "COMPLETE" and r.excluded == ["DEMO-US3"]


def test_switch_language_from_sidebar_and_render_every_page_in_spanish(app_env):
    """The sidebar selector switches the whole interface; every page renders in Spanish without errors."""
    from src import i18n
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.selectbox(key="language_selector").set_value("es").run()
    assert not at.exception
    assert at.session_state["settings"].language == "es"
    i18n.set_language("es")  # AppTest re-evaluates widget format functions in the test thread
    try:
        for page in ["00_how_to_use"] + PAGES:
            at.switch_page(f"views/{page}.py")
            at.run()
            assert not at.exception, (page, [e.value for e in at.exception])
            text = " ".join(m.value for m in at.markdown)
            assert "Market allocation" not in text, page  # no English leftovers in page markdown
        # the persisted setting survives a new session
        at2 = _app()
        assert at2.session_state["settings"].language == "es"
        labels = [b.label for b in at2.button] + [m.value for m in at2.markdown]
        assert any("Panel" in x or "Construye" in x for x in labels)
    finally:
        i18n.set_language("en")


def test_spanish_builder_buttons_and_reports(app_env):
    from src import i18n
    s = AppSettings(data_dir=str(app_env), output_dir=str(app_env / "out"), use_demo_database=True,
                    benchmark_ticker="^DEMO-IDX", selected_horizon=3, language="es")
    save_settings(s)
    i18n.set_language("es")  # AppTest re-evaluates widget format functions in the test thread
    at = _app()
    try:
        at.switch_page("views/02_portfolio_builder.py").run()
        labels = {b.label for b in at.button}
        assert "Ponderar por igual" in labels and "Continuar al paso 2" in labels
        at.session_state["portfolio"] = demo_portfolio()
        at.switch_page("views/10_reports.py").run()
        next(b for b in at.button if b.label == "Generar reporte HTML").click().run()
        html = at.session_state["html_rep"]
        assert "Resumen ejecutivo" in html and "Limitaciones y conclusiones" in html and "lang='es'" in html
        next(b for b in at.button if b.label == "Generar reporte PDF").click().run()
        assert at.session_state["pdf_rep"][:4] == b"%PDF" and not at.exception
        warnings = " ".join(w for r in at.session_state["analysis"].horizons.values() for w in r.warnings)
        assert "INCOMPLETO" in warnings and "INCOMPLETE:" not in warnings
    finally:
        i18n.set_language("en")


def test_dark_mode_switch_and_working_portfolio_survives_reload(app_env):
    """The sidebar switch stores the theme, re-renders in dark mode and the portfolio survives a new session."""
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.run()
    assert at.toggle(key="theme_toggle_0").value is False
    at.toggle(key="theme_toggle_0").set_value(True).run()
    assert not at.exception
    assert at.session_state["settings"].theme == "dark"
    assert at.toggle(key="theme_toggle_1").value is True          # switch shows the new state
    for page in ["01_dashboard", "06_efficient_frontier", "08_risk_analysis"]:
        at.switch_page(f"views/{page}.py")
        at.run()
        assert not at.exception, page
    # a page reload is a new session: theme and working portfolio are restored
    at2 = _app()
    assert at2.session_state["settings"].theme == "dark"
    restored = at2.session_state["portfolio"]
    assert sorted(h.ticker for h in restored.holdings) == sorted(h.ticker for h in demo_portfolio().holdings)
    at2.toggle(key="theme_toggle_1").set_value(False).run()
    assert at2.session_state["settings"].theme == "light"



def test_builder_step2_picker_and_new_pages(app_env):
    """Step 2 shows the name picker per market; currency page renders the worked example in Spanish too."""
    from src import i18n
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.switch_page("views/02_portfolio_builder.py").run()
    at.session_state["_goto_step"] = 2
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["builder_step"] == 2
    at.switch_page("views/12_currency.py").run()
    assert not at.exception
    assert any("USDMXN=X" in m.value for m in at.markdown)
    at.selectbox(key="language_selector").set_value("es").run()
    i18n.set_language("es")
    try:
        for page in ("12_currency", "09_backtesting", "05_portfolio_statistics", "03_market_explorer"):
            at.switch_page(f"views/{page}.py").run()
            assert not at.exception, (page, [e.value for e in at.exception])
            if page == "12_currency":
                assert any("Tipos de cambio usados" in h.value for h in at.subheader)
    finally:
        i18n.set_language("en")
