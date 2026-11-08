"""Predictive backtesting lab: train a model on one period, test it (and its forecasts) on a later one.

Timeline
--------
    |---- training window [train_start, train_end] ----|---- test window [test_start, test_end] ----|
The model only sees returns dated on or before ``train_end``.  At the close of ``train_end`` it chooses the
weights of every strategy and produces a FORECAST (fan of possible paths) for the test window.  The test
window then replays what actually happened, with costs, rebalancing and optional monthly contributions.

Modes
-----
* static        weights are estimated once on the training window and kept as targets; at every rebalance
                date the portfolio is brought back to them (``rebalance='none'`` lets them drift: buy and hold).
* walk_forward  the model keeps learning: at every rebalance date it is re-estimated with the data available
                up to the day before (expanding window from ``train_start``, or the last ``rolling_obs``
                observations) and re-optimized.

Money accounting (base currency)
-------------------------------
Holdings h_i (money).  Each day h_i ← h_i (1 + r_i,t).  On a rebalance date the targets are W·w*, the traded
value is Σ|W w*_i − h_i| and the cost is traded × (commission + slippage) plus an FX-conversion cost on the
traded value of foreign-currency securities.  A contribution C is invested at the previous close on the first
trading day of each month (after the first), split by the target weights (its cost is charged too).
Time-weighted return r_t = (W_t − flow_t) / W_{t−1} − 1 (flows excluded); money-weighted return = XIRR of the
cash flows.

Forecast
--------
For each strategy's training weights w: 'normal' draws i.i.d. per-period returns N(w'μ/n, w'Σw/n);
'bootstrap' resamples the training-window portfolio returns in circular blocks (keeps fat tails and short-range
dependence).  Paths use the SAME contribution schedule as the realized test, constant weights and no costs.
The realized result is then placed in that distribution (percentile), and the forecast's daily 95% VaR is
checked against the realized days (breaches, Kupiec proportion-of-failures test).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sps
from scipy.optimize import brentq

from .i18n import N_, t
from .optimization import (ConstraintSet, equal_weight, inverse_volatility, maximum_diversification,
                           maximum_return, maximum_sharpe, minimum_cvar, minimum_variance, risk_parity,
                           target_volatility)
from .statistics import estimate_cov, estimate_mu, max_drawdown, rf_markowitz, rf_per_period

STRATEGIES = {
    "user": N_("Your portfolio (fixed weights)"),
    "equal_weight": N_("Equal weight"),
    "min_variance": N_("Minimum variance"),
    "max_sharpe": N_("Maximum Sharpe"),
    "max_diversification": N_("Max diversification"),
    "risk_parity": N_("Risk parity"),
    "inverse_vol": N_("Inverse volatility"),
    "min_cvar": N_("Minimum CVaR 95%"),
    "target_vol": N_("Target volatility"),
    "max_return": N_("Maximum return"),
}
NEEDS_MODEL = {"min_variance", "max_sharpe", "max_diversification", "risk_parity", "inverse_vol", "min_cvar",
               "target_vol", "max_return"}
REBALANCE_RULES = {"monthly": "ME", "quarterly": "QE", "semiannual": "6ME", "annual": "YE"}
PCTS = (5, 25, 50, 75, 95)


@dataclass
class LabConfig:
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    strategies: tuple[str, ...] = ("user", "equal_weight", "min_variance", "max_sharpe", "risk_parity")
    mode: str = "static"                    # static | walk_forward
    window: str = "expanding"               # expanding | rolling (walk_forward only)
    rolling_obs: int = 252
    rebalance: str = "quarterly"            # none | monthly | quarterly | semiannual | annual
    mu_estimator: str = "arithmetic"
    cov_estimator: str = "ledoit_wolf"
    ewma_lambda: float = 0.97
    capital: float = 100_000.0
    contribution: float = 0.0               # per month, base currency
    cost_bps: float = 10.0
    slippage_bps: float = 5.0
    fx_cost_bps: float = 20.0               # extra cost on traded value of foreign-currency securities
    target_vol: float = 0.15
    rf_annual: float = 0.065
    periods_per_year: int = 252
    projection: str = "bootstrap"           # bootstrap | normal
    n_paths: int = 2000
    block: int = 21
    seed: int = 7


@dataclass
class StrategyRun:
    key: str
    label: str
    ok: bool
    train_weights: pd.Series
    value: pd.Series                        # portfolio value after each test period
    invested: pd.Series                     # capital + contributions to date
    twr: pd.Series                          # time-weighted period returns (net of costs)
    weights_path: pd.DataFrame              # end-of-day weights (sampled)
    decisions: pd.DataFrame                 # target weights at each decision date
    contrib_money: pd.Series                # money made by each security in the test window
    turnover: float
    costs: float
    train_value: pd.Series                  # what the training weights did DURING training (in-sample)
    forecast: dict = field(default_factory=dict)
    realized: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class LabResult:
    config: LabConfig
    runs: dict[str, StrategyRun]
    train_returns: pd.DataFrame
    test_returns: pd.DataFrame
    train_mu: pd.Series
    train_cov: pd.DataFrame
    flows: pd.Series                        # contribution on each test date (0 = none)
    benchmark: dict | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
def strategy_weights(key: str, est: pd.DataFrame, cs: ConstraintSet, user_w: np.ndarray, cfg: LabConfig
                     ) -> tuple[np.ndarray | None, str]:
    if key == "user":
        return user_w.copy(), ""
    rf = rf_markowitz(cfg.rf_annual, cfg.periods_per_year)
    mu = estimate_mu(est, cfg.mu_estimator, cfg.periods_per_year, cfg.ewma_lambda).reindex(cs.tickers).values
    S = estimate_cov(est, cfg.cov_estimator, cfg.periods_per_year, cfg.ewma_lambda)[0] \
        .reindex(index=cs.tickers, columns=cs.tickers).values
    if key == "equal_weight":
        res = equal_weight(mu, S, cs, rf)
    elif key == "min_variance":
        res = minimum_variance(mu, S, cs, rf)
    elif key == "max_sharpe":
        res = maximum_sharpe(mu, S, cs, rf, cross_check=False)
    elif key == "max_diversification":
        res = maximum_diversification(mu, S, cs, rf)
    elif key == "risk_parity":
        res = risk_parity(mu, S, cs, rf)
    elif key == "inverse_vol":
        res = inverse_volatility(mu, S, cs, rf)
    elif key == "min_cvar":
        res = minimum_cvar(est.reindex(columns=cs.tickers).values, mu, S, cs, rf)
    elif key == "target_vol":
        gmv = minimum_variance(mu, S, cs, rf)
        res = target_volatility(mu, S, cs, rf, max(cfg.target_vol, gmv.volatility if gmv.ok else 0.0),
                                gmv.volatility if gmv.ok else None)
    elif key == "max_return":
        res = maximum_return(mu, S, cs, rf)
    else:
        raise ValueError(key)
    if not res.ok:
        return None, str(res.status)
    return res.weights.reindex(cs.tickers).values, ""


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def decision_dates(test_index: pd.DatetimeIndex, rebalance: str) -> list[pd.Timestamp]:
    """First test day plus the first trading day after each period end."""
    out = [test_index[0]]
    if rebalance in REBALANCE_RULES:
        ends = test_index.to_series().resample(REBALANCE_RULES[rebalance]).last().dropna()
        for e in ends.array:
            pos = test_index.searchsorted(pd.Timestamp(e), side="right")
            if 0 < pos < len(test_index):
                out.append(test_index[pos])
    return sorted(set(out))


def contribution_flows(test_index: pd.DatetimeIndex, amount: float) -> pd.Series:
    """Amount on the first trading day of each month after the first test month."""
    flows = pd.Series(0.0, index=test_index)
    if amount == 0 or len(test_index) == 0:
        return flows
    months = test_index.to_period("M")
    first_days = test_index[np.r_[False, months[1:] != months[:-1]]]
    flows.loc[first_days] = amount
    return flows


# ---------------------------------------------------------------------------
# Simulation of one strategy in the test window
# ---------------------------------------------------------------------------
def _simulate(key: str, R: pd.DataFrame, cs: ConstraintSet, w0: np.ndarray, decisions: list[pd.Timestamp],
              flows: pd.Series, cfg: LabConfig, foreign: np.ndarray, reestimate) -> dict:
    n = R.shape[1]
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 1e4
    fx_rate = cfg.fx_cost_bps / 1e4
    h = np.zeros(n)
    W_prev = 0.0
    target = w0.copy()
    vals, inv, twr, wts, contrib = [], [], [], [], np.zeros(n)
    turnover = costs = 0.0
    invested = 0.0
    dec_rows = []
    dset = set(decisions)
    notes: list[str] = []
    for k, d in enumerate(R.index):
        r = R.iloc[k].to_numpy(dtype=float)
        flow = cfg.capital if k == 0 else float(flows.iloc[k])
        if k > 0 and d in dset and cfg.mode == "walk_forward" and key != "user":
            new, why = reestimate(d)
            if new is None:
                notes.append(t("{date}: re-estimation failed ({why}); previous targets kept.", date=f"{d:%Y-%m-%d}",
                               why=why))
            else:
                target = new
        rebalance_now = (k == 0) or (d in dset and cfg.rebalance != "none")
        W = h.sum() + flow
        invested += flow
        if rebalance_now:
            desired = W * target
            traded = np.abs(desired - h)
            if k == 0:
                traded = np.abs(desired)
            c = float(traded.sum() * cost_rate + (traded * foreign).sum() * fx_rate)
            turnover += float(traded.sum()) / max(W, 1e-12) if k > 0 else 0.0
            costs += c
            W -= c
            h = W * target
            dec_rows.append(pd.Series(target, index=R.columns, name=d))
        elif flow > 0:
            buy = flow * target
            c = float(buy.sum() * cost_rate + (buy * foreign).sum() * fx_rate)
            costs += c
            h = h + buy * (1 - c / max(flow, 1e-12))
        gain = h * r
        contrib += gain
        h = h + gain
        W_end = float(h.sum())
        if not np.isfinite(W_end) or W_end <= 0.0:
            raise RuntimeError(
                f"Portfolio NAV became non-positive on {d.date()}; leveraged/short margin calls "
                "and liquidation are not modelled."
            )
        # time-weighted return: the day's flow is excluded, the day's costs are included
        base = W_prev + flow
        twr.append(W_end / base - 1 if base > 0 else 0.0)
        vals.append(W_end)
        inv.append(invested)
        wts.append(h / W_end if W_end > 0 else np.zeros(n))
        W_prev = W_end
    idx = R.index
    return {"value": pd.Series(vals, index=idx), "invested": pd.Series(inv, index=idx),
            "twr": pd.Series(twr, index=idx), "weights": pd.DataFrame(wts, index=idx, columns=R.columns),
            "decisions": pd.DataFrame(dec_rows), "contrib": pd.Series(contrib, index=R.columns),
            "turnover": turnover, "costs": costs, "notes": notes}


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------
def forecast_paths(train_port_r: np.ndarray, mu_p: float, sd_p: float, n_steps: int, capital: float,
                   flows: np.ndarray, method: str, n_paths: int, block: int, seed: int) -> np.ndarray:
    """Simulated portfolio values (n_paths x n_steps) with the same contribution schedule."""
    rng = np.random.default_rng(seed)
    if method == "normal" or len(train_port_r) < max(block * 2, 30):
        R = rng.normal(mu_p, sd_p, size=(n_paths, n_steps))
    else:
        T = len(train_port_r)
        k = int(np.ceil(n_steps / block))
        starts = rng.integers(0, T, size=(n_paths, k))
        idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_paths, -1)[:, :n_steps] % T
        R = train_port_r[idx]
    W = np.empty((n_paths, n_steps))
    cur = np.full(n_paths, capital, dtype=float)
    for s in range(n_steps):
        if s > 0:
            cur = cur + flows[s]
        cur = cur * (1 + R[:, s])
        W[:, s] = cur
    return W


def kupiec(breaches: int, n: int, p: float = 0.05) -> float:
    """p-value of Kupiec's proportion-of-failures test (H0: breach rate = p)."""
    if n == 0:
        return float("nan")
    x = breaches
    phat = x / n
    ll0 = (n - x) * np.log(1 - p) + (x * np.log(p) if x > 0 else 0.0)
    ll1 = ((n - x) * np.log(1 - phat) if x < n else 0.0) + (x * np.log(phat) if x > 0 else 0.0)
    lr = -2 * (ll0 - ll1)
    return float(1 - sps.chi2.cdf(max(lr, 0.0), 1))


def xirr(dates: list[pd.Timestamp], amounts: list[float]) -> float:
    """Annual money-weighted return (amounts: negative = money in, positive = money out)."""
    t0 = dates[0]
    yrs = np.array([(d - t0).days / 365.25 for d in dates])
    a = np.array(amounts, dtype=float)

    def npv(r):
        return float(np.sum(a / (1 + r) ** yrs))
    try:
        return float(brentq(npv, -0.9999, 100.0, maxiter=500))
    except (ValueError, RuntimeError):
        return float("nan")


def summarize(run: dict, R_index: pd.DatetimeIndex, flows: pd.Series, cfg: LabConfig,
             period_start: pd.Timestamp | None = None) -> dict:
    v, twr = run["value"], run["twr"]
    n = cfg.periods_per_year
    T = len(twr)
    start_date = (pd.Timestamp(period_start) if period_start is not None else
                  R_index[0] - (R_index[1] - R_index[0]) if len(R_index) > 1 else
                  R_index[0] - pd.Timedelta(days=1))
    years = max((R_index[-1] - start_date).days / 365.25, 1 / 365.25)
    growth = float(np.prod(1 + twr.values))
    sd = float(twr.std(ddof=1)) if T > 1 else float("nan")
    rf_d = rf_per_period(cfg.rf_annual, n)
    mdd = max_drawdown(twr)[0] if T > 1 else float("nan")
    flow_dates = [start_date] + [d for d, f in flows.items() if f > 0 and d != R_index[0]]
    flow_amts = [-cfg.capital] + [-float(flows[d]) for d in flow_dates[1:]]
    irr = xirr(flow_dates + [R_index[-1]], flow_amts + [float(v.iloc[-1])])
    return {"final_value": float(v.iloc[-1]), "invested": float(run["invested"].iloc[-1]),
            "gain": float(v.iloc[-1] - run["invested"].iloc[-1]),
            "twr_total": growth - 1, "twr_annual": growth ** (1 / years) - 1 if years >= 0.25 else growth - 1,
            "volatility": sd * np.sqrt(n), "sharpe": (float(twr.mean()) - rf_d) / sd * np.sqrt(n) if sd > 0 else np.nan,
            "max_drawdown": mdd, "irr": irr, "turnover": run["turnover"], "costs": run["costs"],
            "best_day": float(twr.max()), "worst_day": float(twr.min()), "n_days": T, "years": years}


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def run_lab(prices: pd.DataFrame, user_w: pd.Series, cs: ConstraintSet, cfg: LabConfig,
            foreign: dict[str, bool] | None = None, benchmark_prices: pd.Series | None = None) -> LabResult:
    if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.has_duplicates:
        raise ValueError("Backtest prices must have a unique DatetimeIndex.")
    if cs.n == 0 or len(set(cs.tickers)) != cs.n:
        raise ValueError("The backtest constraint universe must contain unique securities.")
    missing_tickers = [tk for tk in cs.tickers if tk not in prices.columns]
    if missing_tickers:
        raise ValueError(f"Price history is missing securities: {', '.join(missing_tickers)}")
    if cs.feasibility_problems():
        raise ValueError("Backtest constraints are infeasible: " + " ".join(cs.feasibility_problems()))
    if cfg.mode not in ("static", "walk_forward") or cfg.window not in ("expanding", "rolling"):
        raise ValueError("Unsupported backtest mode or estimation window.")
    if cfg.rebalance not in ("none", *REBALANCE_RULES):
        raise ValueError("Unsupported backtest rebalance frequency.")
    if cfg.projection not in ("normal", "bootstrap"):
        raise ValueError("Projection must be 'normal' or 'bootstrap'.")
    if not cfg.strategies or len(set(cfg.strategies)) != len(cfg.strategies) or set(cfg.strategies) - set(STRATEGIES):
        raise ValueError("Backtest strategies must be a non-empty, unique subset of the supported strategies.")
    if cfg.train_start >= cfg.train_end or cfg.test_start <= cfg.train_end or cfg.test_start > cfg.test_end:
        raise ValueError("Backtest windows must satisfy train_start < train_end < test_start <= test_end.")
    integer_settings = (cfg.periods_per_year, cfg.rolling_obs, cfg.n_paths, cfg.block)
    if any(not isinstance(v, (int, np.integer)) or isinstance(v, bool) for v in integer_settings):
        raise ValueError("Periods per year, rolling observations, path count, and block length must be integers.")
    if cfg.periods_per_year <= 0 or cfg.rolling_obs < 2 or cfg.n_paths < 1 or cfg.block < 1:
        raise ValueError("Periods per year and path count must be positive; rolling observations >= 2 and block >= 1.")
    costs = np.asarray([cfg.cost_bps, cfg.slippage_bps, cfg.fx_cost_bps], dtype=float)
    if not np.isfinite(costs).all() or np.any(costs < 0):
        raise ValueError("Transaction, slippage, and FX costs must be finite and non-negative.")
    if not np.isfinite(cfg.capital) or cfg.capital <= 0 or not np.isfinite(cfg.contribution) or cfg.contribution < 0:
        raise ValueError("Initial capital must be positive and monthly contributions must be finite and non-negative.")
    if not np.isfinite(cfg.rf_annual) or cfg.rf_annual <= -1.0:
        raise ValueError("The effective annual risk-free rate must be finite and greater than -100%.")
    if not np.isfinite(cfg.ewma_lambda) or not 0.0 < cfg.ewma_lambda <= 1.0:
        raise ValueError("EWMA lambda must lie in (0, 1].")
    if not np.isfinite(cfg.target_vol) or cfg.target_vol < 0:
        raise ValueError("Target volatility must be finite and non-negative.")
    px = prices.loc[:, cs.tickers].sort_index()
    if np.isinf(px.to_numpy(dtype=float)).any():
        raise ValueError("Price history contains infinite values.")
    px = px.dropna(how="any")
    if px.empty or (px <= 0).any().any():
        raise ValueError("Backtest requires positive prices on at least two complete dates.")
    rets = (px / px.shift(1) - 1).iloc[1:]
    tr = rets.loc[(rets.index >= pd.Timestamp(cfg.train_start)) & (rets.index <= pd.Timestamp(cfg.train_end))]
    te = rets.loc[(rets.index >= pd.Timestamp(cfg.test_start)) & (rets.index <= pd.Timestamp(cfg.test_end))
                  & (rets.index > pd.Timestamp(cfg.train_end))]
    notes: list[str] = []
    if len(tr) < 60:
        raise ValueError(t("The training window has only {n} return observations (minimum 60).", n=len(tr)))
    if len(te) < 5:
        raise ValueError(t("The test window has only {n} return observations (minimum 5).", n=len(te)))
    if not set(cs.tickers).issubset(set(user_w.index)):
        raise ValueError("User weights are missing one or more securities in the backtest universe.")
    uw = user_w.reindex(cs.tickers).to_numpy(dtype=float)
    if not np.isfinite(uw).all() or not cs.is_feasible(uw):
        raise ValueError("User weights must be finite and satisfy the configured portfolio constraints.")
    fvec = np.array([1.0 if (foreign or {}).get(tk) else 0.0 for tk in cs.tickers])
    flows = contribution_flows(te.index, cfg.contribution)
    decisions = decision_dates(te.index, cfg.rebalance)
    mu_tr = estimate_mu(tr, cfg.mu_estimator, cfg.periods_per_year, cfg.ewma_lambda)
    cov_tr = estimate_cov(tr, cfg.cov_estimator, cfg.periods_per_year, cfg.ewma_lambda)[0]
    n = cfg.periods_per_year
    runs: dict[str, StrategyRun] = {}
    test_period_start = px.index[px.index.get_loc(te.index[0]) - 1]
    for i, key in enumerate(cfg.strategies):
        label = t(STRATEGIES.get(key, key))
        w0, why = strategy_weights(key, tr, cs, uw, cfg)
        if w0 is None:
            runs[key] = StrategyRun(key, label, False, pd.Series(dtype=float), pd.Series(dtype=float),
                                    pd.Series(dtype=float), pd.Series(dtype=float), pd.DataFrame(), pd.DataFrame(),
                                    pd.Series(dtype=float), 0.0, 0.0, pd.Series(dtype=float),
                                    notes=[t("Training optimization failed: {why}", why=why)])
            continue

        def reestimate(d, key=key):
            hist = rets.loc[(rets.index >= pd.Timestamp(cfg.train_start)) & (rets.index < d)]
            if cfg.window == "rolling":
                hist = hist.iloc[-cfg.rolling_obs:]
            return strategy_weights(key, hist, cs, uw, cfg)
        sim = _simulate(key, te, cs, w0, decisions, flows, cfg, fvec, reestimate)
        realized = summarize(sim, te.index, flows, cfg, period_start=test_period_start)
        # forecast from the training window only
        port_tr = tr.values @ w0
        mu_p = float(mu_tr.reindex(cs.tickers).values @ w0) / n
        sd_p = float(np.sqrt(max(w0 @ cov_tr.reindex(index=cs.tickers, columns=cs.tickers).values @ w0, 0.0) / n))
        paths = forecast_paths(port_tr, mu_p, sd_p, len(te), cfg.capital, flows.values, cfg.projection,
                               cfg.n_paths, cfg.block, cfg.seed + i)
        finals = paths[:, -1]
        bands = pd.DataFrame(np.percentile(paths, PCTS, axis=0).T, index=te.index, columns=[f"p{p}" for p in PCTS])
        bands["mean"] = paths.mean(axis=0)
        if cfg.projection == "normal" or len(port_tr) < 2 * cfg.block:
            var95 = -(mu_p - 1.6448536 * sd_p)
        else:
            var95 = -float(np.quantile(port_tr, 0.05))
        breaches = int((sim["twr"].values < -var95).sum())
        invested_total = float(sim["invested"].iloc[-1])
        forecast = {"bands": bands, "median_final": float(np.median(finals)), "p5_final": float(np.percentile(finals, 5)),
                    "p95_final": float(np.percentile(finals, 95)),
                    "prob_loss": float(np.mean(finals < invested_total)),
                    "expected_annual_return": mu_p * n, "expected_volatility": sd_p * np.sqrt(n),
                    "var95_period": var95, "realized_percentile": float(np.mean(finals <= realized["final_value"])),
                    "breaches": breaches, "expected_breaches": 0.05 * len(te),
                    "kupiec_p": kupiec(breaches, len(te)),
                    "inside_90": bool(np.percentile(finals, 5) <= realized["final_value"] <= np.percentile(finals, 95))}
        train_value = cfg.capital * (1 + pd.Series(port_tr, index=tr.index)).cumprod()
        step = max(1, len(te) // 260)
        runs[key] = StrategyRun(key, label, True, pd.Series(w0, index=cs.tickers), sim["value"], sim["invested"],
                                sim["twr"], sim["weights"].iloc[::step], sim["decisions"], sim["contrib"],
                                sim["turnover"], sim["costs"], train_value, forecast, realized, sim["notes"])
    bench = None
    if benchmark_prices is not None and not benchmark_prices.dropna().empty:
        b = benchmark_prices.dropna().sort_index()
        br = (b / b.shift(1) - 1).reindex(te.index)
        # Missing benchmark observations are not zero returns. A zero-fill would
        # fabricate performance (and the next available observation would span
        # multiple sessions), so only report a benchmark on a complete test grid.
        if br.notna().all() and np.isfinite(br.to_numpy(dtype=float)).all() and (br >= -1.0).all():
            bvals, cur = [], 0.0
            for k, d in enumerate(te.index):
                cur = (cur + (cfg.capital if k == 0 else flows.iloc[k])) * (1 + br.iloc[k])
                bvals.append(cur)
            bench = {"value": pd.Series(bvals, index=te.index), "returns": br}
        else:
            notes.append(t("Benchmark omitted: its return history does not cover every test date; missing benchmark returns were not filled with zero."))
    return LabResult(cfg, runs, tr, te, mu_tr, cov_tr, flows, bench, notes)


# ---------------------------------------------------------------------------
# What-if scenarios
# ---------------------------------------------------------------------------
def replay(R: pd.DataFrame, w: np.ndarray, capital: float, flows: pd.Series | None = None) -> pd.Series:
    """Constant-weight (daily rebalanced) value path, no costs."""
    rp = R.values @ w
    out, cur = [], 0.0
    for k in range(len(rp)):
        cur = (cur + (capital if k == 0 else (flows.iloc[k] if flows is not None else 0.0))) * (1 + rp[k])
        out.append(cur)
    return pd.Series(out, index=R.index)


def entry_date_sensitivity(R: pd.DataFrame, weights: dict[str, np.ndarray], capital: float) -> pd.DataFrame:
    """Final value at the end of the test window if the capital had been invested on each month's first day."""
    months = R.index.to_period("M")
    starts = R.index[np.r_[True, months[1:] != months[:-1]]]
    rows = []
    for s in starts:
        sub = R.loc[R.index >= s]
        row = {"start": s}
        for k, w in weights.items():
            row[k] = float(capital * np.prod(1 + sub.values @ w))
        rows.append(row)
    return pd.DataFrame(rows).set_index("start")


def fx_shock_returns(R: pd.DataFrame, foreign: dict[str, bool], shock: float) -> pd.DataFrame:
    """Spread an FX move of ``shock`` (e.g. -0.10 = the base currency appreciates 10%) evenly over the window on
    foreign-currency securities: (1 + r_i,t)(1 + δ) − 1 with (1 + δ)^T = 1 + shock."""
    T = len(R)
    delta = (1 + shock) ** (1 / max(T, 1)) - 1
    out = R.copy()
    for c in R.columns:
        if foreign.get(c):
            out[c] = (1 + R[c]) * (1 + delta) - 1
    return out


def worst_window(train_port_r: pd.Series, days: int) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    if len(train_port_r) < days:
        return float("nan"), None, None
    roll = np.exp(np.log1p(train_port_r).rolling(days).sum()) - 1
    end = roll.idxmin()
    pos = train_port_r.index.get_loc(end)
    return float(roll.min()), train_port_r.index[pos - days + 1], end


def renormalized_without(user_w: pd.Series, market_of: dict[str, str], drop: list[str]) -> pd.Series:
    """User weights without ``drop``: shares re-split inside each market; empty markets' budgets re-split."""
    w = user_w.copy()
    budgets = w.groupby(lambda tk: market_of.get(tk, "?")).sum()
    keep = w.drop(index=[d for d in drop if d in w.index])
    out = {}
    kept_m = keep.groupby(lambda tk: market_of.get(tk, "?")).sum()
    total_budget = sum(budgets[m] for m in kept_m.index)
    for tk, v in keep.items():
        m = market_of.get(tk, "?")
        share = v / kept_m[m] if kept_m[m] > 0 else 0.0
        out[tk] = budgets[m] / total_budget * share if total_budget > 0 else 0.0
    return pd.Series(out).reindex(user_w.index).fillna(0.0)
