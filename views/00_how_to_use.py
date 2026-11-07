"""How to use: a step-by-step guide, page reference, interpretation notes, glossary and troubleshooting."""
from __future__ import annotations

import streamlit as st

from src import i18n, ui
from src.i18n import t

ui.page_header(t("How to use"), t("A practical guide to building a portfolio, reading the results and fixing common "
                                  "problems."), show_allocation=False)

sections = i18n.doc_sections("guide")
intro = [b for h, b in sections if not h]
if intro:
    st.markdown(intro[0])
named = [(h, b) for h, b in sections if h]

c1, c2, c3 = st.columns(3)
c1.page_link("views/02_portfolio_builder.py", label=t("Open Portfolio Builder"), icon=":material/construction:")
c2.page_link("views/11_settings.py", label=t("Try the offline demo (Settings)"), icon=":material/science:")
c3.page_link("views/01_dashboard.py", label=t("Back to the Dashboard"), icon=":material/dashboard:")

tabs = st.tabs([h for h, _ in named])
for i, (tab, (heading, body)) in enumerate(zip(tabs, named)):
    with tab, st.container(key=f"guide_{i}"):
        st.markdown(body)
ui.footer()
