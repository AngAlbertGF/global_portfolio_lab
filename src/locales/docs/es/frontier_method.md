1. Los límites factibles del rendimiento esperado $[R_{min}, R_{max}]$ se obtienen con dos **programas lineales**
   sobre el conjunto factible.
2. Primero se resuelve el portafolio de mínima varianza global (GMV). Los objetivos por encima forman la **rama
   eficiente** (línea continua); los de abajo, la **rama ineficiente** (línea punteada).
3. Para cada uno de los [[points]] objetivos el optimizador calcula $\min_w w^\top\Sigma w$ sujeto a
   $w^\top\mu = R$, las restricciones de presupuesto y de mercado y los límites. Cada solución se verifica (éxito
   del optimizador y residuales del objetivo, del presupuesto y de las sumas por mercado); los puntos fallidos se
   excluyen de la curva.
4. El portafolio tangente se muestra solo si la solución de máximo Sharpe es válida y ningún punto de la frontera la
   supera.
5. La línea discontinua del mercado de capitales empieza en $n\,r_f$ = [[rf]].

Los óptimos estimados son **dentro de muestra**: cambios pequeños en $\mu$ pueden moverlos mucho.
