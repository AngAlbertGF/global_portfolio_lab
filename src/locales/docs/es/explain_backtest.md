**1. Entrenamiento.** Solo se usan los rendimientos entre las fechas de entrenamiento. Con ellos el modelo estima $\mu$ y $\Sigma$ (con los estimadores que elijas) y cada estrategia escoge sus pesos con las mismas restricciones que el resto de la app (presupuestos por mercado, long-only, topes). Estrategias: tus pesos fijos, pesos iguales, mínima varianza, máximo Sharpe, máxima diversificación, paridad de riesgo (igual contribución al riesgo), inverso de la volatilidad, mínimo CVaR, volatilidad objetivo y máximo rendimiento.

**2. Pronóstico.** El último día de entrenamiento cada estrategia simula entre 500 y 5,000 trayectorias posibles para el periodo de prueba, con las mismas aportaciones mensuales:

* *Bootstrap histórico*: se remuestrean en bloques (21 días por defecto) los rendimientos del portafolio en el entrenamiento; conserva colas gruesas y rachas cortas.
* *Normal*: rendimientos diarios independientes con media $w^\top\mu/n$ y varianza $w^\top\Sigma w/n$.

El cono muestra los rangos 5–95% y 25–75% y la mediana. El **percentil** del resultado real dentro del cono indica si el modelo fue optimista (percentil bajo) o pesimista (percentil alto). Su **VaR 95%** diario se compara con los días de prueba: cerca de 5% de los días deberían rebasarlo; un valor p de Kupiec menor a 0.05 rechaza el pronóstico.

**3. Prueba (lo que pasó de verdad).** Las posiciones en dinero $h_i$ crecen con el rendimiento de cada día. En las fechas de rebalanceo se regresan a los pesos objetivo; el monto operado paga comisión + deslizamiento, más un costo de conversión de moneda en los valores de otra divisa. Las aportaciones se invierten el primer día hábil de cada mes según los pesos objetivo.

* *Se entrena una vez*: pesos objetivo fijos al final del entrenamiento.
* *Sigue aprendiendo*: en cada rebalanceo el modelo se vuelve a estimar con los datos hasta el día anterior (ventana creciente o móvil).

**4. Resultados en [[ccy]].** Valor final, ganancia = valor final − dinero invertido, rendimiento ponderado por tiempo $\prod(1+r_t)-1$ (sin flujos, con costos), rendimiento ponderado por dinero (TIR de tus flujos), volatilidad, Sharpe, caída máxima, costos y rotación. Las contribuciones por acción suman la ganancia más los costos.

**5. ¿Qué pasaría si…?** Otra fecha de entrada (primer día de cada mes, pesos constantes), monedas congeladas (cada acción en su propia moneda), un movimiento cambiario adicional repartido en la prueba, quitar acciones (pesos redistribuidos dentro de cada mercado), repetir la peor racha del entrenamiento, y una proyección hacia adelante desde hoy con el modelo reentrenado con todos los datos.

Todos los pronósticos son simulaciones con supuestos explícitos; el comportamiento pasado no garantiza resultados futuros.
