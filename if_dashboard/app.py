from __future__ import annotations

import html
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import get_settings
from .metrics import compute_impact_factor, compute_immediacy_factor
from .storage import CacheStore
from .scopus import ApiUsage, ScopusClient


def load_journals(path: str = "journals.json") -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def render_page(journals, selected_issn, selected_year, impact, immediacy, items, error, usage: ApiUsage):
    options = "".join(
        f'<option value="{html.escape(j["issn"])}" {"selected" if j["issn"] == selected_issn else ""}>{html.escape(j["name"])} ({html.escape(j["issn"])})</option>'
        for j in journals
    )
    rows = "".join(
        f"<tr><td>{html.escape(i.eid)}</td><td>{html.escape(i.title)}</td><td>{i.publication_year}</td><td>{html.escape(i.subtype)}</td><td>{i.citations_by_year.get(selected_year,0)}</td><td>{'Yes' if i.subtype in ['article','review'] else 'No'}</td></tr>"
        for i in items
    )
    impact_value = f"{impact.value:.3f}" if impact and impact.value is not None else "N/A"
    immed_value = f"{immediacy.value:.3f}" if immediacy and immediacy.value is not None else "N/A"
    error_html = f"<p style='color:#b00020'><strong>{html.escape(error)}</strong></p>" if error else ""

    quota_used = usage.quota_used if usage.quota_used is not None else "N/A"
    quota_remaining = usage.quota_remaining if usage.quota_remaining is not None else "N/A"
    quota_limit = usage.quota_limit if usage.quota_limit is not None else "N/A"

    usage_card = f"""
      <div class='card'>
        <h2>Scopus API Usage</h2>
        <p>API calls this page load: {usage.api_calls_made}</p>
        <p>Cache hits this page load: {usage.cache_hits}</p>
        <p>Quota used (from Scopus headers): {quota_used}</p>
        <p>Quota remaining (from Scopus headers): {quota_remaining}</p>
        <p>Quota limit (from Scopus headers): {quota_limit}</p>
      </div>
    """

    cards = usage_card
    if impact and immediacy:
        cards = f"""
        <div class='cards'>
          <div class='card'><h2>Custom Impact Factor ({impact.metric_year})</h2><p><strong>{impact_value}</strong></p><p>Numerator: {impact.numerator}</p><p>Denominator: {impact.denominator}</p></div>
          <div class='card'><h2>Immediacy Factor ({immediacy.metric_year})</h2><p><strong>{immed_value}</strong></p><p>Numerator: {immediacy.numerator}</p><p>Denominator: {immediacy.denominator}</p></div>
          {usage_card}
        </div>
        <h2>Numerator/Denominator contributions (item-level)</h2>
        <table><thead><tr><th>EID</th><th>Title</th><th>Year</th><th>Subtype</th><th>Citations in {selected_year}</th><th>Counts in Denominator?</th></tr></thead><tbody>{rows}</tbody></table>
        """

    return f"""<!doctype html><html><head><meta charset='utf-8'/><title>IF Dashboard</title><style>body{{font-family:Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{border:1px solid #ccc;padding:.5rem;text-align:left}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(200px,1fr));gap:1rem}}.card{{border:1px solid #ddd;padding:1rem;border-radius:8px}}</style></head><body><h1>Impact & Immediacy Dashboard (Scopus)</h1><form method='get'><label>Journal:</label><select name='issn'>{options}</select><label>Year:</label><input type='number' name='year' value='{selected_year}'/><button type='submit'>Refresh</button></form>{error_html}{cards}</body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        settings = get_settings()
        journals = load_journals()
        query = parse_qs(urlparse(self.path).query)
        year = int(query.get("year", [datetime.now().year])[0])
        selected_issn = query.get("issn", [journals[0]["issn"] if journals else ""])[0]

        impact = None
        immediacy = None
        items = []
        error = None
        usage = ApiUsage()

        if not settings.scopus_api_key:
            error = "SCOPUS_API_KEY is missing. Export it before running to fetch live data."
        elif selected_issn:
            try:
                cache = CacheStore(settings.cache_db_path, settings.cache_ttl_days)
                client = ScopusClient(settings.scopus_api_key, settings.scopus_base_url, cache, settings.scopus_insttoken)
                items = client.hydrate_items_with_citations(
                    issn=selected_issn,
                    years=[year - 2, year - 1, year],
                    citation_window_start=year - 2,
                    citation_window_end=year,
                )
                impact = compute_impact_factor(items, year)
                immediacy = compute_immediacy_factor(items, year)
                usage = client.usage
            except Exception as exc:  # noqa: BLE001
                error = f"Failed to load Scopus data: {exc}"

        content = render_page(journals, selected_issn, year, impact, immediacy, items, error, usage).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run_server() -> None:
    settings = get_settings()
    server = ThreadingHTTPServer(("0.0.0.0", settings.port), DashboardHandler)
    print(f"IF Dashboard running on http://127.0.0.1:{settings.port}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
