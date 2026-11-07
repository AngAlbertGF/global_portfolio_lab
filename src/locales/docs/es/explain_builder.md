**Pesos.** El peso de cada acción en todo el portafolio es la asignación de su mercado por su participación dentro del mercado:

$$w_i = \frac{A_m}{100}\cdot\frac{a_{i\mid m}}{100}$$

Las asignaciones deben sumar 100% y también las participaciones dentro de cada mercado.

**Agregar una acción.** *Elegir de tu base de datos* muestra las acciones que ya descargaste (el nombre, el logo y el color de las gráficas vienen de esa primera descarga). *Agregar un ticker nuevo* valida un símbolo exacto de Yahoo: debe existir, tener precios recientes, y su moneda y sufijo se comparan con los del mercado.

**Descarga.** El paso 3 descarga hasta 15 años de precios diarios, solo de los días que todavía no están guardados. Si un split o un dividendo cambió el historial del proveedor desde la última descarga, se vuelve a descargar todo el historial para que los precios viejos y nuevos estén en la misma base. Los logos se descargan una sola vez por ticker.
