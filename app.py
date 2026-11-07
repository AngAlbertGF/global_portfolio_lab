"""Global Portfolio Lab - Streamlit entry point and navigation.

Run:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from src import ui
from src.config import APP_NAME, setup_logging
from src.i18n import N_, t

setup_logging()
st.set_page_config(page_title=APP_NAME, page_icon=str(ui.ASSETS / "icon.svg"), layout="wide",
                   initial_sidebar_state="auto")
ui.init_state()       # loads settings and activates the saved interface language
ui.inject_css()

# optional refresh of portfolio tickers once per session (local cache prevents redundant requests)
if ui.settings().auto_refresh_on_startup and not st.session_state.get("startup_refresh_done"):
    st.session_state.startup_refresh_done = True
    ok, _ = ui.portfolio_ready()
    if ok:
        p = ui.portfolio()
        try:
            ui.service().update_many([(h.ticker, h.market_id) for h in p.holdings], ui.settings().base_currency)
        except Exception as exc:  # never block the UI on a refresh failure
            st.toast(t("Startup refresh failed: {error}", error=exc))

ui.sidebar_top()      # logo + language selector; a language change applies to this same run


def page(path: str, title: str, icon: str, url: str, default: bool = False) -> st.Page:
    return st.Page(path, title=t(title), icon=icon, url_path=url, default=default)


pages = {
    t("Start"): [
        page("views/01_dashboard.py", N_("Dashboard"), ":material/dashboard:", "dashboard", default=True),
        page("views/00_how_to_use.py", N_("How to use"), ":material/menu_book:", "how-to-use"),
    ],
    t("1 · Build"): [
        page("views/02_portfolio_builder.py", N_("Portfolio Builder"), ":material/construction:", "builder"),
        page("views/03_market_explorer.py", N_("Find securities"), ":material/travel_explore:", "explorer"),
        page("views/04_historical_database.py", N_("Historical Database"), ":material/database:", "database"),
    ],
    t("2 · Analyze"): [
        page("views/05_portfolio_statistics.py", N_("Portfolio Statistics"), ":material/query_stats:", "statistics"),
        page("views/12_currency.py", N_("Currency conversion"), ":material/currency_exchange:", "currency"),
        page("views/06_efficient_frontier.py", N_("Efficient Frontier"), ":material/show_chart:", "frontier"),
        page("views/07_optimized_portfolios.py", N_("Optimized Portfolios"), ":material/tune:", "optimized"),
        page("views/08_risk_analysis.py", N_("Risk Analysis"), ":material/shield:", "risk"),
    ],
    t("3 · Simulate and export"): [
        page("views/09_backtesting.py", N_("Backtesting lab"), ":material/model_training:", "backtesting"),
        page("views/10_reports.py", N_("Reports and Exports"), ":material/download:", "reports"),
        page("views/11_settings.py", N_("Settings and Data Quality"), ":material/settings:", "settings"),
    ],
}
nav = st.navigation(pages, expanded=True)
try:
    if ui.portfolio().tickers:
        ui.ensure_portfolio_logos_once()
except Exception:  # logos are cosmetic
    pass
try:
    nav.run()
finally:  # rendered after the page (also when a page calls st.stop) so the status reflects this run
    ui.sidebar_status()
