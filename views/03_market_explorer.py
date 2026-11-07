"""Find securities: search the local database by name (with logos), look up any new Yahoo ticker, inspect
prices, splits, dividends and repairs, and see the configured markets."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, ui
from src.data_service import session_gap_report
from src.i18n import t
from src.returns import load_base_currency_prices

ui.page_header(t("Find securities"), t("Search the stocks already in your database by name, look up any exact Yahoo "
                                       "Finance ticker, and inspect its prices, splits and dividends."),
               show_allocation=False)
mk = ui.markets()
db = ui.db()
s = ui.settings()
ss = st.session_state
ui.intro(t("Names come from Yahoo Finance and are stored the first time a ticker is validated, so the search box "
           "lists every security you have downloaded. A new security is always added by its exact ticker."))

tab_lookup, tab_markets = st.tabs([t("Search and inspect"), t("Supported markets")])
with tab_markets:
    st.caption(t("Market metadata are configuration (src/config.py or data/markets_custom.json). Benchmark symbols "
                 "are configured defaults; 'stored' means data for them exist in your local database."))
    rows = []
    for m in mk.values():
        n = db.get_date_range(m.benchmark)[2] if m.benchmark else 0
        rows.append({t("ID"): m.market_id, t("Market"): t(m.name), t("Exchanges"): ", ".join(m.exchanges),
                     t("Currency"): m.currency, t("Timezone"): m.timezone,
                     t("Calendar"): m.calendar or t("weekday heuristic"), t("Close"): m.close_time,
                     t("Ticker suffix"): m.suffix_text(), t("Benchmark"): f"{m.benchmark} ({m.benchmark_name})",
                     t("Benchmark data"): t("stored") if n else t("not downloaded yet"),
                     t("Priority"): "★" if m.priority else "", t("Notes"): t(m.notes) if m.notes else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=520)

with tab_lookup:
    left, right = st.columns([3, 2])
    with left:
        st.markdown(t("**Search your database by name**"))
        picked = ui.security_picker("explorer_picker")
        if picked:
            ss.explore_ticker = picked
    with right:
        st.markdown(t("**Or look up a new ticker**"))
        with st.container(key="inputs_lookup"):
            ticker = st.text_input(t("Exact Yahoo Finance ticker"), placeholder=t("e.g. WALMEX.MX"))
            market = st.selectbox(t("Market"), list(mk), format_func=lambda k: t(mk[k].name))
            look = st.button(t("Look up"), icon=":material/search:", type="primary")
        if look and ticker.strip():
            with st.spinner(t("Validating...")):
                res = ui.service().validate_ticker(ticker, market)
            ss.lookup = res
            if res.accepted:
                ui.ensure_logos([res.ticker])
                ss.explore_ticker = res.ticker
        res = ss.get("lookup")
        if res is not None and not res.accepted:
            st.error(f"**{res.ticker}**: {ui.status_label(res.status)}. {res.message}")
        elif res is not None:
            st.success(f"**{res.ticker}**: {ui.status_label(res.status)}. {res.message}")
            for w in res.warnings:
                st.warning(w, icon=":material/warning:")

    tk = ss.get("explore_ticker")
    if not tk:
        st.caption(t("Pick a stored security or type an exact symbol such as AAPL, WALMEX.MX, 7203.T or PETR4.SA."))
    else:
        sec = db.get_security(tk) or {}
        mid = sec.get("market_id") or market
        st.divider()
        ui.security_card(tk)
        f, l_, n = db.get_date_range(tk)
        if n == 0:
            if st.button(t("Download {period} of history for {ticker}", h=s.history_years, ticker=tk),
                         icon=":material/cloud_download:"):
                with st.spinner(t("Downloading...")):
                    out = ui.service().update_ticker(tk, mid)
                st.write(ui.status_label(out.status), "; ".join(out.messages))
                st.rerun()
        else:
            hist = db.get_price_history(tk)
            actions = db.get_actions(tk)
            splits = actions[actions["action"] == "SPLIT"] if not actions.empty else actions
            divs = actions[actions["action"] == "DIVIDEND"] if not actions.empty else actions
            c = st.columns(4)
            c[0].metric(t("Stored observations"), f"{n:,}", border=True)
            c[1].metric(t("History"), f"{f[:4]} → {l_[:4]}", border=True, help=f"{f} → {l_}")
            c[2].metric(t("Splits recorded"), len(splits), border=True)
            c[3].metric(t("Dividends recorded"), len(divs), border=True)
            color = ui.security_colors([tk]).get(tk)
            fig = charts.simple_line(hist.index, {t("Adjusted close"): hist["adj_close"], t("Close"): hist["close"]},
                                     t("{ticker} in {ccy} (local currency)", ticker=tk, ccy=sec.get("currency") or ""),
                                     t("Price ({ccy})", ccy=sec.get("currency") or ""))
            if color:
                fig.data[0].line.color = color
            for row in splits.itertuples():
                ratio = row.value
                label = (t("split {ratio}:1", ratio=f"{ratio:g}") if ratio >= 1
                         else t("reverse split 1:{ratio}", ratio=f"{1 / ratio:g}"))
                fig.add_vline(x=pd.Timestamp(row.date), line={"color": charts.C.ink2, "dash": "dot", "width": 1})
                fig.add_annotation(x=pd.Timestamp(row.date), y=1, yref="paper", text=label, showarrow=False,
                                   yanchor="bottom", font={"size": 11, "color": charts.C.ink2})
            st.plotly_chart(fig, width="stretch", theme=None)
            st.caption(t("Both lines are already split-adjusted (Yahoo restates the whole history after a split). The "
                         "adjusted close also reinvests dividends; the analysis always uses it."))
            base = s.base_currency
            bp, rep = load_base_currency_prices(db, [tk], base, s.fx_max_staleness_days)
            if not bp.empty and sec.get("currency") and sec.get("currency") != base:
                st.plotly_chart(charts.simple_line(bp.index, {t("In {ccy}", ccy=base): bp[tk]},
                                                   t("{ticker} adjusted close converted to {ccy}", ticker=tk, ccy=base),
                                                   t("Price ({ccy})", ccy=base)), width="stretch", theme=None)
                st.page_link("views/12_currency.py", label=t("See how the conversion was done"),
                             icon=":material/currency_exchange:")
            elif bp.empty:
                st.info(t("No {ccy} conversion yet (FX series missing). Download the portfolio in the Builder.",
                          ccy=base))
            repairs = db.get_repairs(tk)
            with st.expander(t("Splits, dividends and price repairs ({n})", n=len(splits) + len(divs) + len(repairs)),
                             icon=":material/build:"):
                if not splits.empty:
                    st.markdown(t("**Splits**"))
                    st.dataframe(splits[["date", "value"]].rename(columns={"date": t("Date"),
                                                                            "value": t("Ratio (new:old)")}),
                                 hide_index=True)
                if not repairs.empty:
                    st.markdown(t("**Repairs applied to provider data**"))
                    st.dataframe(repairs[["kind", "date_from", "date_to", "factor", "detail", "created_at"]],
                                 hide_index=True, width="stretch")
                if not divs.empty:
                    st.markdown(t("**Dividends (per share, local currency)**"))
                    st.dataframe(divs[["date", "value"]].tail(40).rename(columns={"date": t("Date"),
                                                                                   "value": t("Dividend")}),
                                 hide_index=True)
                if splits.empty and repairs.empty and divs.empty:
                    st.caption(t("No corporate actions or repairs recorded for this security."))
            cal = mk[mid].calendar if mid in mk else None
            ui.gap_report_view(session_gap_report(hist.index, cal))
ui.explain("explain_explorer")
ui.footer()
