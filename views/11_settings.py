"""Settings and Data Quality."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import i18n, ui
from src.config import PROVIDER_NAME, SUPPORTED_BASE_CURRENCIES, database_path, settings_path
from src.i18n import t
from src.synthetic import build_demo_database, demo_portfolio

ui.page_header(t("Settings and Data Quality"), t("Language, reporting currency, estimators, constraints and data "
                                                 "sources. Changes are saved to settings.json."), show_allocation=False)
s = ui.settings()
mk = ui.markets()


def _settings_language() -> None:
    code = st.session_state.get("settings_language")
    if code:
        s.language = i18n.set_language(code)
        st.session_state.language_selector = s.language  # keep the sidebar selector in sync
        ui.persist_settings()


tab_general, tab_data, tab_quality = st.tabs([t("Analysis settings"), t("Data source and demo"), t("Data quality")])
with tab_general:
    with st.container(key="inputs_language"):
        langs = i18n.available_languages()
        if st.session_state.get("settings_language") not in langs:
            st.session_state.settings_language = i18n.get_language()
        st.selectbox(":material/translate: " + t("Interface language"), list(langs),
                     format_func=lambda c: langs[c], key="settings_language", on_change=_settings_language,
                     help=t("Applies to every page, chart, message and report. Exported table and column names stay "
                            "in English."))
    with st.form("settings_form"):
        st.markdown(t("#### Money and appearance"))
        c = st.columns(3)
        dcap = c[0].number_input(t("Default capital ({ccy})", ccy=s.base_currency), 1.0, 1e12, float(s.default_capital),
                                 10000.0, format="%.2f",
                                 help=t("Used for every amount in money when the portfolio has no capital of its own "
                                        "(Builder, step 1)."))
        brand = c[1].toggle(t("Use each company's logo color in charts"), s.use_brand_colors)
        dlogos = c[2].toggle(t("Download company logos"), s.download_logos,
                             help=t("Once per ticker, from Parqet or Financial Modeling Prep (public images), or from "
                                    "logostream.dev if you enter an API key below."))
        c = st.columns([2, 1])
        lkey = c[0].text_input(t("logostream.dev API key (optional)"), s.logostream_api_key, type="password",
                               help=t("Free 'Community' plan: 20,000 requests a month, attribution required (the app "
                                      "then shows 'Logos by logostream.dev' at the bottom of every page)."))
        lstore = c[1].checkbox(t("My logostream plan allows caching"), s.logostream_store_images,
                               help=t("The free plan does not include caching: logostream images are then kept in "
                                      "memory only and fetched again in a new session."))
        st.markdown(t("#### Reporting and risk-free rate"))
        c = st.columns(3)
        base = c[0].selectbox(t("Base (reporting) currency"), SUPPORTED_BASE_CURRENCIES,
                              index=SUPPORTED_BASE_CURRENCIES.index(s.base_currency))
        rf = c[1].number_input(t("Risk-free rate, EFFECTIVE annual (%)"), -5.0, 50.0, float(s.risk_free_annual * 100),
                               0.05, help=t("Default 6.5% MXN is an assumption, not a verified market yield. Use a "
                                            "rate in the base currency.")) / 100
        freqs = ["daily", "weekly"]
        freq = c[2].selectbox(t("Return frequency"), freqs, index=freqs.index(s.return_frequency),
                              format_func=lambda k: t(ui.FREQUENCY_LABELS[k]),
                              help=t("Weekly returns reduce the bias from asynchronous market closes."))
        st.markdown(t("#### Estimators"))
        c = st.columns(3)
        mus = ["arithmetic", "geometric", "ewma", "user"]
        mu_e = c[0].selectbox(t("Expected returns"), mus, index=mus.index(s.mu_estimator),
                              format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
        covs = ["sample", "ledoit_wolf", "ewma"]
        cov_e = c[1].selectbox(t("Covariance"), covs, index=covs.index(s.cov_estimator),
                               format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
        lam = c[2].number_input(t("EWMA decay λ"), 0.80, 0.9999, float(s.ewma_lambda), 0.005, format="%.4f")
        st.markdown(t("#### Constraints"))
        c = st.columns(4)
        modes = ["fixed_markets", "global_only"]
        mode = c[0].selectbox(t("Market constraint mode"), modes, index=modes.index(s.constraint_mode),
                              format_func=lambda k: t(ui.CONSTRAINT_LABELS[k]))
        long_only = c[1].checkbox(t("Long-only"), s.long_only)
        minw = c[2].number_input(t("Min weight if shorting (%)"), -100.0, 0.0, float(min(s.min_weight * 100, 0.0)),
                                 1.0) / 100
        cap = c[3].number_input(t("Max weight per stock (%; 0 = none)"), 0.0, 100.0, float((s.max_weight or 0) * 100),
                                1.0)
        st.markdown(t("#### Horizons and coverage"))
        c = st.columns(4)
        amodes = ["strict", "reconstructed", "common_universe", "available_history"]
        amode = c[0].selectbox(t("Coverage mode"), amodes, index=amodes.index(s.analysis_mode),
                               format_func=lambda k: t(ui.COVERAGE_LABELS[k]))
        minobs = c[1].number_input(t("Minimum observations"), 2, 10000, s.min_observations)
        tol = c[2].number_input(t("Coverage tolerance (days)"), 0, 60, s.coverage_tolerance_days)
        stale = c[3].number_input(t("Max FX staleness (days)"), 0, 10, s.fx_max_staleness_days)
        bmin = st.number_input(t("Reconstructed history: minimum real days of a new listing"), 10, 250,
                               s.backfill_min_obs,
                               help=t("A recently listed stock (IPO) needs at least this many real daily returns "
                                      "before its earlier history can be reconstructed from the other holdings."))
        c = st.columns(4)
        pts = c[0].number_input(t("Frontier points"), 5, 300, s.frontier_points)
        vlim = c[1].number_input(t("Max-risk vertex limit"), 100, 5_000_000, s.max_risk_vertex_limit, 1000)
        years = c[2].number_input(t("History to download (years)"), 1, 30, s.history_years)
        overlap = c[3].number_input(t("Refresh overlap (days)"), 0, 60, s.refresh_overlap_days)
        st.markdown(t("#### Benchmark and folders"))
        c = st.columns(3)
        bopts = [""] + [m.benchmark for m in mk.values() if m.benchmark]
        bench = c[0].selectbox(t("Benchmark"), bopts, index=bopts.index(s.benchmark_ticker)
                               if s.benchmark_ticker in bopts else 0, format_func=lambda b: b or t("none"))
        auto = c[1].checkbox(t("Refresh portfolio data on startup"), s.auto_refresh_on_startup)
        datadir = c[2].text_input(t("Data directory"), s.data_dir)
        outdir = c[2].text_input(t("Outputs directory"), s.output_dir)
        st.markdown(t("#### User-defined expected returns (annual %, used when the estimator is User-defined)"))
        p = ui.portfolio()
        C_T, C_E = t("Ticker"), t("Expected return %")
        ue = pd.DataFrame({C_T: p.tickers, C_E: [s.user_expected_returns.get(tk, float("nan")) * 100
                                                 for tk in p.tickers]})
        ue_ed = st.data_editor(ue, hide_index=True, disabled=[C_T], key="ue_editor")
        if st.form_submit_button(t("Save settings"), type="primary", icon=":material/save:"):
            s.default_capital, s.use_brand_colors, s.download_logos = float(dcap), bool(brand), bool(dlogos)
            s.logostream_api_key, s.logostream_store_images = lkey.strip(), bool(lstore)
            s.base_currency, s.risk_free_annual, s.return_frequency = base, rf, freq
            s.mu_estimator, s.cov_estimator, s.ewma_lambda = mu_e, cov_e, lam
            s.constraint_mode, s.long_only, s.min_weight = mode, long_only, (0.0 if long_only else minw)
            s.max_weight = cap / 100 if cap > 0 else None
            s.analysis_mode, s.min_observations, s.coverage_tolerance_days = amode, int(minobs), int(tol)
            s.backfill_min_obs = int(bmin)
            s.fx_max_staleness_days, s.frontier_points, s.max_risk_vertex_limit = int(stale), int(pts), int(vlim)
            s.history_years, s.refresh_overlap_days, s.benchmark_ticker = int(years), int(overlap), bench
            s.auto_refresh_on_startup, s.data_dir, s.output_dir = auto, datadir, outdir
            s.user_expected_returns = {row[C_T]: row[C_E] / 100 for _, row in ue_ed.iterrows() if pd.notna(row[C_E])}
            p.base_currency = base
            ui.persist_settings()
            st.success(t("Saved to {path}. Analyses will be recomputed.", path=settings_path()))
            if mu_e == "user" and len(s.user_expected_returns) < len(p.tickers):
                st.warning(t("The User-defined estimator needs an expected return for every holding."))

with tab_data:
    st.write(t("Provider: **{provider}**. Free, unofficial interface: coverage, accuracy and availability are not "
               "guaranteed; respect Yahoo's terms of use and rate limits. Active database: {path}.",
               provider=PROVIDER_NAME, path=f"`{database_path(s)}`"))
    demo = st.toggle(t("Use SYNTHETIC demo database"), s.use_demo_database,
                     help=t("A separate file with illustrative synthetic data, for exploring the app offline."))
    if demo != s.use_demo_database:
        s.use_demo_database = demo
        ui.persist_settings()
        st.session_state.analysis = None
        st.rerun()
    if s.use_demo_database:
        if st.button(t("Build or rebuild the synthetic demo data and load the demo portfolio"),
                     icon=":material/science:"):
            with st.spinner(t("Generating synthetic data...")):
                build_demo_database(ui.db(), s, mk)
            st.session_state.portfolio = demo_portfolio()
            st.session_state.portfolio.name = t("SYNTHETIC demo portfolio")
            if not s.benchmark_ticker:
                s.benchmark_ticker = "^DEMO-IDX"
                ui.persist_settings()
            st.success(t("Synthetic demo database ready; demo portfolio loaded."))

with tab_quality:
    bundle = st.session_state.analysis
    if bundle is not None:
        st.markdown(t("**Currency conversion and FX alignment (latest analysis)**"))
        ui.show_table(bundle.conversion_report)
        st.caption(t("Carried FX = stock dates priced with an FX rate from an earlier day (within the staleness "
                     "limit); Dropped = stock observations removed because no admissible FX rate existed. Exchanges "
                     "close at different times, so a same-date FX close is not perfectly synchronous with every "
                     "stock close."))
    else:
        st.caption(t("Run any analysis page to see the currency-conversion report here."))
    st.markdown(t("**FX series and quote direction**"))
    fx = ui.db().get_fx_series_info()
    if not fx.empty:
        fx["direction_verified"] = fx["direction_verified"].map(lambda v: t("yes") if v else t("no"))
    ui.show_table(fx)
    if st.button(t("Run integrity check"), icon=":material/fact_check:"):
        res = ui.db().integrity_check()
        (st.success if res["ok"] else st.error)(t("Integrity OK") if res["ok"] else t("Integrity problems found"))
        st.dataframe(pd.DataFrame({t("Check"): list(res), t("Result"): [str(v) for v in res.values()]}),
                     hide_index=True)
    failed = ui.db().failed_tickers()
    st.write(t("Symbols whose latest download did not succeed: {symbols}", symbols=", ".join(failed) or t("none")))
ui.footer()
