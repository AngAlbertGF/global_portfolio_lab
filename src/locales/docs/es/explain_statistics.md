**Muestra**: los rendimientos diarios (o semanales) del horizonte en las fechas en que *todas* las acciones cotizaron (calendario común, sin rellenar nada). Los precios son cierres ajustados convertidos a [[ccy]].

**Dinero**: [[capital]] capitalizados con el rendimiento del portafolio, $V_t = V_{t-1}(1+r_{p,t})$. Mejor/peor día en dinero = $V_{t-1}\, r_{p,t}$ de ese día. Valor más alto = el máximo de $V_t$. Peor caída en dinero = la mayor baja de $V_t$ desde un máximo.

**Estadísticas en porcentaje** ($n$ = [[n]] periodos por año, $r_f$ = tasa libre de riesgo por periodo a partir de [[rf]] efectiva anual):

| Estadística | Fórmula |
|---|---|
| Rendimiento anual aritmético | $n \cdot \bar r$ |
| CAGR | $(V_T/V_0)^{1/\text{años}} - 1$ |
| Volatilidad | $\sqrt n \cdot s(r)$ (muestral, ddof = 1) |
| Sharpe | $\sqrt n\, \overline{(r - r_f)}/s(r)$ |
| Sortino | $n\,\overline{(r-r_f)} / (\sqrt n \cdot DD)$, $DD = \sqrt{\tfrac1T\sum \min(r_t-r_f,0)^2}$ |
| Caída máxima | $\min_t (W_t/\max_{s\le t} W_s - 1)$ |
| VaR / CVaR | cuantil histórico de 5% / 1% de los rendimientos y el promedio más allá de él |

**Comparar con**: los portafolios optimizados se reproducen con sus propios pesos sobre los mismos rendimientos (dentro de muestra). El benchmark es el índice elegido en Configuración, convertido a [[ccy]].

**Rendimientos mensuales**: $\prod (1+r_t) - 1$ dentro de cada mes calendario.

**Cada acción**: peso = asignación del mercado × participación dentro del mercado. Crecimiento = rendimiento acumulado de la acción en [[ccy]]. Parte del riesgo = contribución de Euler a la volatilidad, $w_i(\Sigma w)_i/\sigma_p$, como porcentaje de $\sigma_p$. Dinero generado = $\sum_t V_{t-1} w_i r_{i,t}$; la columna suma exactamente la ganancia total.

**Historia reconstruida (IPOs)** — solo en ese modo. Para una acción con $S$ rendimientos reales dentro de un horizonte de $T$ periodos: (1) factores = índice de su mercado (si está guardado), promedio de las otras acciones de su mercado y resto del portafolio con tus pesos, usando $k=\min(3, \lfloor S/60\rfloor)$; (2) regresión en exceso sobre los $S$ días reales, $y_t-r_f = a + b'(F_t-r_f) + e_t$; (3) cada día faltante es $\tilde y_t = r_f + b'(F_t-r_f) + e^*_t$, con $e^*$ remuestreado en bloques de 5 días de los residuos reales y centrado en cero. El rendimiento extra $a$ **no** se lleva al pasado. Así la media de la acción nueva se acerca a la que implican sus betas en proporción a la parte reconstruida, su volatilidad y correlaciones salen de sus betas y su riesgo propio reales, y las demás acciones conservan 100% datos reales. Método de Stambaugh (1997) y Jiang y Martin (2016) para historias de distinta longitud.
