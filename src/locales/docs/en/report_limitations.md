<ul>
<li>Historical estimates of expected returns are noisy, and optimized weights are highly sensitive to them. An in-sample
optimum is neither a forecast nor a recommendation.</li>
<li>Data come from an unofficial Yahoo Finance interface; completeness, accuracy and availability are not guaranteed, and
the provider can revise adjusted histories.</li>
<li>Markets close at different times, so daily cross-market correlations are understated (weekly frequency reduces
this).</li>
<li>Common-calendar filtering can create multi-session return intervals. Fixed 252/52 annualization is therefore an approximation; material gaps can distort annualized means, volatility and covariance. Weekly data or an explicitly interval-aware estimator is preferable when gaps are substantial.</li>
<li>Survivorship bias: the analysis uses securities chosen today.</li>
<li>The maximum-risk portfolio is a mathematical benchmark only.</li>
</ul>
