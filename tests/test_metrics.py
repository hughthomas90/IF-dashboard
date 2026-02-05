from if_dashboard.metrics import compute_impact_factor, compute_immediacy_factor
from if_dashboard.models import JournalItem


def _item(eid: str, year: int, subtype: str, cits: dict[int, int]) -> JournalItem:
    return JournalItem(eid=eid, title=eid, publication_year=year, subtype=subtype, citations_by_year=cits)


def test_impact_factor_uses_two_prior_years_and_article_review_denominator():
    items = [
        _item("E1", 2023, "article", {2025: 5}),
        _item("E2", 2024, "review", {2025: 3}),
        _item("E3", 2024, "editorial", {2025: 2}),
        _item("E4", 2025, "article", {2025: 4}),
    ]
    result = compute_impact_factor(items, 2025)
    assert result.numerator == 10
    assert result.denominator == 2
    assert result.value == 5.0


def test_immediacy_factor_uses_same_year_items():
    items = [
        _item("E1", 2025, "article", {2025: 2}),
        _item("E2", 2025, "editorial", {2025: 5}),
        _item("E3", 2024, "review", {2025: 10}),
    ]
    result = compute_immediacy_factor(items, 2025)
    assert result.numerator == 7
    assert result.denominator == 1
    assert result.value == 7.0
