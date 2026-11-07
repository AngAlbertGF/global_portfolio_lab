"""Exports: CSV (zip), Excel, PNG figures, HTML report, PDF report, configuration snapshot.

Every export is generated from the same AnalysisBundle object the UI displays, so exported
statistics match the on-screen values by construction (an acceptance test checks this).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import AnalysisBundle, HorizonResult
from .config import APP_NAME, APP_VERSION, PROVIDER_NAME
from .database import Database
from .i18n import doc, get_language, t, years
from .horizons import sheet_prefix, tag
from .labels import CONSTRAINT_LABELS, ESTIMATOR_LABELS, STAT_LABELS, col_label, status_label
from .returns import simple_returns


def _jsonable(o):
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Series, pd.DataFrame)):
        return o.to_dict()
    return str(o)


def provider_label(bundle: AnalysisBundle) -> str:
    from .synthetic import SYNTHETIC_PROVIDER

    return SYNTHETIC_PROVIDER if bundle.config["settings"].get("use_demo_database") else PROVIDER_NAME


def config_snapshot(bundle: AnalysisBundle) -> str:
    return json.dumps({"application": f"{APP_NAME} {APP_VERSION}", "calculated_at": bundle.created_at,
                       "data_cutoff": bundle.data_cutoff, "data_provider": provider_label(bundle),
                       "data_version": bundle.data_version, **bundle.config}, indent=2, default=_jsonable,
                      ensure_ascii=False)


def stats_frame(stats: dict) -> pd.DataFrame:
    return pd.DataFrame({"statistic": list(stats.keys()), "value": [_jsonable(v) if not isinstance(v, (int, float))
                                                                    else v for v in stats.values()]})


def optimized_tables(r: HorizonResult) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = pd.DataFrame([o.summary() for o in r.optimized.values()])
    weights = pd.DataFrame({o.name: o.weights for o in r.optimized.values()})
    return summary, weights


def build_tables(bundle: AnalysisBundle, db: Database | None = None) -> dict[str, pd.DataFrame]:
    p = bundle.config["portfolio"]
    s = bundle.config["settings"]
    out: dict[str, pd.DataFrame] = {}
    out["configuration"] = pd.DataFrame(
        [("portfolio_name", p["name"]), ("base_currency", s["base_currency"]), ("total_capital", p["total_capital"]),
         ("risk_free_annual_effective", s["risk_free_annual"]), ("return_frequency", s["return_frequency"]),
         ("expected_return_estimator", s["mu_estimator"]), ("covariance_estimator", s["cov_estimator"]),
         ("constraint_mode", s["constraint_mode"]), ("long_only", s["long_only"]), ("max_weight", s["max_weight"]),
         ("analysis_mode", s["analysis_mode"]), ("min_observations", s["min_observations"]),
         ("calculated_at", bundle.created_at), ("data_cutoff", bundle.data_cutoff), ("provider", provider_label(bundle))],
        columns=["parameter", "value"])
    out["market_allocations"] = pd.DataFrame([{"market_id": m, "allocation_pct": a}
                                            for m, a in p["market_allocations"].items() if a > 0])
    alloc = p["market_allocations"]
    out["security_weights"] = pd.DataFrame([{"ticker": h["ticker"], "market_id": h["market_id"],
                                           "within_market_pct": h["within_pct"],
                                           "total_weight_pct": alloc.get(h["market_id"], 0) * h["within_pct"] / 100}
                                          for h in p["holdings"]])
    tickers = [h["ticker"] for h in p["holdings"]]
    if not bundle.metadata.empty:
        out["security_metadata"] = bundle.metadata.loc[[x for x in tickers if x in bundle.metadata.index]].reset_index()
    out["fx_conversion_report"] = bundle.conversion_report
    if db is not None:
        local = db.get_prices_wide(tickers, "adj_close")
        out["adj_prices_local"] = local.reset_index().rename(columns={"index": "date"})
    out["prices_base_ccy"] = bundle.prices_base.reset_index().rename(columns={"index": "date"})
    common = bundle.prices_base.dropna(how="any")
    out["returns_base_ccy_common"] = simple_returns(common).reset_index().rename(columns={"index": "date"})
    out["cross_horizon"] = bundle.comparison_table()
    capital = float(p.get("total_capital") or s.get("default_capital") or 100_000.0)
    for h, r in bundle.horizons.items():
        pre = sheet_prefix(h)
        meta = {"horizon": years(h), "horizon_years": round(float(h), 2), "status": r.status, "mode": r.label, "start": r.start, "end": r.end,
                "n_obs": r.n_obs, "excluded": ", ".join(r.excluded), "warnings": " | ".join(r.warnings)}
        out[pre + "info"] = pd.DataFrame(list(meta.items()), columns=["field", "value"])
        if not r.coverage.empty:
            out[pre + "coverage"] = r.coverage.reset_index()
        if r.reconstructed:
            out[pre + "reconstructed"] = pd.DataFrame([rec.to_dict() for rec in r.reconstructed.values()])
        if not r.analyzable:
            continue
        out[pre + "user_stats"] = stats_frame(r.user_stats)
        out[pre + "asset_stats"] = r.asset_stats.reset_index()
        out[pre + "covariance"] = r.cov.reset_index().rename(columns={"index": "ticker"})
        out[pre + "correlation"] = r.corr.reset_index().rename(columns={"index": "ticker"})
        out[pre + "expected_returns"] = r.mu.rename("expected_return_annual").reset_index()
        out[pre + "risk_decomposition"] = r.risk_decomp.reset_index()
        out[pre + "money"] = money_table(r, capital)
        summ, w = optimized_tables(r)
        out[pre + "optimized_summary"] = summ
        out[pre + "optimized_weights"] = w.reset_index().rename(columns={"index": "ticker"})
        if r.frontier is not None and not r.frontier.points.empty:
            out[pre + "frontier_points"] = r.frontier.points
            out[pre + "frontier_weights"] = r.frontier.weights.reset_index().rename(columns={"index": "target_return"})
    if db is not None:
        tick = tickers
        acts = db.get_actions()
        out["corporate_actions"] = acts[acts["ticker"].isin(tick)] if not acts.empty else acts
        reps = db.get_repairs()
        out["price_repairs"] = reps[reps["ticker"].isin(tick)] if not reps.empty else reps
        out["download_log"] = db.get_download_log(5000)
        integ = db.integrity_check()
        out["data_quality"] = pd.DataFrame(list(integ.items()), columns=["check", "result"])
    return out


def money_table(r: HorizonResult, capital: float) -> pd.DataFrame:
    """What ``capital`` would have become in each portfolio over the horizon (in-sample replay, constant weights)."""
    from .money import money_summary

    rows = []
    for key, o in r.optimized.items():
        if not o.ok:
            continue
        rp = r.returns @ o.weights.reindex(r.returns.columns).values
        m = money_summary(rp, capital)
        rows.append({"portfolio": o.name, "capital": capital, "final_value": m["final"], "gain": m["gain"],
                     "total_return": m["total_return"], "max_drawdown_money": m["max_drawdown_money"],
                     "best_period_gain": m["best_period_gain"], "worst_period_loss": m["worst_period_loss"]})
    return pd.DataFrame(rows)


def _sheet_name(name: str, used: set[str]) -> str:
    base = name[:31]
    k, out = 1, base
    while out in used:
        suffix = f"_{k}"
        out = base[:31 - len(suffix)] + suffix
        k += 1
    used.add(out)
    return out


def to_excel_bytes(tables: dict[str, pd.DataFrame], config_json: str) -> bytes:
    buf = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame({"analysis_configuration_json": config_json.splitlines()}).to_excel(
            xw, sheet_name=_sheet_name("README_config", used), index=False)
        for name, df in tables.items():
            out = df.copy()
            for c in out.columns:
                if isinstance(out[c].dtype, pd.DatetimeTZDtype):
                    out[c] = out[c].dt.tz_localize(None)
                if out[c].dtype == object:
                    out[c] = out[c].map(lambda v: json.dumps(v, default=_jsonable) if isinstance(v, (dict, list))
                                        else v)
            out.to_excel(xw, sheet_name=_sheet_name(name, used), index=False)
    return buf.getvalue()


def to_csv_zip_bytes(tables: dict[str, pd.DataFrame], config_json: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("analysis_configuration.json", config_json)
        for name, df in tables.items():
            z.writestr(f"{name}.csv", df.to_csv(index=False))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Static figures (matplotlib) for PNG and PDF
# ---------------------------------------------------------------------------
def _mpl():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": "#c5ccd6", "axes.grid": True, "grid.color": "#e6e9ef",
                         "axes.facecolor": "#ffffff", "figure.facecolor": "#ffffff", "text.color": "#142033",
                         "axes.labelcolor": "#4a5568", "xtick.color": "#7b8494", "ytick.color": "#7b8494",
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def frontier_png(r: HorizonResult, rf: float, currency: str) -> bytes:
    from .charts import PORTFOLIO_STYLE

    plt = _mpl()
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=150)
    symbols = {"star": "*", "circle": "o", "diamond": "D", "triangle-up": "^", "x": "X", "square": "s",
               "pentagon": "p", "hexagon": "h"}
    if r.frontier is not None:
        e, ie = r.frontier.efficient, r.frontier.inefficient
        ax.plot(e["volatility"], e["expected_return"], color="#142033", lw=2, label=t("Efficient frontier"))
        if not ie.empty:
            ax.plot(ie["volatility"], ie["expected_return"], color="#7b8494", lw=1.5, ls=":",
                    label=t("Inefficient branch"))
    for key, (label_key, color, sym) in PORTFOLIO_STYLE.items():
        o = r.optimized.get(key)
        if o is not None and o.ok:
            label = t(label_key)
            ax.scatter([o.volatility], [o.expected_return], s=150 if sym == "star" else 70, color=color,
                       marker=symbols[sym], label=label, edgecolors="#ffffff", zorder=5)
            if key in ("user", "min_variance", "max_sharpe"):
                ax.annotate(label, (o.volatility, o.expected_return), xytext=(6, 2), textcoords="offset points",
                            fontsize=7, color="#4a5568")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax.set_xlabel(t("Annualized volatility"))
    ax.set_ylabel(t("Expected annualized return"))
    ax.set_title(t("Efficient frontier, horizon {period} ({ccy}), {start} to {end}, n={n}", h=r.horizon, ccy=currency,
                   start=f"{r.start:%Y-%m-%d}", end=f"{r.end:%Y-%m-%d}", n=r.n_obs), fontsize=9, loc="left")
    ax.legend(fontsize=7, loc="lower right", frameon=False)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def cumulative_png(r: HorizonResult, currency: str) -> bytes:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    w = (1 + r.portfolio_returns).cumprod() - 1
    ax.plot(w.index, w.values, color="#2a78d6", lw=1.6, label=t("User portfolio"))
    if r.benchmark_returns is not None and len(r.benchmark_returns):
        b = (1 + r.benchmark_returns).cumprod() - 1
        ax.plot(b.index, b.values, color="#eb6834", lw=1.4, label=t("Benchmark"))
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0%}")
    ax.set_title(t("Cumulative return in {ccy}, horizon {period}", ccy=currency, h=r.horizon), fontsize=9, loc="left")
    ax.legend(fontsize=7, frameon=False)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML report (in the active interface language)
# ---------------------------------------------------------------------------
def _display(df: pd.DataFrame) -> pd.DataFrame:
    """Translate column headers and status codes for human-facing reports."""
    out = df.copy()
    for c in ("status", "download_status", "validation_status", "branch"):
        if c in out.columns:
            out[c] = out[c].map(status_label)
    out.columns = [col_label(c) for c in out.columns]
    return out


def _df_html(df: pd.DataFrame, pct_cols: tuple[str, ...] | list[str] = (), digits: int = 4) -> str:
    out = df.copy()
    for c in out.columns:
        if c in pct_cols:
            out[c] = out[c].map(lambda v: f"{v:.2%}" if isinstance(v, (float, int, np.floating)) and
                                pd.notna(v) else v)
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].map(lambda v: f"{v:.{digits}f}" if pd.notna(v) else "")
    return _display(out).to_html(index=False, border=0, classes="tbl", escape=True)


def _stats_display(stats: dict) -> pd.DataFrame:
    rows = []
    for k, v in stats.items():
        label = t(STAT_LABELS[k]) if k in STAT_LABELS else k.replace("_", " ")
        if isinstance(v, (pd.Timestamp, datetime)):
            val = f"{v:%Y-%m-%d}"
        elif isinstance(v, (float, np.floating)):
            val = f"{v:.4f}"
        else:
            val = str(v)
        rows.append({t("Statistic"): label, t("Value"): val})
    return pd.DataFrame(rows)


def html_report(bundle: AnalysisBundle, horizon: int, include_plotlyjs: str = "cdn") -> str:
    """Self-contained HTML report; always uses the light palette (reports are printed and shared)."""
    from .charts import _mode as chart_mode

    token = chart_mode.set("light")
    try:
        return _html_report(bundle, horizon, include_plotlyjs)
    finally:
        chart_mode.reset(token)


def _html_report(bundle: AnalysisBundle, horizon: int, include_plotlyjs: str = "cdn") -> str:
    import html as _html

    from .charts import correlation_heatmap, cross_horizon_chart, cumulative_chart, frontier_chart, \
        market_donut, risk_contribution_bar, security_treemap
    from .config import DEFAULT_MARKETS
    from .statistics import rf_markowitz

    s = bundle.config["settings"]
    p = bundle.config["portfolio"]
    r = bundle.horizons[horizon]
    ccy = s["base_currency"]
    n = 52 if s["return_frequency"] == "weekly" else 252
    first = [True]

    def fig_html(fig) -> str:
        inc = include_plotlyjs if first[0] else False
        first[0] = False
        return fig.to_html(full_html=False, include_plotlyjs=inc, config={"displaylogo": False})

    tables = build_tables(bundle)
    market_of = {h["ticker"]: h["market_id"] for h in p["holdings"]}
    from .validation import Portfolio, global_weights
    pf = Portfolio.from_dict(p)
    w = global_weights(pf)
    names = {k: t(m.name) for k, m in DEFAULT_MARKETS.items()}
    esc = _html.escape
    parts = [f"<h1>{esc(t('{app}: portfolio report', app=APP_NAME))}</h1>"]
    if s.get("use_demo_database"):
        parts.append(f"<p class='warn'><b>{esc(t('SYNTHETIC DEMO DATA'))}</b>: "
                     f"{esc(t('illustrative only, not market prices.'))}</p>")
    parts.append("<p class='meta'>" + esc(t("Portfolio {name}; base currency {ccy}; calculated {created}; data cutoff "
                                            "{cutoff}; provider: {provider}", name=p["name"], ccy=ccy,
                                            created=bundle.created_at, cutoff=bundle.data_cutoff,
                                            provider=provider_label(bundle))) + "</p>")

    def h2(num: int, title: str) -> None:
        parts.append(f"<h2>{num}. {esc(title)}</h2>")

    h2(1, t("Executive summary"))
    if r.analyzable:
        us = r.user_stats
        ms = r.optimized.get("max_sharpe")
        mv = r.optimized.get("min_variance")
        parts.append("<p>" + esc(t("Horizon {period} ({label}): {start} to {end}, {n} observations. User portfolio: "
                                   "annualized arithmetic return {ret}, CAGR {cagr}, volatility {vol}, Sharpe {sharpe}, "
                                   "maximum drawdown {mdd}.", h=horizon, label=r.label, start=f"{r.start:%Y-%m-%d}",
                                   end=f"{r.end:%Y-%m-%d}", n=r.n_obs, ret=f"{us['annual_arithmetic_return']:.2%}",
                                   cagr=f"{us['annual_geometric_return_cagr']:.2%}",
                                   vol=f"{us['annual_volatility']:.2%}", sharpe=f"{us['sharpe_annual']:.3f}",
                                   mdd=f"{us['max_drawdown']:.2%}")) + "</p>")
        if mv and mv.ok:
            txt = t("In-sample minimum-variance portfolio: volatility {vol}.", vol=f"{mv.volatility:.2%}")
            if ms and ms.ok and ms.sharpe is not None:
                txt += " " + t("In-sample maximum-Sharpe portfolio: Sharpe {sharpe}.", sharpe=f"{ms.sharpe:.3f}")
            txt += " " + t("These are historical, in-sample results.")
            parts.append("<p>" + esc(txt) + "</p>")
    else:
        parts.append("<p class='warn'>" + esc(t("The horizon of {period} is {status}:", h=horizon,
                                                status=status_label(r.status))) + " "
                     + esc(" ".join(r.warnings)) + "</p>")
    h2(2, t("Portfolio composition"))
    parts.append(fig_html(market_donut(p["market_allocations"], names)))
    parts.append(fig_html(security_treemap(w, market_of, [m for m, a in p["market_allocations"].items() if a > 0],
                                           names)))
    parts.append(_df_html(tables["security_weights"]))
    h2(3, t("Data sources and coverage"))
    parts.append(_df_html(bundle.conversion_report.drop(columns=["notes"], errors="ignore")))
    if not r.coverage.empty:
        parts.append(_df_html(r.coverage.reset_index()))
    if r.reconstructed:
        parts.append("<p class='warn'>" + esc(t("Reconstructed history (estimated, not market data):")) + "</p>")
        parts.append(_df_html(pd.DataFrame([rec.to_dict() for rec in r.reconstructed.values()])))
    parts.append("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in r.warnings + bundle.warnings) + "</ul>")
    h2(4, t("Methodology and assumptions"))
    parts.append(doc("report_methodology"))
    shrink = (t(" (shrinkage {value})", value=f"{r.cov_info['shrinkage']:.3f}")
              if r.cov_info.get("shrinkage") is not None else "")
    parts.append("<p>" + esc(t("Estimators: expected return {mu}, covariance {cov}{shrink}; risk-free {rf} effective "
                               "annual (assumption); constraint mode {mode}; long-only {lo}.",
                               mu=t(ESTIMATOR_LABELS.get(s["mu_estimator"], s["mu_estimator"])),
                               cov=t(ESTIMATOR_LABELS.get(s["cov_estimator"], s["cov_estimator"])), shrink=shrink,
                               rf=f"{s['risk_free_annual']:.2%}",
                               mode=t(CONSTRAINT_LABELS.get(s["constraint_mode"], s["constraint_mode"])),
                               lo=t("yes") if s["long_only"] else t("no"))) + "</p>")
    if r.analyzable:
        h2(5, t("Historical performance"))
        series = {t("User portfolio"): r.portfolio_returns}
        if r.benchmark_returns is not None and len(r.benchmark_returns):
            series[t("Benchmark")] = r.benchmark_returns
        parts.append(fig_html(cumulative_chart(series, t("Cumulative return ({span}, {ccy})", h=horizon, ccy=ccy), ccy)))
        parts.append(_stats_display(r.user_stats).to_html(index=False, border=0, classes="tbl", escape=True))
        mt = tables.get(sheet_prefix(horizon) + "money")
        if mt is not None and not mt.empty:
            parts.append("<p>" + esc(t("What {capital} {ccy} would have become in each portfolio over the horizon "
                                       "(in-sample replay with constant weights):", capital=f"{mt['capital'].iloc[0]:,.0f}",
                                       ccy=ccy)) + "</p>")
            disp = mt.drop(columns=["capital"]).copy()
            for c_ in ("final_value", "gain", "max_drawdown_money", "best_period_gain", "worst_period_loss"):
                disp[c_] = disp[c_].map(lambda v: f"{v:,.0f}")
            parts.append(_df_html(disp, ("total_return",)))
        h2(6, t("Risk and diversification"))
        parts.append(fig_html(risk_contribution_bar(r.risk_decomp)))
        parts.append(fig_html(correlation_heatmap(r.corr)))
        parts.append("<p>" + esc(t("Diversification ratio {dr}; effective number of securities {eff}; covariance "
                                   "condition number {cond}.", dr=f"{r.concentration['diversification_ratio']:.3f}",
                                   eff=f"{r.concentration['effective_n_securities']:.2f}",
                                   cond=f"{r.cov_check['condition_number']:.3g}")) + "</p>")
        h2(7, t("Efficient frontier"))
        rf = rf_markowitz(s["risk_free_annual"], n)
        parts.append(fig_html(frontier_chart(r.frontier, r.optimized, rf, t("Efficient frontier ({span})", h=horizon))))
        h2(8, t("Optimized portfolios"))
        summ, wts = optimized_tables(r)
        parts.append(_df_html(summ, ("expected_return", "volatility")))
        parts.append(_df_html(wts.reset_index().rename(columns={"index": "ticker"}), tuple(wts.columns)))
    h2(9, t("Cross-horizon comparison"))
    ct = bundle.comparison_table()
    parts.append(fig_html(cross_horizon_chart(ct)))
    parts.append(_df_html(ct, [c for c in ct.columns if any(k in c for k in ("return", "volatility", "drawdown",
                                                                               "cagr"))]))
    h2(10, t("Sensitivity analysis"))
    if r.analyzable:
        parts.append("<p>" + esc(t("Maximum-Sharpe portfolio recomputed with the risk-free rate shifted by -2 to +2 "
                                   "percentage points.")) + "</p>")
        parts.append(_df_html(sensitivity_table(r, s["risk_free_annual"], n),
                              ("risk_free_annual", "expected_return", "volatility")))
    h2(11, t("Limitations and conclusions"))
    parts.append(doc("report_limitations"))
    parts.append(f"<h3>{esc(t('Analysis configuration'))}</h3><pre>" + esc(config_snapshot(bundle)) + "</pre>")
    css = ("@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap');"
           "body{font-family:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',sans-serif;color:#142033;"
           "background:#f5f7fa;max-width:1100px;margin:auto;padding:32px 24px;line-height:1.5}"
           "h1{font-size:26px;margin:0 0 4px 0}h2{font-size:18px;margin-top:40px;border-bottom:1px solid #e1e6ee;"
           "padding-bottom:6px}.meta{color:#4a5568}p,li{max-width:80ch}"
           ".tbl{border-collapse:collapse;font-size:12px;margin:10px 0;font-variant-numeric:tabular-nums;"
           "background:#fff}.tbl th,.tbl td{padding:5px 9px;border-bottom:1px solid #e1e6ee;text-align:right}"
           ".tbl th{color:#4a5568;font-weight:600}.warn{color:#b42318}"
           "pre{font-size:11px;background:#fff;border:1px solid #e1e6ee;padding:12px;overflow:auto}")
    lang = get_language()
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
            f"<title>{esc(t('{app}: portfolio report', app=APP_NAME))}</title>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{css}</style></head><body>"
            + "\n".join(parts) + "</body></html>")


def sensitivity_table(r: HorizonResult, rf_annual: float, n: int, shifts=(-0.02, -0.01, 0.0, 0.01, 0.02)
                      ) -> pd.DataFrame:
    """Max-Sharpe portfolio under alternative risk-free rates (same mu, Sigma, constraints)."""
    from .optimization import maximum_sharpe
    from .statistics import rf_markowitz

    rows = []
    m = r.mu.reindex(r.constraints.tickers).values
    S = r.cov.reindex(index=r.constraints.tickers, columns=r.constraints.tickers).values
    for d in shifts:
        rf_a = rf_annual + d
        rf = rf_markowitz(rf_a, n)
        o = maximum_sharpe(m, S, r.constraints, rf)
        rows.append({"risk_free_annual": rf_a, "max_sharpe_ok": o.ok, "expected_return": o.expected_return,
                     "volatility": o.volatility, "sharpe": o.sharpe,
                     "largest_weight": f"{o.weights.idxmax()} {o.weights.max():.1%}" if o.ok else "-"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# PDF report (matplotlib PdfPages: text, tables, figures)
# ---------------------------------------------------------------------------
def pdf_report(bundle: AnalysisBundle, horizon: int) -> bytes:
    from matplotlib.backends.backend_pdf import PdfPages

    plt = _mpl()
    s = bundle.config["settings"]
    p = bundle.config["portfolio"]
    r = bundle.horizons[horizon]
    ccy = s["base_currency"]
    buf = io.BytesIO()

    def text_page(pdf, title: str, lines: list[str]):
        import textwrap

        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.07, 0.95, title, fontsize=14, weight="bold", color="#142033")
        y = 0.91
        for line in lines:
            is_heading = line.isupper() and len(line) < 80
            for chunk in (textwrap.wrap(line, 100) or [""]):
                fig.text(0.07, y, chunk, fontsize=9 if is_heading else 8.5, family="DejaVu Sans",
                         weight="bold" if is_heading else "normal", color="#142033")
                y -= 0.018
                if y < 0.05:
                    pdf.savefig(fig)
                    plt.close(fig)
                    fig = plt.figure(figsize=(8.27, 11.69))
                    y = 0.95
        pdf.savefig(fig)
        plt.close(fig)

    def table_page(pdf, title: str, df: pd.DataFrame, max_rows: int = 40):
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        ax.axis("off")
        ax.set_title(title, loc="left", fontsize=11)
        d = df.head(max_rows).copy()
        for c in d.columns:
            if pd.api.types.is_float_dtype(d[c]):
                d[c] = d[c].map(lambda v: f"{v:.4f}" if pd.notna(v) else "")
        d = _display(d)
        d = d.map(lambda v: "" if (not isinstance(v, (list, dict)) and pd.isna(v)) else str(v)[:28])
        tb = ax.table(cellText=d.values, colLabels=[str(c)[:24] for c in d.columns], loc="upper left",
                      cellLoc="left")
        tb.auto_set_font_size(False)
        tb.set_fontsize(7)
        tb.auto_set_column_width(list(range(len(d.columns))))
        tb.scale(1, 1.3)
        for (row, _), cell in tb.get_celld().items():
            cell.set_edgecolor("#e1e6ee")
            if row == 0:
                cell.set_facecolor("#eef3fa")
        pdf.savefig(fig)
        plt.close(fig)

    def image_page(pdf, png: bytes):
        img = plt.imread(io.BytesIO(png), format="png")
        fig, ax = plt.subplots(figsize=(11.69, 8.27))
        ax.imshow(img)
        ax.axis("off")
        pdf.savefig(fig)
        plt.close(fig)

    with PdfPages(buf) as pdf:
        lines = ([t("*** SYNTHETIC DEMO DATA: illustrative only, not market prices ***"), ""]
                 if s.get("use_demo_database") else [])
        lines += [t("Portfolio: {name}   Base currency: {ccy}   Calculated: {created}", name=p["name"], ccy=ccy,
                    created=bundle.created_at),
                  t("Data cutoff: {cutoff}   Provider: {provider}", cutoff=bundle.data_cutoff,
                    provider=provider_label(bundle)),
                  t("Horizon: {period}   Status: {status}   Mode: {mode}", h=horizon, status=status_label(r.status),
                    mode=r.label),
                  t("Sample: {start} to {end}, {n} observations", start=r.start, end=r.end, n=r.n_obs), ""]
        if r.analyzable:
            us = r.user_stats
            lines += [t("EXECUTIVE SUMMARY (HISTORICAL, IN-SAMPLE)"),
                      t("Annualized arithmetic return {ret}; CAGR {cagr}; volatility {vol}; Sharpe {sharpe}; max "
                        "drawdown {mdd}; VaR95 {var}; CVaR95 {cvar} (per period).",
                        ret=f"{us['annual_arithmetic_return']:.2%}", cagr=f"{us['annual_geometric_return_cagr']:.2%}",
                        vol=f"{us['annual_volatility']:.2%}", sharpe=f"{us['sharpe_annual']:.3f}",
                        mdd=f"{us['max_drawdown']:.2%}", var=f"{us['var_95']:.2%}", cvar=f"{us['cvar_95']:.2%}")]
        lines += ["", t("WARNINGS AND DATA NOTES")] + r.warnings + bundle.warnings
        lines += ["", t("METHODOLOGY"),
                  t("Adjusted closes converted to the base currency at price level, then simple returns on the "
                    "common calendar (no filling)."),
                  t("Annual mean = n x mean, annual vol = sqrt(n) x sd (n=252 daily or 52 weekly); CAGR uses elapsed "
                    "time."),
                  t("Estimators: mu={mu}, Sigma={cov}; risk-free {rf} effective annual (assumption).",
                    mu=t(ESTIMATOR_LABELS.get(s["mu_estimator"], s["mu_estimator"])),
                    cov=t(ESTIMATOR_LABELS.get(s["cov_estimator"], s["cov_estimator"])),
                    rf=f"{s['risk_free_annual']:.2%}"),
                  t("Constraints: {mode}, long-only={lo}, max weight={cap}.",
                    mode=t(CONSTRAINT_LABELS.get(s["constraint_mode"], s["constraint_mode"])),
                    lo=t("yes") if s["long_only"] else t("no"), cap=s["max_weight"] or t("none")),
                  "", t("LIMITATIONS"),
                  t("Historical estimates are noisy; optima are in-sample and not forecasts or recommendations."),
                  t("Yahoo Finance (unofficial interface) does not guarantee completeness; adjusted data can be "
                    "revised."),
                  t("Asynchronous market closes understate daily cross-market correlations.")]
        text_page(pdf, t("{app}: portfolio report", app=APP_NAME), lines)
        table_page(pdf, t("Security weights"), build_tables(bundle)["security_weights"])
        if r.analyzable:
            image_page(pdf, cumulative_png(r, ccy))
            from .statistics import rf_markowitz
            image_page(pdf, frontier_png(r, rf_markowitz(s["risk_free_annual"], 52 if s["return_frequency"] ==
                                                          "weekly" else 252), ccy))
            summ, wts = optimized_tables(r)
            table_page(pdf, t("Optimized portfolios ({span})", h=horizon),
                       summ[["portfolio", "expected_return", "volatility", "sharpe", "ok", "certification",
                             "max_residual"]])
            table_page(pdf, t("Optimized weights ({span})", h=horizon),
                       wts.reset_index().rename(columns={"index": "ticker"}))
            table_page(pdf, t("User portfolio statistics ({span})", h=horizon), _stats_display(r.user_stats), 60)
        table_page(pdf, t("Cross-horizon comparison"), bundle.comparison_table().iloc[:, :12])
    return buf.getvalue()


def save_outputs(bundle: AnalysisBundle, db: Database, out_dir: str | Path, horizon: int) -> list[Path]:
    """Write every export format to disk (used by the CLI/tests and the Reports page)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tables = build_tables(bundle, db)
    cfg = config_snapshot(bundle)
    files = {f"analysis_{stamp}.xlsx": to_excel_bytes(tables, cfg),
             f"analysis_{stamp}_csv.zip": to_csv_zip_bytes(tables, cfg),
             f"report_{stamp}_{tag(horizon)}.html": html_report(bundle, horizon).encode("utf-8"),
             f"report_{stamp}_{tag(horizon)}.pdf": pdf_report(bundle, horizon),
             f"config_{stamp}.json": cfg.encode("utf-8")}
    r = bundle.horizons[horizon]
    if r.analyzable:
        from .statistics import rf_markowitz
        n = 52 if bundle.config["settings"]["return_frequency"] == "weekly" else 252
        files[f"frontier_{stamp}_{tag(horizon)}.png"] = frontier_png(
            r, rf_markowitz(bundle.config["settings"]["risk_free_annual"], n), bundle.config["settings"]["base_currency"])
        files[f"cumulative_{stamp}_{tag(horizon)}.png"] = cumulative_png(r, bundle.config["settings"]["base_currency"])
    paths = []
    for name, data in files.items():
        path = out / name
        path.write_bytes(data)
        paths.append(path)
    return paths
