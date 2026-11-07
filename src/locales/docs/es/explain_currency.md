**1. Qué tasa.** Para cada moneda extranjera la app descarga la serie diaria de Yahoo `XXX[[base]]=X` (unidades de [[base]] por 1 unidad de XXX). Antes de usarla se **verifica la dirección**: se descarga el símbolo inverso `[[base]]XXX=X` de los últimos 40 días y la mediana del producto de ambas series debe estar a menos de 2% de 1. Un par que Yahoo no cotiza se **deriva vía USD** ($\text{XXX}\to[[base]] = \text{USD}\to[[base]] \,/\, \text{USD}\to\text{XXX}$) y queda etiquetado así.

**2. Qué día.** Cada precio de una acción en la fecha $d$ usa la tasa observada en $d$. Si el mercado cambiario no tuvo cotización ese día, se usa la última tasa observada **hasta [[n]] días calendario antes** ("arrastrada"). Si no hay tasa admisible, esa observación se elimina: nunca se inventan precios.

**3. La conversión.**

$$P^{[[base]]}_{i,d} = \frac{P^{\text{local}}_{i,d}}{\text{subunidad}} \times FX_{d}$$

El divisor de subunidad es 100 para precios cotizados en peniques (GBp), centavos (ZAc) o agorot (ILA); si no, es 1.

**4. Los rendimientos, después.** Los rendimientos se calculan con los precios ya convertidos, así que

$$1 + r^{[[base]]} = (1 + r^{\text{local}})\,(1 + r^{FX}) \;\Rightarrow\; r^{[[base]]} = r^{\text{local}} + r^{FX} + r^{\text{local}}\, r^{FX}$$

El último término es el **término cruzado** de la gráfica de descomposición.

**5. "Sin movimientos de la moneda".** Los mismos pesos se aplican al rendimiento de cada acción en su propia moneda (los tipos de cambio congelados al inicio). La diferencia entre ambos valores finales es el **efecto cambiario** en dinero.
