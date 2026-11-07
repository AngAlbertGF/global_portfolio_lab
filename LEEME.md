# Global Portfolio Lab (resumen en español)

La documentación completa está en `README.md` (inglés) y, dentro de la app, en **Cómo usar**. Cada página termina
con un panel **¿Cómo se calculó?** que explica de dónde sale cada número.

## Instalar y abrir

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Actualizar desde la versión anterior

1. Respalda tu carpeta `data/` (contiene `stock_prices.db` y `settings.json`).
2. Reemplaza la carpeta del proyecto por la nueva y copia tu carpeta `data/` dentro de ella.
3. Asegúrate de que **no** quede una carpeta `pages/` vieja (las páginas están en `views/`).
4. `pip install -r requirements.txt` (esta versión necesita Streamlit 1.66 o más nuevo, Pillow y requests) y
   `streamlit run app.py`.
5. La base de datos se migra sola (se agregan las tablas de splits, reparaciones y logos). En la siguiente
   actualización de precios, la app detecta los datos mal ajustados por splits que ya tenías guardados y vuelve a
   descargar la historia completa de esos símbolos. No tienes que borrar nada.

## Novedades de esta versión

**Splits y reverse splits.** Yahoo a veces deja días con la escala de precio anterior al split (pasó con el ETF del
Nikkei `1321.T`, split 100:1: aparecían rendimientos falsos de −99% en un día). Ahora cada descarga se revisa:
se guardan los splits y dividendos, se corrigen los bloques con la escala equivocada, se valida el precio ajustado
(y se recalcula si está roto) y, si Yahoo cambió la base de precios, se descarga de nuevo toda la historia. Todas
las correcciones quedan registradas en **Base de datos histórica → Splits y reparaciones**.

**Selector por nombre con logos.** En el Constructor (paso 2) y en **Buscar acciones** puedes buscar por nombre o
ticker entre todas las acciones de tu base de datos; cada fila muestra el logo, el nombre, el ticker y el color que
tendrá en las gráficas. Las acciones nuevas se siguen agregando con su símbolo exacto de Yahoo.

**Logos y colores.** Fuentes, en orden: logostream.dev (solo con tu API key gratuita), Parqet y Financial Modeling
Prep (gratis, sin key; cubren EE. UU., México, Brasil, Japón, Reino Unido, India, Australia y Alemania en las
pruebas). El color de cada empresa en las gráficas sale del color principal de su logo, ajustado para que se lea
bien en modo claro y oscuro y para que dos empresas no queden con colores casi iguales. ETFs e índices no tienen
logo: se muestra un recuadro de color con sus iniciales.

Para usar logostream: crea una cuenta gratuita en logostream.dev, copia tu API key y pégala en **Configuración →
Dinero y apariencia**. Su plan gratuito pide mostrar la atribución (la app la pone en el pie de página) y no permite
guardar las imágenes, así que se mantienen solo en memoria salvo que actives guardarlas.

**Todo en dinero.** Además del porcentaje, cada página muestra cuánto valdría tu capital (el capital del portafolio
o el de Configuración): valor final, ganancia, peor caída, mejor y peor día, cuánto dinero aportó cada acción (suma
exacta de la ganancia), VaR/CVaR y Monte Carlo en dinero.

**Página Conversión de divisas.** Para cada acción: moneda, divisor de centavos (p. ej. peniques ÷100), par de Yahoo
usado (p. ej. `USDMXN=X`) y su verificación, la tasa de cada día (con la fecha de la tasa realmente usada), un
ejemplo paso a paso y cuánto del rendimiento vino de la acción y cuánto de la moneda:
`1 + r_MXN = (1 + r_local)(1 + r_tipo de cambio)`.

**Laboratorio de backtesting.** Eliges el periodo de entrenamiento (por omisión todo hasta el 31/12/2025) y el de
prueba (por omisión desde el 01/01/2026). Compara 10 estrategias (tus pesos, pesos iguales, inversa de volatilidad,
paridad de riesgo, mínima varianza, máximo Sharpe, máxima diversificación, mínimo CVaR, máximo rendimiento e
índice), con modo estático (entrenar una vez y aplicar) o walk-forward, rebalanceo, aportaciones mensuales y
costos. Muestra el cono de pronóstico del modelo contra lo que pasó en realidad, y escenarios "¿qué hubiera
pasado si…?": otra fecha de entrada, sin movimientos de tipo de cambio, un choque cambiario, quitar acciones, la
peor racha histórica y una proyección hacia adelante.

## Si un horizonte sale "Incompleto"

Antes, si una acción del portafolio no tenía precios descargados (no se usó "Confirmar y descargar" o la descarga
falló) o faltaba el tipo de cambio a la moneda base (por ejemplo, después de cambiar la moneda en Configuración),
todos los horizontes salían "Incompleto" y la causa quedaba escondida. Ahora la app descarga sola lo que falta al
abrir una página de análisis, y si un horizonte sigue incompleto dice el motivo de cada acción (sin precios, sin
tipo de cambio, historia demasiado corta o pocas fechas en común) con el botón que lo arregla: **Descargar lo que
falta**, **Analizar con la historia disponible** o **Excluir** las acciones con poca historia.

## Horizonte personalizado

En el selector de horizonte, además de los atajos de 1, 3, 5, 10 y 15 años, está **✎ Personalizado**: elige una
ventana rápida (3 o 6 meses, en lo que va del año, 2 o 7 años, desde que cotizan todas tus acciones, toda la
historia) o cualquier par de fechas. Todas las páginas de análisis y los reportes usan esa ventana. Si el final es la
última fecha, avanza sola cuando descargas precios nuevos. Con menos de un año la app avisa que las cifras anuales
se extrapolan de pocos datos.

## Acciones nuevas (IPOs) con menos historia que el horizonte

Elige **Historia reconstruida para IPOs**: con el botón **Reconstruir la historia corta** que aparece cuando un
horizonte sale incompleto, o en Configuración → Horizontes y cobertura. La elección se guarda.

* Las demás acciones usan solo sus precios reales; sus números no cambian.
* A la acción nueva se le estiman solo los rendimientos que le faltan, a partir de su relación real con el índice
  de su mercado (la app lo descarga sola) y con el resto del portafolio, más su propio ruido diario real.
* Su rendimiento extra de los primeros meses **no** se copia hacia atrás, así que un arranque muy bueno no infla
  el horizonte completo.
* Necesita al menos 20 días reales (se puede cambiar en Configuración).
* Todo lo reconstruido se marca: etiqueta del modo, "con reconstrucción" en el selector de horizonte, tabla con la
  parte reconstruida, factores, betas y R², franja gris en las gráficas, exportaciones y reporte.
* En el laboratorio de backtesting el modelo se ajusta solo con datos hasta el fin del entrenamiento y la prueba usa
  solo precios reales.

Por la regla del proyecto ("no extrapolar automáticamente hacia atrás"), este modo nunca se activa solo: tú lo eliges.

## Cambiar el idioma y el modo oscuro

Elige **Español** en **Language / Idioma** de la barra lateral. Activa **Modo oscuro** debajo del idioma (la página
se recarga una vez y el portafolio que editas se conserva). Los reportes exportados se quedan en claro.

## Cómo funciona el módulo de traducción

* Archivo: `src/i18n.py`. En el código, el texto en inglés es la llave: `t("Market allocation")`.
* Traducciones: `src/locales/es.json` (inglés → español). Si falta una llave, se muestra el inglés.
* Textos largos (guía, fórmulas, explicaciones de cada página): `src/locales/docs/es/*.md`.
* Revisar traducciones: `python -m src.i18n_extract` (llaves faltantes y marcadores `{...}` distintos).

**Agregar otro idioma:** copia `es.json` a `<código>.json` y `docs/es` a `docs/<código>`, traduce los valores y
cambia `"_language_name"`. Aparece solo en el selector.

**Agregar texto nuevo a la app:** envuélvelo en `t("...")`, ejecuta `python -m src.i18n_extract --write es` y
escribe la traducción. Las pruebas fallan mientras quede una llave sin traducir.
