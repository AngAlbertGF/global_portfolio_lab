# Quantitative and Code Audit — 2026-11-08

## Status

This audit branch contains targeted corrections, regression tests, documentation updates, and a GitHub Actions workflow. The changes have been committed to `audit/quantitative-correctness-2026-11`; the default `main` branch has not been modified.

**Test execution is not yet verified.** The repository could be read and updated through GitHub, but this session did not have a repository runtime in which to execute pytest. A workflow was added to run `pytest -q --tb=short` under Python 3.13. At the time this report was written, GitHub's Actions API had not returned a run for the audit branch. Do not interpret the tests as passing until the workflow completes successfully.

## Findings corrected in this branch

### 1. Asset-level CAGR used the wrong elapsed interval

**Location:** `src/statistics.py`, `asset_statistics`.

The asset statistic started the CAGR clock at the date of the first return. A return dated at the first observation is earned over the interval from the preceding price observation, so the previous implementation understated elapsed time and could overstate CAGR. Asset CAGR now uses the same first-interval convention as portfolio CAGR: one observed return interval before the first return date.

### 2. Maximum-drawdown peak date could be wrong

**Location:** `src/statistics.py`, `max_drawdown`.

The drawdown series correctly included initial wealth of 1.0, but peak-date lookup searched only dated post-return wealth. When initial capital remained the peak, the function reported the first return date as the peak. It now identifies the inferred date immediately before the first return in that case. This is an inferred timestamp from the return index; callers needing an exact prior-price timestamp should pass that source date in a future interface refinement.

### 3. Benchmark alpha omitted the risk-free adjustment

**Location:** `src/statistics.py`, `benchmark_relative`; `src/labels.py`; English and Spanish statistics explanations.

The reported alpha was the intercept of a regression of raw portfolio returns on raw benchmark returns. It was labelled generically as alpha, although the standard CAPM/Jensen alpha is the intercept of excess-return regression. It now uses:

`alpha_annual = n * mean((r_portfolio - rf_period) - beta * (r_benchmark - rf_period))`

The display label and methodology text now explicitly identify the value as Jensen alpha.

### 4. An asymmetric covariance matrix could pass the optimization gate

**Location:** `src/statistics.py`, `check_covariance`; `src/analysis.py`, optimization gate.

The eigenvalue check used the symmetric part of the matrix. A matrix could therefore have a positive-semidefinite symmetric part but still be asymmetric, while the analysis gate checked only the PSD flag. The check now reports symmetry separately, rejects malformed/non-finite covariance matrices, and the analysis pipeline blocks optimization unless the matrix is both symmetric and PSD. No silent symmetrization or PSD repair is performed.

### 5. Invalid portfolio variance could be presented as zero volatility

**Location:** `src/optimization.py`, `port_stats` and `make_result`.

A materially negative quadratic form (w'\Sigma w) was previously clamped to zero before taking its square root. That can turn invalid covariance inputs into a plausible-looking zero-volatility portfolio. Materially negative or non-finite variance now yields non-finite volatility, and the result validator will not classify a non-finite solution as feasible/valid.

### 6. Optimizer failure states could be misreported

**Location:** `src/optimization.py`, `risk_parity` and `maximum_risk`.

- Risk parity previously set `solver_success=True` even when SLSQP failed and inverse-volatility fallback weights were returned. It now reports failure and explicitly marks those weights as an uncertified fallback.
- The multi-start maximum-risk search previously retained feasible candidates even when their SLSQP run reported failure, then labelled the result successful. It now accepts only converged, feasible candidates; otherwise it returns a failed, uncertified result.

### 7. Invalid optimization inputs were insufficiently guarded

**Location:** `src/optimization.py`, `minimum_cvar` and `target_volatility`.

Minimum CVaR now rejects a confidence level outside the open interval (0, 1), empty or wrongly shaped scenario matrices, and non-finite scenario returns. Target-volatility optimization now rejects negative and non-finite targets.

### 8. Walk-forward backtest overcharged rebalance turnover

**Location:** `src/backtesting.py`, `run_backtest`.

The module describes costs as proportional to **one-way turnover**, but subsequent rebalances charged the full L1 weight change. For a fully invested portfolio, that counts both buys and sells and is twice one-way turnover. Rebalances now use one-half of the L1 weight change. Initial purchases remain charged at the full invested amount.

### 9. Missing benchmark observations were treated as zero returns

**Location:** `src/backtest_lab.py`, `run_lab`.

The benchmark series was reindexed to test dates and missing values were filled with zero. This silently invented flat benchmark returns on dates without a benchmark observation. The lab now omits benchmark comparison for that test if any required benchmark return is missing and adds an explanatory note. It does not invent a benchmark value.

### 10. Monetary drawdown formula in README had the wrong sign

**Location:** `README.md`.

The documented expression used the largest value of wealth minus its running peak, although that expression is non-positive and its largest value is not the worst loss. The formula now reports the positive peak-to-trough loss magnitude:

`max_t(max_{s<=t} V_s - V_t)`

This is equivalent in magnitude to the absolute value of the minimum of wealth minus running peak. The money-summary implementation already selected the minimum signed drawdown; the defect was in the documentation formula.

## Regression tests added

- `tests/test_audit_regressions.py` covers asset CAGR timing, maximum-drawdown peak dating, Jensen alpha, asymmetric covariance, negative portfolio variance, risk-parity solver failure, maximum-risk solver failure, invalid CVaR confidence levels, and one-way turnover.
- `tests/test_backtest_lab.py` now verifies that a missing benchmark observation is not converted into a zero return.
- `.github/workflows/tests.yml` runs the offline pytest suite on Python 3.13 for audit-branch pushes and pull requests targeting `main`.

## Important issues not silently “fixed”

### Irregular common-calendar return intervals

The application intentionally uses dates on which every holding has a converted price and does not fill missing stock prices. Returns that span a dropped date are therefore multi-day returns. Several estimators and risk metrics still annualize using the conventional 252 daily / 52 weekly periods. Treating unequal-duration returns as equal-duration observations can bias annualized mean, volatility, Sharpe, covariance, and risk estimates. The README now discloses this directly.

This is not safely corrected by merely replacing 252 with a single observed frequency: intervals may have different lengths. A robust solution requires an explicit irregular-time return/covariance methodology or a carefully specified resampling policy, with separate validation for cross-market holidays, provider gaps, and stale prices. Until that work is implemented, treat daily/weekly annualized statistics as approximate, especially when the common-calendar dropped-date percentage is high.

### Normal-return simulation and wealth floor

The normal forecast option samples simple returns from a Gaussian distribution. Gaussian simple returns have non-zero probability below -100%, which can produce negative simulated wealth after compounding. This is a limitation of the stated distributional assumption, not a code crash to conceal with clipping. A future change should choose and document a wealth-consistent alternative (for example, a suitably parameterized gross-return/log-return model for long-only portfolios) and handle leveraged/short portfolios separately.

### Historical estimates remain in-sample

The historical optimized portfolios in the analysis pages are fitted and evaluated on the same historical sample. They are descriptive, in-sample estimates and not forecasts. The separate backtesting lab is the place to evaluate out-of-sample performance; it still has the disclosed limitations of current-universe survivorship bias and provider-revised adjusted prices.

## Review recommendation

Review this branch and its CI result before merging. In particular, verify the new regression tests in GitHub Actions and compare the updated one-way transaction-cost convention against any external performance reports that were generated using the former gross-turnover convention.
