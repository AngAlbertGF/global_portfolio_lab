**1. Which rate.** For each foreign currency the app downloads Yahoo's daily series `XXX[[base]]=X` (units of [[base]] per 1 unit of XXX). Before using it, the direction is **verified**: the inverse symbol `[[base]]XXX=X` is downloaded for the last 40 days and the median of the product of both series must be within 2% of 1. A pair Yahoo does not quote is **derived through USD** ($\text{XXX}\to[[base]] = \text{USD}\to[[base]] \,/\, \text{USD}\to\text{XXX}$) and labelled as such.

**2. Which day.** Each stock price on date $d$ uses the rate observed on $d$. When the currency market had no quote that day, the last rate observed **at most [[n]] calendar days earlier** is used ("carried"). With no admissible rate, the stock observation is dropped — prices are never invented.

**3. The conversion.**

$$P^{[[base]]}_{i,d} = \frac{P^{\text{local}}_{i,d}}{\text{sub-unit}} \times FX_{d}$$

The sub-unit divisor is 100 for prices quoted in pence (GBp), cents (ZAc) or agorot (ILA), otherwise 1.

**4. Returns afterwards.** Returns are computed from the converted prices, so

$$1 + r^{[[base]]} = (1 + r^{\text{local}})\,(1 + r^{FX}) \;\Rightarrow\; r^{[[base]]} = r^{\text{local}} + r^{FX} + r^{\text{local}}\, r^{FX}$$

The last term is the **cross term** shown in the decomposition chart.

**5. "Without currency moves".** The same weights are applied to each stock's return in its own currency (the exchange rates frozen at the start). The difference between the two final values is the **currency effect** in money.
