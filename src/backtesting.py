"""Optional walk-forward backtest (kept separate from the historical Markowitz analysis).

At each rebalance date d, weights are estimated ONLY from returns strictly before d
(rolling or expanding window).  Between rebalances weights drift with prices.
Costs: (transaction + slippage) bps x one-way turnover, charged on the rebalance day.
All strategies share identical out-of-sample test dates.

Known limitations (disclosed in the UI): survivorship bias (the user picks today's
listings), adjusted-price revisions, no taxes, no FX transaction costs, no cash drag.
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
    estimation: str = "rolling"       # rolling | expanding
    window: int = 252                 # observations for the rolling window / minimum for expanding
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
            rf: float, notes: list[str], d) -> np.ndarray:
    if strategy in ("user_rebalanced", "user_buy_and_hold"):
        return user_w
    if strategy == "equal_weight":
        w = np.zeros(cs.n)
        for m, g in cs.groups.items():
            w[g] = cs.market_budgets[m] / len(g)
        return w
    mu = estimate_mu(est, cfg.mu_estimator, cfg.periods_per_year).values
    cov, _ = estimate_cov(est, cfg.cov_estimator, cfg.periods_per_year)
    res = (minimum_variance if strategy == "min_variance" else maximum_sharpe)(mu, cov.values, cs, rf)
    if not res.ok:
        notes.append(t("{date}: {strategy} optimisation failed ({status}); previous weights kept.", date=d.date(),
                       strategy=t(STRATEGY_LABELS.get(strategy, strategy)), status=res.status))
        return None  # type: ignore[return-value]
    return res.weights.values


def run_backtest(prices: pd.DataFrame, user_w: pd.Series, cs: ConstraintSet, rf_annual: float,
                 cfg: BacktestConfig) -> BacktestResult:
    rets = simple_returns(prices.dropna(how="any"))
    tickers = cs.tickers
    rets = rets[tickers]
    notes: list[str] = []
    if len(rets) <= cfg.window + 5:
        return BacktestResult(pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame(), None, None, 0,
                              [t("Need more than {need} observations; have {have}.", need=cfg.window + 5,
                                 have=len(rets))])
    rf = rf_markowitz(rf_annual, cfg.periods_per_year)
    uw = user_w.reindex(tickers).fillna(0).values
    period_end = rets.index.to_series().resample(REBALANCE_RULES[cfg.rebalance]).last().dropna()
    # first trading day strictly after each period end, and only once the window is available
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
        r_t = rets.iloc[k].values
        for s in cfg.strategies:
            turnover = 0.0
            if k in decision_set and (s != "user_buy_and_hold" or cur[s] is None):
                est = rets.iloc[max(0, k - cfg.window):k] if cfg.estimation == "rolling" else rets.iloc[:k]
                tgt = _target(s, est, cs, uw, cfg, rf, notes, d)
                if tgt is None and cur[s] is None:  # first decision failed: start from equal weight, disclosed
                    tgt = _target("equal_weight", est, cs, uw, cfg, rf, notes, d)
                    notes.append(t("{date}: {strategy} started from equal weights after a failed first optimisation.",
                                   date=d.date(), strategy=t(STRATEGY_LABELS.get(s, s))))
                if tgt is not None:
                    if cur[s] is None:
                        turnover = float(np.abs(tgt).sum())  # initial purchase
                    else:
                        # One-way turnover is half the L1 weight change for a
                        # fully invested long/short portfolio: buys and sells
                        # are both counted in gross traded value.
                        turnover = 0.5 * float(np.abs(tgt - cur[s]).sum())
                    cur[s] = tgt
                    w_hist[s].append(pd.Series(tgt, index=tickers, name=d))
            w = cur[s]
            rp = float(w @ r_t)
            out_r[s].append(rp - turnover * cost_rate)
            out_t[s].append(turnover)
            cur[s] = w * (1 + r_t) / (1 + rp) if (1 + rp) > 0 else w
    R = pd.DataFrame(out_r, index=test.index)
    TO = pd.DataFrame(out_t, index=test.index)
    years = max(len(R) / cfg.periods_per_year, 1e-9)
    rows = []
    for s in cfg.strategies:
        st = portfolio_statistics(R[s], rf_annual, cfg.periods_per_year)
        rows.append({"strategy": s, "cagr": st["annual_geometric_return_cagr"],
                     "annual_volatility": st["annual_volatility"], "sharpe": st["sharpe_annual"],
                     "max_drawdown": st["max_drawdown"], "cumulative_return": st["cumulative_return"],
                     "annual_turnover": float(TO[s].iloc[1:].sum() / years),
                     "total_cost_drag": float((TO[s] * cost_rate).sum())})
    notes.append(t("Out-of-sample: weights at each decision date use only returns observed before that date."))
    return BacktestResult(R, TO, {s: pd.DataFrame(v) for s, v in w_hist.items()},
                          pd.DataFrame(rows).set_index("strategy"), test.index[0], test.index[-1], len(decision_pos),
                          notes)
