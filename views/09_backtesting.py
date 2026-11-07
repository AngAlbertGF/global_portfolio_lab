"""Backtesting lab: train on a chosen period, decide and forecast, then compare with what really happened."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import charts, ui
from src.backtest_lab import (STRATEGIES, LabConfig, entry_date_sensitivity, forecast_paths, fx_shock_returns,
                              renormalized_without, replay, run_lab, strategy_weights, worst_window)
from src.i18n import t
from src.money import compact as money_compact
from src.optimization import ConstraintSet
from src.returns import conversion_details
from src.validation import global_weights, major_currency

ui.page_header(t("Backtesting lab"), t("Train a model with the data up to a date you choose, let it decide and "
                                       "forecast, then compare with what really happened afterwards."))
s = ui.settings()
p = ui.portfolio()
ss = st.session_state
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
ui.intro(t("The model only sees the training period. At its last day it chooses the weights of every strategy and "
           "draws a cone of possible futures. The test period then replays what actually happened, in money, with "
           "costs and optional monthly contributions — and checks how good the forecast was."))
st.warning(t("Disclosures: survivorship bias (today's chosen listings), provider revisions of adjusted prices, no "
             "taxes. Weights and forecasts use only data available before the test period (or before each "
             "re-estimation date in walk-forward mode)."), icon=":material/warning:")

raw = bundle.prices_base[[tk for tk in p.tickers if tk in bundle.prices_base.columns]]
firsts = {tk: raw[tk].first_valid_index() for tk in raw.columns}
recent = [tk for tk, f in firsts.items() if f is not None and f > raw.index[-1] - pd.Timedelta(days=730)]
long_ = [tk for tk in raw.columns if tk not in recent and firsts[tk] is not None]
short_lab = recent if (s.analysis_mode == "reconstructed" and recent and long_) else []
min_real = s.backfill_min_obs
if short_lab:   # long holdings' calendar; new listings stay empty before their first real price
    prices = raw.loc[raw[long_].notna().all(axis=1)]
    keep = pd.Series(True, index=prices.index)
    for tk in short_lab:
        keep &= (prices.index < firsts[tk]) | prices[tk].notna()
    prices = prices.loc[keep]
    real_ok = {tk: prices[tk].dropna().index[min(min_real, prices[tk].notna().sum() - 1)] for tk in short_lab}
    min_train_end = max(real_ok.values()).date()
    min_test_start = max(firsts[tk] for tk in short_lab).date() + timedelta(days=1)
else:
    prices = raw.dropna(how="any")
    min_train_end, min_test_start = None, None
if len(prices) < 120:
    st.error(t("Not enough common history for all holdings ({n} days).", n=len(prices)))
    st.stop()
first, last = prices.index[1].date(), prices.index[-1].date()
cap0 = ui.capital()
base = s.base_currency
if short_lab:
    st.info(t("**Reconstructed history in the lab.** {tickers} started trading recently. The lab trains with the full "
              "history of the other holdings; the earlier returns of the new listing are reconstructed with a model "
              "fitted only on its real returns up to the end of training (never on test data), and the test period "
              "uses real prices only. Training must end on or after {end}; the test must start after {start}.",
              tickers=", ".join(short_lab), end=min_train_end, start=min_test_start - timedelta(days=1)),
            icon=":material/auto_fix_high:")
elif recent and long_:
    st.info(t("The common history starts on {date} because {tickers} started trading then, so every strategy trains "
              "on that short period. Choose **Reconstructed history for IPOs** (Settings → Horizons and coverage, or "
              "the button on Portfolio Statistics) to train with the long history of the other holdings.",
              date=f"{prices.index[0]:%Y-%m-%d}", tickers=", ".join(recent)), icon=":material/info:")


def _defaults() -> tuple[tuple[date, date], tuple[date, date]]:
    te = date(2025, 12, 31)
    if min_train_end is not None:
        te = max(te, min_train_end, min_test_start)
    if not (first + timedelta(days=200) < te < last - timedelta(days=20)):
        te = (prices.index[int(len(prices) * 0.8)]).date()
        if min_train_end is not None:
            te = max(te, min_train_end, min_test_start)
    return (first, te), (te + timedelta(days=1), last)


def _preset() -> None:
    key = ss.get("lab_preset")
    trn, tst = _defaults()
    if key == "last12":
        cut = max(first + timedelta(days=200), last - timedelta(days=365))
        trn, tst = (first, cut), (cut + timedelta(days=1), last)
    elif key == "last36":
        cut = max(first + timedelta(days=200), last - timedelta(days=3 * 365))
        trn, tst = (first, cut), (cut + timedelta(days=1), last)
    elif key == "rolling3":
        cut = max(first + timedelta(days=200), last - timedelta(days=365))
        trn, tst = (max(first, cut - timedelta(days=3 * 365)), cut), (cut + timedelta(days=1), last)
    ss.lab_train, ss.lab_test = trn, tst


if "lab_train" not in ss:
    ss.lab_train, ss.lab_test = _defaults()
st.caption(t("Common history of all holdings in {base}: {start} to {end} ({n} days).", base=base, start=first, end=last,
             n=len(prices) - 1))
PRESETS = {"default": t("Train to 2025-12-31, test from 2026-01-01"), "last12": t("Test the last 12 months"),
           "last36": t("Test the last 3 years"), "rolling3": t("Train only on the 3 years before the last 12 months")}
st.pills(t("Quick periods"), list(PRESETS), format_func=lambda k: PRESETS[k], key="lab_preset", on_change=_preset)

with st.container(key="inputs_lab"):
    with st.form("lab_form", border=False):
        st.markdown(t("**1. Periods**"))
        c = st.columns(2)
        trn = c[0].date_input(t("Training period (the model sees only this)"), key="lab_train", min_value=first,
                              max_value=last, format="YYYY-MM-DD")
        tst = c[1].date_input(t("Test period (what really happened afterwards)"), key="lab_test", min_value=first,
                              max_value=last, format="YYYY-MM-DD")
        st.markdown(t("**2. Model**"))
        c = st.columns(4)
        strategies = c[0].multiselect(t("Strategies to compare"), list(STRATEGIES), format_func=lambda k: t(STRATEGIES[k]),
                                      default=["user", "equal_weight", "min_variance", "max_sharpe", "risk_parity"])
        mode = c[1].radio(t("How the model learns"), ["static", "walk_forward"],
                          format_func=lambda k: {"static": t("Trained once, then held"),
                                                 "walk_forward": t("Keeps learning (re-trains at each rebalance)")}[k])
        reb = c[2].selectbox(t("Rebalancing"), ["none", "monthly", "quarterly", "semiannual", "annual"], index=2,
                             format_func=lambda k: {"none": t("Never (buy and hold)"), "monthly": t("Monthly"),
                                                    "quarterly": t("Quarterly"), "semiannual": t("Every 6 months"),
                                                    "annual": t("Annual")}[k])
        window = c[3].selectbox(t("Learning window (walk-forward)"), ["expanding", "rolling"],
                                format_func=lambda k: t(ui.WINDOW_LABELS[k]))
        c = st.columns(4)
        roll_obs = c[0].number_input(t("Rolling window (observations)"), 60, 5000, 252)
        mu_e = c[1].selectbox(t("Expected-return estimator"), ["arithmetic", "geometric", "ewma"],
                              format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
        cov_e = c[2].selectbox(t("Covariance estimator"), ["ledoit_wolf", "sample", "ewma"],
                               format_func=lambda k: t(ui.ESTIMATOR_LABELS[k]))
        tvol = c[3].number_input(t("Target volatility (%)"), 1.0, 100.0, 20.0, 1.0)
        st.markdown(t("**3. Money and costs**"))
        c = st.columns(5)
        capital = c[0].number_input(t("Initial capital ({ccy})", ccy=base), 1.0, 1e12, float(cap0), 10000.0,
                                    format="%.0f")
        contrib = c[1].number_input(t("Monthly contribution ({ccy})", ccy=base), 0.0, 1e10, 0.0, 1000.0, format="%.0f",
                                    help=t("Invested on the first trading day of every month after the first."))
        cost = c[2].number_input(t("Commission (bps)"), 0.0, 500.0, 10.0)
        slip = c[3].number_input(t("Slippage (bps)"), 0.0, 500.0, 5.0)
        fxc = c[4].number_input(t("Currency conversion cost (bps)"), 0.0, 500.0, 20.0,
                                help=t("Extra cost on the traded value of securities in another currency."))
        st.markdown(t("**4. Forecast**"))
        c = st.columns(3)
        proj = c[0].selectbox(t("Forecast method"), ["bootstrap", "normal"],
                              format_func=lambda k: {"bootstrap": t("Historical bootstrap (resamples real days)"),
                                                     "normal": t("Normal distribution (μ and Σ)")}[k])
        paths = c[1].select_slider(t("Simulated paths"), [500, 1000, 2000, 5000], value=2000)
        block = c[2].number_input(t("Bootstrap block (days)"), 1, 252, 21)
        run = st.form_submit_button(t("Train, forecast and test"), type="primary", icon=":material/play_arrow:")


def _valid_range(v) -> tuple[date, date] | None:
    return (v[0], v[1]) if isinstance(v, (list, tuple)) and len(v) == 2 else None


trn_r, tst_r = _valid_range(trn), _valid_range(tst)
if trn_r and tst_r:
    fig = go.Figure()
    fig.add_trace(go.Bar(y=[""], x=[(pd.Timestamp(trn_r[1]) - pd.Timestamp(trn_r[0])).days * 864e5],
                         base=[pd.Timestamp(trn_r[0])], orientation="h", marker={"color": charts.C.series[0]},
                         name=t("Training"), hovertemplate=f"{trn_r[0]} → {trn_r[1]}<extra></extra>"))
    fig.add_trace(go.Bar(y=[""], x=[(pd.Timestamp(tst_r[1]) - pd.Timestamp(tst_r[0])).days * 864e5],
                         base=[pd.Timestamp(tst_r[0])], orientation="h", marker={"color": charts.C.series[1]},
                         name=t("Test"), hovertemplate=f"{tst_r[0]} → {tst_r[1]}<extra></extra>"))
    fig = charts._layout(fig, t("Timeline"), "", "", height=150)
    fig.update_xaxes(type="date", range=[pd.Timestamp(first), pd.Timestamp(last)])
    fig.update_layout(barmode="overlay", margin={"l": 20, "r": 20, "t": 40, "b": 30},
                      legend={"y": 1.25, "orientation": "h"})
    st.plotly_chart(fig, width="stretch", theme=None)

mkt = {h.ticker: h.market_id for h in p.holdings}
budgets = {m: a / 100 for m, a in p.market_allocations.items() if a > 0}
cs = ConstraintSet.build(p.tickers, mkt, budgets, s.constraint_mode, s.long_only, s.min_weight, s.max_weight)
foreign = {}
for tk in p.tickers:
    cur = (ui.db().get_security(tk) or {}).get("currency") or ""
    foreign[tk] = major_currency(cur)[0] not in ("", base)

if run:
    if not (trn_r and tst_r):
        st.error(t("Choose a start and an end date for both periods."))
    elif trn_r[1] >= tst_r[0]:
        st.error(t("The test period must start after the training period ends."))
    elif not strategies:
        st.error(t("Choose at least one strategy."))
    elif short_lab and trn_r[1] < min_train_end:
        st.error(t("{tickers} needs at least {n} real days inside the training period: end training on or after "
                   "{date}.", tickers=", ".join(short_lab), n=min_real, date=min_train_end))
    elif short_lab and tst_r[0] < min_test_start:
        st.error(t("The test must use real prices only: start it on or after {date}.", date=min_test_start))
    else:
        cfg = LabConfig(trn_r[0], trn_r[1], tst_r[0], tst_r[1], tuple(strategies), mode, window, int(roll_obs), reb,
                        mu_e, cov_e, s.ewma_lambda, float(capital), float(contrib), float(cost), float(slip), float(fxc),
                        tvol / 100, s.risk_free_annual, s.periods_per_year if s.return_frequency == "daily" else 252,
                        proj, int(paths), int(block))
        bench = None
        if s.benchmark_ticker:
            from src.returns import load_base_currency_prices
            bp, _ = load_base_currency_prices(ui.db(), [s.benchmark_ticker], base, s.fx_max_staleness_days)
            bench = bp[s.benchmark_ticker] if s.benchmark_ticker in bp.columns else None
        lab_px = prices
        ss.lab_recon = {}
        if short_lab:
            from src.backfill import reconstruct_frame
            from src.returns import simple_returns
            r_ = simple_returns(prices)
            fit = pd.Series(r_.index <= pd.Timestamp(trn_r[1]), index=r_.index)
            rf_p = (1 + s.risk_free_annual) ** (1 / 252) - 1
            from src.analysis import index_returns_on, load_index_prices
            ip_, in_ = load_index_prices(ui.db(), p, s, ui.markets())
            full, ss.lab_recon = reconstruct_frame(r_, short_lab, long_, mkt, global_weights(p), rf_p, 252,
                                                   index_returns_on(prices.index, ip_), in_, salt="lab",
                                                   fit_mask=fit)
            lab_px = pd.concat([pd.DataFrame(100.0, index=prices.index[:1], columns=full.columns),
                                100.0 * (1 + full).cumprod()])
        try:
            with st.spinner(t("Training the model, simulating {n} forecast paths and replaying the test period...",
                              n=f"{int(paths):,}")):
                ss.lab = run_lab(lab_px, global_weights(p), cs, cfg, foreign, bench)
        except ValueError as exc:
            st.error(str(exc))
            ss.lab = None

lab = ss.get("lab")
if lab is None:
    st.info(t("Choose the periods and select **Train, forecast and test**."), icon=":material/model_training:")
    ui.explain("explain_backtest", ccy=base)
    ui.footer()
    st.stop()

cfg = lab.config
runs = {k: r for k, r in lab.runs.items() if r.ok}
for k, r in lab.runs.items():
    if not r.ok:
        st.error(f"{r.label}: " + " ".join(r.notes))
if not runs:
    st.stop()
te = lab.test_returns
split = lab.train_returns.index[-1]
st.success(t("Trained on {a} to {b} ({n} days); tested on {c} to {d} ({m} days).", a=f"{lab.train_returns.index[0]:%Y-%m-%d}",
             b=f"{split:%Y-%m-%d}", n=len(lab.train_returns), c=f"{te.index[0]:%Y-%m-%d}", d=f"{te.index[-1]:%Y-%m-%d}",
             m=len(te)), icon=":material/check_circle:")
for tk_, rec_ in (ss.get("lab_recon") or {}).items():
    st.caption(t("Reconstructed in training: {ticker}, {share}% of the training days (real prices from {first}; factors "
                 "{factors}, R² {r2}). The test period uses only real prices.", ticker=tk_,
                 share=f"{100 * rec_.n_filled / max(len(lab.train_returns), 1):.0f}",
                 first=f"{rec_.first_real:%Y-%m-%d}" if rec_.first_real is not None else "–",
                 factors=", ".join(ui.factor_name(f) for f in rec_.factors), r2=f"{rec_.r2:.2f}"))
labels = {k: r.label for k, r in runs.items()}
colors = {r.label: charts.strategy_color(k) for k, r in runs.items()}
invested_total = next(iter(runs.values())).realized["invested"]
best = max(runs, key=lambda k: runs[k].realized["final_value"])

# ---------------------------------------------------------------- scoreboard
st.subheader(t("Result in money"))
k_ = st.columns(4)
u = runs.get("user") or runs[best]
k_[0].metric(t("Money invested"), ui.fmt_compact(invested_total),
             (t("+ {m} contributions", m=ui.fmt_compact(invested_total - cfg.capital)) if cfg.contribution else None),
             delta_color="off", delta_arrow="off", border=True)
spark = u.value.iloc[:: max(1, len(u.value) // 60)].round(0).tolist()
k_[1].metric(t("Final value: {name}", name=u.label if u.key != "user" else t("yours")), ui.fmt_compact(u.realized["final_value"]),
             ui.fmt_money(u.realized["gain"], sign=True), chart_data=spark, chart_type="area", border=True)
k_[2].metric(t("Best: {name}", name=runs[best].label), ui.fmt_compact(runs[best].realized["final_value"]),
             ui.fmt_money(runs[best].realized["gain"], sign=True), border=True)
k_[3].metric(t("Forecast for yours") if u.key == "user" else t("Forecast"), ui.fmt_compact(u.forecast["median_final"]),
             t("reality at percentile {p}", p=f"{u.forecast['realized_percentile']:.0%}"), delta_color="off",
             delta_arrow="off", border=True,
             help=t("Median of the simulated paths. The percentile tells where the real result fell among them: 50% = "
                    "as expected, below 5% or above 95% = outside the model's 90% range."))
finals = {r.label: r.realized["final_value"] for r in runs.values()}
if lab.benchmark is not None:
    finals[t("Benchmark {ticker}", ticker=s.benchmark_ticker)] = float(lab.benchmark["value"].iloc[-1])
    colors[t("Benchmark {ticker}", ticker=s.benchmark_ticker)] = charts.strategy_color("benchmark")
st.plotly_chart(charts.bars_money(finals, t("Final value by strategy ({a} to {b})", a=f"{te.index[0]:%Y-%m-%d}",
                                                                       b=f"{te.index[-1]:%Y-%m-%d}"), base, colors,
                                  reference=invested_total, ref_label=t("invested")), width="stretch", theme=None)

show = st.pills(t("Show on the chart"), list(runs), selection_mode="multi", format_func=lambda k: labels[k],
                default=[k for k in ("user", best, "min_variance") if k in runs], key="lab_show")
show_train = st.toggle(t("Also show the last year of training (rescaled so each line ends at your initial capital)"),
                       value=False)
paths_m = {labels[k]: runs[k].value for k in show or []}
if lab.benchmark is not None and st.session_state.get("lab_bench", True):
    paths_m[t("Benchmark {ticker}", ticker=s.benchmark_ticker)] = lab.benchmark["value"]
faded = {}
if show_train:
    for k in show or []:
        tv = runs[k].train_value.iloc[-252:]
        faded[labels[k]] = tv / tv.iloc[-1] * cfg.capital
invested = next(iter(runs.values())).invested if cfg.contribution else None
st.plotly_chart(charts.money_growth(paths_m, t("Value of your money: training (faded) and test (bold)"), base, colors,
                                    invested, split, faded), width="stretch", theme=None)

# ---------------------------------------------------------------- forecast vs reality
st.subheader(t("Forecast vs reality"))
sel = st.segmented_control(t("Strategy"), list(runs), format_func=lambda k: labels[k], default="user" if "user" in runs
                           else best, key="lab_sel") or best
R = runs[sel]
f = R.forecast
z = R.realized
hist = R.train_value / R.train_value.iloc[-1] * cfg.capital
st.plotly_chart(charts.fan_chart(f["bands"], R.value, t("{name}: forecast made on {date} vs what happened", name=R.label,
                                                        date=f"{split:%Y-%m-%d}"), base, charts.strategy_color(sel),
                                 R.invested if cfg.contribution else None, hist.iloc[-min(len(hist), 252):], split),
                width="stretch", theme=None)
pct = f["realized_percentile"]
if pct < 0.05:
    verdict = t("The model was **too optimistic**: reality fell below 95% of the simulated futures.")
elif pct > 0.95:
    verdict = t("The model was **too pessimistic**: reality beat 95% of the simulated futures.")
elif pct < 0.25:
    verdict = t("Reality was **worse than expected but plausible** (inside the model's 90% range).")
elif pct > 0.75:
    verdict = t("Reality was **better than expected but plausible** (inside the model's 90% range).")
else:
    verdict = t("Reality landed **close to what the model expected**.")
st.markdown(verdict)
m = st.columns(4)
m[0].metric(t("Forecast (median)"), ui.fmt_compact(f["median_final"]),
            t("90%: {lo} – {hi}", lo=money_compact(f["p5_final"]), hi=money_compact(f["p95_final"])),
            delta_color="off", delta_arrow="off", border=True)
m[1].metric(t("Real final value"), ui.fmt_compact(z["final_value"]), t("percentile {p}", p=f"{pct:.0%}"),
            delta_color="off", delta_arrow="off", border=True)
m[2].metric(t("Probability of loss (forecast)"), f"{f['prob_loss']:.0%}",
            t("real: {r}", r=t("loss") if z["gain"] < 0 else t("gain")), delta_color="off", delta_arrow="off", border=True)
m[3].metric(t("Days beyond VaR 95%"), f"{f['breaches']} / {len(te)}",
            t("expected {e} · p {p}", e=f"{f['expected_breaches']:.0f}", p=f"{f['kupiec_p']:.2f}"),
            delta_color="off", delta_arrow="off", border=True,
            help=t("A day is a breach when the loss exceeded the 95% VaR forecast from the training period. About 5% "
                   "of days should be breaches; Kupiec's p-value below 0.05 rejects the VaR forecast."))
m = st.columns(4)
m[0].metric(t("Return (time-weighted)"), ui.pct(z["twr_total"]), t("annualized {v}", v=ui.pct(z["twr_annual"])),
            delta_color="off", delta_arrow="off", border=True)
m[1].metric(t("IRR (money-weighted)"), ui.pct(z["irr"]), border=True,
            help=t("Annual return of your actual cash flows (initial capital and contributions)."))
m[2].metric(t("Real volatility"), ui.pct(z["volatility"], 1),
            t("forecast {v}", v=ui.pct(f["expected_volatility"], 1)), delta_color="off", delta_arrow="off", border=True)
m[3].metric(t("Costs paid"), ui.fmt_compact(z["costs"]), t("turnover {v}", v=ui.pct(z["turnover"], 0)),
            delta_color="off", delta_arrow="off", border=True)

with st.expander(t("Forecast scorecard (all strategies)"), icon=":material/table:", expanded=False):
    rows = []
    for k, r in runs.items():
        rows.append({t("Strategy"): r.label, t("Final value"): r.realized["final_value"],
                     t("Gain"): r.realized["gain"], t("Forecast median"): r.forecast["median_final"],
                     t("Forecast 5%"): r.forecast["p5_final"], t("Forecast 95%"): r.forecast["p95_final"],
                     t("Real percentile"): r.forecast["realized_percentile"] * 100,
                     t("Inside 90% range"): t("yes") if r.forecast["inside_90"] else t("no"),
                     t("Expected annual return %"): r.forecast["expected_annual_return"] * 100,
                     t("Real annualized return %"): r.realized["twr_annual"] * 100,
                     t("Expected volatility %"): r.forecast["expected_volatility"] * 100,
                     t("Real volatility %"): r.realized["volatility"] * 100,
                     t("Sharpe (real)"): r.realized["sharpe"], t("Max drawdown %"): r.realized["max_drawdown"] * 100,
                     t("VaR breaches"): r.forecast["breaches"], t("Kupiec p"): r.forecast["kupiec_p"],
                     t("IRR %"): r.realized["irr"] * 100, t("Costs"): r.realized["costs"],
                     t("Turnover %"): r.realized["turnover"] * 100})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%,.0f") for c in
                                (t("Final value"), t("Gain"), t("Forecast median"), t("Forecast 5%"), t("Forecast 95%"),
                                 t("Costs"))} |
                 {c: st.column_config.NumberColumn(format="%.2f") for c in
                  (t("Real percentile"), t("Expected annual return %"), t("Real annualized return %"),
                   t("Expected volatility %"), t("Real volatility %"), t("Max drawdown %"), t("IRR %"), t("Turnover %"),
                   t("Sharpe (real)"), t("Kupiec p"))})

# ---------------------------------------------------------------- inside one strategy
st.subheader(t("Inside the strategy: {name}", name=R.label))
tickers = list(R.train_weights.index)
scol = ui.security_colors(tickers)
nm = ui.names(tickers)
logos = ui.logo_uris(tickers)
tab_w, tab_c, tab_r = st.tabs([t("Weights"), t("Who made the money"), t("Risk in the test")])
with tab_w:
    a, b = st.columns(2)
    a.plotly_chart(charts.security_donut(R.train_weights, t("Weights chosen at the end of training"), scol, nm),
                   width="stretch", theme=None)
    b.plotly_chart(charts.weights_area(R.weights_path, t("Weights during the test (drift and rebalancing)"), scol),
                   width="stretch", theme=None)
    if len(R.decisions):
        with st.expander(t("Target weights at each decision date ({n})", n=len(R.decisions))):
            st.dataframe((R.decisions * 100).round(2), width="stretch")
with tab_c:
    st.plotly_chart(charts.contribution_bars(R.contrib_money, t("Money made by each security in the test ({ccy})",
                                                                 ccy=base), base, scol, nm, logos),
                    width="stretch", theme=None)
    st.caption(t("Sum of contributions {s} − costs {c} = gain {g}.", s=ui.fmt_money(R.contrib_money.sum(), sign=True),
                 c=ui.fmt_money(z["costs"]), g=ui.fmt_money(z["gain"], sign=True)))
with tab_r:
    a, b = st.columns(2)
    a.plotly_chart(charts.drawdown_chart(R.twr, t("Drawdown in the test")), width="stretch", theme=None)
    b.plotly_chart(charts.monthly_heatmap(R.twr, t("Monthly returns in the test")), width="stretch", theme=None)

# ---------------------------------------------------------------- what if
st.subheader(t("What if…?"))
wi = st.tabs([t("…I had invested on another date?"), t("…the exchange rate had not moved?"),
              t("…the currency had moved more?"), t("…I had left out some stocks?"),
              t("…the worst streak of the training repeated?"), t("…I look forward from today?")])
with wi[0]:
    weights = {labels[k]: runs[k].train_weights.values for k in runs}
    ed = entry_date_sensitivity(te, weights, cfg.capital)
    fig = go.Figure()
    for name in ed.columns:
        fig.add_trace(go.Scatter(x=ed.index, y=ed[name], mode="lines+markers", name=name,
                                 line={"color": colors.get(name), "width": 2},
                                 hovertemplate="%{x|%Y-%m}: %{y:,.0f} " + base + "<extra>" + name + "</extra>"))
    fig.add_hline(y=cfg.capital, line={"color": charts.C.axis, "dash": "dot"})
    fig = charts._layout(fig, t("Value at {end} of {capital} invested at the start of each month",
                                end=f"{te.index[-1]:%Y-%m-%d}", capital=ui.fmt_compact(cfg.capital)),
                         t("Month of entry"), t("Value ({ccy})", ccy=base))
    fig.update_yaxes(tickformat=",.0f")
    st.plotly_chart(fig, width="stretch", theme=None)
    st.caption(t("Each point invests the whole capital once, with the training weights held constant (no costs, no "
                 "contributions)."))
with wi[1]:
    det = conversion_details(ui.db(), tickers, base, s.fx_max_staleness_days)
    loc = pd.DataFrame({tk: det[tk]["detail"]["price_major"] for tk in tickers if tk in det}).sort_index()
    loc = loc.reindex(prices.index, method="ffill")
    lr = (loc / loc.shift(1) - 1).reindex(te.index).fillna(0.0)[tickers]
    w0 = R.train_weights.values
    a_ = replay(te, w0, cfg.capital, lab.flows)
    b_ = replay(lr, w0, cfg.capital, lab.flows)
    st.metric(t("Currency effect on {name}", name=R.label), ui.fmt_money(a_.iloc[-1] - b_.iloc[-1], sign=True),
              t("with currency {a} · without {b}", a=ui.fmt_compact(a_.iloc[-1]), b=ui.fmt_compact(b_.iloc[-1])),
              delta_color="off", delta_arrow="off", border=True)
    st.plotly_chart(charts.money_growth({t("Actual (in {base})", base=base): a_, t("Without currency moves"): b_},
                                        t("With and without the exchange-rate effect (constant weights, no costs)"),
                                        base, {t("Actual (in {base})", base=base): charts.strategy_color(sel),
                                               t("Without currency moves"): charts.strategy_color("benchmark")}),
                    width="stretch", theme=None)
with wi[2]:
    shock = st.slider(t("Extra move of foreign currencies against {base} over the test (%)", base=base), -40, 40, -10,
                      help=t("Negative = the {base} strengthens (foreign stocks are worth less in {base}).", base=base))
    shocked = fx_shock_returns(te, foreign, shock / 100)
    a_ = replay(te, R.train_weights.values, cfg.capital, lab.flows)
    b_ = replay(shocked, R.train_weights.values, cfg.capital, lab.flows)
    st.metric(t("Final value with that currency move"), ui.fmt_compact(b_.iloc[-1]),
              ui.fmt_money(b_.iloc[-1] - a_.iloc[-1], sign=True) + " " + t("vs actual"), border=True)
    st.plotly_chart(charts.money_growth({t("Actual"): a_, t("With the extra currency move"): b_},
                                        t("Currency stress on {name}", name=R.label), base,
                                        {t("Actual"): charts.strategy_color(sel),
                                         t("With the extra currency move"): charts.C.series[7]}),
                    width="stretch", theme=None)
with wi[3]:
    drop = st.multiselect(t("Leave out"), tickers, format_func=lambda x: f"{nm.get(x, x)} ({x})", key="lab_drop")
    if drop and len(drop) < len(tickers):
        uw = global_weights(p).reindex(tickers).fillna(0.0)
        w2 = renormalized_without(uw, mkt, drop)
        a_ = replay(te, uw.values, cfg.capital, lab.flows)
        b_ = replay(te, w2.values, cfg.capital, lab.flows)
        st.metric(t("Your portfolio without them"), ui.fmt_compact(b_.iloc[-1]),
                  ui.fmt_money(b_.iloc[-1] - a_.iloc[-1], sign=True) + " " + t("vs actual"), border=True)
        st.plotly_chart(charts.money_growth({t("Your portfolio"): a_, t("Without the selected stocks"): b_},
                                            t("Effect of leaving stocks out (constant weights, no costs)"), base,
                                            {t("Your portfolio"): charts.strategy_color("user"),
                                             t("Without the selected stocks"): charts.C.series[4]}),
                        width="stretch", theme=None)
        st.caption(t("The weight of the removed stocks is re-split inside their market; a market left empty gives its "
                     "budget to the others in proportion."))
    else:
        st.caption(t("Choose one or more stocks to see what the test period would have looked like without them."))
with wi[4]:
    days = st.select_slider(t("Streak length"), [5, 21, 63, 126], value=21,
                            format_func=lambda d: {5: t("1 week"), 21: t("1 month"), 63: t("3 months"),
                                                   126: t("6 months")}[d])
    port_tr = pd.Series(lab.train_returns.values @ R.train_weights.values, index=lab.train_returns.index)
    loss, a0, a1 = worst_window(port_tr, days)
    if a0 is None:
        st.caption(t("The training period is shorter than that streak."))
    else:
        st.metric(t("If it repeated right after training"), ui.fmt_compact(cfg.capital * loss, sign=True),
                  t("{p} between {a} and {b}", p=ui.pct(loss), a=f"{a0:%Y-%m-%d}", b=f"{a1:%Y-%m-%d}"),
                  delta_color="off", delta_arrow="off", border=True)
        st.caption(t("The worst {n}-day stretch the model saw in training, applied to {capital} with the same weights.",
                     n=days, capital=ui.fmt_money(cfg.capital)))
with wi[5]:
    months = st.slider(t("Months ahead"), 1, 36, 12)
    full = pd.concat([lab.train_returns, te])
    w_new, why = strategy_weights(sel, full, cs, global_weights(p).reindex(cs.tickers).fillna(0.0).values, cfg)
    if w_new is None:
        st.error(why)
    else:
        n_steps = int(months * 21)
        future_idx = pd.bdate_range(te.index[-1] + pd.Timedelta(days=1), periods=n_steps)
        months_idx = future_idx.to_period("M")
        fl = np.zeros(n_steps)
        if cfg.contribution:
            fl[np.r_[False, months_idx[1:] != months_idx[:-1]]] = cfg.contribution
        mu_p = float(full.mean().values @ w_new)
        sd_p = float(np.sqrt(max(w_new @ full.cov().values @ w_new, 0.0)))
        start_val = float(R.value.iloc[-1])
        sims = forecast_paths(full.values @ w_new, mu_p, sd_p, n_steps, start_val, fl, cfg.projection, cfg.n_paths,
                              cfg.block, cfg.seed + 99)
        bands = pd.DataFrame(np.percentile(sims, [5, 25, 50, 75, 95], axis=0).T, index=future_idx,
                             columns=["p5", "p25", "p50", "p75", "p95"])
        fin = sims[:, -1]
        c = st.columns(3)
        c[0].metric(t("Median in {m} months", m=months), ui.fmt_money(float(np.median(fin))), border=True)
        c[1].metric(t("Pessimistic (5%)"), ui.fmt_compact(float(np.percentile(fin, 5))), border=True)
        c[2].metric(t("Optimistic (95%)"), ui.fmt_compact(float(np.percentile(fin, 95))), border=True)
        st.plotly_chart(charts.fan_chart(bands, R.value.iloc[-min(len(R.value), 126):],
                                         t("{name}: possible paths for the next {m} months (model re-trained on all "
                                           "data up to {d})", name=R.label, m=months, d=f"{te.index[-1]:%Y-%m-%d}"),
                                         base, charts.strategy_color(sel)), width="stretch", theme=None)
        st.caption(t("A projection, not a prediction: it assumes the future behaves like the resampled past. "
                     "Re-trained weights: {w}.", w=", ".join(f"{tk} {v:.0%}" for tk, v in zip(cs.tickers, w_new)
                                                             if v > 0.005)))

# ---------------------------------------------------------------- downloads
with st.expander(t("Downloads and notes"), icon=":material/download:"):
    daily = pd.concat({labels[k]: r.value for k, r in runs.items()}, axis=1)
    st.download_button(t("Daily values of every strategy (CSV)"), daily.to_csv().encode(), "backtest_values.csv",
                       "text/csv", icon=":material/download:")
    twr = pd.concat({labels[k]: r.twr for k, r in runs.items()}, axis=1)
    st.download_button(t("Daily returns of every strategy (CSV)"), twr.to_csv().encode(), "backtest_returns.csv",
                       "text/csv", icon=":material/download:")
    st.download_button(t("Configuration (JSON)"), json.dumps({k: str(v) for k, v in cfg.__dict__.items()},
                                                             indent=2).encode(), "backtest_config.json",
                       "application/json", icon=":material/download:")
    for r in runs.values():
        for n in r.notes:
            st.caption(f"{r.label}: {n}")
ui.explain("explain_backtest", ccy=base)
ui.footer()
