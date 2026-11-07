"""Short histories (IPOs, new listings): complete the missing early returns with a factor model.

Why: a stock listed 4 months ago blocks every horizon of the original portfolio (strict mode). Cutting every
other holding to 4 months (available history) throws away years of real data and makes every estimate noisy;
leaving the stock out (common universe) changes the portfolio. The standard answer in the literature for
histories of unequal length is to keep every real observation and fill only the missing early part of the
short series from its relationship with the long ones (Stambaugh 1997, "Analyzing investments whose histories
differ in length"; Page 2013; Jiang and Martin 2016, "Turning long and short return histories into equal
histories: a better way to backfill returns").

Method, for a security with S real returns inside a window of T periods (S < T):

1. Factors are portfolios that exist over the whole window, in this order of preference: the index of the
   security's market (when stored), the average of the other holdings of its market, and the rest of the
   portfolio (the other holdings with your weights). k = min(3, S // 60, available) factors, at least 1.
2. Excess-return regression on the S real periods (OLS):   y - rf = a + b'(F - rf) + e.
3. Each missing period is   y~_t = rf + b'(F_t - rf) + e*_t,   with e* drawn in blocks of 5 periods from the
   real residuals (fixed seed, so results are reproducible) and centred to mean zero, so the residuals add
   the security's own risk but no return. The abnormal return ``a`` is NOT carried back: before listing the
   security earns only what its exposure to the factors implies.

Consequences:
* every other holding keeps 100 % real data, so its statistics are exactly the ones it has without the IPO;
* the IPO's own real returns are never changed;
* the IPO's mean is pulled towards its factor-implied mean in proportion to the reconstructed share (a hot
  first quarter is not annualized over the whole horizon), while its volatility and correlations come from
  its real betas and real residual risk.
Everything reconstructed is labelled with its share, factors, betas and R².
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MIN_OBS_PER_FACTOR = 60
MAX_FACTORS = 3
BLOCK = 5


@dataclass
class Reconstruction:
    ticker: str
    first_real: pd.Timestamp | None      # date of the first real return used
    n_real: int
    n_filled: int
    share_filled: float                  # reconstructed periods / all periods of the window
    factors: list[str] = field(default_factory=list)
    betas: dict[str, float] = field(default_factory=dict)
    alpha_annual: float = 0.0            # estimated on the real part, NOT carried into the filled part
    r2: float = 0.0
    resid_vol_annual: float = 0.0
    real_mean_annual: float = 0.0
    filled_mean_annual: float = 0.0

    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "first_real": self.first_real, "n_real": self.n_real,
                "n_filled": self.n_filled, "share_filled": self.share_filled, "factors": ", ".join(self.factors),
                "betas": ", ".join(f"{k} {v:.2f}" for k, v in self.betas.items()), "r2": self.r2,
                "alpha_annual": self.alpha_annual, "resid_vol_annual": self.resid_vol_annual,
                "real_mean_annual": self.real_mean_annual, "filled_mean_annual": self.filled_mean_annual}


def candidate_factors(rets: pd.DataFrame, ticker: str, long: list[str], market_of: dict[str, str],
                      weights: pd.Series, index_returns: dict[str, pd.Series] | None = None,
                      index_names: dict[str, str] | None = None) -> pd.DataFrame:
    """Factor portfolios for ``ticker`` (columns in order of preference), complete over ``rets.index``."""
    cols: dict[str, pd.Series] = {}
    mkt = market_of.get(ticker)
    idx = (index_returns or {}).get(mkt) if mkt else None
    if idx is not None:
        idx = idx.reindex(rets.index)
        if idx.notna().all():
            cols[(index_names or {}).get(mkt, f"index {mkt}")] = idx
    same = [tk for tk in long if market_of.get(tk) == mkt]
    if same:
        cols[f"avg:{mkt}"] = rets[same].mean(axis=1)
    w = weights.reindex(long).fillna(0.0).clip(lower=0)
    w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(long), index=long)
    rest = rets[long] @ w.values
    if not any(np.corrcoef(rest.values, v.values)[0, 1] > 0.999 for v in cols.values() if v.std() > 0):
        cols["rest"] = rest
    return pd.DataFrame(cols, index=rets.index)


def _seed(ticker: str, salt: str) -> int:
    return zlib.crc32(f"{ticker}|{salt}".encode())


def reconstruct(y: pd.Series, factors: pd.DataFrame, rf_period: float, periods_per_year: int,
                salt: str = "") -> tuple[pd.Series, Reconstruction]:
    """Fill the leading missing values of ``y`` (see module docstring). Real values are returned unchanged."""
    real = y.notna()
    n_real = int(real.sum())
    tk = str(y.name)
    first = y.index[real.values.argmax()] if n_real else None
    missing = (~real) & (y.index < first) if first is not None else ~real
    k = max(1, min(MAX_FACTORS, n_real // MIN_OBS_PER_FACTOR, factors.shape[1]))
    F = factors.iloc[:, :k]
    names = list(F.columns)
    Y = (y[real] - rf_period).values
    X = np.column_stack([np.ones(n_real), (F[real] - rf_period).values])
    coef, *_ = np.linalg.lstsq(X, Y, rcond=None)
    a, b = float(coef[0]), coef[1:]
    fitted = X @ coef
    resid = Y - fitted
    ss_tot = float(((Y - Y.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    n_fill = int(missing.sum())
    out = y.copy()
    filled_mean = 0.0
    if n_fill:
        rng = np.random.default_rng(_seed(tk, salt))
        blk = max(1, min(BLOCK, n_real))
        n_blocks = int(np.ceil(n_fill / blk))
        starts = rng.integers(0, n_real, size=n_blocks)
        e_star = resid[(starts[:, None] + np.arange(blk)[None, :]).ravel() % n_real][:n_fill]
        if n_fill > 1:  # centred: residuals add risk, never return (no sampling luck in the mean)
            e_star = e_star - e_star.mean()
        Fm = (F[missing] - rf_period).values
        vals = rf_period + Fm @ b + e_star
        out[missing] = vals
        filled_mean = float(np.mean(vals)) * periods_per_year
    info = Reconstruction(tk, first, n_real, n_fill, n_fill / max(len(y), 1), names,
                          {nm: float(bv) for nm, bv in zip(names, b)}, a * periods_per_year, r2,
                          float(np.std(resid, ddof=1) * np.sqrt(periods_per_year)) if n_real > 2 else 0.0,
                          float(y[real].mean()) * periods_per_year, filled_mean)
    return out, info


def reconstruct_frame(rets: pd.DataFrame, short: list[str], long: list[str], market_of: dict[str, str],
                      weights: pd.Series, rf_period: float, periods_per_year: int,
                      index_returns: dict[str, pd.Series] | None = None,
                      index_names: dict[str, str] | None = None, salt: str = "",
                      fit_mask: pd.Series | None = None) -> tuple[pd.DataFrame, dict[str, Reconstruction]]:
    """Complete every ``short`` column of ``rets`` (``long`` columns must have no missing values).

    ``fit_mask`` restricts the periods used to estimate the model (the backtest passes "up to the end of
    training" so the reconstruction never uses information from the test period)."""
    out = rets.copy()
    info: dict[str, Reconstruction] = {}
    for tk in short:
        F = candidate_factors(rets, tk, long, market_of, weights, index_returns, index_names)
        y = rets[tk]
        if fit_mask is not None:
            y_fit = y.where(fit_mask.reindex(y.index).fillna(False).astype(bool))
            filled, rec = reconstruct(y_fit, F, rf_period, periods_per_year, salt)
            lead = y.index < (rec.first_real if rec.first_real is not None else y.index[-1])
            out[tk] = y.where(~lead, filled)
        else:
            out[tk], rec = reconstruct(y, F, rf_period, periods_per_year, salt)
        info[tk] = rec
    return out, info
