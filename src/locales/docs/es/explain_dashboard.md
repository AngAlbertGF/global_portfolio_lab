**De dónde salen los números**

* **Precios**: cierres diarios *ajustados* de Yahoo Finance (incluyen splits y dividendos), guardados en la base SQLite local. Los splits y los datos dañados del proveedor se reparan antes de guardarse (ver *Base histórica → Splits y reparaciones*).
* **Conversión**: cada precio se convierte a [[ccy]] en su propio día de operación con el tipo de cambio de ese día (o el último disponible hasta unos días antes). El detalle está en la página *Conversión de divisas*.
* **Capital**: todos los montos suponen [[capital]] invertidos el primer día del horizonte con los pesos que capturaste.

**Valor final y ganancia**

El portafolio se rebalancea a tus pesos todos los días (pesos constantes), así que su rendimiento diario es la suma ponderada de los rendimientos de las acciones:

$$r_{p,t} = \sum_i w_i\, r_{i,t}, \qquad V_t = V_{t-1}\,(1 + r_{p,t}), \qquad V_0 = \text{capital}$$

Ganancia = valor final − capital. **CAGR** = (valor final / capital)^(1/años) − 1, con años = días calendario / 365.25. **Peor caída** = la mayor baja del valor desde un máximo previo, en dinero y en porcentaje.

**Quién generó el dinero**: cada día cada acción gana peso × su rendimiento × el valor del día anterior; sumados en todo el periodo, esos montos dan exactamente la ganancia total.

**Mapa de la app**: una etapa aparece como completa cuando sus datos están listos (asignación válida y precios descargados; análisis actualizado; un backtest corrido en esta sesión).
