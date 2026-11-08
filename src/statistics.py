"""Estimators (expected returns, covariance) and portfolio / asset risk statistics.

Risk-free convention
--------------------
The user enters an EFFECTIVE annual rate R_f (default 6.5 % in the base currency,
an assumption, not a market quote).  Per-period rate: r_f = (1 + R_f)^(1/n) - 1.
The annual rate used inside Markowitz formulas is n * r_f, so that

    (mu_p - n r_f) / sigma_p = sqrt(n) * mean(r_t - r_f) / sd(r_t)

i.e. the optimizer's Sharpe ratio and the historical annualised Sharpe agree exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

from .i18n import N_, t
from .returns import cagr, cumulative_return, wealth_index


# ---------------------------------------------------------------------------
# Risk-free helpers
# ---------------------------------------------------------------------------
def rf_per_period(rf_annual_effective: float, periods_per_year: int) -> float:
    return (1.0 + rf_annual_effective) ** (1.0 / periods_per_year) - 1.0


def rf_markowitz(rf_annual_effective: float, periods_per_year: int) -> float:
    return periods_per_year * rf_per_period(rf_annual_effective, periods_per_year)


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------
def ewma_weights(n: int, lam: float) -> np.ndarray:
    w = lam ** np.arange(n - 1, -1, -1, dtype=float)
    return w / w.sum()


def estimate_mu(returns: pd.DataFrame, method: str, periods_per_year: int, lam: float = 0.97,
                user: dict[str, float] | None = None) -> pd.Series:
    """Annualised expected-return vector (decimal)."""
    if method == "arithmetic":
        return returns.mean() * periods_per_year
    if method == "geometric":
        n = len(returns)
        return (1.0 + returns).prod() ** (periods_per_year / n) - 1.0
    if method == "ewma":
        w = ewma_weights(len(returns), lam)
        return pd.Series(w @ returns.values, index=returns.columns) * periods_per_year
    if method == "user":
        user = user or {}
        missing = [c for c in returns.columns if c not in user]
        if missing:
            raise ValueError(t("User-defined expected returns missing for: {tickers}", tickers=", ".join(missing)))
        return pd.Series({c: float(user[c]) for c in returns.columns})
    raise ValueError(f"Unknown expected-return estimator '{method}'")


def ledoit_wolf(X: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit & Wolf (2004) shrinkage toward a scaled identity (MLE scaling 1/T).

    Returns (shrunk covariance, shrinkage intensity in [0, 1]).
    """
    T, p = X.shape
    Xc = X - X.mean(axis=0)
    S = Xc.T @ Xc / T
    mu = np.trace(S) / p
    X2 = Xc ** 2
    beta_ = np.sum(X2.T @ X2) / T
    delta_ = np.sum(S ** 2)
    beta = (beta_ / T - delta_ / T)
    delta = np.sum((S - mu * np.eye(p)) ** 2)
    beta = min(beta, delta)
    shrink = 0.0 if delta == 0 else beta / delta
    return (1 - shrink) * S + shrink * mu * np.eye(p), float(shrink)


def estimate_cov(returns: pd.DataFrame, method: str, periods_per_year: int, lam: float = 0.97
                 ) -> tuple[pd.DataFrame, dict]:
    T, p = returns.shape
    info: dict = {"method": method, "n_obs": T, "n_assets": p, "shrinkage": None, "regularized": False}
    if T < 2:
        raise ValueError("At least two return observations are required to estimate a covariance matrix.")
    X = returns.values
    if method == "sample":
        S = np.cov(X, rowvar=False, ddof=1)
    elif method == "ledoit_wolf":
        S, delta = ledoit_wolf(X)
        info.update(shrinkage=delta, regularized=True)
    elif method == "ewma":
        w = ewma_weights(T, lam)
        m = w @ X
        Xc = X - m
        S = (Xc * w[:, None]).T @ Xc / (1.0 - np.sum(w ** 2))  # bias-corrected weighted covariance
        info["lambda"] = lam
    else:
        raise ValueError(f"Unknown covariance estimator '{method}'")
    S = np.atleast_2d(S) * periods_per_year
    return pd.DataFrame(S, index=returns.columns, columns=returns.columns), info


def check_covariance(cov: pd.DataFrame, n_obs: int) -> dict:
    A = cov.values
    sym_err = float(np.max(np.abs(A - A.T))) if A.size else 0.0
    eig = np.linalg.eigvalsh((A + A.T) / 2)
    max_e, min_e = float(eig.max()), float(eig.min())
    tol = 1e-10 * max(max_e, 1e-16) * A.shape[0]
    cond = float(max_e / min_e) if min_e > tol else float("inf")
    warnings: list[str] = []
    if sym_err > 1e-12 * max(max_e, 1.0):
        warnings.append(t("Covariance matrix is not symmetric (max asymmetry {value}).", value=f"{sym_err:.2e}"))
    if min_e < -tol:
        warnings.append(t("Covariance matrix is NOT positive semidefinite (min eigenvalue {value}).",
                          value=f"{min_e:.3e}"))
    if not np.isfinite(cond):
        warnings.append(t("Covariance matrix is singular (zero eigenvalue): the minimum-variance solution may be "
                          "non-unique."))
    elif cond > 1e6:
        warnings.append(t("Covariance matrix is poorly conditioned (condition number {value}).",
                          value=f"{cond:.2e}"))
    p = A.shape[0]
    if n_obs <= p:
        warnings.append(t("Only {n} observations for {p} assets: the sample covariance is singular. Use "
                          "Ledoit-Wolf shrinkage or fewer assets.", n=n_obs, p=p))
    elif n_obs < 10 * p:
        warnings.append(t("Observations ({n}) are fewer than 10x the number of assets ({p}); estimates are "
                          "noisy -- consider Ledoit-Wolf shrinkage.", n=n_obs, p=p))
    return {"symmetric_error": sym_err, "min_eigenvalue": min_e, "max_eigenvalue": max_e,
            "condition_number": cond, "psd": min_e >= -tol, "warnings": warnings}


def cov_to_corr(cov: pd.DataFrame) -> pd.DataFrame:
    d = np.sqrt(np.diag(cov.values))
    with np.errstate(divide="ignore", invalid="ignore"):
        c = cov.values / np.outer(d, d)
    return pd.DataFrame(c, index=cov.index, columns=cov.columns)


# ---------------------------------------------------------------------------
# Drawdowns & tail risk
# ---------------------------------------------------------------------------
def drawdown_series(r: pd.Series) -> pd.Series:
    w = wealth_index(r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], w.values]))[1:]
    return pd.Series(w.values / peak - 1.0, index=r.index)


def max_drawdown(r: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    """Return the maximum drawdown and its peak/trough dates.

    The initial wealth (1.0) is a real peak even though it is not represented by
    a return observation. When that initial value remains the peak, report the
    date immediately before the first return rather than mislabelling the
    first return date as the peak.
    """
    r = r.dropna()
    dd = drawdown_series(r)
    if dd.empty:
        return float("nan"), None, None
    trough = dd.idxmin()
    w = wealth_index(r)
    if dd.min() >= 0:
        peak_date = trough
    else:
        prior = w.loc[:trough]
        if prior.empty or float(prior.max()) <= 1.0:
            start_date = (r.index[0] - (r.index[1] - r.index[0])) if len(r) > 1 else r.index[0] - pd.Timedelta(days=1)
            peak_date = start_date
        else:
            peak_date = prior.idxmax()
    return float(dd.min()), peak_date, trough


def historical_var_cvar(r: pd.Series, level: float) -> tuple[float, float]:
    """Positive numbers = losses. VaR_a = -q_{1-a}; CVaR_a = -E[r | r <= q_{1-a}]."""
    q = float(np.quantile(r.values, 1 - level))
    tail = r.values[r.values <= q]
    return -q, -float(tail.mean()) if len(tail) else float("nan")


def rolling_period_extremes(r: pd.Series, window: int) -> dict:
    if len(r) < window:
        return {"window": window, "best": float("nan"), "best_end": None, "worst": float("nan"), "worst_end": None}
    roll = np.exp(np.log1p(r).rolling(window).sum()) - 1.0
    return {"window": window, "best": float(roll.max()), "best_end": roll.idxmax(), "worst": float(roll.min()),
            "worst_end": roll.idxmin()}


# ---------------------------------------------------------------------------
# Portfolio-level statistics
# ---------------------------------------------------------------------------
def portfolio_statistics(r: pd.Series, rf_annual: float, periods_per_year: int,
                         benchmark: pd.Series | None = None) -> dict:
    n = periods_per_year
    rf_d = rf_per_period(rf_annual, n)
    r = r.dropna()
    excess = r - rf_d
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    downside = np.minimum(excess.values, 0.0)
    dd_dev = float(np.sqrt(np.mean(downside ** 2)))
    mdd, peak, trough = max_drawdown(r)
    start_value_date = r.index[0]
    total = cumulative_return(r)
    # CAGR uses actual elapsed time; the first return covers (prev date -> first date), so the
    # elapsed span is measured from one period before the first return date.
    span_start = r.index[0] - (r.index[1] - r.index[0]) if len(r) > 1 else r.index[0]
    g = cagr(1.0, 1.0 + total, span_start, r.index[-1])
    var95, cvar95 = historical_var_cvar(r, 0.95)
    var99, cvar99 = historical_var_cvar(r, 0.99)
    win = 21 if n == 252 else 4
    ext = rolling_period_extremes(r, win)
    jb = sps.jarque_bera(r.values) if len(r) > 7 else None
    out = {
        "n_obs": len(r), "start": r.index[0], "end": r.index[-1],
        "mean_period": mean, "sd_period": sd,
        "annual_arithmetic_return": mean * n, "annual_geometric_return_cagr": g,
        "annual_volatility": sd * np.sqrt(n),
        "sharpe_period": float(excess.mean() / sd) if sd > 0 else float("nan"),
        "sharpe_annual": float(excess.mean() / sd * np.sqrt(n)) if sd > 0 else float("nan"),
        "sortino_annual": float(excess.mean() * n / (dd_dev * np.sqrt(n))) if dd_dev > 0 else float("nan"),
        "downside_deviation_annual": dd_dev * np.sqrt(n),
        "max_drawdown": mdd, "max_drawdown_peak": peak, "max_drawdown_trough": trough,
        "calmar": float(g / abs(mdd)) if mdd < 0 else float("nan"),
        "best_period_return": float(r.max()), "best_period_date": r.idxmax(),
        "worst_period_return": float(r.min()), "worst_period_date": r.idxmin(),
        f"best_rolling_{win}p": ext["best"], f"best_rolling_{win}p_end": ext["best_end"],
        f"worst_rolling_{win}p": ext["worst"], f"worst_rolling_{win}p_end": ext["worst_end"],
        "skewness": float(sps.skew(r.values, bias=False)) if len(r) > 2 else float("nan"),
        "excess_kurtosis": float(sps.kurtosis(r.values, fisher=True, bias=False)) if len(r) > 3 else float("nan"),
        "jarque_bera_stat": float(jb.statistic) if jb is not None else float("nan"),
        "jarque_bera_pvalue": float(jb.pvalue) if jb is not None else float("nan"),
        "var_95": var95, "cvar_95": cvar95, "var_99": var99, "cvar_99": cvar99,
        "cumulative_return": total,
        "positive_frequency": float((r > 0).mean()), "negative_frequency": float((r < 0).mean()),
        "zero_frequency": float((r == 0).mean()),
        "rf_annual_effective": rf_annual, "rf_period": rf_d,
    }
    if benchmark is not None:
        out.update(benchmark_relative(r, benchmark, n, rf_d))
    return out


def benchmark_relative(r: pd.Series, b: pd.Series, n: int, rf_period: float = 0.0) -> dict:
    """Benchmark-relative statistics; alpha is the Jensen regression intercept.

    Returns are paired on common dates. Beta is estimated from raw-return
    covariance (equivalently excess-return covariance with a constant rf).
    """
    df = pd.concat([r.rename("p"), b.rename("b")], axis=1).dropna()
    if len(df) < 10:
        return {"benchmark_obs": len(df)}
    active = df["p"] - df["b"]
    var_b = df["b"].var(ddof=1)
    beta = float(df["p"].cov(df["b"]) / var_b) if var_b > 0 else float("nan")
    te = float(active.std(ddof=1) * np.sqrt(n))
    alpha = ((df["p"] - rf_period) - beta * (df["b"] - rf_period)).mean() * n
    return {"benchmark_obs": len(df), "beta": beta,
            "alpha_annual_arith": float(alpha),
            "benchmark_annual_return": float(df["b"].mean() * n),
            "benchmark_cumulative_return": cumulative_return(df["b"]),
            "active_return_annual": float(active.mean() * n), "tracking_error": te,
            "information_ratio": float(active.mean() * n / te) if te > 0 else float("nan"),
            "correlation_to_benchmark": float(df["p"].corr(df["b"]))}


# ---------------------------------------------------------------------------
# Asset-level statistics & risk decomposition
# ---------------------------------------------------------------------------
def risk_decomposition(w: pd.Series, cov: pd.DataFrame) -> pd.DataFrame:
    """Euler decomposition of volatility: sigma = sum_i w_i (Sigma w)_i / sigma."""
    wv = w.reindex(cov.index).values
    sw = cov.values @ wv
    var = float(wv @ sw)
    sigma = np.sqrt(max(var, 0.0))
    mcr = sw / sigma if sigma > 0 else np.full_like(sw, np.nan)
    ccr = wv * mcr
    return pd.DataFrame({"weight": wv, "variance_contribution": wv * sw,
                         "variance_contribution_pct": wv * sw / var if var > 0 else np.nan,
                         "marginal_vol_contribution": mcr, "component_vol_contribution": ccr,
                         "component_vol_pct": ccr / sigma if sigma > 0 else np.nan}, index=cov.index)


def asset_statistics(returns: pd.DataFrame, weights: pd.Series, cov: pd.DataFrame, mu: pd.Series,
                     rf_annual: float, periods_per_year: int, meta: pd.DataFrame,
                     benchmark: pd.Series | None = None) -> pd.DataFrame:
    n = periods_per_year
    rf_d = rf_per_period(rf_annual, n)
    rows = []
    rd = risk_decomposition(weights, cov)
    for tk in returns.columns:
        r = returns[tk]
        sd = r.std(ddof=1)
        mdd, _, _ = max_drawdown(r)
        span_start = (r.index[0] - (r.index[1] - r.index[0])) if len(r) > 1 else r.index[0] - pd.Timedelta(days=1)
        row = {"ticker": tk, "annual_arith_return": r.mean() * n,
               "annual_cagr": cagr(1.0, 1 + cumulative_return(r), span_start, r.index[-1]),
               "annual_volatility": sd * np.sqrt(n),
               "sharpe": (r.mean() - rf_d) / sd * np.sqrt(n) if sd > 0 else np.nan,
               "max_drawdown": mdd, "expected_return_used": mu.get(tk, np.nan),
               "weight": weights.get(tk, 0.0),
               "contribution_to_expected_return": weights.get(tk, 0.0) * mu.get(tk, np.nan),
               "marginal_vol_contribution": rd.loc[tk, "marginal_vol_contribution"],
               "component_vol_contribution": rd.loc[tk, "component_vol_contribution"],
               "component_vol_pct": rd.loc[tk, "component_vol_pct"], "n_obs": int(r.notna().sum())}
        if benchmark is not None:
            df = pd.concat([r, benchmark], axis=1).dropna()
            vb = df.iloc[:, 1].var(ddof=1)
            row["beta"] = df.iloc[:, 0].cov(df.iloc[:, 1]) / vb if len(df) > 10 and vb > 0 else np.nan
        rows.append(row)
    out = pd.DataFrame(rows).set_index("ticker")
    if meta is not None and not meta.empty:
        out = out.join(meta[[c for c in ("market_id", "currency", "security_name") if c in meta.columns]])
    return out


def concentration(weights: pd.Series, market_of: dict[str, str], currency_of: dict[str, str],
                  cov: pd.DataFrame) -> dict:
    w = weights.reindex(cov.index).fillna(0.0)
    hhi = float(np.sum(w.values ** 2))
    by_market = w.groupby(lambda t: market_of.get(t, "?")).sum()
    by_ccy = w.groupby(lambda t: currency_of.get(t, "?")).sum()
    vols = np.sqrt(np.diag(cov.values))
    sig = float(np.sqrt(max(w.values @ cov.values @ w.values, 0.0)))
    return {"hhi_security": hhi, "effective_n_securities": 1 / hhi if hhi > 0 else float("nan"),
            "hhi_market": float(np.sum(by_market.values ** 2)),
            "effective_n_markets": 1 / float(np.sum(by_market.values ** 2)),
            "max_security_weight": float(w.max()), "weights_by_market": by_market.to_dict(),
            "weights_by_currency": by_ccy.to_dict(),
            "diversification_ratio": float(w.values @ vols / sig) if sig > 0 else float("nan")}


# ---------------------------------------------------------------------------
# Reliability: bootstrap, Monte Carlo
# ---------------------------------------------------------------------------
def block_bootstrap_ci(r: pd.Series, rf_annual: float, n: int, n_boot: int = 1000, block: int = 21,
                       level: float = 0.95, seed: int = 7) -> pd.DataFrame:
    """Circular block bootstrap CIs (preserves short-range dependence) for key annual statistics."""
    rng = np.random.default_rng(seed)
    x = r.values
    T = len(x)
    rf_d = rf_per_period(rf_annual, n)
    k = int(np.ceil(T / block))
    res = np.empty((n_boot, 3))
    for b in range(n_boot):
        starts = rng.integers(0, T, size=k)
        idx = (starts[:, None] + np.arange(block)[None, :]).ravel()[:T] % T
        s = x[idx]
        sd = s.std(ddof=1)
        res[b] = (s.mean() * n, sd * np.sqrt(n), (s.mean() - rf_d) / sd * np.sqrt(n) if sd > 0 else np.nan)
    a = (1 - level) / 2
    names = ["annual_arith_return", "annual_volatility", "sharpe_annual"]
    point = [x.mean() * n, x.std(ddof=1) * np.sqrt(n), (x.mean() - rf_d) / x.std(ddof=1) * np.sqrt(n)]
    return pd.DataFrame({"estimate": point, "ci_low": np.nanquantile(res, a, axis=0),
                         "ci_high": np.nanquantile(res, 1 - a, axis=0)}, index=names)


def monte_carlo_terminal(mu: pd.Series, cov: pd.DataFrame, w: pd.Series, periods: int, periods_per_year: int,
                         n_paths: int = 5000, seed: int = 11) -> np.ndarray:
    """Terminal wealth (start = 1) of a constant-weight portfolio under i.i.d. multivariate normal
    per-period simple returns with mean mu/n and covariance Sigma/n.  Explicit, simplistic assumption."""
    rng = np.random.default_rng(seed)
    n = periods_per_year
    m = (w.values @ mu.values) / n
    s = np.sqrt(max(w.values @ cov.values @ w.values, 0.0) / n)
    paths = rng.normal(m, s, size=(n_paths, periods))
    return np.prod(1 + paths, axis=1)


CRISIS_PERIODS = {
    N_("2015-16 China / EM sell-off"): ("2015-08-10", "2016-02-11"),
    N_("2018 Q4 sell-off"): ("2018-10-01", "2018-12-24"),
    N_("COVID-19 crash"): ("2020-02-19", "2020-03-23"),
    N_("2022 inflation / rate shock"): ("2022-01-03", "2022-10-12"),
}


def crisis_performance(r: pd.Series) -> pd.DataFrame:
    rows = []
    for name, (a, b) in CRISIS_PERIODS.items():
        seg = r.loc[a:b]
        if len(seg) < 3:
            rows.append({"period": t(name), "from": a, "to": b, "n_obs": len(seg), "return": np.nan,
                         "max_drawdown": np.nan})
            continue
        rows.append({"period": t(name), "from": a, "to": b, "n_obs": len(seg), "return": cumulative_return(seg),
                     "max_drawdown": max_drawdown(seg)[0]})
    return pd.DataFrame(rows)
