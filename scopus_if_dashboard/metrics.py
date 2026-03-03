from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import streamlit as st

from scopus_client import ElsevierScopusClient, ScopusApiError


@dataclass(frozen=True)
class JournalSelection:
    title: str
    issn: Optional[str]
    source_id: Optional[str]
    publisher: Optional[str]


@dataclass(frozen=True)
class IFProxyResult:
    issn: str
    target_year: int
    denom_doctypes: Tuple[str, ...]
    numerator_mode: str
    exclude_self: bool

    citations_in_year: int
    denom_items: int
    numerator_items: int
    if_proxy: Optional[float]

    breakdown_by_pubyear: List[Dict[str, Any]]


# ---------------------------
# Serial Title API helpers
# ---------------------------

@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def lookup_journals_by_title(client: ElsevierScopusClient, title_query: str, max_results: int = 10) -> List[JournalSelection]:
    """
    Use Serial Title API search interface to find journals by title.
    """
    data = client.get_json("/content/serial/title", params={"title": title_query})
    resp = data.get("serial-metadata-response", {})
    entries = resp.get("entry", []) or []
    if isinstance(entries, dict):
        entries = [entries]

    out: List[JournalSelection] = []
    for e in entries[:max_results]:
        title = e.get("dc:title") or e.get("title") or "(unknown title)"
        issn = e.get("prism:issn") or e.get("issn")
        source_id = e.get("source-id") or e.get("source_id") or e.get("sourceId")
        publisher = e.get("dc:publisher") or e.get("publisher")

        out.append(JournalSelection(title=str(title), issn=str(issn) if issn else None,
                                   source_id=str(source_id) if source_id else None,
                                   publisher=str(publisher) if publisher else None))
    return out


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_journal_metadata_by_issn(client: ElsevierScopusClient, issn: str) -> Dict[str, Any]:
    """
    Pull journal-level metadata & metrics (CiteScore, SJR, SNIP, yearly-data) via Serial Title API.
    """
    data = client.get_json(f"/content/serial/title/issn/{issn}", params={})
    resp = data.get("serial-metadata-response", {})
    entry = resp.get("entry", [])
    if isinstance(entry, list) and entry:
        entry0 = entry[0]
    elif isinstance(entry, dict):
        entry0 = entry
    else:
        return {}

    # Extract metric lists (shape varies a bit depending on view/entitlement)
    def _latest_from_metric_list(metric_list: Any) -> Optional[str]:
        # Often: {"SNIP":[{"@year":"2022","$":"2.197"}, ...]}
        if not metric_list or not isinstance(metric_list, dict):
            return None
        # metric_list has a single key like "SNIP" or "SJR"
        for _, arr in metric_list.items():
            if isinstance(arr, dict):
                arr = [arr]
            if isinstance(arr, list) and arr:
                # pick max year if possible
                best = None
                for it in arr:
                    if not isinstance(it, dict):
                        continue
                    year = it.get("@year") or it.get("year")
                    val = it.get("$") or it.get("value")
                    if year is None or val is None:
                        continue
                    try:
                        y = int(year)
                    except Exception:
                        y = -1
                    if best is None or y > best[0]:
                        best = (y, str(val))
                if best:
                    return best[1]
        return None

    # CiteScore current
    citescore_current = None
    cs = entry0.get("citeScoreYearInfoList") or {}
    if isinstance(cs, dict):
        # A few possible key names
        citescore_current = cs.get("citeScoreCurrentMetric") or cs.get("citeScoreCurrentMetric", None)

    snip_latest = _latest_from_metric_list(entry0.get("SNIPList"))
    sjr_latest = _latest_from_metric_list(entry0.get("SJRList"))

    # yearly-data/info (publicationCount, citeCountSCE, etc.)
    yearly = []
    yd = entry0.get("yearly-data") or entry0.get("yearly-data/info") or {}
    if isinstance(yd, dict):
        info = yd.get("info") if isinstance(yd.get("info"), list) else yd.get("info")
        if isinstance(info, dict):
            info = [info]
        if isinstance(info, list):
            for it in info:
                if not isinstance(it, dict):
                    continue
                year = it.get("@year") or it.get("year")
                row = {"year": int(year) if str(year).isdigit() else year}
                for k, v in it.items():
                    if k in ("@year", "year"):
                        continue
                    row[k] = v
                yearly.append(row)

    return {
        "title": entry0.get("dc:title"),
        "publisher": entry0.get("dc:publisher"),
        "issn": entry0.get("prism:issn"),
        "source_id": entry0.get("source-id"),
        "citescore_current": citescore_current,
        "snip_latest": snip_latest,
        "sjr_latest": sjr_latest,
        "yearly": yearly,
    }


# ---------------------------
# Scopus Search API helpers
# ---------------------------

def _doctype_clause(doctypes: Sequence[str]) -> str:
    if not doctypes:
        return ""
    parts = [f"DOCTYPE({dt})" for dt in doctypes]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def scopus_search_total(client: ElsevierScopusClient, query: str) -> int:
    """Return totalResults for a query with one lightweight Search API call."""
    data = client.get_json("/content/search/scopus", params={"query": query, "count": 1, "start": 0, "view": "STANDARD"})
    sr = data.get("search-results", {})
    total = sr.get("opensearch:totalResults") or sr.get("opensearch_totalResults") or 0
    try:
        return int(total)
    except Exception:
        return 0


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def scopus_search_scopus_ids(
    client: ElsevierScopusClient,
    query: str,
    use_cursor: bool = False,
    count: int = 25,
    max_records: Optional[int] = None,
) -> List[str]:
    """
    Return list of numeric scopus_ids from Scopus Search API, using cursor-based pagination if possible.

    NOTE: Scopus Search returns dc:identifier like "SCOPUS_ID:1234567890".
    """
    ids: List[str] = []
    seen = set()

    # With Scopus Search, max "count" depends on the view. STANDARD is typically
    # higher throughput than COMPLETE. We only need SCOPUS_ID identifiers.
    params = {"query": query, "view": "STANDARD", "count": int(count)}
    cursor = "*" if use_cursor else None
    start = 0

    while True:
        page_params = dict(params)
        if cursor is not None:
            page_params["cursor"] = cursor
        else:
            page_params["start"] = start

        try:
            data = client.get_json("/content/search/scopus", params=page_params)
        except ScopusApiError as e:
            # Some API keys are not entitled to use cursor-based deep pagination.
            # If cursor is rejected, transparently fall back to start-based paging.
            msg = str(e).lower()
            if cursor is not None and ("cursor" in msg and "restricted" in msg):
                cursor = None
                start = 0
                continue
            raise
        sr = data.get("search-results", {})

        # If we are NOT using cursor pagination, Scopus Search has a 5,000 item
        # result cap for iterating results. If the result set is larger, we
        # cannot retrieve all identifiers accurately.
        if cursor is None and max_records is None:
            total = sr.get("opensearch:totalResults") or 0
            try:
                total_i = int(total)
            except Exception:
                total_i = 0
            if total_i > 5000:
                raise ScopusApiError(
                    f"Your query returned {total_i} results, but without cursor pagination only the first 5,000 can be retrieved. "
                    "Refine the query (e.g., limit doctypes) or request cursor pagination entitlement from Elsevier."
                )

        entries = sr.get("entry", []) or []
        if isinstance(entries, dict):
            entries = [entries]

        for e in entries:
            raw = e.get("dc:identifier") or e.get("dc_identifier") or ""
            scid = _parse_scopus_id(raw)
            if scid and scid not in seen:
                ids.append(scid)
                seen.add(scid)
                if max_records and len(ids) >= max_records:
                    return ids

        # pagination
        if cursor is not None:
            cursor_obj = sr.get("cursor") or {}
            nxt = cursor_obj.get("@next") or cursor_obj.get("next")
            if not nxt:
                break
            cursor = nxt
        else:
            total = sr.get("opensearch:totalResults") or 0
            try:
                total = int(total)
            except Exception:
                total = len(ids)
            start += int(count)
            if start >= total:
                break

        if not entries:
            break

    return ids


def _parse_scopus_id(dc_identifier: str) -> Optional[str]:
    if not dc_identifier:
        return None
    s = str(dc_identifier).strip()
    # Typical: "SCOPUS_ID:33646008552"
    if ":" in s:
        tail = s.split(":")[-1].strip()
        return tail if tail.isdigit() else tail
    # Sometimes already numeric
    return s if s.isdigit() else s


# ---------------------------
# Citation Overview API helpers
# ---------------------------

@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def citation_overview_citations_in_year(
    client: ElsevierScopusClient,
    scopus_ids: Tuple[str, ...],
    year: int,
    exclude_self: bool = False,
) -> int:
    """
    Sum citations in a single year for up to 25 Scopus IDs via Citation Overview API.
    """
    if not scopus_ids:
        return 0
    if len(scopus_ids) > 25:
        raise ValueError("Citation Overview batch size must be <= 25")

    params: Dict[str, Any] = {
        "scopus_id": ",".join(scopus_ids),
        "date": f"{year}-{year}",
    }
    if exclude_self:
        params["citation"] = "exclude-self"

    data = client.get_json("/content/abstract/citations", params=params)

    acr = data.get("abstract-citations-response", {})
    matrix = (
        acr.get("citeInfoMatrix", {})
        .get("citeInfoMatrixXML", {})
        .get("citationMatrix", {})
        .get("citeInfo", [])
    )
    if isinstance(matrix, dict):
        matrix = [matrix]

    total = 0
    for doc in matrix:
        # Each doc['cc'] is a list of dicts with '$' holding the count.
        cc = doc.get("cc")
        if not cc:
            continue
        if isinstance(cc, dict):
            cc = [cc]
        if isinstance(cc, list):
            for it in cc:
                if isinstance(it, dict) and "$" in it:
                    try:
                        total += int(it["$"])
                    except Exception:
                        pass
                elif isinstance(it, str) and it.isdigit():
                    total += int(it)
    return total


# ---------------------------
# Proxy metric computation
# ---------------------------

def _build_journal_year_query(
    issn: str,
    pubyear: int,
    doctypes: Optional[Sequence[str]],
) -> str:
    # Use ISSN and SRCTYPE(j) as per Scopus Search field codes.
    # - ISSN search also matches ISSNP and EISSN.
    # - PUBYEAR uses numeric operators; we use "=".
    base = f"ISSN({issn}) AND SRCTYPE(j) AND PUBYEAR = {int(pubyear)}"
    dt_clause = _doctype_clause(tuple(doctypes or ()))
    if dt_clause:
        return f"{base} AND {dt_clause}"
    return base


def compute_scopus_if_proxy(
    client: ElsevierScopusClient,
    issn: str,
    target_year: int,
    denom_doctypes: Tuple[str, ...] = ("ar", "re"),
    numerator_mode: str = "all",  # "all" or "same"
    exclude_self: bool = False,
    use_cursor_pagination: bool = False,
) -> IFProxyResult:
    """
    Compute a 2-year "impact factor"-like proxy from Scopus:
        citations in Y to items in (Y-1, Y-2) / number of citable items in (Y-1, Y-2)

    denom_doctypes: used for denominator (default ar+re).
    numerator_mode:
        - "all": numerator is ALL item types from Y-1 & Y-2 (JIF-like asymmetry)
        - "same": numerator uses same doctypes as denominator (symmetric)
    """
    issn = (issn or "").strip()
    if not issn:
        raise ScopusApiError("ISSN is required to compute proxy.")

    y1, y2 = int(target_year) - 1, int(target_year) - 2

    # Denominator counts: light calls (totalResults)
    denom_queries = [
        _build_journal_year_query(issn, y1, denom_doctypes),
        _build_journal_year_query(issn, y2, denom_doctypes),
    ]
    denom_counts = [scopus_search_total(client, q) for q in denom_queries]
    denom_total = sum(denom_counts)

    # Numerator document set
    if numerator_mode not in ("all", "same"):
        raise ScopusApiError("numerator_mode must be 'all' or 'same'.")

    num_doctypes = None if numerator_mode == "all" else denom_doctypes
    num_queries = [
        _build_journal_year_query(issn, y1, num_doctypes),
        _build_journal_year_query(issn, y2, num_doctypes),
    ]

    # Fetch IDs (potentially many). If your API key is not entitled to
    # cursor-based deep pagination, you must keep each query <= 5,000 results.
    num_ids: List[str] = []
    for q in num_queries:
        num_ids.extend(
            scopus_search_scopus_ids(
                client,
                q,
                use_cursor=bool(use_cursor_pagination),
                count=25,
            )
        )

    numerator_items = len(num_ids)

    # Batch citation overview calls (<=25 ids each)
    citations_total = 0
    batch_size = 25
    for i in range(0, len(num_ids), batch_size):
        batch = tuple(num_ids[i : i + batch_size])
        citations_total += citation_overview_citations_in_year(client, batch, int(target_year), exclude_self=exclude_self)

    if_proxy = None
    if denom_total > 0:
        if_proxy = citations_total / denom_total

    breakdown = [
        {"pubyear": y2, "denominator_items": denom_counts[1], "numerator_items": None if numerator_mode == "all" else denom_counts[1]},
        {"pubyear": y1, "denominator_items": denom_counts[0], "numerator_items": None if numerator_mode == "all" else denom_counts[0]},
    ]

    return IFProxyResult(
        issn=issn,
        target_year=int(target_year),
        denom_doctypes=tuple(denom_doctypes),
        numerator_mode=numerator_mode,
        exclude_self=exclude_self,
        citations_in_year=int(citations_total),
        denom_items=int(denom_total),
        numerator_items=int(numerator_items),
        if_proxy=if_proxy,
        breakdown_by_pubyear=breakdown,
    )
