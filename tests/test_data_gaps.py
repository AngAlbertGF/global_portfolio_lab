"""Missing prices / exchange rates: detected, explained per security, and downloaded automatically."""
from pathlib import Path

from src.analysis import incomplete_reasons, run_analysis
from src.config import AppSettings, database_path, load_markets, save_settings
from src.data_service import DataService
from src.database import Database
from src.synthetic import SyntheticProvider, build_demo_database, demo_portfolio
from tests.conftest import FIXED_NOW
from tests.test_app_ui import _app, app_env  # noqa: F401  (fixture)


def _drop(db: Database, ticker: str | None = None, fx: tuple[str, str] | None = None) -> None:
    with db.transaction() as conn:
        if ticker:
            conn.execute("DELETE FROM daily_prices WHERE ticker = ?", (ticker,))
        if fx:
            conn.execute("DELETE FROM exchange_rates WHERE base_currency = ? AND quote_currency = ?", fx)


def test_gaps_are_explained_and_filled(tmp_path):
    s = AppSettings(data_dir=str(tmp_path), use_demo_database=True, benchmark_ticker="^DEMO-IDX")
    db = Database(tmp_path / "demo.db")
    build_demo_database(db, s, load_markets(), now=lambda: FIXED_NOW)
    _drop(db, ticker="DEMO-US2", fx=("JPY", "MXN"))
    p = demo_portfolio()
    svc = DataService(db, SyntheticProvider(), load_markets(), s, now=lambda: FIXED_NOW, cache_hours=0)
    gaps = svc.data_gaps(p.tickers, "MXN")
    assert gaps == {"no_prices": ["DEMO-US2"], "no_fx": {"JPY": ["DEMO-JP1.T"]}}

    b = run_analysis(db, p, s, load_markets(), (1,))
    r = b.horizons[1]
    assert r.status == "INCOMPLETE"
    kinds = {o["ticker"]: o["kind"] for o in incomplete_reasons(r, b, p.tickers)}
    assert kinds == {"DEMO-US2": "no_prices", "DEMO-JP1.T": "no_fx"}

    res = svc.fill_gaps([(h.ticker, h.market_id) for h in p.holdings], "MXN", gaps)
    assert {"DEMO-US2", "JPYMXN"} <= {r_.symbol for r_ in res}
    assert svc.data_gaps(p.tickers, "MXN") == {"no_prices": [], "no_fx": {}}
    assert run_analysis(db, p, s, load_markets(), (1,)).horizons[1].status == "COMPLETE"


def test_short_history_reason(demo_env, demo_bundle):
    r = demo_bundle.horizons[10]
    reasons = incomplete_reasons(r, demo_bundle, demo_portfolio().tickers)
    assert [o["kind"] for o in reasons] == ["short"] and reasons[0]["ticker"] == "DEMO-US3"
    assert 3 < reasons[0]["years"] < 10 and reasons[0]["needed"] == r.nominal_start


def test_statistics_page_downloads_missing_data_once(tmp_path, monkeypatch):
    """A holding never downloaded and a new base currency (no exchange rates yet) no longer leave every
    horizon INCOMPLETE: the analysis page fetches what is missing and the horizons become COMPLETE."""
    monkeypatch.setenv("GPL_DATA_DIR", str(tmp_path))
    s = AppSettings(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"), use_demo_database=True,
                    benchmark_ticker="^DEMO-IDX", selected_horizon=1)
    save_settings(s)
    db = Database(database_path(s))
    build_demo_database(db, s, load_markets(), now=lambda: FIXED_NOW)
    _drop(db, ticker="DEMO-US2")
    s.base_currency = "USD"
    save_settings(s)
    assert db.get_fx_range("MXN", "USD")[2] == 0
    at = _app()
    at.session_state["portfolio"] = demo_portfolio()
    at.switch_page("views/05_portfolio_statistics.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert db.get_date_range("DEMO-US2")[2] > 0 and db.get_fx_range("MXN", "USD")[2] > 0
    b = at.session_state["analysis"]
    assert b.horizons[1].status == "COMPLETE" and b.horizons[3].status == "COMPLETE"
    assert Path(database_path(s)).exists()


def test_banner_explains_and_offers_fixes(app_env):
    """Unknown symbol: the automatic download fails once, the reason and a retry button are shown.
    Short history: the reason is visible and one click switches to a labelled alternative."""
    from src.validation import Holding

    at = _app()
    p = demo_portfolio()
    next(h for h in p.holdings if h.market_id == "USA").within_pct -= 10
    p.holdings.append(Holding("DEMO-NOPE", "USA", 10.0))
    at.session_state["portfolio"] = p
    at.session_state["stats_h"] = 1
    at.switch_page("views/05_portfolio_statistics.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["analysis"].horizons[1].status == "INCOMPLETE"
    err = " ".join(e.value for e in at.error)
    assert "DEMO-NOPE" in err and "have not been downloaded" in err
    assert any(b.label == "Download what is missing" for b in at.button)
    attempts = list(at.session_state["gap_attempts"])
    at.run()  # no second automatic attempt for the same gap
    assert not at.exception and list(at.session_state["gap_attempts"]) == attempts

    at.session_state["portfolio"] = demo_portfolio()
    at.session_state["stats_h"] = 10
    at.run()
    assert at.session_state["analysis"].horizons[10].status == "INCOMPLETE"
    err = " ".join(e.value for e in at.error)
    assert "DEMO-US3" in err and "Why:" in err
    next(b for b in at.button if b.label == "Analyze with the available history").click().run()
    assert not at.exception, [e.value for e in at.exception]
    r = at.session_state["analysis"].horizons[10]
    assert r.status == "COMPLETE" and r.mode == "available_history"
