from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from if_dashboard.config import get_settings
from if_dashboard.metrics import compute_impact_factor, compute_immediacy_factor
from if_dashboard.scopus import ScopusClient
from if_dashboard.storage import CacheStore

DEFAULT_TEST_JOURNAL_NAME = "Nature Reviews Gastroenterology & Hepatology"
DEFAULT_TEST_ISSN = "1759-5045"


def load_journals(path: str = "journals.json") -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one focused Scopus test call for a single journal."
    )
    parser.add_argument("--issn", default=DEFAULT_TEST_ISSN)
    parser.add_argument("--name", default=DEFAULT_TEST_JOURNAL_NAME)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--journals-path", default="journals.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    if not settings.scopus_api_key:
        print("SCOPUS_API_KEY is required for test calls. Set it in your environment.")
        return 1

    journals = load_journals(args.journals_path)
    configured = next((j for j in journals if j.get("issn") == args.issn), None)
    journal_name = configured.get("name") if configured else args.name

    cache = CacheStore(settings.cache_db_path, settings.cache_ttl_days)
    client = ScopusClient(
        api_key=settings.scopus_api_key,
        base_url=settings.scopus_base_url,
        cache=cache,
        insttoken=settings.scopus_insttoken,
    )

    year = args.year
    items = client.hydrate_items_with_citations(
        issn=args.issn,
        years=[year - 2, year - 1, year],
        citation_window_start=year - 2,
        citation_window_end=year,
    )

    impact = compute_impact_factor(items, year)
    immediacy = compute_immediacy_factor(items, year)

    print(f"Journal: {journal_name} ({args.issn})")
    print(f"Year: {year}")
    print(f"Items fetched: {len(items)}")
    print(
        "Impact Factor => "
        f"numerator={impact.numerator}, denominator={impact.denominator}, value={impact.value}"
    )
    print(
        "Immediacy Factor => "
        f"numerator={immediacy.numerator}, denominator={immediacy.denominator}, value={immediacy.value}"
    )
    print(
        "Usage => "
        f"api_calls={client.usage.api_calls_made}, cache_hits={client.usage.cache_hits}, "
        f"quota_used={client.usage.quota_used}, quota_remaining={client.usage.quota_remaining}, "
        f"quota_limit={client.usage.quota_limit}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
