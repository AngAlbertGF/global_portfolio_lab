**Search by name** lists every security stored in your database. Names, exchange and currency are the ones Yahoo Finance reported when the ticker was validated; the logo comes from logostream.dev (with an API key), Parqet or Financial Modeling Prep, and its dominant color becomes the security's color in every chart.

**Prices.** *Close* is Yahoo's closing price, already split-adjusted; *adjusted close* also reinvests dividends and is the only price used in the analysis. Dotted lines mark splits (e.g. 100:1) and reverse splits.

**Repairs.** Provider data are checked before storing: a block of days off by a split factor (or by 100) relative to the days around it is rescaled; a history left on the pre-split basis is divided by the split ratio; an adjusted close that is negative or inconsistent is recomputed from the close and the dividends. Every repair is listed with its dates and factor.

**Coverage** compares stored dates with the exchange's real trading sessions (holidays are not counted as missing).
