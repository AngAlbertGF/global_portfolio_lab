**Tablas.** `daily_prices` (llave ticker + fecha, así que los duplicados son imposibles), `exchange_rates`, `securities`, `corporate_actions` (splits y dividendos), `price_repairs`, `security_logos` y `download_log`.

**Actualización incremental.** Solo se piden los días que faltan, más un traslape de 10 días que detecta precios revisados. Si el traslape muestra que los precios del proveedor cambiaron de base (un split, o un dividendo aplicado a todo el historial), o la serie guardada tiene un salto con forma de split, se vuelve a descargar todo el historial y se reemplaza en una sola transacción. Una descarga fallida nunca borra datos guardados.

**Splits y reparaciones.** Ejemplo: el ETF NEXT FUNDS Nikkei 225 (1321.T) tuvo un split 100:1 el 2026-10-05. Yahoo entregó dos sesiones posteriores al split divididas entre 100 por segunda vez y los dividendos en la base anterior al split, lo que hizo negativo su cierre ajustado; la app reescala esas sesiones, lleva los dividendos a la nueva base y recalcula el cierre ajustado.

**Logos.** Se descargan una vez por ticker. El color de marca es el color saturado dominante del logo; las gráficas lo ajustan para que contraste con el tema claro u oscuro y para que las acciones se distingan entre sí.
