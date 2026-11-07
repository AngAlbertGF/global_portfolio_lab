**Cada punto** es un portafolio ubicado por su rendimiento esperado anual $\mu_p = w^\top\mu$ (vertical) y su volatilidad anual $\sigma_p = \sqrt{w^\top\Sigma w}$ (horizontal), ambos estimados en el horizonte elegido.

**La curva** se construye resolviendo, para 50 rendimientos objetivo entre el menor y el mayor factibles, $\min_w w^\top\Sigma w$ sujeto a $\mu^\top w = R$, tus presupuestos por mercado y los límites de peso. La parte superior (desde el punto de mínima varianza hacia arriba) es la frontera eficiente.

**Al hacer clic en un punto** ves su composición y su traducción a dinero para [[capital]]:

* ganancia esperada por año = $\mu_p \times$ capital;
* oscilación típica por año = $\pm\,\sigma_p \times$ capital (una desviación estándar: cerca de dos de cada tres años dentro, si los rendimientos fueran normales).

Ambas son estimaciones **dentro de muestra** con datos históricos, no pronósticos; el *Laboratorio de backtesting* prueba qué pasa fuera de muestra. La línea punteada es la línea del mercado de capitales desde la tasa libre de riesgo hasta el portafolio de máximo Sharpe. Las acciones individuales se dibujan con su color de marca.
