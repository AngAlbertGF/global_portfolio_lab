<ul>
<li><b>Prices:</b> provider adjusted close (splits and dividends), converted to the base currency at the price level:
P<sub>base</sub> = P<sub>local</sub> / unit divisor &times; FX(local&rarr;base). Returns are computed after conversion, so
1 + r<sub>base</sub> = (1 + r<sub>local</sub>)(1 + r<sub>FX</sub>).</li>
<li><b>Calendar:</b> common observation dates only (no price filling). FX may be carried up to the configured staleness
limit; observations without an admissible FX rate are dropped.</li>
<li><b>Returns:</b> r<sub>t</sub> = P<sub>t</sub>/P<sub>t-1</sub> &minus; 1; annual mean = n&middot;mean, annual volatility =
&radic;n&middot;sd (n = 252 daily or 52 weekly, an approximation); CAGR uses the actual elapsed time.</li>
<li><b>Portfolio:</b> constant weights (rebalanced each period), &mu;<sub>p</sub> = w&prime;&mu;,
&sigma;<sub>p</sub><sup>2</sup> = w&prime;&Sigma;w, Sharpe = (&mu;<sub>p</sub> &minus; n&middot;r<sub>f</sub>)/&sigma;<sub>p</sub>
with r<sub>f</sub> = (1+R<sub>f</sub>)<sup>1/n</sup> &minus; 1 from the effective annual rate R<sub>f</sub>.</li>
<li><b>Constraints:</b> fixed market budgets &Sigma;<sub>i&isin;m</sub> w<sub>i</sub> = A<sub>m</sub>, full investment,
long-only unless configured otherwise; every solution is checked for residuals.</li>
<li><b>Risk decomposition (Euler):</b> &sigma; = &Sigma;<sub>i</sub> w<sub>i</sub>(&Sigma;w)<sub>i</sub>/&sigma;.</li>
<li><b>VaR / CVaR:</b> historical, per period, reported as positive losses.</li>
</ul>
