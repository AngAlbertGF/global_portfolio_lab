1. The feasible expected-return bounds $[R_{min}, R_{max}]$ come from two **linear programs** over the feasible set.
2. The global minimum-variance (GMV) portfolio is solved first. Targets above it form the **efficient branch**
   (solid line); targets below it form the **inefficient branch** (dotted line).
3. For each of [[points]] targets the solver computes $\min_w w^\top\Sigma w$ subject to $w^\top\mu = R$, the budget
   and market constraints and the bounds. Every solution is checked for solver success and for the target, budget
   and market-sum residuals; failed points are left out of the curve.
4. The tangency portfolio is shown only if the maximum-Sharpe solution is valid and no frontier point beats it.
5. The dashed capital market line starts at $n\,r_f$ = [[rf]].

Estimated optima are **in-sample**: small changes in $\mu$ can move them substantially.
