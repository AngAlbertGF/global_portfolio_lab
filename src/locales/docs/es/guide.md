Global Portfolio Lab mide un portafolio internacional de acciones en una sola moneda de reporte (MXN por omisión),
describe su historia a 1, 3, 5, 10 y 15 años y lo compara con portafolios optimizados con Markowitz que respetan la
asignación por mercado que elegiste. Todo es histórico y dentro de muestra: explica el pasado, no predice el futuro.

## Inicio rápido

**Con datos en vivo (unos cinco minutos)**

1. Abre **Constructor de portafolio** y selecciona **Cargar ejemplo**, o escribe tus propios
   porcentajes hasta que la columna sume 100%.
2. Selecciona **Continuar al paso 2**. En cada mercado escribe un ticker exacto de Yahoo Finance, su parte de ese
   mercado y selecciona **Validar y agregar**. Ejemplos: `AAPL` y `NVDA` (EE. UU.), `WALMEX.MX` (México), `PETR4.SA`
   (Brasil), `7203.T` (Japón), `BHP.AX` (Australia), `RELIANCE.NS` (India).
3. Cuando todos los mercados muestren una palomita, selecciona **Continuar a la confirmación**, revisa la tabla y
   selecciona **Confirmar y descargar**. La primera descarga guarda 15 años de precios y tipos de cambio; las
   siguientes visitas los reutilizan.
4. Abre **Panel**, **Estadísticas del portafolio** o **Frontera eficiente**. Los análisis se calculan solos.

**Sin internet**

Ve a **Configuración y calidad de datos → Fuente de datos y demo**, activa **Usar base de datos demo SINTÉTICA** y
selecciona **Generar o regenerar los datos demo sintéticos**. Se carga un portafolio demo con precios inventados,
marcado claramente en cada página. Desactiva el interruptor para volver a tus datos reales; las dos bases nunca se
mezclan.

**Modo oscuro**

Activa **Modo oscuro** en la barra lateral. La página se recarga una vez y todas las pantallas, tablas, menús y
gráficas cambian al tema oscuro; tu portafolio y tu configuración se conservan. Los reportes HTML/PDF exportados se
quedan en claro para imprimirse bien. Streamlit recuerda la elección en este navegador.

**Cambiar el idioma**

Usa el menú **Idioma** de la barra lateral (o Configuración). Toda la interfaz, las gráficas, los mensajes y los
reportes HTML/PDF cambian de inmediato. Los nombres de hojas y columnas de Excel/CSV se quedan como identificadores
en inglés para que tus scripts sigan funcionando.

## Construir un portafolio

**Paso 1: asignación por mercado.** Cada renglón es un mercado. El porcentaje es la parte del capital total
invertida ahí. Los mercados en 0% quedan excluidos. La suma debe ser 100% (tolerancia de una millonésima de punto
porcentual); la página muestra cuánto falta por asignar. *Ponderar por igual* reparte 100% entre los mercados que
elijas, y las plantillas te permiten guardar y reutilizar una asignación.

**Paso 2: valores.** Dentro de cada mercado, cada acción recibe una parte de la asignación de *ese mercado*, y esas
partes deben sumar 100%. El peso total en el portafolio es

> peso total = asignación del mercado × parte dentro del mercado

así que NVDA con 25% de una asignación de 80% a EE. UU. pesa 20% del portafolio. Reglas que aplica el constructor:

* Los tickers deben ser símbolos exactos de Yahoo con su sufijo de bolsa (`.MX`, `.SA`, `.T`, `.AX`, `.NS`, `.L`
  ...). Los nombres de empresa se rechazan; la app nunca cambia un símbolo por otro.
* Un ticker solo puede aparecer una vez.
* Si una acción cotiza en una moneda distinta a la de su mercado (por ejemplo `VALE` en USD dentro de Brasil)
  aparece una advertencia; la conversión siempre usa la moneda propia de la acción.
* "Error del proveedor" significa que Yahoo no respondió, no que el ticker esté mal. No se agrega nada; vuelve a
  intentarlo.

**Paso 3: confirmar y descargar.** La tabla muestra nombres, bolsas, monedas, ambos pesos, lo que ya está guardado
y lo que se va a solicitar. Las descargas son incrementales: solo se pide la historia faltante y un pequeño traslape
reciente, y una descarga fallida nunca borra datos guardados. Guarda el portafolio para volver a cargarlo después
desde el desplegable en la parte superior del constructor.

## Las páginas

El menú sigue el trabajo en tres etapas: **1 · Construye**, **2 · Analiza**, **3 · Simula y exporta**. El Panel muestra
el mismo mapa con una ✓ en cada etapa terminada. Cada página empieza con una frase sobre lo que estás viendo y
termina con **¿Cómo se calculó?**, que explica los datos usados y las fórmulas.

* **Panel**: mapa de la app, composición y en qué se habría convertido tu capital (valor final, ganancia, peor caída
  en dinero), quién generó el dinero y una vista previa de la frontera.
* **Constructor de portafolio**: en el paso 2, *Elegir de tu base de datos* muestra las acciones que ya
  descargaste, con su logo, nombre y color de gráfica; *Agregar un ticker nuevo* acepta cualquier símbolo exacto
  de Yahoo.
* **Buscar acciones**: busca en tu base por nombre de la empresa, consulta cualquier ticker nuevo, ve sus precios
  con los splits marcados, sus dividendos y cualquier reparación aplicada a los datos del proveedor.
* **Base de datos histórica**: actualiza tickers, historia guardada, splits y reparaciones, tipos de cambio, logos,
  verificaciones de integridad, respaldos y la bitácora de descargas.
* **Estadísticas del portafolio**: por horizonte, en qué se convirtió tu capital (en dinero y porcentaje), su
  crecimiento comparado con el benchmark o con cualquier portafolio optimizado, caídas, calendario de rendimientos
  mensuales, un renglón por acción con su logo, peso, minigráfica de crecimiento y el dinero que generó, y todas las
  estadísticas en las tablas de abajo.
* **Conversión de divisas**: el tipo de cambio usado para cada precio, con un ejemplo resuelto para cualquier acción
  y día, las tasas en el tiempo y cuánto del resultado vino de la moneda.
* **Frontera eficiente**: cambia el modelo y haz clic en cualquier punto para ver su composición, su ganancia
  esperada y su oscilación típica anual en dinero.
* **Portafolios optimizados**: una tarjeta por portafolio con lo que valdría tu capital, composiciones con colores
  de marca, comparaciones y todos los detalles de validación.
* **Análisis de riesgo**: el riesgo en dinero (día malo, peores días, peor caída), de dónde viene, concentración,
  colas, intervalos de confianza, sensibilidad y Monte Carlo.
* **Laboratorio de backtesting**: entrena con el periodo que elijas (por defecto hasta el 2025-12-31), deja que cada
  estrategia decida y pronostique, y luego prueba en el periodo posterior (por defecto desde el 2026-01-01) en
  dinero, con costos y aportaciones mensuales; compara pronóstico contra realidad e incluye escenarios
  *¿qué pasaría si…?*.
* **Reportes y exportaciones**: archivos Excel, CSV, HTML, PDF y PNG, incluidas tablas en dinero, splits y
  reparaciones.
* **Configuración y calidad de datos**: idioma, capital por defecto, logos y colores de marca, moneda,
  estimadores, restricciones, carpetas y datos demo.

**Logos y colores.** Los logos se descargan una vez por ticker de Parqet o de Financial Modeling Prep (imágenes
públicas), o de logostream.dev si capturas una API key gratuita en Configuración (la app muestra entonces el enlace
obligatorio "Logos by logostream.dev"). Cada acción conserva el color principal de su logo en todas las gráficas,
ajustado para que contraste.

**Splits.** Las descargas incluyen splits y dividendos. Los errores en los datos del proveedor (por ejemplo el
split 100:1 del ETF del Nikkei 225, 1321.T, en octubre de 2026) se reparan, y un split posterior a tu última
descarga provoca una nueva descarga completa para que los rendimientos nunca muestren un falso −99% en un día.

## Interpretar los resultados

**Horizontes.** 1, 3, 5, 10 y 15 años son atajos. **✎ Personalizado** analiza la ventana que tú elijas: con
ventanas rápidas (3 o 6 meses, en lo que va del año, 2 o 7 años, desde que cotizan todas, toda la historia) o con
fechas libres. Si el final es la última fecha disponible, la ventana avanza sola con los precios nuevos. Todas las
acciones usan las mismas fechas reales de la ventana y el resultado se etiqueta con su duración verdadera
("Horizonte de 5 meses (2026-06-01 a 2026-10-30)"). En ventanas de menos de un año las cifras anualizadas se
extrapolan de pocos datos y la app lo avisa.

**Estado del horizonte.** *Completo* significa que todas las posiciones tienen datos para todo el horizonte.
*Incompleto* significa que al menos una empezó a cotizar después; no se muestran estadísticas del portafolio
original, porque una cifra "a 15 años" calculada con 4 años de datos sería engañosa. Entonces puedes cambiar a:

* *Universo común*: quita las posiciones con historia corta y reescala el resto (marcado claramente, no es tu
  portafolio);
* *Historia disponible*: conserva todas las posiciones pero usa una muestra más corta (se muestra la duración real);
* *Historia reconstruida para IPOs* (recomendada cuando una acción empezó a cotizar hace poco): conserva todas las
  posiciones y el horizonte completo. Las demás acciones usan solo sus precios reales; a la acción nueva se le
  estiman únicamente los rendimientos que le faltan, con un modelo de factores ajustado sobre sus rendimientos
  reales (sus betas contra el índice de su mercado y el resto del portafolio, más su propio ruido real, sin
  rendimiento extra). Necesita al menos 20 días reales. Todo lo reconstruido se marca: parte reconstruida por
  acción, franja gris en las gráficas y la etiqueta "con reconstrucción" en el selector de horizonte.

**Rendimientos.** El rendimiento anual *aritmético* (252 × rendimiento diario promedio) es el que optimiza
Markowitz. El rendimiento *geométrico* (CAGR) es lo que un inversionista realmente ganó por año. Con activos
volátiles la cifra aritmética es mayor; ninguna es un pronóstico.

**Razón de Sharpe.** Rendimiento en exceso sobre la tasa libre de riesgo por unidad de volatilidad. La tasa libre de
riesgo de 6.5% en MXN es un supuesto; cámbiala para que corresponda a tu periodo y moneda.

**Portafolios optimizados.** En el modo estándar cada mercado conserva exactamente la asignación que fijaste; solo
se reponderan las acciones dentro de cada mercado.

* *Mínima varianza*: la combinación menos volátil.
* *Máximo Sharpe*: el portafolio tangente, el mejor rendimiento por unidad de riesgo.
* *Máximo rendimiento*: tiende a poner todo el presupuesto de cada mercado en su mejor acción histórica.
* *Máximo riesgo*: solo una referencia matemática, nunca una recomendación.
* *Pesos iguales*: partes iguales dentro de cada mercado.

La columna *Certificación* indica qué tan seguro está el optimizador: *exacto* u *óptimo global* está demostrado;
*aproximado* es el mejor de varios intentos. Los óptimos históricos son muy sensibles a los rendimientos estimados;
las herramientas de sensibilidad en Análisis de riesgo muestran cuánto se mueven los pesos.

**Frontera.** La línea continua es la rama eficiente (el mejor rendimiento para cada nivel de riesgo) y la punteada
la rama ineficiente. Los puntos a la derecha y por debajo de la línea están dominados. La línea discontinua que sale
de la tasa libre de riesgo y pasa por el portafolio tangente es la línea del mercado de capitales.

**Datos diarios entre mercados.** Las bolsas cierran a distintas horas, así que las correlaciones diarias entre, por
ejemplo, Tokio y Nueva York se ven más bajas de lo que son. La frecuencia semanal (Configuración) reduce este efecto.

## Glosario

* **Cierre ajustado**: precio corregido por splits y dividendos; se usa para todos los rendimientos.
* **Moneda base**: la moneda en que se mide cada precio (MXN por omisión). Los precios se convierten antes de
  calcular rendimientos, así que se incluyen las ganancias y pérdidas cambiarias.
* **Calendario común**: fechas en que todas las posiciones tienen precio. Nunca se inventa un precio.
* **Volatilidad**: desviación estándar anualizada de los rendimientos.
* **Máxima caída (drawdown)**: la peor baja desde un máximo previo.
* **VaR 95%**: pérdida que se supera en 5% de los días. **CVaR 95%**: pérdida promedio en ese 5% de peores días.
* **Razón de Sortino**: como Sharpe, pero penaliza solo la volatilidad a la baja.
* **Razón de Calmar**: CAGR dividido entre el valor absoluto de la máxima caída.
* **Beta**: sensibilidad frente al índice de referencia; 1.2 significa que el portafolio se movió 1.2% por cada 1%
  del índice.
* **Contribución al riesgo (Euler)**: la parte de la volatilidad total que aporta cada acción; las partes suman 100%.
* **Contracción de Ledoit-Wolf**: una estimación de la covarianza acercada a una estructura más simple; más estable
  cuando hay muchos activos y pocas observaciones.
* **Razón de diversificación**: promedio ponderado de las volatilidades de los activos entre la volatilidad del
  portafolio; un valor mayor indica más diversificación.

## Solución de problemas

* **"No encontrado"**: revisa el sufijo de la bolsa (México `.MX`, Brasil `.SA`, Japón `.T`, Australia `.AX`, India
  `.NS` o `.BO`, Reino Unido `.L`, Canadá `.TO`, Alemania `.DE`, Hong Kong `.HK`). Las acciones de EE. UU. no llevan
  sufijo.
* **"Error del proveedor"**: Yahoo limitó o falló temporalmente. Espera un minuto y vuelve a intentar; no se pierde
  nada.
* **Un horizonte dice Incompleto**: el recuadro rojo dice el motivo. Si una posición es demasiado reciente (IPO),
  usa el botón **Reconstruir la historia corta** o el selector de Modo de cobertura en Estadísticas del portafolio.
* **"Observaciones insuficientes"**: baja *Observaciones mínimas* en Configuración o usa un horizonte más largo.
* **Los pesos no cuadran**: los valores de cada mercado deben sumar 100% de ese mercado; usa *Ponderar por igual este
  mercado*.
* **Los precios se ven 100 veces más grandes**: Londres y Johannesburgo cotizan en peniques o centavos; la app divide
  entre 100 automáticamente.
* **Algo se ve raro en los datos**: abre Base de datos histórica, revisa el ticker, corre la verificación de
  integridad y reintenta las descargas fallidas.
