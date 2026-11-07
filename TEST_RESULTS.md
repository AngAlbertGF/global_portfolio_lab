# Test results

Run on 2026-10-27, 2026-10-28 and 2026-10-29, Python 3.13.18, Linux, streamlit 1.66.1, yfinance 1.7.0, pandas 3.0.5, scipy 1.18.1.

## Custom analysis window (2026-10-31)

Offline suite: **105 passed, 2 skipped** (`tests/test_custom_horizon.py` added: the custom window is a number equal
to its length in years but a distinct key, pickles, prints "5 meses (2026-06-01 a 2026-10-30)"; in the engine a
window inside the common history is COMPLETE and ends on its end date, a window before a listing is INCOMPLETE in
strict mode and COMPLETE when reconstructed, a two-month window explains the minimum of observations and becomes
COMPLETE (with the short-window warning) when the minimum is lowered; in the interface the Custom option, the date
range, every analysis page and the HTML report work with the window). Browser (Spanish): the selector, quick
windows, date range and the cross-horizon charts show the custom window; no exceptions or page errors.

## Reconstructed history for IPOs (2026-10-30)

Offline suite: **101 passed, 2 skipped** (`tests/test_backfill.py` added: real returns never changed, residuals add
risk but no return, reproducible, no look-ahead when fitted up to the end of training, the other holdings keep only
real returns, PSD covariance, all optimizers valid, the "too few real days" explanation, and the Reconstruct button
plus every analysis page and the Backtesting lab in the interface).

**Validation on real Yahoo data.** Nine real stocks (AAPL, NVDA, WALMEX.MX, AMXB.MX, PETR4.SA, 7203.T, 1321.T, SHEL.L,
BHP.AX; base MXN). One stock at a time had its history before a date deleted, as if it had just listed; the results
were compared with the analysis on its true full history. Errors in percentage points of the portfolio's annual
return (μ) and volatility (σ); "others" = largest change in another holding's expected return.

| "IPO" (real days) | Horizon | Common universe μ / σ | Available history μ / σ / others | Reconstructed μ / σ / others |
|---|---|---|---|---|
| AMXB.MX (≈105) | 1y | −3.4 / 0.0 | not enough data | **+0.2** / +0.3 / 0 |
| | 3y | −2.6 / +0.4 | not enough data | **−0.6 / +0.1** / 0 |
| | 5y | −1.4 / +0.5 | not enough data | **−0.3 / +0.3** / 0 |
| NVDA (≈165) | 1y | +5.2 / +0.7 | +7.4 / −0.8 / 30 | **+1.8 / −0.2** / 0 |
| | 3y | −8.5 / −0.9 | +1.3 / −5.4 / 36 | −8.5 / −1.6 / 0 |
| | 5y | −7.7 / −1.9 | +7.4 / −7.1 / 40 | −9.9 / −2.3 / 0 |
| 7203.T (≈60) | 1y | +1.2 / +0.3 | not enough data | **+0.9 / −0.1** / 0 |
| | 3y | +0.8 / +0.1 | not enough data | **−0.1** / −0.3 / 0 |
| | 5y | +0.3 / 0.0 | not enough data | **+0.1** / −0.3 / 0 |
| PETR4.SA (≈120) | 1y | −6.7 / +0.6 | +3.8 / −0.9 / 32 | **−4.4 / 0.0** / ≈1* |
| | 3y | −0.7 / +0.8 | −2.3 / −5.5 / 56 | −1.8 / **−0.2** / ≈1* |
| | 5y | −2.9 / +0.8 | +3.8 / −7.2 / 54 | −3.8 / **−0.2** / ≈1* |

\* Brazilian holidays: the common calendar drops the dates on which the new listing did not trade, as in every mode.

Reading: *available history* moves the other holdings' expected returns by 30–56 points and halves the measured
risk; *common universe* is no longer your portfolio (the stock is missing). *Reconstructed* keeps your portfolio,
never changes the other holdings' data, and its volatility error is at most 0.3 points except for NVDA. NVDA's real
2021–2025 return was exceptional: no method can know an abnormal return that is not in the data, and the
reconstruction deliberately does not invent one (it is conservative).

Live through the interface: with PETR4.SA cut to 2026-05-04 and the reconstructed mode on, opening Portfolio
Statistics downloaded ^BVSP automatically and used it as the factor (β 0.72, R² 0.40; the rest of this portfolio has
R² ≈ 0 for PETR4, which is why the market index matters); all five horizons COMPLETE. Browser (Spanish): the
"Reconstruir la historia corta" button, the reconstructed banner, the table, the grey band and the Backtesting lab
render with no exceptions or page errors.

## Missing data fix (2026-10-30)

Reported: after building a portfolio, Portfolio Statistics showed "Horizon 1 year: Incomplete (STRICT)" in every
horizon. Reproduced with real Yahoo data in two ways: a holding whose prices were never downloaded, and a base
currency with no stored exchange rates (base changed from MXN to USD). Both made every horizon INCOMPLETE, with
the reason only inside a collapsed expander. After the fix:

* Offline suite: **96 passed, 2 skipped** (`tests/test_data_gaps.py` added: gap detection and filling, reason per
  security, automatic one-time download on the Statistics page, the explanation banner and its buttons).
* Live, through the interface (AppTest, real Yahoo): a 7-stock portfolio (AAPL, NVDA, WALMEX.MX, PETR4.SA, 7203.T,
  BHP.AX, RELIANCE.NS) built in the Builder: all five horizons COMPLETE. Base currency then switched to USD with no
  USD exchange rates stored: opening Statistics downloaded MXN/BRL/JPY/AUD/INR→USD automatically and all five
  horizons were COMPLETE.
* Browser (Spanish): a holding that cannot be downloaded shows "Por qué: … todavía no se han descargado sus
  precios" and a "Descargar lo que falta" button; no exceptions or page errors.

## Offline suite: `pytest -v` (2026-10-29, after splits, logos, money, currency page and Backtesting lab)

```
tests/test_analysis_and_exports.py::test_every_horizon_reports_dates_and_status PASSED [  1%]
tests/test_analysis_and_exports.py::test_overlapping_history_marks_long_horizons_incomplete PASSED [  2%]
tests/test_analysis_and_exports.py::test_common_universe_and_available_history_are_labelled PASSED [  3%]
tests/test_analysis_and_exports.py::test_minimum_observation_requirement PASSED [  4%]
tests/test_analysis_and_exports.py::test_fixed_market_constraints_hold_in_analysis PASSED [  5%]
tests/test_analysis_and_exports.py::test_portfolio_returns_consistent_with_quadratic_form PASSED [  6%]
tests/test_analysis_and_exports.py::test_exports_match_displayed_values PASSED [  7%]
tests/test_analysis_and_exports.py::test_backtest_no_lookahead PASSED    [  8%]
tests/test_analysis_and_exports.py::test_html_report_stays_light_while_screen_is_dark PASSED [  9%]
tests/test_app_ui.py::test_every_page_renders_without_exceptions PASSED  [ 10%]
tests/test_app_ui.py::test_build_portfolio_through_interface PASSED      [ 11%]
tests/test_app_ui.py::test_interactive_controls_run PASSED               [ 12%]
tests/test_app_ui.py::test_strict_mode_switch_to_labelled_mode PASSED    [ 13%]
tests/test_app_ui.py::test_switch_language_from_sidebar_and_render_every_page_in_spanish PASSED [ 14%]
tests/test_app_ui.py::test_spanish_builder_buttons_and_reports PASSED    [ 15%]
tests/test_app_ui.py::test_dark_mode_switch_and_working_portfolio_survives_reload PASSED [ 17%]
tests/test_app_ui.py::test_builder_step2_picker_and_new_pages PASSED     [ 18%]
tests/test_backtest_lab.py::test_money_accounting_is_exact PASSED        [ 19%]
tests/test_backtest_lab.py::test_no_look_ahead_in_training_and_forecast PASSED [ 20%]
tests/test_backtest_lab.py::test_walk_forward_uses_only_past_data PASSED [ 21%]
tests/test_backtest_lab.py::test_buy_and_hold_lets_weights_drift PASSED  [ 22%]
tests/test_backtest_lab.py::test_all_strategies_run PASSED               [ 23%]
tests/test_backtest_lab.py::test_helpers PASSED                          [ 24%]
tests/test_corporate_actions.py::test_block_off_by_100_after_split_is_rescaled PASSED [ 25%]
tests/test_corporate_actions.py::test_history_left_on_presplit_basis_is_divided PASSED [ 26%]
tests/test_corporate_actions.py::test_reverse_split_block_is_repaired PASSED [ 27%]
tests/test_corporate_actions.py::test_negative_adjusted_close_recomputed_from_rebased_dividends PASSED [ 28%]
tests/test_corporate_actions.py::test_split_after_incremental_download_triggers_full_rebase PASSED [ 29%]
tests/test_corporate_actions.py::test_corrupted_stored_history_is_rebased_on_next_update PASSED [ 30%]
tests/test_corporate_actions.py::test_dividend_basis_change_is_detected PASSED [ 31%]
tests/test_corporate_actions.py::test_analysis_warns_on_remaining_extreme_returns PASSED [ 32%]
tests/test_database_and_data.py::test_initialize_new_database PASSED     [ 34%]
tests/test_database_and_data.py::test_duplicate_prevention_and_upsert PASSED [ 35%]
tests/test_database_and_data.py::test_download_and_cache_then_refresh_without_duplicates PASSED [ 36%]
tests/test_database_and_data.py::test_cache_avoids_network PASSED        [ 37%]
tests/test_database_and_data.py::test_recent_listing_backfill_checked_once PASSED [ 38%]
tests/test_database_and_data.py::test_invalid_ticker_and_provider_error_distinguished PASSED [ 39%]
tests/test_database_and_data.py::test_empty_provider_response PASSED     [ 40%]
tests/test_database_and_data.py::test_failed_refresh_keeps_existing_data PASSED [ 41%]
tests/test_database_and_data.py::test_currency_mismatch_warning PASSED   [ 42%]
tests/test_database_and_data.py::test_fx_download_verified_and_inverted_series_rejected PASSED [ 43%]
tests/test_database_and_data.py::test_backup_restore_and_portfolio_persistence PASSED [ 44%]
tests/test_i18n.py::test_no_variable_shadows_the_translation_function PASSED [ 45%]
tests/test_i18n.py::test_catalog_complete_and_placeholders_match[es] PASSED [ 46%]
tests/test_i18n.py::test_catalog_is_valid_json_with_language_name[es] PASSED [ 47%]
tests/test_i18n.py::test_docs_exist_for_every_language PASSED            [ 48%]
tests/test_i18n.py::test_translation_switch_fallback_and_formatting PASSED [ 50%]
tests/test_i18n.py::test_engine_messages_follow_language PASSED          [ 51%]
tests/test_i18n.py::test_guide_sections_split PASSED                     [ 52%]
tests/test_live_yahoo.py::test_live_download_fx_and_analysis SKIPPED     [ 53%]
tests/test_live_yahoo.py::test_live_split_repair_and_logos SKIPPED (...) [ 54%]
tests/test_money_logos_fx.py::test_money_summary_and_contributions PASSED [ 55%]
tests/test_money_logos_fx.py::test_brand_color_and_chart_colors PASSED   [ 56%]
tests/test_money_logos_fx.py::test_fetch_logo_source_order_and_storage_rule PASSED [ 57%]
tests/test_money_logos_fx.py::test_conversion_detail_rate_used_and_subunits PASSED [ 58%]
tests/test_optimization.py::test_min_variance_invariants PASSED          [ 59%]
tests/test_optimization.py::test_min_variance_matches_closed_form_when_unconstrained PASSED [ 60%]
tests/test_optimization.py::test_max_sharpe_beats_feasible_portfolios PASSED [ 61%]
tests/test_optimization.py::test_max_return_concentrates_per_market PASSED [ 62%]
tests/test_optimization.py::test_max_risk_exact_by_enumeration PASSED    [ 63%]
tests/test_optimization.py::test_max_risk_with_caps_is_labelled_approximate PASSED [ 64%]
tests/test_optimization.py::test_infeasible_caps_detected PASSED         [ 65%]
tests/test_optimization.py::test_global_only_mode_moves_market_budgets PASSED [ 67%]
tests/test_optimization.py::test_short_selling_mode_respects_bounds PASSED [ 68%]
tests/test_optimization.py::test_frontier_feasibility_and_ordering PASSED [ 69%]
tests/test_optimization.py::test_run_all_constraint_residuals_and_equal_weight PASSED [ 70%]
tests/test_optimization.py::test_min_cvar_and_diversification_and_target_vol PASSED [ 71%]
tests/test_optimization.py::test_max_sharpe_when_no_portfolio_beats_rf PASSED [ 72%]
tests/test_returns_fx.py::test_simple_and_log_returns PASSED             [ 73%]
tests/test_returns_fx.py::test_annualization PASSED                      [ 74%]
tests/test_returns_fx.py::test_currency_conversion_known_values_and_cross_term PASSED [ 75%]
tests/test_returns_fx.py::test_minor_currency_units_pence PASSED         [ 76%]
tests/test_returns_fx.py::test_fx_alignment_carry_limit_and_drop PASSED  [ 77%]
tests/test_returns_fx.py::test_same_currency_no_conversion PASSED        [ 78%]
tests/test_returns_fx.py::test_fx_direction_verification PASSED          [ 79%]
tests/test_returns_fx.py::test_common_calendar_no_filling PASSED         [ 80%]
tests/test_statistics.py::test_covariance_and_portfolio_variance_quadratic_form PASSED [ 81%]
tests/test_statistics.py::test_sharpe_consistency_between_history_and_markowitz PASSED [ 82%]
tests/test_statistics.py::test_ledoit_wolf_matches_sklearn PASSED        [ 84%]
tests/test_statistics.py::test_estimators_shapes_and_psd PASSED          [ 85%]
tests/test_statistics.py::test_singular_covariance_detected PASSED       [ 86%]
tests/test_statistics.py::test_drawdown_var_cvar_known_values PASSED     [ 87%]
tests/test_statistics.py::test_euler_decomposition_sums_to_volatility PASSED [ 88%]
tests/test_statistics.py::test_synthetic_dataset_reproduces_known_statistics PASSED [ 89%]
tests/test_statistics.py::test_bootstrap_ci_contains_point_estimate PASSED [ 90%]
tests/test_theme.py::test_set_dark_switches_chart_tokens PASSED          [ 91%]
tests/test_theme.py::test_light_mode_constants_unchanged_for_static_exports PASSED [ 92%]
tests/test_validation.py::test_market_allocations_sum_to_100 PASSED      [ 93%]
tests/test_validation.py::test_within_market_weights_sum_to_100 PASSED   [ 94%]
tests/test_validation.py::test_global_weight_conversion_matches_spec_example PASSED [ 95%]
tests/test_validation.py::test_duplicates_negative_and_empty_markets_rejected PASSED [ 96%]
tests/test_validation.py::test_ticker_normalization_preserves_suffix_and_rejects_names PASSED [ 97%]
tests/test_validation.py::test_currency_and_suffix_conflicts_warn PASSED [ 98%]
tests/test_validation.py::test_clean_price_frame_never_fabricates PASSED [100%]
=================== 92 passed, 2 skipped in 85.95s (0:01:25) ===================
```

## Live Yahoo Finance tests: `GPL_LIVE_TESTS=1 pytest tests/test_live_yahoo.py` (2026-10-29: 2 passed in 27.06s)

```
tests/test_live_yahoo.py::test_live_download_fx_and_analysis PASSED
tests/test_live_yahoo.py::test_live_split_repair_and_logos PASSED
```

`test_live_split_repair_and_logos` downloads the Nikkei 225 ETF `1321.T` (100:1 split) and requires no
split-sized jump in the stored adjusted series and every daily move below 30%; it also fetches the NVDA and
WALMEX.MX logos and checks that a primary colour was extracted.

## Split repair, manual live check (2026-10-29)

Before the fix, `1321.T` from Yahoo had days still on the pre-split price basis around the 100:1 split, which
produced fake daily returns of about −99% / +9,900% and distorted every statistic of a portfolio holding it.
After the fix: largest absolute daily return 11.4%, no split-like jumps, one `SCALE_BLOCK` repair logged. A
database created with the previous version (containing the broken rows) was updated with the new version: the
basis change was detected and the symbol's full history was downloaded again and replaced (`rebase`).

## Logo sources, manual live check (2026-10-29)

Parqet returned logos for NVDA, WALMEX.MX, VALE3.SA, PETR4.SA, 7203.T, SHEL.L, RELIANCE.NS, BHP.AX and SAP.DE;
Financial Modeling Prep for AMXB.MX; no source had a logo for the ETF 1321.T (a coloured tile with initials is
shown). logostream.dev was not tested live (it needs an API key).

## Browser check, redesign (2026-10-29)

Chromium 1440 px against `streamlit run app.py` (demo data), in Spanish and English, light and dark mode:
Dashboard map, Builder step 2 name picker with logos, Find securities, Statistics, Currency conversion, Efficient
Frontier (point click → detail), Optimized Portfolios, Risk Analysis and Backtesting lab (run, forecast cone,
what-if tabs). No Streamlit exceptions and no browser page errors.

## Browser check (2026-10-28)

The app was run with `streamlit run app.py` and inspected in Chromium at 1440 px and 390 px width: Spanish and
English rendering, language switch from the sidebar without reloading, Builder, Dashboard, How to use, Efficient
Frontier, Optimized Portfolios and Risk Analysis pages.

## Dark mode browser check (2026-10-29)

Chromium 1440 px against `streamlit run app.py` (demo data): clicking **Dark mode** in the sidebar reloaded the page
once and the app background changed from `rgb(245, 247, 250)` to `rgb(15, 21, 32)`; after the reload the switch
showed "on", the 8-security portfolio was still loaded, and Builder, Statistics, Efficient Frontier and How to use
were dark (tables, inputs, Plotly charts). Clicking again returned to light. No browser JavaScript errors. A fresh
browser profile opens in light mode (the choice is stored per browser).

## Additional manual live checks (same day)

* Validation: AAPL (USD), WALMEX.MX (MXN), PETR4.SA (BRL), 7203.T (JPY), BHP.AX (AUD), RELIANCE.NS (INR),
  BARC.L (GBp, converted /100), ^GSPC accepted with names; `VALE` under Brazil accepted with suffix and currency
  warnings; `ZZQXQ.MX` and the company name `Walmart` rejected as NOT_FOUND.
* 15-year download of those 8 symbols + ^GSPC and FX AUD/BRL/GBP/JPY/USD → MXN: all SUCCESS; FX direction verified
  for all direct pairs (median direct x inverse product within 0.2% of 1); `INRMXN=X` unavailable, triangulated
  via USD and labelled as derived.
* Second refresh: overlap rows updated, zero new duplicate rows, integrity check OK.
* Analysis on the live data: all five horizons COMPLETE in strict mode, every optimizer valid.
* Yahoo throttled crumb-protected endpoints (HTTP 401/429) during testing; validation falls back to chart
  metadata, and ambiguous failures are reported as provider errors instead of invalid tickers.

The live results depend on Yahoo's availability at the time of running and are not guaranteed.
