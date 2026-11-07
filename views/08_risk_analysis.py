"""Risk Analysis: covariance/correlation, Euler decomposition, concentration, tails, reliability."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src import charts, ui
from src.i18n import t
from src.optimization import maximum_sharpe
from src.reporting import sensitivity_table
from src.money import money_summary
from src.statistics import block_bootstrap_ci, crisis_performance, monte_carlo_terminal, rf_markowitz

ui.page_header(t("Risk Analysis"), t("Where the portfolio's risk comes from, how concentrated it is, how bad the "
                                     "tails are, and how much the estimates can be trusted."))
ui.intro(t("Risk measured three ways: how much the value swings, how bad the worst days and falls were (in money), "
           "and which securities the swings come from."))
s = ui.settings()
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
h = ui.horizon_selector(bundle, "risk_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
if not r.analyzable:
    st.stop()
w = r.weights_user
cap = ui.capital()
ms = money_summary(r.portfolio_returns, cap)
var_p = float(w.values @ r.cov.values @ w.values)
us0 = r.user_stats
c = st.columns(4)
c[0].metric(t("Portfolio volatility"), ui.pct(np.sqrt(var_p)),
            t("≈ {value} per year", value=ui.fmt_compact(cap * np.sqrt(var_p))), delta_color="off", delta_arrow="off",
            border=True, help=t("One annual standard deviation applied to {capital}.", capital=ui.fmt_money(cap)))
c[1].metric(t("Bad day (VaR 95%)"), ui.fmt_compact(-cap * us0["var_95"]), ui.pct(-us0["var_95"]), delta_color="off",
            delta_arrow="off", border=True,
            help=t("On 1 day out of 20 the historical loss was at least this much ({capital} invested).",
                   capital=ui.fmt_money(cap)))
c[2].metric(t("Average of the worst days (CVaR 95%)"), ui.fmt_compact(-cap * us0["cvar_95"]), ui.pct(-us0["cvar_95"]),
            delta_color="off", delta_arrow="off", border=True)
c[3].metric(t("Worst fall"), ui.fmt_compact(ms["max_drawdown_money"]), ui.pct(us0["max_drawdown"]),
            delta_color="normal", border=True)
c = st.columns(4)
c[0].metric(t("Portfolio variance (annual)"), f"{var_p:.6f}", border=True)
c[1].metric(t("Diversification ratio"), ui.num(r.concentration["diversification_ratio"]), border=True)
c[2].metric(t("Effective number of securities"), ui.num(r.concentration["effective_n_securities"], 2), border=True)
c[3].metric(t("Largest single weight"), ui.pct(r.concentration["max_security_weight"]), border=True)

tab_contrib, tab_cov, tab_conc, tab_tail, tab_rel = st.tabs(
    [t("Risk contributions"), t("Covariance and correlation"), t("Concentration"), t("Tail risk and distribution"),
     t("Reliability and sensitivity")])
with tab_contrib:
    st.plotly_chart(charts.add_logo_ticks(charts.risk_contribution_bar(r.risk_decomp),
                                          list(r.risk_decomp.sort_values("component_vol_pct").index),
                                          ui.logo_uris(list(r.risk_decomp.index)), "y"), width="stretch", theme=None)
    st.caption(t("Blue = share of the money; orange = share of the risk. A security whose orange bar is longer than "
                 "its blue bar adds more risk than its weight suggests."))
    ui.show_table(r.risk_decomp, pct=["weight", "variance_contribution_pct", "marginal_vol_contribution",
                                      "component_vol_contribution", "component_vol_pct"],
                  num=["variance_contribution"], digits=3, num_digits=6, hide_index=False, index_label=t("Ticker"))
    st.caption(t("Euler decomposition: MCR_i = (Σw)_i / σ_p, CR_i = w_i·MCR_i, and Σ CR_i = σ_p exactly; variance "
                 "contributions w_i(Σw)_i sum to σ²_p. Check: Σ CR_i = {sum_cr} vs σ_p = {sigma}.",
                 sum_cr=f"{r.risk_decomp['component_vol_contribution'].sum():.6f}", sigma=f"{np.sqrt(var_p):.6f}"))
with tab_cov:
    st.plotly_chart(charts.correlation_heatmap(r.corr), width="stretch", theme=None)
    st.markdown(t("**Annualized covariance matrix**"))
    st.dataframe(r.cov.style.format("{:.5f}"), width="stretch")
    ck = r.cov_check
    reg = (t(", shrinkage intensity {value} (regularized)", value=f"{r.cov_info['shrinkage']:.4f}")
           if r.cov_info.get("shrinkage") is not None else t(", no regularization"))
    st.write(t("Estimator **{est}**{reg}. Eigenvalues: min {emin}, max {emax}; condition number {cond}; symmetry "
               "error {sym}; positive semidefinite: {psd}. {n} observations for {k} assets.",
               est=t(ui.ESTIMATOR_LABELS.get(r.cov_info["method"], r.cov_info["method"])), reg=reg,
               emin=f"{ck['min_eigenvalue']:.3e}", emax=f"{ck['max_eigenvalue']:.3e}",
               cond=f"{ck['condition_number']:.3g}", sym=f"{ck['symmetric_error']:.1e}",
               psd=t("yes") if ck["psd"] else t("no"), n=r.n_obs, k=len(r.universe)))
    for wmsg in ck["warnings"]:
        st.warning(wmsg)
with tab_conc:
    con = r.concentration
    a, b = st.columns(2)
    a.markdown(t("**By market**"))
    a.dataframe(pd.Series(con["weights_by_market"]).mul(100).round(3).rename(t("Weight %")).to_frame(),
                width="stretch")
    b.markdown(t("**Currency exposure**"))
    b.dataframe(pd.Series(con["weights_by_currency"]).mul(100).round(3).rename(t("Weight %")).to_frame(),
                width="stretch")
    st.write(t("HHI (securities) {hhi_s} → effective N {n_s}; HHI (markets) {hhi_m} → effective N {n_m}; largest "
               "single weight {maxw}.", hhi_s=f"{con['hhi_security']:.4f}", n_s=f"{con['effective_n_securities']:.2f}",
               hhi_m=f"{con['hhi_market']:.4f}", n_m=f"{con['effective_n_markets']:.2f}",
               maxw=f"{con['max_security_weight']:.2%}"))
with tab_tail:
    us = r.user_stats
    st.dataframe(pd.DataFrame({t("VaR (per period)"): [us["var_95"] * 100, us["var_99"] * 100],
                               t("CVaR / expected shortfall"): [us["cvar_95"] * 100, us["cvar_99"] * 100],
                               t("VaR in {ccy}", ccy=s.base_currency): [cap * us["var_95"], cap * us["var_99"]],
                               t("CVaR in {ccy}", ccy=s.base_currency): [cap * us["cvar_95"], cap * us["cvar_99"]]},
                              index=["95%", "99%"]).round(3), width="stretch",
                 column_config={t("VaR in {ccy}", ccy=s.base_currency): st.column_config.NumberColumn(format="%,.0f"),
                                t("CVaR in {ccy}", ccy=s.base_currency): st.column_config.NumberColumn(format="%,.0f")})
    st.caption(t("Historical, non-parametric, per return period, reported as positive losses (in %)."))
    st.plotly_chart(charts.distribution_chart(r.portfolio_returns, us["var_95"]), width="stretch", theme=None)
    verdict = (t("normality rejected at 5%.") if us["jarque_bera_pvalue"] < 0.05
               else t("normality not rejected at 5%."))
    st.write(t("Skewness {skew}; excess kurtosis {kurt}; Jarque-Bera {jb} (p = {p}): {verdict}",
               skew=f"{us['skewness']:.3f}", kurt=f"{us['excess_kurtosis']:.3f}", jb=f"{us['jarque_bera_stat']:.1f}",
               p=f"{us['jarque_bera_pvalue']:.3g}", verdict=verdict))
    st.markdown(t("**Historical crisis periods** (shown only if inside this sample)"))
    ui.show_table(crisis_performance(r.portfolio_returns), pct=["return", "max_drawdown"])
with tab_rel:
    st.info(t("Historical expected returns are noisy estimates; descriptive statistics are not forecasts."),
            icon=":material/info:")
    if st.button(t("Bootstrap 95% confidence intervals (1,000 circular block resamples)"), icon=":material/replay:"):
        ci = block_bootstrap_ci(r.portfolio_returns, s.risk_free_annual, s.periods_per_year,
                                block=21 if s.periods_per_year == 252 else 4)
        ci.index = [t(ui.ROW_LABELS.get(i, i)) for i in ci.index]
        ui.show_table(ci, num=["estimate", "ci_low", "ci_high"], hide_index=False, index_label=t("Statistic"))
    st.markdown(t("**Risk-free sensitivity of the maximum-Sharpe portfolio**"))
    ui.show_table(sensitivity_table(r, s.risk_free_annual, s.periods_per_year),
                  pct=["risk_free_annual", "expected_return", "volatility"], num=["sharpe"])
    st.markdown(t("**Expected-return sensitivity**: μ perturbed by its sampling standard error (σ_i/√T, annualized)"))
    if st.button(t("Run 200 perturbations"), icon=":material/scatter_plot:"):
        rng = np.random.default_rng(3)
        cs = r.constraints
        mu0 = r.mu.reindex(cs.tickers).values
        S = r.cov.reindex(index=cs.tickers, columns=cs.tickers).values
        se = np.sqrt(np.diag(S)) / np.sqrt(r.n_obs / s.periods_per_year)
        rf = rf_markowitz(s.risk_free_annual, s.periods_per_year)
        ws = []
        for _ in range(200):
            o = maximum_sharpe(mu0 + rng.normal(0, se), S, cs, rf)
            if o.ok:
                ws.append(o.weights)
        Wd = pd.DataFrame(ws)
        st.dataframe(pd.DataFrame({t("Mean weight %"): Wd.mean() * 100, t("5th percentile %"): Wd.quantile(0.05) * 100,
                                   t("95th percentile %"): Wd.quantile(0.95) * 100}).round(2), width="stretch")
        st.caption(t("{ok}/200 perturbed problems solved. Wide bands show how unstable max-Sharpe weights are.",
                     ok=len(ws)))
    st.markdown(t("**Monte Carlo (explicit assumptions)**"))
    st.caption(t("Assumes i.i.d. multivariate-normal per-period returns with the estimated μ and Σ, constant weights "
                 "and no costs. A teaching tool, not a forecast."))
    years = st.slider(t("Simulation horizon (years)"), 1, 10, 1)
    if st.button(t("Simulate 5,000 paths"), icon=":material/casino:"):
        tw = monte_carlo_terminal(r.mu, r.cov, w.reindex(r.mu.index), years * s.periods_per_year, s.periods_per_year)
        q = np.quantile(tw - 1, [0.05, 0.25, 0.5, 0.75, 0.95])
        st.dataframe(pd.DataFrame({t("Quantile"): ["5%", "25%", "50%", "75%", "95%"],
                                   t("Cumulative return %"): q * 100,
                                   t("Value of {capital}", capital=ui.fmt_compact(cap)): cap * (1 + q)}).round(2),
                     hide_index=True, column_config={t("Value of {capital}", capital=ui.fmt_compact(cap)):
                                                     st.column_config.NumberColumn(format="%,.0f")})
        st.metric(t("Probability of ending below {capital}", capital=ui.fmt_compact(cap)), f"{np.mean(tw < 1):.1%}",
                  border=True)
        st.plotly_chart(charts.histogram(tw - 1, t("Simulated cumulative return over {period}", h=years),
                                         t("Cumulative return"), t("Paths")), width="stretch", theme=None)
ui.explain("explain_risk", capital=ui.fmt_money(cap), ccy=s.base_currency)
ui.footer()
