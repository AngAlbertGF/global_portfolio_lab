**Las cifras en dinero** aplican porcentajes del horizonte a [[capital]]:

* **Oscilación típica por año** = volatilidad anual × capital.
* **Día malo (VaR 95%)**: el cuantil histórico de 5% de los rendimientos diarios, $-q_{5\%}(r)$, × capital: en uno de cada veinte días la pérdida fue al menos así de grande.
* **Promedio de los peores días (CVaR 95%)** = promedio de los rendimientos por debajo de ese cuantil × capital.
* **Peor caída** = la mayor baja del valor del portafolio desde un máximo.

**De dónde viene el riesgo** (descomposición de Euler): $\sigma_p = \sum_i w_i\,(\Sigma w)_i/\sigma_p$. Cada término es la volatilidad que aporta una acción; suman $\sigma_p$ exactamente. Una acción cuya parte del riesgo es mayor que su parte del dinero agrega más riesgo del que sugiere su peso.

**Concentración**: HHI $=\sum w_i^2$, número efectivo de acciones $=1/\text{HHI}$; razón de diversificación $=\sum w_i\sigma_i/\sigma_p$ (mayor que 1 = la diversificación elimina riesgo).

**Confiabilidad**: el bootstrap por bloques (1,000 remuestreos de bloques de 21 días) da intervalos de confianza; el Monte Carlo simula 5,000 trayectorias normales con $\mu$ y $\Sigma$ estimadas: un supuesto explícito y sencillo, no un pronóstico.
