"""Streamlit helpers shared by all pages: state, services, layout, translation-aware widgets, formatting."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from . import i18n
from .analysis import AnalysisBundle, HorizonResult, analyze_custom, incomplete_reasons, run_analysis
from .horizons import CUSTOM, CustomHorizon, is_custom
from .charts import market_colors
from .config import APP_NAME, HORIZONS_YEARS, PROJECT_ROOT, PROVIDER_NAME, AppSettings, database_path, \
    load_markets, load_settings, save_settings
from .data_service import DataService
from .database import Database
from .i18n import t
from .logos import ATTRIBUTION_HTML, LogoService, assign_colors, data_uri, logo_png
from .money import compact as money_compact
from .money import money as money_text
from .synthetic import SyntheticProvider
from .validation import Portfolio, validate_holdings, validate_market_allocations

ASSETS = PROJECT_ROOT / "assets"

# Labels live in src/labels.py so reports can use them without Streamlit
from .labels import COLUMN_LABELS, CONSTRAINT_LABELS, COVERAGE_LABELS, ESTIMATOR_LABELS, FREQUENCY_LABELS, \
    REBALANCE_LABELS, ROW_LABELS, STATUS_COLOR, STATUS_ICON, STATUS_LABELS, WINDOW_LABELS, col_label, \
    status_label  # noqa: F401  (re-exported for pages)


def show_table(df: pd.DataFrame, pct: tuple[str, ...] | list[str] = (), num: tuple[str, ...] | list[str] = (),
               digits: int = 2, num_digits: int = 4, hide_index: bool = True, status_cols: tuple[str, ...] = (
                   "status", "download_status", "validation_status", "branch"), height: int | str = "auto",
               index_label: str | None = None) -> None:
    """Display a frame with translated column headers, percentage formatting and status labels."""
    out = df.copy()
    for c in pct:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce") * 100
    for c in status_cols:
        if c in out.columns:
            out[c] = out[c].map(status_label)
    cfg: dict[str, Any] = {}
    for c in out.columns:
        label = col_label(c)
        if c in pct:
            cfg[c] = st.column_config.NumberColumn(label, format=f"%.{digits}f%%")
        elif c in num:
            cfg[c] = st.column_config.NumberColumn(label, format=f"%.{num_digits}f")
        else:
            cfg[c] = st.column_config.Column(label)
    if index_label is not None:
        out.index.name = index_label
    st.dataframe(out, hide_index=hide_index, width="stretch", column_config=cfg, height=height)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def init_state() -> None:
    ss = st.session_state
    if "settings" not in ss:
        ss.settings = load_settings()
    i18n.set_language(ss.settings.language)
    if "portfolio" not in ss:
        ss.portfolio = _load_working_portfolio() or Portfolio(name=t("My portfolio"),
                                                               base_currency=ss.settings.base_currency)
    ss.setdefault("builder_step", 1)
    ss.setdefault("analysis", None)
    ss.setdefault("analysis_sig", None)
    ss.setdefault("last_download_results", None)


def _working_portfolio_path() -> Path:
    s = st.session_state.settings
    name = "working_portfolio_demo.json" if s.use_demo_database else "working_portfolio.json"
    return Path(s.data_dir) / name


def _load_working_portfolio() -> Portfolio | None:
    """The portfolio being edited is kept across page reloads and restarts (e.g. after a theme switch)."""
    try:
        path = _working_portfolio_path()
        if path.exists():
            p = Portfolio.from_dict(json.loads(path.read_text(encoding="utf-8")))
            st.session_state._wp_json = path.read_text(encoding="utf-8")
            return p
    except Exception:  # a damaged file must never block the app
        return None
    return None


def save_working_portfolio() -> None:
    try:
        text = json.dumps(portfolio().to_dict(), ensure_ascii=False, sort_keys=True)
        if st.session_state.get("_wp_json") != text:
            path = _working_portfolio_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            st.session_state._wp_json = text
    except Exception:
        pass


def settings() -> AppSettings:
    return st.session_state.settings


def portfolio() -> Portfolio:
    return st.session_state.portfolio


def persist_settings() -> None:
    save_settings(settings())


@st.cache_resource(show_spinner=False)
def _db(path: str) -> Database:
    return Database(path)


def db() -> Database:
    return _db(str(database_path(settings())))


@st.cache_resource(show_spinner=False)
def _yahoo():
    from .yahoo_client import YahooProvider

    return YahooProvider()


def markets():
    return load_markets(settings().data_dir)


def market_name(market_id: str) -> str:
    m = markets().get(market_id)
    return t(m.name) if m else market_id


def service() -> DataService:
    s = settings()
    provider = SyntheticProvider() if s.use_demo_database else _yahoo()
    return DataService(db(), provider, markets(), s)


def is_demo() -> bool:
    return settings().use_demo_database


# ---------------------------------------------------------------------------
# Money, names, logos and brand colors
# ---------------------------------------------------------------------------
def capital() -> float:
    """Capital used for every money amount: the portfolio's total capital, else the default in Settings."""
    p = portfolio()
    return float(p.total_capital) if p.total_capital else float(settings().default_capital)


def ccy() -> str:
    return settings().base_currency


def fmt_money(v: float | None, sign: bool = False, digits: int = 0) -> str:
    return money_text(v, ccy(), digits, sign)


def fmt_compact(v: float | None, sign: bool = False) -> str:
    return money_compact(v, ccy(), sign)


def logo_service() -> LogoService:
    s = settings()
    return LogoService(db(), s.logostream_api_key.strip(), s.logostream_store_images,
                       offline=s.use_demo_database or not s.download_logos)


def ensure_logos(tickers: list[str], force: bool = False, progress=None) -> dict:
    try:
        return logo_service().ensure([tk for tk in tickers if tk], force, progress)
    except Exception:  # logos are cosmetic: never break a page
        return db().get_logos(list(tickers))


def ensure_portfolio_logos_once() -> None:
    """Fetch logos for the portfolio's tickers once per session (only tickers never tried before)."""
    ss = st.session_state
    key = "_logos_checked:" + ",".join(sorted(portfolio().tickers))
    if ss.get(key):
        return
    ss[key] = True
    missing = [tk for tk in portfolio().tickers if tk not in db().get_logos(portfolio().tickers)]
    if missing:
        ensure_logos(missing)


def logo_records(tickers: list[str]) -> dict[str, dict]:
    return db().get_logos(list(tickers))


def logo_uris(tickers: list[str]) -> dict[str, str | None]:
    recs = logo_records(tickers)
    return {tk: data_uri(logo_png(recs.get(tk))) for tk in tickers}


def names(tickers: list[str]) -> dict[str, str]:
    out = {}
    for tk in tickers:
        sec = db().get_security(tk) or {}
        out[tk] = sec.get("security_name") or tk
    return out


def security_colors(tickers: list[str]) -> dict[str, str]:
    """Brand color per security (readable on the current light/dark surface, kept distinguishable)."""
    from .charts import C

    tickers = list(dict.fromkeys(tickers))
    recs = logo_records(tickers) if settings().use_brand_colors else {}
    brand = {tk: (recs.get(tk) or {}).get("primary_color") for tk in tickers}
    return assign_colors(tickers, brand, list(C.series), C.surface)


def security_items(tickers: list[str] | None = None, market_id: str | None = None,
                   in_portfolio: set[str] | None = None) -> list[dict]:
    """Options for the logo picker from the securities stored in the local database."""
    secs = db().list_securities()
    if secs.empty:
        return []
    secs = secs[secs["n_obs"] > 0]
    secs = secs[~secs["ticker"].str.endswith("=X")]
    if market_id is not None:
        secs = secs[~secs["ticker"].str.startswith("^")]          # indices are benchmarks, not holdings
    if tickers is not None:
        secs = secs[secs["ticker"].isin(tickers)]
    if market_id is not None:
        m = markets().get(market_id)
        suff = tuple(m.ticker_suffixes) if m else ()

        def belongs(row) -> bool:
            if row["market_id"] == market_id:
                return True
            tk = row["ticker"]
            if suff:
                return tk.endswith(suff)
            return "." not in tk and not tk.startswith("^") and row["market_id"] in (None, "", market_id)
        secs = secs[secs.apply(belongs, axis=1)] if not secs.empty else secs
    tks = secs["ticker"].tolist()
    uris = logo_uris(tks)
    cols = security_colors(tks)
    items = []
    for row in secs.itertuples():
        sub = " · ".join(x for x in (market_name(row.market_id) if row.market_id else "", row.currency or "",
                                    t("{n} obs.", n=f"{int(row.n_obs):,}")) if x)
        held = in_portfolio is not None and row.ticker in in_portfolio
        items.append({"ticker": row.ticker, "name": row.security_name or row.ticker, "sub": sub,
                      "logo": uris.get(row.ticker), "color": cols.get(row.ticker),
                      "badge": t("in portfolio") if held else "", "disabled": held})
    return sorted(items, key=lambda x: (x["disabled"], x["name"].lower()))


def security_picker(key: str, market_id: str | None = None, in_portfolio: set[str] | None = None,
                    tickers: list[str] | None = None) -> str | None:
    from .picker import logo_picker

    items = security_items(tickers, market_id, in_portfolio)
    if not items:
        st.caption(t("No stored securities for this market yet. Add the first one by its exact Yahoo ticker."))
        return None
    return logo_picker(items, key=key, placeholder=t("Search by company name or ticker…"),
                       empty=t("No stored security matches."), count_text=t("{n} of {total} stored securities"))


def logo_column(label: str | None = None):
    return st.column_config.ImageColumn(label or "", width="small")


# ---------------------------------------------------------------------------
# Didactic blocks
# ---------------------------------------------------------------------------
def intro(text: str, icon: str = ":material/lightbulb:") -> None:
    """One or two sentences at the top of a page: what the reader is looking at."""
    st.markdown(f"<div class='gpl-intro'>{html.escape(text)}</div>", unsafe_allow_html=True)


def explain(doc_name: str, title: str | None = None, **kw: Any) -> None:
    """'How was this calculated?' panel with the page's method, data sources and formulas."""
    with st.expander(title or t("How was this calculated?"), icon=":material/calculate:"):
        st.markdown(i18n.doc(doc_name, **kw))


# ---------------------------------------------------------------------------
# Analysis cache (invalidated by portfolio, settings, language or stored-data changes)
# ---------------------------------------------------------------------------
ANALYSIS_KEYS = ("base_currency", "risk_free_annual", "return_frequency", "mu_estimator", "cov_estimator",
                 "ewma_lambda", "user_expected_returns", "constraint_mode", "long_only", "min_weight", "max_weight",
                 "analysis_mode", "min_observations", "coverage_tolerance_days", "fx_max_staleness_days",
                 "frontier_points", "max_risk_vertex_limit", "benchmark_ticker", "use_demo_database", "language",
                 "backfill_min_obs")


def analysis_signature() -> str:
    s = settings().to_dict()
    payload = {"portfolio": portfolio().to_dict(), "settings": {k: s[k] for k in ANALYSIS_KEYS},
               "data": db().data_version()}
    payload["portfolio"].pop("portfolio_id", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def portfolio_ready() -> tuple[bool, list[str]]:
    v = validate_holdings(portfolio(), settings().long_only)
    return v.ok, v.errors


def get_analysis(auto: bool = True) -> AnalysisBundle | None:
    """Return a current analysis; recompute when inputs changed (and auto=True)."""
    ok, errors = portfolio_ready()
    if not ok:
        with st.container(border=True):
            st.markdown(t("**No complete portfolio yet.** Build one in Portfolio Builder, or load the synthetic demo "
                          "in Settings to explore the app offline."))
            c1, c2, c3 = st.columns([1, 1, 2])
            c1.page_link("views/02_portfolio_builder.py", label=t("Open Portfolio Builder"),
                         icon=":material/construction:")
            c2.page_link("views/00_how_to_use.py", label=t("Read How to use"), icon=":material/menu_book:")
            if errors and portfolio().market_allocations:
                with st.expander(t("What is missing ({n})", n=len(errors))):
                    for e in errors:
                        st.write("- " + e)
        return None
    if auto:  # prices or exchange rates missing (download skipped or failed, base currency changed): fetch once
        gaps = data_gaps()
        if gaps["no_prices"] or gaps["no_fx"] or gaps.get("no_index"):
            key = json.dumps([gaps, settings().base_currency, is_demo()], sort_keys=True)
            tried = st.session_state.setdefault("gap_attempts", [])
            if key not in tried:
                tried.append(key)
                fill_data_gaps(gaps)
    sig = analysis_signature()
    current = st.session_state.analysis if st.session_state.analysis_sig == sig else None
    if current is None and auto:
        with st.spinner(t("Running analysis for all five horizons (estimation, optimization, frontier)...")):
            current = run_analysis(db(), portfolio(), settings(), markets(), HORIZONS_YEARS)
        st.session_state.analysis, st.session_state.analysis_sig = current, sig
    return ensure_custom(current)


# ---------------------------------------------------------------------------
# Visual design: CSS, header with allocation strip, sidebar
# ---------------------------------------------------------------------------
CSS_VARS = {
    "light": ":root{--gpl-ink:#142033;--gpl-ink2:#4a5568;--gpl-muted:#7b8494;--gpl-paper:#f5f7fa;"
             "--gpl-surface:#ffffff;--gpl-line:#e1e6ee;--gpl-cobalt:#1d5bb8;--gpl-input:#eef3fa;--gpl-ok:#0c7a54;}",
    "dark": ":root{--gpl-ink:#e6ebf2;--gpl-ink2:#b4bfcd;--gpl-muted:#8592a3;--gpl-paper:#0f1520;"
            "--gpl-surface:#161e2b;--gpl-line:#2a3546;--gpl-cobalt:#5b9cf0;--gpl-input:#18233a;--gpl-ok:#3ccf91;}",
}
CSS = """
<style>
__VARS__
.block-container{padding-top:2.2rem;max-width:1320px;}
h1,h2,h3{color:var(--gpl-ink);letter-spacing:-0.01em;}
h2{font-size:1.35rem !important;margin-top:.6rem;}
h3{font-size:1.1rem !important;}
[data-testid="stMetric"]{background:var(--gpl-surface);border:1px solid var(--gpl-line);border-radius:10px;
padding:12px 16px 10px 16px;}
[data-testid="stMetricLabel"] p{color:var(--gpl-ink2);font-size:.82rem;}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;font-weight:600;color:var(--gpl-ink);
font-size:1.5rem;}
[data-testid="stDataFrame"]{font-variant-numeric:tabular-nums;}
[data-testid="stPlotlyChart"]{background:var(--gpl-surface);border:1px solid var(--gpl-line);border-radius:10px;
padding:6px 8px 2px 8px;}
div[class*="st-key-inputs"]{background:var(--gpl-input);border-left:3px solid var(--gpl-cobalt);
border-radius:0 10px 10px 0;padding:14px 16px 4px 16px;}
.gpl-head{margin:0 0 1.1rem 0;}
.gpl-head h1{font-size:2.05rem;font-weight:700;margin:0;padding:0;line-height:1.15;}
.gpl-head .gpl-sub{color:var(--gpl-ink2);margin:.35rem 0 .9rem 0;max-width:72ch;font-size:.98rem;}
.gpl-strip{display:flex;gap:2px;height:10px;border-radius:5px;overflow:hidden;background:var(--gpl-line);}
.gpl-strip span{display:block;height:100%;}
.gpl-strip.empty{background:repeating-linear-gradient(90deg,var(--gpl-line) 0 8px,transparent 8px 12px);}
.gpl-legend{display:flex;flex-wrap:wrap;gap:4px 18px;margin:.45rem 0 0 0;font-size:.84rem;color:var(--gpl-ink2);
font-variant-numeric:tabular-nums;}
.gpl-legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px;vertical-align:0;}
.gpl-context{display:flex;flex-wrap:wrap;gap:4px 22px;margin-top:.55rem;font-size:.82rem;color:var(--gpl-muted);}
.gpl-context b{color:var(--gpl-ink2);font-weight:600;margin-right:4px;}
.gpl-side-steps{font-size:.88rem;line-height:1.9;color:var(--gpl-ink2);}
.gpl-side-steps .ok{color:var(--gpl-ok);}
div[class*="st-key-guide"] p,div[class*="st-key-guide"] li,div[class*="st-key-guide"] blockquote{max-width:78ch;}
.gpl-footer{color:var(--gpl-muted);font-size:.78rem;margin-top:2.5rem;border-top:1px solid var(--gpl-line);
padding-top:.6rem;max-width:90ch;}
.gpl-intro{border-left:3px solid var(--gpl-cobalt);background:var(--gpl-input);border-radius:0 10px 10px 0;
padding:10px 14px;margin:0 0 1rem 0;color:var(--gpl-ink);font-size:.95rem;max-width:95ch;}
[data-testid="stSidebarNav"] a{border-radius:8px;margin:1px 0;}
[data-testid="stSidebarNav"] a[aria-current="page"]{background:var(--gpl-input);box-shadow:inset 3px 0 0 var(--gpl-cobalt);}
[data-testid="stSidebarNavSeparator"]{margin:.4rem 0;}
[data-testid="stNavSectionHeader"]{font-weight:700;letter-spacing:.02em;color:var(--gpl-ink2);text-transform:none;}
.gpl-map{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:.3rem 0 1rem 0;}
.gpl-stage{border:1px solid var(--gpl-line);border-radius:12px;background:var(--gpl-surface);padding:12px 14px;}
.gpl-stage h4{margin:0 0 .2rem 0;font-size:1rem;}
.gpl-stage p{margin:0;color:var(--gpl-ink2);font-size:.85rem;}
.gpl-chip{display:inline-block;font-size:.72rem;border-radius:10px;padding:1px 8px;margin-left:6px;
border:1px solid var(--gpl-line);color:var(--gpl-ink2);}
.gpl-chip.ok{color:var(--gpl-ok);border-color:var(--gpl-ok);}
.gpl-attrib{font-size:.78rem;color:var(--gpl-muted);}
.gpl-sec{display:flex;align-items:center;gap:12px;margin:.2rem 0 .6rem 0;}
.gpl-sec img,.gpl-sec .ini{width:44px;height:44px;border-radius:10px;background:#fff;object-fit:contain;
box-shadow:0 0 0 1px var(--gpl-line);}
.gpl-sec .ini{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;}
.gpl-sec .nm{font-size:1.15rem;font-weight:700;color:var(--gpl-ink);line-height:1.2;}
.gpl-sec .sb{font-size:.85rem;color:var(--gpl-ink2);}
.gpl-sec .sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;}
@media (max-width: 640px){.gpl-head h1{font-size:1.6rem;}.gpl-map{grid-template-columns:1fr;}}
</style>
"""


def theme_mode() -> str:
    """'dark' or 'light': the theme the browser is actually showing (falls back to the saved choice)."""
    current = getattr(getattr(st.context, "theme", None), "type", None)
    if current in ("light", "dark"):
        return current
    return settings().theme if settings().theme in ("light", "dark") else "light"


def inject_css() -> None:
    """Mode-aware CSS variables and chart palette for this run."""
    from .charts import set_dark

    mode = theme_mode()
    set_dark(mode == "dark")
    st.markdown(CSS.replace("__VARS__", CSS_VARS[mode]), unsafe_allow_html=True)


URL_SLUGS = ("dashboard", "how-to-use", "builder", "explorer", "database", "statistics", "currency", "frontier",
             "optimized", "risk", "backtesting", "reports", "settings")

THEME_JS = r"""
<script>
(function () {
  const mode = "__MODE__";            // Streamlit's own stored theme choice: "Light" | "Dark"
  const slugs = __SLUGS__;
  const path = window.location.pathname;
  let base = path.replace(/\/$/, "");
  for (const s of slugs) {
    if (base.endsWith("/" + s)) { base = base.slice(0, base.length - s.length - 1); break; }
  }
  const paths = new Set([path, base + "/", base || "/"]);
  for (const s of slugs) { paths.add(base + "/" + s); }
  for (const p of paths) {
    try { window.localStorage.setItem("stActiveTheme-" + p + "-v2", JSON.stringify(mode)); } catch (e) {}
  }
  window.location.reload();
})();
</script>
"""


def _toggle_theme(target_dark: bool) -> None:
    settings().theme = "dark" if target_dark else "light"
    persist_settings()
    save_working_portfolio()            # the reload starts a new session; keep the work in progress
    st.session_state._apply_theme = "Dark" if target_dark else "Light"


def allocation_strip_html(allocations: dict[str, float]) -> str:
    items = [(m, a) for m, a in allocations.items() if a and a > 0]
    if not items:
        return (f"<div class='gpl-strip empty' role='img' aria-label='{html.escape(t('No market allocation yet'))}'>"
                f"</div><div class='gpl-legend'>{html.escape(t('No market allocation yet'))}</div>")
    colors = market_colors([m for m, _ in items])
    label = ", ".join(f"{market_name(m)} {a:.1f}%" for m, a in items)
    bars = "".join(f"<span style='flex:{a:.6f};background:{colors[m]}' title='{html.escape(market_name(m))} "
                   f"{a:.2f}%'></span>" for m, a in items)
    legend = "".join(f"<span><i style='background:{colors[m]}'></i>{html.escape(market_name(m))} {a:.1f}%</span>"
                     for m, a in items)
    return (f"<div class='gpl-strip' role='img' aria-label='{html.escape(t('Market allocation'))}: "
            f"{html.escape(label)}'>{bars}</div><div class='gpl-legend'>{legend}</div>")


def page_header(title: str, subtitle: str = "", show_allocation: bool = True) -> None:
    s = settings()
    p = portfolio()
    data = t("Synthetic demo data") if s.use_demo_database else "Yahoo Finance"
    parts = [f"<div class='gpl-head'><h1>{html.escape(title)}</h1>"]
    if subtitle:
        parts.append(f"<p class='gpl-sub'>{html.escape(subtitle)}</p>")
    if show_allocation:
        parts.append(allocation_strip_html(p.market_allocations))
        parts.append("<div class='gpl-context'>"
                     f"<span><b>{html.escape(t('Portfolio'))}</b>{html.escape(p.name)}</span>"
                     f"<span><b>{html.escape(t('Base currency'))}</b>{s.base_currency}</span>"
                     f"<span><b>{html.escape(t('Risk-free'))}</b>{s.risk_free_annual:.2%} "
                     f"{html.escape(t('(assumed)'))}</span>"
                     f"<span><b>{html.escape(t('Data'))}</b>{html.escape(data)}</span></div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)
    if is_demo():
        st.warning(t("**Synthetic demo database.** Prices and exchange rates here are illustrative, not market "
                     "data. Turn it off in Settings to use Yahoo Finance."), icon=":material/science:")


def footer() -> None:
    text = t("Historical, in-sample analysis for study purposes. Optimized portfolios are estimates, not forecasts "
             "or investment recommendations. Data: Yahoo Finance via an unofficial interface, without guarantees of "
             "completeness.")
    attrib = ""
    if settings().logostream_api_key.strip():
        attrib = "<div class='gpl-attrib'>" + ATTRIBUTION_HTML + "</div>"
    st.markdown("<div class='gpl-footer'>" + html.escape(text) + attrib + "</div>", unsafe_allow_html=True)


def horizon_label(h: int, bundle: AnalysisBundle | None = None) -> str:
    if h == CUSTOM and not is_custom(h):
        ch = custom_key(bundle)
        base = "✎ " + t("Custom") + (f": {ch.duration()}" if ch is not None else "")
        if ch is None:
            return base
        h = ch
    else:
        base = i18n.years(h, short=True)
    if bundle is None or h not in bundle.horizons:
        return base
    r = bundle.horizons[h]
    if r.status == "COMPLETE" and any(rec.n_filled for rec in r.reconstructed.values()):
        return f"{base} ({t('with reconstruction')})"
    return base if r.status == "COMPLETE" else f"{base} ({status_label(r.status).lower()})"


def horizon_selector(bundle: AnalysisBundle | None, key: str):
    """Fixed horizons (1, 3, 5, 10, 15 years) as shortcuts, plus a custom window chosen by the user.
    Returns the horizon key to use with ``bundle.horizons``."""
    opts = list(HORIZONS_YEARS) + [CUSTOM]
    default = settings().selected_horizon if settings().selected_horizon in opts else 5
    if st.session_state.get(key) is None:
        st.session_state[key] = default
    h = st.segmented_control(t("Analysis horizon"), opts, format_func=lambda x: horizon_label(x, bundle), key=key,
                             help=t("The fixed horizons are shortcuts; choose Custom to analyze any window."))
    h = h if h is not None else default
    if h != settings().selected_horizon:
        settings().selected_horizon = h
        persist_settings()
    if h == CUSTOM and bundle is not None:
        return _custom_window_controls(bundle, key)
    return h


# ---------------------------------------------------------------------------
# Custom analysis window
# ---------------------------------------------------------------------------
def custom_key(bundle: AnalysisBundle | None) -> CustomHorizon | None:
    return next((k for k in bundle.horizons if is_custom(k)), None) if bundle is not None else None


def _data_span(bundle: AnalysisBundle) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """(earliest stored date, date from which every holding trades, last common date)."""
    pb = bundle.prices_base
    firsts = [pb[c].first_valid_index() for c in pb.columns if pb[c].notna().any()]
    hi = pd.Timestamp(bundle.data_cutoff) if bundle.data_cutoff else pb.index.max()
    if not firsts:
        return hi, hi, hi
    return min(firsts), max(firsts), hi


def _custom_presets(bundle: AnalysisBundle) -> dict[str, tuple[pd.Timestamp, str]]:
    lo, newest, hi = _data_span(bundle)
    ytd = pd.Timestamp(hi.year if hi.month > 1 else hi.year - 1, 1, 1)
    out = {"3m": (hi - pd.DateOffset(months=3), t("3 months")), "6m": (hi - pd.DateOffset(months=6), t("6 months")),
           "ytd": (ytd, t("Year to date")), "2y": (hi - pd.DateOffset(years=2), t("2 years")),
           "7y": (hi - pd.DateOffset(years=7), t("7 years"))}
    if newest > lo + pd.Timedelta(days=30) and (hi - newest).days >= 20:
        out["common"] = (newest, t("Since every holding trades ({date})", date=f"{newest:%Y-%m-%d}"))
    out["all"] = (lo, t("All stored history (from {date})", date=f"{lo:%Y-%m-%d}"))
    return {k: (max(v[0], lo), v[1]) for k, v in out.items()}


def _default_custom_window(bundle: AnalysisBundle) -> None:
    lo, newest, hi = _data_span(bundle)
    start = newest if (newest > lo + pd.Timedelta(days=30) and (hi - newest).days >= 60) else hi - pd.DateOffset(months=6)
    settings().custom_horizon_start, settings().custom_horizon_end = f"{max(start, lo):%Y-%m-%d}", ""
    persist_settings()


def _custom_window(bundle: AnalysisBundle) -> CustomHorizon | None:
    s = settings()
    if not s.custom_horizon_start:
        return None
    lo, _, hi = _data_span(bundle)
    end = min(pd.Timestamp(s.custom_horizon_end), hi) if s.custom_horizon_end else hi
    start = max(pd.Timestamp(s.custom_horizon_start), lo)
    if start >= end:
        start = max(end - pd.DateOffset(months=6), lo)
    return CustomHorizon(start, end)


def ensure_custom(bundle: AnalysisBundle | None) -> AnalysisBundle | None:
    """Put the user's custom window into ``bundle.horizons`` (computed once per window and data version)."""
    if bundle is None:
        return bundle
    ch = _custom_window(bundle)
    for k in [k for k in bundle.horizons if is_custom(k) and k != ch]:
        del bundle.horizons[k]
    if ch is None or ch in bundle.horizons:
        return bundle
    cache = st.session_state.setdefault("custom_h_cache", {})
    ckey = (st.session_state.get("analysis_sig"), ch.start, ch.end)
    if ckey not in cache:
        if len(cache) > 12:
            cache.clear()
        with st.spinner(t("Analyzing the window {period}...", h=ch)):
            cache[ckey] = analyze_custom(bundle, portfolio(), settings(), ch)
    bundle.horizons[ch] = cache[ckey]
    return bundle


def _on_custom_dates(rkey: str, pkey: str, hi: str) -> None:
    v = st.session_state.get(rkey)
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] < v[1]:
        settings().custom_horizon_start = v[0].isoformat()
        settings().custom_horizon_end = "" if v[1].isoformat() >= hi else v[1].isoformat()
        persist_settings()
        st.session_state[pkey] = None


def _on_custom_preset(pkey: str, rkey: str, presets: dict) -> None:
    k = st.session_state.get(pkey)
    if k in presets:
        settings().custom_horizon_start, settings().custom_horizon_end = presets[k], ""
        persist_settings()
        st.session_state.pop(rkey, None)


def _custom_window_controls(bundle: AnalysisBundle, key: str):
    if not settings().custom_horizon_start:
        _default_custom_window(bundle)
    ensure_custom(bundle)
    ch = custom_key(bundle)
    lo, _, hi = _data_span(bundle)
    presets = _custom_presets(bundle)
    rkey, pkey = f"{key}_crange", f"{key}_cpreset"
    cur = st.session_state.get(rkey)
    if ch is not None and not (isinstance(cur, (list, tuple)) and len(cur) == 1):   # keep a half-picked range
        st.session_state[rkey] = (ch.start.date(), ch.end.date())
    with st.container(key=f"inputs_{key}_custom"):
        st.pills(t("Quick windows"), list(presets), format_func=lambda k: presets[k][1], key=pkey,
                 on_change=_on_custom_preset, args=(pkey, rkey, {k: f"{v[0]:%Y-%m-%d}" for k, v in presets.items()}))
        c1, _ = st.columns([2, 3])
        c1.date_input(t("Window (from – to)"), key=rkey, min_value=lo.date(), max_value=hi.date(),
                      format="YYYY-MM-DD", on_change=_on_custom_dates, args=(rkey, pkey, f"{hi:%Y-%m-%d}"),
                      help=t("If the end is the last available date, the window moves forward when new prices "
                             "are downloaded."))
        if ch is not None:
            r = bundle.horizons[ch]
            note = t("Window of {period}: {n} return observations.", h=ch, n=f"{r.n_obs:,}")
            if ch.days < 365:
                note += " " + t("Under a year: annualized figures are extrapolated from few data.")
            st.caption(note)
    return ch if ch is not None else 5


def horizon_banner(r: HorizonResult) -> None:
    freq = t("weekly") if settings().return_frequency == "weekly" else t("daily")
    if r.status == "COMPLETE":
        msg = t("**Horizon {period}, {label}.** Sample {start} to {end}: {n} {freq} return observations "
                "({years} years), {k} securities.", h=r.horizon, label=r.label, start=f"{r.start:%Y-%m-%d}",
                end=f"{r.end:%Y-%m-%d}", n=r.n_obs, freq=freq, years=f"{r.actual_years:.2f}", k=len(r.universe))
        if r.mode != "strict" and (r.excluded or r.actual_years < r.horizon - 0.1):
            lines, kinds = _reason_lines(r)
            extra = ("\n\n" + t("Left out:") + "\n" + "\n".join("- " + x for x in lines)) if lines else ""
            st.warning(msg + " " + t("This is NOT the original full-horizon portfolio analysis.") + extra,
                       icon=":material/warning:")
            if kinds & {"no_prices", "no_fx"} and st.button(t("Download what is missing"),
                                                             icon=":material/cloud_download:",
                                                             key=f"gap_dl_{r.horizon}"):
                fill_data_gaps()
                st.rerun()
        elif r.reconstructed:
            lines = reconstruction_lines(r)
            st.warning(msg + "\n\n" + t("Reconstructed history (estimated, not market data):") + "\n" +
                       "\n".join("- " + x for x in lines), icon=":material/auto_fix_high:")
        else:
            st.success(msg, icon=":material/check_circle:")
    else:
        _explain_incomplete(r)
    if r.warnings:
        with st.expander(t("Data notes and warnings ({n})", n=len(r.warnings)), expanded=r.status == "ERROR"):
            for w in r.warnings:
                st.write("- " + w)


def factor_name(name: str) -> str:
    if name.startswith("avg:"):
        return t("other {market} holdings", market=market_name(name[4:]))
    if name == "rest":
        return t("rest of the portfolio")
    return t("index {ticker}", ticker=name)


def reconstruction_lines(r: HorizonResult) -> list[str]:
    nm = names(list(r.reconstructed))
    out = []
    for tk, rec in r.reconstructed.items():
        out.append(t("**{name}** (`{ticker}`): real prices since {first} ({real}% of the sample); the earlier {share}% "
                     "follows its betas to {factors} (R² {r2}) plus its own real day-to-day noise, with no extra "
                     "return.", name=nm.get(tk, tk), ticker=tk,
                     first=f"{rec.first_real:%Y-%m-%d}" if rec.first_real is not None else "–",
                     real=f"{100 * (1 - rec.share_filled):.0f}", share=f"{100 * rec.share_filled:.0f}",
                     factors=", ".join(f"{factor_name(f)} ({rec.betas.get(f, 0):.2f})" for f in rec.factors),
                     r2=f"{rec.r2:.2f}"))
    return out


def shade_reconstructed(fig, r: HorizonResult):
    """Grey band over the dates where some holding's returns are reconstructed."""
    ends = [rec.first_real for rec in r.reconstructed.values() if rec.first_real is not None and rec.n_filled]
    if ends and r.start is not None:
        fig.add_vrect(x0=r.start, x1=max(ends), fillcolor="#8592a3", opacity=0.12, line_width=0, layer="below",
                      annotation_text=t("reconstructed history"), annotation_position="top left",
                      annotation_font_size=11)
    return fig


def _reason_lines(r: HorizonResult) -> tuple[list[str], set[str]]:
    lines, reasons = _reasons_text(r)
    return lines, {o["kind"] for o in reasons}


def _reasons_text(r: HorizonResult) -> tuple[list[str], list[dict]]:
    s = settings()
    reasons = incomplete_reasons(r, st.session_state.get("analysis"), portfolio().tickers, s.min_observations)
    nm = names([o["ticker"] for o in reasons if o["ticker"]])
    lines = []
    for o in reasons:
        if o["kind"] == "short_window":
            lines.append(t("The window has only {n} return observations and the minimum is {needed}: widen the "
                           "window or lower the minimum.", n=o["n"], needed=o["needed"]))
            continue
        who = f"**{nm.get(o['ticker'], o['ticker'])}** (`{o['ticker']}`)"
        if o["kind"] == "no_prices":
            lines.append(t("{who}: its prices have not been downloaded yet.", who=who))
        elif o["kind"] == "no_fx":
            lines.append(t("{who}: there is no stored exchange rate {pair} to convert its prices to {base}.",
                           who=who, pair=o["pair"], base=s.base_currency))
        elif o["kind"] == "short":
            first = f"{pd.Timestamp(o['first']):%Y-%m-%d}" if o["first"] is not None else "–"
            needed = f"{pd.Timestamp(o['needed']):%Y-%m-%d}" if o["needed"] is not None else "–"
            line = t("{who}: data only since {first} ({years} years); this horizon needs data from {needed}.",
                     who=who, first=first, years=f"{o['years']:.1f}", needed=needed)
            if o["fx_dropped"]:
                line += " " + t("({n} days were dropped because the exchange rate {pair} is missing on those dates.)",
                                n=f"{o['fx_dropped']:,}", pair=o["pair"])
            lines.append(line)
        elif o["kind"] == "too_short":
            first = f"{pd.Timestamp(o['first']):%Y-%m-%d}" if o.get("first") is not None else "–"
            lines.append(t("{who}: listed on {first}; only {n} real returns so far, and reconstructing its earlier "
                           "history needs at least {needed}.", who=who, first=first, n=o["n"], needed=o["needed"]))
        elif o["kind"] == "sparse":
            lines.append(t("{who}: only {n} prices in this window; all holdings trade together on just {common} "
                           "dates.", who=who, n=f"{o['n']:,}", common=f"{o['n_common']:,}"))
    return lines, reasons


def _explain_incomplete(r: HorizonResult) -> None:
    """Say plainly why a horizon has no statistics and offer the fix that applies."""
    s = settings()
    lines, reasons = _reasons_text(r)
    head = t("**Horizon {period}: {status}** ({label}).", h=r.horizon, status=status_label(r.status), label=r.label)
    if lines:
        head += "\n\n" + t("Why:") + "\n" + "\n".join("- " + x for x in lines)
    st.error(head, icon=":material/warning:")
    kinds = {o["kind"] for o in reasons}
    if not kinds:
        return
    if kinds & {"no_prices", "no_fx"}:
        if st.button(t("Download what is missing"), icon=":material/cloud_download:", type="primary",
                     key=f"gap_dl_{r.horizon}"):
            fill_data_gaps()
            st.rerun()
    if "short" in kinds and s.analysis_mode in ("strict", "available_history", "common_universe"):
        short = [o["ticker"] for o in reasons if o["kind"] == "short"]
        if st.button(t("Reconstruct the short history of {tickers} (recommended for IPOs)", tickers=", ".join(short)),
                     icon=":material/auto_fix_high:", type="primary", key=f"gap_recon_{r.horizon}",
                     help=t("Keeps every holding and the full horizon. Only the missing early returns of the new "
                            "listing are estimated from its relationship with the other holdings; every other "
                            "holding keeps 100% real data.")):
            s.analysis_mode = "reconstructed"
            persist_settings()
            st.rerun()
    if "short" in kinds and s.analysis_mode == "strict":
        st.caption(t("Other labelled alternatives:"))
        cols = st.columns(2)
        if cols[0].button(t("Analyze with the available history"), icon=":material/history:",
                          key=f"gap_avail_{r.horizon}",
                          help=t("Keeps every holding; the sample starts when the youngest one starts trading.")):
            s.analysis_mode = "available_history"
            persist_settings()
            st.rerun()
        if cols[1].button(t("Leave out {tickers}", tickers=", ".join(short)), icon=":material/filter_alt:",
                          key=f"gap_common_{r.horizon}",
                          help=t("Analyzes the other holdings over the full horizon; weights are rescaled within "
                                 "each market.")):
            s.analysis_mode = "common_universe"
            persist_settings()
            st.rerun()
        longest = min((o["years"] for o in reasons if o["kind"] == "short"), default=0.0)
        if longest >= 1:
            st.caption(t("With these holdings the longest complete horizon is about {years} years: choose a shorter "
                         "horizon above, or one of the buttons.", years=f"{longest:.1f}"))
    if "short_window" in kinds:
        n = next(o["n"] for o in reasons if o["kind"] == "short_window")
        if n >= 20 and st.button(t("Accept {n} observations (lower the minimum)", n=n), icon=":material/tune:",
                                 key=f"gap_minobs_{r.horizon}",
                                 help=t("Changes 'Minimum observations' in Settings for every horizon.")):
            s.min_observations = int(n)
            persist_settings()
            st.rerun()
    if "too_short" in kinds:
        st.caption(t("Choose a shorter horizon, wait a few more trading days, or lower the minimum in Settings → "
                     "Horizons and coverage."))
    if "sparse" in kinds:
        st.caption(t("Few common dates usually means a security that trades rarely (for example some SIC listings). "
                     "Weekly returns in Settings, or replacing that security, solve it."))


def data_gaps() -> dict:
    """Holdings without prices and currencies without exchange rates for the current portfolio."""
    p, s = portfolio(), settings()
    try:
        indexes = None
        if s.analysis_mode == "reconstructed" and not is_demo():
            cutoff = pd.Timestamp.today() - pd.DateOffset(years=s.history_years) + pd.Timedelta(days=60)
            mk = markets()
            indexes = []
            for h in p.holdings:
                first, _, n = db().get_date_range(h.ticker)
                m = mk.get(h.market_id)
                if n and pd.Timestamp(first) > cutoff and m and m.benchmark and [m.benchmark, h.market_id] not in \
                        indexes:
                    indexes.append([m.benchmark, h.market_id])
        return service().data_gaps(p.tickers, s.base_currency, indexes)
    except Exception:  # never break a page because of the check itself
        return {"no_prices": [], "no_fx": {}}


def fill_data_gaps(gaps: dict | None = None) -> list:
    """Download the prices and exchange rates the analysis is missing, with visible progress."""
    p, s = portfolio(), settings()
    gaps = gaps or data_gaps()
    if not gaps["no_prices"] and not gaps["no_fx"] and not gaps.get("no_index"):
        return []
    items = ", ".join(gaps["no_prices"] + [f"{c}→{s.base_currency}" for c in sorted(gaps["no_fx"])] +
                      [tk for tk, _ in gaps.get("no_index", [])])
    with st.status(t("Downloading what the analysis needs: {items}", items=items), expanded=False) as box:
        bar = st.progress(0.0)
        results = service().fill_gaps([(h.ticker, h.market_id) for h in p.holdings], s.base_currency, gaps,
                                      progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0), m))
        bad = [r for r in results if r.status not in ("SUCCESS", "UP_TO_DATE", "PARTIAL") and not r.optional]
        for r in results:
            st.write(f"{r.symbol}: {status_label(r.status)}" + (f" — {r.messages[-1]}" if r.messages and
                                                                  r in bad else ""))
        box.update(label=t("Download finished with problems: {items}", items=", ".join(r.symbol for r in bad))
                   if bad else t("Missing data downloaded: {items}", items=items),
                   state="error" if bad else "complete")
    if gaps["no_prices"]:
        ensure_logos(gaps["no_prices"])
    return results


def assumptions_expander() -> None:
    s = settings()
    if s.constraint_mode == "fixed_markets":
        constraints = t("fixed market budgets") + r" $\sum_{i\in m} w_i = A_m$"
    else:
        constraints = t("global budget only (market allocations free)") + r" $\sum_i w_i = 1$"
    if s.long_only:
        positions = t("long-only") + r" $w_i \ge 0$"
    else:
        positions = t("short selling allowed") + rf" $w_i \ge {s.min_weight:.0%}$".replace("%", r"\%")
    if s.max_weight:
        positions += "; " + t("cap") + rf" $w_i \le {s.max_weight:.0%}$".replace("%", r"\%")
    with st.expander(t("Formulas, assumptions and conventions"), icon=":material/function:"):
        st.markdown(i18n.doc("assumptions", base=s.base_currency, staleness=s.fx_max_staleness_days,
                             n=s.periods_per_year, rf=f"{s.risk_free_annual:.2%}",
                             mu=t(ESTIMATOR_LABELS.get(s.mu_estimator, s.mu_estimator)),
                             cov=t(ESTIMATOR_LABELS.get(s.cov_estimator, s.cov_estimator)),
                             constraints=constraints, positions=positions))


def pct(v: Any, digits: int = 2) -> str:
    try:
        return t("n/a") if v is None or pd.isna(v) else f"{v:.{digits}%}"
    except TypeError:
        return str(v)


def num(v: Any, digits: int = 3) -> str:
    try:
        return t("n/a") if v is None or pd.isna(v) else f"{v:.{digits}f}"
    except TypeError:
        return str(v)


def as_pct_frame(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce") * 100
    return out


def _change_language() -> None:
    code = st.session_state.get("language_selector")
    if code:
        settings().language = i18n.set_language(code)
        st.session_state.settings_language = settings().language  # keep the Settings-page selector in sync
        persist_settings()


def sidebar_top() -> None:
    """Logo and language selector (rendered before the page so a change applies immediately)."""
    suffix = "_dark" if theme_mode() == "dark" else ""
    logo, icon = ASSETS / f"logo{suffix}.svg", ASSETS / f"icon{suffix}.svg"
    if logo.exists():
        st.logo(str(logo), size="large", icon_image=str(icon) if icon.exists() else None)
    langs = i18n.available_languages()
    if st.session_state.get("language_selector") not in langs:
        st.session_state.language_selector = i18n.get_language()
    with st.sidebar:
        st.selectbox(":material/translate: " + t("Language"), list(langs), format_func=lambda c: langs[c],
                     key="language_selector", on_change=_change_language)
        dark = theme_mode() == "dark"
        st.toggle(":material/dark_mode: " + t("Dark mode"), value=dark, key=f"theme_toggle_{int(dark)}",
                  on_change=_toggle_theme, args=(not dark,),
                  help=t("Switches the whole interface. The page reloads; your portfolio and settings are kept."))
        target = st.session_state.pop("_apply_theme", None)
        if target:
            st.html(THEME_JS.replace("__MODE__", target).replace("__SLUGS__", json.dumps(list(URL_SLUGS))),
                    unsafe_allow_javascript=True)


def sidebar_status() -> None:
    s = settings()
    p = portfolio()
    with st.sidebar:
        alloc_ok = validate_market_allocations(p.market_allocations).ok if p.market_allocations else False
        ready, _ = portfolio_ready()
        data_ok = False
        if ready:
            data_ok = all(db().get_date_range(tk)[2] > 0 for tk in p.tickers)
        analysis_ok = st.session_state.analysis is not None and st.session_state.analysis_sig == \
            (analysis_signature() if ready else None)
        steps = [(t("Market allocation"), alloc_ok), (t("Securities and weights"), ready),
                 (t("Historical data"), data_ok), (t("Analysis up to date"), analysis_ok)]
        n_done = sum(ok for _, ok in steps)
        st.markdown(f"**{t('Workflow')}**")
        st.progress(n_done / len(steps), text=t("{done} of {total} steps complete", done=n_done, total=len(steps)))
        rows = "".join(f"<div class='{'ok' if ok else ''}'>{'✓' if ok else '○'}&nbsp; {html.escape(name)}</div>"
                       for name, ok in steps)
        st.markdown(f"<div class='gpl-side-steps'>{rows}</div>", unsafe_allow_html=True)
        st.caption(t("Data: {source}", source=t("Synthetic demo") if s.use_demo_database else PROVIDER_NAME))
        st.caption(t("Database: {name}", name=database_path(s).name))
    save_working_portfolio()


def page_title(name: str) -> str:
    """Browser-tab title."""
    return f"{name} | {APP_NAME}"


def gap_report_view(gaps: dict) -> None:
    """Exchange-calendar coverage report as metrics plus a short explanation."""
    g = st.columns(4)
    g[0].metric(t("Expected sessions"), gaps.get("expected", 0))
    g[1].metric(t("Observed"), gaps.get("observed", 0))
    g[2].metric(t("Missing sessions"), gaps.get("missing", 0))
    g[3].metric(t("Coverage"), f"{gaps.get('coverage_pct', 0):.2f}%")
    method = gaps.get("method", "")
    if method.startswith("exchange_calendars"):
        method = t("exchange calendar {code}", code=method.split()[-1])
    elif method.startswith("weekday"):
        method = t("weekday heuristic (no exchange calendar)")
    long_gaps = gaps.get("long_gaps") or []
    long_text = ", ".join(f"{x['from']}–{x['to']} ({x['sessions']})" for x in long_gaps) or t("none")
    st.caption(t("Method: {method}. Isolated provider gaps: {isolated}. Long gaps (possible suspension or outage): "
                 "{long}. Missing sessions at the end (stale or possibly delisted): {trailing}. Observations on "
                 "non-session days: {extra}. Exchange holidays are not counted as missing.", method=method,
                 isolated=gaps.get("isolated_provider_gaps", 0), long=long_text,
                 trailing=gaps.get("trailing_missing_sessions", 0), extra=gaps.get("non_session_observations", 0)))


def security_card(ticker: str) -> None:
    """Logo, name, ticker, market and the chart color of one security."""
    from .picker import initials

    sec = db().get_security(ticker) or {}
    name = sec.get("security_name") or ticker
    uri = logo_uris([ticker]).get(ticker)
    color = security_colors([ticker]).get(ticker, "#7b8494")
    tile = (f"<img alt='' src='{uri}'>" if uri else
            f"<span class='ini' style='background:{color}'>{html.escape(initials(name, ticker))}</span>")
    sub = " · ".join(x for x in (ticker, market_name(sec.get("market_id")) if sec.get("market_id") else "",
                                sec.get("exchange") or "", sec.get("currency") or "") if x)
    st.markdown(f"<div class='gpl-sec'>{tile}<div><div class='nm'>{html.escape(name)}</div>"
                f"<div class='sb'><span class='sw' style='background:{color}'></span>{html.escape(sub)}</div></div></div>",
                unsafe_allow_html=True)
