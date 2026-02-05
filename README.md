# IF Dashboard (Scopus-powered)

A lightweight dashboard for tracking a **custom impact-factor style metric** and **immediacy factor** for a selected list of journals using the Scopus API.

## What this project computes

For a target year `Y`:

- **Custom Impact Factor (Y)**
  - **Numerator:** citations made in `Y` to all content published in `Y-1` and `Y-2` in a journal (all document types count in numerator contribution).
  - **Denominator:** count of citable items published in `Y-1` and `Y-2` where subtype is `article` or `review`.
  - Formula: `IF(Y) = citations_in_Y_to_items_from_(Y-1,Y-2) / citable_items_in_(Y-1,Y-2)`

- **Immediacy Factor (Y)**
  - Citations made in `Y` to items published in `Y`.
  - Formula: `Immediacy(Y) = citations_in_Y_to_items_from_Y / citable_items_in_Y`

The app also shows the exact item-level rows contributing to numerator and denominator.

## Architecture

- `if_dashboard/scopus.py`: Scopus API calls and parsing.
- `if_dashboard/storage.py`: SQLite cache to avoid API overuse (default refresh every 7 days).
- `if_dashboard/metrics.py`: metric calculations from normalized item records.
- `if_dashboard/app.py`: lightweight built-in HTTP dashboard (no external web framework required).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m if_dashboard.app
```

Then open http://127.0.0.1:8000.

## Configuration

Set in `.env`:

- `SCOPUS_API_KEY`
- `SCOPUS_INSTTOKEN` (optional, if your account requires it)
- `SCOPUS_BASE_URL` (defaults to Elsevier API)
- `CACHE_DB_PATH` (defaults to `./if_dashboard.db`)
- `CACHE_TTL_DAYS` (defaults to `7`)
- `PORT` (defaults to `8000`)

## Add your journals

Edit `journals.json` to provide your target journals (preloaded with your requested set):

```json
[
  {"name": "Journal Name", "issn": "1234-5678"}
]
```

## Notes on Scopus data

This implementation uses:

1. Search endpoint to fetch journal items by ISSN and publication year.
2. Citation-overview endpoint per item to extract **citations by year** (not total citation count).

If Scopus response schema differs for your subscription tier, update parser logic in `if_dashboard/scopus.py`.


## One-journal test call

To run a focused test against **Nature Reviews Gastroenterology & Hepatology** only:

```bash
python -m if_dashboard.test_call
```

You can also run it directly as a script:

```bash
python if_dashboard/test_call.py
```

Optional overrides:

```bash
python -m if_dashboard.test_call --issn 1759-5045 --year 2025
```

This prints item counts, impact/immediacy values, and API usage for that one test journal.


### If you get a 400 from Citation Overview

The client now prints the failing URL/path and the first part of Scopus error body to help debugging invalid parameters (for example, an invalid document identifier).

## API usage visibility

The dashboard now includes a **Scopus API Usage** card showing:

- API calls made for the current page load (cache misses).
- Cache hits for the current page load.
- Quota used/remaining/limit when Scopus returns `X-RateLimit-*` headers.

Note: Scopus does not report LLM-style "token" usage; this view reports request/quota usage instead.
