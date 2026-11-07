**Money figures** apply percentages from the horizon to [[capital]]:

* **Typical swing per year** = annual volatility × capital.
* **Bad day (VaR 95%)**: the historical 5% quantile of daily returns, $-q_{5\%}(r)$, × capital: on one day out of twenty the loss was at least this large.
* **Average of the worst days (CVaR 95%)** = mean of the returns below that quantile × capital.
* **Worst fall** = the largest peak-to-trough drop of the portfolio value.

**Where the risk comes from** (Euler decomposition): $\sigma_p = \sum_i w_i\,(\Sigma w)_i/\sigma_p$. Each term is the volatility contributed by one stock; they add up to $\sigma_p$ exactly. A stock whose share of risk is larger than its share of money adds more risk than its weight suggests.

**Concentration**: HHI $=\sum w_i^2$, effective number of stocks $=1/\text{HHI}$; diversification ratio $=\sum w_i\sigma_i/\sigma_p$ (above 1 = diversification removes risk).

**Reliability**: block bootstrap (1,000 resamples of 21-day blocks) gives confidence intervals; the Monte Carlo draws 5,000 normal paths with the estimated $\mu$ and $\Sigma$ — an explicit, simple assumption, not a forecast.
