from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import time
import requests


class ScopusApiError(RuntimeError):
    """Raised for Scopus/Elsevier API errors."""


@dataclass(frozen=True)
class ElsevierScopusClient:
    api_key: str
    insttoken: Optional[str] = None
    base_url: str = "https://api.elsevier.com"
    timeout_s: int = 30
    max_retries: int = 4

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/json",
            "X-ELS-APIKey": self.api_key,
        }
        if self.insttoken:
            h["X-ELS-Insttoken"] = self.insttoken
        return h

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        GET a JSON response from Elsevier.

        Uses simple exponential backoff on HTTP 429 / 5xx.
        Raises ScopusApiError on non-2xx responses.
        """
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        params = dict(params or {})
        # Elsevier APIs also accept httpAccept as query param; we set for robustness.
        params.setdefault("httpAccept", "application/json")

        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                r = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout_s)
            except requests.RequestException as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(0.6 * (2 ** attempt))
                    continue
                raise ScopusApiError(f"Network error calling Elsevier API: {e}") from e

            # Rate limit / transient
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < self.max_retries:
                    retry_after = r.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(int(retry_after))
                    else:
                        time.sleep(0.8 * (2 ** attempt))
                    continue

            if 200 <= r.status_code < 300:
                try:
                    return r.json()
                except ValueError as e:
                    raise ScopusApiError(f"Non-JSON response from Elsevier API at {url}") from e

            # Non-success
            msg = _format_elsevier_error(r)
            raise ScopusApiError(msg)

        raise ScopusApiError(f"Failed calling Elsevier API after retries: {last_err}")


def _format_elsevier_error(r: requests.Response) -> str:
    url = r.url
    status = r.status_code
    try:
        data = r.json()
    except Exception:
        data = None

    # Elsevier sometimes wraps errors in service-error
    if isinstance(data, dict):
        svc = data.get("service-error") or data.get("serviceError") or data.get("error")
        if isinstance(svc, dict):
            # Try common shapes
            status_text = svc.get("status") or svc.get("statusText")
            message = svc.get("message") or svc.get("errorMessage") or svc.get("description")
            if status_text or message:
                return f"Elsevier API error {status} at {url}: {status_text or ''} {message or ''}".strip()

    # Fallback
    body = (r.text or "")[:500].strip().replace("\n", " ")
    return f"Elsevier API error {status} at {url}: {body}"
