* **Prices**: Yahoo adjusted close (split and dividend adjusted; the provider can revise history). Converted to
  **[[base]]** *before* returns are computed: $P^{base}_t = P^{local}_t / d \cdot FX_t$ ($d$ = 100 for GBp/ZAc
  quotes), so $1+r^{base} = (1+r^{local})(1+r^{FX})$.
* **Common calendar**: only dates on which every holding has a price; no price is ever filled. An FX rate may be
  carried at most [[staleness]] calendar days.
* **Returns**: $r_t = P_t/P_{t-1} - 1$. Annualization with $n = [[n]]$ periods per year (an approximation):
  $\mu = n\,\bar r$, $\sigma = \sqrt n\, s_r$. CAGR uses the actual elapsed time.
* **Risk-free rate**: [[rf]] **effective annual** (an assumption, not a verified market yield); per period
  $r_f = (1+R_f)^{1/n}-1$; the optimizer uses $n\,r_f$.
* **Markowitz**: $\mu_p = w^\top\mu$, $\sigma_p^2 = w^\top\Sigma w$, $SR = (\mu_p - n r_f)/\sigma_p$.
  Estimators: $\mu$ = **[[mu]]**, $\Sigma$ = **[[cov]]**.
* **Constraints**: [[constraints]]; [[positions]].
* Optimized results are **in-sample historical estimates**, not forecasts or recommendations.
