"""Currency conversion: which exchange rates were used, how every price was converted, and the FX effect."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, ui
from src.i18n import t
from src.money import wealth_with_start
from src.returns import conversion_details

ui.page_header(t("Currency conversion"), t("How every foreign price was converted to your base currency, which "
                                           "exchange rates were used, and how much of the result came from the "
                                           "currency."))
s = ui.settings()
base = s.base_currency
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
cap = ui.capital()
ui.intro(t("Each stock's adjusted close is converted on its own trading day: price ÷ sub-unit × exchange rate of that "
           "day. Returns are computed only afterwards, so the result in {base} already includes the currency's move.",
           base=base))
h = ui.horizon_selector(bundle, "fx_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
if not r.analyzable:
    st.stop()
tickers = list(r.returns.columns)
details = conversion_details(ui.db(), tickers, base, s.fx_max_staleness_days)
d0, d1 = r.prices.index[0], r.prices.index[-1]
nm = ui.names(tickers)
logos = ui.logo_uris(tickers)

# ---------------------------------------------------------------- decomposition
rows = []
for tk in tickers:
    info = details.get(tk)
    if info is None:
        continue
    det = info["detail"].dropna(subset=["price_base"])
    a_, b_ = det.loc[:d0], det.loc[:d1]          # weekly dates are week ends: use the last trading day on/before
    if a_.empty or b_.empty:
        continue
    a, b = a_.iloc[-1], b_.iloc[-1]
    local = b["price_major"] / a["price_major"] - 1
    fxr = b["fx_rate"] / a["fx_rate"] - 1
    tot = b["price_base"] / a["price_base"] - 1
    rows.append({"ticker": tk, "logo": logos.get(tk), "name": nm.get(tk, tk), "currency": info["currency"],
                 "divisor": info["divisor"], "pair": info["pair"] or t("none (same currency)"),
                 "symbol": info["symbol"] or "–",
                 "verified": (t("same currency") if not info["pair"] else
                              (t("verified") if info["verified"] else t("not verified"))),
                 "rate_start": a["fx_rate"], "rate_start_date": a["fx_date"], "rate_end": b["fx_rate"],
                 "rate_end_date": b["fx_date"], "local_return": local, "fx_return": fxr, "cross": local * fxr,
                 "base_return": tot, "weight": float(r.weights_user.get(tk, 0.0))})
dec = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
foreign = [tk for tk in tickers if details.get(tk) and details[tk]["pair"]]

# portfolio with and without the currency effect
local_px = pd.DataFrame({tk: details[tk]["detail"]["price_major"] for tk in tickers if tk in details}).sort_index() \
    .reindex(r.prices.index, method="ffill")
local_r = (local_px / local_px.shift(1) - 1).iloc[1:].reindex(columns=tickers)
w = r.weights_user.reindex(tickers).fillna(0.0).values
actual = wealth_with_start(r.portfolio_returns, cap, d0)
no_fx = wealth_with_start(pd.Series(local_r.fillna(0.0).values @ w, index=local_r.index), cap, d0)
fx_money = float(actual.iloc[-1] - no_fx.iloc[-1])
c = st.columns(4)
c[0].metric(t("Securities in foreign currency"), f"{len(foreign)} / {len(tickers)}", border=True)
c[1].metric(t("Currencies converted"), len({details[tk]['major'] for tk in foreign}), border=True)
c[2].metric(t("Final value in {base}", base=base), ui.fmt_compact(actual.iloc[-1]),
            ui.fmt_money(actual.iloc[-1] - cap, sign=True), border=True)
c[3].metric(t("Currency effect"), ui.fmt_compact(fx_money, sign=True),
            t("without it: {value}", value=ui.fmt_money(no_fx.iloc[-1])), delta_color="off", delta_arrow="off",
            border=True, help=t("Final value minus the value the same portfolio would have had if every exchange rate "
                                "had stayed at its {date} level (stocks measured in their own currency).",
                                date=f"{d0:%Y-%m-%d}"))
st.plotly_chart(charts.money_growth({t("Actual (in {base})", base=base): actual,
                                     t("Without currency moves"): no_fx},
                                    t("Your {capital}: with and without the currency effect ({span})",
                                      capital=ui.fmt_compact(cap), h=h), base,
                                    {t("Actual (in {base})", base=base): charts.strategy_color("user"),
                                     t("Without currency moves"): charts.strategy_color("benchmark")}),
                width="stretch", theme=None)
if not dec.empty:
    st.plotly_chart(charts.fx_decomposition(dec, t("Where each security's return came from ({start} to {end})",
                                                   start=f"{d0:%Y-%m-%d}", end=f"{d1:%Y-%m-%d}"), nm),
                    width="stretch", theme=None)
    st.caption(t("Return in {base} = (1 + return in own currency) × (1 + change of the exchange rate) − 1. The cross term "
                 "is the product of the two changes.", base=base))

# ---------------------------------------------------------------- rates used
st.subheader(t("Exchange rates used"))
pairs = {}
for tk in foreign:
    info = details[tk]
    if info["pair"] not in pairs and info["fx"] is not None:
        fx = info["fx"]
        pairs[info["pair"]] = fx[(fx.index >= d0 - pd.Timedelta(days=7)) & (fx.index <= d1)]
if pairs:
    norm = st.toggle(t("Show as an index (start = 100)"), value=True, key="fx_norm")
    st.plotly_chart(charts.fx_lines(pairs, t("{base} per unit of each currency", base=base), norm), width="stretch",
                    theme=None)
    st.caption(t("A rising line means that currency became more expensive in {base} (the {base} weakened against it), "
                 "which raises the {base} value of the stocks priced in it.", base=base))
else:
    st.info(t("All holdings trade in {base}: no conversion was needed.", base=base))
if not dec.empty:
    tab = dec.reset_index()[["logo", "name", "ticker", "currency", "divisor", "pair", "symbol", "verified",
                             "rate_start_date", "rate_start", "rate_end_date", "rate_end", "fx_return",
                             "local_return", "base_return"]].copy()
    for col in ("fx_return", "local_return", "base_return"):
        tab[col] = tab[col] * 100
    for col in ("rate_start_date", "rate_end_date"):
        tab[col] = pd.to_datetime(tab[col]).dt.date
    st.dataframe(tab, hide_index=True, width="stretch", column_config={
        "logo": ui.logo_column(), "name": t("Name"), "ticker": t("Ticker"), "currency": t("Trading currency"),
        "divisor": st.column_config.NumberColumn(t("Sub-unit divisor"), format="%g"), "pair": t("Pair"),
        "symbol": t("Yahoo symbol"), "verified": t("Quote direction"),
        "rate_start_date": t("Rate date (start)"), "rate_start": st.column_config.NumberColumn(t("Rate at start"),
                                                                                              format="%.4f"),
        "rate_end_date": t("Rate date (end)"), "rate_end": st.column_config.NumberColumn(t("Rate at end"), format="%.4f"),
        "fx_return": st.column_config.NumberColumn(t("Currency change"), format="%+.2f%%"),
        "local_return": st.column_config.NumberColumn(t("Stock in own currency"), format="%+.2f%%"),
        "base_return": st.column_config.NumberColumn(t("Total in {base}", base=base), format="%+.2f%%")})

# ---------------------------------------------------------------- worked example
st.subheader(t("Worked example: one price, one day"))
with st.container(key="inputs_fx_example"):
    e1, e2 = st.columns([2, 3])
    pick = e1.selectbox(t("Security"), foreign or tickers, format_func=lambda x: f"{nm.get(x, x)} ({x})",
                        key="fx_ex_tk")
    det = details[pick]["detail"]
    det = det[(det.index >= d0) & (det.index <= d1)].dropna(subset=["price_base"])
    day = e2.select_slider(t("Day"), options=list(det.index), value=det.index[-1],
                           format_func=lambda d: f"{d:%Y-%m-%d}", key="fx_ex_day")
row = det.loc[day]
info = details[pick]
ui.security_card(pick)
if info["pair"]:
    carried = int(row["carried_days"]) if pd.notna(row["carried_days"]) else 0
    when = (t("rate of the same day") if carried == 0 else
            t("last rate available, {n} day(s) earlier (exchange-rate market closed that day)", n=carried))
    steps = [t("1. Adjusted close on {date}: **{price} {ccy}** (from Yahoo Finance, split- and dividend-adjusted).",
               date=f"{day:%Y-%m-%d}", price=f"{row['price_local']:,.4f}", ccy=info["currency"])]
    if info["divisor"] != 1:
        steps.append(t("2. Quoted in a sub-unit ({ccy}): divided by {d} → **{p} {major}**.", ccy=info["currency"],
                       d=f"{info['divisor']:g}", p=f"{row['price_major']:,.4f}", major=info["major"]))
    steps.append(t("{n}. Exchange rate {pair} from `{symbol}` on {fxdate} ({when}): **{rate}** {base} per 1 {major}.",
                   n=len(steps) + 1, pair=info["pair"], symbol=info["symbol"], fxdate=f"{row['fx_date']:%Y-%m-%d}",
                   when=when, rate=f"{row['fx_rate']:,.6f}", base=base, major=info["major"]))
    steps.append(t("{n}. Price in {base}: {p} × {rate} = **{value} {base}**.", n=len(steps) + 1, base=base,
                   p=f"{row['price_major']:,.4f}", rate=f"{row['fx_rate']:,.6f}", value=f"{row['price_base']:,.4f}"))
    st.markdown("\n".join(steps))
    if info["verification_detail"]:
        st.caption(t("Quote-direction check: {detail}", detail=info["verification_detail"]))
else:
    st.markdown(t("{ticker} trades in {base}: its adjusted close **{price} {base}** is used as is.", ticker=pick,
                  base=base, price=f"{row['price_local']:,.4f}"))

with st.expander(t("Conversion quality per security (all dates)"), icon=":material/table:"):
    ui.show_table(bundle.conversion_report)
    st.caption(t("Same-day: a rate existed on the stock's trading day. Carried: the last rate up to {n} calendar days "
                 "earlier was used (e.g. a currency-market holiday). Dropped: no admissible rate, so that stock "
                 "observation was not used; prices are never invented.", n=s.fx_max_staleness_days))
ui.explain("explain_currency", base=base, n=s.fx_max_staleness_days)
ui.footer()
