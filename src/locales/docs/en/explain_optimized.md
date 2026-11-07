**Same data, different objectives.** Every portfolio uses the horizon's $\mu$ and $\Sigma$ and the same constraints (market budgets, long-only or the configured short limit, optional cap per stock):

| Portfolio | Objective | Solver |
|---|---|---|
| Minimum variance | $\min w^\top\Sigma w$ | convex QP (SLSQP), two starts must agree |
| Maximum Sharpe | $\max (w^\top\mu - r_f)/\sigma_p$ | Charnes-Cooper transform → convex QP, cross-checked |
| Maximum return | $\max w^\top\mu$ | linear program (HiGHS), exact |
| Maximum risk | $\max w^\top\Sigma w$ | all polytope vertices checked (exact) or labelled approximate |
| Max diversification | $\max (w^\top\sigma)/\sigma_p$ | same transform as Sharpe |
| Minimum CVaR 95% | historical expected shortfall | Rockafellar-Uryasev LP, exact in-sample |
| Equal weight | equal shares inside each market | closed form |

Every result is checked (budget, market sums, bounds, solver status) before it is shown.

**Money**: "Would be worth" replays each portfolio's constant weights over the horizon with [[capital]]: $V_T = \text{capital}\prod_t(1 + w^\top r_t)$. Because the optimizer chose those weights *knowing* these returns, these figures overstate what you could have obtained; the Backtesting lab measures it fairly.
