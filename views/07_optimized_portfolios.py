"""Optimized Portfolios: cards, compositions, money results and every validation detail."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from src import charts, ui
from src.i18n import t
from src.money import money_summary, wealth_with_start
from src.optimization import target_volatility
from src.statistics import rf_markowitz

ui.page_header(t("Optimized Portfolios"), t("Each optimum is checked for solver status, constraint residuals and "
                                            "optimality before it is reported."))
s = ui.settings()
cap = ui.capital()
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
ui.intro(t("Eight ways to split the same markets, each optimized with the same data. The money figures replay each "
           "portfolio over the horizon with {capital}: they are in-sample (the optimizer already knew these returns), "
           "so the Backtesting lab is where they are tested fairly.", capital=ui.fmt_money(cap)))
h = ui.horizon_selector(bundle, "opt_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
if not r.analyzable:
    st.stop()
shrink = (t(" (Ledoit-Wolf shrinkage intensity {value})", value=f"{r.cov_info['shrinkage']:.3f}")
          if r.cov_info.get("shrinkage") is not None else "")
positions = t("long-only") if s.long_only else t("short selling, min weight {value}", value=f"{s.min_weight:.0%}")
capw = t("; max weight {value}", value=f"{s.max_weight:.0%}") if s.max_weight else ""
st.caption(t("Estimators: μ = **{mu}**, Σ = **{cov}**{shrink}; constraint mode **{mode}**; {positions}{cap}.",
             mu=t(ui.ESTIMATOR_LABELS[s.mu_estimator]), cov=t(ui.ESTIMATOR_LABELS[s.cov_estimator]), shrink=shrink,
             mode=t(ui.CONSTRAINT_LABELS[s.constraint_mode]), positions=positions, cap=capw))

user = r.optimized["user"]
start0 = r.prices.index[0]
replays = {k: r.returns @ o.weights.reindex(r.returns.columns).values for k, o in r.optimized.items() if o.ok}
ms = {k: money_summary(v, cap) for k, v in replays.items()}

# ---------------------------------------------------------------- cards
st.caption(t("What {capital} invested on {start} would be worth on {end} in each portfolio; the arrow is the "
             "difference with your portfolio.", capital=ui.fmt_compact(cap), start=f"{start0:%Y-%m-%d}",
             end=f"{r.end:%Y-%m-%d}"))
keys = [k for k in r.optimized if r.optimized[k].ok]
for row_start in range(0, len(keys), 4):
    cols = st.columns(4)
    for col, k in zip(cols, keys[row_start:row_start + 4]):
        o = r.optimized[k]
        with col.container(border=True):
            color = charts.strategy_color(k)
            st.markdown(f"<div style='display:flex;align-items:center;gap:8px'><span style='width:12px;height:12px;"
                        f"border-radius:3px;background:{color};display:inline-block'></span><b>{html.escape(o.name)}"
                        f"</b></div>", unsafe_allow_html=True)
            st.metric(t("Would be worth"), ui.fmt_compact(ms[k]["final"]),
                      ui.fmt_compact(ms[k]["final"] - ms["user"]["final"], sign=True) if k != "user" else None,
                      delta_color="normal" if k != "user" else "off")
            st.caption(t("Return {ret} · volatility {vol} · Sharpe {sh}", ret=ui.pct(o.expected_return),
                         vol=ui.pct(o.volatility), sh=ui.num(o.sharpe, 2)))
            st.caption(f"{t('Certification')}: {o.certification}")
st.warning(t("The maximum-risk portfolio is a risk-seeking mathematical benchmark, not an investment "
             "recommendation. The maximum-return portfolio concentrates each market budget in its highest "
             "historical-return stock unless a cap is set. Historical optima are not forecasts."),
           icon=":material/warning:")

# ---------------------------------------------------------------- compositions and paths
W = pd.DataFrame({o.name: o.weights for o in r.optimized.values()})
tickers = list(W.index)
colors = ui.security_colors(tickers)
nm = ui.names(tickers)
st.plotly_chart(charts.weights_stack({o.name: o.weights for o in r.optimized.values() if o.ok},
                                     t("How each portfolio splits the money ({span})", h=h), colors, nm),
                width="stretch", theme=None)
names_by_key = {k: o.name for k, o in r.optimized.items() if o.ok}
pick = st.pills(t("Compare"), list(names_by_key), selection_mode="multi", format_func=lambda k: names_by_key[k],
                default=[k for k in ("user", "min_variance", "max_sharpe") if k in names_by_key], key=f"opt_pick_{h}")
if pick:
    paths = {names_by_key[k]: wealth_with_start(replays[k], cap, start0) for k in pick}
    st.plotly_chart(ui.shade_reconstructed(charts.money_growth(
        paths, t("{capital} in each portfolio over {span} (in-sample replay)", capital=ui.fmt_compact(cap), h=h),
        s.base_currency, {names_by_key[k]: charts.strategy_color(k) for k in pick}), r),
                    width="stretch", theme=None)
    st.plotly_chart(charts.weights_bar({names_by_key[k]: W[names_by_key[k]] for k in pick},
                                       t("Weights comparison ({span})", h=h)), width="stretch", theme=None)

# ---------------------------------------------------------------- full tables
C_P, C_V, C_R, C_VOL = t("Portfolio"), t("Valid"), t("Expected return %"), t("Volatility %")
C_DR, C_DV, C_DS = t("Δ return vs user (pp)"), t("Δ vol vs user (pp)"), t("Δ Sharpe vs user")
C_CERT, C_METH, C_SOLV, C_RES = t("Certification"), t("Method"), t("Solver status"), t("Max residual")
C_FV, C_GAIN = t("Final value ({ccy})", ccy=s.base_currency), t("Gain ({ccy})", ccy=s.base_currency)
rows = []
for key, o in r.optimized.items():
    rows.append({C_P: o.name, C_V: t("yes") if o.ok else t("NO"), C_R: o.expected_return * 100,
                 C_VOL: o.volatility * 100, "Sharpe": o.sharpe,
                 C_FV: ms[key]["final"] if key in ms else None, C_GAIN: ms[key]["gain"] if key in ms else None,
                 C_DR: (o.expected_return - user.expected_return) * 100, C_DV: (o.volatility - user.volatility) * 100,
                 C_DS: (o.sharpe - user.sharpe) if o.sharpe is not None and user.sharpe is not None else None,
                 C_CERT: o.certification, C_METH: o.method, C_SOLV: str(o.status)[:60],
                 C_RES: o.summary()["max_residual"]})
with st.expander(t("Summary table (all portfolios)"), icon=":material/table:", expanded=False):
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in [C_R, C_VOL, C_DR, C_DV]}
                 | {"Sharpe": st.column_config.NumberColumn(format="%.4f"),
                    C_FV: st.column_config.NumberColumn(format="%,.0f"), C_GAIN: st.column_config.NumberColumn(format="%+,.0f"),
                    C_DS: st.column_config.NumberColumn(format="%.4f"),
                    C_RES: st.column_config.NumberColumn(format="%.2e")})
with st.expander(t("Weights (share of total portfolio)"), icon=":material/table:"):
    st.dataframe((W * 100).round(4), width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f%%") for c in W.columns})
    mk_of = {x.ticker: x.market_id for x in ui.portfolio().holdings}
    TOTAL = t("TOTAL")
    msum = W.groupby(lambda tk: mk_of.get(tk, "?")).sum()
    msum.loc[TOTAL] = W.sum()
    st.markdown(t("**Market sums check** (in fixed-market mode each must equal the configured allocation)"))
    target = pd.Series({**r.market_budgets, TOTAL: sum(r.market_budgets.values())}, name=t("Configured"))
    sums = pd.concat([target, msum], axis=1).mul(100).round(6)
    sums.index = [ui.market_name(m) if m != TOTAL else m for m in sums.index]
    st.dataframe(sums, width="stretch")

RES_LABELS = {"budget": t("Budget residual"), "lower_bound_violation": t("Lower-bound violation"),
              "upper_bound_violation": t("Upper-bound violation"), "market_max_abs": t("Largest market-sum residual"),
              "target_return": t("Target-return residual")}
st.markdown(t("#### Validation of each optimum"))
for key, o in r.optimized.items():
    with st.expander(t("{name}: details", name=o.name), icon=":material/check_circle:" if o.ok else ":material/error:"):
        st.markdown(t("Method: **{method}**. Certification: **{cert}**. Solver: {status}", method=o.method,
                      cert=o.certification, status=o.status))
        res_rows = [{t("Check"): RES_LABELS.get(k, k), t("Value"): f"{v:.2e}"} for k, v in o.residuals.items()
                    if isinstance(v, float)]
        if res_rows:
            st.dataframe(pd.DataFrame(res_rows), hide_index=True)
        if o.residuals.get("market_sums"):
            st.caption(t("Market sums: {sums}", sums=", ".join(f"{m} {v:.4%}" for m, v in
                                                               o.residuals["market_sums"].items())))
        for n in o.notes:
            st.write("- " + n)

st.subheader(t("Optional: maximum return at a target volatility"))
gmv = r.optimized["min_variance"]
with st.container(key="inputs_targetvol"):
    c1, c2 = st.columns([1, 1], vertical_alignment="bottom")
    tv = c1.number_input(t("Target annualized volatility (%)"), 0.0, 200.0,
                         float(round((gmv.volatility if gmv.ok else 0.2) * 100 + 2, 2)), 0.5)
    solve = c2.button(t("Solve target-volatility portfolio"), icon=":material/target:")
if solve:
    cs = r.constraints
    o = target_volatility(r.mu.reindex(cs.tickers).values, r.cov.reindex(index=cs.tickers, columns=cs.tickers).values,
                          cs, rf_markowitz(s.risk_free_annual, s.periods_per_year), tv / 100,
                          gmv.volatility if gmv.ok else None)
    msg = t("{name}: valid {ok}, return {ret}, volatility {vol}, Sharpe {sharpe}, {cert}.", name=o.name,
            ok=t("yes") if o.ok else t("no"), ret=ui.pct(o.expected_return), vol=ui.pct(o.volatility),
            sharpe=ui.num(o.sharpe), cert=o.certification)
    (st.success if o.ok else st.error)(msg + " " + " ".join(o.notes))
    if o.ok:
        c1, c2 = st.columns(2)
        c1.metric(t("Expected gain per year"), ui.fmt_compact(cap * o.expected_return, sign=True), border=True)
        c2.plotly_chart(charts.security_donut(o.weights, t("Composition"), colors, nm), width="stretch", theme=None)
        st.dataframe((o.weights * 100).rename(t("Weight %")).to_frame().T, width="stretch")
ui.explain("explain_optimized", capital=ui.fmt_money(cap))
ui.footer()
