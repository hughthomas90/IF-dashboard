from if_dashboard import test_call


def test_main_requires_api_key(monkeypatch, capsys):
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    code = test_call.main([])
    captured = capsys.readouterr()
    assert code == 1
    assert "SCOPUS_API_KEY is required" in captured.out


def test_default_issn_is_nature_reviews_gastro():
    assert test_call.DEFAULT_TEST_ISSN == "1759-5045"
