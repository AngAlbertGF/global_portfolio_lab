* **Precios**: cierre ajustado de Yahoo (ajustado por splits y dividendos; el proveedor puede revisar la historia).
  Se convierten a **[[base]]** *antes* de calcular rendimientos: $P^{base}_t = P^{local}_t / d \cdot FX_t$
  ($d$ = 100 para cotizaciones en GBp/ZAc), así que $1+r^{base} = (1+r^{local})(1+r^{FX})$.
* **Calendario común**: solo fechas en que todas las posiciones tienen precio; nunca se rellena un precio. Un tipo
  de cambio puede arrastrarse como máximo [[staleness]] días naturales.
* **Rendimientos**: $r_t = P_t/P_{t-1} - 1$. Anualización con $n = [[n]]$ periodos por año (una aproximación):
  $\mu = n\,\bar r$, $\sigma = \sqrt n\, s_r$. El CAGR usa el tiempo transcurrido real.
* **Tasa libre de riesgo**: [[rf]] **efectiva anual** (un supuesto, no un rendimiento de mercado verificado); por
  periodo $r_f = (1+R_f)^{1/n}-1$; el optimizador usa $n\,r_f$.
* **Markowitz**: $\mu_p = w^\top\mu$, $\sigma_p^2 = w^\top\Sigma w$, $SR = (\mu_p - n r_f)/\sigma_p$.
  Estimadores: $\mu$ = **[[mu]]**, $\Sigma$ = **[[cov]]**.
* **Restricciones**: [[constraints]]; [[positions]].
* Los resultados optimizados son **estimaciones históricas dentro de muestra**, no pronósticos ni recomendaciones.
