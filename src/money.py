"""Money amounts in the base currency: what a given capital would have become.

All amounts follow the same convention as the statistics: a constant-weight portfolio (rebalanced every
period) whose period return is r_p,t = Σ_i w_i r_i,t, compounded from an initial capital K:

    W_0 = K,   W_t = W_{t-1} (1 + r_p,t)            (value after period t)
    gain = W_T - K,    best/worst period in money = W_{t-1} r_p,t
    contribution of security i = Σ_t W_{t-1} w_i r_i,t     (sums exactly to W_T - K)

Drawdown in money = peak value - lowest later value.  VaR/CVaR in money apply the historical percentage to
the CURRENT value (an approximation: the percentage is per period).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def wealth(r: pd.Series, capital: float) -> pd.Series:
    """Portfolio value after each period (the initial capital is NOT included as a row)."""
    return capital * (1.0 + r.fillna(0.0)).cumprod()


def wealth_with_start(r: pd.Series, capital: float, start_date=None) -> pd.Series:
    w = wealth(r, capital)
    if len(r) == 0:
        return w
    d0 = start_date if start_date is not None else r.index[0] - (r.index[1] - r.index[0] if len(r) > 1
                                                                  else pd.Timedelta(days=1))
    return pd.concat([pd.Series([capital], index=[pd.Timestamp(d0)]), w])


def money_summary(r: pd.Series, capital: float) -> dict:
    r = r.dropna()
    if r.empty:
        return {"initial": capital, "final": capital, "gain": 0.0, "total_return": 0.0}
    w = wealth(r, capital)
    prev = w.shift(1).fillna(capital)
    pnl = prev * r
    full = pd.concat([pd.Series([capital]), w.reset_index(drop=True)])
    peak = full.cummax()
    dd = full - peak
    trough_pos = int(dd.values.argmin())
    peak_pos = int(full.iloc[:trough_pos + 1].values.argmax())
    dates = [None] + list(w.index)
    return {"initial": float(capital), "final": float(w.iloc[-1]), "gain": float(w.iloc[-1] - capital),
            "total_return": float(w.iloc[-1] / capital - 1), "peak_value": float(full.max()),
            "best_period_gain": float(pnl.max()), "best_period_date": pnl.idxmax(),
            "worst_period_loss": float(pnl.min()), "worst_period_date": pnl.idxmin(),
            "max_drawdown_money": float(dd.min()), "drawdown_peak_date": dates[peak_pos],
            "drawdown_trough_date": dates[trough_pos], "positive_periods_gain": float(pnl[pnl > 0].sum()),
            "negative_periods_loss": float(pnl[pnl < 0].sum())}


def contributions(asset_returns: pd.DataFrame, weights: pd.Series, capital: float) -> pd.Series:
    """Money gained (lost) by each security in a constant-weight portfolio; sums to the total gain."""
    w = weights.reindex(asset_returns.columns).fillna(0.0)
    rp = asset_returns.fillna(0.0) @ w.values
    prev = capital * (1.0 + rp).cumprod().shift(1).fillna(1.0)
    prev.iloc[0] = capital
    contrib = asset_returns.fillna(0.0).mul(w.values, axis=1).mul(prev, axis=0).sum()
    return contrib


def money(v: float | None, currency: str, digits: int = 0, sign: bool = False) -> str:
    """'1,234,567 MXN' (thousands separators, no decimals by default)."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "–"
    fmt = f"{{:{'+' if sign else ''},.{digits}f}}"
    return f"{fmt.format(v)} {currency}"


def compact(v: float | None, currency: str = "", sign: bool = False) -> str:
    """Short money label: 1.2 M, 845 k."""
    if v is None or not np.isfinite(v):
        return "–"
    a = abs(v)
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    def trim(x: str) -> str:
        return x.rstrip("0").rstrip(".") if "." in x else x
    if a >= 1e9:
        txt = trim(f"{a / 1e9:.2f}") + " B"
    elif a >= 1e6:
        txt = trim(f"{a / 1e6:.2f}") + " M"
    elif a >= 1e4:
        txt = trim(f"{a / 1e3:.1f}") + " k"
    else:
        txt = f"{a:,.0f}"
    return f"{s}{txt}{(' ' + currency) if currency else ''}"
