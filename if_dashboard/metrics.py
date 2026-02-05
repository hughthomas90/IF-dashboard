from __future__ import annotations

from dataclasses import dataclass

from .models import JournalItem

CITABLE_TYPES = {"article", "review"}


@dataclass
class MetricResult:
    metric_year: int
    numerator: int
    denominator: int
    value: float | None
    numerator_items: list[JournalItem]
    denominator_items: list[JournalItem]


def compute_impact_factor(items: list[JournalItem], metric_year: int) -> MetricResult:
    window_years = {metric_year - 1, metric_year - 2}
    window_items = [i for i in items if i.publication_year in window_years]

    numerator_items = [
        i for i in window_items if i.citations_by_year.get(metric_year, 0) > 0
    ]
    numerator = sum(i.citations_by_year.get(metric_year, 0) for i in window_items)

    denominator_items = [i for i in window_items if i.subtype in CITABLE_TYPES]
    denominator = len(denominator_items)

    value = (numerator / denominator) if denominator else None
    return MetricResult(
        metric_year=metric_year,
        numerator=numerator,
        denominator=denominator,
        value=value,
        numerator_items=numerator_items,
        denominator_items=denominator_items,
    )


def compute_immediacy_factor(items: list[JournalItem], metric_year: int) -> MetricResult:
    same_year_items = [i for i in items if i.publication_year == metric_year]
    numerator_items = [
        i for i in same_year_items if i.citations_by_year.get(metric_year, 0) > 0
    ]
    numerator = sum(i.citations_by_year.get(metric_year, 0) for i in same_year_items)

    denominator_items = [i for i in same_year_items if i.subtype in CITABLE_TYPES]
    denominator = len(denominator_items)

    value = (numerator / denominator) if denominator else None
    return MetricResult(
        metric_year=metric_year,
        numerator=numerator,
        denominator=denominator,
        value=value,
        numerator_items=numerator_items,
        denominator_items=denominator_items,
    )
