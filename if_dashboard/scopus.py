from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import JournalItem
from .storage import CacheStore


class ScopusClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        cache: CacheStore,
        insttoken: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout
        self.headers = {"X-ELS-APIKey": self.api_key, "Accept": "application/json"}
        if insttoken:
            self.headers["X-ELS-Insttoken"] = insttoken

    def _get(self, path: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
        rec = self.cache.get(cache_key)
        if rec and self.cache.is_fresh(rec):
            return rec.payload

        query = urlencode(params)
        req = Request(f"{self.base_url}{path}?{query}", headers=self.headers)
        with urlopen(req, timeout=self.timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        self.cache.set(cache_key, payload)
        return payload

    def fetch_journal_items(self, issn: str, year: int) -> list[dict[str, Any]]:
        query = f"ISSN({issn}) AND PUBYEAR IS {year}"
        payload = self._get(
            "/content/search/scopus",
            {"query": query, "count": 200, "view": "STANDARD"},
            cache_key=f"search:{issn}:{year}",
        )
        return payload.get("search-results", {}).get("entry", [])

    def fetch_citations_by_year(self, eid: str, start_year: int, end_year: int) -> dict[int, int]:
        scopus_id = eid.split("-")[-1]
        payload = self._get(
            "/content/abstract/citations",
            {
                "scopus_id": scopus_id,
                "date": f"{start_year}-{end_year}",
                "view": "STANDARD",
            },
            cache_key=f"citations:{eid}:{start_year}:{end_year}",
        )
        return self._parse_citations(payload)

    @staticmethod
    def _parse_citations(payload: dict[str, Any]) -> dict[int, int]:
        out: dict[int, int] = {}
        matrix = (
            payload.get("abstract-citations-response", {})
            .get("citeInfoMatrix", {})
            .get("citeInfoMatrixXML", {})
            .get("citationMatrix", {})
            .get("citeInfoMatrix", [])
        )

        if isinstance(matrix, dict):
            matrix = [matrix]

        for row in matrix:
            year = row.get("@year") or row.get("year")
            value = row.get("$") or row.get("value") or row.get("@value")
            if year is None:
                continue
            out[int(year)] = int(value or 0)

        if not out:
            year_cells = (
                payload.get("abstract-citations-response", {})
                .get("citeInfoMatrix", {})
                .get("citeInfoMatrix", [])
            )
            for row in year_cells if isinstance(year_cells, list) else []:
                if "year" in row and "count" in row:
                    out[int(row["year"])] = int(row["count"])

        return out

    def hydrate_items_with_citations(
        self,
        issn: str,
        years: list[int],
        citation_window_start: int,
        citation_window_end: int,
    ) -> list[JournalItem]:
        items: list[JournalItem] = []
        for year in years:
            for entry in self.fetch_journal_items(issn, year):
                eid = entry.get("eid")
                if not eid:
                    continue
                citations_by_year = self.fetch_citations_by_year(
                    eid, citation_window_start, citation_window_end
                )
                items.append(
                    JournalItem(
                        eid=eid,
                        title=entry.get("dc:title", ""),
                        publication_year=year,
                        subtype=(entry.get("subtypeDescription") or "").lower(),
                        citations_by_year=citations_by_year,
                    )
                )
        return items
