import os
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

import pandas as pd
import streamlit as st

from scopus_client import ElsevierScopusClient, ScopusApiError
from metrics import (
    JournalSelection,
    lookup_journals_by_title,
    get_journal_metadata_by_issn,
    compute_scopus_if_proxy,
)

st.set_page_config(
    page_title="Scopus IF Proxy Dashboard",
    page_icon="📈",
    layout="wide",
)

st.title("Scopus-derived Impact Factor Proxy Dashboard")

with st.expander("What this is (and what it isn't)", expanded=False):
    st.markdown(
        """
This app computes a **Scopus-derived proxy** for the classic 2‑year Journal Impact Factor (JIF).

**Proxy definition (JIF-like):**

- **Numerator:** citations received in year *Y* to items published in years *Y‑1* and *Y‑2* (from Scopus).
- **Denominator:** number of “citable items” published in years *Y‑1* and *Y‑2* (default: Scopus DOCTYPE **ar** + **re**).

You can also switch to a symmetric variant where numerator and denominator use the same document types.

**Important:** This is not Clarivate’s JIF and will differ because of database coverage, document type rules, and counting methods.
        """
    )

# --- Secrets / credentials ---
def _get_secret(name: str, default: Optional[str] = None) -> Optional[str]:
    # Streamlit Cloud: st.secrets
    if name in st.secrets:
        return str(st.secrets[name])
    # Local: environment variables
    return os.environ.get(name, default)

API_KEY = _get_secret("SCOPUS_API_KEY")
INSTTOKEN = _get_secret("SCOPUS_INSTTOKEN", None)

if not API_KEY:
    st.error(
        "Missing SCOPUS_API_KEY. Add it to Streamlit secrets or set an env var SCOPUS_API_KEY."
    )
    st.stop()

client = ElsevierScopusClient(api_key=API_KEY, insttoken=INSTTOKEN)

# --- Sidebar controls ---
st.sidebar.header("Journal & Proxy settings")

mode = st.sidebar.radio(
    "Select journal by…",
    options=["Title search", "ISSN"],
    index=0,
)

selection: Optional[JournalSelection] = None

if mode == "Title search":
    title_query = st.sidebar.text_input("Journal title (partial ok)", value="")
    max_hits = st.sidebar.slider("Max search results", 5, 25, 10)
    if st.sidebar.button("Search journals"):
        if not title_query.strip():
            st.sidebar.warning("Type a journal title (or part of it) first.")
        else:
            try:
                hits = lookup_journals_by_title(client, title_query.strip(), max_results=max_hits)
            except ScopusApiError as e:
                st.sidebar.error(f"Serial Title API error: {e}")
                hits = []

            if not hits:
                st.sidebar.warning("No journals found for that title query.")
            else:
                st.session_state["journal_hits"] = hits

    hits = st.session_state.get("journal_hits", [])
    if hits:
        labels = [f"{h.title} (ISSN: {h.issn or 'n/a'})" for h in hits]
        idx = st.sidebar.selectbox("Pick a journal", range(len(labels)), format_func=lambda i: labels[i])
        selection = hits[int(idx)]

else:
    issn = st.sidebar.text_input("ISSN (e.g., 0308-8146)", value="").strip()
    if issn:
        selection = JournalSelection(title=issn, issn=issn, source_id=None, publisher=None)

# --- Target year & counting rules ---
current_year = date.today().year
default_target_year = current_year - 1

target_year = st.sidebar.number_input(
    "Citations year Y",
    min_value=1970,
    max_value=current_year,
    value=default_target_year,
    step=1,
)

denom_doctypes = st.sidebar.multiselect(
    "Denominator doc types (citable items)",
    options=[
        ("ar", "Article (ar)"),
        ("re", "Review (re)"),
        ("cp", "Conference Paper (cp)"),
        ("le", "Letter (le)"),
        ("sh", "Short Survey (sh)"),
        ("ed", "Editorial (ed)"),
        ("no", "Note (no)"),
    ],
    default=[("ar", "Article (ar)"), ("re", "Review (re)")],
    format_func=lambda t: t[1],
)
denom_doctypes_codes = [t[0] for t in denom_doctypes]

numerator_mode = st.sidebar.selectbox(
    "Numerator document set",
    options=[
        ("all", "JIF-like: all item types in Y-1 & Y-2"),
        ("same", "Symmetric: same doc types as denominator"),
    ],
    index=0,
    format_func=lambda x: x[1],
)[0]

exclude_self = st.sidebar.checkbox("Exclude self-citations (if enabled for your key)", value=False)

run = st.sidebar.button("Compute proxy")

# --- Main area ---
if not selection:
    st.info("Choose a journal (left sidebar) to begin.")
    st.stop()

# Show journal metadata (title, publisher, Scopus metrics if available)
meta_col1, meta_col2 = st.columns([2, 3], gap="large")
with meta_col1:
    st.subheader("Journal")
    st.write(f"**Selection:** {selection.title}")
    if selection.issn:
        st.write(f"**ISSN:** {selection.issn}")
    if selection.publisher:
        st.write(f"**Publisher:** {selection.publisher}")
    if selection.source_id:
        st.write(f"**Scopus source-id:** {selection.source_id}")

with meta_col2:
    if selection.issn:
        try:
            meta = get_journal_metadata_by_issn(client, selection.issn)
        except ScopusApiError as e:
            st.warning(f"Could not load Serial Title metadata: {e}")
            meta = None

        if meta:
            st.subheader("Scopus journal metrics (from Serial Title API)")
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("CiteScore (current)", meta.get("citescore_current") or "—")
            with m2:
                st.metric("SJR (latest)", meta.get("sjr_latest") or "—")
            with m3:
                st.metric("SNIP (latest)", meta.get("snip_latest") or "—")

            if meta.get("yearly"):
                df_yearly = pd.DataFrame(meta["yearly"]).sort_values("year", ascending=False)
                st.dataframe(df_yearly, use_container_width=True)

if not run:
    st.stop()

# Compute proxy
with st.spinner("Computing Scopus-derived IF proxy…"):
    try:
        result = compute_scopus_if_proxy(
            client=client,
            issn=selection.issn,
            target_year=int(target_year),
            denom_doctypes=tuple(denom_doctypes_codes),
            numerator_mode=numerator_mode,
            exclude_self=exclude_self,
        )
    except ScopusApiError as e:
        st.error(str(e))
        st.stop()

# Display results
st.divider()
st.subheader("Scopus-derived IF proxy")

c1, c2, c3, c4 = st.columns(4, gap="large")
with c1:
    st.metric("IF proxy", f"{result.if_proxy:.3f}" if result.if_proxy is not None else "—")
with c2:
    st.metric("Citations in Y", result.citations_in_year)
with c3:
    st.metric("Denominator items", result.denom_items)
with c4:
    st.metric("Numerator items", result.numerator_items)

st.caption(
    f"Computed for citations year **{result.target_year}** to items published in **{result.target_year-1}** and **{result.target_year-2}**."
)

details = {
    "Target year (Y)": result.target_year,
    "Publication years counted": f"{result.target_year-2}, {result.target_year-1}",
    "Denominator doctypes": ", ".join(result.denom_doctypes) if result.denom_doctypes else "(none)",
    "Numerator mode": result.numerator_mode,
    "Excluded self-citations": result.exclude_self,
}

st.json(details)

# A small table by publication year
df = pd.DataFrame(result.breakdown_by_pubyear)
st.subheader("Breakdown by publication year")
st.dataframe(df, use_container_width=True)

st.subheader("Notes / troubleshooting")
st.markdown(
    """
- If you get **403 / authentication or entitlements** on Citation Overview, your key likely lacks that entitlement. Elsevier notes that the Citation Overview API can be access-controlled.  
- For very high-volume journals, this can take time and may hit rate limits because Citation Overview accepts **up to 25 identifiers per request** (batched).  
- Use Streamlit caching (already enabled in the code) or increase TTL to reduce repeated calls.
"""
)
