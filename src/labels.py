"""Display labels for internal codes, table columns and statistics (shared by the UI and the reports).

Values are English message keys marked with ``N_``; translate them at display time with ``t()``.
"""
from __future__ import annotations

from typing import Any

from .i18n import N_, t

STATUS_LABELS = {
    "COMPLETE": N_("Complete"), "INCOMPLETE": N_("Incomplete"),
    "INSUFFICIENT_OBSERVATIONS": N_("Insufficient observations"), "NO_DATA": N_("No data"), "ERROR": N_("Error"),
    "SUCCESS": N_("Success"), "UP_TO_DATE": N_("Up to date"), "PARTIAL": N_("Partial"), "FAILED": N_("Failed"),
    "NOT_FOUND": N_("Not found"), "VALID": N_("Valid"), "VALID_LOCAL": N_("Valid (local)"),
    "PROVIDER_ERROR": N_("Provider error"), "INVALID_SYNTAX": N_("Invalid format"), "NO_PRICE_DATA": N_("No prices"),
    "UNVALIDATED": N_("Not validated"), "efficient": N_("efficient"), "inefficient": N_("inefficient"),
}
STATUS_COLOR = {"COMPLETE": "green", "INCOMPLETE": "orange", "INSUFFICIENT_OBSERVATIONS": "orange",
                "NO_DATA": "red", "ERROR": "red"}
STATUS_ICON = {"COMPLETE": ":material/check_circle:", "INCOMPLETE": ":material/warning:",
               "INSUFFICIENT_OBSERVATIONS": ":material/warning:", "NO_DATA": ":material/block:",
               "ERROR": ":material/error:"}

ESTIMATOR_LABELS = {"arithmetic": N_("Historical arithmetic mean"), "geometric": N_("Historical geometric"),
                    "ewma": N_("Exponentially weighted"), "user": N_("User-defined"), "sample": N_("Sample"),
                    "ledoit_wolf": N_("Ledoit-Wolf shrinkage")}
CONSTRAINT_LABELS = {"fixed_markets": N_("Fixed market allocations (standard)"),
                     "global_only": N_("Unconstrained market allocation (budget only)")}
COVERAGE_LABELS = {"strict": N_("Strict (original portfolio)"), "common_universe": N_("Common universe (labelled)"),
                   "available_history": N_("Available history (labelled)"),
                   "reconstructed": N_("Reconstructed history for IPOs (labelled)")}
FREQUENCY_LABELS = {"daily": N_("Daily"), "weekly": N_("Weekly")}
REBALANCE_LABELS = {"monthly": N_("Monthly"), "quarterly": N_("Quarterly"), "annual": N_("Annual")}
WINDOW_LABELS = {"rolling": N_("Rolling"), "expanding": N_("Expanding")}

COLUMN_LABELS = {
    "first_real": N_("First real return"), "n_real": N_("Real returns"), "n_filled": N_("Reconstructed"),
    "share_filled": N_("Reconstructed share"), "factors": N_("Factors"), "betas": N_("Betas"), "r2": "R²",
    "alpha_annual": N_("Extra return of the real part (not carried back)"),
    "resid_vol_annual": N_("Own (residual) volatility"), "real_mean_annual": N_("Mean of real part (annual)"),
    "filled_mean_annual": N_("Mean of reconstructed part (annual)"),
    "rebased": N_("Full re-download"), "repairs": N_("Repairs"), "kind": N_("Kind"), "date_from": N_("From"),
    "date_to": N_("To"), "factor": N_("Factor"), "detail": N_("Detail"), "created_at": N_("Recorded at"),
    "ticker": N_("Ticker"), "horizon": N_("Horizon"), "horizon_years": N_("Horizon (years)"), "status": N_("Status"), "mode": N_("Mode"),
    "start": N_("Start"), "end": N_("End"), "n_obs": N_("Observations"), "actual_years": N_("Years covered"),
    "n_assets": N_("Assets"), "user_annual_return": N_("User return"), "user_cagr": N_("User CAGR"),
    "user_volatility": N_("User volatility"), "user_sharpe": N_("User Sharpe"),
    "user_max_drawdown": N_("User max drawdown"), "min_variance_return": N_("Min-variance return"),
    "min_variance_volatility": N_("Min-variance volatility"), "min_variance_sharpe": N_("Min-variance Sharpe"),
    "max_sharpe_return": N_("Max-Sharpe return"), "max_sharpe_volatility": N_("Max-Sharpe volatility"),
    "max_sharpe_sharpe": N_("Max-Sharpe Sharpe"),
    "annual_arith_return": N_("Annual return (arith.)"), "annual_cagr": N_("CAGR"),
    "annual_volatility": N_("Annual volatility"), "sharpe": N_("Sharpe"), "max_drawdown": N_("Max drawdown"),
    "expected_return_used": N_("Expected return used"), "weight": N_("Weight"),
    "contribution_to_expected_return": N_("Contribution to return"),
    "marginal_vol_contribution": N_("Marginal risk contribution"),
    "component_vol_contribution": N_("Component risk contribution"), "component_vol_pct": N_("Share of risk"),
    "variance_contribution": N_("Variance contribution"), "variance_contribution_pct": N_("Share of variance"),
    "beta": N_("Beta"), "market_id": N_("Market"), "currency": N_("Currency"), "security_name": N_("Name"),
    "first_obs": N_("First observation"), "last_obs": N_("Last observation"), "covers_horizon": N_("Covers horizon"),
    "years_available": N_("Years available"), "target": N_("Target return"), "expected_return": N_("Expected return"),
    "volatility": N_("Volatility"), "ok": N_("Valid"), "branch": N_("Branch"), "is_gmv": N_("GMV point"),
    "max_residual": N_("Max residual"), "trading_currency": N_("Trading currency"),
    "major_currency": N_("Major currency"), "unit_divisor": N_("Unit divisor"), "fx_pair": N_("FX pair"),
    "fx_direction_verified": N_("FX direction verified"), "n_local": N_("Local obs"),
    "n_converted": N_("Converted obs"), "n_fx_same_day": N_("Same-day FX"), "n_fx_carried": N_("Carried FX"),
    "n_dropped_no_fx": N_("Dropped (no FX)"), "max_fx_staleness_days": N_("Max FX staleness (days)"),
    "notes": N_("Notes"), "exchange": N_("Exchange"), "first_observed_date": N_("First date"),
    "last_observed_date": N_("Last date"), "provider": N_("Provider"), "last_updated_at": N_("Last updated (UTC)"),
    "validation_status": N_("Validation"), "security_type": N_("Type"), "timezone": N_("Timezone"),
    "history_checked_from": N_("History checked from"), "base_currency": N_("From currency"),
    "quote_currency": N_("To currency"), "symbol": N_("Symbol"), "direction_verified": N_("Direction verified"),
    "verification_detail": N_("Verification detail"), "last_checked_at": N_("Last checked (UTC)"),
    "first_date": N_("First date"), "last_date": N_("Last date"), "flags": N_("Flags"), "id": N_("ID"),
    "requested_start_date": N_("Requested start"), "requested_end_date": N_("Requested end (exclusive)"),
    "download_status": N_("Download status"), "rows_received": N_("Rows received"),
    "rows_inserted": N_("Rows inserted"), "rows_updated": N_("Rows updated"), "error_message": N_("Message"),
    "timestamp": N_("Time (UTC)"), "cagr": N_("CAGR"), "cumulative_return": N_("Cumulative return"),
    "annual_turnover": N_("Annual turnover"), "total_cost_drag": N_("Total cost drag"), "strategy": N_("Strategy"),
    "period": N_("Period"), "from": N_("From"), "to": N_("To"), "return": N_("Return"), "estimate": N_("Estimate"),
    "ci_low": N_("95% CI low"), "ci_high": N_("95% CI high"), "risk_free_annual": N_("Risk-free (annual)"),
    "max_sharpe_ok": N_("Max-Sharpe valid"), "largest_weight": N_("Largest weight"),
    "stored_obs": N_("Stored obs"), "stored_first": N_("Stored from"), "stored_last": N_("Stored to"),
    "planned_requests": N_("Planned download"), "calendar_days_requested": N_("Calendar days requested"),
    "portfolio": N_("Portfolio"), "solver_success": N_("Solver success"), "feasible": N_("Feasible"),
    "certification": N_("Certification"), "method": N_("Method"), "n_holdings": N_("Holdings"),
    "portfolio_name": N_("Portfolio"), "created_at": N_("Created"), "updated_at": N_("Updated"),
    "messages": N_("Messages"),
}
ROW_LABELS = {"annual_arith_return": N_("Annual return (arith.)"), "annual_volatility": N_("Annual volatility"),
              "sharpe_annual": N_("Sharpe (annualized)")}


def col_label(c: Any) -> str:
    return t(COLUMN_LABELS[c]) if isinstance(c, str) and c in COLUMN_LABELS else str(c)


def status_label(code: Any) -> Any:
    return t(STATUS_LABELS[code]) if isinstance(code, str) and code in STATUS_LABELS else code



STAT_LABELS = {"n_obs": N_("Observations"), "start": N_("First return date"), "end": N_("Last return date"),
          "annual_arithmetic_return": N_("Expected annualized arithmetic return"),
          "annual_geometric_return_cagr": N_("Historical annualized geometric return (CAGR)"),
          "annual_volatility": N_("Annualized volatility"), "mean_period": N_("Mean period return"),
          "sd_period": N_("Period return std. deviation"), "sharpe_period": N_("Sharpe ratio (per period)"),
          "sharpe_annual": N_("Sharpe ratio (annualized)"), "sortino_annual": N_("Sortino ratio (annualized)"),
          "downside_deviation_annual": N_("Annualized downside deviation"), "max_drawdown": N_("Maximum drawdown"),
          "max_drawdown_peak": N_("Drawdown peak"), "max_drawdown_trough": N_("Drawdown trough"),
          "calmar": N_("Calmar ratio"), "best_period_return": N_("Best period return"),
          "best_period_date": N_("Best period date"), "worst_period_return": N_("Worst period return"),
          "worst_period_date": N_("Worst period date"), "skewness": N_("Skewness"),
          "excess_kurtosis": N_("Excess kurtosis"), "jarque_bera_stat": N_("Jarque-Bera statistic"),
          "jarque_bera_pvalue": N_("Jarque-Bera p-value"), "var_95": N_("Historical VaR 95% (per period)"),
          "cvar_95": N_("Historical CVaR 95%"), "var_99": N_("Historical VaR 99%"), "cvar_99": N_("Historical CVaR 99%"),
          "cumulative_return": N_("Cumulative total return"), "positive_frequency": N_("Positive-return frequency"),
          "negative_frequency": N_("Negative-return frequency"), "zero_frequency": N_("Zero-return frequency"),
          "rf_annual_effective": N_("Risk-free rate (effective annual)"), "rf_period": N_("Risk-free rate per period"),
          "benchmark_obs": N_("Benchmark observations"), "beta": N_("Beta to benchmark"),
          "alpha_annual_arith": N_("Alpha (annual, arith.)"), "tracking_error": N_("Tracking error"),
          "information_ratio": N_("Information ratio"), "active_return_annual": N_("Active return (annual, arith.)"),
          "benchmark_annual_return": N_("Benchmark annual return (arith.)"),
          "benchmark_cumulative_return": N_("Benchmark cumulative return"),
          "correlation_to_benchmark": N_("Correlation to benchmark"),
          "best_rolling_21p": N_("Best 21-period return"), "best_rolling_21p_end": N_("Best 21-period window end"),
          "worst_rolling_21p": N_("Worst 21-period return"), "worst_rolling_21p_end": N_("Worst 21-period window end"),
          "best_rolling_4p": N_("Best 4-week return"), "best_rolling_4p_end": N_("Best 4-week window end"),
          "worst_rolling_4p": N_("Worst 4-week return"), "worst_rolling_4p_end": N_("Worst 4-week window end")}
