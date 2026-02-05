from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    scopus_api_key: str
    scopus_insttoken: str | None
    scopus_base_url: str
    cache_db_path: str
    cache_ttl_days: int
    port: int


def get_settings() -> Settings:
    return Settings(
        scopus_api_key=os.getenv("SCOPUS_API_KEY", ""),
        scopus_insttoken=os.getenv("SCOPUS_INSTTOKEN") or None,
        scopus_base_url=os.getenv("SCOPUS_BASE_URL", "https://api.elsevier.com"),
        cache_db_path=os.getenv("CACHE_DB_PATH", "./if_dashboard.db"),
        cache_ttl_days=int(os.getenv("CACHE_TTL_DAYS", "7")),
        port=int(os.getenv("PORT", "8000")),
    )
