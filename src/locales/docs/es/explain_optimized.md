**Mismos datos, distintos objetivos.** Todos los portafolios usan el $\mu$ y la $\Sigma$ del horizonte y las mismas restricciones (presupuestos por mercado, long-only o el límite de cortos configurado, tope opcional por acción):

| Portafolio | Objetivo | Método |
|---|---|---|
| Mínima varianza | $\min w^\top\Sigma w$ | QP convexo (SLSQP), dos inicios deben coincidir |
| Máximo Sharpe | $\max (w^\top\mu - r_f)/\sigma_p$ | transformación de Charnes-Cooper → QP convexo, con verificación cruzada |
| Máximo rendimiento | $\max w^\top\mu$ | programa lineal (HiGHS), exacto |
| Máximo riesgo | $\max w^\top\Sigma w$ | se revisan todos los vértices (exacto) o se etiqueta como aproximado |
| Máxima diversificación | $\max (w^\top\sigma)/\sigma_p$ | misma transformación que Sharpe |
| Mínimo CVaR 95% | pérdida esperada histórica | LP de Rockafellar-Uryasev, exacto en la muestra |
| Pesos iguales | partes iguales dentro de cada mercado | fórmula cerrada |

Cada resultado se verifica (presupuesto, sumas por mercado, límites, estado del solver) antes de mostrarse.

**Dinero**: "Valdría" reproduce los pesos constantes de cada portafolio durante el horizonte con [[capital]]: $V_T = \text{capital}\prod_t(1 + w^\top r_t)$. Como el optimizador eligió esos pesos *conociendo* estos rendimientos, estas cifras exageran lo que realmente se habría obtenido; el Laboratorio de backtesting lo mide de forma justa.
