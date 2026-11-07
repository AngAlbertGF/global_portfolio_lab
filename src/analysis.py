"""Horizon orchestration: coverage rules, estimation, statistics, optimisation, frontier.

Coverage modes (never applied silently -- every result carries its label):
* strict             original portfolio only; a horizon is COMPLETE only if every holding has
                     history back to the horizon start (within a tolerance) and >= min observations.
* common_universe    drops holdings that lack the full horizon; within-market weights of the remaining
                     holdings are rescaled, and markets left empty are removed with the remaining market
                     budgets rescaled proportionally.  Membership change is listed explicitly.
* available_history  keeps all holdings but starts the sample at the latest first-observation date, so the
                     sample is SHORTER than the nominal horizon.  Actual span is reported.
* reconstructed      keeps all holdings and the full horizon; the missing early returns of a recently listed
                     holding (IPO) are estimated with a factor model fitted on its real returns (src/backfill.py).
                     Every other holding keeps 100% real data; the reconstructed share is reported per holding.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .backfill import reconstruct_frame
from .config import AppSettings, MarketConfig
from .database import Database
from .frontier import FrontierResult, build_frontier
from .horizons import is_custom
from .i18n import N_, t, years
from .optimization import ConstraintSet, OptimizationResult, run_all
from .returns import common_calendar, load_base_currency_prices, simple_returns, to_frequency
from .statistics import asset_statistics, check_covariance, concentration, cov_to_corr, estimate_cov, estimate_mu, \
    portfolio_statistics, rf_markowitz, risk_decomposition
from .validation import Portfolio, global_weights, major_currency

logger = logging.getLogger("gpl.analysis")

MODE_LABELS = {"strict": N_("STRICT (original portfolio)"),
               "common_universe": N_("COMMON-UNIVERSE (holdings with full history only)"),
               "available_history": N_("AVAILABLE-HISTORY (shorter sample, all holdings)"),
               "reconstructed": N_("RECONSTRUCTED (short histories completed with a factor model)")}


@dataclass
class HorizonResult:
    horizon: int
    mode: str
    status: str                       # COMPLETE | INCOMPLETE | INSUFFICIENT_OBSERVATIONS | NO_DATA | ERROR
    label: str
    nominal_start: pd.Timestamp | None = None
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    n_obs: int = 0
    actual_years: float = 0.0
    universe: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    market_budgets: dict[str, float] = field(default_factory=dict)
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)
    weights_user: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    returns: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    benchmark_returns: pd.Series | None = None
    mu: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    cov: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr: pd.DataFrame = field(default_factory=pd.DataFrame)
    cov_info: dict = field(default_factory=dict)
    calendar: dict = field(default_factory=dict)
    cov_check: dict = field(default_factory=dict)
    user_stats: dict = field(default_factory=dict)
    asset_stats: pd.DataFrame = field(default_factory=pd.DataFrame)
    risk_decomp: pd.DataFrame = field(default_factory=pd.DataFrame)
    concentration: dict = field(default_factory=dict)
    optimized: dict[str, OptimizationResult] = field(default_factory=dict)
    frontier: FrontierResult | None = None
    constraints: ConstraintSet | None = None
    reconstructed: dict = field(default_factory=dict)   # ticker -> backfill.Reconstruction
    too_short: dict = field(default_factory=dict)       # ticker -> real observations (below the minimum)

    @property
    def analyzable(self) -> bool:
        return self.status == "COMPLETE"


@dataclass
class AnalysisBundle:
    created_at: str
    data_cutoff: str | None
    config: dict
    conversion_report: pd.DataFrame
    calendar_report: dict
    prices_base: pd.DataFrame
    horizons: dict[int, HorizonResult]
    metadata: pd.DataFrame
    data_version: str
    warnings: list[str] = field(default_factory=list)
    benchmark_prices: pd.Series | None = None
    index_prices: dict = field(default_factory=dict)
    index_names: dict = field(default_factory=dict)

    def comparison_table(self) -> pd.DataFrame:
        rows = []
        for h, r in self.horizons.items():
            row = {"horizon": years(h, short=True), "horizon_years": round(float(h), 2) if is_custom(h) else h,
                   "status": r.status, "mode": r.label, "start": r.start, "end": r.end,
                   "n_obs": r.n_obs, "actual_years": round(r.actual_years, 2), "n_assets": len(r.universe)}
            if r.analyzable:
                s = r.user_stats
                row.update({"user_annual_return": s["annual_arithmetic_return"], "user_cagr":
                            s["annual_geometric_return_cagr"], "user_volatility": s["annual_volatility"],
                            "user_sharpe": s["sharpe_annual"], "user_max_drawdown": s["max_drawdown"]})
                for key in ("min_variance", "max_sharpe"):
                    o = r.optimized.get(key)
                    if o is not None and o.ok:
                        row[f"{key}_return"] = o.expected_return
                        row[f"{key}_volatility"] = o.volatility
                        row[f"{key}_sharpe"] = o.sharpe
            rows.append(row)
        return pd.DataFrame(rows)


def _renormalized_budgets(portfolio: Portfolio, keep: list[str]) -> tuple[dict[str, float], pd.Series, list[str]]:
    notes: list[str] = []
    budgets: dict[str, float] = {}
    within: dict[str, float] = {}
    for m, a in portfolio.market_allocations.items():
        if a <= 0:
            continue
        members = [h for h in portfolio.holdings if h.market_id == m and h.ticker in keep]
        if not members:
            notes.append(t("Market {market} removed (no holding with sufficient history).", market=m))
            continue
        s = sum(h.within_pct for h in members)
        budgets[m] = a / 100.0
        for h in members:
            within[h.ticker] = h.within_pct / s if s > 0 else 1 / len(members)
    tot = sum(budgets.values())
    if tot > 0 and abs(tot - 1) > 1e-12:
        notes.append(t("Remaining market budgets rescaled by 1/{value}.", value=f"{tot:.4f}"))
    budgets = {m: b / tot for m, b in budgets.items()} if tot > 0 else {}
    mkt = {h.ticker: h.market_id for h in portfolio.holdings}
    w = pd.Series({t: budgets[mkt[t]] * within[t] for t in within})
    return budgets, w, notes


def index_returns_on(dates: pd.DatetimeIndex, index_prices: dict[str, pd.Series] | None) -> dict[str, pd.Series]:
    """Market-index returns on ``dates`` (factors for reconstructed histories). The index level is carried over
    at most 5 local holidays (the market was closed, so the index did not move); an index that does not cover
    every date is not used."""
    out = {}
    for m, ser in (index_prices or {}).items():
        sp = ser.dropna()
        if sp.empty:
            continue
        sp = sp.reindex(sp.index.union(dates)).ffill(limit=5).reindex(dates)
        if sp.notna().all():
            out[m] = simple_returns(sp)
    return out


def load_index_prices(db: Database, portfolio: Portfolio, settings: AppSettings,
                      markets: dict[str, MarketConfig]) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Stored market indices (base currency) of the portfolio's markets, keyed by market id."""
    idx = {m: markets[m].benchmark for m in portfolio.market_allocations if m in markets and markets[m].benchmark}
    prices, names = {}, {}
    if idx:
        ip, _ = load_base_currency_prices(db, sorted(set(idx.values())), settings.base_currency,
                                          settings.fx_max_staleness_days)
        for m, tk in idx.items():
            if tk in ip.columns and ip[tk].notna().any():
                prices[m], names[m] = ip[tk], tk
    return prices, names


def _reconstructed_window(res: HorizonResult, prices_base: pd.DataFrame, portfolio: Portfolio,
                          settings: AppSettings, short: list[str], start: pd.Timestamp, w_user: pd.Series,
                          index_prices: dict[str, pd.Series] | None, index_names: dict[str, str] | None
                          ) -> tuple[pd.DataFrame, pd.DataFrame, dict] | None:
    """Prices (real only) and returns (short histories completed) for the reconstructed mode."""
    tickers = portfolio.tickers
    long = [tk for tk in tickers if tk not in short]
    if not long:
        res.status = "INCOMPLETE"
        res.excluded = short
        res.warnings.append(t("RECONSTRUCTED: no holding has the full {period} of history, so there is nothing to "
                              "reconstruct the short histories from.", h=res.horizon))
        return None
    first = {tk: prices_base[tk].first_valid_index() for tk in short}
    window = prices_base[tickers].loc[prices_base.index >= start].dropna(how="all")
    keep = window[long].notna().all(axis=1)
    for tk in short:
        keep &= (window.index < first[tk]) | window[tk].notna()
    px = window.loc[keep]
    cal = {"union_dates": len(window), "common_dates": len(px), "dropped_dates": len(window) - len(px),
           "dropped_pct": 100.0 * (len(window) - len(px)) / len(window) if len(window) else 0.0}
    prior = prices_base[long].dropna(how="any")
    prior = prior.loc[prior.index < px.index.min()] if not px.empty else prior.iloc[0:0]
    if not prior.empty and (px.index.min() - prior.index.max()).days <= 7:
        px = pd.concat([prices_base[tickers].loc[[prior.index.max()]], px])
    if settings.return_frequency == "weekly":
        px = px.resample("W-FRI").last().dropna(subset=long)
    rets = simple_returns(px)
    min_real = settings.backfill_min_obs if settings.return_frequency == "daily" else \
        max(8, int(np.ceil(settings.backfill_min_obs / 5)))
    few = {tk: int(rets[tk].notna().sum()) for tk in short if rets[tk].notna().sum() < min_real}
    if few:
        res.status = "INCOMPLETE"
        res.excluded = list(few)
        res.too_short = {tk: (n, min_real) for tk, n in few.items()}
        res.warnings.append(t("RECONSTRUCTED: {tickers} has too few real observations to estimate its relationship "
                              "with the other holdings (minimum {n}).", tickers=", ".join(few), n=min_real))
        return None
    mkt = {h_.ticker: h_.market_id for h_ in portfolio.holdings}
    idx_r = index_returns_on(px.index, index_prices)
    rf = (1 + settings.risk_free_annual) ** (1 / settings.periods_per_year) - 1
    full, info = reconstruct_frame(rets, short, long, mkt, w_user, rf, settings.periods_per_year, idx_r,
                                   index_names, salt=f"{res.horizon}")
    res.reconstructed = info
    for tk, rec in info.items():
        res.warnings.append(t("RECONSTRUCTED: {ticker} has real data since {first} ({n} observations, {real}% of this "
                              "horizon). The earlier {share}% was estimated from {factors} (R² {r2}), with its "
                              "real residual risk and no abnormal return.", ticker=tk,
                              first=f"{rec.first_real:%Y-%m-%d}" if rec.first_real is not None else "–",
                              n=rec.n_real, real=f"{100 * (1 - rec.share_filled):.0f}",
                              share=f"{100 * rec.share_filled:.0f}", factors=", ".join(rec.factors),
                              r2=f"{rec.r2:.2f}"))
    return px, full, cal


def analyze_horizon(h: int, prices_base: pd.DataFrame, portfolio: Portfolio, settings: AppSettings,
                    meta: pd.DataFrame, benchmark_prices: pd.Series | None,
                    index_prices: dict[str, pd.Series] | None = None,
                    index_names: dict[str, str] | None = None) -> HorizonResult:
    mode = settings.analysis_mode
    tickers = portfolio.tickers
    res = HorizonResult(h, mode, "NO_DATA", t(MODE_LABELS.get(mode, mode)))
    have = [t for t in tickers if t in prices_base.columns and prices_base[t].notna().any()]
    missing = [t for t in tickers if t not in have]
    if not have:
        res.warnings.append(t("No base-currency price history is available for any holding."))
        return res
    first = prices_base[have].apply(lambda s: s.first_valid_index())
    last = prices_base[have].apply(lambda s: s.last_valid_index())
    full_common, _ = common_calendar(prices_base[have])
    if is_custom(h):   # user-chosen window: [h.start, h.end], end moved back to the last common date
        alive = [tk for tk in have if first[tk] <= h.end]          # holdings already trading in the window
        fc = common_calendar(prices_base[alive])[0].loc[:h.end] if alive else pd.DataFrame()
        end = fc.index.max() if not fc.empty else None
        if end is None or pd.isna(end) or end <= h.start:
            res.warnings.append(t("No date on which every holding traded falls inside the chosen window."))
            return res
        nominal_start = h.start
        prices_base = prices_base.loc[:end]
        if (end - nominal_start).days < 365:
            res.warnings.append(t("Short window ({period}): annual figures (return, volatility, Sharpe) are "
                                  "extrapolated to a full year from few data; read them with caution.", h=h))
    else:
        end = full_common.index.max() if not full_common.empty else last.min()
        nominal_start = end - pd.DateOffset(years=h)
    res.nominal_start, res.end = nominal_start, end
    tol = pd.Timedelta(days=settings.coverage_tolerance_days)
    cov_rows = []
    for tk in tickers:
        f = first.get(tk) if tk in have else None
        ok = (f is not None) and (f <= nominal_start + tol)
        cov_rows.append({"ticker": tk, "first_obs": f, "last_obs": last.get(tk) if tk in have else None,
                         "covers_horizon": bool(ok),
                         "years_available": max((end - f).days / 365.25, 0.0) if f is not None else 0.0})
    res.coverage = pd.DataFrame(cov_rows).set_index("ticker")
    lacking = res.coverage.index[~res.coverage["covers_horizon"]].tolist()

    if mode == "common_universe":
        universe = [t for t in tickers if t not in lacking]
        res.excluded = lacking
        if not universe:
            res.status = "NO_DATA"
            res.warnings.append(t("No holding has {period} of history; common-universe analysis impossible.", h=h))
            return res
        budgets, w_user, notes = _renormalized_budgets(portfolio, universe)
        res.warnings += notes
        if lacking:
            res.warnings.append(t("COMMON-UNIVERSE: excluded {tickers} (insufficient history). This is NOT the "
                                  "original portfolio.", tickers=", ".join(lacking)))
        start = nominal_start
    elif mode == "available_history":
        universe = have
        res.excluded = missing
        budgets, w_user, notes = _renormalized_budgets(portfolio, universe)
        res.warnings += notes
        start = max(nominal_start, first[universe].max())
        if start > nominal_start + tol:
            res.warnings.append(t("AVAILABLE-HISTORY: sample starts {start} (latest listing among holdings), not "
                                  "{nominal}; the requested horizon of {period} is NOT fully covered.",
                                  start=start.date(), nominal=nominal_start.date(), h=h))
    elif mode == "reconstructed":
        universe = tickers
        budgets = {m: a / 100.0 for m, a in portfolio.market_allocations.items() if a > 0}
        w_user = global_weights(portfolio)
        start = nominal_start
        nodata = [tk for tk in lacking if tk not in have or not prices_base[tk].notna().any()]
        if nodata:
            res.status = "INCOMPLETE"
            res.excluded = nodata
            res.universe = universe
            res.warnings.append(t("INCOMPLETE: {tickers} has no usable price history, so it cannot be reconstructed.",
                                  tickers=", ".join(nodata)))
            return res
    else:  # strict
        universe = tickers
        budgets = {m: a / 100.0 for m, a in portfolio.market_allocations.items() if a > 0}
        w_user = global_weights(portfolio)
        start = nominal_start
        if lacking:
            res.status = "INCOMPLETE"
            res.excluded = lacking
            res.universe = universe
            res.warnings.append(t("INCOMPLETE: {tickers} lack(s) {period} of history. No statistics for {period} are "
                                  "reported for the original portfolio. Switch to the labelled common-universe or "
                                  "available-history mode to analyse alternatives.", tickers=", ".join(lacking), h=h))
            return res

    res.universe, res.market_budgets, res.weights_user = universe, budgets, w_user.reindex(universe)
    if mode == "reconstructed" and lacking:
        out = _reconstructed_window(res, prices_base, portfolio, settings, lacking, start, w_user, index_prices,
                                    index_names)
        if out is None:
            return res
        px, rets, cal = out
    else:
        if mode == "reconstructed":   # nothing to reconstruct in this window: it is the original portfolio
            res.label = t(MODE_LABELS["strict"])
        window = prices_base[universe].loc[prices_base.index >= start].dropna(how="all")
        px, cal = common_calendar(window)
        # include one observation before the start so the first return falls inside the window
        prior = prices_base[universe].dropna(how="any")
        prior = prior.loc[prior.index < px.index.min()] if not px.empty else prior.iloc[0:0]
        if not prior.empty and (px.index.min() - prior.index.max()).days <= 7:
            px = pd.concat([prior.iloc[[-1]], px])
        px = to_frequency(px, settings.return_frequency)
        rets = simple_returns(px)
    res.prices, res.returns = px, rets
    res.n_obs = len(rets)
    if res.n_obs:
        res.start, res.end = rets.index.min(), rets.index.max()
        res.actual_years = (res.end - px.index.min()).days / 365.25
    res.warnings.append(t("Common calendar in this window keeps {kept} of {total} dates on which at least one "
                          "holding traded ({pct}% dropped because some market was closed or had a provider gap; no "
                          "prices were filled). Returns spanning a dropped date are multi-day returns.",
                          kept=cal["common_dates"], total=cal["union_dates"], pct=f"{cal['dropped_pct']:.1f}"))
    res.calendar = cal
    extreme = rets.abs() > (0.4 if settings.return_frequency == "daily" else 0.5)
    if res.n_obs and extreme.to_numpy().any():
        hits = [f"{tk} {d:%Y-%m-%d} ({rets.at[d, tk]:+.0%})" for d, row in extreme.iterrows() for tk in row.index[row]]
        res.warnings.append(t("Extreme period returns remain in the sample: {items}. They usually mean an unadjusted "
                              "split or a provider error; see Historical Database, Corporate actions and repairs.",
                              items=", ".join(hits[:6]) + (" …" if len(hits) > 6 else "")))
    if res.n_obs < max(settings.min_observations, 2):
        res.status = "INSUFFICIENT_OBSERVATIONS"
        res.warnings.append(t("Only {n} observations (< minimum {minimum}).", n=res.n_obs,
                              minimum=settings.min_observations))
        return res
    try:
        n = settings.periods_per_year
        rf = rf_markowitz(settings.risk_free_annual, n)
        res.mu = estimate_mu(rets, settings.mu_estimator, n, settings.ewma_lambda, settings.user_expected_returns)
        res.cov, res.cov_info = estimate_cov(rets, settings.cov_estimator, n, settings.ewma_lambda)
        res.cov_check = check_covariance(res.cov, res.n_obs)
        res.warnings += res.cov_check["warnings"]
        res.corr = cov_to_corr(res.cov)
        port_r = rets @ res.weights_user.reindex(rets.columns).values
        res.portfolio_returns = pd.Series(port_r, index=rets.index, name="user_portfolio")
        if benchmark_prices is not None and not benchmark_prices.dropna().empty:
            b = benchmark_prices.dropna()
            if settings.return_frequency == "weekly":
                b = b.resample("W-FRI").last()
            b = b.reindex(px.index)  # benchmark dates outside the common calendar are not used; no filling
            res.benchmark_returns = simple_returns(b).dropna()
        res.user_stats = portfolio_statistics(res.portfolio_returns, settings.risk_free_annual, n,
                                              res.benchmark_returns)
        res.asset_stats = asset_statistics(rets, res.weights_user, res.cov, res.mu, settings.risk_free_annual, n,
                                           meta, res.benchmark_returns)
        res.risk_decomp = risk_decomposition(res.weights_user, res.cov)
        mkt = {h_.ticker: h_.market_id for h_ in portfolio.holdings}
        ccy = {t: major_currency((meta.loc[t, "currency"] if t in meta.index else "") or "")[0] for t in universe}
        res.concentration = concentration(res.weights_user, mkt, ccy, res.cov)
        if not res.cov_check["psd"]:
            res.status = "ERROR"
            res.warnings.append(t("Optimisation skipped: covariance matrix is not positive semidefinite. Choose "
                                  "Ledoit-Wolf shrinkage; the matrix is NOT silently repaired."))
            return res
        cs = ConstraintSet.build(universe, mkt, budgets, settings.constraint_mode, settings.long_only,
                                 settings.min_weight, settings.max_weight)
        res.constraints = cs
        res.optimized = run_all(res.mu, res.cov, cs, rf, res.weights_user, rets, settings.max_risk_vertex_limit)
        res.frontier = build_frontier(res.mu, res.cov, cs, rf, settings.frontier_points,
                                      tangency=res.optimized.get("max_sharpe"), gmv=res.optimized.get("min_variance"))
        res.warnings += res.frontier.warnings
        res.status = "COMPLETE"
    except Exception as exc:
        logger.exception("event=horizon_failed horizon=%s", h)
        res.status = "ERROR"
        res.warnings.append(t("Analysis failed: {error}", error=f"{type(exc).__name__}: {exc}"))
    return res


def run_analysis(db: Database, portfolio: Portfolio, settings: AppSettings,
                 markets: dict[str, MarketConfig], horizons: tuple[int, ...] | list[int] = (1, 3, 5, 10, 15)
                 ) -> AnalysisBundle:
    tickers = portfolio.tickers
    bench = settings.benchmark_ticker.strip() if settings.benchmark_ticker else ""
    all_t = tickers + ([bench] if bench and bench not in tickers else [])
    prices_base, conv = load_base_currency_prices(db, all_t, settings.base_currency, settings.fx_max_staleness_days)
    bench_series = prices_base[bench] if bench and bench in prices_base.columns else None
    prices_port = prices_base[[t for t in tickers if t in prices_base.columns]]
    meta = db.list_securities()
    meta = meta.set_index("ticker") if not meta.empty else pd.DataFrame()
    _, cal = common_calendar(prices_port) if not prices_port.empty else (None, {})
    warnings: list[str] = []
    if bench and bench_series is None:
        warnings.append(t("Benchmark {ticker} has no stored base-currency history; benchmark statistics omitted.",
                          ticker=bench))
    index_prices, index_names = ({}, {}) if settings.analysis_mode != "reconstructed" else \
        load_index_prices(db, portfolio, settings, markets)
    results = {h: analyze_horizon(h, prices_port, portfolio, settings, meta, bench_series, index_prices, index_names)
               for h in horizons}
    cutoff = prices_port.dropna(how="any").index.max() if not prices_port.empty else None
    return AnalysisBundle(
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        data_cutoff=cutoff.strftime("%Y-%m-%d") if cutoff is not None and not pd.isna(cutoff) else None,
        config={"settings": settings.to_dict(), "portfolio": portfolio.to_dict()},
        conversion_report=conv, calendar_report=cal, prices_base=prices_port, horizons=results, metadata=meta,
        data_version=db.data_version(), warnings=warnings, benchmark_prices=bench_series,
        index_prices=index_prices, index_names=index_names)


def incomplete_reasons(r: HorizonResult, bundle: AnalysisBundle | None, tickers: list[str],
                       min_observations: int = 0) -> list[dict]:
    """Why a horizon has no statistics, one entry per security at fault.

    kind = no_prices (nothing downloaded), no_fx (prices exist, no exchange rate to the base currency),
    short (history starts after the horizon start), too_short (reconstructed mode: fewer real observations
    than the minimum needed to reconstruct) or sparse (too few common trading dates)."""
    if r.status == "COMPLETE" and not r.excluded:
        return []
    conv = (bundle.conversion_report.set_index("ticker") if bundle is not None and
            not bundle.conversion_report.empty else pd.DataFrame())
    out: list[dict] = []
    suspects = list(r.excluded) if r.excluded else (list(tickers) if r.status == "NO_DATA" else [])
    for tk in suspects:
        c = conv.loc[tk] if tk in conv.index else None
        n_local = int(c["n_local"]) if c is not None else 0
        n_conv = int(c["n_converted"]) if c is not None else 0
        pair = str(c["fx_pair"]) if c is not None else ""
        if tk in r.too_short:
            n_real, needed = r.too_short[tk]
            out.append({"kind": "too_short", "ticker": tk, "n": n_real, "needed": needed,
                        "first": r.coverage.at[tk, "first_obs"] if tk in r.coverage.index else None})
        elif n_local == 0:
            out.append({"kind": "no_prices", "ticker": tk})
        elif n_conv == 0:
            out.append({"kind": "no_fx", "ticker": tk, "pair": pair})
        else:
            first = r.coverage.at[tk, "first_obs"] if tk in r.coverage.index else None
            years = float(r.coverage.at[tk, "years_available"]) if tk in r.coverage.index else 0.0
            dropped = int(c["n_dropped_no_fx"]) if c is not None else 0
            out.append({"kind": "short", "ticker": tk, "first": first, "years": years,
                        "needed": r.nominal_start, "fx_dropped": dropped if dropped > 0.2 * n_local else 0,
                        "pair": pair})
    if r.status == "INSUFFICIENT_OBSERVATIONS" and is_custom(r.horizon) and r.calendar.get("dropped_pct", 0) < 50:
        return out + [{"kind": "short_window", "ticker": "", "n": r.n_obs, "needed": min_observations}]
    if r.status == "INSUFFICIENT_OBSERVATIONS" and bundle is not None and r.nominal_start is not None:
        win = bundle.prices_base.loc[bundle.prices_base.index >= r.nominal_start]
        counts = win.notna().sum().sort_values()
        for tk, n in counts.items():
            if n < max(min_observations, 2) * 1.5:
                out.append({"kind": "sparse", "ticker": tk, "n": int(n), "n_common": r.n_obs})
        if not any(o["kind"] == "sparse" for o in out) and len(counts):
            out.append({"kind": "sparse", "ticker": counts.index[0], "n": int(counts.iloc[0]), "n_common": r.n_obs})
    return out


def analyze_custom(bundle: AnalysisBundle, portfolio: Portfolio, settings: AppSettings, h) -> HorizonResult:
    """One more horizon (normally the user's custom window) from the data already loaded in ``bundle``."""
    return analyze_horizon(h, bundle.prices_base, portfolio, settings, bundle.metadata, bundle.benchmark_prices,
                           bundle.index_prices, bundle.index_names)
