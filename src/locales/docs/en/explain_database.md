**Tables.** `daily_prices` (key ticker + date, so duplicates are impossible), `exchange_rates`, `securities`, `corporate_actions` (splits and dividends), `price_repairs`, `security_logos` and `download_log`.

**Incremental refresh.** Only the missing days are requested, plus a 10-day overlap that catches revised prices. If the overlap shows that the provider's prices changed basis (a split, or a dividend applied to the whole history), or the stored series contains a split-like jump, the full history is downloaded again and replaced in one transaction. A failed download never deletes stored data.

**Splits and repairs.** Example: NEXT FUNDS Nikkei 225 ETF (1321.T) had a 100:1 split on 2026-10-05. Yahoo served two post-split sessions divided by 100 a second time and dividends on the pre-split basis, which made its adjusted close negative; the app rescales those sessions, brings the dividends to the new basis and recomputes the adjusted close.

**Logos.** Fetched once per ticker. The brand color is the dominant saturated color of the logo; charts then adjust it for contrast with the light/dark theme and keep securities distinguishable.
