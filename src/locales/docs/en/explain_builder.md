**Weights.** Each stock's weight in the whole portfolio is its market's allocation times its share inside the market:

$$w_i = \frac{A_m}{100}\cdot\frac{a_{i\mid m}}{100}$$

Allocations must add up to 100%, and so must the shares inside every market.

**Adding a security.** *Pick from your database* lists the securities you have already downloaded (name, logo and chart color come from that first download). *Add a new ticker* validates an exact Yahoo symbol: it must exist, have recent prices, and its currency and suffix are checked against the market.

**Downloading.** Step 3 downloads up to 15 years of daily prices only for the days that are not stored yet. If a split or dividend changed the provider's history since the last download, the whole history is downloaded again so that old and new prices share one basis. Company logos are fetched once per ticker.
