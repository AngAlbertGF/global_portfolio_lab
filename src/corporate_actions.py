"""Stock splits, reverse splits and dividends: detection and repair of the price series.

Why this exists
---------------
Yahoo adjusts the whole price history when a split happens, but (verified on real data,
Oct 2026) the result is not always clean:

* NEXT FUNDS Nikkei 225 ETF (1321.T), 100:1 split on 2026-10-05: the first two post-split
  sessions were divided by 100 a second time (7.28 instead of ~728), and the dividends paid
  before the split were left on the pre-split basis (723 JPY instead of 7.23 JPY), which made
  Yahoo's "Adj Close" NEGATIVE for years of history.
* An incremental download stores history *before* a split; after the split Yahoo's new rows
  are on the post-split basis, so the stored series jumps by the split ratio (e.g. -99%).

What is done (never inventing prices)
-------------------------------------
1. ``repair_scale_errors``: a run of rows whose level is off by a split factor (or 100x,
   a units error) relative to the rows on both sides is rescaled back; a history left on the
   pre-split basis at a split date is divided by the split ratio.  Every change is recorded.
2. ``check_adjusted``/``recompute_adjusted``: the adjusted close must be positive and its ratio to
   the close must be a non-decreasing step function in time (it only changes on ex-dividend
   dates).  If Yahoo's adjusted close violates that, it is recomputed from the close and the
   dividends (dividends on the pre-split basis are brought to the post-split basis first).
3. ``split_like_jumps``: remaining daily moves that look like a split ratio are reported so that the
   download service can re-download the full history and the analysis can warn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

PRICE_COLS = ("open", "high", "low", "close", "adj_close")
COMMON_FACTORS = (2, 3, 4, 5, 10, 20, 25, 50, 100, 200, 1000)
UNIT_FACTORS = (100.0,)          # pence/cents or "price divided by 100 twice" errors
LOG_TOL = 0.12                   # |log(move) - log(factor)| tolerance (about 12%)
MAX_BLOCK_ROWS = 40


@dataclass
class Repair:
    kind: str                    # SCALE_BLOCK | PRESPLIT_UNADJUSTED | ADJ_RECOMPUTED | DIVIDEND_REBASED
    date_from: str
    date_to: str
    factor: float
    detail: str


@dataclass
class RepairReport:
    repairs: list[Repair] = field(default_factory=list)
    splits: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    dividends: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


def extract_actions(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(splits, dividends) from a normalized provider frame (optional columns)."""
    sp = df["splits"] if "splits" in df.columns else pd.Series(dtype=float)
    dv = df["dividends"] if "dividends" in df.columns else pd.Series(dtype=float)
    sp = pd.to_numeric(sp, errors="coerce").fillna(0.0)
    dv = pd.to_numeric(dv, errors="coerce").fillna(0.0)
    return sp[sp > 0], dv[dv > 0]


def _candidate_factors(splits: pd.Series) -> list[float]:
    f = set(UNIT_FACTORS)
    for r in splits.values:
        if r > 0 and abs(np.log(r)) > np.log(1.2):
            f.add(float(r))
            f.add(float(1.0 / r))
    f |= {1.0 / x for x in UNIT_FACTORS}
    return sorted(f)


def _match(move: float, factors: list[float]) -> float | None:
    """The factor f with log(move) ≈ log(f), if any."""
    if not np.isfinite(move) or move <= 0:
        return None
    lm = np.log(move)
    best = min(factors, key=lambda f: abs(lm - np.log(f)))
    return best if abs(lm - np.log(best)) < LOG_TOL else None


def repair_scale_errors(df: pd.DataFrame, splits: pd.Series | None = None) -> tuple[pd.DataFrame, list[Repair]]:
    """Fix rows whose level is off by a split/units factor. Returns a copy and the repairs made."""
    out = df.copy()
    repairs: list[Repair] = []
    if out.empty or "close" not in out.columns:
        return out, repairs
    splits = splits if splits is not None else pd.Series(dtype=float)
    factors = _candidate_factors(splits)
    cols = [c for c in PRICE_COLS if c in out.columns]

    # (a) temporary blocks (first, so a broken split-day row is not mistaken for an unadjusted history): a jump by f followed (within MAX_BLOCK_ROWS rows) by a jump back by 1/f
    close = out["close"].to_numpy(dtype=float, copy=True)
    i = 1
    while i < len(close):
        f = _match(close[i] / close[i - 1], factors) if close[i - 1] > 0 else None
        if f is None or abs(np.log(f)) < np.log(1.5):
            i += 1
            continue
        end = None
        for j in range(i + 1, min(i + MAX_BLOCK_ROWS + 1, len(close))):
            back = close[j] / close[j - 1] if close[j - 1] > 0 else np.nan
            if np.isfinite(back) and back > 0 and abs(np.log(back) + np.log(f)) < LOG_TOL:
                end = j
                break
        if end is None:
            i += 1
            continue
        idx = out.index[i:end]
        out.loc[idx, cols] = out.loc[idx, cols] / f
        close[i:end] = close[i:end] / f
        repairs.append(Repair("SCALE_BLOCK", f"{idx[0]:%Y-%m-%d}", f"{idx[-1]:%Y-%m-%d}", 1.0 / f,
                              f"{len(idx)} row(s) were off by a factor {f:g} relative to both neighbours "
                              f"(bad split adjustment or units error); rescaled"))
        i = end + 1

    # (b) a history left on the pre-split basis: the close drops by the split ratio ON the split date
    for d, ratio in splits.items():
        d = pd.Timestamp(d).normalize()
        if d not in out.index or abs(np.log(ratio)) < np.log(1.2):
            continue
        pos = out.index.get_loc(d)
        if pos == 0:
            continue
        move = out["close"].iloc[pos] / out["close"].iloc[pos - 1]
        if abs(np.log(move) + np.log(ratio)) < LOG_TOL:
            out.iloc[:pos, [out.columns.get_loc(c) for c in cols]] /= ratio
            repairs.append(Repair("PRESPLIT_UNADJUSTED", f"{out.index[0]:%Y-%m-%d}", f"{out.index[pos - 1]:%Y-%m-%d}",
                                  1.0 / ratio, f"rows before the {ratio:g}:1 split of {d:%Y-%m-%d} were not adjusted; "
                                               f"divided by {ratio:g}"))

    return out, repairs


def check_adjusted(df: pd.DataFrame, rel_tol: float = 2e-3) -> list[str]:
    """Problems with the adjusted close (empty list = consistent)."""
    problems: list[str] = []
    if df.empty or "adj_close" not in df.columns:
        return problems
    adj, close = df["adj_close"].astype(float), df["close"].astype(float)
    if (adj <= 0).any():
        problems.append(f"{int((adj <= 0).sum())} non-positive adjusted closes")
    ratio = (adj / close).replace([np.inf, -np.inf], np.nan).dropna()
    if len(ratio) and (ratio > 1.0 + 5e-3).any():
        problems.append("adjusted close above close (adjustment factor > 1)")
    if len(ratio) > 1:
        drops = ratio.diff() < -rel_tol * ratio.shift(1)
        if drops.any():
            problems.append(f"adjustment factor decreases on {int(drops.sum())} date(s) "
                            f"(first {ratio.index[drops.to_numpy()][0]:%Y-%m-%d})")
    return problems


def recompute_adjusted(df: pd.DataFrame, dividends: pd.Series, splits: pd.Series | None = None
                       ) -> tuple[pd.Series, list[Repair]]:
    """Dividend-adjusted close from the (split-adjusted) close and the dividends.

    factor(t) = prod over ex-dividend dates d > t of (1 - D_d / close_{d-1}).
    A dividend larger than half the previous close is assumed to be on the pre-split basis and
    is divided by the product of the later split ratios when that makes it plausible.
    """
    close = df["close"].astype(float)
    repairs: list[Repair] = []
    splits = splits if splits is not None else pd.Series(dtype=float)
    mult = pd.Series(1.0, index=close.index)
    for d, D in dividends.sort_index().items():
        d = pd.Timestamp(d).normalize()
        pos = close.index.searchsorted(d)
        if pos <= 0 or pos >= len(close):
            continue
        prev = close.iloc[pos - 1]
        div = float(D)
        if prev > 0 and div / prev > 0.5:
            later = splits[pd.DatetimeIndex(splits.index).normalize() > d]
            k = float(np.prod(later.values)) if len(later) else 1.0
            if k > 1 and div / k / prev < 0.5:
                repairs.append(Repair("DIVIDEND_REBASED", f"{d:%Y-%m-%d}", f"{d:%Y-%m-%d}", 1.0 / k,
                                      f"dividend {div:g} was on the pre-split basis; divided by {k:g}"))
                div /= k
            else:
                continue  # implausible dividend: ignored rather than producing negative prices
        if prev <= 0 or div <= 0:
            continue
        f = 1.0 - div / prev
        mult.iloc[:pos] *= f
    adj = close * mult
    return adj, repairs


def repair_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, RepairReport]:
    """Full repair pipeline for one provider frame (rows are never added or invented)."""
    splits, dividends = extract_actions(df)
    out, repairs = repair_scale_errors(df, splits)
    problems = check_adjusted(out) if "adj_close" in out.columns else []
    if problems:
        adj, more = recompute_adjusted(out, dividends, splits)
        out["adj_close"] = adj
        repairs += more
        repairs.append(Repair("ADJ_RECOMPUTED", f"{out.index[0]:%Y-%m-%d}", f"{out.index[-1]:%Y-%m-%d}", 1.0,
                              "provider adjusted close was inconsistent (" + "; ".join(problems) +
                              "); recomputed from close and dividends"))
    return out, RepairReport(repairs, splits, dividends)


def split_like_jumps(prices: pd.Series, extra_factors: tuple[float, ...] = (), threshold: float = 0.45
                     ) -> list[tuple[pd.Timestamp, float]]:
    """Dates where the price moves by a factor that looks like a split (or by more than ±threshold)."""
    s = prices.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return []
    move = (s / s.shift(1)).iloc[1:]
    factors = [float(f) for f in COMMON_FACTORS] + [1.0 / f for f in COMMON_FACTORS] + list(extra_factors)
    out = []
    for d, m in move.items():
        lm = abs(np.log(m))
        if lm < np.log(1.5):
            continue
        if _match(m, factors) is not None or m - 1 > threshold * 2 or m - 1 < -threshold:
            out.append((d, float(m)))
    return out
