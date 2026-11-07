**Buscar por nombre** muestra todas las acciones guardadas en tu base de datos. El nombre, la bolsa y la moneda son los que reportó Yahoo Finance al validar el ticker; el logo viene de logostream.dev (con API key), Parqet o Financial Modeling Prep, y su color dominante se vuelve el color de la acción en todas las gráficas.

**Precios.** *Cierre* es el precio de cierre de Yahoo, ya ajustado por splits; el *cierre ajustado* además reinvierte los dividendos y es el único precio que usa el análisis. Las líneas punteadas marcan splits (por ejemplo 100:1) y splits inversos.

**Reparaciones.** Los datos del proveedor se revisan antes de guardarse: un bloque de días desfasado por un factor de split (o por 100) respecto a los días de alrededor se reescala; un historial que quedó en la base anterior al split se divide entre la razón del split; un cierre ajustado negativo o inconsistente se recalcula con el cierre y los dividendos. Cada reparación aparece con sus fechas y su factor.

**Cobertura** compara las fechas guardadas con las sesiones reales de la bolsa (los días festivos no cuentan como faltantes).
