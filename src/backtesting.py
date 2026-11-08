"""Backtest a set of strategies with costs charged to NAV and holdings.

At each rebalance date d, target weights are estimated only from returns strictly
before d. Between rebalances weights drift with realised asset returns. Transaction
and slippage costs are charged against portfolio NAV at the rebalance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .i18n import N_, t
from .optimization import ConstraintSet, maximum_sharpe, minimum_variance
from .returns import simple_returns
from .statistics import estimate_cov, estimate_mu, portfolio_statistics, rf_markowitz

STRATEGY_LABELS = {"user_rebalanced": N_("User weights, rebalanced"),
                   "user_buy_and_hold": N_("User weights, buy and hold"),
                   "equal_weight": N_("Equal weight"), "min_variance": N_("Minimum variance"),
                   "max_sharpe": N_("Maximum Sharpe")}
REBALANCE_RULES = {"monthly": "ME", "quarterly": "QE", "annual": "YE"}


@dataclass
class BacktestConfig:
    estimation: str = "rolling"
    window: int = 252
    rebalance: str = "monthly"
    cost_bps: float = 10.0
    slippage_bps: float = 5.0
    strategies: tuple[str, ...] = ("user_rebalanced", "user_buy_and_hold", "equal_weight", "min_variance",
                                   "max_sharpe")
    mu_estimator: str = "arithmetic"
    cov_estimator: str = "ledoit_wolf"
    periods_per_year: int = 252


@dataclass
class BacktestResult:
    returns: pd.DataFrame
    turnover: pd.DataFrame
    weights_at_rebalance: dict[str, pd.DataFrame]
    summary: pd.DataFrame
    test_start: pd.Timestamp | None
    test_end: pd.Timestamp | None
    n_rebalances: int
    notes: list[str] = field(default_factory=list)


def _target(strategy: str, est: pd.DataFrame, cs: ConstraintSet, user_w: np.ndarray, cfg: BacktestConfig,
            rf: float, notes: list[str], d) -> np.ndarray | None:
    if strategy in ("user_rebalanced", "user_buy_and_hold"):
        return user_w.copy()
    if strategy == "equal_weight":
        w = np.zeros(cs.n)
        for m, g in cs.groups.items():
            w[g] = cs.market_budgets[m] / len(g)
        if not cs.is_feasible(w):
            notes.append(t("{date}: equal-weight allocation violates the configured per-security bounds; strategy skipped.",
                           date=d.date()))
            return None
        return w
    mu = estimate_mu(est, cfg.mu_estimator, cfg.periods_per_year).reindex(cs.tickers).values
    cov, _ = estimate_cov(est, cfg.cov_estimator, cfg.periods_per_year)
    cov_values = cov.reindex(index=cs.tickers, columns=cs.tickers).values
    if strategy == "min_variance":
        res = minimum_variance(mu, cov_values, cs, rf)
    elif strategy == "max_sharpe":
        res = maximum_sharpe(mu, cov_values, cs, rf)
    else:
        raise ValueError(f"Unknown backtest strategy: {strategy}")
    if not res.ok:
        notes.append(t("{date}: {strategy} optimisation failed ({status}); previous weights kept.",
                       date=d.date(), strategy=t(STRATEGY_LABELS.get(strategy, strategy)), status=res.status))
        return None
    return res.weights.reindex(cs.tickers).values


def run_backtest(prices: pd.DataFrame, user_w: pd.Series, cs: ConstraintSet, rf_annual: float,
                 cfg: BacktestConfig) -> BacktestResult:
    if cfg.estimation not in ("rolling", "expanding"):
        raise ValueError("estimation must be 'rolling' or 'expanding'.")
    if cfg.rebalance not in REBALANCE_RULES:
        raise ValueError(f"Unsupported rebalance frequency: {cfg.rebalance}")
    if cfg.window < 2 or cfg.periods_per_year <= 0:
        raise ValueError("window must be >= 2 and periods_per_year must be positive.")
    if not np.isfinite(cfg.cost_bps) or not np.isfinite(cfg.slippage_bps) or min(cfg.cost_bps, cfg.slippage_bps) < 0:
        raise ValueError("Transaction costs and slippage must be finite and non-negative.")
    if not np.isfinite(rf_annual) or rf_annual <= -1:
        raise ValueError("The effective annual risk-free rate must be finite and greater than -100%.")
    unknown = set(cfg.strategies) - set(STRATEGY_LABELS)
    if unknown:
        raise ValueError(f"Unknown strategies: {', '.join(sorted(unknown))}")

    rets = simple_returns(prices.dropna(how="any"))[cs.tickers]
    notes: list[str] = []
    if len(rets) <= cfg.window + 5:
        return BacktestResult(pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), None, None, 0,
                              [t("Need more than {need} observations; have {have}.", need=cfg.window + 5,
                                 have=len(rets))])
    rf = rf_markowitz(rf_annual, cfg.periods_per_year)
    uw = user_w.reindex(cs.tickers).fillna(0.0).to_numpy(dtype=float)
    if not np.isfinite(uw).all() or not cs.is_feasible(uw):
        raise ValueError("User portfolio weights must be finite and satisfy the configured constraints.")

    period_end = rets.index.to_series().resample(REBALANCE_RULES[cfg.rebalance]).last().dropna()
    pos_ends = rets.index.get_indexer(pd.DatetimeIndex(period_end.values))
    decision_pos = sorted({p + 1 for p in pos_ends if cfg.window <= p + 1 < len(rets)})
    if not decision_pos:
        return BacktestResult(pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), None, None, 0,
                              [t("No rebalance date after the estimation window.")])
    first = decision_pos[0]
    test = rets.iloc[first:]
    out_r = {s: [] for s in cfg.strategies}
    out_t = {s: [] for s in cfg.strategies}
    w_hist = {s: [] for s in cfg.strategies}
    cur = {s: None for s in cfg.strategies}
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 1e4
    decision_set = set(decision_pos)
    for k in range(first, len(rets)):
        d = rets.index[k]
        r_t = rets.iloc[k].to_numpy(dtype=float)
        if not np.isfinite(r_t).all() or np.any(r_t < -1):
            raise ValueError(f"Invalid asset return encountered on {d.date()}.")
        for strategy in cfg.strategies:
            turnover = 0.0
            if k in decision_set and (strategy != "user_buy_and_hold" or cur[strategy] is None):
                est = rets.iloc[max(0, k - cfg.window):k] if cfg.estimation == "rolling" else rets.iloc[:k]
                target = _target(strategy, est, cs, uw, cfg, rf, notes, d)
                if target is None and cur[strategy] is None:
                    raise RuntimeError(
                        f"Cannot initialize {strategy}: no valid feasible target was obtained. "
                        "The backtest is stopped rather than silently substituting a different strategy."
                    )
                if target is not None:
                    current = cur[strategy]
                    turnover = float(np.abs(target - (current if current is not None else 0.0)).sum())
                    cur[strategy] = target.copy()
                    w_hist[strategy].append(pd.Series(target, index=cs.tickers, name=d))

            weights = cur[strategy]
            if weights is None:
                raise RuntimeError(f"Strategy {strategy} has no initial feasible portfolio.")
            gross_return = float(weights @ r_t)
            if gross_return <= -1:
                net_return = -1.0
            else:
                net_return = (1.0 + gross_return) * (1.0 - turnover * cost_rate) - 1.0
            out_r[strategy].append(net_return)
            out_t[strategy].append(turnover)

            # Costs are paid from NAV. Applying the same net return to holdings makes the
            # next-period drift consistent with the NAV series (previously only the output
            # return included costs, while the weights drifted on gross returns).
            if gross_return > -1:
                cur[strategy] = weights * (1.0 + r_t) * (1.0 - turnover * cost_rate) / (1.0 + net_return)
            else:
                cur[strategy] = weights.copy()

    R = pd.DataFrame(out_r, index=test.index)
    TO = pd.DataFrame(out_t, index=test.index)
    years = max(len(R) / cfg.periods_per_year, 1e-9)
    rows = []
    for strategy in cfg.strategies:
        st = portfolio_statistics(R[strategy], rf_annual, cfg.periods_per_year,
                                  period_start=rets.index[first - 1])
        rows.append({"strategy": strategy, "cagr": st["annual_geometric_return_cagr"],
                     "annual_volatility": st["annual_volatility"], "sharpe": st["sharpe_annual"],
                     "max_drawdown": st["max_drawdown"], "cumulative_return": st["cumulative_return"],
                     "annual_turnover": float(TO[strategy].iloc[1:].sum() / years),
                     "total_cost_drag": float((TO[strategy] * cost_rate).sum())})
    notes.append(t("Out-of-sample: weights at each decision date use only returns observed before that date."))
    return BacktestResult(R, TO, {s: pd.DataFrame(v) for s, v in w_hist.items()},
                          pd.DataFrame(rows).set_index("strategy"), test.index[0], test.index[-1], len(decision_pos),
                          notes)
