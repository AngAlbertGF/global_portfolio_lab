**Each point** is a portfolio located by its expected annual return $\mu_p = w^\top\mu$ (vertical) and its annual volatility $\sigma_p = \sqrt{w^\top\Sigma w}$ (horizontal), both estimated on the selected horizon.

**The curve** is built by solving, for 50 target returns between the lowest and the highest feasible one, $\min_w w^\top\Sigma w$ subject to $\mu^\top w = R$, your market budgets and the weight limits. The upper part (from the minimum-variance point up) is the efficient frontier.

**Clicking a point** shows its composition and translates it into money for [[capital]]:

* expected gain per year = $\mu_p \times$ capital;
* typical swing per year = $\pm\,\sigma_p \times$ capital (one standard deviation: about two years out of three inside, if returns were normal).

Both are **in-sample** estimates from history, not forecasts; the *Backtesting lab* tests what happens out of sample. The dashed line is the capital market line from the risk-free rate through the maximum-Sharpe portfolio. Individual stocks are drawn with their brand color.
