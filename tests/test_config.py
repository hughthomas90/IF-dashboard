from if_dashboard.config import get_settings


def test_default_scopus_search_count(monkeypatch):
    monkeypatch.delenv("SCOPUS_SEARCH_COUNT", raising=False)
    settings = get_settings()
    assert settings.scopus_search_count == 25
