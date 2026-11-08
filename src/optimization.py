"""Constrained Markowitz optimisation with explicit feasibility and optimality checks.

Feasible set (n assets, markets m with fixed budgets A_m, sum_m A_m = 1)
-------------------------------------------------------------------------
fixed_markets mode :  sum_{i in m} w_i = A_m for every market m   (implies sum w = 1)
global_only mode   :  sum_i w_i = 1
bounds             :  lb_i <= w_i <= ub_i  (long-only: lb = 0; optional cap ub; short mode: lb < 0)

Only one of the two equality systems is passed to the solver (the budget row is
linearly dependent on the market rows), but *both* are always verified.

Methods and what is certified
-----------------------------
minimum variance   convex QP, SLSQP with analytic gradients from two starts; agreement checked
maximum Sharpe     Charnes-Cooper transform -> convex QP in (y, kappa):
                   min y'Sigma y  s.t. (mu - rf)'y = 1, A y = kappa b, kappa*lb <= y <= kappa*ub
                   valid when some feasible portfolio has mu_p > rf; w = y / kappa.
                   Cross-checked against a direct multi-start search and all comparison portfolios.
maximum return     linear program (HiGHS) -> exact
maximum risk       maximising a convex function: optimum lies at a vertex of the feasible polytope.
                   Long-only without caps: exhaustive vertex enumeration -> exact.
                   Otherwise multi-start local search -> approximate, NOT certified.
minimum CVaR       Rockafellar-Uryasev linear program on historical scenarios -> exact (in-sample)
max diversification  same transform as max Sharpe with (mu - rf) replaced by asset volatilities
target volatility  max mu'w s.t. w'Sigma w <= target^2 (convex), SLSQP
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize

from .config import WEIGHT_TOLERANCE
from .i18n import t

logger = logging.getLogger("gpl.optimization")
FEAS_TOL = 1e-6


@dataclass
class ConstraintSet:
    tickers: list[str]
    market_of: dict[str, str]
    market_budgets: dict[str, float]          # fractions, used in fixed_markets mode
    mode: str = "fixed_markets"
    lb: np.ndarray | None = None
    ub: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = len(self.tickers)
        self.lb = np.zeros(n) if self.lb is None else np.asarray(self.lb, float)
        self.ub = np.ones(n) if self.ub is None else np.asarray(self.ub, float)
        self.markets = sorted({self.market_of[t] for t in self.tickers})
        self.groups = {m: np.array([i for i, t in enumerate(self.tickers) if self.market_of[t] == m])
                       for m in self.markets}

    @classmethod
    def build(cls, tickers: list[str], market_of: dict[str, str], market_budgets: dict[str, float],
              mode: str = "fixed_markets", long_only: bool = True, min_weight: float = 0.0,
              max_weight: float | None = None) -> "ConstraintSet":
        n = len(tickers)
        lb = np.zeros(n) if long_only else np.full(n, float(min_weight))
        if max_weight is not None:
            ub = np.full(n, float(max_weight))
        else:
            ub = np.ones(n) if long_only else np.full(n, 1.0 - float(min_weight) * (n - 1))
        return cls(tickers, market_of, market_budgets, mode, lb, ub)

    @property
    def n(self) -> int:
        return len(self.tickers)

    @property
    def is_simple_long_only(self) -> bool:
        """Long-only and no binding caps: vertices are 'one asset per market' portfolios."""
        if np.any(self.lb != 0):
            return False
        if self.mode == "fixed_markets":
            return all(np.all(self.ub[g] >= self.market_budgets[m] - 1e-12) for m, g in self.groups.items())
        return bool(np.all(self.ub >= 1 - 1e-12))

    def equality_system(self) -> tuple[np.ndarray, np.ndarray]:
        if self.mode == "fixed_markets":
            A = np.zeros((len(self.markets), self.n))
            for k, m in enumerate(self.markets):
                A[k, self.groups[m]] = 1.0
            return A, np.array([self.market_budgets[m] for m in self.markets])
        return np.ones((1, self.n)), np.array([1.0])

    def feasibility_problems(self) -> list[str]:
        msgs = []
        if np.any(self.lb > self.ub):
            msgs.append(t("Some lower bounds exceed upper bounds."))
        if self.mode == "fixed_markets":
            total = sum(self.market_budgets[m] for m in self.markets)
            if abs(total - 1) > 1e-9:
                msgs.append(t("Market budgets sum to {value}, not 1.", value=f"{total:.10f}"))
            for m, g in self.groups.items():
                lo, hi = self.lb[g].sum(), self.ub[g].sum()
                if not (lo - 1e-12 <= self.market_budgets[m] <= hi + 1e-12):
                    msgs.append(t("Market {market}: budget {budget} is outside the attainable range [{lo}, {hi}] "
                                  "given per-stock bounds (add stocks or relax the cap).", market=m,
                                  budget=f"{self.market_budgets[m]:.4%}", lo=f"{lo:.4%}", hi=f"{hi:.4%}"))
        else:
            if not (self.lb.sum() - 1e-12 <= 1 <= self.ub.sum() + 1e-12):
                msgs.append(t("Bounds make a fully-invested portfolio impossible."))
        return msgs

    def residuals(self, w: np.ndarray) -> dict:
        res = {"budget": float(abs(w.sum() - 1.0)),
               "lower_bound_violation": float(max(0.0, np.max(self.lb - w))),
               "upper_bound_violation": float(max(0.0, np.max(w - self.ub)))}
        market = {m: float(w[g].sum() - self.market_budgets[m]) for m, g in self.groups.items()}
        if self.mode == "fixed_markets":
            res["market_max_abs"] = float(max(abs(v) for v in market.values()))
        res["market_sums"] = {m: float(w[g].sum()) for m, g in self.groups.items()}
        res["market_deviation"] = market
        return res

    def is_feasible(self, w: np.ndarray, tol: float = FEAS_TOL) -> bool:
        r = self.residuals(w)
        ok = r["budget"] <= tol and r["lower_bound_violation"] <= tol and r["upper_bound_violation"] <= tol
        if self.mode == "fixed_markets":
            ok = ok and r["market_max_abs"] <= tol
        return bool(ok)

    def polish(self, w: np.ndarray) -> np.ndarray:
        """Remove solver noise (< 1e-9): clip into bounds and re-balance each group/budget exactly."""
        w = np.clip(w, self.lb, self.ub)
        groups = self.groups.items() if self.mode == "fixed_markets" else [("ALL", np.arange(self.n))]
        for m, g in groups:
            target = self.market_budgets[m] if self.mode == "fixed_markets" else 1.0
            for _ in range(5):
                resid = target - w[g].sum()
                if abs(resid) < 1e-15:
                    break
                room = (self.ub[g] - w[g]) if resid > 0 else (w[g] - self.lb[g])
                if room.sum() <= 0:
                    break
                w[g] = w[g] + np.sign(resid) * room / room.sum() * min(abs(resid), room.sum())
        return w

    def feasible_start(self, rng: np.random.Generator | None = None) -> np.ndarray:
        """A strictly interior-ish feasible point (equal split or Dirichlet), polished into bounds."""
        w = np.zeros(self.n)
        groups = self.groups.items() if self.mode == "fixed_markets" else [("ALL", np.arange(self.n))]
        for m, g in groups:
            target = self.market_budgets[m] if self.mode == "fixed_markets" else 1.0
            share = rng.dirichlet(np.ones(len(g))) if rng is not None else np.full(len(g), 1 / len(g))
            w[g] = target * share
        return self.polish(w)


@dataclass
class OptimizationResult:
    name: str
    weights: pd.Series
    expected_return: float
    volatility: float
    sharpe: float | None
    solver_success: bool
    feasible: bool
    status: str
    method: str
    certification: str
    residuals: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.solver_success and self.feasible

    def summary(self) -> dict:
        return {"portfolio": self.name, "expected_return": self.expected_return, "volatility": self.volatility,
                "sharpe": self.sharpe, "ok": self.ok, "solver_success": self.solver_success,
                "feasible": self.feasible, "certification": self.certification, "method": self.method,
                "status": self.status, "max_residual": max([v for k, v in self.residuals.items()
                                                            if isinstance(v, float)] or [np.nan])}


def port_stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> tuple[float, float, float | None]:
    ret = float(w @ mu)
    var = float(w @ cov @ w)
    vol = float(np.sqrt(max(var, 0.0)))
    sharpe = (ret - rf) / vol if vol > 1e-12 else None
    return ret, vol, sharpe


def make_result(name: str, w: np.ndarray, cs: ConstraintSet, mu: np.ndarray, cov: np.ndarray, rf: float,
                solver_success: bool, status: str, method: str, certification: str,
                notes: list[str] | None = None, polish: bool = True) -> OptimizationResult:
    w = cs.polish(w.copy()) if polish and solver_success else np.asarray(w, float)
    feasible = cs.is_feasible(w)
    ret, vol, sh = port_stats(w, mu, cov, rf)
    notes = list(notes or [])
    if vol <= 1e-12:
        notes.append(t("Volatility is zero: Sharpe ratio undefined."))
    if not feasible:
        notes.append(t("Result violates constraints beyond tolerance; NOT reported as a valid optimum."))
    cert = certification if (solver_success and feasible) else t("failed")
    return OptimizationResult(name, pd.Series(w, index=cs.tickers), ret, vol, sh, solver_success, feasible, status,
                              method, cert, cs.residuals(w), notes)


def _scipy_constraints(cs: ConstraintSet) -> list[dict]:
    A, b = cs.equality_system()
    return [{"type": "eq", "fun": lambda w, A=A, b=b: A @ w - b, "jac": lambda w, A=A: A}]


# ---------------------------------------------------------------------------
# Minimum variance (+ target return)
# ---------------------------------------------------------------------------
def _min_var(cov: np.ndarray, cs: ConstraintSet, x0: np.ndarray, extra: list[dict] | None = None):
    f = lambda w: float(w @ cov @ w)
    g = lambda w: 2.0 * cov @ w
    return minimize(f, x0, jac=g, method="SLSQP", bounds=list(zip(cs.lb, cs.ub)),
                    constraints=_scipy_constraints(cs) + (extra or []),
                    options={"ftol": 1e-15, "maxiter": 2000})


def minimum_variance(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float,
                     extra_starts: list[np.ndarray] | None = None) -> OptimizationResult:
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(t("Minimum variance"), cs, mu, cov, rf, problems)
    starts = [cs.feasible_start()] + [s for s in (extra_starts or []) if s is not None]
    sols = [_min_var(cov, cs, x0) for x0 in starts]
    good = [s for s in sols if s.success and cs.is_feasible(cs.polish(s.x.copy()))]
    if not good:
        best = min(sols, key=lambda s: s.fun)
        return make_result(t("Minimum variance"), best.x, cs, mu, cov, rf, False, best.message, t("SLSQP (convex QP)"),
                           t("failed"))
    best = min(good, key=lambda s: s.fun)
    spread = (max(s.fun for s in good) - best.fun) / max(abs(best.fun), 1e-16)
    notes = [t("{ok}/{total} starts converged; relative objective spread {spread}.", ok=len(good), total=len(sols),
               spread=f"{spread:.1e}")]
    cert = t("global optimum (convex QP; starts agree)") if spread < 1e-6 else t("best of starts (starts disagree)")
    return make_result(t("Minimum variance"), best.x, cs, mu, cov, rf, True, best.message, t("SLSQP (convex QP)"), cert,
                       notes)


def min_variance_at_target(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, target: float, rf: float,
                           x0: np.ndarray | None = None) -> OptimizationResult:
    cons = [{"type": "eq", "fun": lambda w: np.array([w @ mu - target]), "jac": lambda w: mu[None, :]}]
    sol = _min_var(cov, cs, x0 if x0 is not None else cs.feasible_start(), cons)
    res = make_result(t("Min variance @ {target}", target=f"{target:.4%}"), sol.x, cs, mu, cov, rf, bool(sol.success), sol.message,
                      t("SLSQP (convex QP)"), t("optimal (convex QP)"))
    gap = abs(res.expected_return - target)
    res.residuals["target_return"] = gap
    if gap > FEAS_TOL * max(1.0, abs(target)):
        res.feasible = False
        res.certification = t("failed")
        res.notes.append(t("Target return missed by {gap}.", gap=f"{gap:.2e}"))
    return res


# ---------------------------------------------------------------------------
# Linear programs: max / min return, min CVaR
# ---------------------------------------------------------------------------
def _lp(c: np.ndarray, cs: ConstraintSet):
    A, b = cs.equality_system()
    return linprog(c, A_eq=A, b_eq=b, bounds=list(zip(cs.lb, cs.ub)), method="highs")


def maximum_return(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float) -> OptimizationResult:
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(t("Maximum return"), cs, mu, cov, rf, problems)
    sol = _lp(-mu, cs)
    notes = [t("Concentrates each market budget in its highest estimated-return security unless caps bind. "
               "A historical maximum is not a forecast.")]
    if sol.status != 0:
        return make_result(t("Maximum return"), cs.feasible_start(), cs, mu, cov, rf, False, sol.message,
                           t("Linear program (HiGHS)"), t("failed"), notes)
    return make_result(t("Maximum return"), sol.x, cs, mu, cov, rf, True, sol.message, t("Linear program (HiGHS)"),
                       t("exact (LP)"), notes)


def minimum_return_value(mu: np.ndarray, cs: ConstraintSet) -> float | None:
    sol = _lp(mu, cs)
    return float(sol.fun) if sol.status == 0 else None


def minimum_cvar(returns: np.ndarray, mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float,
                 level: float = 0.95) -> OptimizationResult:
    """Rockafellar-Uryasev LP: min a + 1/((1-b)T) sum u_t, u_t >= -r_t'w - a, u >= 0 (per-period scenarios)."""
    returns = np.asarray(returns, dtype=float)
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    if not np.isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError("CVaR confidence level must lie strictly between 0 and 1.")
    if (returns.ndim != 2 or returns.shape[0] < 2 or returns.shape[1] != cs.n
            or not np.isfinite(returns).all() or np.any(returns < -1.0)):
        raise ValueError("CVaR scenarios must be a finite T-by-N matrix with T >= 2 and returns >= -100%.")
    if mu.shape != (cs.n,) or cov.shape != (cs.n, cs.n) or not np.isfinite(mu).all() or not np.isfinite(cov).all():
        raise ValueError("CVaR expected returns and covariance must be finite and match the constraint universe.")
    if not np.isfinite(rf):
        raise ValueError("The risk-free input to CVaR optimisation must be finite.")
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(t("Minimum CVaR {level}", level=f"{level:.0%}"), cs, mu, cov, rf, problems)
    T, n = returns.shape
    A, b = cs.equality_system()
    c = np.concatenate([np.zeros(n), [1.0], np.full(T, 1.0 / ((1 - level) * T))])
    A_ub = np.hstack([-returns, -np.ones((T, 1)), -np.eye(T)])
    A_eq = np.hstack([A, np.zeros((A.shape[0], 1 + T))])
    bounds = list(zip(cs.lb, cs.ub)) + [(None, None)] + [(0, None)] * T
    sol = linprog(c, A_ub=A_ub, b_ub=np.zeros(T), A_eq=A_eq, b_eq=b, bounds=bounds, method="highs")
    name = t("Minimum CVaR {level}", level=f"{level:.0%}")
    if sol.status != 0:
        return make_result(name, cs.feasible_start(), cs, mu, cov, rf, False, sol.message, t("LP (Rockafellar-Uryasev)"),
                           t("failed"))
    res = make_result(name, sol.x[:n], cs, mu, cov, rf, True, sol.message, t("LP (Rockafellar-Uryasev, HiGHS)"),
                      t("exact (in-sample LP)"), [t("Minimised historical per-period CVaR = {value}.", value=f"{sol.fun:.4%}")])
    return res


# ---------------------------------------------------------------------------
# Ratio maximisation (Sharpe, diversification) via Charnes-Cooper
# ---------------------------------------------------------------------------
def _ratio_transform(cov: np.ndarray, a: np.ndarray, cs: ConstraintSet):
    """max a'w / sqrt(w'Sigma w) over the feasible set, assuming max a'w > 0 on it."""
    n = cs.n
    A, b = cs.equality_system()
    finite_lb = np.isfinite(cs.lb)
    cons = [
        {"type": "eq", "fun": lambda x: np.array([a @ x[:n] - 1.0]),
         "jac": lambda x: np.concatenate([a, [0.0]])[None, :]},
        {"type": "eq", "fun": lambda x: A @ x[:n] - b * x[n], "jac": lambda x: np.hstack([A, -b[:, None]])},
        {"type": "ineq", "fun": lambda x: cs.ub * x[n] - x[:n],
         "jac": lambda x: np.hstack([-np.eye(n), cs.ub[:, None]])},
        {"type": "ineq", "fun": lambda x: x[:n] - cs.lb * x[n],
         "jac": lambda x: np.hstack([np.eye(n), -cs.lb[:, None]])},
    ]
    w0 = cs.feasible_start()
    s0 = a @ w0
    k0 = 1.0 / s0 if s0 > 1e-12 else 1.0
    x0 = np.concatenate([w0 * k0, [k0]])
    f = lambda x: float(x[:n] @ cov @ x[:n])
    g = lambda x: np.concatenate([2 * cov @ x[:n], [0.0]])
    bounds = [(None, None)] * n + [(0.0, None)]
    del finite_lb
    sol = minimize(f, x0, jac=g, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"ftol": 1e-15, "maxiter": 3000})
    k = sol.x[n]
    return sol, (sol.x[:n] / k if k > 1e-14 else None)


def _direct_ratio(cov: np.ndarray, a: np.ndarray, cs: ConstraintSet, n_starts: int = 12, seed: int = 0):
    rng = np.random.default_rng(seed)

    def neg(w):
        v = np.sqrt(max(w @ cov @ w, 1e-20))
        return -(a @ w) / v

    def grad(w):
        v = np.sqrt(max(w @ cov @ w, 1e-20))
        return -(a / v - (a @ w) * (cov @ w) / v ** 3)
    best = None
    starts = [cs.feasible_start()] + [cs.feasible_start(rng) for _ in range(n_starts - 1)]
    for x0 in starts:
        s = minimize(neg, x0, jac=grad, method="SLSQP", bounds=list(zip(cs.lb, cs.ub)),
                     constraints=_scipy_constraints(cs), options={"ftol": 1e-14, "maxiter": 2000})
        w = cs.polish(s.x.copy())
        if s.success and cs.is_feasible(w) and (best is None or neg(w) < neg(best)):
            best = w
    return best


def maximum_sharpe(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float,
                   comparison: dict[str, np.ndarray] | None = None, cross_check: bool = True) -> OptimizationResult:
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(t("Maximum Sharpe"), cs, mu, cov, rf, problems)
    excess = mu - rf
    lp = _lp(-excess, cs)
    max_excess = -lp.fun if lp.status == 0 else None
    notes: list[str] = []
    w = None
    method = t("Charnes-Cooper transform -> convex QP (SLSQP)")
    cert = t("global optimum (convex reformulation)")
    if max_excess is not None and max_excess > 1e-10:
        sol, w = _ratio_transform(cov, excess, cs)
        if w is None or not sol.success or not cs.is_feasible(cs.polish(w.copy())):
            notes.append(t("Convex reformulation did not converge ({message}); using direct multi-start search.",
                           message=sol.message))
            w = None
    else:
        notes.append(t("No feasible portfolio has expected return above the risk-free rate: the convex "
                       "reformulation does not apply; Sharpe is maximised directly (non-convex)."))
    direct = _direct_ratio(cov, excess, cs) if (cross_check or w is None) else None
    if w is None:
        w = direct
        method = t("Direct multi-start SLSQP on Sharpe ratio")
        cert = t("approximate (multi-start; not certified)")
    if w is None:
        return make_result(t("Maximum Sharpe"), cs.feasible_start(), cs, mu, cov, rf, False, t("all methods failed"),
                           method, t("failed"), notes)
    res = make_result(t("Maximum Sharpe"), w, cs, mu, cov, rf, True, t("converged"), method, cert, notes)
    # invariant: no verified feasible comparison portfolio may beat it
    cands = dict(comparison or {})
    if direct is not None:
        cands[t("direct multi-start")] = direct
    for name, wc in cands.items():
        if wc is None or not cs.is_feasible(wc):
            continue
        _, _, sc = port_stats(wc, mu, cov, rf)
        if sc is not None and res.sharpe is not None and sc > res.sharpe + 1e-7:
            res.notes.append(t("'{name}' has a higher Sharpe ({better} > {current}); replaced by it and "
                               "certification downgraded.", name=name, better=f"{sc:.6f}",
                               current=f"{res.sharpe:.6f}"))
            res = make_result(t("Maximum Sharpe"), wc, cs, mu, cov, rf, True, t("replaced by better feasible point"),
                              method, t("approximate (improved by comparison)"), res.notes)
    return res


def maximum_diversification(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float) -> OptimizationResult:
    vols = np.sqrt(np.diag(cov))
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(t("Maximum diversification"), cs, mu, cov, rf, problems)
    if np.any(cs.lb < 0):
        w = _direct_ratio(cov, vols, cs)
        return make_result(t("Maximum diversification"), w if w is not None else cs.feasible_start(), cs, mu, cov, rf,
                           w is not None, t("direct"), t("Direct multi-start SLSQP"), t("approximate (not certified)"))
    sol, w = _ratio_transform(cov, vols, cs)
    ok = w is not None and sol.success
    res = make_result(t("Maximum diversification"), w if ok else cs.feasible_start(), cs, mu, cov, rf, ok, sol.message,
                      t("Charnes-Cooper transform -> convex QP"), t("global optimum (convex reformulation)"))
    if ok:
        res.notes.append(t("Diversification ratio = {value}.", value=f"{(res.weights.values @ vols) / res.volatility:.4f}"))
    return res


def target_volatility(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float, target_vol: float,
                      gmv_vol: float | None = None) -> OptimizationResult:
    name = t("Max return @ vol {target}", target=f"{target_vol:.2%}")
    if gmv_vol is not None and target_vol < gmv_vol - 1e-9:
        return _infeasible(name, cs, mu, cov, rf, [t("Target volatility is below the minimum attainable "
                                                     "({value}).", value=f"{gmv_vol:.2%}")])
    cons = _scipy_constraints(cs) + [{"type": "ineq", "fun": lambda w: np.array([target_vol ** 2 - w @ cov @ w]),
                                      "jac": lambda w: (-2 * cov @ w)[None, :]}]
    best = None
    for x0 in [cs.feasible_start()] + [cs.feasible_start(np.random.default_rng(s)) for s in range(4)]:
        sol = minimize(lambda w: -float(w @ mu), x0, jac=lambda w: -mu, method="SLSQP",
                       bounds=list(zip(cs.lb, cs.ub)), constraints=cons, options={"ftol": 1e-14, "maxiter": 2000})
        w = cs.polish(sol.x.copy())
        if sol.success and cs.is_feasible(w) and w @ cov @ w <= target_vol ** 2 * (1 + 1e-6):
            if best is None or w @ mu > best @ mu:
                best = w
    if best is None:
        return make_result(name, cs.feasible_start(), cs, mu, cov, rf, False, t("no start converged"),
                           t("SLSQP (convex)"), t("failed"))
    return make_result(name, best, cs, mu, cov, rf, True, t("converged"), t("SLSQP (convex, multi-start)"),
                       t("optimal (convex program)"))


# ---------------------------------------------------------------------------
# Maximum risk (non-convex: maximise a convex function)
# ---------------------------------------------------------------------------
def maximum_risk(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float, vertex_limit: int = 200_000,
                 n_starts: int = 40, seed: int = 1) -> OptimizationResult:
    name = t("Maximum risk")
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(name, cs, mu, cov, rf, problems)
    warn = t("Risk-seeking mathematical benchmark only -- not an investment recommendation.")
    if cs.is_simple_long_only:
        if cs.mode == "fixed_markets":
            groups = [cs.groups[m] for m in cs.markets]
            budgets = np.array([cs.market_budgets[m] for m in cs.markets])
        else:
            groups, budgets = [np.arange(cs.n)], np.array([1.0])
        n_vertices = int(np.prod([len(g) for g in groups]))
        if n_vertices <= vertex_limit:
            best_var, best_combo = -1.0, None
            it = itertools.product(*groups)
            while True:
                chunk = np.array(list(itertools.islice(it, 20000)))
                if chunk.size == 0:
                    break
                sub = cov[chunk[:, :, None], chunk[:, None, :]]          # (k, M, M)
                var = np.einsum("i,kij,j->k", budgets, sub, budgets)
                k = int(np.argmax(var))
                if var[k] > best_var:
                    best_var, best_combo = float(var[k]), chunk[k]
            w = np.zeros(cs.n)
            # repeated index cannot happen in fixed mode; in global mode there is one group
            for idx, bud in zip(best_combo, budgets):
                w[idx] += bud
            return make_result(name, w, cs, mu, cov, rf, True, t("enumerated {n} vertices", n=n_vertices),
                               t("Exhaustive vertex enumeration"), t("exact (global; all polytope vertices checked)"),
                               [warn, t("Maximum of a convex function over a polytope is attained at a vertex; "
                                        "vertices = one security per market holding the whole market budget.")])
    rng = np.random.default_rng(seed)
    f = lambda w: -float(w @ cov @ w)
    g = lambda w: -2.0 * cov @ w
    best = None
    starts = [cs.feasible_start()] + [cs.feasible_start(rng) for _ in range(n_starts - 1)]
    for x0 in starts:
        s = minimize(f, x0, jac=g, method="SLSQP", bounds=list(zip(cs.lb, cs.ub)), constraints=_scipy_constraints(cs),
                     options={"ftol": 1e-14, "maxiter": 2000})
        w = cs.polish(s.x.copy())
        if cs.is_feasible(w) and (best is None or f(w) < f(best)):
            best = w
    if best is None:
        return make_result(name, cs.feasible_start(), cs, mu, cov, rf, False, t("no start converged"),
                           t("Multi-start SLSQP"), t("failed"), [warn])
    reason = (t("bounds include caps or short positions") if not cs.is_simple_long_only
              else t("vertex count exceeds limit {limit}", limit=vertex_limit))
    return make_result(name, best, cs, mu, cov, rf, True, t("best of {n} local searches", n=n_starts),
                       t("Multi-start SLSQP (local maxima)"), t("approximate (NOT certified global)"),
                       [warn, t("Exhaustive vertex search not used: {reason}.", reason=reason)])


# ---------------------------------------------------------------------------
# Risk-based allocations
# ---------------------------------------------------------------------------
def inverse_volatility(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float) -> OptimizationResult:
    """Inside each market (or globally) weights proportional to 1/σ_i, market budgets preserved."""
    vols = np.sqrt(np.maximum(np.diag(cov), 1e-16))
    w = np.zeros(cs.n)
    groups = cs.groups.items() if cs.mode == "fixed_markets" else [("ALL", np.arange(cs.n))]
    for m, g in groups:
        target = cs.market_budgets[m] if cs.mode == "fixed_markets" else 1.0
        inv = 1.0 / vols[g]
        w[g] = target * inv / inv.sum()
    res = make_result(t("Inverse volatility"), w, cs, mu, cov, rf, True, t("closed form"), t("Closed form"),
                      t("exact (definition)"))
    return res


def risk_parity(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float) -> OptimizationResult:
    """Minimise dispersion of *percentage* Euler variance contributions (equal risk shares)."""
    name = t("Risk parity")
    problems = cs.feasibility_problems()
    if problems:
        return _infeasible(name, cs, mu, cov, rf, problems)

    n = cs.n

    def risk_shares(w: np.ndarray) -> np.ndarray | None:
        sw = cov @ w
        variance = float(w @ sw)
        if not np.isfinite(variance) or variance <= 1e-16:
            return None
        return (w * sw) / variance

    def objective(w: np.ndarray) -> float:
        shares = risk_shares(w)
        if shares is None or not np.isfinite(shares).all():
            return 1e6
        deviation = shares - 1.0 / n
        return float(deviation @ deviation)

    def gradient(w: np.ndarray) -> np.ndarray:
        sw = cov @ w
        variance = float(w @ sw)
        if not np.isfinite(variance) or variance <= 1e-16:
            return np.zeros(n)
        rc = w * sw
        deviation = rc / variance - 1.0 / n
        # J_rc[i,k] = d(w_i (Σw)_i)/dw_k. Apply the quotient rule
        # to each risk share RC_i / (w'Σw), whose denominator gradient is 2Σw.
        jac_rc = np.diag(sw) + w[:, None] * cov
        jac_share = jac_rc / variance - np.outer(rc, 2.0 * sw) / variance**2
        return 2.0 * jac_share.T @ deviation

    # Inverse-volatility is a useful starting point, but it may violate stock caps.
    # Always retain a constraint-feasible start and use deterministic multi-starts.
    starts = [cs.feasible_start()]
    inv_vol = inverse_volatility(mu, cov, cs, rf).weights.values
    if cs.is_feasible(inv_vol):
        starts.append(inv_vol)
    rng = np.random.default_rng(17)
    starts.extend(cs.feasible_start(rng) for _ in range(7))

    candidates: list[tuple[float, np.ndarray, object]] = []
    for x0 in starts:
        sol = minimize(objective, x0, jac=gradient, method="SLSQP",
                       bounds=list(zip(cs.lb, cs.ub)), constraints=_scipy_constraints(cs),
                       options={"ftol": 1e-12, "maxiter": 3000})
        w = cs.polish(np.asarray(sol.x, dtype=float).copy())
        if (bool(sol.success) and np.isfinite(w).all() and cs.is_feasible(w)
                and risk_shares(w) is not None):
            candidates.append((objective(w), w, sol))

    if not candidates:
        fallback = cs.feasible_start()
        return make_result(name, fallback, cs, mu, cov, rf, False,
                           t("Risk-parity optimisation failed; a feasible starting portfolio is shown only as fallback."),
                           t("SLSQP (equal percentage risk contributions, multi-start)"), t("failed"),
                           [t("Fallback weights are not a risk-parity solution and must not be interpreted as one.")])

    value, best, sol = min(candidates, key=lambda item: item[0])
    res = make_result(name, best, cs, mu, cov, rf, True, sol.message,
                      t("SLSQP (equal percentage risk contributions, multi-start)"),
                      t("local optimum (non-convex)"),
                      [t("Squared dispersion of percentage variance contributions: {value}.", value=f"{value:.3e}")])
    return res


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------
def equal_weight(mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet, rf: float) -> OptimizationResult:
    """Equal weights inside each market, market budgets preserved (in both constraint modes)."""
    w = np.zeros(cs.n)
    for m, g in cs.groups.items():
        w[g] = cs.market_budgets[m] / len(g)
    res = make_result(t("Equal weight (within markets)"), w, cs, mu, cov, rf, True, t("closed form"), t("Closed form"),
                      t("exact (definition)"), polish=False)
    if not res.feasible:
        res.notes.append(t("Equal weighting violates the configured per-stock bounds."))
    return res


def evaluate_given(name: str, w: np.ndarray, mu: np.ndarray, cov: np.ndarray, cs: ConstraintSet,
                   rf: float) -> OptimizationResult:
    res = make_result(name, np.asarray(w, float), cs, mu, cov, rf, True, t("user-specified weights"), t("Evaluation only"),
                      t("n/a (not optimised)"), polish=False)
    if not res.feasible:
        res.notes.append(t("User weights violate the current optimisation bounds (e.g. a stock cap); shown for "
                           "comparison only."))
    return res


def _infeasible(name: str, cs: ConstraintSet, mu, cov, rf, problems: list[str]) -> OptimizationResult:
    w = np.full(cs.n, np.nan)
    return OptimizationResult(name, pd.Series(w, index=cs.tickers), float("nan"), float("nan"), None, False, False,
                              t("infeasible") + ": " + " ".join(problems), t("pre-check"), t("infeasible"), {}, problems)


def run_all(mu: pd.Series, cov: pd.DataFrame, cs: ConstraintSet, rf: float, user_w: pd.Series,
            scenario_returns: pd.DataFrame | None = None, vertex_limit: int = 200_000) -> dict[str, OptimizationResult]:
    m, S = mu.reindex(cs.tickers).values, cov.reindex(index=cs.tickers, columns=cs.tickers).values
    uw = user_w.reindex(cs.tickers).fillna(0.0).values
    out: dict[str, OptimizationResult] = {}
    out["user"] = evaluate_given(t("User portfolio"), uw, m, S, cs, rf)
    out["equal_weight"] = equal_weight(m, S, cs, rf)
    out["min_variance"] = minimum_variance(m, S, cs, rf, extra_starts=[uw if cs.is_feasible(uw) else None])
    out["max_return"] = maximum_return(m, S, cs, rf)
    comps = {k: v.weights.values for k, v in out.items() if v.ok}
    out["max_sharpe"] = maximum_sharpe(m, S, cs, rf, comps)
    out["max_risk"] = maximum_risk(m, S, cs, rf, vertex_limit)
    out["max_diversification"] = maximum_diversification(m, S, cs, rf)
    if scenario_returns is not None and len(scenario_returns) > 20:
        out["min_cvar"] = minimum_cvar(scenario_returns.reindex(columns=cs.tickers).values, m, S, cs, rf)
    # invariant check: min variance must not exceed any verified feasible portfolio's variance
    mv = out["min_variance"]
    if mv.ok:
        for k, r in out.items():
            if k != "min_variance" and r.ok and r.volatility < mv.volatility - 1e-7:
                mv.notes.append(t("Invariant violated: '{name}' has lower volatility; certification downgraded.",
                                  name=r.name))
                mv.certification = t("not certified")
    return out
