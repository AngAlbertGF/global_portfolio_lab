**Sample**: the horizon's daily (or weekly) returns on the dates where *every* holding traded (common calendar, nothing filled). Prices are adjusted closes converted to [[ccy]].

**Money**: [[capital]] compounded with the portfolio's return, $V_t = V_{t-1}(1+r_{p,t})$. Best/worst day in money = $V_{t-1}\, r_{p,t}$ of that day. Highest value = the maximum of $V_t$. Worst fall in money = largest peak-to-trough drop of $V_t$.

**Percent statistics** ($n$ = [[n]] periods per year, $r_f$ = per-period risk-free from [[rf]] effective annual):

| Statistic | Formula |
|---|---|
| Arithmetic annual return | $n \cdot \bar r$ |
| CAGR | $(V_T/V_0)^{1/\text{years}} - 1$ |
| Volatility | $\sqrt n \cdot s(r)$ (sample, ddof = 1) |
| Sharpe | $\sqrt n\, \overline{(r - r_f)}/s(r)$ |
| Sortino | $n\,\overline{(r-r_f)} / (\sqrt n \cdot DD)$, $DD = \sqrt{\tfrac1T\sum \min(r_t-r_f,0)^2}$ |
| Max drawdown | $\min_t (W_t/\max_{s\le t} W_s - 1)$ |
| VaR / CVaR | historical 5% / 1% quantile of returns and the mean beyond it |

**Compare with**: the optimized portfolios are replayed with their own weights on the same returns (in-sample). The benchmark is the index you chose in Settings, converted to [[ccy]]. Benchmark alpha is Jensen's alpha: `n * mean((r_p - r_f) - beta * (r_b - r_f))`.

**Monthly returns**: $\prod (1+r_t) - 1$ inside each calendar month.

**Each security**: weight = market allocation × share inside the market. Growth = cumulative return of the stock in [[ccy]]. Share of risk = Euler contribution to volatility, $w_i(\Sigma w)_i/\sigma_p$, as a percentage of $\sigma_p$. Money made = $\sum_t V_{t-1} w_i r_{i,t}$; the column adds up to the total gain.

**Reconstructed history (IPOs)** — only in that mode. For a holding with $S$ real returns inside a horizon of $T$ periods: (1) factors = its market index (when stored), the average of the other holdings of its market and the rest of the portfolio with your weights, using $k=\min(3, \lfloor S/60\rfloor)$; (2) excess-return regression on the $S$ real days, $y_t-r_f = a + b'(F_t-r_f) + e_t$; (3) each missing day is $\tilde y_t = r_f + b'(F_t-r_f) + e^*_t$, with $e^*$ resampled in 5-day blocks from the real residuals and centred at zero. The extra return $a$ is **not** carried back. The new holding's mean is therefore pulled towards the one its betas imply in proportion to the reconstructed share, its volatility and correlations come from its real betas and own risk, and every other holding keeps 100% real data. Method of Stambaugh (1997) and Jiang and Martin (2016) for histories of unequal length.
