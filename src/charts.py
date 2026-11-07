"""Plotly figure builders shared by the Streamlit UI and the HTML report.

Palette: validated categorical order (blue, orange, aqua, yellow, magenta, green, violet, red),
sequential blue ramp, diverging blue<->red with gray midpoint.  Identity is never color-only:
scatter charts add marker symbols and direct labels; every chart has a legend or a title naming
its single series, plus hover tooltips.  All visible text goes through the translation module.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from contextvars import ContextVar

from .i18n import N_, t, years

# categorical series (validated order): light steps, and the same hues stepped for the dark surface
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
# interface tokens (shared with the CSS in src/ui.py); light = cool paper + navy ink, dark = deep navy
TOKENS = {
    "light": {"ink": "#142033", "ink2": "#4a5568", "muted": "#7b8494", "grid": "#e6e9ef", "axis": "#c5ccd6",
              "surface": "#ffffff", "mid": "#f0f2f5", "series": SERIES},
    "dark": {"ink": "#e6ebf2", "ink2": "#b4bfcd", "muted": "#8592a3", "grid": "#253041", "axis": "#3a4658",
             "surface": "#161e2b", "mid": "#2a3140", "series": SERIES_DARK},
}
INK, INK2, MUTED = (TOKENS["light"][k] for k in ("ink", "ink2", "muted"))     # light values (static exports)
GRID, AXIS, SURFACE = (TOKENS["light"][k] for k in ("grid", "axis", "surface"))
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGING = [[0.0, "#2a78d6"], [0.5, "#f0f2f5"], [1.0, "#e34948"]]

_mode: ContextVar[str] = ContextVar("gpl_chart_mode", default="light")


def set_dark(dark: bool) -> None:
    """Select the dark or light chart palette for figures built in this session/run."""
    _mode.set("dark" if dark else "light")


def is_dark() -> bool:
    return _mode.get() == "dark"


class _Tokens:
    """Mode-aware colors: ``C.ink`` etc. resolve to the light or dark step of the active mode."""

    def __getattr__(self, name: str):
        tok = TOKENS[_mode.get()]
        if name == "diverging":
            return [[0.0, tok["series"][0]], [0.5, tok["mid"]], [1.0, tok["series"][7]]]
        return tok[name]

    def slot(self, light_color: str) -> str:
        """Map a light categorical color to the same slot in the active mode."""
        return self.series[SERIES.index(light_color)] if light_color in SERIES else light_color


C = _Tokens()

FONT = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"

# fixed identity per portfolio (color follows the entity, never its rank)
PORTFOLIO_STYLE = {
    "user": (N_("User portfolio"), SERIES[0], "star"),
    "min_variance": (N_("Minimum variance"), SERIES[2], "circle"),
    "max_sharpe": (N_("Maximum Sharpe"), SERIES[1], "diamond"),
    "max_return": (N_("Maximum return"), SERIES[6], "triangle-up"),
    "max_risk": (N_("Maximum risk"), SERIES[7], "x"),
    "equal_weight": (N_("Equal weight"), SERIES[3], "square"),
    "max_diversification": (N_("Max diversification"), SERIES[4], "pentagon"),
    "min_cvar": (N_("Minimum CVaR 95%"), SERIES[5], "hexagon"),
}
DIRECT_LABELS = ("user", "min_variance", "max_sharpe")  # selective direct labels; others via legend + hover


def _layout(fig: go.Figure, title: str, xtitle: str = "", ytitle: str = "", height: int = 420,
            xpct: bool = False, ypct: bool = False) -> go.Figure:
    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": C.ink, "family": FONT}, "x": 0, "xanchor": "left",
               "y": 0.98, "yanchor": "top"},
        font={"family": FONT, "color": C.ink2, "size": 12}, paper_bgcolor=C.surface, plot_bgcolor=C.surface,
        height=height, margin={"l": 60, "r": 24, "t": 56, "b": 48}, hovermode="closest",
        legend={"orientation": "h", "yanchor": "top", "y": -0.22 if xtitle else -0.08, "xanchor": "left", "x": 0,
                "font": {"color": C.ink2}},
        hoverlabel={"bgcolor": C.surface, "font": {"color": C.ink, "family": FONT}, "bordercolor": C.axis})
    for ax, axis_title, pct in (("xaxis", xtitle, xpct), ("yaxis", ytitle, ypct)):
        fig.update_layout(**{ax: {"title": {"text": axis_title, "font": {"color": C.ink2}}, "gridcolor": C.grid,
                                  "linecolor": C.axis, "zerolinecolor": C.axis, "tickfont": {"color": C.muted},
                                  "automargin": True, "tickformat": ".0%" if pct else None}})
    return fig


def market_colors(markets: list[str]) -> dict[str, str]:
    """Fixed color per market, by allocation order (shared by donut, treemap and the header strip)."""
    return {m: C.series[i] if i < len(C.series) else C.muted for i, m in enumerate(markets)}


def market_donut(allocations: dict[str, float], names: dict[str, str] | None = None) -> go.Figure:
    items = [(m, a) for m, a in allocations.items() if a > 0]
    labels = [(names or {}).get(m, m) for m, _ in items]
    cmap = market_colors([m for m, _ in items])  # beyond eight markets: neutral gray, labels keep identity
    colors = [cmap[m] for m, _ in items]
    fig = go.Figure(go.Pie(labels=labels, values=[a for _, a in items], hole=0.58, sort=False,
                           marker={"colors": colors, "line": {"color": C.surface, "width": 2}},
                           textinfo="percent", textposition="inside", insidetextorientation="horizontal",
                           textfont={"color": ["#142033" if (c == C.series[3] and not is_dark()) else "#ffffff" for c in colors]},
                           hovertemplate="%{label}: %{value:.2f}%<extra></extra>"))
    fig = _layout(fig, t("Market allocation"), height=380)
    fig.update_layout(legend={"orientation": "v", "yanchor": "middle", "y": 0.5, "xanchor": "left", "x": 1.0})
    return fig


def security_treemap(weights: pd.Series, market_of: dict[str, str], market_order: list[str] | None = None,
                     names: dict[str, str] | None = None, colors: dict[str, str] | None = None) -> go.Figure:
    present = {market_of[tk] for tk in weights.index}
    markets = [m for m in (market_order or sorted(present)) if m in present]
    color = market_colors(market_order or markets)
    ids = markets + list(weights.index)
    parents = [""] * len(markets) + [market_of[tk] for tk in weights.index]
    values = [float(weights[[tk for tk in weights.index if market_of[tk] == m]].sum()) for m in markets] + \
        list(weights.values)
    colors = [color[m] for m in markets] + [(colors or {}).get(tk, color[market_of[tk]]) for tk in weights.index]
    labels = [(names or {}).get(m, m) for m in markets] + list(weights.index)
    fig = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                               marker={"colors": colors, "line": {"color": C.surface, "width": 2}},
                               texttemplate="%{label}<br>%{value:.1%}",
                               textfont={"color": [_text_on(c) for c in colors]},
                               hovertemplate="%{label}: %{value:.2%} " + t("of portfolio") + "<extra></extra>"))
    return _layout(fig, t("Security allocation (share of total portfolio)"), height=380)


def _text_on(bg: str) -> str:
    """Dark or white label text, whichever contrasts more with a fill color."""
    try:
        h = bg.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return "#ffffff"
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#142033" if lum > 0.6 else "#ffffff"


def cumulative_chart(series: dict[str, pd.Series], title: str, currency: str) -> go.Figure:
    fig = go.Figure()
    for i, (name, r) in enumerate(series.items()):
        w = (1 + r).cumprod() - 1
        fig.add_trace(go.Scatter(x=w.index, y=w.values, mode="lines", name=name,
                                 line={"width": 2, "color": C.series[i % len(C.series)]},
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:.2%}<extra>" + name + "</extra>"))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, t("Date"), t("Cumulative return ({currency})", currency=currency), ypct=True)


def drawdown_chart(r: pd.Series, title: str | None = None) -> go.Figure:
    w = (1 + r).cumprod()
    dd = w / np.maximum.accumulate(np.concatenate([[1.0], w.values]))[1:] - 1
    fig = go.Figure(go.Scatter(x=r.index, y=dd, mode="lines", fill="tozeroy", line={"width": 2, "color": C.series[7]},
                               fillcolor="rgba(227,73,72,0.15)", name=t("Drawdown"),
                               hovertemplate="%{x|%Y-%m-%d}: %{y:.2%}<extra></extra>"))
    fig.update_layout(showlegend=False, hovermode="x unified")
    return _layout(fig, title or t("Drawdown"), t("Date"), t("Drawdown from prior peak"), height=300, ypct=True)


def _weights_hover(w: pd.Series) -> str:
    top = w[w.abs() > 5e-4].sort_values(ascending=False)
    return "<br>".join(f"{tk}: {v:.1%}" for tk, v in top.head(12).items())


def frontier_chart(frontier, optimized: dict, rf: float | None = None, title: str | None = None,
                   asset_points: pd.DataFrame | None = None, asset_colors: dict[str, str] | None = None,
                   capital: float | None = None, ccy: str = "") -> go.Figure:
    fig = go.Figure()
    vol_l, ret_l = t("Vol"), t("Return")
    if frontier is not None and not frontier.points.empty:
        for branch, dash, name in (("efficient", "solid", t("Efficient frontier")),
                                   ("inefficient", "dot", t("Inefficient branch"))):
            p = frontier.points[(frontier.points["ok"]) & (frontier.points["branch"] == branch)]
            p = p.sort_values("expected_return")
            if p.empty:
                continue
            hov = []
            for target in p["target"]:
                w = frontier.weights.loc[target] if target in frontier.weights.index else pd.Series(dtype=float)
                hov.append(_weights_hover(w))
            fig.add_trace(go.Scatter(
                x=p["volatility"], y=p["expected_return"], mode="lines", name=name,
                line={"width": 2.5 if branch == "efficient" else 1.5,
                      "color": C.ink if branch == "efficient" else C.muted, "dash": dash},
                customdata=np.stack([p["sharpe"].fillna(np.nan).values, np.array(hov, dtype=object)], axis=-1),
                hovertemplate=f"{vol_l} %{{x:.2%}}<br>{ret_l} %{{y:.2%}}<br>Sharpe %{{customdata[0]:.3f}}<br>"
                              "%{customdata[1]}<extra>" + name + "</extra>"))
        tang = optimized.get("max_sharpe")
        if rf is not None and tang is not None and tang.ok and tang.volatility > 0:
            xmax = float(frontier.points.loc[frontier.points["ok"], "volatility"].max()) * 1.05
            slope = (tang.expected_return - rf) / tang.volatility
            fig.add_trace(go.Scatter(x=[0, xmax], y=[rf, rf + slope * xmax], mode="lines",
                                     name=t("Capital market line"),
                                     line={"width": 1, "color": C.axis, "dash": "dash"}, hoverinfo="skip"))
    if asset_points is not None and not asset_points.empty:
        acol = [(asset_colors or {}).get(tk, "rgba(123,132,148,0.30)") for tk in asset_points.index]
        fig.add_trace(go.Scatter(x=asset_points["volatility"], y=asset_points["return"],
                                 mode="markers",
                                 text=asset_points.index, name=t("Individual assets"), textposition="top center",
                                 textfont={"color": C.muted, "size": 10},
                                 marker={"size": 9, "color": acol, "opacity": 0.85 if asset_colors else 1,
                                         "line": {"color": C.surface if asset_colors else C.muted, "width": 1}},
                                 hovertemplate=f"%{{text}}<br>{vol_l} %{{x:.2%}}<br>{ret_l} %{{y:.2%}}"
                                               "<extra></extra>"))
    vols = [o.volatility for o in optimized.values() if o is not None and o.ok]
    vmax = max(vols) if vols else 0.0
    for key, (label_key, light_color, symbol) in PORTFOLIO_STYLE.items():
        o = optimized.get(key)
        if o is None or not o.ok:
            continue
        label = t(label_key)
        color = C.slot(light_color)
        sh = f"{o.sharpe:.3f}" if o.sharpe is not None else t("undefined")
        money_line = (f"<br>{t('Expected gain per year')}: {capital * o.expected_return:,.0f} {ccy}"
                      if capital else "")
        labelled = key in DIRECT_LABELS
        fig.add_trace(go.Scatter(
            x=[o.volatility], y=[o.expected_return], mode="markers+text" if labelled else "markers", name=label,
            text=[label] if labelled else None,
            textposition="middle left" if o.volatility > 0.8 * vmax else "middle right",
            textfont={"color": C.ink2, "size": 11},
            marker={"size": 16 if symbol == "star" else 13, "color": color, "symbol": symbol,
                    "line": {"color": C.surface, "width": 2}},
            customdata=[key],
            hovertemplate=f"<b>{label}</b><br>{vol_l} %{{x:.2%}}<br>{ret_l} %{{y:.2%}}<br>Sharpe {sh}{money_line}<br>"
                          f"{_weights_hover(o.weights)}<br>{t('Certification')}: {o.certification}"
                          "<extra></extra>"))
    return _layout(fig, title or t("Efficient frontier"), t("Annualized volatility"), t("Expected annualized return"),
                   height=560, xpct=True, ypct=True)


def portfolio_scatter(optimized: dict, assets: pd.DataFrame | None, title: str) -> go.Figure:
    """Risk-return comparison of portfolios (and optionally individual assets), no frontier line."""
    return frontier_chart(None, optimized, None, title, assets)


def correlation_heatmap(corr: pd.DataFrame, title: str | None = None) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1, colorscale=C.diverging,
                               text=np.round(corr.values, 2), texttemplate="%{text}", textfont={"color": C.ink},
                               hovertemplate="%{y} vs %{x}: %{z:.3f}<extra></extra>", xgap=2, ygap=2,
                               colorbar={"title": "ρ"}))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, title or t("Correlation matrix"), height=max(380, 40 * len(corr) + 120))


def weights_bar(weights: dict[str, pd.Series], title: str) -> go.Figure:
    fig = go.Figure()
    by_label = {t(label): C.slot(color) for label, color, _ in PORTFOLIO_STYLE.values()}
    by_label[t("Equal weight (within markets)")] = C.slot(PORTFOLIO_STYLE["equal_weight"][1])
    for i, (name, w) in enumerate(weights.items()):
        color = by_label.get(name, C.series[i % 8])  # a portfolio keeps the same color on every chart
        fig.add_trace(go.Bar(x=w.index, y=w.values, name=name, marker={"color": color,
                                                                     "line": {"color": C.surface, "width": 2}},
                             hovertemplate="%{x}: %{y:.2%}<extra>" + name + "</extra>"))
    fig.update_layout(barmode="group", bargap=0.25)
    return _layout(fig, title, t("Security"), t("Total portfolio weight"), ypct=True)


def risk_contribution_bar(rd: pd.DataFrame, title: str | None = None) -> go.Figure:
    d = rd.sort_values("component_vol_pct", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=d.index, x=d["weight"], orientation="h", name=t("Weight"), marker={"color": C.series[0]},
                         hovertemplate="%{y}: %{x:.2%}<extra>" + t("Weight") + "</extra>"))
    fig.add_trace(go.Bar(y=d.index, x=d["component_vol_pct"], orientation="h", name=t("Share of volatility"),
                         marker={"color": C.series[1]},
                         hovertemplate="%{y}: %{x:.2%}<extra>" + t("Share of volatility") + "</extra>"))
    fig.update_layout(barmode="group", bargap=0.3)
    return _layout(fig, title or t("Contribution to volatility (Euler)"), t("Share"), "",
                   height=max(320, 36 * len(d) + 120), xpct=True)


def coverage_timeline(coverage: pd.DataFrame, title: str | None = None) -> go.Figure:
    fig = go.Figure()
    for tk, row in coverage.iterrows():
        if pd.isna(row.get("first")) or pd.isna(row.get("last")):
            continue
        fig.add_trace(go.Scatter(x=[row["first"], row["last"]], y=[tk, tk], mode="lines",
                                 line={"width": 10, "color": C.series[0]}, showlegend=False,
                                 hovertemplate=f"{tk}: {pd.Timestamp(row['first']).date()} – "
                                               f"{pd.Timestamp(row['last']).date()}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, title or t("Historical data coverage"), t("Date"), "",
                   height=max(260, 32 * len(coverage) + 100))


def cross_horizon_chart(table: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    ok = table[table["status"] == "COMPLETE"]
    for i, (col, key) in enumerate((("user_sharpe", "user"), ("min_variance_sharpe", "min_variance"),
                                    ("max_sharpe_sharpe", "max_sharpe"))):
        if col in ok.columns:
            label, light_color, _ = PORTFOLIO_STYLE[key]
            color = C.slot(light_color)
            name = t(label)
            xs = list(ok["horizon"]) if "horizon" in ok.columns else [years(h, short=True) for h in ok["horizon_years"]]
            fig.add_trace(go.Bar(x=xs, y=ok[col], name=name,
                                 marker={"color": color},
                                 hovertemplate="%{x}: Sharpe %{y:.3f}<extra>" + name + "</extra>"))
    fig.update_layout(barmode="group")
    return _layout(fig, t("Annualized Sharpe ratio by horizon (complete horizons only)"), t("Horizon"),
                   t("Sharpe ratio"))


def distribution_chart(r: pd.Series, var95: float, title: str | None = None) -> go.Figure:
    fig = go.Figure(go.Histogram(x=r.values, nbinsx=80, marker={"color": C.series[0], "line": {"color": C.surface,
                                                                                           "width": 1}},
                                 name=t("Returns"), hovertemplate="%{x:.2%}: %{y}<extra></extra>"))
    fig.add_vline(x=-var95, line={"color": C.series[7], "dash": "dash"}, annotation_text="VaR 95%",
                  annotation_font_color=C.ink2)
    fig.update_layout(showlegend=False)
    return _layout(fig, title or t("Return distribution"), t("Period return"), t("Count"), height=320, xpct=True)


def simple_line(x, ys: dict[str, pd.Series], title: str, ytitle: str) -> go.Figure:
    """Generic multi-line price chart (used by the Explorer and Database pages)."""
    fig = go.Figure()
    for i, (name, y) in enumerate(ys.items()):
        fig.add_trace(go.Scatter(x=x if x is not None else y.index, y=y, mode="lines", name=name,
                                 line={"color": C.series[i % len(C.series)], "width": 2 if i == 0 else 1}))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, t("Date"), ytitle)


def histogram(values, title: str, xtitle: str, ytitle: str) -> go.Figure:
    fig = go.Figure(go.Histogram(x=values, nbinsx=80, marker={"color": C.series[0]}, name=xtitle))
    fig.update_layout(showlegend=False)
    return _layout(fig, title, xtitle, ytitle, height=320, xpct=True)


# ---------------------------------------------------------------------------
# Money, brand colors and logos (v1.2)
# ---------------------------------------------------------------------------
STRATEGY_STYLE = {   # backtest strategies keep the portfolio identities above; new ones get the remaining hues
    "user": SERIES[0], "min_variance": SERIES[2], "max_sharpe": SERIES[1], "max_return": SERIES[6],
    "equal_weight": SERIES[3], "max_diversification": SERIES[4], "min_cvar": SERIES[5], "risk_parity": "#0f8b8d",
    "inverse_vol": "#8a6d3b", "target_vol": "#7b8494", "benchmark": "#4a5568",
}


MONTHS = (N_("Jan"), N_("Feb"), N_("Mar"), N_("Apr"), N_("May"), N_("Jun"), N_("Jul"), N_("Aug"), N_("Sep"),
          N_("Oct"), N_("Nov"), N_("Dec"))


def strategy_color(key: str) -> str:
    c = STRATEGY_STYLE.get(key, SERIES[0])
    if is_dark():
        c = C.slot(c)
        if c in ("#4a5568", "#7b8494"):
            c = "#b4bfcd" if c == "#4a5568" else "#8592a3"
    return c


def _money_fmt(ccy: str) -> str:
    return ",.0f"


def add_logo_ticks(fig: go.Figure, tickers: list[str], logos: dict[str, str | None], axis: str = "y",
                   size: float = 0.72) -> go.Figure:
    """Small logos between the category labels and the plot of a horizontal bar chart (categories in the
    order they are drawn).  Labels are pushed left to make room."""
    n = len(tickers)
    if n == 0 or not any((logos or {}).get(tk) for tk in tickers):
        return fig
    height = fig.layout.height or 420
    m = fig.layout.margin
    plot_h = max(height - (m.t or 56) - (m.b or 48), 60)
    px = min(30.0, plot_h / n * size)
    for i, tk in enumerate(tickers):
        src = (logos or {}).get(tk)
        if not src:
            continue
        fig.add_layout_image(source=src, xref="paper", yref="paper", x=-0.006, y=(i + 0.5) / n,
                             sizex=0.2, sizey=px / plot_h, xanchor="right", yanchor="middle", sizing="contain",
                             layer="above")
    fig.update_yaxes(ticklabelstandoff=int(px + 10))
    return fig


def money_growth(paths: dict[str, pd.Series], title: str, ccy: str, colors: dict[str, str] | None = None,
                 invested: pd.Series | None = None, split: pd.Timestamp | None = None,
                 faded: dict[str, pd.Series] | None = None, height: int = 440) -> go.Figure:
    """Value of the money over time (one line per portfolio), optional invested-capital step line and a
    vertical marker where the model stops seeing data."""
    fig = go.Figure()
    for i, (name, s) in enumerate((faded or {}).items()):
        col = (colors or {}).get(name, C.series[i % 8])
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=name, showlegend=False,
                                 line={"width": 1.2, "color": col}, opacity=0.35, hoverinfo="skip"))
    if invested is not None:
        fig.add_trace(go.Scatter(x=invested.index, y=invested.values, mode="lines", name=t("Money invested"),
                                 line={"width": 1.5, "color": C.muted, "dash": "dot", "shape": "hv"},
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f} " + ccy + "<extra>" + t("Money invested") +
                                               "</extra>"))
    for i, (name, s) in enumerate(paths.items()):
        col = (colors or {}).get(name, C.series[i % 8])
        fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=name, line={"width": 2.4, "color": col},
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f} " + ccy + "<extra>" + name + "</extra>"))
    if split is not None:
        fig.add_vline(x=split, line={"color": C.axis, "dash": "dash", "width": 1.5})
        fig.add_annotation(x=split, y=1.0, yref="paper", text=t("model stops seeing data"), showarrow=False,
                           xanchor="left", yanchor="bottom", font={"color": C.ink2, "size": 11}, xshift=4)
    fig.update_layout(hovermode="x unified")
    fig = _layout(fig, title, t("Date"), t("Value ({ccy})", ccy=ccy), height=height)
    fig.update_yaxes(tickformat=",.0f")
    return fig


def contribution_bars(contrib: pd.Series, title: str, ccy: str, colors: dict[str, str] | None = None,
                      names: dict[str, str] | None = None, logos: dict[str, str | None] | None = None) -> go.Figure:
    """Money each security added (or took away), sorted, brand-colored, with its logo."""
    d = contrib.sort_values()
    cols = [(colors or {}).get(tk, C.series[0]) for tk in d.index]
    labels = [f"{(names or {}).get(tk, tk)}  " for tk in d.index]
    fig = go.Figure(go.Bar(y=list(d.index), x=d.values, orientation="h", marker={"color": cols},
                           text=[f"{v:+,.0f}" for v in d.values], textposition="outside", cliponaxis=False,
                           textfont={"color": C.ink2},
                           customdata=labels, hovertemplate="%{customdata}: %{x:+,.0f} " + ccy + "<extra></extra>"))
    fig.add_vline(x=0, line={"color": C.axis, "width": 1})
    fig.update_yaxes(tickmode="array", tickvals=list(d.index), ticktext=labels)
    fig = _layout(fig, title, t("Gain or loss ({ccy})", ccy=ccy), "", height=max(300, 44 * len(d) + 110))
    fig.update_layout(showlegend=False, margin={"l": 150, "r": 70, "t": 56, "b": 48})
    fig.update_xaxes(tickformat="~s", nticks=5)
    return add_logo_ticks(fig, list(d.index), logos or {}, "y")


def weights_stack(portfolios: dict[str, pd.Series], title: str, colors: dict[str, str] | None = None,
                  names: dict[str, str] | None = None) -> go.Figure:
    """One horizontal 100% bar per portfolio; each segment is a security in its brand color."""
    tickers = list(dict.fromkeys(tk for w in portfolios.values() for tk in w.index))
    fig = go.Figure()
    pnames = list(portfolios)
    for i, tk in enumerate(tickers):
        vals = [float(portfolios[p].get(tk, 0.0)) for p in pnames]
        col = (colors or {}).get(tk, C.series[i % 8])
        nm = (names or {}).get(tk, tk)
        fig.add_trace(go.Bar(y=pnames, x=vals, orientation="h", name=tk, marker={"color": col,
                                                                                  "line": {"color": C.surface, "width": 1}},
                             text=[tk if v >= 0.06 else "" for v in vals], textposition="inside",
                             insidetextanchor="middle", textfont={"color": "#ffffff", "size": 11},
                             customdata=[nm] * len(vals),
                             hovertemplate="%{y}<br>%{customdata} (" + tk + "): %{x:.2%}<extra></extra>"))
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_yaxes(autorange="reversed")
    fig = _layout(fig, title, t("Share of the portfolio"), "", height=max(260, 46 * len(pnames) + 140), xpct=True)
    fig.update_layout(legend={"traceorder": "normal"})
    return fig


def security_donut(weights: pd.Series, title: str, colors: dict[str, str] | None = None,
                   names: dict[str, str] | None = None) -> go.Figure:
    w = weights[weights.abs() > 1e-6]
    cols = [(colors or {}).get(tk, C.series[i % 8]) for i, tk in enumerate(w.index)]
    fig = go.Figure(go.Pie(labels=list(w.index), values=w.values, hole=0.6, sort=False,
                           marker={"colors": cols, "line": {"color": C.surface, "width": 2}},
                           textinfo="label+percent", textposition="outside",
                           customdata=[(names or {}).get(tk, tk) for tk in w.index],
                           hovertemplate="%{customdata} (%{label}): %{percent}<extra></extra>"))
    fig = _layout(fig, title, height=360)
    fig.update_layout(showlegend=False)
    return fig


def monthly_heatmap(r: pd.Series, title: str | None = None) -> go.Figure:
    """Calendar of monthly returns (rows = years, columns = months)."""
    m = (1 + r).resample("ME").prod() - 1
    df = pd.DataFrame({"y": m.index.year, "m": m.index.month, "v": m.values})
    piv = df.pivot(index="y", columns="m", values="v").reindex(columns=range(1, 13))
    months = [t(x) for x in MONTHS]
    lim = float(np.nanmax(np.abs(piv.values))) if np.isfinite(piv.values).any() else 0.1
    text = [[("" if pd.isna(v) else f"{v:+.1%}") for v in row] for row in piv.values]
    fig = go.Figure(go.Heatmap(z=piv.values, x=months, y=[str(y) for y in piv.index], zmin=-lim, zmax=lim,
                               colorscale=[[0, C.series[7]], [0.5, C.mid], [1, C.series[2]]], text=text,
                               texttemplate="%{text}", textfont={"color": C.ink, "size": 11}, xgap=2, ygap=2,
                               hovertemplate="%{y} %{x}: %{z:.2%}<extra></extra>", showscale=False))
    fig.update_yaxes(autorange="reversed", type="category")
    return _layout(fig, title or t("Monthly returns"), "", "", height=max(220, 34 * len(piv) + 110))


def fan_chart(bands: pd.DataFrame, realized: pd.Series, title: str, ccy: str, color: str,
              invested: pd.Series | None = None, history: pd.Series | None = None,
              split: pd.Timestamp | None = None) -> go.Figure:
    """Forecast cone (5-95% and 25-75% of simulated paths, median) against what actually happened."""
    fig = go.Figure()
    if history is not None and len(history):
        fig.add_trace(go.Scatter(x=history.index, y=history.values, mode="lines", name=t("Training period (in-sample)"),
                                 line={"width": 1.3, "color": C.muted},
                                 hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f} " + ccy + "<extra></extra>"))
    x = list(bands.index)
    for lo, hi, op, name in (("p5", "p95", 0.13, t("Forecast 5-95%")), ("p25", "p75", 0.25, t("Forecast 25-75%"))):
        fig.add_trace(go.Scatter(x=x + x[::-1], y=list(bands[hi]) + list(bands[lo])[::-1], fill="toself",
                                 fillcolor=_rgba(color, op), line={"width": 0}, name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=bands["p50"], mode="lines", name=t("Forecast median"),
                             line={"width": 1.6, "color": color, "dash": "dash"},
                             hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f} " + ccy + "<extra>" + t("Forecast median") +
                                           "</extra>"))
    if invested is not None:
        fig.add_trace(go.Scatter(x=invested.index, y=invested.values, mode="lines", name=t("Money invested"),
                                 line={"width": 1.2, "color": C.muted, "dash": "dot", "shape": "hv"}, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=realized.index, y=realized.values, mode="lines", name=t("What actually happened"),
                             line={"width": 3, "color": C.ink},
                             hovertemplate="%{x|%Y-%m-%d}: %{y:,.0f} " + ccy + "<extra>" +
                                           t("What actually happened") + "</extra>"))
    if split is not None:
        fig.add_vline(x=split, line={"color": C.axis, "dash": "dash", "width": 1.5})
    fig.update_layout(hovermode="x unified")
    fig = _layout(fig, title, t("Date"), t("Value ({ccy})", ccy=ccy), height=460)
    fig.update_yaxes(tickformat=",.0f")
    return fig


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def fx_lines(rates: dict[str, pd.Series], title: str, normalize: bool = True) -> go.Figure:
    fig = go.Figure()
    for i, (pair, s) in enumerate(rates.items()):
        s = s.dropna()
        if s.empty:
            continue
        y = s / s.iloc[0] * 100 if normalize else s
        fig.add_trace(go.Scatter(x=s.index, y=y.values, mode="lines", name=pair, line={"width": 2, "color": C.series[i % 8]},
                                 customdata=s.values,
                                 hovertemplate="%{x|%Y-%m-%d}: %{customdata:.4f}<extra>" + pair + "</extra>"))
    if normalize:
        fig.add_hline(y=100, line={"color": C.axis, "width": 1})
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, t("Date"), t("Index (start = 100)") if normalize else t("Rate"))


def fx_decomposition(df: pd.DataFrame, title: str, names: dict[str, str] | None = None) -> go.Figure:
    """Per security: local-currency return, FX effect and cross term, plus the total in the base currency."""
    d = df.sort_values("base_return")
    labels = [(names or {}).get(tk, tk) for tk in d.index]
    fig = go.Figure()
    for col, name, color in (("local_return", t("Stock in its own currency"), C.series[0]),
                             ("fx_return", t("Exchange-rate effect"), C.series[1]),
                             ("cross", t("Cross term"), C.muted)):
        fig.add_trace(go.Bar(y=labels, x=d[col], orientation="h", name=name, marker={"color": color},
                             hovertemplate="%{y}: %{x:+.2%}<extra>" + name + "</extra>"))
    fig.add_trace(go.Scatter(y=labels, x=d["base_return"], mode="markers", name=t("Total in base currency"),
                             marker={"symbol": "diamond", "size": 12, "color": C.ink, "line": {"color": C.surface,
                                                                                            "width": 1.5}},
                             hovertemplate="%{y}: %{x:+.2%}<extra>" + t("Total in base currency") + "</extra>"))
    fig.update_layout(barmode="relative")
    fig.add_vline(x=0, line={"color": C.axis, "width": 1})
    return _layout(fig, title, t("Return over the period"), "", height=max(300, 40 * len(d) + 140), xpct=True)


def bars_money(values: dict[str, float], title: str, ccy: str, colors: dict[str, str] | None = None,
               reference: float | None = None, ref_label: str = "") -> go.Figure:
    """Ranking bar chart of money amounts (e.g. final value by strategy)."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(y=[k for k, _ in items], x=[v for _, v in items], orientation="h",
                           marker={"color": [(colors or {}).get(k, C.series[0]) for k, _ in items]},
                           text=[f"{v:,.0f}" for _, v in items], textposition="outside", cliponaxis=False,
                           textfont={"color": C.ink2},
                           hovertemplate="%{y}: %{x:,.0f} " + ccy + "<extra></extra>"))
    if reference is not None:
        fig.add_vline(x=reference, line={"color": C.ink2, "dash": "dot"}, annotation_text=ref_label,
                      annotation_font_color=C.ink2, annotation_position="top")
    fig = _layout(fig, title, t("Value ({ccy})", ccy=ccy), "", height=max(280, 40 * len(items) + 140))
    fig.update_layout(showlegend=False, margin={"l": 60, "r": 90, "t": 56, "b": 64})
    fig.update_xaxes(tickformat=",.0f")
    if reference is not None and items:
        lo = min(min(v for _, v in items), reference)
        fig.update_xaxes(range=[lo * 0.97, max(max(v for _, v in items), reference) * 1.03])
    return fig


def weights_area(weights: pd.DataFrame, title: str, colors: dict[str, str] | None = None) -> go.Figure:
    """Stacked area of portfolio weights over time (drift and rebalancing)."""
    fig = go.Figure()
    for i, tk in enumerate(weights.columns):
        col = (colors or {}).get(tk, C.series[i % 8])
        fig.add_trace(go.Scatter(x=weights.index, y=weights[tk], mode="lines", stackgroup="w", name=tk,
                                 line={"width": 0.5, "color": col}, fillcolor=col,
                                 hovertemplate="%{x|%Y-%m-%d} " + tk + ": %{y:.1%}<extra></extra>"))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, title, "", t("Weight"), height=380, ypct=True)
