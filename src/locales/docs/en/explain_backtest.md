**1. Training.** Only the returns between the training dates are used. With them the model estimates $\mu$ and $\Sigma$ (the estimators you choose) and each strategy picks its weights under the same constraints as the rest of the app (market budgets, long-only, caps). Strategies: your fixed weights, equal weight, minimum variance, maximum Sharpe, maximum diversification, risk parity (equal risk contribution), inverse volatility, minimum CVaR, target volatility and maximum return.

**2. Forecast.** At the last training day each strategy draws 500–5,000 possible paths for the test period, with the same monthly contributions:

* *Historical bootstrap*: the training-period portfolio returns are resampled in blocks (default 21 days), keeping fat tails and short streaks.
* *Normal*: i.i.d. daily returns with mean $w^\top\mu/n$ and variance $w^\top\Sigma w/n$.

The cone shows the 5–95% and 25–75% ranges and the median. The **percentile** of the real result inside that cone tells whether the model was optimistic (low percentile) or pessimistic (high percentile). Its daily **VaR 95%** is checked against the test days: about 5% of days should breach it; Kupiec's test p-value below 0.05 rejects the forecast.

**3. Test (what really happened).** Holdings in money $h_i$ grow with each day's return. On rebalancing dates they are brought back to the targets; the traded value pays commission + slippage, plus a currency-conversion cost on securities in another currency. Contributions are invested on the first trading day of each month by the target weights.

* *Trained once*: targets fixed at the end of training.
* *Keeps learning*: at every rebalance date the model is re-estimated with data up to the previous day (expanding or rolling window).

**4. Results in [[ccy]].** Final value, gain = final value − money invested, time-weighted return $\prod(1+r_t)-1$ (flows excluded, costs included), money-weighted return (IRR of your cash flows), volatility, Sharpe, drawdown, costs and turnover. Contributions by security add up to the gain plus the costs.

**5. What if…?** Entry date (each month's first day, constant weights), currencies frozen (each stock in its own currency), an extra currency move spread over the test, leaving stocks out (weights re-split inside each market), the worst streak of the training repeated, and a projection forward from today with the model re-trained on all data.

All forecasts are simulations under explicit assumptions; past behavior does not guarantee future results.
