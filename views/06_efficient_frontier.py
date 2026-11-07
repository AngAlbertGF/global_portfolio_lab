"""Efficient Frontier with model controls; click any portfolio or frontier point to inspect it."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from src import charts, i18n, ui
from src.i18n import t
from src.horizons import tag
from src.statistics import rf_markowitz

ui.page_header(t("Efficient Frontier"), t("The constrained Markowitz frontier for each horizon, with your portfolio "
                                          "and the optimized alternatives on the same axes."))
s = ui.settings()
cap = ui.capital()
ui.intro(t("Each point is a portfolio: further right = more risk, higher = more expected return. The curve holds the "
           "lowest-risk portfolio for every return level. Click a point to see its composition and what it means "
           "for {capital}.", capital=ui.fmt_money(cap)))

with st.container(key="inputs_model"):
    st.markdown(t("**Model settings**"))
    c = st.columns(3)
    rf = c[0].number_input(t("Risk-free rate (effective annual, %)"), -5.0, 50.0, float(s.risk_free_annual * 100),
                           0.05, format="%.2f") / 100
    covs = ["sample", "ledoit_wolf", "ewma"]
    cov_e = c[1].selectbox(t("Covariance estimator"), covs, index=covs.index(s.cov_estimator),
                           format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
    mu_opts = ["arithmetic", "geometric", "ewma"] + (["user"] if s.user_expected_returns else [])
    mu_e = c[2].selectbox(t("Expected-return estimator"), mu_opts,
                          index=mu_opts.index(s.mu_estimator) if s.mu_estimator in mu_opts else 0,
                          format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
    c = st.columns(3)
    modes = ["fixed_markets", "global_only"]
    mode = c[0].selectbox(t("Market constraint mode"), modes, index=modes.index(s.constraint_mode),
                          format_func=lambda k: t(ui.CONSTRAINT_LABELS[k]))
    long_only = c[1].radio(t("Position mode"), [True, False], index=0 if s.long_only else 1, horizontal=True,
                           format_func=lambda x: t("Long-only") if x else t("Short selling (configured)"))
    minw = s.min_weight
    if not long_only:
        minw = c[1].number_input(t("Minimum weight per stock (%)"), -100.0, 0.0, float(min(s.min_weight * 100, 0.0)),
                                 1.0) / 100
    cap_w = c[2].number_input(t("Max weight per stock (% of total, 0 = none)"), 0.0, 100.0,
                              float((s.max_weight or 0.0) * 100), 1.0)
    new = dict(risk_free_annual=rf, cov_estimator=cov_e, mu_estimator=mu_e, constraint_mode=mode,
               long_only=long_only, min_weight=minw if not long_only else 0.0,
               max_weight=cap_w / 100 if cap_w > 0 else None)
    if any(getattr(s, k) != v for k, v in new.items()):
        for k, v in new.items():
            setattr(s, k, v)
        ui.persist_settings()
        st.rerun()

bundle = ui.get_analysis()
if bundle is None:
    st.stop()
h = ui.horizon_selector(bundle, "fr_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
if not r.analyzable:
    st.stop()
if s.constraint_mode == "global_only":
    st.warning(t("Unconstrained market-allocation mode: optimized portfolios may move capital between markets; only "
                 "the global budget and the bounds are enforced."), icon=":material/warning:")
fr = r.frontier
rf_m = rf_markowitz(s.risk_free_annual, s.periods_per_year)
assets = pd.DataFrame({"volatility": r.asset_stats["annual_volatility"], "return": r.mu})
colors = ui.security_colors(list(assets.index))
nm = ui.names(list(assets.index))
show_assets = st.toggle(t("Show individual assets"), value=True)
fig = charts.frontier_chart(fr, r.optimized, rf_m, t("Efficient frontier, {span} ({ccy})", h=h, ccy=s.base_currency),
                            assets if show_assets else None, colors if show_assets else None, cap, s.base_currency)
event = st.plotly_chart(fig, width="stretch", theme=None, on_select="rerun", selection_mode="points", key=f"fr_{h}")

# ---------------------------------------------------------------- inspect the clicked point
sel_w, sel_name, sel_ret, sel_vol = None, None, None, None
pts = (event.selection.points if event and getattr(event, "selection", None) else []) or []
if pts:
    pt = pts[0]
    cd = pt.get("customdata")
    key = cd[0] if isinstance(cd, (list, tuple)) and cd and isinstance(cd[0], str) else (cd if isinstance(cd, str) else None)
    if key in r.optimized:
        o = r.optimized[key]
        sel_w, sel_name, sel_ret, sel_vol = o.weights, o.name, o.expected_return, o.volatility
    elif fr is not None and not fr.points.empty:
        okp = fr.points[fr.points["ok"]]
        dist = (okp["volatility"] - pt.get("x", np.nan)) ** 2 + (okp["expected_return"] - pt.get("y", np.nan)) ** 2
        if dist.notna().any():
            row = okp.loc[dist.idxmin()]
            if row["target"] in fr.weights.index:
                sel_w = fr.weights.loc[row["target"]]
                sel_name = t("Frontier point")
                sel_ret, sel_vol = float(row["expected_return"]), float(row["volatility"])
        if sel_w is None and pt.get("text") in assets.index:
            tk = pt["text"]
            sel_w = pd.Series({tk: 1.0})
            sel_name, sel_ret, sel_vol = nm.get(tk, tk), float(assets.loc[tk, "return"]), float(
                assets.loc[tk, "volatility"])
if sel_w is None:
    o = r.optimized.get("max_sharpe")
    if o is not None and o.ok:
        sel_w, sel_name, sel_ret, sel_vol = o.weights, o.name, o.expected_return, o.volatility
        st.caption(t("Showing the maximum-Sharpe portfolio. Click any point of the chart to inspect another one."))
if sel_w is not None:
    with st.container(border=True):
        st.markdown(f"#### {sel_name}")
        sh = (sel_ret - rf_m) / sel_vol if sel_vol else np.nan
        m = st.columns(4)
        m[0].metric(t("Expected return"), ui.pct(sel_ret), t("Sharpe {value}", value=ui.num(sh, 2)),
                    delta_color="off", delta_arrow="off", border=True)
        m[1].metric(t("Volatility"), ui.pct(sel_vol), border=True)
        m[2].metric(t("Expected gain per year"), ui.fmt_compact(cap * sel_ret, sign=True), border=True,
                    help=t("Expected annual return × {capital}.", capital=ui.fmt_money(cap)))
        m[3].metric(t("Typical swing per year"), "± " + ui.fmt_compact(cap * sel_vol), border=True,
                    help=t("One standard deviation × {capital}: about two years out of three would land within this "
                           "distance of the expected gain if returns were normal. In-sample estimate, not a "
                           "forecast.", capital=ui.fmt_money(cap)))
        w = sel_w[sel_w.abs() > 1e-6]
        st.plotly_chart(charts.weights_stack({sel_name: w}, t("Composition"), ui.security_colors(list(w.index)),
                                             ui.names(list(w.index))), width="stretch", theme=None)

if fr is not None:
    c = st.columns(5)
    c[0].metric(t("Lowest return"), ui.pct(fr.r_min), border=True, help=t("Lowest feasible expected return."))
    c[1].metric(t("Highest return"), ui.pct(fr.r_max), border=True, help=t("Highest feasible expected return."))
    c[2].metric(t("Solved points"), f"{int(fr.points['ok'].sum())}/{len(fr.points)}", border=True)
    c[3].metric(t("GMV volatility"), ui.pct(fr.gmv.volatility if fr.gmv else None), border=True)
    c[4].metric(t("Tangency Sharpe"), ui.num(fr.tangency.sharpe if fr.tangency else None),
                t("identified") if fr.tangency else t("not identified"), delta_color="off", delta_arrow="off",
                border=True)
    for w_ in fr.warnings:
        st.warning(w_)
    with st.expander(t("Frontier points and weights"), icon=":material/table:"):
        ui.show_table(fr.points, pct=["target", "expected_return", "volatility"], num=["sharpe", "max_residual"],
                      num_digits=4)
        st.dataframe((fr.weights * 100).round(3), width="stretch")
    st.download_button(t("Download frontier (CSV)"), pd.concat([fr.points.set_index("target"), fr.weights], axis=1)
                       .to_csv().encode(), f"frontier_{tag(h)}.csv", "text/csv", icon=":material/download:")
with st.expander(t("How the frontier is built"), icon=":material/function:"):
    st.markdown(i18n.doc("frontier_method", points=s.frontier_points, rf=f"{rf_m:.2%}"))
ui.explain("explain_frontier", capital=ui.fmt_money(cap), ccy=s.base_currency)
ui.footer()
