# Global Portfolio Lab

International portfolio construction, Markowitz optimization and quantitative risk analytics — a local
Streamlit application backed by a persistent SQLite price database (Yahoo Finance via `yfinance`).

> Historical, in-sample analysis for study purposes. Optimized portfolios are estimates, not forecasts or
> investment recommendations. Yahoo Finance is an unofficial, free interface with no guarantee of completeness
> or availability.

---

## 1. Installation

Verified with **Python 3.13.18** (all pinned dependency ranges also support Python 3.12).

**macOS / Linux**
```bash
cd global_portfolio_lab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
cd global_portfolio_lab
py -3.13 -m venv .venv          # or: py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Launch

```bash
streamlit run app.py
```
The browser opens at `http://localhost:8501`. The database `data/stock_prices.db` is created automatically on
first launch (schema migrations run on every start and are idempotent).

Optional: put the data somewhere else (paths with spaces / non-ASCII characters are supported):
```bash
GPL_DATA_DIR="/path/to/my data" streamlit run app.py          # macOS / Linux
$env:GPL_DATA_DIR="D:\Mis datos"; streamlit run app.py         # Windows PowerShell
```

**Language / Idioma.** Pick *English* or *Español* in the sidebar (or in Settings). The whole interface, charts,
messages and HTML/PDF reports switch immediately; the choice is saved in `settings.json`. A full user guide is in the
app under **How to use / Cómo usar**.

**Offline?** *Settings and Data Quality → Data source and demo → Use SYNTHETIC demo database → Build or rebuild*.
This writes illustrative synthetic data to a **separate** file (`demo_synthetic.db`) and loads a demo portfolio.
Every page, report and export is then labelled SYNTHETIC. Switch it off to return to Yahoo data.

## 3. Sample workflow

1. **Portfolio Builder → 1. Market allocation.** Click *Load example* (USA 50, Mexico 20, Brazil 10,
   Japan 10, Australia 5, India 5) or type percentages in the table. The page shows the total, the unallocated
   remainder and blocks the next step until the sum is 100% (tolerance ±1e-6 percentage points).
2. **2. Securities.** In each market pick stocks already in your database **by name** (searchable list with logo,
   ticker and chart colour) or enter a new exact Yahoo symbol and its within-market percentage, e.g.
   USA: `AAPL` 60, `NVDA` 40 · Mexico: `WALMEX.MX` 100 · Brazil: `PETR4.SA` 100 · Japan: `7203.T` 100 ·
   Australia: `BHP.AX` 100 · India: `RELIANCE.NS` 100. Each symbol is validated (local DB first, then Yahoo);
   invalid symbols, provider errors, duplicates and currency/suffix conflicts are reported separately.
3. **3. Confirm and download.** Review names, exchanges, currencies, within-market and total weights, stored
   coverage and the planned download, then *Confirm and download*. Prices (15 calendar years) and the FX series
   needed for MXN are stored; the portfolio is saved.
4. **Portfolio Statistics** — what the capital became (money and percent) per horizon (1, 3, 5, 10, 15 years),
   growth vs benchmark/optimized portfolios, drawdown, monthly heatmap, money made by each security; all the
   statistics stay in tables below the charts.
5. **Currency conversion** — which FX rates were used for every security, a worked conversion example, and how much
   of the return came from the stock and how much from the currency.
6. **Efficient Frontier / Optimized Portfolios / Risk Analysis** — change the risk-free rate, estimators,
   constraint mode, long-only vs. short selling and stock caps; everything recomputes. Click a frontier point to
   see its composition and what it means in money.
7. **Backtesting lab** — train on a period you choose (default: everything up to 2025-12-31), test on the
   following period (default: from 2026-01-01), compare 10 strategies, forecast cones vs reality, and what-if
   scenarios.
8. **Reports and Exports** — Excel, CSV zip, HTML, PDF, PNG and the JSON configuration snapshot (money tables
   included).

Every page ends with a **"How was this calculated?"** panel that explains, in the selected language, where each
number comes from.

## 4. Project structure

```
app.py                     Streamlit entry point: theme CSS, language selector, navigation (13 pages in 4 sections)
views/                     How to use, Dashboard, Builder, Find securities, Database, Statistics, Currency,
                           Frontier, Optimized, Risk, Backtesting lab, Reports, Settings (named views/, not pages/,
                           so Streamlit's
                           legacy multipage mode never bypasses app.py)
assets/                    Logo and favicon (SVG)
src/i18n.py                Translation module: t(), N_(), doc(), years(), language switching
src/i18n_extract.py        Translation maintenance tool (missing/unused keys, placeholder check)
src/locales/es.json        Spanish catalog (English text is the key)
src/locales/docs/<lang>/   Long texts per language: how-to-use guide, formula panels, report sections
src/labels.py              Display labels for internal codes, table columns and statistics
src/ui.py                  Shared Streamlit layout: CSS, page header with allocation strip, sidebar, tables
src/config.py              Settings (JSON) and market metadata (configuration, not code branches)
src/database.py            SQLite schema + migrations, parameterized queries, transactions, backup/restore
src/yahoo_client.py        Provider interface, Yahoo implementation, retry/backoff, error classification
src/data_service.py        Ticker validation, incremental downloads, FX downloads, exchange-calendar gap report,
                           split repair and automatic re-download when the stored price basis changed
src/corporate_actions.py   Splits / reverse splits / dividends: scale-error repair, adjusted-close check and
                           recomputation, split-like jump detection
src/logos.py               Company logos (logostream, Parqet, FMP), brand colour extraction, chart colour assignment
src/picker.py              Custom component: searchable security picker with logo tiles
src/money.py               Wealth paths, money summaries, per-security money contributions, money formatting
src/fx.py                  FX symbols, quote-direction verification, alignment, conversion and per-date detail
src/returns.py             Base-currency prices, common calendar, returns, annualization
src/statistics.py          Estimators (mu, Sigma incl. Ledoit-Wolf, EWMA), portfolio/asset/tail statistics,
                           Euler risk decomposition, bootstrap, Monte Carlo, crisis periods
src/optimization.py        Constraint sets and all optimizers with feasibility/optimality checks
src/frontier.py            Constrained efficient frontier
src/analysis.py            Horizon orchestration and coverage rules
src/backtesting.py         Walk-forward backtest (used by reports)
src/backtest_lab.py        Backtesting lab: train/test split, 10 strategies, contributions, costs, forecast cones,
                           Kupiec test, XIRR, what-if scenarios
src/reporting.py           CSV/XLSX/PNG/HTML/PDF exports and configuration snapshot
src/charts.py              Plotly figures (shared by UI and HTML report)
src/synthetic.py           Deterministic synthetic provider (tests + labelled offline demo only)
src/validation.py          Portfolio model, input validation, price data-quality checks
tests/                     pytest suite (unit, integration with mocked provider, invariants, UI acceptance)
data/                      SQLite databases, settings.json, backups/
outputs/                   Reports written by "Save every format to the outputs folder"
```

## 5. Database

| Table | Key | Purpose |
|---|---|---|
| `securities` | ticker | name, market, exchange, currency, first/last observed date, provider, validation status |
| `daily_prices` | (ticker, date) | open, high, low, close, adj_close, volume, provider timestamp |
| `exchange_rates` | (base, quote, date) | `rate` = quote-currency units per 1 base-currency unit |
| `fx_series` | (base, quote) | Yahoo symbol, direction verification result, history checked |
| `portfolio_configurations`, `portfolio_market_allocations`, `portfolio_holdings` | portfolio | saved portfolios |
| `allocation_templates` | name | saved market allocations |
| `download_log` | id | every request: window, status, rows received / inserted / updated, error |
| `corporate_actions` | (ticker, date, action) | splits and dividends reported by Yahoo |
| `price_repairs` | id | every automatic repair: kind, dates, factor, detail |
| `security_logos` | ticker | logo source, status, PNG (when the source allows storing it), primary colour |
| `schema_version`, `app_metadata` | — | migrations |

**Incremental update logic** (per symbol): target window = last 15 calendar years up to the last *completed*
session (the exchange-local clock is compared with the configured close time + 45 min; Yahoo's `end` is
exclusive, so the request end is the day after the last completed session). If nothing is stored the whole
window is requested; otherwise missing older history is back-filled once (recently listed stocks are not
re-queried) and a 10-day overlap is re-downloaded and UPSERTed so provider revisions replace old values and new
dates are appended. Primary keys make duplicate ticker-date rows impossible. Every write is a transaction; a
failed refresh is logged and the stored data are untouched. A symbol refreshed in the last 12 hours is served
from the database without a network request. Backups use SQLite's online backup API (*Historical Database →
Back up now / Restore*); a restore first writes a safety backup.

**Splits and reverse splits.** Yahoo's split adjustment is sometimes wrong around a split (example found with
real data: the Nikkei 225 ETF `1321.T`, split 100:1, had some days still on the old price basis, which produced
fake ±99% daily returns). Every download is now requested with `actions=True, repair=True` and then checked by
`src/corporate_actions.py`:

1. Splits and dividends are stored in `corporate_actions`.
2. *Temporary blocks* off by a split factor (or ×100, the typical unit error) relative to both neighbours are
   rescaled (`SCALE_BLOCK`).
3. A history left on the *pre-split basis* (a jump on the split date that matches the split ratio) is divided by
   the ratio (`PRE_SPLIT`).
4. The adjusted close is validated (positive, adjustment factor non-decreasing in time); if it is broken it is
   recomputed from closes, splits and dividends (`RECOMPUTED_ADJ`).
5. On every update the overlap window is compared with the stored data; if the price basis changed (a new split
   or a provider re-adjustment) the whole history of that symbol is downloaded again and replaced in one
   transaction (`rebase`). Old databases with broken data are fixed this way automatically on the next update.

Every repair is logged in `price_repairs` and shown in *Historical Database → Splits and repairs* and in *Find
securities*. Any remaining split-sized jump is reported as a data warning on the analysis pages.

**Data quality.** Rows with missing/zero/negative closes are discarded (never filled); high<low and >50% daily
moves are kept and flagged. Missing sessions are classified with `exchange_calendars` (holidays are not counted
as missing): isolated provider gaps, long gaps (possible suspension/outage), trailing gaps (stale/possibly
delisted), observations on non-session days.

## 6. Mathematical methods

**Currency conversion (price level, before returns).** For a security quoted in currency F and base B:
`P_B(t) = P_F(t) / d · FX_{F→B}(t)` with `d = 100` for minor units (`GBp`, `ZAc`, `ILA`). Hence
`1 + r_B = (1 + r_F)(1 + r_FX)` — the cross term is never dropped. FX symbols are `FFFBBB=X`; their direction
(B per F) is **verified** by downloading the inverse symbol `BBBFFF=X` and requiring the median product to be
1 ± 2% (otherwise the series is rejected). If the direct symbol does not exist (e.g. `INRMXN=X` during testing)
the series is **triangulated** through USD and labelled as derived. For each stock date the same-day FX rate is
used; if missing, the latest rate at most 3 calendar days older (configurable) is carried and counted; otherwise
the observation is dropped. Counts are shown in *Settings and Data Quality*. The **Currency conversion** page shows,
for each security, the currency, the minor-unit divisor, the FX pair and its verification, the rate used on every
date (with the FX date actually used and how many days it was carried), and the decomposition
`1 + r_base = (1 + r_local)(1 + r_FX)` in money, plus a "what if the currency had not moved" scenario.

**Money amounts.** All results are also shown in money in the base currency. The capital is the portfolio's total
capital (Builder, step 1) or, if none is set, the default in Settings (100,000; the demo portfolio uses 1,000,000). A
constant-weight portfolio is replayed as `V_t = V_{t-1}(1 + r_p,t)`, `V_0` = capital. Money contribution of
security i: `Σ_t V_{t-1} w_i r_{i,t}`; the contributions add up exactly to `V_T − V_0`. Worst fall in money =
`max_t(max_{s≤t} V_s − V_t)` (a non-negative peak-to-trough loss; equivalently, the minimum of `V_t − max_{s≤t} V_s`). VaR/CVaR and Monte Carlo results are scaled by the current value.

**Common calendar.** Portfolio analysis uses only dates on which every holding has a converted price; the share
of dropped dates is reported per horizon. Returns spanning a dropped date are multi-day returns. They are currently treated as one observation by the conventional 252/52 annualization, so annualized mean, volatility, Sharpe and covariance estimates can be biased when common-date gaps are frequent or uneven. Asynchronous
closes also affect cross-market correlation; weekly frequency (Fridays) is available in Settings, but does not eliminate data gaps.

**Returns and annualization** (n = 252 daily or 52 weekly, an approximation):
`r_t = P_t/P_{t-1} − 1`, `g_t = ln(P_t/P_{t-1})`, cumulative `∏(1+r_t) − 1`, `μ_ann = n·mean(r)`,
`σ_ann = √n·sd(r)` (ddof 1), CAGR `(P_end/P_start)^{1/T} − 1` with T = elapsed days / 365.25.
Portfolio returns are constant-weight (rebalanced each period): `r_p = Σ w_i r_i`, so `μ_p = w'μ` and
`σ_p² = w'Σw` hold exactly in sample (verified by tests).

**Risk-free rate.** Default 6.5% MXN, an *effective annual assumption* (not a market quote), editable.
Per-period `r_f = (1+R_f)^{1/n} − 1`; the optimizer uses `n·r_f`, which makes the Markowitz Sharpe
`(μ_p − n r_f)/σ_p` identical to the historical `√n·mean(r − r_f)/sd(r)`.

**Statistics.** Sharpe (per period and annualized), Sortino (downside deviation vs. `r_f`), maximum drawdown
(peak/trough dates), Calmar (CAGR/|MDD|), best/worst day and best/worst rolling 21-day period, skewness, excess
kurtosis, Jarque-Bera, historical VaR/CVaR 95/99% (per period, as positive losses), positive/negative frequency,
benchmark beta, alpha, tracking error, information ratio. Euler risk decomposition:
`MCR_i = (Σw)_i/σ_p`, `CR_i = w_i·MCR_i`, `Σ CR_i = σ_p`. Concentration: HHI and effective N by security and
market, currency exposure, diversification ratio `w'σ/σ_p`, covariance eigenvalues and condition number.

**Estimators.** μ: arithmetic (default), geometric `(∏(1+r))^{n/T} − 1`, EWMA (λ), or user-defined. Σ: sample
(default), Ledoit–Wolf (2004) shrinkage toward a scaled identity (checked against scikit-learn to 1e-8), or
bias-corrected EWMA. Σ is checked for symmetry and positive semidefiniteness; a non-PSD matrix stops the
optimization (it is never silently repaired); singular/ill-conditioned matrices and T < 10·N are flagged.

**Constraints.** Fixed-market mode: `Σ_{i∈m} w_i = A_m` for every market (implies `Σw = 1`). Alternative,
explicitly labelled mode: global budget only. Long-only `w ≥ 0` by default; optional short selling with a
configured lower bound; optional cap on any stock's total weight. Pre-checks detect infeasible caps
(e.g. 3 stocks × 10% < a 50% market budget).

**Optimizers and certification** (every result reports solver status, budget/market/bound residuals, and is
marked invalid if any residual exceeds 1e-6):

| Portfolio | Method | Certification |
|---|---|---|
| Minimum variance | convex QP, SLSQP with analytic gradients from two starts | global (convex), starts must agree |
| Maximum Sharpe | Charnes–Cooper transform → convex QP in (y, κ): `min y'Σy` s.t. `(μ−r_f)'y = 1`, `Ay = κb`, `κ·lb ≤ y ≤ κ·ub`; cross-checked by direct multi-start and all feasible comparison portfolios | global (convex); falls back to labelled "approximate" if no feasible portfolio beats r_f |
| Maximum return | linear program (HiGHS) | exact |
| Maximum risk | max of a convex function ⇒ a polytope vertex. Long-only without caps: exhaustive enumeration of "one stock per market" vertices (≤ 200,000) | exact; otherwise multi-start, labelled *approximate, not certified* |
| Equal weight | equal within markets, market budgets preserved | definition |
| Minimum CVaR 95% | Rockafellar–Uryasev LP on historical scenarios | exact (in-sample) |
| Maximum diversification | same transform with σ_i in place of μ_i − r_f | global (convex) |
| Max return at target volatility | convex program, multi-start | optimal (convex) |

Invariants enforced at run time: the minimum-variance portfolio may not have higher volatility than any other
verified feasible portfolio, and no verified feasible portfolio (including frontier points) may have a higher
Sharpe than the maximum-Sharpe solution — otherwise certification is downgraded.

**Efficient frontier.** Feasible return bounds `[R_min, R_max]` from two LPs; GMV solved first; 50 targets
(configurable) across the range (endpoints moved inside by 1e-9 of the width), each solved as
`min w'Σw s.t. w'μ = R` + constraints with warm starts outward from the GMV. Each point is checked (solver,
target residual, constraints). Targets above the GMV return form the efficient branch, below it the inefficient
branch. The tangency portfolio is shown only when the maximum-Sharpe solution is valid. Hover shows return,
volatility, Sharpe and weights; frontier points and weights are exportable.

**Horizons and coverage.** Each horizon ends at the last common date and starts `H` calendar years earlier.
*Strict* (default): a horizon is COMPLETE only if every holding has data back to its start (±10 days) and at
least the minimum number of observations; otherwise it is reported INCOMPLETE with no statistics. Two explicitly
labelled alternatives: *common universe* (drops short-history holdings, rescales within-market weights and,
if a market empties, the remaining market budgets) and *available history* (all holdings, shorter sample, actual
span reported). Membership never changes silently; dates and observation counts are shown with every result.

**Custom window.** The five fixed horizons are shortcuts; the horizon selector also offers **Custom**: quick
windows (3/6 months, year to date, 2/7 years, since every holding trades, all stored history) or any start and end
date (`settings.custom_horizon_start/end`; an empty end follows the latest data). It is analyzed exactly like a fixed
horizon (same coverage modes, statistics, optimizers, frontier, risk, reports; sheets `custom_*`), labelled with its
true length and dates (`src/horizons.py`: `CustomHorizon` is a float equal to its length in years, so every formula
keeps working, but it never equals the integer horizons). Only the custom window is recomputed when it changes.
Windows under a year carry a warning that annualized figures are extrapolated; when the window has fewer
observations than the minimum, the banner offers to accept them.

**Reconstructed history for IPOs (fourth, labelled mode).** A holding listed recently blocks every horizon of the
original portfolio. Cutting every other holding to the IPO's few months (*available history*) throws away years of
real data and makes every estimate noisy; dropping the IPO (*common universe*) changes the portfolio. The
*reconstructed* mode keeps every holding and the full horizon and estimates only the IPO's missing early returns
(`src/backfill.py`; Stambaugh 1997, Page 2013, Jiang & Martin 2016): factors are portfolios that exist over the
whole window (its market index when stored, which the app downloads in this mode; the other holdings of its market;
the rest of the portfolio with your weights), `k = min(3, S // 60)` factors for `S` real returns; excess-return OLS
`y − rf = a + b'(F − rf) + e` on the real part; each missing period is `rf + b'(F_t − rf) + e*_t` with `e*` drawn in
5-day blocks from the real residuals and centred at zero (fixed seed). The IPO's abnormal return `a` is not carried
back, so a hot first quarter is not annualized over years; its own real returns and every other holding's prices
are never changed. At least 20 real daily returns are required (Settings). Everything reconstructed is labelled:
mode label, "with reconstruction" in the horizon selector, a table per holding (first real date, reconstructed
share, factors, betas, R², the abnormal return left out), a grey band on the growth and drawdown charts, the
exports (`h{h}y_reconstructed`) and the HTML report. In the Backtesting lab the reconstruction is fitted only on
real returns up to the end of training (never on test data) and the test period must use real prices only.
Validation on real data (history of AMXB.MX, NVDA, 7203.T and PETR4.SA deliberately cut, results compared with the
true full history) is in `TEST_RESULTS.md`.

**Missing data is fetched, and every gap is explained.** Before an analysis runs, the app checks whether any
holding has no stored prices (step 3 was skipped or its download failed) or whether a currency has no stored
exchange rate to the base currency (for example after the base currency was changed in Settings). Either case
used to make *every* horizon INCOMPLETE. The analysis pages now download what is missing once per session (with a
visible status), and when a horizon still has no statistics the banner says why for each security: prices not
downloaded, exchange rate missing, history too short (first date and years available, and the date the horizon
needs), or too few common trading dates. It offers the fix that applies: *Download what is missing*, *Analyze
with the available history* or *Leave out* the short-history securities (the labelled alternative modes).

**Backtesting lab.** The user picks a *training* window (default: all history up to 2025-12-31) and a *test*
window (default: 2026-01-01 to the last date). Two modes: *static* (weights estimated once on the training window,
then held/rebalanced during the test, the honest "train then predict" setting) and *walk-forward* (re-estimated at
each rebalance with an expanding or rolling window, using only returns strictly before that date; a test truncates
the future and checks the weights are unchanged). Ten strategies: your weights, equal weight, inverse volatility,
risk parity (equal risk contribution), minimum variance, maximum Sharpe, maximum diversification, minimum CVaR,
maximum return and the benchmark. Options: rebalancing (none, monthly, quarterly, semiannual, annual), initial
capital and monthly contributions, commission + slippage in bps of traded value and an FX cost on foreign
trades. Money is simulated in holdings (`W_t = Σ h_i P_i`); the time-weighted return chains
`W_end/(W_prev + flow) − 1`; the money-weighted return is the XIRR of the cash flows. **Forecast vs reality:**
from the training returns, 2,000 paths are simulated over the test length (block bootstrap or normal), giving a
5–95% cone; the realized path's percentile and the share of test days outside the 95% VaR are reported with
Kupiec's POF test. **What-ifs:** different entry dates (every month of the test window), no currency moves, an FX
shock (±x% on every foreign currency), excluding one or more stocks (weights renormalized within markets), the
worst historical window of the same length replayed, and a projection beyond the last date.

## 7. Adding a market or exchange

No code changes are needed. Create `data/markets_custom.json` (in your data directory):
```json
[
  {"market_id": "CHILE", "name": "Chile", "country": "Chile", "exchanges": ["Bolsa de Santiago"],
   "currency": "CLP", "timezone": "America/Santiago", "calendar": "XSGO", "ticker_suffixes": [".SN"],
   "close_time": "16:00", "benchmark": "^IPSA", "benchmark_name": "S&P IPSA"}
]
```
`calendar` is an `exchange_calendars` code (use `null` for a weekday heuristic). Restart the app: the market
appears in the Builder, Explorer and optimizer. If the currency's symbol `CLPMXN=X` exists on Yahoo it is used and
verified; otherwise it is triangulated through USD. To make it permanent, add the same entry to
`DEFAULT_MARKETS` in `src/config.py`. (The Chile values above are an example, not tested.)

## 8. Translation module (English / Español)

**How it works.** English text in the code is the message key: `t("Market allocation")`. `src/i18n.py` looks it up
in `src/locales/<code>.json` for the active language and falls back to English when a key is missing, so the app
never breaks. Placeholders use `str.format` names (`t("{n} securities", n=8)`); `{period}` and `{span}` are filled
from `h=` with correct plurals ("1 year / 5 years", "1 año / 5 años"). Long texts (the guide, formula panels, report
sections) are Markdown files in `src/locales/docs/<code>/`. The active language is a context variable set from
`settings.language` at the start of every Streamlit run; engine messages (warnings, optimizer notes, validation
errors) and reports are produced in that language. Stored database logs and exported sheet/column names stay in
English so files and scripts are language-independent.

**Adding another language** (e.g. Portuguese):
```bash
cp src/locales/es.json src/locales/pt.json          # then translate the values; set "_language_name": "Português"
cp -r src/locales/docs/es src/locales/docs/pt        # translate the Markdown texts
python -m src.i18n_extract                           # reports missing keys and placeholder mismatches
pytest tests/test_i18n.py -q                         # completeness test runs for every catalog
```
The new language appears in the selector automatically.

**Adding new text to the app.** Wrap it in `t("...")` (or `N_("...")` for constants translated later), run
`python -m src.i18n_extract --write es` to append the new keys with empty values, and fill them in. The test suite
fails while any key is untranslated or a translation drops a `{placeholder}`.

**Dark mode.** The sidebar switch **Dark mode / Modo oscuro** changes the whole interface: Streamlit's native
dark theme (`[theme.dark]` in `.streamlit/config.toml`, so tables, menus and widgets switch too), the custom CSS
variables (`CSS_VARS` in `src/ui.py`), the logo and the Plotly palette (`charts.set_dark()`; dark chart colours
were validated for contrast and colour-blind separation on the dark surface). Streamlit can only change theme in
the browser, so the switch stores Streamlit's own theme choice in the browser's localStorage and reloads the
page once. The portfolio being edited is autosaved to `data/working_portfolio.json`
(`working_portfolio_demo.json` in demo mode), so it survives the reload and restarts. Exported HTML, PDF and PNG
reports always use the light palette.

## 9. Tests

```bash
pytest -q                                   # 107 tests, no network (the 2 live tests are skipped)
GPL_LIVE_TESTS=1 pytest tests/test_live_yahoo.py -v     # optional, real Yahoo downloads
```
Results on 2026-10-31 (Python 3.13.18, Linux): **105 passed, 2 skipped** offline (the skipped ones are the live
tests); **both live tests passed** separately: (1) validated and downloaded AAPL, WALMEX.MX, 7203.T, PETR4.SA,
rejected an invalid `.MX` symbol, refresh added no duplicate rows, USD→MXN direction verified, 1y and 5y horizons
complete, all optimizers valid; (2) downloaded the Nikkei ETF `1321.T` through its 100:1 split with no split-sized
jump left in the stored series (largest daily move below 30%), and fetched NVDA and WALMEX.MX logos with a primary
colour. Details: `TEST_RESULTS.md`.

Coverage: allocation and within-market sums, global-weight conversion, ticker normalization, simple/log returns,
FX conversion with known values (incl. cross term and pence), FX alignment/staleness, direction verification,
annualization, covariance and quadratic form, Sharpe consistency, Ledoit–Wolf vs scikit-learn, VaR/CVaR,
drawdown, Euler sums, synthetic data reproducing known moments, every optimizer's residuals and optimality
invariants (random feasible portfolios, brute-force vertex enumeration, closed-form GMV), frontier feasibility
and monotonicity, infeasible caps, short mode, database duplicate prevention/UPSERT, backup/restore,
incremental downloads with a mocked provider (invalid ticker, provider outage, empty response, cache, inverted
FX), horizon coverage modes, minimum observations, export values equal on-screen values (Excel read back),
no look-ahead in backtests, split/reverse-split repair (temporary blocks, ×100 errors, pre-split history, broken adjusted close, dividend rebasing, automatic re-download when the basis changes), Backtesting-lab accounting (money identity, contributions, costs, XIRR, Kupiec, forecast cone, what-ifs), money contributions that sum to the gain, FX conversion detail, logo source order and brand colours, and headless UI acceptance tests that build a portfolio through the interface,
download, analyze, click every analysis control and render all 13 pages, in English and in Spanish (language
switch from the sidebar, Spanish buttons, Spanish HTML/PDF reports and engine messages), plus i18n tests for
catalog completeness, placeholder consistency, English fallback, docs per language and no variable shadowing `t()`.

## 10. Incomplete, simplified or unverified

* **Live-tested markets:** USA, Mexico, Brazil, Japan, Australia, India and UK equities plus `^GSPC`. The other
  markets' ticker suffixes and benchmark symbols (e.g. `^J203.JO`, `^TASI.SR`, `000001.SS`) are configured
  defaults that have **not** been verified against Yahoo; the Explorer shows whether data exist locally.
* **Risk-free rate** is a constant; a historical risk-free series is not implemented.
* **Optional constraints** implemented: maximum stock weight and short-selling bounds. Not implemented: minimum
  number of holdings, sector limits, turnover limits. Risk parity and inverse volatility exist only as
  Backtesting-lab strategies.
* **Forecasts** in the Backtesting lab are simulations from past returns, not predictions; the cone shows the
  range the model expected, and the lab reports how often reality fell outside it.
* **Logos.** Sources, in order: logostream.dev (only with your free API key, Settings → Money and appearance; its
  free plan requires the attribution shown in the footer and does not allow storing images, so they are kept in
  memory only unless you enable storing), Parqet and Financial Modeling Prep public logo URLs (stored in the
  database). ETFs, indices and some small companies have no logo: a coloured tile with initials is shown instead.
  logostream's symbol mapping for non-US tickers was not tested (no API key available during development).
* **Split repair** covers the patterns found in Yahoo data (temporary blocks off by a split factor or ×100, a
  history left on the pre-split basis, a broken adjusted close). A genuine price move of exactly a split ratio on
  a day without a reported split would not be repaired; it is reported as a warning instead.
* **Turnover** is reported in the Backtesting lab only (the main analysis assumes constant weights).
* **PNG/PDF** figures are static matplotlib renderings; the interactive versions are in the app and HTML report.
* **Exchange-calendar gap classification** is heuristic (it cannot prove a suspension or delisting).
* Yahoo throttles some endpoints (HTTP 401/429 observed). Metadata falls back to the chart endpoint; if both fail
  the ticker is reported as a provider error (not judged) rather than accepted or rejected.
* The most recent FX bar can be intraday when downloaded during trading; it is revised by the next refresh.
* Number and date formats are the same in both languages (decimal point, ISO dates), matching Mexican usage.
* The dark/light choice is stored per browser (Streamlit's own setting); a different browser opens in light mode
  until the switch is used there.
* Verified on Linux; Windows/macOS are expected to work (pathlib everywhere, no absolute paths) but were not run.
