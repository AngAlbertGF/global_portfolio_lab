Global Portfolio Lab measures an international stock portfolio in one reporting currency (MXN by default), describes
its history over 1, 3, 5, 10 and 15 years, and compares it with Markowitz-optimized portfolios that respect the market
allocation you chose. Everything is historical and in-sample: it explains the past, it does not predict the future.

## Quick start

**With live data (about five minutes)**

1. Open **Portfolio Builder** and select **Load example**, or type your own percentages so the
   column adds up to 100%.
2. Select **Continue to step 2**. In each market type an exact Yahoo Finance ticker, its share of that market,
   and select **Validate and add**. Examples: `AAPL` and `NVDA` (USA), `WALMEX.MX` (Mexico), `PETR4.SA` (Brazil),
   `7203.T` (Japan), `BHP.AX` (Australia), `RELIANCE.NS` (India).
3. When every market shows a check mark, select **Continue to confirmation**, review the table and select
   **Confirm and download**. The first download stores 15 years of prices and exchange rates; later visits reuse
   them.
4. Open **Dashboard**, **Portfolio Statistics** or **Efficient Frontier**. Analyses run automatically.

**Without internet**

Go to **Settings and Data Quality → Data source and demo**, turn on **Use SYNTHETIC demo database** and select
**Build or rebuild the synthetic demo data**. A demo portfolio loads with made-up prices, clearly labelled on every
page. Turn the switch off to return to your real data; the two databases never mix.

**Dark mode**

Turn on **Dark mode** in the sidebar. The page reloads once and every screen, table, menu and chart switches to
the dark theme; your portfolio and settings are kept. Exported HTML/PDF reports stay light so they print well.
Streamlit remembers the choice in this browser.

**Changing the language**

Use the **Language** menu in the sidebar (or Settings). The whole interface, charts, messages and the HTML/PDF
reports switch immediately. Exported Excel/CSV sheet and column names stay as English identifiers so your scripts
keep working.

## Building a portfolio

**Step 1: market allocation.** Each row is a market. The percentage is the share of total capital invested there.
Markets left at 0% are excluded. The sum must equal 100% (tolerance one millionth of a percentage point); the page
shows how much is still unallocated. *Equal-weight* splits 100% evenly across the markets you pick, and templates
let you save and reuse an allocation.

**Step 2: securities.** Inside each market, every stock gets a share of *that market's* allocation, and those shares
must add up to 100%. The total portfolio weight is

> total weight = market allocation × within-market share

so NVDA at 25% of a 80% USA allocation is 20% of the portfolio. Rules the builder enforces:

* Tickers must be exact Yahoo symbols with their exchange suffix (`.MX`, `.SA`, `.T`, `.AX`, `.NS`, `.L` ...).
  Company names are rejected; the app never swaps a symbol for another.
* A ticker can appear only once.
* If a stock trades in a different currency than its market (for example `VALE` in USD under Brazil) you get a
  warning; conversion always uses the stock's own currency.
* "Provider error" means Yahoo did not answer, not that the ticker is wrong. Nothing is added; try again.

**Step 3: confirm and download.** The table shows names, exchanges, currencies, both weights, what is already
stored and what will be requested. Downloads are incremental: only missing history and a short recent overlap are
requested, and a failed download never deletes stored data. Save the portfolio to reload it later from the expander
at the top of the builder.

## The pages

The menu follows the work in three stages: **1 · Build**, **2 · Analyze**, **3 · Simulate and export**. The
Dashboard shows the same map with a ✓ on each finished stage. Every page starts with one sentence on what you are
looking at and ends with **How was this calculated?**, which lists the data used and the formulas.

* **Dashboard**: map of the app, composition and what your capital would have become (final value, gain, worst
  fall in money), who made the money, and a frontier preview.
* **Portfolio Builder**: in step 2, *Pick from your database* lists the securities you already downloaded, with their
  logo, name and chart color; *Add a new ticker* takes any exact Yahoo symbol.
* **Find securities**: search your database by company name, look up any new ticker, see its prices with splits
  marked, its dividends and any repair applied to provider data.
* **Historical Database**: refresh tickers, stored history, splits and repairs, exchange rates, logos, integrity
  checks, backups and the download log.
* **Portfolio Statistics**: per horizon, what your capital became (in money and percent), growth compared with the
  benchmark or any optimized portfolio, drawdown, monthly-returns calendar, one row per security with its logo,
  weight, growth sparkline and the money it made — and every statistic in the tables below.
* **Currency conversion**: the exchange rate used for every price, with a worked example for any stock and day, the
  rates over time, and how much of the result came from the currency.
* **Efficient Frontier**: change the model settings and click any point to see its composition and its expected
  gain and typical yearly swing in money.
* **Optimized Portfolios**: one card per portfolio with what your capital would be worth, compositions in brand
  colors, comparisons and every validation detail.
* **Risk Analysis**: risk in money (bad day, worst days, worst fall), where it comes from, concentration, tails,
  confidence intervals, sensitivity and Monte Carlo.
* **Backtesting lab**: train on a period you choose (by default up to 2025-12-31), let each strategy decide and
  forecast, then test on the later period (by default from 2026-01-01) in money, with costs and monthly
  contributions; forecast-vs-reality checks and a set of *what if…?* scenarios.
* **Reports and Exports**: Excel, CSV, HTML, PDF and PNG files, including money tables, splits and repairs.
* **Settings and Data Quality**: language, default capital, logos and brand colors, currency, estimators,
  constraints, folders and demo data.

**Logos and colors.** Logos are fetched once per ticker from Parqet or Financial Modeling Prep (public images), or
from logostream.dev if you enter a free API key in Settings (the app then shows the required "Logos by
logostream.dev" link). Each security keeps the main color of its logo in every chart, adjusted for contrast.

**Splits.** Downloads include splits and dividends. Errors in provider data (for example the 100:1 split of the
Nikkei 225 ETF 1321.T in October 2026) are repaired, and a split after your last download triggers a full
re-download so that returns never show a false −99% day.

## Reading the results

**Horizons.** 1, 3, 5, 10 and 15 years are shortcuts. **✎ Custom** analyzes the window you choose: quick windows (3
or 6 months, year to date, 2 or 7 years, since every holding trades, all stored history) or free dates. If the end is
the last available date, the window moves forward with new prices. Every holding uses the same real dates of the
window and the result is labelled with its true length ("Horizon 5 months (2026-06-01 to 2026-10-30)"). In windows
shorter than a year the annualized figures are extrapolated from few data and the app says so.

**Horizon status.** *Complete* means every holding has data for the whole horizon. *Incomplete* means at least one
holding was listed later; no statistics are shown for the original portfolio, because a 15-year figure computed on
4 years of data would be misleading. You can then switch to:

* *Common universe*: drops the short-history holdings and rescales the rest (clearly labelled, not your portfolio);
* *Available history*: keeps every holding but uses a shorter sample (the real length is shown);
* *Reconstructed history for IPOs* (recommended when a stock started trading recently): keeps every holding and the
  full horizon. The other holdings use only their real prices; only the missing returns of the new listing are
  estimated, with a factor model fitted on its real returns (its betas to its market index and the rest of the
  portfolio, plus its own real noise, with no extra return). It needs at least 20 real days. Everything
  reconstructed is labelled: reconstructed share per holding, a grey band in the charts and "with reconstruction"
  in the horizon selector.

**Returns.** The *arithmetic* annual return (252 × average daily return) is what Markowitz optimizes. The
*geometric* return (CAGR) is what an investor actually earned per year. With volatile assets the arithmetic figure
is higher; neither is a forecast.

**Sharpe ratio.** Excess return over the risk-free rate per unit of volatility. The default 6.5% MXN risk-free rate
is an assumption; change it to match your period and currency.

**Optimized portfolios.** In standard mode each market keeps exactly the allocation you set; only the stocks inside
each market are re-weighted.

* *Minimum variance*: the least volatile mix.
* *Maximum Sharpe*: the tangency portfolio, best return per unit of risk.
* *Maximum return*: tends to put each market's whole budget in its best historical performer.
* *Maximum risk*: a mathematical benchmark only, never a recommendation.
* *Equal weight*: equal shares inside each market.

The *Certification* column says how sure the solver is: *exact* or *global optimum* is proven; *approximate* is the
best of several searches. Historical optima are very sensitive to estimated returns; the sensitivity tools in Risk
Analysis show how much the weights move.

**Frontier.** The solid line is the efficient branch (best return for each risk level), the dotted line the
inefficient branch. Points to the right of and below the line are dominated. The dashed line from the risk-free
rate through the tangency portfolio is the capital market line.

**Daily data across markets.** Markets close at different hours, so daily correlations between, for example, Tokyo
and New York look lower than they are. Weekly frequency (Settings) reduces this effect.

## Glossary

* **Adjusted close**: price corrected for splits and dividends; used for all returns.
* **Base currency**: the currency in which every price is measured (MXN by default). Prices are converted before
  returns are computed, so currency gains and losses are included.
* **Common calendar**: dates on which every holding has a price. No price is ever invented.
* **Volatility**: annualized standard deviation of returns.
* **Maximum drawdown**: worst fall from a previous peak.
* **VaR 95%**: loss exceeded on 5% of days. **CVaR 95%**: average loss on those worst 5% of days.
* **Sortino ratio**: like Sharpe but penalizing only downside volatility.
* **Calmar ratio**: CAGR divided by the absolute maximum drawdown.
* **Beta**: sensitivity to the benchmark; 1.2 means the portfolio moved 1.2% per 1% of the benchmark.
* **Risk contribution (Euler)**: each stock's share of total volatility; the shares add up to 100%.
* **Ledoit-Wolf shrinkage**: a covariance estimate pulled toward a simpler structure; more stable when there are
  many assets and few observations.
* **Diversification ratio**: weighted average of asset volatilities divided by portfolio volatility; higher means
  more diversification.

## Troubleshooting

* **"Not found"**: check the exchange suffix (Mexico `.MX`, Brazil `.SA`, Japan `.T`, Australia `.AX`, India `.NS`
  or `.BO`, UK `.L`, Canada `.TO`, Germany `.DE`, Hong Kong `.HK`). US stocks have no suffix.
* **"Provider error"**: Yahoo throttled or failed temporarily. Wait a minute and try again; nothing is lost.
* **A horizon says Incomplete**: the red box says why. If a holding is too recent (IPO), use the **Reconstruct the
  short history** button or the Coverage mode selector in Portfolio Statistics.
* **"Insufficient observations"**: lower *Minimum observations* in Settings or use a longer horizon.
* **Weights do not add up**: each market's securities must total 100% of that market; use *Equal-weight this
  market*.
* **Prices look 100 times too large**: London and Johannesburg quote in pence or cents; the app divides by 100
  automatically.
* **Something looks wrong in the data**: open Historical Database, inspect the ticker, run the integrity check and
  retry failed downloads.
