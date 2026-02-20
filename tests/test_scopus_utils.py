import pytest

from if_dashboard.scopus import ScopusClient


def test_extract_scopus_id_from_eid_suffix_digits():
    assert ScopusClient._extract_scopus_id("2-s2.0-85123456789") == "85123456789"


def test_extract_scopus_id_raises_for_invalid_eid():
    with pytest.raises(ValueError):
        ScopusClient._extract_scopus_id("invalid-eid")
