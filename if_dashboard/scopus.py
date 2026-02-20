from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import JournalItem
from .storage import CacheStore


@dataclass
class ApiUsage:
    api_calls_made: int = 0
    cache_hits: int = 0
    quota_limit: int | None = None
    quota_remaining: int | None = None

    @property
    def quota_used(self) -> int | None:
        if self.quota_limit is None or self.quota_remaining is None:
            return None
        return self.quota_limit - self.quota_remaining


class ScopusClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        cache: CacheStore,
        insttoken: str | None = None,
        timeout: int = 30,
        search_count: int = 25,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.timeout = timeout
        self.usage = ApiUsage()
        self.search_count = max(1, search_count)
        self.headers = {"X-ELS-APIKey": self.api_key, "Accept": "application/json"}
        if insttoken:
            self.headers["X-ELS-Insttoken"] = insttoken

    def _get(self, path: str, params: dict[str, Any], cache_key: str) -> dict[str, Any]:
        rec = self.cache.get(cache_key)
        if rec and self.cache.is_fresh(rec):
            self.usage.cache_hits += 1
            return rec.payload

        query = urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        req = Request(url, headers=self.headers)

        try:
            with urlopen(req, timeout=self.timeout) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                self.usage.api_calls_made += 1
                self._update_quota_from_headers(dict(response.headers.items()))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            detail = (
                f"Scopus API request failed ({exc.code}) for {path}. "
                f"URL: {url}. Response: {body[:500]}"
            )
            raise RuntimeError(detail) from exc

        self.cache.set(cache_key, payload)
        return payload

    def _update_quota_from_headers(self, headers: dict[str, str]) -> None:
        normalized = {k.lower(): v for k, v in headers.items()}
        limit = normalized.get("x-ratelimit-limit")
        remaining = normalized.get("x-ratelimit-remaining")
        if limit and limit.isdigit():
            self.usage.quota_limit = int(limit)
        if remaining and remaining.isdigit():
            self.usage.quota_remaining = int(remaining)

    @staticmethod
    def _extract_scopus_id(eid: str) -> str:
        match = re.search(r"(\d+)$", eid)
        if not match:
            raise ValueError(f"Could not extract numeric scopus_id from EID: {eid}")
        return match.group(1)

    def fetch_journal_items(self, issn: str, year: int) -> list[dict[str, Any]]:
        query = f"ISSN({issn}) AND PUBYEAR IS {year}"
        payload = self._get(
            "/content/search/scopus",
            {"query": query, "count": self.search_count, "view": "STANDARD"},
            cache_key=f"search:{issn}:{year}:count={self.search_count}",
        )
        return payload.get("search-results", {}).get("entry", [])

    def fetch_citations_by_year(self, eid: str, start_year: int, end_year: int) -> dict[int, int]:
        scopus_id = self._extract_scopus_id(eid)
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
