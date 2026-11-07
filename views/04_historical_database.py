"""Historical Database: local history, refresh controls, integrity, backups, download log."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, ui
from src.data_service import session_gap_report
from src.fx import stale_fx_flags
from src.i18n import t

ui.page_header(t("Historical Database"), t("Local SQLite store of daily prices and exchange rates. Primary keys "
                                           "prevent duplicates; each refresh re-downloads a short overlap window."),
               show_allocation=False)
db = ui.db()
mk = ui.markets()
svc = ui.service()
p = ui.portfolio()
ui.intro(t("Everything the app knows is stored here: daily prices, exchange rates, splits and dividends, logos and a "
           "log of every download. Refreshing only asks Yahoo for the days that are missing, and re-downloads the "
           "whole history when a split or dividend changed it."))

counts = db.table_counts()
c = st.columns(5)
c[0].metric(t("Securities"), counts["securities"])
c[1].metric(t("Daily price rows"), f"{counts['daily_prices']:,}")
c[2].metric(t("FX rows"), f"{counts['exchange_rates']:,}")
c[3].metric(t("Saved portfolios"), counts["portfolio_configurations"])
c[4].metric(t("Download log entries"), f"{counts['download_log']:,}")
st.caption(t("Database file: {path}", path=f"`{db.path}`"))

INTEGRITY_LABELS = {"sqlite_integrity": t("SQLite integrity check"), "duplicate_price_keys": t("Duplicate ticker-date rows"),
                    "nonpositive_prices": t("Zero or negative prices"), "high_below_low": t("Rows with high below low"),
                    "orphan_price_tickers": t("Prices without a security record"),
                    "nonpositive_fx": t("Zero or negative FX rates"), "schema_version": t("Schema version"),
                    "ok": t("Overall result")}

tab_refresh, tab_secs, tab_actions, tab_fx, tab_logos, tab_maint, tab_log = st.tabs(
    [t("Refresh"), t("Stored securities"), t("Splits and repairs"), t("Exchange rates"), t("Logos"),
     t("Integrity and backups"), t("Download log")])

with tab_refresh:
    secs = db.list_securities()
    with st.container(key="inputs_refresh"):
        r1, r2, r3, r4 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
        selected = r1.multiselect(t("Tickers"), secs["ticker"].tolist() if not secs.empty else [])
        force = r1.checkbox(t("Ignore 12-hour cache"), value=False)
        do_sel = r2.button(t("Update selected tickers"), icon=":material/sync:", disabled=not selected)
        do_all = r3.button(t("Update all portfolio tickers"), icon=":material/sync:", disabled=not p.holdings)
        failed = db.failed_tickers()
        do_retry = r4.button(t("Retry failed downloads ({n})", n=len(failed)), icon=":material/replay:",
                             disabled=not failed)

    def _run(items, label):
        bar = st.progress(0.0, label)
        res = svc.update_many(items, ui.settings().base_currency, force=force,
                              progress=lambda f, m: bar.progress(min(f, 1.0), m))
        st.session_state.db_results = pd.DataFrame([{"symbol": x.symbol, "status": x.status,
                                                      "rows_inserted": x.inserted, "rows_updated": x.updated,
                                                      "rebased": getattr(x, "rebased", False),
                                                      "repairs": getattr(x, "repairs", 0),
                                                      "messages": " | ".join(x.messages)} for x in res])

    if do_sel:
        mid = secs.set_index("ticker")["market_id"].to_dict()
        _run([(tk, mid.get(tk)) for tk in selected], t("Updating selected..."))
    if do_all:
        _run([(h.ticker, h.market_id) for h in p.holdings], t("Updating portfolio..."))
    if do_retry:
        fx_like = [tk for tk in failed if tk.endswith("=X")]
        for tk in fx_like:
            svc.update_fx(tk[:3], tk[3:6], force=True)
        mid = secs.set_index("ticker")["market_id"].to_dict() if not secs.empty else {}
        _run([(tk, mid.get(tk)) for tk in failed if tk not in fx_like], t("Retrying..."))
    if st.session_state.get("db_results") is not None:
        ui.show_table(st.session_state.db_results)
    else:
        st.caption(t("Refreshes use the local cache for 12 hours unless you tick the box. A failed refresh never "
                     "deletes stored data."))

with tab_secs:
    if secs.empty:
        st.info(t("No securities stored yet. Download a portfolio from Portfolio Builder, step 3."))
    else:
        view = secs.copy()
        uris = ui.logo_uris(view["ticker"].tolist())
        view.insert(0, "logo", view["ticker"].map(uris))
        st.dataframe(view, hide_index=True, width="stretch",
                     column_config={"logo": ui.logo_column()} | {c: st.column_config.Column(ui.col_label(c))
                                                                for c in secs.columns})
        pick = st.selectbox(t("Inspect local history"), secs["ticker"],
                            format_func=lambda x: f"{x} · {secs.set_index('ticker').loc[x, 'security_name'] or ''}")
        h = db.get_price_history(pick)
        if not h.empty:
            meta = secs.set_index("ticker").loc[pick]
            st.plotly_chart(charts.simple_line(h.index, {t("Adjusted close"): h["adj_close"],
                                                         t("Close (raw)"): h["close"]},
                                               t("{ticker} in {ccy} (local currency)", ticker=pick,
                                                 ccy=meta["currency"]), t("Price")), width="stretch", theme=None)
            cal = mk[meta["market_id"]].calendar if meta["market_id"] in mk else None
            ui.gap_report_view(session_gap_report(h.index, cal))
            with st.expander(t("Raw rows")):
                st.dataframe(h.reset_index(), hide_index=True, width="stretch")

with tab_actions:
    acts = db.get_actions(action="SPLIT")
    reps = db.get_repairs()
    st.caption(t("Splits come from Yahoo Finance with each download. Repairs are corrections the app applied to "
                 "provider data (a block of prices off by a split factor, a history left on the pre-split basis, or "
                 "an inconsistent adjusted close recomputed from the dividends). A split or a dividend after the last "
                 "download makes the app re-download the whole history, so old and new prices share one basis."))
    c = st.columns(3)
    c[0].metric(t("Splits recorded"), len(acts), border=True)
    c[1].metric(t("Repairs applied"), len(reps), border=True)
    rebases = db.get_download_log(5000)
    rebases = rebases[rebases["error_message"].fillna("").str.startswith("rebase")] if not rebases.empty else rebases
    c[2].metric(t("Full re-downloads after a corporate action"), len(rebases), border=True)
    if not acts.empty:
        st.markdown(t("**Splits and reverse splits**"))
        st.dataframe(acts.rename(columns={"ticker": t("Ticker"), "date": t("Date"), "action": t("Action"),
                                          "value": t("Ratio (new:old)")}), hide_index=True, width="stretch")
    if not reps.empty:
        st.markdown(t("**Repairs**"))
        ui.show_table(reps)
    if not rebases.empty:
        st.markdown(t("**Re-downloads**"))
        ui.show_table(rebases)
    if acts.empty and reps.empty:
        st.caption(t("No splits or repairs recorded yet."))

with tab_logos:
    s_ = ui.settings()
    allt = secs["ticker"].tolist() if not secs.empty else []
    recs = db.get_logos(allt)
    ok = sum(1 for r in recs.values() if r["status"] == "OK")
    c = st.columns(3)
    c[0].metric(t("Logos found"), f"{ok} / {len(allt)}", border=True)
    c[1].metric(t("Logo source order"), ("logostream → " if s_.logostream_api_key.strip() else "") + "Parqet → FMP",
                border=True)
    c[2].metric(t("Logo downloads"), t("on") if s_.download_logos else t("off"), border=True)
    b1, b2 = st.columns(2)
    if b1.button(t("Fetch missing logos"), icon=":material/image:", disabled=not allt):
        bar = st.progress(0.0)
        ui.ensure_logos(allt, progress=lambda f_, m_: bar.progress(min(f_, 1.0), m_))
        st.rerun()
    if b2.button(t("Re-fetch all logos"), icon=":material/refresh:", disabled=not allt):
        bar = st.progress(0.0)
        ui.ensure_logos(allt, force=True, progress=lambda f_, m_: bar.progress(min(f_, 1.0), m_))
        st.rerun()
    if allt:
        uris = ui.logo_uris(allt)
        cols_ = ui.security_colors(allt)
        lt = pd.DataFrame([{"logo": uris.get(tk), "ticker": tk, "status": (recs.get(tk) or {}).get("status", "–"),
                            "source": (recs.get(tk) or {}).get("source") or "–",
                            "brand": (recs.get(tk) or {}).get("primary_color") or "–",
                            "chart": cols_.get(tk)} for tk in allt])
        st.dataframe(lt, hide_index=True, width="stretch",
                     column_config={"logo": ui.logo_column(), "ticker": t("Ticker"), "status": t("Status"),
                                    "source": t("Source"), "brand": t("Brand color (from logo)"),
                                    "chart": t("Color used in charts")})
        st.caption(t("The brand color is the dominant saturated color of the logo; black, white and gray logos have "
                     "none and get a palette color. Chart colors are adjusted for contrast with the light or dark "
                     "theme and kept distinguishable from each other."))

with tab_fx:
    fx = db.get_fx_series_info()
    if fx.empty:
        st.info(t("No FX series stored yet."))
    else:
        fx["flags"] = [" ".join(stale_fx_flags(db.get_fx(r.base_currency, r.quote_currency))) for r in fx.itertuples()]
        fx["direction_verified"] = fx["direction_verified"].map(lambda v: t("yes") if v else t("no"))
        st.caption(t("Each rate is the number of 'to' currency units per 1 'from' currency unit. Direction is verified "
                     "against the inverse Yahoo symbol; pairs Yahoo does not quote are derived through USD."))
        ui.show_table(fx)

with tab_maint:
    i1, i2, i3 = st.columns(3)
    if i1.button(t("Check database integrity"), icon=":material/fact_check:"):
        res = db.integrity_check()
        (st.success if res["ok"] else st.error)(t("Integrity OK") if res["ok"] else t("Integrity problems found"))
        st.dataframe(pd.DataFrame({t("Check"): [INTEGRITY_LABELS.get(k, k) for k in res],
                                   t("Result"): [str(v) for v in res.values()]}), hide_index=True)
    if i2.button(t("Back up now"), icon=":material/backup:"):
        path = db.backup()
        st.success(t("Backup written: {name}", name=path.name))
    backups = db.list_backups()
    if backups:
        b = i3.selectbox(t("Restore from backup"), backups, format_func=lambda x: x.name)
        if i3.button(t("Restore selected backup"), icon=":material/settings_backup_restore:"):
            safety = db.restore(b)
            st.success(t("Restored. A safety backup of the previous state was saved as {name}.", name=safety.name))
    else:
        i3.caption(t("No backups yet."))

with tab_log:
    st.caption(t("Log messages are stored as recorded at download time."))
    ui.show_table(db.get_download_log(1000))
ui.explain("explain_database")
ui.footer()
