from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JournalItem:
    eid: str
    title: str
    publication_year: int
    subtype: str
    citations_by_year: dict[int, int]
