"""Portfolio Statistics: what the portfolio did in money and percent, per horizon, with every statistic kept."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src import charts, i18n, ui
from src.i18n import t
from src.labels import STAT_LABELS as LABELS
from src.money import contributions, money_summary, wealth_with_start

ui.page_header(t("Portfolio Statistics"), t("Descriptive statistics of your portfolio as you entered it, estimated "
                                            "independently for each horizon."))
s = ui.settings()
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
cap = ui.capital()
ui.intro(t("How {capital} invested with your weights would have evolved, in money and in percent. Charts first; every "
           "statistic is still available in the tables below them.", capital=ui.fmt_money(cap)))

with st.container(key="inputs_coverage"):
    modes = ["strict", "reconstructed", "common_universe", "available_history"]
    mode = st.radio(t("Coverage mode"), modes, horizontal=True, index=modes.index(s.analysis_mode),
                    format_func=lambda m: t(ui.COVERAGE_LABELS[m]),
                    help=t("Strict never changes membership or sample length. The other two modes are explicitly "
                           "labelled alternatives when some holdings lack history."))
if mode != s.analysis_mode:
    s.analysis_mode = mode
    ui.persist_settings()
    st.rerun()

# ------------------------------------------------------------------ cross-horizon overview
st.subheader(t("Cross-horizon comparison"))
ct = bundle.comparison_table()
rows = []
for hh, rr in bundle.horizons.items():
    if rr.analyzable:
        rows.append({"h": i18n.years(hh, short=True), "final": money_summary(rr.portfolio_returns, cap)["final"]})
if rows:
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.cross_horizon_chart(ct), width="stretch", theme=None)
    c2.plotly_chart(charts.bars_money({x["h"]: x["final"] for x in rows},
                                      t("What {capital} became, by horizon", capital=ui.fmt_compact(cap)),
                                      s.base_currency, reference=cap, ref_label=t("invested")),
                    width="stretch", theme=None)
else:
    st.info(t("No horizon is complete yet. The reason, and the button that fixes it, are under **Details for one "
              "horizon** below."), icon=":material/info:")
with st.expander(t("Cross-horizon table")):
    tab = ct.copy()
    for col in ("start", "end"):
        tab[col] = pd.to_datetime(tab[col]).dt.date
    pct_cols = [col for col in tab.columns if any(k in col for k in ("return", "volatility", "drawdown", "cagr"))]
    ui.show_table(tab, pct=pct_cols, num=[col for col in tab.columns if col.endswith("sharpe")], num_digits=3)

# ------------------------------------------------------------------ one horizon
st.subheader(t("Details for one horizon"))
h = ui.horizon_selector(bundle, "stats_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
if not r.coverage.empty:
    with st.expander(t("Coverage by holding")):
        ui.show_table(r.coverage, num=["years_available"], num_digits=2, hide_index=False)
if not r.analyzable:
    st.stop()
us = r.user_stats
ms = money_summary(r.portfolio_returns, cap)
start0 = r.prices.index[0]
path = wealth_with_start(r.portfolio_returns, cap, start0)
spark = path.iloc[:: max(1, len(path) // 60)].round(0).tolist()
k = st.columns(4)
k[0].metric(t("Final value"), ui.fmt_compact(ms["final"]), ui.fmt_money(ms["gain"], sign=True), chart_data=spark,
            chart_type="area", border=True)
k[1].metric(t("Annual growth (CAGR)"), ui.pct(us["annual_geometric_return_cagr"]),
            t("total {value}", value=ui.pct(us["cumulative_return"])), delta_color="off", delta_arrow="off", border=True)
k[2].metric(t("Volatility"), ui.pct(us["annual_volatility"]), t("Sharpe {value}", value=ui.num(us["sharpe_annual"], 2)),
            delta_color="off", delta_arrow="off", border=True)
k[3].metric(t("Worst fall"), ui.fmt_compact(ms["max_drawdown_money"]), ui.pct(us["max_drawdown"]), delta_color="normal",
            border=True)
k = st.columns(4)
k[0].metric(t("Best day"), ui.fmt_compact(ms["best_period_gain"], sign=True), f"{ms['best_period_date']:%Y-%m-%d}",
            delta_color="off", delta_arrow="off", border=True)
k[1].metric(t("Worst day"), ui.fmt_compact(ms["worst_period_loss"], sign=True), f"{ms['worst_period_date']:%Y-%m-%d}",
            delta_color="off", delta_arrow="off", border=True)
k[2].metric(t("Days up / down"), f"{us['positive_frequency']:.0%} / {us['negative_frequency']:.0%}", border=True)
k[3].metric(t("Highest value reached"), ui.fmt_compact(ms["peak_value"]), border=True)

# growth chart with interactive comparison
opts = {"benchmark": t("Benchmark {ticker}", ticker=s.benchmark_ticker)} if (
    r.benchmark_returns is not None and len(r.benchmark_returns)) else {}
opts |= {k_: o.name for k_, o in r.optimized.items() if k_ != "user" and o.ok}
pick = st.pills(t("Compare with"), list(opts), selection_mode="multi", format_func=lambda x: opts[x],
                default=[x for x in ("benchmark", "max_sharpe") if x in opts], key=f"stats_cmp_{h}")
paths = {t("Your portfolio"): path}
pcol = {t("Your portfolio"): charts.strategy_color("user")}
for key in pick or []:
    if key == "benchmark":
        paths[opts[key]] = wealth_with_start(r.benchmark_returns, cap, start0)
    else:
        rp = r.returns @ r.optimized[key].weights.reindex(r.returns.columns).values
        paths[opts[key]] = wealth_with_start(rp, cap, start0)
    pcol[opts[key]] = charts.strategy_color(key)
st.plotly_chart(ui.shade_reconstructed(charts.money_growth(paths, t("Growth of {capital} ({span}, {ccy})",
                                                                   capital=ui.fmt_compact(cap), h=h,
                                                                   ccy=s.base_currency), s.base_currency, pcol), r),
                width="stretch", theme=None)
c1, c2 = st.columns(2)
c1.plotly_chart(ui.shade_reconstructed(charts.drawdown_chart(r.portfolio_returns), r), width="stretch", theme=None)
c2.plotly_chart(charts.monthly_heatmap(r.portfolio_returns), width="stretch", theme=None)

# ------------------------------------------------------------------ securities
st.markdown(t("#### Each security in the portfolio"))
tickers = list(r.returns.columns)
logos = ui.logo_uris(tickers)
nm = ui.names(tickers)
contrib = contributions(r.returns, r.weights_user, cap)
growth = (1 + r.returns).cumprod()
step = max(1, len(growth) // 50)
a = r.asset_stats
sec = pd.DataFrame({
    "logo": [logos.get(tk) for tk in tickers], "name": [nm[tk] for tk in tickers], "ticker": tickers,
    "weight": [float(r.weights_user.get(tk, 0.0)) * 100 for tk in tickers],
    "trend": [growth[tk].iloc[::step].round(4).tolist() for tk in tickers],
    "cagr": [a.loc[tk, "annual_cagr"] * 100 for tk in tickers],
    "vol": [a.loc[tk, "annual_volatility"] * 100 for tk in tickers],
    "mdd": [a.loc[tk, "max_drawdown"] * 100 for tk in tickers],
    "risk": [a.loc[tk, "component_vol_pct"] * 100 for tk in tickers],
    "money": [contrib[tk] for tk in tickers],
    "real": [100 * (1 - r.reconstructed[tk].share_filled) if tk in r.reconstructed else 100.0 for tk in tickers]})
st.dataframe(sec.sort_values("weight", ascending=False), hide_index=True, width="stretch",
             column_config={"logo": ui.logo_column(), "name": st.column_config.TextColumn(t("Name")),
                            "ticker": st.column_config.TextColumn(t("Ticker")),
                            "weight": st.column_config.ProgressColumn(t("Weight"), format="%.1f%%", min_value=0,
                                                                      max_value=100),
                            "trend": st.column_config.LineChartColumn(t("Growth")),
                            "cagr": st.column_config.NumberColumn(t("CAGR"), format="%.1f%%"),
                            "vol": st.column_config.NumberColumn(t("Volatility"), format="%.1f%%"),
                            "mdd": st.column_config.NumberColumn(t("Worst fall"), format="%.1f%%"),
                            "risk": st.column_config.NumberColumn(t("Share of risk"), format="%.1f%%"),
                            "money": st.column_config.NumberColumn(t("Money made ({ccy})", ccy=s.base_currency),
                                                                   format="%,.0f"),
                            "real": st.column_config.ProgressColumn(
                                t("Real data"), format="%.0f%%", min_value=0, max_value=100,
                                help=t("Share of this horizon covered by real prices; the rest is reconstructed "
                                       "(Reconstructed history mode)."))})
st.plotly_chart(charts.contribution_bars(contrib, t("Money made by each security ({ccy})", ccy=s.base_currency),
                                         s.base_currency, ui.security_colors(tickers), nm, logos),
                width="stretch", theme=None)
st.caption(t("Contributions add up exactly to the total gain of {gain}: each day, each security earns its weight × "
             "its return × the portfolio value of the previous day.", gain=ui.fmt_money(ms["gain"], sign=True)))
if r.reconstructed:
    with st.expander(t("Reconstructed history: how each new listing was completed"), icon=":material/auto_fix_high:",
                     expanded=True):
        RC = pd.DataFrame([rec.to_dict() for rec in r.reconstructed.values()])
        RC["factors"] = [", ".join(ui.factor_name(f) for f in rec.factors) for rec in r.reconstructed.values()]
        RC["share_filled"] *= 100
        for col_ in ("alpha_annual", "resid_vol_annual", "real_mean_annual", "filled_mean_annual"):
            RC[col_] *= 100
        RC["first_real"] = pd.to_datetime(RC["first_real"]).dt.date
        st.dataframe(RC, hide_index=True, width="stretch", column_config={
            "ticker": t("Ticker"), "first_real": t("First real return"), "n_real": t("Real returns"),
            "n_filled": t("Reconstructed"),
            "share_filled": st.column_config.ProgressColumn(t("Reconstructed share"), format="%.0f%%", min_value=0,
                                                            max_value=100),
            "factors": t("Factors"), "betas": t("Betas"), "r2": st.column_config.NumberColumn("R²", format="%.2f"),
            "alpha_annual": st.column_config.NumberColumn(t("Extra return of the real part (not carried back)"),
                                                          format="%+.1f%%"),
            "resid_vol_annual": st.column_config.NumberColumn(t("Own (residual) volatility"), format="%.1f%%"),
            "real_mean_annual": st.column_config.NumberColumn(t("Mean of real part (annual)"), format="%+.1f%%"),
            "filled_mean_annual": st.column_config.NumberColumn(t("Mean of reconstructed part (annual)"),
                                                                format="%+.1f%%")})
        st.caption(t("Every other holding uses only real prices: its numbers match an analysis without the new "
                     "listing, except for the few dates the new listing did not trade (dropped for everyone by the "
                     "common calendar). The grey band in the charts marks the dates with reconstructed returns."))

# ------------------------------------------------------------------ all the numbers
PCT_KEYS = {"annual_arithmetic_return", "annual_geometric_return_cagr", "annual_volatility", "mean_period",
            "sd_period", "downside_deviation_annual", "max_drawdown", "best_period_return", "worst_period_return",
            "var_95", "cvar_95", "var_99", "cvar_99", "cumulative_return", "positive_frequency", "negative_frequency",
            "tracking_error", "active_return_annual", "benchmark_annual_return", "zero_frequency",
            "benchmark_cumulative_return", "alpha_annual_arith", "rf_annual_effective", "rf_period"}


def fmt(k_, v):
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if k_ in PCT_KEYS or (k_.startswith(("best_rolling", "worst_rolling")) and not k_.endswith("_end")):
        return ui.pct(v, 3)
    if isinstance(v, (float, np.floating)):
        return ui.num(v, 4)
    return str(v)


with st.expander(t("All statistics (table)"), icon=":material/table:"):
    rows = [{t("Statistic"): t(LABELS[k_]) if k_ in LABELS else k_.replace("_", " "), t("Value"): fmt(k_, v)}
            for k_, v in us.items()]
    money_rows = [(t("Capital"), ui.fmt_money(cap)), (t("Final value"), ui.fmt_money(ms["final"])),
                  (t("Gain or loss"), ui.fmt_money(ms["gain"], sign=True)),
                  (t("Worst fall in money"), ui.fmt_money(ms["max_drawdown_money"])),
                  (t("Best day in money"), ui.fmt_money(ms["best_period_gain"], sign=True)),
                  (t("Worst day in money"), ui.fmt_money(ms["worst_period_loss"], sign=True))]
    rows = [{t("Statistic"): a_, t("Value"): b_} for a_, b_ in money_rows] + rows
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=640)
with st.expander(t("Weights and asset-level statistics (tables)"), icon=":material/table:"):
    st.markdown(t("**Initial portfolio weights** (as you entered them; never replaced by optimized weights)"))
    st.dataframe((r.weights_user * 100).round(4).rename(t("Total weight %")).to_frame().T, width="stretch")
    st.markdown(t("**Asset-level statistics**"))
    pcols = ["annual_arith_return", "annual_cagr", "annual_volatility", "max_drawdown", "expected_return_used",
             "weight", "contribution_to_expected_return", "component_vol_contribution", "component_vol_pct",
             "marginal_vol_contribution"]
    ui.show_table(r.asset_stats, pct=pcols, num=["sharpe", "beta"], num_digits=3, hide_index=False,
                  index_label=t("Ticker"))
st.caption(t("Return frequency: {freq}; risk-free {rf} effective annual (assumption). Statistics describe "
             "{start} to {end} and are not forecasts. Turnover is reported in Backtesting.",
             freq=t(ui.FREQUENCY_LABELS[s.return_frequency]).lower(), rf=f"{s.risk_free_annual:.2%}",
             start=f"{r.start:%Y-%m-%d}", end=f"{r.end:%Y-%m-%d}"))
ui.explain("explain_statistics", ccy=s.base_currency, capital=ui.fmt_money(cap), n=s.periods_per_year,
           rf=f"{s.risk_free_annual:.2%}")
ui.assumptions_expander()
ui.footer()
