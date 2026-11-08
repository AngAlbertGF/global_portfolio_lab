<ul>
<li><b>Precios:</b> cierre ajustado del proveedor (splits y dividendos), convertido a la moneda base a nivel de precio:
P<sub>base</sub> = P<sub>local</sub> / divisor de unidad &times; FX(local&rarr;base). Los rendimientos se calculan después
de la conversión, así que 1 + r<sub>base</sub> = (1 + r<sub>local</sub>)(1 + r<sub>FX</sub>).</li>
<li><b>Calendario:</b> solo fechas de observación comunes (sin rellenar precios). El tipo de cambio puede arrastrarse
hasta el límite de antigüedad configurado; se eliminan las observaciones sin un tipo de cambio admisible.</li>
<li><b>Rendimientos:</b> r<sub>t</sub> = P<sub>t</sub>/P<sub>t-1</sub> &minus; 1; media anual = n&middot;media, volatilidad
anual = &radic;n&middot;desv. est. (n = 252 diaria o 52 semanal, una aproximación); los huecos del calendario común pueden hacer que rendimientos consecutivos abarquen varias sesiones, aunque la anualización conserva este factor fijo. El CAGR usa el tiempo transcurrido
real.</li>
<li><b>Portafolio:</b> pesos constantes (rebalanceo cada periodo), &mu;<sub>p</sub> = w&prime;&mu;,
&sigma;<sub>p</sub><sup>2</sup> = w&prime;&Sigma;w, Sharpe = (&mu;<sub>p</sub> &minus; n&middot;r<sub>f</sub>)/&sigma;<sub>p</sub>
con r<sub>f</sub> = (1+R<sub>f</sub>)<sup>1/n</sup> &minus; 1 a partir de la tasa efectiva anual R<sub>f</sub>.</li>
<li><b>Restricciones:</b> presupuestos fijos por mercado &Sigma;<sub>i&isin;m</sub> w<sub>i</sub> = A<sub>m</sub>, inversión
total, solo posiciones largas salvo que se configure otra cosa; cada solución se verifica por residuales.</li>
<li><b>Descomposición del riesgo (Euler):</b> &sigma; = &Sigma;<sub>i</sub> w<sub>i</sub>(&Sigma;w)<sub>i</sub>/&sigma;.</li>
<li><b>Paridad de riesgo:</b> minimiza la dispersión cuadrática de las contribuciones porcentuales de Euler a la varianza respecto a 1/N, bajo las restricciones configuradas; la solución SLSQP de múltiples puntos iniciales es local y no está certificada como óptimo global.</li>
<li><b>VaR / CVaR:</b> históricos, por periodo, reportados como pérdidas positivas.</li>
</ul>
