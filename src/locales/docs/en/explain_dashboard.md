**Where the numbers come from**

* **Prices**: daily *adjusted* closes from Yahoo Finance (splits and dividends included), stored in the local SQLite database. Splits and broken provider data are repaired before storing (see *Historical Database → Splits and repairs*).
* **Conversion**: each price is converted to [[ccy]] on its own trading day with the exchange rate of that day (or the last one up to a few days earlier). Details on the *Currency conversion* page.
* **Capital**: every amount assumes [[capital]] invested on the first day of the horizon with the weights you entered.

**Final value and gain**

The portfolio is rebalanced to your weights every day (constant weights), so its daily return is the weighted sum of the stocks' returns:

$$r_{p,t} = \sum_i w_i\, r_{i,t}, \qquad V_t = V_{t-1}\,(1 + r_{p,t}), \qquad V_0 = \text{capital}$$

Gain = final value − capital. **CAGR** = (final value / capital)^(1/years) − 1 with years = calendar days / 365.25. **Worst fall** = the largest drop of the value from a previous peak, in money and in percent.

**Who made the money**: each day each stock earns weight × its return × the value of the previous day; added over the period these amounts equal the total gain exactly.

**Map of the app**: a stage is marked done when its inputs are complete (valid allocation and prices downloaded; an up-to-date analysis; a backtest run in this session).
