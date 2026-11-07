"""Dashboard: visual map of the app, portfolio composition and what the money would have done."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from src import charts, ui
from src.i18n import t
from src.money import contributions, money_summary, wealth_with_start
from src.statistics import rf_markowitz
from src.validation import global_weights, validate_market_allocations

ui.page_header(t("Dashboard"), t("Build an international portfolio, measure it in one currency and compare it "
                                 "with Markowitz-optimized alternatives over five historical horizons."))
p = ui.portfolio()
s = ui.settings()
db = ui.db()
ui.intro(t("Your starting point: the map of the app, the state of your portfolio and what your money would have "
           "become. Every number here is explained on the page it comes from."))

alloc = validate_market_allocations(p.market_allocations) if p.market_allocations else None
total_alloc = alloc.details["total"] if alloc else 0.0
ready, _ = ui.portfolio_ready()
bundle = ui.get_analysis(auto=True) if ready else None   # downloads missing prices / exchange rates once
have_data = ready and all(db.get_date_range(tk)[2] > 0 for tk in p.tickers)

# ---------------------------------------------------------------- map of the app
st.subheader(t("Map of the app"))
stages = [
    (t("1 · Build"), t("Choose markets and stocks, download 15 years of prices."), bool(alloc and alloc.ok) and ready,
     [("views/02_portfolio_builder.py", t("Portfolio Builder"), ":material/construction:"),
      ("views/03_market_explorer.py", t("Find securities"), ":material/travel_explore:"),
      ("views/04_historical_database.py", t("Historical Database"), ":material/database:")]),
    (t("2 · Analyze"), t("Statistics, currency effect, frontier, optimized portfolios and risk."), bundle is not None,
     [("views/05_portfolio_statistics.py", t("Portfolio Statistics"), ":material/query_stats:"),
      ("views/12_currency.py", t("Currency conversion"), ":material/currency_exchange:"),
      ("views/06_efficient_frontier.py", t("Efficient Frontier"), ":material/show_chart:"),
      ("views/07_optimized_portfolios.py", t("Optimized Portfolios"), ":material/tune:"),
      ("views/08_risk_analysis.py", t("Risk Analysis"), ":material/shield:")]),
    (t("3 · Simulate and export"), t("Train a model on the past, test it on later data, export everything."),
     st.session_state.get("lab") is not None,
     [("views/09_backtesting.py", t("Backtesting lab"), ":material/model_training:"),
      ("views/10_reports.py", t("Reports and Exports"), ":material/download:"),
      ("views/11_settings.py", t("Settings and Data Quality"), ":material/settings:")]),
]
cols = st.columns(3)
for col, (title, desc, done, links) in zip(cols, stages):
    with col.container(border=True):
        chip = (f"<span class='gpl-chip ok'>✓ {html.escape(t('done'))}</span>" if done
                else f"<span class='gpl-chip'>{html.escape(t('pending'))}</span>")
        st.markdown(f"#### {html.escape(title)} {chip}", unsafe_allow_html=True)
        st.caption(desc)
        for path, label, icon in links:
            st.page_link(path, label=label, icon=icon)

if not ready:
    with st.container(border=True):
        st.markdown(t("#### Get started"))
        st.markdown(t("1. **Allocate capital** across markets (for example USA 50%, Mexico 20%).\n"
                      "2. **Add exact Yahoo Finance tickers** in each market and split the market's share.\n"
                      "3. **Confirm and download** 15 years of prices; every analysis page then fills in."))
        c1, c2, c3 = st.columns(3)
        c1.page_link("views/02_portfolio_builder.py", label=t("Open Portfolio Builder"),
                     icon=":material/construction:")
        c2.page_link("views/00_how_to_use.py", label=t("Read How to use"), icon=":material/menu_book:")
        c3.page_link("views/11_settings.py", label=t("Try the offline demo (Settings)"), icon=":material/science:")
elif not have_data:
    st.info(t("Prices are missing for some holdings. Open **Portfolio Builder**, step 3, and select **Confirm and "
              "download**."), icon=":material/cloud_download:")
    st.page_link("views/02_portfolio_builder.py", label=t("Open Portfolio Builder"), icon=":material/construction:")

# ---------------------------------------------------------------- composition
st.subheader(t("Portfolio"))
cap = ui.capital()
c = st.columns(5)
c[0].metric(t("Capital"), ui.fmt_compact(cap), help=t("Money used for every amount in the app: the portfolio's total "
                                                      "capital (Builder, step 1) or the default in Settings."),
            border=True)
c[1].metric(t("Total allocation"), f"{total_alloc:.2f}%", border=True)
c[2].metric(t("Markets"), len([a for a in p.market_allocations.values() if a > 0]), border=True)
c[3].metric(t("Securities"), len(p.holdings), border=True)
if p.tickers:
    yrs = []
    for tk in p.tickers:
        f, l_, n = db.get_date_range(tk)
        yrs.append((pd.Timestamp(l_) - pd.Timestamp(f)).days / 365.25 if n else 0.0)
    c[4].metric(t("Common history"), t("{years} years", years=f"{min(yrs):.1f}"),
                help=t("Shortest stored history among holdings."), border=True)
else:
    c[4].metric(t("Common history"), "–", border=True)

if p.market_allocations:
    colors = ui.security_colors(p.tickers) if p.tickers else {}
    l1, r1 = st.columns(2)
    l1.plotly_chart(charts.market_donut(p.market_allocations, {k: ui.market_name(k) for k in p.market_allocations}),
                    width="stretch", theme=None)
    if p.holdings:
        r1.plotly_chart(charts.security_treemap(global_weights(p), {x.ticker: x.market_id for x in p.holdings},
                                                [m for m, a in p.market_allocations.items() if a > 0],
                                                {k: ui.market_name(k) for k in p.market_allocations}, colors),
                        width="stretch", theme=None)

# ---------------------------------------------------------------- performance
if bundle is not None:
    st.subheader(t("What your money would have done"))
    h = ui.horizon_selector(bundle, "dash_h")
    r = bundle.horizons[h]
    ui.horizon_banner(r)
    if r.analyzable:
        us = r.user_stats
        ms = money_summary(r.portfolio_returns, cap)
        path = wealth_with_start(r.portfolio_returns, cap, r.prices.index[0])
        spark = path.iloc[:: max(1, len(path) // 60)].round(0).tolist()
        k = st.columns(4)
        k[0].metric(t("Final value"), ui.fmt_compact(ms["final"]), ui.fmt_money(ms["gain"], sign=True),
                    chart_data=spark, chart_type="area", border=True,
                    help=t("{capital} invested on {start} with the weights you entered, rebalanced daily, until {end}.",
                           capital=ui.fmt_money(cap), start=f"{r.prices.index[0]:%Y-%m-%d}", end=f"{r.end:%Y-%m-%d}"))
        k[1].metric(t("Annual growth (CAGR)"), ui.pct(us.get("annual_geometric_return_cagr")),
                    t("arith. {value}", value=ui.pct(us.get("annual_arithmetic_return"))), delta_color="off",
                    delta_arrow="off", border=True)
        k[2].metric(t("Volatility"), ui.pct(us.get("annual_volatility")),
                    t("Sharpe {value}", value=ui.num(us.get("sharpe_annual"), 2)), delta_color="off",
                    delta_arrow="off", border=True)
        k[3].metric(t("Worst fall"), ui.fmt_compact(ms["max_drawdown_money"]), ui.pct(us.get("max_drawdown")),
                    delta_color="normal", border=True,
                    help=t("Largest drop from a previous peak value, in money and percent."))
        ref = {t("Your portfolio"): path}
        pcolors = {t("Your portfolio"): charts.strategy_color("user")}
        if r.benchmark_returns is not None and len(r.benchmark_returns):
            name_b = t("Benchmark {ticker}", ticker=s.benchmark_ticker)
            ref[name_b] = wealth_with_start(r.benchmark_returns, cap, r.prices.index[0])
            pcolors[name_b] = charts.strategy_color("benchmark")
        for key in ("max_sharpe", "min_variance"):
            o = r.optimized.get(key)
            if o is not None and o.ok:
                ref[o.name] = wealth_with_start(r.returns @ o.weights.reindex(r.returns.columns).values, cap,
                                                r.prices.index[0])
                pcolors[o.name] = charts.strategy_color(key)
        l2, r2 = st.columns([3, 2])
        l2.plotly_chart(ui.shade_reconstructed(charts.money_growth(ref, t("Growth of {capital} ({span})",
                                                                          capital=ui.fmt_compact(cap), h=h),
                                                               s.base_currency, pcolors), r),
                        width="stretch", theme=None)
        contrib = contributions(r.returns, r.weights_user, cap)
        r2.plotly_chart(charts.contribution_bars(contrib, t("Who made the money"), s.base_currency,
                                                 ui.security_colors(list(contrib.index)), ui.names(list(contrib.index)),
                                                 ui.logo_uris(list(contrib.index))), width="stretch", theme=None)
        assets = pd.DataFrame({"volatility": r.asset_stats["annual_volatility"], "return": r.mu})
        st.plotly_chart(charts.frontier_chart(r.frontier, r.optimized,
                                              rf_markowitz(s.risk_free_annual, s.periods_per_year),
                                              t("Efficient frontier preview ({span})", h=h), assets,
                                              ui.security_colors(list(assets.index)), cap, s.base_currency),
                        width="stretch", theme=None)
    with st.expander(t("Historical data coverage")):
        cov = pd.DataFrame({"first": [bundle.prices_base[tk].first_valid_index() if tk in bundle.prices_base
                                      else None for tk in p.tickers],
                            "last": [bundle.prices_base[tk].last_valid_index() if tk in bundle.prices_base
                                     else None for tk in p.tickers]}, index=p.tickers)
        st.plotly_chart(charts.coverage_timeline(cov), width="stretch", theme=None)
ui.explain("explain_dashboard", ccy=s.base_currency, capital=ui.fmt_money(cap))
ui.assumptions_expander()
ui.footer()
