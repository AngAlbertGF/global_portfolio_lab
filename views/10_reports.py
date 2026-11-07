"""Reports and Exports: CSV, Excel, PNG, HTML, PDF and the reproducibility snapshot."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from src import ui
from src.horizons import tag
from src.i18n import t
from src.reporting import build_tables, config_snapshot, cumulative_png, frontier_png, html_report, pdf_report, \
    save_outputs, to_csv_zip_bytes, to_excel_bytes
from src.statistics import rf_markowitz

ui.page_header(t("Reports and Exports"), t("Every export is generated from the same analysis shown in the app, so "
                                           "exported numbers match the screen."))
s = ui.settings()
bundle = ui.get_analysis()
if bundle is None:
    st.stop()
h = ui.horizon_selector(bundle, "rep_h")
r = bundle.horizons[h]
ui.horizon_banner(r)
stamp = datetime.now().strftime("%Y%m%d_%H%M")
st.caption(t("Calculated {created}; data cutoff {cutoff}; base currency {ccy}.", created=bundle.created_at,
             cutoff=bundle.data_cutoff, ccy=s.base_currency))

tables = build_tables(bundle, ui.db())
cfg = config_snapshot(bundle)
c = st.columns(3)
with c[0].container(border=True):
    st.markdown(t("**Data for Python, Excel or R**"))
    st.caption(t("{n} tables. Sheet and column names stay in English identifiers so scripts keep working in any "
                 "language.", n=len(tables)))
    st.download_button(t("Excel workbook (.xlsx)"), to_excel_bytes(tables, cfg), f"global_portfolio_lab_{stamp}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table:")
    st.download_button(t("All tables as CSV (.zip)"), to_csv_zip_bytes(tables, cfg),
                       f"global_portfolio_lab_{stamp}.zip", "application/zip", icon=":material/folder_zip:")
    st.download_button(t("Analysis configuration (.json)"), cfg.encode(), f"analysis_config_{stamp}.json",
                       "application/json", icon=":material/data_object:")
with c[1].container(border=True):
    st.markdown(t("**Reports in the interface language**"))
    st.caption(t("Executive summary, composition, data coverage, methodology, results, cross-horizon comparison, "
                 "sensitivity and limitations."))
    offline = st.toggle(t("Embed charting library (works offline, ~4 MB)"), value=False)
    if st.button(t("Build HTML report"), icon=":material/html:"):
        st.session_state.html_rep = html_report(bundle, h, "inline" if offline else "cdn")
    if st.session_state.get("html_rep"):
        st.download_button(t("Download HTML report"), st.session_state.html_rep.encode(), f"report_{tag(h)}_{stamp}.html",
                           "text/html", icon=":material/download:")
    if st.button(t("Build PDF report"), icon=":material/picture_as_pdf:"):
        with st.spinner(t("Rendering PDF...")):
            st.session_state.pdf_rep = pdf_report(bundle, h)
    if st.session_state.get("pdf_rep"):
        st.download_button(t("Download PDF report"), st.session_state.pdf_rep, f"report_{tag(h)}_{stamp}.pdf",
                           "application/pdf", icon=":material/download:")
with c[2].container(border=True):
    st.markdown(t("**Figures**"))
    if r.analyzable:
        st.caption(t("Static PNG images of the selected horizon."))
        rf = rf_markowitz(s.risk_free_annual, s.periods_per_year)
        st.download_button(t("Frontier chart (.png)"), frontier_png(r, rf, s.base_currency),
                           f"frontier_{tag(h)}_{stamp}.png", "image/png", icon=":material/image:")
        st.download_button(t("Cumulative return chart (.png)"), cumulative_png(r, s.base_currency),
                           f"cumulative_{tag(h)}_{stamp}.png", "image/png", icon=":material/image:")
    else:
        st.caption(t("Figures need a complete horizon."))
if st.button(t("Save every format to the outputs folder ({path})", path=s.output_dir), icon=":material/save:"):
    paths = save_outputs(bundle, ui.db(), Path(s.output_dir), h)
    st.success(t("Written: {files}", files=", ".join(p.name for p in paths)))
with st.expander(t("Preview a table")):
    name = st.selectbox(t("Table"), sorted(tables))
    st.dataframe(tables[name], width="stretch")
ui.footer()
