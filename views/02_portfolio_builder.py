"""Portfolio Builder: 1) market allocation  2) securities and within-market weights  3) confirmation & download."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, ui
from src.config import ALLOCATION_TOLERANCE_PCT
from src.i18n import t
from src.validation import Holding, Portfolio, global_weights, validate_holdings, validate_market_allocations

ui.page_header(t("Portfolio Builder"), t("Allocate capital across markets, pick exact Yahoo Finance tickers, then "
                                         "confirm and download their history."))
ui.intro(t("Three steps: split 100% of your money among markets, choose the stocks inside each market (by name from "
           "your database or by exact Yahoo ticker), then download their prices."))
ss = st.session_state
ss.setdefault("alloc_version", 0)
ss.setdefault("hold_version", 0)
p = ui.portfolio()
mk = ui.markets()
db = ui.db()
s = ui.settings()

alloc_check = validate_market_allocations(p.market_allocations) if p.market_allocations else None
hold_check = validate_holdings(p, s.long_only)
done = {1: bool(alloc_check and alloc_check.ok), 2: hold_check.ok,
        3: hold_check.ok and all(db.get_date_range(tk)[2] > 0 for tk in p.tickers)}
if "_goto_step" in ss:  # programmatic navigation must be applied before the widget is created
    ss.step_selector = ss.builder_step = ss.pop("_goto_step")


def goto(n: int) -> None:
    ss._goto_step = n
    st.rerun()


labels = {1: t("1. Market allocation"), 2: t("2. Securities"), 3: t("3. Confirm and download")}
ss.setdefault("step_selector", ss.builder_step)
step = st.segmented_control(t("Workflow step"), [1, 2, 3],
                            format_func=lambda k: ("✓ " if done[k] else "") + labels[k], key="step_selector")
step = step or ss.builder_step
ss.builder_step = step

# ---------------------------------------------------------------------- load / templates
with st.expander(t("Load a saved portfolio or allocation template"), icon=":material/folder_open:"):
    saved = db.list_portfolios()
    c1, c2 = st.columns(2)
    with c1:
        if saved.empty:
            st.caption(t("No saved portfolios yet."))
        else:
            sv = saved.set_index("portfolio_id")
            choice = st.selectbox(t("Saved portfolios"), saved["portfolio_id"],
                                  format_func=lambda i: t("{name} ({n} holdings)", name=sv.loc[i, "portfolio_name"],
                                                          n=sv.loc[i, "n_holdings"]))
            b1, b2 = st.columns(2)
            if b1.button(t("Load portfolio"), icon=":material/upload:"):
                loaded = db.load_portfolio(int(choice))
                if loaded:
                    ss.portfolio = loaded
                    ss.alloc_version += 1
                    ss.hold_version += 1
                    st.rerun()
            if b2.button(t("Delete portfolio"), icon=":material/delete:"):
                db.delete_portfolio(int(choice))
                st.rerun()
    with c2:
        templates = db.list_templates()
        if templates:
            tname = st.selectbox(t("Allocation templates"), list(templates))
            if st.button(t("Apply template"), icon=":material/content_paste:"):
                p.market_allocations = {k: float(v) for k, v in templates[tname].items() if k in mk}
                ss.alloc_version += 1
                st.rerun()
        else:
            st.caption(t("No allocation templates yet (save one in step 1)."))

# ---------------------------------------------------------------------- STEP 1
if step == 1:
    st.subheader(t("Step 1: divide 100% of capital among markets"))
    COL_MARKET, COL_CCY, COL_EXCH = t("Market"), t("Currency"), t("Exchanges")
    COL_SUFFIX, COL_PRIO, COL_ALLOC = t("Ticker suffix"), t("Priority"), t("Allocation %")
    with st.container(key="inputs_step1"):
        c1, c2, c3 = st.columns([1, 1, 1])
        p.name = c1.text_input(t("Portfolio name"), p.name, max_chars=80)
        cap = c2.number_input(t("Capital to invest ({ccy})", ccy=s.base_currency), min_value=0.0,
                              value=float(p.total_capital or 0.0), step=10000.0, format="%.2f",
                              help=t("Every result in money (final value, gains, losses, VaR) uses this amount. Leave "
                                     "at 0 to use the default of {default} from Settings.",
                                     default=ui.fmt_money(s.default_capital)))
        p.total_capital = cap if cap > 0 else None
        p.base_currency = s.base_currency
        c3.metric(t("Reporting currency"), p.base_currency, help=t("Change it in Settings."))

        rows = [{"market_id": m.market_id, COL_MARKET: t(m.name), COL_CCY: m.currency,
                 COL_EXCH: ", ".join(m.exchanges), COL_SUFFIX: m.suffix_text(), COL_PRIO: "★" if m.priority else "",
                 COL_ALLOC: float(p.market_allocations.get(m.market_id, 0.0))} for m in mk.values()]
        df = pd.DataFrame(rows).set_index("market_id")
        edited = st.data_editor(
            df, key=f"alloc_editor_{ss.alloc_version}", width="stretch", height=420,
            disabled=[COL_MARKET, COL_CCY, COL_EXCH, COL_SUFFIX, COL_PRIO],
            column_config={"market_id": st.column_config.Column(t("ID")),
                           COL_ALLOC: st.column_config.NumberColumn(COL_ALLOC, min_value=0.0, max_value=100.0,
                                                                    step=0.01, format="%.2f")})
        p.market_allocations = {m: float(a) for m, a in edited[COL_ALLOC].items() if pd.notna(a) and a > 0}

        sel = st.multiselect(t("Markets for equal weighting"), list(mk), default=list(p.market_allocations),
                             format_func=lambda m: t(mk[m].name))
        b2, b3, b4, _ = st.columns([1, 1, 1, 2])
        if b2.button(t("Equal-weight"), icon=":material/balance:", disabled=not sel, width="stretch"):
            p.market_allocations = {m: 100.0 / len(sel) for m in sel}
            ss.alloc_version += 1
            st.rerun()
        if b3.button(t("Reset"), icon=":material/restart_alt:", width="stretch"):
            p.market_allocations = {}
            ss.alloc_version += 1
            st.rerun()
        if b4.button(t("Load example"), icon=":material/lightbulb:", width="stretch",
                     help=t("USA 50%, Mexico 20%, Brazil 10%, Japan 10%, Australia 5%, India 5%")):
            p.market_allocations = {"USA": 50.0, "MEXICO": 20.0, "BRAZIL": 10.0, "JAPAN": 10.0, "AUSTRALIA": 5.0,
                                    "INDIA": 5.0}
            ss.alloc_version += 1
            st.rerun()

    v = validate_market_allocations(p.market_allocations)
    total = v.details["total"]
    m1, m2, m3 = st.columns(3)
    m1.metric(t("Total allocated"), f"{total:.4f}%")
    m2.metric(t("Unallocated"), f"{100 - total:.4f}%",
              help=t("Tolerance for 'sums to 100%': ±{tol} percentage points.", tol=f"{ALLOCATION_TOLERANCE_PCT:g}"))
    m3.metric(t("Markets selected"), len(v.details["active_markets"]))
    if p.total_capital:
        st.caption(t("Unallocated capital: {value} {ccy}", value=f"{p.total_capital * (100 - total) / 100:,.2f}",
                     ccy=p.base_currency))
    left, right = st.columns([1, 1])
    with left:
        if v.ok:
            st.success(t("Allocation is valid."), icon=":material/check_circle:")
        for e in v.errors:
            st.error(e, icon=":material/error:")
        tname = st.text_input(t("Template name"), placeholder=t("e.g. Americas tilt"))
        if st.button(t("Save allocation template"), icon=":material/save:", disabled=not (v.ok and tname.strip())):
            db.save_template(tname.strip(), p.market_allocations)
            st.toast(t("Template '{name}' saved.", name=tname.strip()))
        # removing a market removes its holdings only after explicit confirmation
        orphans = [h.ticker for h in p.holdings if h.market_id not in p.market_allocations]
        if orphans:
            st.warning(t("Holdings in markets with 0% allocation: {tickers}.", tickers=", ".join(orphans)))
            if st.button(t("Remove those holdings"), icon=":material/delete:"):
                p.holdings = [h for h in p.holdings if h.market_id in p.market_allocations]
                ss.hold_version += 1
                st.rerun()
        if st.button(t("Continue to step 2"), type="primary", icon=":material/arrow_forward:", disabled=not v.ok):
            goto(2)
    with right:
        if p.market_allocations:
            st.plotly_chart(charts.market_donut(p.market_allocations,
                                                {k: ui.market_name(k) for k in p.market_allocations}),
                            width="stretch", theme=None)

# ---------------------------------------------------------------------- STEP 2
elif step == 2:
    st.subheader(t("Step 2: select securities inside each market"))
    v = validate_market_allocations(p.market_allocations)
    if not v.ok:
        st.error(t("Fix the market allocation in step 1 first."), icon=":material/error:")
        st.stop()
    st.caption(t("Pick stocks already in your database by **name** (left), or add a new one with its **exact Yahoo "
                 "Finance symbol** including the exchange suffix (right; e.g. `WALMEX.MX`, `7203.T`, `PETR4.SA`, "
                 "`BHP.AX`, `RELIANCE.NS`). Each percentage is the share of its market's allocation; within each "
                 "market they must sum to 100%."))
    svc = ui.service()
    COL_T, COL_N, COL_E, COL_C = t("Ticker"), t("Name"), t("Exchange"), t("Currency")
    COL_W, COL_TOT, COL_S, COL_R = t("Within %"), t("Total %"), t("Status"), t("Remove")
    for m in v.details["active_markets"]:
        cfg = mk[m]
        members = [h for h in p.holdings if h.market_id == m]
        msum = sum(h.within_pct for h in members)
        complete = bool(members) and abs(msum - 100) <= ALLOCATION_TOLERANCE_PCT
        with st.container(border=True):
            st.markdown(f"#### {'✓ ' if complete else ''}{t(cfg.name)}  \n"
                        f":blue-badge[{t('{value}% of capital', value=f'{p.market_allocations[m]:.2f}')}] "
                        f":gray-badge[{cfg.currency}] :gray-badge[{t('suffix')} {cfg.suffix_text()}]")
            pick_col, form_col = st.columns([3, 2])
            with pick_col:
                st.markdown(t("**Pick from your database** (name, logo and chart color)"))
                picked = ui.security_picker(f"pick_{m}", market_id=m, in_portfolio=set(p.tickers))
            with form_col, st.container(key=f"inputs_add_{m}"):
                st.markdown(t("**Or add a new ticker**"))
                with st.form(f"add_{m}", clear_on_submit=True, border=False):
                    raw = st.text_input(t("Ticker"), key=f"tk_{m}", placeholder=t("exact Yahoo symbol"))
                    c2, c3 = st.columns([1, 1], vertical_alignment="bottom")
                    pct_in = c2.number_input(t("Within-market %"), 0.0, 100.0, value=max(0.0, 100.0 - msum),
                                             step=1.0, key=f"pc_{m}")
                    submitted = c3.form_submit_button(t("Validate and add"), icon=":material/add:")
            if picked and picked not in p.tickers:
                raw, pct_in, submitted = picked, max(0.0, 100.0 - msum), True
            if submitted and raw.strip():
                with st.spinner(t("Validating {ticker}...", ticker=raw.strip())):
                    res = svc.validate_ticker(raw, m)
                if res.ticker in p.tickers:
                    st.error(t("{ticker} is already in the portfolio; duplicates are rejected.", ticker=res.ticker))
                elif res.accepted:
                    ui.ensure_logos([res.ticker])
                    p.holdings.append(Holding(res.ticker, m, float(pct_in), res.name or "", res.exchange or "",
                                              res.currency or "", "VALID", res.warnings))
                    ss.hold_version += 1
                    st.toast(t("Added {ticker} ({message})", ticker=res.ticker, message=res.message))
                    st.rerun()
                elif res.status == "PROVIDER_ERROR":
                    st.warning(res.message + " " + t("Nothing was added; try again shortly."),
                               icon=":material/cloud_off:")
                else:
                    st.error(f"{ui.status_label(res.status)}: {res.message}", icon=":material/error:")
            if members:
                meta = {h.ticker: db.get_security(h.ticker) or {} for h in members}
                uris = ui.logo_uris([h.ticker for h in members])
                hdf = pd.DataFrame([{"logo": uris.get(h.ticker), COL_T: h.ticker,
                                     COL_N: h.name or meta[h.ticker].get("security_name") or "",
                                     COL_E: h.exchange or meta[h.ticker].get("exchange") or "",
                                     COL_C: h.currency or meta[h.ticker].get("currency") or "",
                                     COL_W: h.within_pct,
                                     COL_TOT: p.market_allocations[m] * h.within_pct / 100,
                                     COL_S: ui.status_label(h.validation_status if h.validation_status != "UNVALIDATED"
                                                            else (meta[h.ticker].get("validation_status")
                                                                  or "UNVALIDATED")),
                                     COL_R: False} for h in members])
                ed = st.data_editor(hdf, key=f"hold_{m}_{ss.hold_version}", hide_index=True, width="stretch",
                                    disabled=["logo", COL_T, COL_N, COL_E, COL_C, COL_TOT, COL_S],
                                    column_config={"logo": ui.logo_column(),
                                                   COL_W: st.column_config.NumberColumn(min_value=0.0, max_value=100.0,
                                                                                        step=0.01, format="%.2f"),
                                                   COL_TOT: st.column_config.NumberColumn(format="%.4f")})
                changed = False
                for h, (_, row) in zip(members, ed.iterrows()):
                    if pd.notna(row[COL_W]) and float(row[COL_W]) != h.within_pct:
                        h.within_pct = float(row[COL_W])
                        changed = True
                remove = set(ed.loc[ed[COL_R], COL_T])
                if remove:
                    p.holdings = [h for h in p.holdings if h.ticker not in remove]
                    changed = True
                if changed:
                    ss.hold_version += 1
                    st.rerun()
                for h in members:
                    for w in h.warnings:
                        st.warning(w, icon=":material/warning:")
                c1, c2 = st.columns([1, 3], vertical_alignment="center")
                if c1.button(t("Equal-weight this market"), key=f"eq_{m}", icon=":material/balance:"):
                    for h in members:
                        h.within_pct = 100.0 / len(members)
                    ss.hold_version += 1
                    st.rerun()
                if complete:
                    c2.success(t("Within-market weights sum to {value}%", value=f"{msum:.4f}"))
                else:
                    c2.error(t("Within-market weights sum to {value}% (must be 100%)", value=f"{msum:.4f}"))
            else:
                st.info(t("No securities yet in this market. Add the first ticker above."))
    hv = validate_holdings(p, s.long_only)
    if hv.ok:
        st.success(t("All markets complete: {n} securities, global weights sum to {total}.", n=len(p.holdings),
                     total=f"{global_weights(p).sum():.10f}"), icon=":material/check_circle:")
        if st.button(t("Continue to confirmation"), type="primary", icon=":material/arrow_forward:"):
            goto(3)
    else:
        with st.expander(t("Outstanding issues ({n})", n=len(hv.errors)), expanded=True):
            for e in hv.errors:
                st.write("- " + e)

# ---------------------------------------------------------------------- STEP 3
else:
    st.subheader(t("Step 3: confirm and download"))
    hv = validate_holdings(p, s.long_only)
    if not hv.ok:
        st.error(t("The portfolio is not valid yet:"), icon=":material/error:")
        for e in hv.errors:
            st.write("- " + e)
        st.stop()
    svc = ui.service()
    w = global_weights(p)
    work = svc.workload_estimate([(h.ticker, h.market_id) for h in p.holdings]).set_index("ticker")
    kinds = {"initial": t("initial"), "backfill": t("backfill"), "refresh": t("refresh"), "none": t("none")}
    rows = []
    for h in p.holdings:
        sec = db.get_security(h.ticker) or {}
        rows.append({t("Market"): ui.market_name(h.market_id), t("Market %"): p.market_allocations[h.market_id],
                     t("Ticker"): h.ticker, t("Name"): sec.get("security_name") or h.name,
                     t("Exchange"): sec.get("exchange") or h.exchange,
                     t("Currency"): sec.get("currency") or h.currency,
                     t("Within %"): h.within_pct, t("Total %"): w[h.ticker] * 100,
                     t("Stored obs"): int(work.loc[h.ticker, "stored_obs"]),
                     t("Stored history"): t("{start} to {end}", start=work.loc[h.ticker, "stored_first"] or "–",
                                            end=work.loc[h.ticker, "stored_last"] or "–"),
                     t("Planned download"): ", ".join(kinds.get(k.strip(), k) for k in
                                                     str(work.loc[h.ticker, "planned_requests"]).split(","))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={t("Market %"): st.column_config.NumberColumn(format="%.2f"),
                                t("Within %"): st.column_config.NumberColumn(format="%.2f"),
                                t("Total %"): st.column_config.NumberColumn(format="%.4f")})
    ccys = sorted(svc.required_currencies(p.tickers) - {p.base_currency})
    days = int(work["calendar_days_requested"].sum())
    fx_text = ", ".join(c + "→" + p.base_currency for c in ccys) or t("none")
    bench_text = t(", benchmark {ticker}", ticker=s.benchmark_ticker) if s.benchmark_ticker else ""
    st.caption(t("Expected workload: {n} securities ({days} calendar days requested), FX series: {fx}{bench}. "
                 "Target history: {years} calendar years.", n=len(p.holdings), days=f"{days:,}", fx=fx_text,
                 bench=bench_text, years=s.history_years))
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.market_donut(p.market_allocations, {k: ui.market_name(k) for k in p.market_allocations}),
                        width="stretch", theme=None)
    with c2:
        st.plotly_chart(charts.security_treemap(w, {h.ticker: h.market_id for h in p.holdings},
                                                [m for m, a in p.market_allocations.items() if a > 0],
                                                {k: ui.market_name(k) for k in p.market_allocations},
                                                ui.security_colors(p.tickers)),
                        width="stretch", theme=None)
    a1, a2, a3, a4, a5 = st.columns(5)
    if a1.button(t("Edit selections"), icon=":material/edit:"):
        goto(2)
    if a2.button(t("Remove securities"), icon=":material/delete:"):
        goto(2)
    if a3.button(t("Save portfolio"), icon=":material/save:"):
        pid = db.save_portfolio(p)
        st.toast(t("Saved '{name}' (id {id}).", name=p.name, id=pid))
    go_download = a4.button(t("Confirm and download"), type="primary", icon=":material/cloud_download:")
    if a5.button(t("Cancel"), icon=":material/close:"):
        if p.portfolio_id:
            ss.portfolio = db.load_portfolio(p.portfolio_id) or Portfolio(name=t("My portfolio"),
                                                                          base_currency=s.base_currency)
        else:
            ss.portfolio = Portfolio(name=t("My portfolio"), base_currency=s.base_currency)
        ss.alloc_version += 1
        ss.hold_version += 1
        goto(1)
    if go_download:
        db.save_portfolio(p)
        items = [(h.ticker, h.market_id) for h in p.holdings]
        bench = s.benchmark_ticker.strip()
        if bench and bench not in p.tickers:
            bm = next((k for k, m in mk.items() if m.benchmark == bench), None)
            if db.get_security(bench) is None:
                svc.validate_ticker(bench, bm or "USA")
            items.append((bench, bm))
        bar = st.progress(0.0, t("Starting downloads..."))
        results = svc.update_many(items, p.base_currency, progress=lambda f, msg: bar.progress(min(f, 1.0), msg))
        bar.progress(1.0, t("Fetching logos..."))
        ui.ensure_logos([h.ticker for h in p.holdings])
        ss.last_download_results = pd.DataFrame([{"symbol": r.symbol, "status": r.status,
                                                  "rows_received": r.received, "rows_inserted": r.inserted,
                                                  "rows_updated": r.updated, "rebased": r.rebased,
                                                  "repairs": r.repairs, "messages": " | ".join(r.messages)}
                                                 for r in results])
    if ss.last_download_results is not None:
        res = ss.last_download_results
        bad = res[~res["status"].isin(["SUCCESS", "UP_TO_DATE"])]
        if bad.empty:
            st.success(t("All downloads completed. Stored data are reused on the next run."), icon=":material/check:")
        else:
            st.warning(t("{n} item(s) did not fully succeed; previously stored data were kept. Retry from "
                         "Historical Database.", n=len(bad)), icon=":material/warning:")
        ui.show_table(res)
        st.page_link("views/05_portfolio_statistics.py", label=t("Go to Portfolio Statistics"),
                     icon=":material/arrow_forward:")
ui.explain("explain_builder")
ui.footer()
