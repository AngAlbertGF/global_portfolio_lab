"""Constrained Markowitz frontier.

1. Feasible expected-return range [R_min, R_max] from two linear programs.
2. Global minimum-variance (GMV) portfolio, return R_gmv.
3. For targets R in [R_min, R_max]: min w'Sigma w s.t. mu'w = R + constraints
   (warm-started, solver status and every residual checked).
   Points with R >= R_gmv form the efficient (upper) branch; R < R_gmv the inefficient branch.
Endpoints are moved inside the range by 1e-9 of its width to avoid degenerate equality targets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .i18n import t
from .optimization import ConstraintSet, OptimizationResult, maximum_return, minimum_return_value, \
    minimum_variance, min_variance_at_target


@dataclass
class FrontierResult:
    points: pd.DataFrame                    # one row per attempted target
    weights: pd.DataFrame                   # rows = successful points, columns = tickers
    r_min: float | None
    r_max: float | None
    gmv: OptimizationResult | None
    tangency: OptimizationResult | None
    warnings: list[str] = field(default_factory=list)

    @property
    def efficient(self) -> pd.DataFrame:
        p = self.points
        return p[(p["ok"]) & (p["branch"] == "efficient")].sort_values("expected_return")

    @property
    def inefficient(self) -> pd.DataFrame:
        p = self.points
        return p[(p["ok"]) & (p["branch"] == "inefficient")].sort_values("expected_return")


def build_frontier(mu: pd.Series, cov: pd.DataFrame, cs: ConstraintSet, rf: float, n_points: int = 50,
                   tangency: OptimizationResult | None = None, gmv: OptimizationResult | None = None
                   ) -> FrontierResult:
    m = mu.reindex(cs.tickers).values
    S = cov.reindex(index=cs.tickers, columns=cs.tickers).values
    warnings: list[str] = []
    problems = cs.feasibility_problems()
    empty = pd.DataFrame(columns=["target", "expected_return", "volatility", "sharpe", "ok", "branch", "status"])
    if problems:
        return FrontierResult(empty, pd.DataFrame(), None, None, None, None, problems)
    r_min = minimum_return_value(m, cs)
    mx = maximum_return(m, S, cs, rf)
    r_max = mx.expected_return if mx.ok else None
    gmv = gmv if gmv is not None and gmv.ok else minimum_variance(m, S, cs, rf)
    if r_min is None or r_max is None or not gmv.ok:
        return FrontierResult(empty, pd.DataFrame(), r_min, r_max, gmv, None,
                              [t("Feasible return range or GMV could not be determined; frontier not built.")])
    width = r_max - r_min
    if width < 1e-12:
        warnings.append(t("All feasible portfolios have the same expected return: the frontier is a single point."))
        targets = np.array([gmv.expected_return])
    else:
        eps = 1e-9 * width
        targets = np.unique(np.concatenate([np.linspace(r_min + eps, r_max - eps, n_points), [gmv.expected_return]]))
    rows, wrows = [], []
    order = np.argsort(np.abs(targets - gmv.expected_return))  # solve outward from GMV for warm starts
    prev_up, prev_down = gmv.weights.values, gmv.weights.values
    results: dict[float, OptimizationResult] = {}
    for k in order:
        tgt = targets[k]
        x0 = prev_up if tgt >= gmv.expected_return else prev_down
        if abs(tgt - gmv.expected_return) < 1e-14:
            res = gmv
        else:
            res = min_variance_at_target(m, S, cs, tgt, rf, x0)
            if not res.ok:  # retry from a neutral start
                res2 = min_variance_at_target(m, S, cs, tgt, rf, cs.feasible_start())
                res = res2 if res2.ok else res
        results[tgt] = res
        if res.ok:
            if tgt >= gmv.expected_return:
                prev_up = res.weights.values
            else:
                prev_down = res.weights.values
    for tgt in sorted(results):
        res = results[tgt]
        branch = "efficient" if tgt >= gmv.expected_return - 1e-12 else "inefficient"
        rows.append({"target": tgt, "expected_return": res.expected_return, "volatility": res.volatility,
                     "sharpe": res.sharpe, "ok": res.ok, "branch": branch, "status": str(res.status)[:80],
                     "is_gmv": res is gmv, "max_residual": res.summary()["max_residual"]})
        if res.ok:
            wrows.append(pd.Series(res.weights.values, index=cs.tickers, name=tgt))
    points = pd.DataFrame(rows)
    weights = pd.DataFrame(wrows)
    failed = int((~points["ok"]).sum())
    if failed:
        warnings.append(t("{failed} of {total} frontier targets failed and are excluded from the curve.",
                          failed=failed, total=len(points)))
    eff = points[(points["ok"]) & (points["branch"] == "efficient")].sort_values("expected_return")
    if len(eff) > 2 and np.any(np.diff(eff["volatility"].values) < -1e-6):
        warnings.append(t("Efficient-branch volatility is not monotone in return (numerical issue) -- inspect "
                          "points."))
    if tangency is not None and tangency.ok and tangency.sharpe is not None:
        best = points.loc[points["ok"], "sharpe"].max()
        if best is not None and np.isfinite(best) and best > tangency.sharpe + 1e-6:
            warnings.append(t("A frontier point has Sharpe {best} > tangency {tangency}; tangency not certified.",
                              best=f"{best:.4f}", tangency=f"{tangency.sharpe:.4f}"))
            tangency = None
    elif tangency is not None:
        tangency = None
        warnings.append(t("No valid maximum-Sharpe solution: tangency portfolio not identified."))
    return FrontierResult(points, weights, r_min, r_max, gmv, tangency, warnings)
